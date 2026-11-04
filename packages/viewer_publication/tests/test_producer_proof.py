"""Gate 5: every pinned derived row names a current or compatible producer version."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets
from viewer_publication.producer_proof import require_producers

from congress_api.lake import captures as _captures

CURRENT = _captures.current_version()  # the producer record's commit must compute it


def with_mapping(spec, tmp_path, values):
    """Staged captures carry e1's mapping_version; replace it with the values under test."""
    table = pq.read_table(spec['captures']['path'])
    rows = table.num_rows
    column = pa.array((values * rows)[:rows], pa.string())
    index = table.schema.get_field_index('mapping_version')
    path = tmp_path / 'captures-mapped.parquet'
    pq.write_table(table.set_column(index, pa.field('mapping_version', pa.string()), column), path)
    return dict(spec, captures=dict(kind='parquet', path=str(path)))


def without_mapping(spec, tmp_path):
    """The v21 shape: captures written with no mapping_version column at all."""
    table = pq.read_table(spec['captures']['path'])
    path = tmp_path / 'captures-unmapped.parquet'
    pq.write_table(table.drop_columns(['mapping_version']), path)
    return dict(spec, captures=dict(kind='parquet', path=str(path)))


JOB = 'packages/congress_api/src/congress_api/lake/daily.py'  # registered for every table


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
    """The v21 captures, written by an unrecorded pyarrow writer, have no mapping_version."""
    with pytest.raises(ValueError, match='captures has no mapping_version column'):
        run(without_mapping(spec, tmp_path), tmp_path, 'absent')


def test_staged_captures_carry_the_current_mapping(spec, tmp_path):
    """Cluster e1's captures stage writes mapping_version; unmodified rows pass the row rule."""
    report = run(spec, tmp_path, 'staged')
    assert report['captures__mapping_version_null'] == 0 and report['captures__mapping_version_unknown'] == 0


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
    (lambda r: r['filename_readings'].update(job='not/a/checked-in/job.py'), "filename_readings: job 'not/a/checked-in/job.py' is not a producer registered"),
    # red-h2's probe: README.md as the job, an old commit, and version 99 were all accepted.
    (lambda r: r['captures'].update(job='README.md'), "captures: job 'README.md' is not a producer registered"),
    (lambda r: r['readings'].update(job='packages/congress_api/src/congress_api/cli/captures_ingest.py'), 'readings: job .* is not a producer registered'),
    (lambda r: r['captures'].update(version=99), 'captures: unknown producer record version 99'),
    (lambda r: r['captures'].update(commit=__import__('subprocess').run(['git', 'rev-parse', 'c9d70d6f'], capture_output=True, text=True).stdout.strip()),
     'captures: the code at c9d70d6f86de computes another version than the pinned rows carry'),
])
def test_snapshot_without_a_valid_producer_record_refuses(spec, tmp_path, change, rule):
    mapped = with_mapping(spec, tmp_path, [CURRENT])
    records = records_for(mapped)
    change(records)
    with pytest.raises(ValueError, match=rule):
        run(mapped, tmp_path, 'records', records=records)


def daily_chain(tmp_path, lineage, *, anchor_in_store=False):
    """An anchor import at snapshot 1, a daily record at 2 on it, a daily head at 3 on 2."""
    from congress_api.lake import meeting_records
    from congress_api.lake.producer_records import ProducerRecords, encode
    from viewer_publication.producer_proof import IMPORT
    metadata = tmp_path / 'm.metadata.json'
    metadata.write_text(json.dumps({'snapshots': [{'snapshot-id': s, 'parent-snapshot-id': p, 'summary': {'operation': o}}
                                                  for s, (p, o) in lineage.items()]}))
    pin = lambda s: {'kind': 'native_table', 'metadata_location': str(metadata), 'table_uuid': 'abcdef01', 'snapshot': s, 'schema_id': 0}
    origin = dict(version=1, input='meeting_records', selector={'kind': 'native_table', 'snapshot': 9}, job=JOB, commit=head())
    anchor = encode(dict(version=1, input='meeting_records', selector=pin(1), job=IMPORT, commit=head(), origin=dict(record=origin)))
    ledger = ProducerRecords({} if anchor_in_store else {'meeting_records': anchor}, root=tmp_path / 'ledger')
    if anchor_in_store:
        path = tmp_path / 'ledger/lake/producers/abcdef01/1.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(anchor)
    base = ledger.find('meeting_records', pin(1))[1]
    daily = lambda s, b, ref: dict(version=1, input='meeting_records', selector=pin(s), job=JOB, commit=head(),
                                   base=dict(selector=pin(b), record=ref))
    middle = ledger.write(daily(2, 1, base))
    model = {'meeting_records': pin(3), 'parser_versions': {'meeting_records': meeting_records.current_versions()}}
    return model, ledger, daily(3, 2, middle)


APPENDS = {3: (2, 'append'), 2: (1, 'append'), 1: (None, 'append')}


def test_a_daily_chain_back_to_a_checked_in_anchor_passes(tmp_path):
    from viewer_publication.producer_proof import snapshot_reasons
    model, ledger, record = daily_chain(tmp_path, APPENDS)
    assert snapshot_reasons(model, {'meeting_records': record}, ledger=ledger) == []


@pytest.mark.parametrize('lineage,change,rule', [
    ({3: (1, 'append'), 1: (None, 'append')}, None, 'base snapshot 2 is not an ancestor reached by appends only'),
    ({3: (2, 'overwrite'), 2: (1, 'append'), 1: (None, 'append')}, None, 'base snapshot 2 is not an ancestor reached by appends only'),
    (APPENDS, lambda r: r['base']['record'].update(sha256='0' * 64), 'the record of base snapshot 2 is missing or differs from its pin'),
    (APPENDS, lambda r: r['base']['selector'].update(table_uuid='other'), 'the base snapshot belongs to another table'),
    (APPENDS, lambda r: r.pop('base'), "no producer record|must name the base"),
    (APPENDS, lambda r: r['base'].update(selector=dict(r['base']['selector'], snapshot=None)), 'an empty base has no record'),
])
def test_a_broken_daily_chain_refuses(tmp_path, lineage, change, rule):
    from viewer_publication.producer_proof import snapshot_reasons
    model, ledger, record = daily_chain(tmp_path, lineage)
    if change is not None:
        change(record)
    reasons = snapshot_reasons(model, {'meeting_records': record}, ledger=ledger) or ['no producer record']
    assert len(reasons) == 1 and __import__('re').search(rule, reasons[0])


def test_an_import_in_the_chain_must_be_checked_in_and_the_chain_needs_its_store(tmp_path):
    from viewer_publication.producer_proof import snapshot_reasons
    model, ledger, record = daily_chain(tmp_path, APPENDS, anchor_in_store=True)
    assert snapshot_reasons(model, {'meeting_records': record}, ledger=ledger) == [
        'producer proof: meeting_records base 1: an import record in the chain must be checked in beside the publish spec']
    assert 'cannot be read without the producer record store' in snapshot_reasons(model, {'meeting_records': record})[0]


def test_an_import_record_passes_only_through_a_valid_origin():
    """Basin copies: the import's commit is checked, and the rows' versions through the origin."""
    from viewer_publication.producer_proof import IMPORT, snapshot_reasons
    from congress_api.lake import meeting_records
    selector = {'kind': 'native_table', 'metadata_location': 's3://x/m.json', 'table_uuid': 'u', 'snapshot': 1, 'schema_id': 0}
    model = {'meeting_records': selector, 'parser_versions': {'meeting_records': meeting_records.current_versions()}}
    origin = dict(version=1, input='meeting_records', selector={'kind': 'native_table', 'snapshot': 9}, job=JOB, commit=head())
    imported = lambda **o: {'meeting_records': dict(version=1, input='meeting_records', selector=selector, job=IMPORT, commit=head(), **o)}
    assert snapshot_reasons(model, imported(origin=dict(record=origin))) == []
    assert 'needs the origin record' in snapshot_reasons(model, imported())[0]
    assert 'origin: producing commit 000000000000 is not reachable' in snapshot_reasons(model, imported(origin=dict(record=dict(origin, commit='0' * 40))))[0]
    assert 'cannot name another import' in snapshot_reasons(model, imported(origin=dict(record=dict(origin, job=IMPORT))))[0]
