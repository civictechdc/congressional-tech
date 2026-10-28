"""F0 migration: declarative native jobs convert the retained legacy catalog."""
import json
from pathlib import Path

from congress_api.retention.provenance import (field as _field, list_of as _list,
    struct as _struct)
from viewer_publication.archive_fixture import build_fixture_release
from viewer_publication.archive_format import ROOT, EMPTY_STRINGS, _step, _normal, _execute, legacy_meeting_keys


def _match(expression, pattern):
    return f"array_element(regexp_match({expression},'{pattern}'),1)"


def committee_input(path):
    """Read the retained committee inventory through the native JSON reader."""
    path = Path(path)
    if path.suffix == '.parquet':
        return dict(name='committee_source', kind='parquet', path=str(path.resolve())), []
    schema = dict(fields=[_field('congress', 'Int64'), _field('committee', _struct(
        systemCode='Utf8', name='Utf8', chamber='Utf8', subcommittees=_list(_struct(systemCode='Utf8', name='Utf8'))))], metadata={})
    source = dict(name='committee_inventory', kind='json_lines',
        files=[dict(key='committee_inventory', path=str(path.resolve()))], schema=schema)
    steps = [_step('committee_candidates', """SELECT congress,committee['systemCode'] AS system_code,
        committee['name'] AS name,lower(committee['chamber']) AS chamber FROM committee_inventory
        UNION ALL SELECT congress,sub['systemCode'],sub['name'],lower(chamber) FROM
        (SELECT congress,committee['chamber'] AS chamber,unnest(committee['subcommittees']) AS sub FROM committee_inventory)"""),
        _step('committee_source', """SELECT system_code,name,chamber FROM (SELECT *,row_number() OVER
        (PARTITION BY system_code ORDER BY congress DESC NULLS LAST,name,chamber) AS rank FROM committee_candidates)
        WHERE rank=1 AND system_code IS NOT NULL""", materialize=True)]
    return source, steps


def convert_catalog(documents, filenames, captures, committees, *, catalog_id, output, scratch, engine):
    """Convert the pinned catalog pair, using engine joins, grouping and exports."""
    output, scratch = Path(output), Path(scratch)
    scratch.mkdir(parents=True, exist_ok=False)
    inputs = [dict(name=name, kind='parquet', path=str(Path(path).resolve())) for name, path in [
        ('legacy_documents', documents), ('legacy_filenames', filenames), ('legacy_captures', captures)]]
    committee, committee_steps = committee_input(committees)
    inputs.append(committee)
    raw_date = 'array_element(d.date_token,1)'
    date = f"CASE WHEN cardinality(d.date_token)=1 THEN try_cast(CASE WHEN regexp_like({raw_date},'^[0-9]{{8}}$') THEN concat(substr({raw_date},1,4),'-',substr({raw_date},5,2),'-',substr({raw_date},7,2)) ELSE {raw_date} END AS DATE) ELSE NULL END"
    body_hex = _match('d.body_key', '([0-9a-f]{64})')
    steps = committee_steps + [_step('body_metadata', """SELECT body_key,max(bytes) AS bytes,max(media_type) AS media_type
        FROM legacy_captures WHERE body_key IS NOT NULL GROUP BY body_key""", materialize=True, release_after=['legacy_captures']),
        _step('document_bodies', 'SELECT document_id,unnest(body_keys) AS body_key FROM legacy_documents'),
        _step('body_groups', f"SELECT document_id,array_agg({_match('body_key', '([0-9a-f]{64})')} ORDER BY body_key) AS bodies FROM document_bodies GROUP BY document_id", materialize=True),
        _step('document_codes', 'SELECT document_id,unnest(committee_code) AS code FROM legacy_documents'),
        _step('committee_aliases', """SELECT system_code,chamber,upper(system_code) AS code FROM committee_source
            UNION SELECT system_code,chamber,upper(substr(system_code,3)) AS code FROM committee_source
            UNION SELECT system_code,chamber,upper(substr(system_code,3,2)) AS code FROM committee_source
            WHERE lower(chamber)='house' AND right(system_code,2)='00'"""),
        _step('committee_groups', """SELECT d.document_id,array_agg(DISTINCT c.system_code ORDER BY c.system_code) AS committee_keys,
            array_agg(DISTINCT lower(c.chamber) ORDER BY lower(c.chamber)) AS chambers FROM document_codes d JOIN committee_aliases c
            ON upper(d.code)=c.code GROUP BY d.document_id""", materialize=True),
        _step('normalized', _normal('legacy_documents d LEFT JOIN body_metadata b ON d.body_key=b.body_key LEFT JOIN committee_groups c ON d.document_id=c.document_id LEFT JOIN body_groups g ON d.document_id=g.document_id',
            body_expected='d.body_key IS NOT NULL', doc_key='d.document_id', filename='d.filename', title='array_element(d.source_link_label,1)',
            source_url='d.source_url', body_hex=body_hex, format="lower(coalesce(array_element(d.format,1),'other'))",
            document_kind='d.document_kind', document_family='d.document_family', committee_keys='c.committee_keys', chambers='c.chambers',
            congress='CASE WHEN cardinality(d.congress)=1 THEN try_cast(array_element(d.congress,1) AS SMALLINT) ELSE NULL END',
            document_date=date, document_date_source=f"CASE WHEN {date} IS NULL THEN NULL ELSE 'filename' END",
            suffix="CASE WHEN regexp_like(d.body_key,'[.]pdf$') THEN '.pdf' WHEN regexp_like(d.body_key,'[.]gz$') THEN '.gz' ELSE '' END",
            media_type="coalesce(b.media_type,CASE WHEN array_element(d.format,1)='pdf' THEN 'application/pdf' ELSE 'application/octet-stream' END)",
            bytes='b.bytes', meeting_keys=legacy_meeting_keys('d.source_url'), link_bodies='g.bodies'), materialize=True, release_after=['body_metadata', 'body_groups', 'document_bodies', 'committee_groups', 'document_codes', 'committee_aliases']),
        _step('source_candidates', """SELECT f.document_id AS doc_key,f.source_id AS source_key,f.source_url AS url,
            cast(NULL AS VARCHAR) AS member_path,coalesce(f.body_key=d.body_key,false) AS is_saved,
            cast(NULL AS DATE) AS first_seen,
            array_element(f.source_page_url,1) AS listed_on,array_element(f.source_link_label,1) AS link_text,
            cast(NULL AS VARCHAR) AS doc_type,cast(NULL AS DATE) AS posted
            FROM legacy_filenames f JOIN (SELECT document_id,body_key FROM legacy_documents) d ON f.document_id=d.document_id
            WHERE f.source_url IS NOT NULL"""),
        _step('source_input', """SELECT doc_key,min(source_key) AS source_key,url,member_path,
            bool_or(is_saved) AS is_saved,min(first_seen) AS first_seen,min(listed_on) AS listed_on,
            min(link_text) AS link_text,min(doc_type) AS doc_type,min(posted) AS posted
            FROM source_candidates GROUP BY doc_key,url,member_path""", materialize=True, release_after=['source_candidates', 'legacy_documents', 'legacy_filenames']),
        _step('recovery_input', """SELECT cast(NULL AS VARCHAR) AS doc_key,cast(NULL AS VARCHAR) AS recovery_key,
            cast(NULL AS VARCHAR) AS original_url,cast(NULL AS VARCHAR) AS kind,arrow_cast(NULL,'FixedSizeBinary(32)') AS body,
            cast(NULL AS VARCHAR) AS suffix,cast(NULL AS BIGINT) AS bytes,cast(NULL AS DATE) AS imported_at,
            cast(NULL AS VARCHAR) AS recovered_url,cast(NULL AS VARCHAR) AS identity_note WHERE false"""),
        _step('meeting_input', 'SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS chamber,cast(NULL AS VARCHAR) AS title,cast(NULL AS DATE) AS meeting_date WHERE false'),
        _step('committee_input', 'SELECT system_code,name,lower(chamber) AS chamber FROM committee_source'),
    ]
    return _execute(inputs, steps, output=output, scratch=scratch, engine=engine,
        origin=dict(kind='converted_catalog', catalog_id=catalog_id, gaps=[
            'Converted catalog fixture; old grouping and classifications are retained',
            'Fetch and import dates are not reconstructed from legacy timestamps',
            'Format alternates, meeting titles, recovery kinds and member paths are unavailable',
            'Metadata-only legacy rows have no saved body, bytes or body link',
            'Capture scheduling is disabled']))


def main():
    import argparse
    from docspec_client.client import NativeDatasets

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--scratch', required=True, type=Path)
    modes = parser.add_subparsers(dest='mode', required=True)
    hand = modes.add_parser('fixture')
    hand.add_argument('--input', type=Path, default=ROOT / 'model/fixtures/hand-release.json')
    catalog = modes.add_parser('catalog')
    for name in ['documents', 'filenames', 'captures', 'committees']:
        catalog.add_argument('--' + name, type=Path, required=True)
    catalog.add_argument('--catalog-id', required=True)
    args = parser.parse_args()
    common = dict(output=args.output, scratch=args.scratch, engine=NativeDatasets.from_config(args.runtime))
    if args.mode == 'fixture':
        result = build_fixture_release(args.input, **common)
    else:
        result = convert_catalog(args.documents, args.filenames, args.captures, args.committees,
                                 catalog_id=args.catalog_id, **common)
    print(json.dumps(dict(release_id=result['release_id'], files=result['files'])))


if __name__ == '__main__':
    main()
