"""Native metadata definitions, release availability, and publication checks."""
from copy import deepcopy
import os

import pytest

from viewer_publication.archive_format import DETAIL_COLUMNS, LIST_COLUMNS
from viewer_publication.archive_schema import (REFERENCE, build_schema, field_types,
    publication_checks, render_reference, validate_schema)


def test_reference_matches_registry_and_nested_paths_are_explicit():
    schema = build_schema()
    assert REFERENCE.read_text() == render_reference(schema)
    tables = {f['name'].removesuffix('.parquet'): f for f in schema['files']}
    assert len(tables) == 22
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


def test_upstream_relations_name_only_stated_generations():
    schema = build_schema(['list.parquet'], entity_digests={'bill-family': 'a' * 64})
    relations = {r['id']: r for r in schema['upstream_relations']}
    assert relations['bill_actions']['available'] and relations['bill_actions']['generation'] == 'a' * 64
    assert relations['bill_actions']['path'] == f"generations/bill-family/{'a' * 64}/bill_actions.parquet"
    assert not relations['member_votes']['available'] and 'path' not in relations['member_votes']
    assert 'generation' not in relations['member_votes']
    unpinned = build_schema(['list.parquet'])
    assert not any(r['available'] or 'path' in r for r in unpinned['upstream_relations'])
    assert 'available' not in build_schema()['upstream_relations'][0]


def test_detail_declares_the_keyed_document_table():
    schema = build_schema()
    tables = {t['name']: t for t in schema['files']}
    detail, listed = tables['detail.parquet'], tables['list.parquet']
    assert detail['identity']['fields'] == ['link_key'] and detail['identity']['kind'] == 'primary_key'
    assert [c['name'] for c in detail['columns']] == [*DETAIL_COLUMNS, *LIST_COLUMNS]
    assert detail['columns'][len(DETAIL_COLUMNS):] == listed['columns']
    assert 'link_key' not in {c['name'] for c in listed['columns']}
    assert [c['name'] for c in detail['virtual_columns']] == ['list_row']  # document_detail still pairs by position.
    bad = deepcopy(schema)
    next(r for r in bad['relationships'] if r['id'] == 'document_detail')['target']['fields'] = ['package_id']
    with pytest.raises(ValueError, match='unique key'):
        validate_schema(bad)


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
    assert recipes['bill_hearing_transcripts']['available']  # meeting subjects work without bills.
    assert not recipes['committee_roster']['available']
    sparse = build_schema(['list.parquet', 'detail.parquet'], registry=original)
    transcripts = next(r for r in sparse['recipes'] if r['id'] == 'bill_hearing_transcripts')
    assert not transcripts['available'] and transcripts['missing_tables'] == ['meetings']
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
        ('details', "SELECT 0 AS list_row,'missing-link' AS link_key UNION ALL SELECT 1,'missing-link'"),
            ('source_rows', "SELECT cast(NULL AS VARCHAR) AS url"),
        ('links', "SELECT 0 AS list_row,'present-link' AS link_key"),
        ('members_export', "SELECT 'A000001' AS bioguide_id UNION ALL SELECT 'A000001' UNION ALL SELECT cast(NULL AS VARCHAR)"),
        ('meetings_export', "SELECT cast(118001 AS BIGINT) AS event_id,make_array(named_struct('list_row',99)) AS transcripts"),
        ('witnesses_export', "SELECT 'present-witness' AS witness_key"),
    ]]
    schema = build_schema()
    for table in schema['files']:  # This fixture writes only the columns it checks.
        for column in table['columns']:
            column['nullable'] = not (table['name'], column['name']) in {('sources.parquet', 'url'), ('members.parquet', 'bioguide_id')}
    result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
                     queries=publication_checks(schema, {'members', 'meetings', 'witnesses'}))
    assert result['relationship_invariants'] == [dict(missing_primary_link=2, duplicate_document_key=1, null_sources_url=1, null_members_bioguide_id=1, invalid_members_key=2,
        invalid_meetings_key=0, invalid_witnesses_key=0, missing_document_meeting=2,
        missing_transcript_document=1, missing_document_witness=1)]


def test_every_registry_column_declares_nullability():
    schema = build_schema()
    for table in schema['files']:
        assert table['nullability'], table['name']
        assert all(isinstance(column['nullable'], bool) for column in table['columns']), table['name']
    tables = {t['name'].removesuffix('.parquet'): t for t in schema['files']}
    required = lambda name: {c['name'] for c in tables[name]['columns'] if not c['nullable']}
    # Data model §8.1 spot checks: types stated without "nullable" are required.
    assert {'url', 'is_saved', 'list_row', 'ordinal'} <= required('sources')
    assert {'filename', 'format', 'date_kind', 'saved_kind', 'hidden'} <= required('list')
    assert 'title' not in required('list') and 'member_path' not in required('sources')
    # Phase-2 annex §3: types stated without "nullable" are required.
    assert {'chamber', 'name', 'names'} <= required('committees')
    assert 'description' in required('nominations') and 'cross_ids' in required('members')
    assert {'source_locator', 'context_key', 'record_sha'} <= required('witnesses')
    assert {'basis', 'count'} <= required('meeting_coverage')


@pytest.mark.parametrize('mutation,expected', [
    (lambda s: s['files'][0]['columns'][0].pop('nullable'), 'without a boolean nullable'),
    (lambda s: s['files'][0]['columns'][0].update(nullable='no'), 'without a boolean nullable'),
    (lambda s: s['files'][0].pop('nullability'), 'nullability basis'),
])
def test_column_without_nullable_is_refused(mutation, expected):
    schema = build_schema()
    mutation(schema)
    with pytest.raises(ValueError, match=expected):
        validate_schema(schema)


def test_non_null_column_without_relation_is_refused():
    schema = build_schema()
    # Published but neither core nor auxiliary: the old code skipped its checks silently.
    with pytest.raises(ValueError, match='no export relation: members.bioguide_id'):
        publication_checks(schema, set(), published=['list.parquet', 'members.parquet'])
    # An unpublished table writes nothing, so it has nothing to check.
    assert publication_checks(schema, set(), published=['list.parquet'])
    sql = publication_checks(schema, set(), published=['list.parquet'])[0]['sql']
    for core in ['ordered WHERE "filename"', 'details WHERE "link_key"', 'links WHERE "list_row"',
                 'url_keys WHERE "lookup_key"', 'source_rows WHERE "url"', 'recovery_rows WHERE "body"']:
        assert core in sql


def test_output_footers_cannot_silently_drift_from_reference_types(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from viewer_publication.archive_schema import validate_parquet_fields
    path = tmp_path/'members.parquet'
    pq.write_table(pa.table({'bioguide_id': [1]}), path)
    with pytest.raises(ValueError, match='members.bioguide_id'):
        validate_parquet_fields(build_schema(), [path])


def test_null_in_declared_list_column_refuses_before_manifest(tmp_path):
    """Injected defect: the model emits a NULL filename; the writing job refuses it."""
    import json
    import shutil
    from pathlib import Path
    from archive_job_fixture import real_model_spec
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import build_release
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes
    spec, _, _ = real_model_spec(tmp_path)
    broken = tmp_path / 'broken-root'
    for relative in _definition_hashes(ROOT):
        target = broken / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    sql = broken / 'model/sql/document-normalized.sql'
    text = sql.read_text()
    assert 's.filename,a.title' in text
    sql.write_text(text.replace('s.filename,a.title', 'cast(NULL AS VARCHAR) AS filename,a.title', 1))
    output = tmp_path / 'release'
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        with pytest.raises(ValueError, match='Release key invariant failed'):
            build_release(**{name: spec[name]['path'] for name in ['captures', 'readings', 'filename_readings']},
                parser_versions=spec['parser_versions'], catalog_version=spec['catalog_version'],
                engine=engine, output=output, scratch=tmp_path / 'model', root=broken)
    assert not (output / 'manifest.json').exists()
    reports = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    assert reports['relationship_invariants'][0]['null_list_filename'] == 1
