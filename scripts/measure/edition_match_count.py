"""Count edition-equal rendition members from pinned canonical model relations.

This measurement does not build or widen rendition groups. The model owner
supplies pre-exclusion real-body membership and the completed text fingerprints.
All joins, deduplication and counts run in the native engine.
"""
import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import re
import sys

from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets
import pyarrow.parquet as pq

RELATIONS = {'rendition_members', 'edition_bodies', 'fingerprint_candidates', 'fingerprints'}
KINDS = {'same_stem', 'publisher'}
DIGEST = re.compile('[a-f0-9]{64}')
BODY_KEY_FROM_SHA = (
    "CASE WHEN body_sha IS NOT NULL AND regexp_match(body_sha,'^[a-f0-9]{64}$') IS NOT NULL "
    "THEN concat('bodies/sha256/',substr(body_sha,1,2),'/',body_sha,'.gz') ELSE body_sha END AS body_key"
)


def pinned_inputs(path):
    path = Path(path).resolve()
    value = json.loads(path.read_text())
    if value.get('version') != 1 or value.get('relation_basis') != 'canonical_model':
        raise ValueError('A version-1 canonical model relation descriptor is required')
    for key in ['source_sql_sha256', 'profile_sha256']:
        if not isinstance(value.get(key), str) or not DIGEST.fullmatch(value[key]):
            raise ValueError('Descriptor must pin source SQL and profile digests')
    if not value.get('snapshots') or not all(isinstance(item, str) and item for item in value['snapshots'].values()):
        raise ValueError('Descriptor must identify exact source snapshots')
    if set(value.get('coverage', {})) != KINDS or any(item not in {'complete', 'pending'} for item in value['coverage'].values()):
        raise ValueError('Descriptor must state same-stem and publisher coverage')
    if set(value.get('relations', {})) != RELATIONS:
        raise ValueError('A required canonical relation is missing')
    inputs = []
    for name in sorted(RELATIONS):
        pin = value['relations'][name]
        source = (path.parent / pin['path']).resolve()
        if source.suffix != '.parquet' or not source.is_file():
            raise ValueError('Canonical relation missing: ' + name)
        if not isinstance(pin.get('sha256'), str) or not DIGEST.fullmatch(pin['sha256']):
            raise ValueError('Relation digest is required: ' + name)
        with source.open('rb') as stream:
            if file_digest(stream, 'sha256').hexdigest() != pin['sha256']:
                raise ValueError('Relation digest differs: ' + name)
        inputs.append(dict(name=name, kind='parquet', path=str(source)))
    return value, inputs


def measure(descriptor, *, engine, work):
    source, raw_inputs = pinned_inputs(descriptor)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    inputs, shim_steps = [], []
    columns = {
        'rendition_members': f'group_kind,group_id,{BODY_KEY_FROM_SHA}',
        'edition_bodies': BODY_KEY_FROM_SHA,
        'fingerprint_candidates': BODY_KEY_FROM_SHA,
        'fingerprints': f'{BODY_KEY_FROM_SHA},fingerprint',
    }
    for item in raw_inputs:
        names = set(pq.read_schema(item['path']).names)
        if 'body_key' not in names and 'body_sha' in names:
            raw = 'raw_' + item['name']
            inputs.append({**item, 'name': raw})
            shim_steps.append((item['name'], f"SELECT {columns[item['name']]} FROM {raw}", False))
        else:
            inputs.append(item)
    # One row per group/fingerprint avoids a candidate × reference-body join.
    # Work is linear in memberships plus hash joins/distinct grouping, with
    # O(E log E) sorting for deterministic examples; repeated groups count once.
    definitions = shim_steps + [
        ('fp', 'SELECT body_key,min(fingerprint) AS fingerprint FROM fingerprints GROUP BY body_key', True),
        ('reference_groups', '''SELECT DISTINCT m.group_kind,m.group_id,m.body_key
            FROM rendition_members m JOIN edition_bodies e ON m.body_key=e.body_key''', True),
        ('group_status', '''SELECT r.group_kind,r.group_id,
            count(*) FILTER(WHERE f.fingerprint IS NULL) AS missing_references
            FROM reference_groups r LEFT JOIN fp f ON r.body_key=f.body_key GROUP BY r.group_kind,r.group_id''', False),
        ('reference_fingerprints', '''SELECT r.group_kind,r.group_id,f.fingerprint,min(r.body_key) AS reference_body
            FROM reference_groups r JOIN fp f ON r.body_key=f.body_key WHERE f.fingerprint IS NOT NULL
            GROUP BY r.group_kind,r.group_id,f.fingerprint''', False),
        ('candidate_groups', '''SELECT DISTINCT m.group_kind,m.group_id,m.body_key
            FROM rendition_members m JOIN group_status g ON m.group_kind=g.group_kind AND m.group_id=g.group_id
            LEFT ANTI JOIN fingerprint_candidates c ON m.body_key=c.body_key''', True),
        ('evaluated_groups', '''SELECT c.group_kind,c.group_id,c.body_key,f.fingerprint,r.reference_body,
            (f.fingerprint IS NULL OR g.missing_references>0) AS has_unknown
            FROM candidate_groups c JOIN group_status g ON c.group_kind=g.group_kind AND c.group_id=g.group_id
            LEFT JOIN fp f ON c.body_key=f.body_key
            LEFT JOIN reference_fingerprints r ON c.group_kind=r.group_kind AND c.group_id=r.group_id
                AND f.fingerprint=r.fingerprint''', True),
        ('candidate_results', '''SELECT body_key,bool_or(reference_body IS NOT NULL) AS matched,
            bool_or(has_unknown) AS has_unknown FROM evaluated_groups GROUP BY body_key''', True),
    ]
    steps = [dict(name=name, sql=sql, materialize=materialize) for name, sql, materialize in definitions]
    validation = '''SELECT
        (SELECT count(*) FROM (SELECT body_key FROM rendition_members UNION ALL SELECT body_key FROM edition_bodies
            UNION ALL SELECT body_key FROM fingerprint_candidates UNION ALL SELECT body_key FROM fingerprints) keys
            WHERE body_key IS NULL OR regexp_match(body_key,'^bodies/sha256/[a-f0-9]{2}/[a-f0-9]{64}[.]gz$') IS NULL) AS invalid_body_keys,
        (SELECT count(*) FROM (SELECT body_key FROM fingerprints GROUP BY body_key
            HAVING count(DISTINCT coalesce(fingerprint,'<missing>'))>1)) AS conflicting_fingerprints,
        (SELECT count(*) FROM fingerprints WHERE fingerprint IS NOT NULL
            AND regexp_match(fingerprint,'^[a-f0-9]{64}$') IS NULL) AS invalid_fingerprints,
        (SELECT count(*) FROM rendition_members WHERE group_kind IS NULL OR group_id IS NULL OR body_key IS NULL
            OR group_kind NOT IN ('same_stem','publisher')) AS invalid_members,
        (SELECT count(*) FROM edition_bodies e LEFT ANTI JOIN fingerprint_candidates c ON e.body_key=c.body_key) AS invalid_editions'''
    counts = '''SELECT count(*) AS eligible_candidates,
        count(*) FILTER(WHERE matched) AS matching_candidates,
        count(*) FILTER(WHERE NOT matched AND has_unknown) AS unknown_candidates,
        count(*) FILTER(WHERE NOT matched AND NOT has_unknown) AS known_nonmatching_candidates FROM candidate_results'''
    outputs = [parquet_output(work, 'matching-examples', '''SELECT group_kind,group_id,body_key,reference_body,fingerprint
        FROM evaluated_groups WHERE reference_body IS NOT NULL ORDER BY group_kind,body_key,group_id LIMIT 25''',
        ['group_kind','body_key','group_id'])]
    result = run_job(work, engine, inputs=inputs, steps=steps, outputs=outputs,
        queries=[dict(name='validation',sql=validation), dict(name='counts',sql=counts),
                 dict(name='unknown_examples',sql='''SELECT body_key FROM candidate_results WHERE NOT matched AND has_unknown ORDER BY body_key LIMIT 25''')])
    if any(result['validation'][0].values()):
        raise ValueError('Canonical relation invariant failed: ' + json.dumps(result['validation'][0], sort_keys=True))
    counts = result['counts'][0]
    ready = counts['unknown_candidates'] == 0 and all(item == 'complete' for item in source['coverage'].values())
    receipt = dict(version=1, status='complete' if ready else 'incomplete', decision_ready=ready,
        **counts, source=source, unknown_examples=result['unknown_examples'],
        descriptor_sha256=sha256(Path(descriptor).read_bytes()).hexdigest())
    (work / 'measurement.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--relations', type=Path, required=True)
    parser.add_argument('--engine-config', type=Path, default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    if not args.engine_config:
        parser.error('An explicitly pinned local engine config is required')
    try:
        result = measure(args.relations, engine=NativeDatasets.from_config(args.engine_config), work=args.work)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Edition count refused: ' + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0 if result['decision_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
