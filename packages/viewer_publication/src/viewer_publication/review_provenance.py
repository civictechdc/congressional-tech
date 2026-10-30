"""One-time native conversion of the pinned, published assistant kind reviews
and interactive document review form provenance recording.
"""
from hashlib import sha256
import json
from pathlib import Path
import re

from congress_api.retention.provenance import (
    VERDICTS,file_pin,finish_stage,instant,json_input,list_of,parquet_output,parquet_records,
    record_review,run_job,stage_records,struct,timestamp_key,validate_provenance,
)
from viewer_publication.filename_review_binding import pinned_reviews,validate_identities

SUPPORTED_FORMS = frozenset({'amendment', 'biography', 'committee-memorandum',
    'committee-print', 'committee-vote', 'legislative-text', 'letter',
    'member-statement', 'opening-statement', 'press-release',
    'testimony-disclosure', 'witness-list', 'witness-statement'})
_BODY_KEY_RE = re.compile(r'^bodies/sha256/([0-9a-f]{2})/([0-9a-f]{64})(?:\.(?:gz|pdf))?$')


def resolve_review_target(target):
    """Normalize a 16-hex link key, 64-hex SHA-256, raw body key, or original_url to a 16-hex target key."""
    if not isinstance(target, str):
        raise ValueError('Invalid review target')
    if re.fullmatch(r'[0-9a-f]{16}', target):
        return target
    if re.fullmatch(r'[0-9a-f]{64}', target):
        return target[:16]
    match = _BODY_KEY_RE.fullmatch(target)
    if match and match.group(1) == match.group(2)[:2]:
        return match.group(2)[:16]
    if target.startswith(('http://', 'https://', 'url:')):
        raw_url = target[4:] if target.startswith('url:') else target
        if not raw_url:
            raise ValueError('Invalid review target')
        return sha256(('url:' + raw_url).encode('utf-8')).hexdigest()[:16]
    raise ValueError('Invalid review target')


def build_review_verdict(form, *, default_decided_at=None, default_reviewer=None, require_supported_forms=False):
    """Convert an interactive review form submission into a schema-validated provenance record."""
    if not isinstance(form, dict):
        raise ValueError('Review form submission must be a mapping')
    raw_target = (
        form.get('target')
        or form.get('link_key')
        or form.get('body_key')
        or form.get('body_sha256')
        or form.get('sha256')
        or form.get('original_url')
    )
    target = resolve_review_target(raw_target)
    verdict = form.get('verdict')
    value = form.get('value')
    if verdict is None:
        forms = form.get('observed_forms') or form.get('observed_document_forms')
        if forms is None and ('primary_forms' in form or 'component_forms' in form):
            forms = list(form.get('primary_forms') or []) + list(form.get('component_forms') or [])
        if forms is not None:
            verdict = 'kind_override'
            value = list(forms)
    if verdict not in VERDICTS:
        raise ValueError('Invalid review target or verdict')
    if verdict == 'kind_override':
        if value is None:
            forms = form.get('observed_forms') or form.get('observed_document_forms') or (
                list(form.get('primary_forms') or []) + list(form.get('component_forms') or [])
            )
            value = list(forms) if forms is not None else None
        if (not isinstance(value, list) or not value
                or any(not isinstance(item, str) or not item for item in value)
                or len(set(value)) != len(value)):
            raise ValueError('Invalid review value')
        if require_supported_forms and not set(value) <= SUPPORTED_FORMS:
            raise ValueError('Unsupported document review form')
    elif verdict == 'duplicate_of' and isinstance(value, str):
        value = resolve_review_target(value)
    decided_at = form.get('decided_at') if form.get('decided_at') is not None else default_decided_at
    reviewer = form.get('reviewer') if form.get('reviewer') is not None else default_reviewer
    note = form.get('note') if 'note' in form else form.get('notes')
    record = dict(
        id=form.get('id'),
        target=target,
        verdict=verdict,
        value=value,
        note=note,
        reviewer=reviewer,
        decided_at=decided_at,
        supersedes=form.get('supersedes'),
    )
    return validate_provenance('reviews', record)


def _read_verdict_inputs(source):
    if isinstance(source, (str, Path)):
        path = Path(source)
        text = path.read_text(encoding='utf-8').strip()
        if not text:
            raise ValueError('Empty review verdict input')
        if text.startswith('['):
            rows = json.loads(text)
        elif text.startswith('{') and '\n' not in text:
            parsed = json.loads(text)
            rows = parsed['records'] if isinstance(parsed, dict) and isinstance(parsed.get('records'), list) else [parsed]
        else:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return rows, dict(verdicts=file_pin(path))
    return list(source), {}


def stage_interactive_reviews(verdicts, *, output, decided_at, reviewer=None, require_supported_forms=False):
    """Validate interactive review form verdicts and stage provenance/reviews/ JSONL records."""
    instant(decided_at)
    raw_rows, inputs = _read_verdict_inputs(verdicts)
    if not raw_rows:
        raise ValueError('Empty review verdict batch')
    records = [
        validate_provenance(
            'reviews',
            build_review_verdict(
                row,
                default_decided_at=decided_at,
                default_reviewer=reviewer,
                require_supported_forms=require_supported_forms,
            ),
        )
        for row in raw_rows
    ]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    key, count = stage_records(output, 'reviews', records, decided_at=decided_at)
    return finish_stage(output, kind='reviews', provenance=key, records=count, inputs=inputs)


stage_review_verdicts = stage_interactive_reviews


def record_interactive_verdict(store, form, *, decided_at=None, reviewer=None, timestamp=None,
                               require_supported_forms=False):
    """Validate one interactive review form verdict and write it to provenance/reviews/."""
    record = validate_provenance(
        'reviews',
        build_review_verdict(
            form,
            default_decided_at=decided_at,
            default_reviewer=reviewer,
            require_supported_forms=require_supported_forms,
        ),
    )
    stamp = timestamp if timestamp is not None else timestamp_key(record['decided_at'])
    key = record_review(store, record, timestamp=stamp)
    return dict(key=key, record=record)


record_review_verdict = record_interactive_verdict


def stage_reviews(reviews,descriptor,identities,*,output,engine,decided_at):
    instant(decided_at)
    reviews,descriptor,identities=map(Path,(reviews,descriptor,identities))
    pin=json.loads(descriptor.read_text())
    published=pinned_reviews(reviews,pin)
    identity=validate_identities(json.loads(identities.read_text()),pin)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    jobs=output/'jobs';jobs.mkdir()
    inputs=[json_input(jobs,'published',
        (dict(position=index,**row) for index,row in enumerate(published['rows'])),
        position='Int64',document_id='Utf8',status='Utf8',
        selected=struct(document_kind=list_of('Utf8')),
        review=struct(body_observation=struct(sha256='Utf8',notes='Utf8'))),
        json_input(jobs,'identities',identity['rows'],index='Int64',document_id='Utf8',body_key='Utf8')]
    steps=[dict(name='review_join',materialize=True,sql='''SELECT p.*,i.body_key,
        substr(i.body_key,18,64) AS body_hex FROM published p
        JOIN identities i ON p.position=i."index" AND p.document_id=i.document_id''')]
    # Both metadata inputs are pinned before interpolation; only the explicit
    # timestamp needs SQL quoting. Selected values remain native list columns.
    stamp=decided_at.replace("'","''")
    source=pin['sha256']
    sql=f'''SELECT '{source}:' || cast(position AS VARCHAR) AS id,
        substr(body_hex,1,16) AS target,'kind_override' AS verdict,
        selected.document_kind AS value,
        coalesce(review.body_observation.notes,'') || '\nPublished selection: ' || status ||
            '; publication {source}; review {pin['review_sha256']}' AS note,
        'assistant' AS reviewer,'{stamp}' AS decided_at,cast(NULL AS VARCHAR) AS supersedes
        FROM review_join'''
    queries=[dict(name='invariants',sql=f'''SELECT
        (SELECT count(*) FROM review_join) AS matched,
        (SELECT count(*) FROM review_join WHERE (NOT regexp_like(body_key,'^bodies/sha256/[a-f0-9]{{2}}/[a-f0-9]{{64}}[.]gz$'))
            OR (substr(body_key,15,2)<>substr(body_hex,1,2))
            OR (review.body_observation.sha256 IS DISTINCT FROM body_hex)
            OR (coalesce(array_length(selected.document_kind),0)=0)) AS invalid,
        (SELECT count(*) FROM (SELECT substr(body_hex,1,16) FROM review_join
            GROUP BY substr(body_hex,1,16) HAVING count(*)>1)) AS duplicate_targets''')]
    reports=run_job(jobs,engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(output,'reviews',sql,['id'])],queries=queries)
    invariant=reports['invariants'][0]
    if invariant!={'matched':pin['groups'],'invalid':0,'duplicate_targets':0}:
        raise ValueError('Published reviews do not bind one-to-one to their exact bodies')
    key,count=stage_records(output,'reviews',parquet_records(output/'reviews.parquet'),decided_at=decided_at)
    return finish_stage(output,kind='reviews',provenance=key,records=count,
        inputs=dict(reviews=file_pin(reviews),descriptor=file_pin(descriptor),identities=file_pin(identities)))



def main(argv=None):
    import argparse
    from docspec_client.client import NativeDatasets
    parser=argparse.ArgumentParser(description=__doc__)
    source_group=parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--reviews',type=Path)
    source_group.add_argument('--verdicts',type=Path,help='Interactive review form verdicts JSON or JSONL')
    parser.add_argument('--descriptor',type=Path,default=Path(__file__).resolve().parent/'data/document-review-publication.json')
    parser.add_argument('--identities',type=Path,default=Path(__file__).resolve().parent/'data/document-review-identities.json')
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--decided-at',required=True,help='Explicit migration decision timestamp, with timezone')
    parser.add_argument('--reviewer',default=None,help='Default reviewer identity for interactive verdicts')
    parser.add_argument('--require-supported-forms',action='store_true')
    parser.add_argument('--native-config',type=Path)
    args=parser.parse_args(argv)
    if args.verdicts is not None:
        result=stage_interactive_reviews(
            args.verdicts,
            output=args.stage,
            decided_at=args.decided_at,
            reviewer=args.reviewer,
            require_supported_forms=args.require_supported_forms,
        )
    else:
        if args.native_config is None:
            parser.error('--native-config is required when staging published --reviews')
        result=stage_reviews(args.reviews,args.descriptor,args.identities,output=args.stage,
            engine=NativeDatasets.from_config(args.native_config),decided_at=args.decided_at)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
