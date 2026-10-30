"""Native metadata definitions, release availability, and publication checks."""
from copy import deepcopy
import os

import pytest

from viewer_publication.archive_schema import (REFERENCE, build_schema, field_types,
    publication_checks, render_reference, validate_schema)


def test_reference_matches_registry_and_nested_paths_are_explicit():
    schema = build_schema()
    assert REFERENCE.read_text() == render_reference(schema)
    tables = {f['name'].removesuffix('.parquet'): f for f in schema['files']}
    assert len(tables) == 17
    assert tables['rosters']['identity']['fields'] == ['congress', 'system_code', 'bioguide_id']
    assert tables['urls']['identity']['scope'] == 'release'
    assert field_types(tables['members'])['cross_ids.fec[]'] == 'string'
    assert field_types(tables['bills'])['amendments[].sponsor_bioguide_id'] == 'dict'
    # Every nested collection/struct either has explicit explanatory notes or
    # relationship endpoints. Embedded values must not turn into inferred keys.
    for name, table in tables.items():
        covered = set(table.get('notes', {}))
        covered.update(path for r in schema['relationships'] for endpoint in (r['source'], r['target'])
                       if endpoint.get('table') == name for path in endpoint['fields'])
        for path, kind in field_types(table).items():
            if kind.startswith(('list<', 'struct<')):
                assert any(p == path or p.startswith(path + '[]') or p.startswith(path + '.') for p in covered), (name, path)


def test_release_availability_keeps_unavailable_definitions_and_identity():
    original = build_schema()
    published = build_schema(['list.parquet', 'detail.parquet', 'meetings.parquet'], registry=original)
    assert 'available' not in original['files'][0]
    relations = {r['id']: r for r in published['relationships']}
    assert relations['document_detail']['available']
    assert relations['witness_submitted_documents']['missing_tables'] == ['witnesses']
    assert not relations['witness_submitted_documents']['available']
    recipes = {r['id']: r for r in published['recipes']}
    assert recipes['bill_documents']['available']  # list keys work without bills.
    assert not recipes['committee_roster']['available']
    assert published['schema_version'] == 1 and published['relationships_version'] == 1


@pytest.mark.parametrize('mutation,expected', [
    (lambda s: s['relationships'][0]['source'].update(fields=['not_a_field']), 'Unknown field path'),
    (lambda s: s['relationships'][0]['target'].update(table='absent'), 'Unknown relationship table'),
    (lambda s: s['relationships'].append(deepcopy(s['relationships'][0])), 'Duplicate relationship'),
    (lambda s: next(r for r in s['relationships'] if r['id']=='document_meetings').update(match='equal'), 'Incompatible join types'),
    (lambda s: next(r for r in s['relationships'] if r['id']=='bill_sponsor')['target'].update(fields=['name']), 'unique key'),
    (lambda s: next(r for r in s['relationships'] if r['id']=='meeting_committees')['source'].update(fields=['committees.system_code']), 'Unknown field path'),
    (lambda s: next(t for t in s['files'] if t['name']=='members.parquet')['identity'].update(fields=['terms']), 'scalar row fields'),
    (lambda s: next(t for t in s['files'] if t['name']=='members.parquet')['columns'][0].update(nullable=True), 'Nullable primary key'),
    (lambda s: s['recipes'][0]['requires'].append('absent'), 'Unknown recipe dependency'),
    (lambda s: next(t for t in s['files'] if t['name']=='search.parquet')['engine_fields'].update(title='absent'), 'Unknown engine field column'),
])
def test_invalid_metadata_is_rejected(mutation, expected):
    schema = build_schema()
    mutation(schema)
    with pytest.raises(ValueError, match=expected):
        validate_schema(schema)


def test_native_checks_detect_duplicates_nulls_and_missing_nested_targets(tmp_path):
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    steps = [dict(name=name, sql=sql) for name, sql in [
        ('ordered', "SELECT 0 AS list_row,make_array('999','not-a-number') AS meeting_keys,make_array('missing-witness') AS witness_keys"),
        ('details', "SELECT 0 AS list_row,'missing-link' AS link_key"),
        ('links', "SELECT 0 AS list_row,'present-link' AS link_key"),
        ('members_export', "SELECT 'A000001' AS bioguide_id UNION ALL SELECT 'A000001' UNION ALL SELECT cast(NULL AS VARCHAR)"),
        ('meetings_export', "SELECT cast(118001 AS BIGINT) AS event_id,make_array(named_struct('list_row',99)) AS transcripts"),
        ('witnesses_export', "SELECT 'present-witness' AS witness_key"),
    ]]
    result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
                     queries=publication_checks(build_schema(), {'members', 'meetings', 'witnesses'}))
    assert result['relationship_invariants'] == [dict(missing_primary_link=1, invalid_members_key=2,
        invalid_meetings_key=0, invalid_witnesses_key=0, missing_document_meeting=2,
        missing_transcript_document=1, missing_document_witness=1)]


def test_output_footers_cannot_silently_drift_from_reference_types(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from viewer_publication.archive_schema import validate_parquet_fields
    path = tmp_path/'members.parquet'
    pq.write_table(pa.table({'bioguide_id': [1]}), path)
    with pytest.raises(ValueError, match='members.bioguide_id'):
        validate_parquet_fields(build_schema(), [path])
