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
    assert len(tables) == 28
    assert tables['caption_resources']['identity']['fields'] == ['video_key','track_body','ordinal']
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


def test_release_publishes_kind_synonyms_for_readers_to_filter_as_one():
    """ct-isnv: the House guide titles one type 'Written Witness Testimony or Witness Statement'.
    The site and the MCP read this from each release's schema.json and filter the words as one kind.
    Owner, 2026-11-11: add the pairs that mean the same thing on real documents, the House guide's word
    first (investigation govinfo-synonyms-20261111): a committee's markup amendment, and a biography of
    someone appearing before the committee; and, by the owner's choice, a Member's opening statement and
    a committee's transcript (a printed hearing labelled transcript is tagged published-hearing instead).
    Words that are broader or name another publication stay apart."""
    listed = next(t for t in build_schema(['list.parquet']) ['files'] if t['name'] == 'list.parquet')
    assert listed['synonyms'] == {'document_kind[]': [['witness-statement', 'testimony'], ['committee-amendment', 'amendment'],
                                                      ['witness-biography', 'biography'], ['member-statement', 'opening-statement'],
                                                      ['committee-transcript', 'transcript']]}
    assert 'synonyms' not in next(t for t in build_schema()['files'] if t['name'] == 'detail.parquet')


def _synonyms(schema, value):
    next(t for t in schema['files'] if t['name'] == 'list.parquet')['synonyms'] = value


@pytest.mark.parametrize('mutation,expected', [
    (lambda s: _synonyms(s, {'not_a_field[]': [['a', 'b']]}), 'Unknown synonym field'),
    (lambda s: _synonyms(s, {'document_kind[]': [['testimony']]}), 'Invalid synonyms'),
    (lambda s: _synonyms(s, {'document_kind[]': [['testimony', '']]}), 'Invalid synonyms'),
    (lambda s: _synonyms(s, {'document_kind[]': [['testimony', 'testimony']]}), 'Invalid synonyms'),
    (lambda s: _synonyms(s, {'document_kind[]': [['witness-statement', 'testimony'], ['testimony', 'statement']]}), 'Invalid synonyms'),
    (lambda s: _synonyms(s, {'document_kind[]': 'testimony'}), 'Invalid synonyms'),
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


def test_native_checks_refuse_a_witness_key_map_that_breaks_its_own_rules(tmp_path):
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    row = "SELECT '{}' AS old_key,{} AS witness_key,'{}' AS status,{} AS basis,{} AS candidate_keys,'meeting:1' AS occasion,'congress_gov' AS source"
    none, empty = "arrow_cast(NULL,'Utf8')", "arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')"
    rows = [
        row.format('old-1', "'current'", 'unambiguous', "'content'", empty),  # sound
        row.format('old-2', none, 'ambiguous', "'content'", "make_array('current','other')"),  # sound
        row.format('old-3', none, 'unresolved', none, empty),  # sound
        row.format('current', "'current'", 'unambiguous', "'content'", empty),  # an old key that is still published
        row.format('old-4', "'gone'", 'unambiguous', "'locator'", empty),  # a successor that is not published
        row.format('old-5', none, 'ambiguous', "'content'", "make_array('current','vanished')"),  # a candidate that is not
        row.format('old-6', "'current'", 'ambiguous', "'content'", "make_array('current','other')"),  # ambiguous yet chosen
        row.format('old-7', none, 'unresolved', "'content'", empty),  # unresolved with a basis
    ]
    steps = [dict(name='ordered', sql="SELECT 0 AS list_row,arrow_cast(make_array(),'List(Utf8)') AS witness_keys"),
             dict(name='details', sql="SELECT 0 AS list_row,cast(NULL AS VARCHAR) AS link_key"),
             dict(name='links', sql="SELECT 0 AS list_row,'present-link' AS link_key"),
             dict(name='witnesses_export', sql="SELECT 'current' AS witness_key UNION ALL SELECT 'other'"),
             dict(name='witness_key_map_export', sql=' UNION ALL '.join(rows))]
    schema = build_schema()
    schema['files'] = [t for t in schema['files'] if t['name'] in ('witnesses.parquet', 'witness_key_map.parquet')]
    for column in schema['files'][0]['columns']:  # This fixture writes only the witness key.
        column['nullable'] = column['name'] != 'witness_key'
    result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
                     queries=publication_checks(schema, {'witnesses', 'witness_key_map'}, keyed_documents=False))
    found = result['relationship_invariants'][0]
    # 'current' counts twice, as the old key and as its own successor; 'gone' and 'vanished' once each.
    assert {k: found[k] for k in ('misplaced_witness_key_map_key', 'inconsistent_witness_key_map',
                                  'invalid_witness_key_map_key')} == dict(
        misplaced_witness_key_map_key=4, inconsistent_witness_key_map=2, invalid_witness_key_map_key=0)


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
    assert 'cross_ids' in required('members')
    # Military promotion lists have no description upstream (17 in 448651e7, all military PNs).
    assert 'description' not in required('nominations')
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
    for relation, table, column in [('ordered', 'list', 'filename'), ('details', 'detail', 'link_key'),
            ('links', 'links', 'list_row'), ('url_keys', 'urls', 'lookup_key'),
            ('source_rows', 'sources', 'url'), ('recovery_rows', 'recoveries', 'body')]:
        assert f'count(*) FILTER (WHERE "{column}" IS NULL) AS null_{table}_{column}' in sql
        assert f'FROM {relation}' in sql


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
    named = "CASE WHEN coalesce(s.filename,'')='' THEN coalesce(x.filename,s.filename) ELSE s.filename END AS filename,"
    assert named in text
    sql.write_text(text.replace(named, 'cast(NULL AS VARCHAR) AS filename,', 1))
    output = tmp_path / 'release'
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        with pytest.raises(ValueError, match='Release key invariant failed'):
            build_release(**{name: spec[name]['path'] for name in ['captures', 'readings', 'filename_readings']},
                parser_versions=spec['parser_versions'], catalog_version=spec['catalog_version'],
                engine=engine, output=output, scratch=tmp_path / 'model', root=broken)
    assert not (output / 'manifest.json').exists()
    reports = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    assert reports['relationship_invariants'][0]['null_list_filename'] == 1


def test_key_uniqueness_reuses_only_matching_native_export_order():
    schema=build_schema()
    fields={'member_votes':['vote_id','member_key']}
    checked=publication_checks(schema,{'member_votes'},keyed_documents=False,ordered_keys=fields)[0]['sql']
    assert 'cast(0 AS BIGINT) AS invalid_member_votes_key' in checked
    assert 'member_votes_export GROUP BY' not in checked
    assert 'count(*) FILTER (WHERE "vote_id" IS NULL) AS null_member_votes_vote_id' in checked
    fallback=publication_checks(schema,{'member_votes'},keyed_documents=False,ordered_keys={'member_votes':['vote_id','member_key','position']})[0]['sql']
    assert 'member_votes_export GROUP BY "vote_id","member_key"' in fallback


@pytest.mark.parametrize('empty', [False, True])
def test_required_column_counts_preserve_each_null_total_and_empty_exports(tmp_path, empty):
    from congress_api.retention.provenance import run_job
    from docspec_client.client import NativeDatasets
    schema = build_schema()
    schema['files'] = [t for t in schema['files'] if t['name'] == 'sources.parquet']
    for column in schema['files'][0]['columns']:
        column['nullable'] = column['name'] not in {'url', 'ordinal'}
    rows = "SELECT cast(NULL AS VARCHAR) AS url,cast(NULL AS BIGINT) AS ordinal UNION ALL SELECT 'valid',NULL UNION ALL SELECT 'other',2"
    steps = [dict(name='source_rows', sql=f'SELECT * FROM ({rows})' + (' WHERE false' if empty else '')),
        dict(name='details', sql="SELECT cast(NULL AS VARCHAR) AS link_key WHERE false"),
        dict(name='links', sql="SELECT 'present' AS link_key WHERE false")]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
            queries=publication_checks(schema, set()))
    assert result['relationship_invariants'] == [dict(missing_primary_link=0, duplicate_document_key=0,
        null_sources_url=0 if empty else 1, null_sources_ordinal=0 if empty else 2)]
