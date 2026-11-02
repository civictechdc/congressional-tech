"""Gate 5: every pinned derived row names a current or compatible producer version."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from viewer_publication.producer_proof import require_producers

CURRENT = 'm' * 64


def with_mapping(spec, tmp_path, values):
    """Until cluster e1 stages mapping_version, the fixture adds the column by hand."""
    table = pq.read_table(spec['captures']['path'])
    rows = table.num_rows
    column = pa.array((values * rows)[:rows], pa.string())
    path = tmp_path / 'captures-mapped.parquet'
    pq.write_table(table.append_column('mapping_version', column), path)
    return dict(spec, captures=dict(kind='parquet', path=str(path)))


JOB = 'packages/congress_api/src/congress_api/cli/captures_ingest.py'


def head():
    import subprocess
    return subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True,
                          cwd=os.path.dirname(__file__)).stdout.strip()


def records_for(spec, **override):
    return {name: dict(dict(version=1, input=name, selector=spec[name], job=JOB, commit=head()), **override)
            for name in ('captures', 'readings', 'filename_readings') if spec.get(name) is not None}


def run(spec, tmp_path, name, records=None):
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        return require_producers(spec, engine=engine, work=tmp_path / name, mapping_current=CURRENT,
                                 records=records_for(spec) if records is None else records)


@pytest.fixture(scope='module')
def spec(tmp_path_factory):
    return real_model_spec(tmp_path_factory.mktemp('producer'))[0]


def test_valid_record_passes(spec, tmp_path):
    report = run(with_mapping(spec, tmp_path, [CURRENT]), tmp_path, 'ok')
    assert report['captures__mapping_version_null'] == 0 and report['captures__mapping_version_unknown'] == 0
    assert report['readings__parser_version_null'] == 0 and report['readings__other_versions_retained'] == 0


@pytest.mark.parametrize('value,rule', [(None, 'captures.mapping_version is NULL'),
                                         ('u' * 64, 'neither the current mapping nor registered compatible')])
def test_null_or_unknown_mapping_refuses_and_names_the_rule(spec, tmp_path, value, rule):
    with pytest.raises(ValueError, match=rule):
        run(with_mapping(spec, tmp_path, [value]), tmp_path, 'bad')


def test_captures_without_the_column_refuse(spec, tmp_path):
    """Today's staged captures (pre-e1) and the v21 captures have no mapping_version."""
    with pytest.raises(ValueError, match='captures has no mapping_version column'):
        run(spec, tmp_path, 'absent')


def test_registered_compatible_mapping_passes(spec, tmp_path, monkeypatch):
    import viewer_publication.producer_proof as module
    registry = tmp_path / 'compatible.json'
    registry.write_text(json.dumps(dict(version=1, entries=[dict(parser='captures', version='o' * 64, current=CURRENT)])))
    monkeypatch.setattr(module, 'REGISTRY', registry)
    monkeypatch.setattr(module.compatible, '__kwdefaults__', {'registry': registry})
    run(with_mapping(spec, tmp_path, [CURRENT, 'o' * 64]), tmp_path, 'compatible')


def test_null_reading_version_refuses_and_old_versions_are_only_reported(spec, tmp_path):
    readings = pq.read_table(spec['readings']['path'])
    rows = readings.to_pylist()
    old = dict(rows[0], parser_version='0' * 64)
    path = tmp_path / 'readings-history.parquet'
    pq.write_table(pa.Table.from_pylist(rows + [old], schema=readings.schema), path)
    mapped = with_mapping(spec, tmp_path, [CURRENT])
    report = run(dict(mapped, readings=dict(kind='parquet', path=str(path))), tmp_path, 'history')
    assert report['readings__other_versions_retained'] == 1
    nulls = readings.schema.set(readings.schema.get_field_index('parser_version'), pa.field('parser_version', pa.string()))
    path = tmp_path / 'readings-null.parquet'
    pq.write_table(pa.Table.from_pylist(rows + [dict(rows[0], parser_version=None)], schema=nulls), path)
    with pytest.raises(ValueError, match='readings: 1 rows: row carries no producer version'):
        run(dict(mapped, readings=dict(kind='parquet', path=str(path))), tmp_path, 'null')


@pytest.mark.parametrize('change,rule', [
    (lambda r: r.pop('captures'), 'captures: no producer record'),
    (lambda r: r['captures'].update(selector={'kind': 'parquet', 'path': '/elsewhere.parquet'}), 'captures: the producer record names another selector'),
    (lambda r: r['readings'].update(commit='0' * 40), 'readings: producing commit 000000000000 is not reachable from HEAD'),
    (lambda r: r['filename_readings'].update(job='not/a/checked-in/job.py'), "filename_readings: job 'not/a/checked-in/job.py' is not a file checked in"),
])
def test_snapshot_without_a_valid_producer_record_refuses(spec, tmp_path, change, rule):
    mapped = with_mapping(spec, tmp_path, [CURRENT])
    records = records_for(mapped)
    change(records)
    with pytest.raises(ValueError, match=rule):
        run(mapped, tmp_path, 'records', records=records)
