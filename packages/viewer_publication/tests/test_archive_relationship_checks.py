"""Plant domain-reference defects in the current DDK-generated native checks.

The full query and its field/key bindings are covered by test_archive_catalog.
These bounded jobs exercise the native relationship expressions on independent
wrong-value cases without a second schema registry or definition validator.
"""
import json
import os
from pathlib import Path

import duckdb
import pytest


@pytest.fixture(scope='module')
def catalog():
    from ddk.catalog import assemble_catalog
    from viewer_publication.archive_relationships import ArchiveRelationshipProfileV1

    root = Path(__file__).parents[3]
    result = assemble_catalog(root/'model/ddk/project.ddk.json', permitted_roots=[root],
                              relationship_profile=ArchiveRelationshipProfileV1())
    assert result.report['decision'] == 'passed', result.local_report
    return result


def selected_report(catalog, auxiliary, names):
    from viewer_publication.archive_catalog import publication_checks

    reports, _ = publication_checks(catalog, auxiliary, [name+'.parquet' for name in auxiliary])
    report, = reports
    sql = report['sql']
    with duckdb.connect(config={'enable_external_access': False, 'threads': 1}) as parser:
        parsed = json.loads(parser.execute('SELECT json_serialize_sql(?)', [sql]).fetchone()[0])
    assert not parsed['error']
    expressions = parsed['statements'][0]['node']['select_list']
    # Use parser offsets to select exact original SQL; never translate its dialect.
    offsets = [item['query_location'] for item in expressions] + [len(sql)]
    fragments = {item['alias']: sql[start:end].rstrip().removesuffix(',')
                 for item, start, end in zip(expressions, offsets, offsets[1:])}
    return dict(name=report['name'], sql='SELECT '+',\n'.join(fragments[name] for name in names))


def test_native_checks_detect_missing_nested_targets(tmp_path, catalog):
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
    names = ('missing_primary_link', 'missing_document_meeting', 'missing_transcript_document', 'missing_document_witness')
    result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
                     queries=[selected_report(catalog, {'meetings', 'witnesses'}, names)])
    assert result['relationship_invariants'] == [dict(missing_primary_link=2,
        missing_document_meeting=2, missing_transcript_document=1, missing_document_witness=1)]


def test_native_checks_refuse_a_witness_key_map_that_breaks_its_own_rules(tmp_path, catalog):
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
    names = ('misplaced_witness_key_map_key', 'inconsistent_witness_key_map')
    result = run_job(tmp_path, engine, inputs=[], steps=steps, outputs=[],
                     queries=[selected_report(catalog, {'witnesses', 'witness_key_map'}, names)])
    # 'current' counts twice: an old key is also its own published successor.
    # Missing 'gone' and 'vanished' successors contribute one failure each.
    assert result['relationship_invariants'] == [dict(misplaced_witness_key_map_key=4,
                                                     inconsistent_witness_key_map=2)]


def test_shared_saved_document_key_has_no_converter_exception(catalog):
    report=selected_report(catalog,{'detail'},('duplicate_document_key',))
    with duckdb.connect(config={'enable_external_access':False,'threads':1}) as db:
        db.execute('CREATE SCHEMA outputs')
        db.execute('CREATE TABLE outputs."detail.parquet" (link_key VARCHAR)')
        db.execute("INSERT INTO outputs.\"detail.parquet\" VALUES ('same-body'),('same-body'),(NULL),(NULL)")
        assert db.execute(report['sql']).fetchone()==(1,)
        db.execute('DELETE FROM outputs."detail.parquet" WHERE link_key IS NOT NULL')
        assert db.execute(report['sql']).fetchone()==(0,)
