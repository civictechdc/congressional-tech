"""Gate 5 records for the heads a daily run moves (ct-ud0b)."""
import json
import subprocess

import pytest

from congress_api.lake import daily
from congress_api.lake.producer_records import DAILY_JOB, ProducerRecords, appended_from, encode, identity, key_for
from test_daily_producers import native_fixture

HEAD = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
WRITER = dict(job=DAILY_JOB, commit=HEAD, lockfile_digest='b' * 64)
PIN = dict(metadata_location='/m.json', table_uuid='01a1a36c-dac3-70d3-94aa-f571c0017da8', snapshot=7, schema_id=0)


@pytest.fixture
def clean_tree(monkeypatch):
    monkeypatch.setattr(daily, 'writer_identity', lambda root, job: dict(WRITER, job=job))


def test_a_record_is_written_once_and_found_by_its_snapshot(tmp_path):
    records = ProducerRecords(root=tmp_path)
    record = dict(version=1, input='captures', selector=dict(kind='native_table', **PIN), job=DAILY_JOB)
    reference = records.write(record)
    assert reference == dict(key=key_for(PIN), **identity(encode(record)))
    assert records.write(record) == reference
    with pytest.raises(ValueError, match='Another producer record already names this snapshot'):
        records.write(dict(record, job='other'))
    assert records.find('captures', PIN) == (record, reference)
    assert records.find('captures', dict(PIN, snapshot=8)) is None


def test_a_checked_in_anchor_is_found_before_the_store(tmp_path):
    anchor = encode(dict(version=1, input='captures', selector=dict(kind='native_table', **PIN)))
    records = ProducerRecords({'captures': anchor}, root=tmp_path)
    assert records.find('captures', PIN)[1] == dict(anchor='captures', **identity(anchor))
    assert records.find('captures', dict(PIN, snapshot=8)) is None


def test_lineage_accepts_only_an_append_path_to_the_base():
    lineage = {3: (2, 'append'), 2: (1, 'append'), 1: (None, 'append'), 9: (1, 'overwrite')}
    assert appended_from(lineage, 3, 1) and appended_from(lineage, 3, None) and appended_from(lineage, 1, 1)
    assert not appended_from(lineage, 1, 3)
    assert not appended_from(lineage, 9, 1)
    assert not appended_from(lineage, 4, 1)


def test_daily_records_each_head_it_moves_and_chains_the_next_run(tmp_path, clean_tree):
    value, engine, store = native_fixture(tmp_path, 2)
    records = ProducerRecords(root=tmp_path / 'ledger')
    first = daily.produce_daily(dict(value, receipt_inventory=value['receipt_inventory'][:1]), engine=engine,
                                raw_store=store, producer_records=records)
    assert first['status'] == 'completed' and set(first['producers']) == set(first['pins'])
    for name, pin in first['pins'].items():
        record, reference = records.find(name, pin)
        assert reference == first['producers'][name]
        assert record['job'] == DAILY_JOB and record['commit'] == HEAD and record['input'] == name
        base = record['base']
        assert base['record'] is None and base['selector']['snapshot'] is None
        assert base['selector']['table_uuid'] == pin['table_uuid']
    second = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store,
                                 producer_records=records)
    assert second['status'] == 'completed' and 'captures' in second['producers']
    record, _ = records.find('captures', second['pins']['captures'])
    assert record['base'] == dict(selector=dict(kind='native_table', **first['pins']['captures']),
                                  record=first['producers']['captures'])
    third = daily.produce_daily(dict(value, work=str(tmp_path / 'third')), engine=engine, raw_store=store,
                                producer_records=records)
    assert third['status'] == 'completed' and third['producers'] == {}


def test_daily_refuses_before_appending_onto_a_head_without_a_record(tmp_path, clean_tree):
    value, engine, store = native_fixture(tmp_path, 2)
    first = daily.produce_daily(dict(value, receipt_inventory=value['receipt_inventory'][:1]), engine=engine, raw_store=store)
    result = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store,
                                 producer_records=ProducerRecords(root=tmp_path / 'ledger'))
    assert result['status'] == 'producer_unrecorded'
    assert result['producers'] == dict(missing=['captures', 'filename_readings', 'readings'])
    assert not (tmp_path / 'second/captures').exists()
    from congress_api.lake import tables
    heads = tables.resolve_tables(engine=engine, work=tmp_path / 'heads', catalog_root=value['catalog_root'], tables=value['tables'])
    assert heads == first['pins']


def test_daily_refuses_from_an_unclean_checkout_before_any_append(tmp_path, monkeypatch):
    def unclean(root, job):
        raise ValueError('Raw receipt writers require a clean application tree')
    monkeypatch.setattr(daily, 'writer_identity', unclean)
    value, engine, store = native_fixture(tmp_path)
    result = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=ProducerRecords(root=tmp_path / 'ledger'))
    assert result['status'] == 'producer_unrecorded' and 'clean application tree' in result['producers']['unavailable']
    assert not (tmp_path / 'work/captures').exists()


def test_a_run_that_stops_after_appending_still_records_its_heads(tmp_path, clean_tree):
    from pyarrow import parquet as pq
    value, engine, store = native_fixture(tmp_path)
    item = pq.read_table(value['body_inventory']).to_pylist()[0]
    (tmp_path / 'raw' / item['relative_path']).unlink()
    records = ProducerRecords(root=tmp_path / 'ledger')
    result = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert result['status'] == 'pending' and set(result['producers']) == {'captures'}


def test_gate_five_accepts_the_chain_a_daily_run_wrote(tmp_path, clean_tree):
    from viewer_publication.producer_proof import find_records, snapshot_reasons
    value, engine, store = native_fixture(tmp_path, 2)
    records = ProducerRecords(root=tmp_path / 'ledger')
    daily.produce_daily(dict(value, receipt_inventory=value['receipt_inventory'][:1]), engine=engine, raw_store=store,
                        producer_records=records)
    second = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store,
                                 producer_records=records)
    versions = second['currentversions']
    model = dict({name: dict(pin, kind='native_table') for name, pin in second['pins'].items()},
                 parser_versions=dict(versions['parsers']), catalog_version=versions['filename_readings'])
    found = find_records(model, records, {})
    assert snapshot_reasons(model, found, mapping_current=versions['captures'], ledger=records) == []
    # Planted: the first night's captures record replaced in the store; the chain must refuse.
    first_key = json.loads(encode(found['captures']))['base']['record']['key']
    (tmp_path / 'ledger' / first_key).write_text(json.dumps(dict(json.loads((tmp_path / 'ledger' / first_key).read_text()),
                                                                 lockfile_digest='c' * 64)))
    assert snapshot_reasons(model, found, mapping_current=versions['captures'], ledger=records) == [
        'producer proof: captures: the record of base snapshot '
        f"{found['captures']['base']['selector']['snapshot']} is missing or differs from its pin"]
