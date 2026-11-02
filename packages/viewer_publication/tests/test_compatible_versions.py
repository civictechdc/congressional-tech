"""Compatible versions need a proof, select without duplicates, and raw duplicates are rejected first."""
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import run_job
from docspec_client.client import NativeDatasets
from viewer_publication import compatible_versions as cv

PROOF = dict(rows=5, columns=3, differences=0, only_old=0, only_new=0)


def entry(**more):
    return dict(dict(parser='html', version='old', current='new', predicate_sql='true', reason='lock pin only', proof=PROOF), **more)


@pytest.fixture
def engine():
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as value:
        yield value


def test_committed_registry_is_valid():
    assert cv.load_registry(current={}) == []


@pytest.mark.parametrize('bad,message', [
    (entry(proof=None), 'differential proof'),
    (entry(proof=dict(PROOF, rows=0)), 'compared nothing'),
    (entry(proof=dict(PROOF, differences=1)), 'found differences'),
    (entry(proof=dict(PROOF, only_new=1)), 'found differences'),
    (entry(current='older'), 'superseded pin'),
    (entry(predicate_sql='true; DROP'), 'semicolon'),
    (entry(version='new'), 'compatible with itself'),
])
def test_unproved_or_stale_entries_are_refused(bad, message):
    with pytest.raises(ValueError, match=message):
        cv.validate_entries([bad], current=dict(html='new'))


def test_an_empty_registry_renders_nothing():
    assert cv.render_compatible([], parser='html', input_name='readings') == ''
    assert cv.render_compatible([entry(parser='xml')], parser='html', input_name='readings') == ''


def selected(tmp_path, engine, rows, entries):
    """Pins plus the rendered rows, over rows of (body_sha, parser_version, value, flag)."""
    path = tmp_path / 'readings.parquet'
    pq.write_table(pa.Table.from_pylist(rows), path)
    sql = "SELECT r.* FROM readings r WHERE r.parser_version='new'" + cv.render_compatible(entries, parser='html', input_name='readings')
    result = run_job(tmp_path / 'select', engine, inputs=[dict(name='readings', kind='parquet', path=str(path))], steps=[], outputs=[],
        queries=[dict(name='rows', sql=sql + ' ORDER BY body_sha')])
    return [(row['body_sha'], row['parser_version']) for row in result['rows']]


def test_current_row_wins_and_the_predicate_limits_older_rows(tmp_path, engine):
    rows = [dict(body_sha='a', parser_version='old', flag=True), dict(body_sha='a', parser_version='new', flag=True),
            dict(body_sha='b', parser_version='old', flag=True), dict(body_sha='c', parser_version='old', flag=False),
            dict(body_sha='d', parser_version='ancient', flag=True)]
    assert selected(tmp_path, engine, rows, [entry(predicate_sql='r.flag')]) == [('a', 'new'), ('b', 'old')]


def test_preflight_rejects_an_injected_duplicate_primary_key(tmp_path, engine):
    good = tmp_path / 'good.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha='a', parser='html', parser_version='v'), dict(body_sha='a', parser='xml', parser_version='v')]), good)
    assert cv.preflight(engine=engine, work=tmp_path / 'ok', inputs=dict(readings=good)) == dict(readings=0)
    bad = tmp_path / 'bad.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha='a', parser='html', parser_version='v')] * 2), bad)
    with pytest.raises(ValueError, match='duplicated before selection'):
        cv.preflight(engine=engine, work=tmp_path / 'dup', inputs=dict(readings=bad))


def test_the_differential_reads_every_row_and_column_both_ways(tmp_path, engine, monkeypatch):
    from congress_api.lake import tables
    schema = dict(fields=[dict(name=n) for n in ('filename', 'source_url', 'catalog_version', 'status', 'error_type')])
    monkeypatch.setattr(tables, 'load_schema', lambda name: schema)
    def write(name, rows):
        path = tmp_path / f'{name}.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([(c, pa.string()) for c in ('filename', 'source_url', 'catalog_version', 'status', 'error_type')])), path)
        return path
    base = [dict(filename=f'{i}.pdf', source_url='u', catalog_version='old', status='completed', error_type=None) for i in range(3)]
    same = [dict(row, catalog_version='new') for row in base]
    def run(new, work, **more):
        return cv.prove_unchanged(engine=engine, work=tmp_path / work, name='filename_readings', old=write('old', base), new=write(work, new), version_column='catalog_version', **more)
    assert run(same, 'same') == (dict(rows=3, columns=2, differences=0, only_old=0, only_new=0), {})
    changed = [dict(same[0], error_type='x'), *same[1:]]
    assert run(changed, 'changed') == (dict(rows=3, columns=2, differences=1, only_old=0, only_new=0), {'error_type': 1})
    assert run(same[:2], 'lost')[0]['only_old'] == 1
    assert run([*same, dict(same[0], filename='9.pdf')], 'extra')[0]['only_new'] == 1
