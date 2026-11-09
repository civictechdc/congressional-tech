"""Gate 5 records for the heads a daily run moves (ct-ud0b)."""
from hashlib import sha256
import json
import subprocess

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import compatible_versions, daily, readings, tables
from congress_api.lake.producer_records import DAILY_JOB, ProducerRecords, appended_from, encode, identity, key_for
from congress_api.retention.provenance import file_pin, import_unreadable, run_job
from congress_api.retention.provenance_inventory import unreadable_inventory
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


def _failing_final_reads(monkeypatch, failures):
    """The final head read fails `failures` times as nightly 20261108T193702Z's did; earlier reads work."""
    from types import SimpleNamespace
    from docspec_client.models import DocSpecFailure
    real, waits = tables.resolve_tables, []

    def resolve(*, work, **kwargs):
        if work.name.startswith('producer-heads') and failures:
            failures.pop()
            raise DocSpecFailure(['docspec'], SimpleNamespace(returncode=1, stdout='',
                stderr='iceberg: Unexpected => client error (Connect): operation timed out'))
        return real(work=work, **kwargs)
    monkeypatch.setattr(tables, 'resolve_tables', resolve)
    monkeypatch.setattr(daily, 'SLEEP', waits.append)
    return waits


def _failing_owed_marks(monkeypatch, status, keys=None):
    """Owed-record writes that set `status` fail (only at `keys`, when given); the rest go through."""
    from congress_api.lake.producer_records import owed_key
    real, failed = ProducerRecords.owe, []

    def owe(self, intent, version):
        key = owed_key(intent['base']['selector'])
        if intent['owed']['status'] == status and (keys is None or key in keys):
            failed.append(key)
            raise OSError('storage unavailable')
        return real(self, intent, version)
    monkeypatch.setattr(ProducerRecords, 'owe', owe)
    return failed


def _heads(engine, value, work):
    return tables.resolve_tables(engine=engine, work=work, catalog_root=value['catalog_root'], tables=value['tables'])


def _owed_at(records, pin, snapshot):
    """The owed record a run left for this table when it started from `snapshot` (None: empty)."""
    return records.owed(dict(table_uuid=pin['table_uuid'], snapshot=snapshot))


def test_a_transient_final_head_failure_is_retried_and_the_records_written(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    waits = _failing_final_reads(monkeypatch, [1])
    result = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert result['status'] == 'completed' and waits == [daily.FINAL_HEAD_DELAYS[0]]
    assert set(result['producers']) == set(result['pins'])
    owed = {name: _owed_at(records, pin, None) for name, pin in result['pins'].items()}
    assert len({key for _, key, _ in owed.values()}) == len(owed)  # One owed record per table.
    for name, pin in result['pins'].items():
        assert records.find(name, pin)[1] == result['producers'][name]
        assert owed[name][0]['input'] == name and pin['table_uuid'] in owed[name][1]
        assert owed[name][0]['owed'] == dict(status='recorded', by='run', record=result['producers'][name])


def test_a_failed_owed_mark_never_fails_a_run_that_wrote_its_records(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    failed = _failing_owed_marks(monkeypatch, 'recorded')
    result = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert result['status'] == 'completed' and set(result['producers']) == set(result['pins'])
    assert sorted(failed) == sorted(note.split(' ')[0] for note in result['owed_unmarked'])
    assert all(records.find(name, pin)[1] == result['producers'][name] for name, pin in result['pins'].items())


def test_a_refusal_mark_is_retried_per_table_and_a_lasting_failure_names_its_key(tmp_path, clean_tree, monkeypatch):
    from congress_api.lake.producer_records import owed_key
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    initial = _heads(engine, value, tmp_path / 'initial')
    stuck = owed_key(initial['captures'])
    failed = _failing_owed_marks(monkeypatch, 'refused', {stuck})
    waits = []
    monkeypatch.setattr(daily, 'SLEEP', waits.append)
    _move_checkout_after_producing(monkeypatch)
    with pytest.raises(daily.CheckoutChanged, match='could not be marked refused and must not be completed') as error:
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert stuck in str(error.value) and failed == [stuck] * (len(daily.REFUSE_DELAYS) + 1)
    assert waits == list(daily.REFUSE_DELAYS)
    for name, pin in initial.items():
        assert _owed_at(records, pin, None)[0]['owed']['status'] == ('pending' if name == 'captures' else 'refused')


def _stop_after_producing(monkeypatch, stop):
    produce = daily._produce

    def produce_then_stop(*args):
        produce(*args)
        raise stop
    monkeypatch.setattr(daily, '_produce', produce_then_stop)


def _move_checkout_after_producing(monkeypatch):
    produce = daily._produce

    def produce_then_move_checkout(*args):
        produce(*args)
        monkeypatch.setattr(daily, 'writer_identity', lambda root, job: dict(WRITER, job=job, commit='c' * 40))
    monkeypatch.setattr(daily, '_produce', produce_then_move_checkout)


def test_a_run_of_forty_unrecorded_appends_is_completed_and_a_cycle_refused(tmp_path):
    records = ProducerRecords(root=tmp_path / 'ledger')
    empty = dict(metadata_location='/empty.json', table_uuid=PIN['table_uuid'], snapshot=None, schema_id=0)
    intent = dict(version=1, input='captures', job=DAILY_JOB, commit=HEAD, lockfile_digest='b' * 64,
                  decided_at='2026-11-08T19:37:02Z', base=dict(selector=dict(kind='native_table', **empty), record=None))
    records.owe(dict(intent, owed=dict(status='pending')), None)
    head = dict(PIN, metadata_location='/head.json', snapshot=40)
    lookups = []
    at = records.at
    records.at = lambda *args: lookups.append(args[2]) or at(*args)
    records.lineage = lambda location: {n: (n - 1 or None, 'append') for n in range(1, 41)}
    unmarked = []
    (record, reference), problem = daily._complete_owed(records, 'captures', head, unmarked)
    assert problem is None and not unmarked and lookups == list(range(39, 0, -1))
    assert record == dict(intent, selector=dict(kind='native_table', **head))
    assert records.find('captures', head) == (record, reference)
    assert records.owed(empty)[0]['owed'] == dict(status='recorded', by='preflight', record=reference)

    records.lineage = lambda location: {7: (8, 'append'), 8: (7, 'append')}
    assert daily._complete_owed(records, 'captures', dict(PIN, snapshot=7), unmarked) == (
        None, dict(reason='the head lineage repeats a snapshot'))
    records.lineage = lambda location: {7: (6, 'append')}
    assert daily._complete_owed(records, 'captures', dict(PIN, snapshot=7), unmarked) == (
        None, dict(reason='snapshot 6 is missing from the head lineage'))


def test_a_lost_final_read_with_a_changed_checkout_refuses_and_raises_the_read(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    failures = [1] * (len(daily.FINAL_HEAD_DELAYS) + 1)
    waits = _failing_final_reads(monkeypatch, failures)
    _move_checkout_after_producing(monkeypatch)
    with pytest.raises(OSError, match='operation timed out'):
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert waits == list(daily.FINAL_HEAD_DELAYS) and not failures
    heads = _heads(engine, value, tmp_path / 'heads')
    assert all(_owed_at(records, pin, None)[0]['owed'] == dict(
        status='refused', reason='Application commit changed during daily production') for pin in heads.values())


def test_a_failed_mark_while_a_run_stops_becomes_a_note_on_its_exception(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    failed = _failing_owed_marks(monkeypatch, 'recorded')
    _stop_after_producing(monkeypatch, ValueError('stopped after appending'))
    with pytest.raises(ValueError, match='stopped after appending') as stopped:
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    notes = '\n'.join(stopped.value.__notes__)
    assert failed and all(key + ' not marked recorded' in notes for key in failed)
    heads = _heads(engine, value, tmp_path / 'heads')
    assert all(records.find(name, pin) is not None for name, pin in heads.items())


def test_an_interrupt_reads_the_heads_once_and_leaves_the_rest_pending(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    failures = [1] * (len(daily.FINAL_HEAD_DELAYS) + 1)
    waits = _failing_final_reads(monkeypatch, failures)
    _stop_after_producing(monkeypatch, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt) as stopped:
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert waits == [] and len(failures) == len(daily.FINAL_HEAD_DELAYS)
    assert 'Owed producer records not settled' in '\n'.join(stopped.value.__notes__)
    heads = _heads(engine, value, tmp_path / 'heads')
    assert all(_owed_at(records, pin, None)[0]['owed'] == dict(status='pending') for pin in heads.values())


def test_the_next_preflight_completes_what_a_killed_run_owed(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')

    def killed(*args, **kwargs):
        raise SystemExit('killed between the appends and the record write')
    settle = daily._settle_owed
    monkeypatch.setattr(daily, '_settle_owed', killed)
    with pytest.raises(SystemExit):
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    monkeypatch.setattr(daily, '_settle_owed', settle)
    heads = _heads(engine, value, tmp_path / 'heads')
    assert all(records.find(name, pin) is None for name, pin in heads.items())
    assert all(_owed_at(records, pin, None)[0]['owed'] == dict(status='pending') for pin in heads.values())
    second = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store,
                                 producer_records=records)
    assert second['status'] == 'completed' and second['pins'] == heads and second['producers'] == {}
    for name, pin in heads.items():
        record, reference = records.find(name, pin)
        assert record['decided_at'] == value['decided_at'] and record['base']['record'] is None
        owed = _owed_at(records, pin, None)
        assert owed[0]['owed'] == dict(status='recorded', by='preflight', record=reference)
        assert {k: v for k, v in owed[0].items() if k != 'owed'} == {k: v for k, v in record.items() if k != 'selector'}


def test_a_changed_checkout_refuses_the_owed_records_for_good(tmp_path, clean_tree, monkeypatch):
    from congress_api.lake.producer_records import owed_key
    value, engine, store = native_fixture(tmp_path)
    records = ProducerRecords(root=tmp_path / 'ledger')
    _move_checkout_after_producing(monkeypatch)
    with pytest.raises(daily.CheckoutChanged, match='Application commit changed during daily production'):
        daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    monkeypatch.setattr(daily, 'writer_identity', lambda root, job: dict(WRITER, job=job))
    heads = _heads(engine, value, tmp_path / 'heads')
    refused = daily.produce_daily(dict(value, work=str(tmp_path / 'second')), engine=engine, raw_store=store,
                                  producer_records=records)
    assert refused['status'] == 'producer_unrecorded' and refused['producers']['missing'] == sorted(heads)
    state = dict(status='refused', reason='Application commit changed during daily production')
    assert refused['producers']['owed'] == {name: dict(key=owed_key(dict(pin, snapshot=None)),
        reason='the owed record is refused', owed=state) for name, pin in heads.items()}
    assert all(records.find(name, pin) is None for name, pin in heads.items())


def test_a_lost_final_read_is_completed_from_its_own_base_never_a_stale_one(tmp_path, clean_tree, monkeypatch):
    value, engine, store = native_fixture(tmp_path, 3)
    records = ProducerRecords(root=tmp_path / 'ledger')
    failures = [1] * (len(daily.FINAL_HEAD_DELAYS) + 1)
    waits = _failing_final_reads(monkeypatch, failures)
    with pytest.raises(OSError, match='operation timed out'):
        daily.produce_daily(dict(value, receipt_inventory=value['receipt_inventory'][:1]), engine=engine,
                            raw_store=store, producer_records=records)
    assert waits == list(daily.FINAL_HEAD_DELAYS) and not failures
    first = _heads(engine, value, tmp_path / 'first-heads')
    # As on 2026-11-08: the records are written by hand, leaving run A's owed records pending.
    for name, pin in first.items():
        if pin['snapshot'] is None:
            continue
        intent = _owed_at(records, pin, None)[0]
        records.write(dict({k: v for k, v in intent.items() if k != 'owed'}, selector=dict(kind='native_table', **pin)))

    # Run B appends onto those heads and loses its final read too.
    failures.extend([1] * (len(daily.FINAL_HEAD_DELAYS) + 1))
    later = '2026-10-29T12:00:00Z'
    with pytest.raises(OSError, match='operation timed out'):
        daily.produce_daily(dict(value, work=str(tmp_path / 'b'), decided_at=later,
                                 receipt_inventory=value['receipt_inventory'][:2]),
                            engine=engine, raw_store=store, producer_records=records)
    second = _heads(engine, value, tmp_path / 'second-heads')
    assert second['captures'] != first['captures']

    # Planted: B's owed captures record names another base record; the preflight refuses and names it.
    _, key, _ = _owed_at(records, first['captures'], first['captures']['snapshot'])
    saved = (tmp_path / 'ledger' / key).read_bytes()
    planted = json.loads(saved)
    planted['base']['record'] = dict(planted['base']['record'], sha256='0' * 64)
    (tmp_path / 'ledger' / key).write_bytes(encode(planted))
    refused = daily.produce_daily(dict(value, work=str(tmp_path / 'refused')), engine=engine, raw_store=store,
                                  producer_records=records)
    assert refused['status'] == 'producer_unrecorded' and refused['producers'] == dict(missing=['captures'],
        owed=dict(captures=dict(key=key, reason='the owed record names another table or base record')))
    assert records.find('captures', second['captures']) is None

    (tmp_path / 'ledger' / key).write_bytes(saved)
    third = daily.produce_daily(dict(value, work=str(tmp_path / 'third')), engine=engine, raw_store=store,
                                producer_records=records)
    assert third['status'] == 'completed'
    record, reference = records.find('captures', second['captures'])
    assert record['decided_at'] == later
    assert record['base'] == dict(selector=dict(kind='native_table', **first['captures']),
                                  record=records.find('captures', first['captures'])[1])
    assert _owed_at(records, first['captures'], first['captures']['snapshot'])[0]['owed']['record'] == reference
    # Run A's stale owed record at the empty base was never read.
    assert _owed_at(records, first['captures'], None)[0]['owed'] == dict(status='pending')


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


def test_scoped_html_metadata_preserves_native_history_on_stop_and_resume(tmp_path, clean_tree, monkeypatch):
    from viewer_publication.producer_proof import find_records, snapshot_reasons

    payloads = [f'<!doctype html><html><head><title>Fixture {i}</title></head><body>Page {i}</body></html>'.encode()
                for i in range(6)]
    keys = sorted(sha256(data).hexdigest() for data in payloads)
    value, engine, store = native_fixture(tmp_path, len(payloads), payloads=payloads, url_suffix='.html')
    records = ProducerRecords(root=tmp_path/'ledger')
    baseline = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert baseline['status'] == 'completed'
    table_specs = {name: value['tables'][name] for name in ('captures', 'readings')}
    authority = dict(engine=engine, catalog_root=value['catalog_root'])
    base = {name: baseline['pins'][name] for name in table_specs}
    version = readings.current_version('html_metadata')
    decision = tmp_path/'original-unreadable.jsonl'
    decision.write_text(json.dumps(dict(id='a'*64, body_sha256=keys[4], parser='html_metadata',
        parser_version=version, reason='timeout', decided_by='readings',
        decided_at=value['decided_at'], supersedes=None))+'\n')
    import_unreadable(store, decision, decided_at=value['decided_at'])
    snapshot = unreadable_inventory(store, work=tmp_path/'initial-unreadable')
    original_refusals = snapshot.rows()

    def pinned_scope(name, body_shas):
        path = tmp_path/(name+'.parquet')
        pq.write_table(pa.table({'body_sha': body_shas}), path)
        return dict(path=str(path), **file_pin(path))

    scope = pinned_scope('selected', keys[:5])
    options = dict(**authority, raw_store=store, producer_records=records, tables_spec=table_specs,
        scope=scope, decided_at=value['decided_at'], unreadable_snapshot=snapshot, batch_size=1)

    with pytest.raises(ValueError, match='bytes changed'):
        daily.produce_html_metadata(**dict(options, scope=dict(scope, sha256='0'*64)),
            work=tmp_path/'bad-digest', expected_heads=base)
    with pytest.raises(ValueError, match='missing from the pinned captures'):
        daily.produce_html_metadata(**dict(options, scope=pinned_scope('absent', ['0'*64])),
            work=tmp_path/'bad-body', expected_heads=base)

    real_append = readings.append
    def interrupt_after_append(staged, **kwargs):
        assert staged['parser'] == 'html_metadata'
        real_append(staged, **kwargs)
        raise KeyboardInterrupt('stopped after native append')

    with monkeypatch.context() as patch:
        patch.setattr(readings, 'append', interrupt_after_append)
        with pytest.raises(KeyboardInterrupt, match='stopped after native append'):
            daily.produce_html_metadata(**options, work=tmp_path/'interrupted', expected_heads=base)
    stopped = tables.resolve_tables(**authority, work=tmp_path/'stopped-heads', tables=table_specs)
    stopped_record, stopped_ref = records.find('readings', stopped['readings'])
    assert stopped['readings'] != base['readings'] and stopped['captures'] == base['captures']
    assert stopped_record['commit'] == HEAD and stopped_record['base'] == {
        'selector': dict(kind='native_table', **base['readings']),
        'record': baseline['producers']['readings'],
    }
    with pytest.raises(ValueError, match='expected captures or readings head changed'):
        daily.produce_html_metadata(**options, work=tmp_path/'stale-head', expected_heads=base)

    body = next(row for row in pq.read_table(value['body_inventory']).to_pylist()
                if row['body_sha'].hex() == keys[3])
    path = store.adapter.root/body['relative_path']
    stored = path.read_bytes()
    path.unlink()
    partial = daily.produce_html_metadata(**options, work=tmp_path/'partial', expected_heads=stopped)
    assert partial['status'] == 'pending'
    assert partial['readings']['work_items'] == 3 and partial['readings']['pending_reads'] == 1
    assert [batch['work_items'] for batch in partial['readings']['batches']] == [1, 1, 1]
    assert len([batch for batch in partial['readings']['batches'] if batch['append'] is not None]) == 2
    partial_pin = partial['pins']['readings']
    partial_record, partial_ref = records.find('readings', partial_pin)
    lineage = records.lineage(partial_pin['metadata_location'])
    assert lineage[lineage[partial_pin['snapshot']][0]] == (stopped['readings']['snapshot'], 'append')
    assert partial_record['base'] == {'selector': dict(kind='native_table', **stopped['readings']),
                                      'record': stopped_ref}

    path.write_bytes(stored)
    complete = daily.produce_html_metadata(**options, work=tmp_path/'complete', expected_heads=partial['pins'])
    assert complete['status'] == 'completed' and complete['readings']['work_items'] == 1
    assert partial['unreadable'] == complete['unreadable'] == original_refusals
    assert complete['pins']['captures'] == base['captures']
    assert set(complete['producers']) == {'readings'}
    current_pin = complete['pins']['readings']
    model = dict(readings=dict(kind='native_table', **current_pin),
                 parser_versions=compatible_versions.current_pins())
    found = find_records(model, records, {})
    assert found['readings']['base'] == {'selector': dict(kind='native_table', **partial_pin), 'record': partial_ref}
    assert snapshot_reasons(model, found, ledger=records) == []
    observed = run_job(tmp_path/'row-comparison', engine,
        inputs=[tables.table_input('before_rows', base['readings']), tables.table_input('after_rows', current_pin)],
        steps=[dict(name='retained', sql="SELECT * FROM after_rows WHERE parser<>'html_metadata'")], outputs=[],
        queries=[dict(name='changed', sql="""SELECT
            (SELECT count(*) FROM (SELECT * FROM before_rows EXCEPT ALL SELECT * FROM retained)) AS lost,
            (SELECT count(*) FROM (SELECT * FROM retained EXCEPT ALL SELECT * FROM before_rows)) AS gained"""),
            dict(name='added', sql="""SELECT encode(body_sha,'hex') AS sha,parser_version,status
                FROM after_rows WHERE parser='html_metadata' ORDER BY sha""")])
    assert observed == dict(changed=[dict(lost=0, gained=0)],
                            added=[dict(sha=key, parser_version=version, status='completed') for key in keys[:4]])
    no_op = daily.produce_html_metadata(**options, work=tmp_path/'no-op', expected_heads=complete['pins'])
    assert no_op['status'] == 'completed' and no_op['readings']['work_items'] == 0
    assert no_op['producers'] == {} and no_op['pins'] == complete['pins']


def test_scoped_html_metadata_uses_pinned_r2_listing_for_older_captures(tmp_path, clean_tree):
    from congress_api.retention.provenance_inventory import UnreadableInventory
    from test_daily_raw_listing import body_gets, body_key, fixture

    data = b'<!doctype html><html><head><title>Older capture</title></head><body>HTML source</body></html>'
    value, engine, bucket, store = fixture(tmp_path, [data], unpinned=(0,))
    records = ProducerRecords(root=tmp_path/'ledger')
    baseline = daily.produce_daily(value, engine=engine, raw_store=store, producer_records=records)
    assert baseline['status'] == 'completed'
    tables_spec = {name: value['tables'][name] for name in ('captures', 'readings')}
    base = {name: baseline['pins'][name] for name in tables_spec}
    scope = tmp_path/'scope.parquet'
    pq.write_table(pa.table({'body_sha': [sha256(data).hexdigest()]}), scope)
    options = dict(engine=engine, catalog_root=value['catalog_root'], raw_store=store,
        producer_records=records, tables_spec=tables_spec, expected_heads=base,
        scope=dict(path=str(scope), **file_pin(scope)), batch_size=1, max_get_workers=2,
        decided_at=value['decided_at'], unreadable_snapshot=UnreadableInventory.from_qualified(store, qualified=[]))
    bucket.gets.clear()
    refused = daily.produce_html_metadata(**options, work=tmp_path/'without-listing')
    assert refused['status'] == 'raw_custody_required' and refused['readings']['missing_pins'] == 1
    assert refused['pins'] == base and refused['producers'] == {} and body_gets(bucket) == []

    key = body_key(data)
    metadata = bucket.head_object(Bucket='bucket', Key=key)
    listing = tmp_path/'listing.parquet'
    pq.write_table(pa.Table.from_pylist([dict(key=key, size=metadata['ContentLength'], etag=metadata['ETag'])],
                                       schema=daily.LISTING_SCHEMA), listing)
    produced = daily.produce_html_metadata(**options, work=tmp_path/'with-listing',
        body_listing=dict(path=str(listing), **file_pin(listing)))
    assert produced['status'] == 'completed' and produced['readings']['work_items'] == 1
    assert produced['readings']['raw_custody']['listing_etag'] == 1
    assert body_gets(bucket) == [dict(Key=key, IfMatch=metadata['ETag'], Range=None)]
    [batch] = produced['readings']['batches']
    [row] = pq.read_table(batch['readings']).to_pylist()
    assert (row['parser'], row['status'], row['body_sha']) == ('html_metadata', 'completed', sha256(data).digest())


def test_daily_html_delta_recovers_after_receipt_commit_and_respects_both_budgets(tmp_path,clean_tree,monkeypatch):
    payloads=[f'<html><head><title>Daily page {n}</title></head><body>Evidence {n}</body></html>'.encode()
        for n in range(5)]
    value,engine,store=native_fixture(tmp_path,5,payloads=payloads,url_suffix='.html')
    records=ProducerRecords(root=tmp_path/'ledger')
    first=daily.produce_daily(dict(value,receipt_inventory=value['receipt_inventory'][:1]),
        engine=engine,raw_store=store,producer_records=records)
    old=sha256(payloads[0]).hexdigest()
    scope_file=tmp_path/'qualified-old-html.parquet'
    pq.write_table(pa.table({'body_sha':[old]}),scope_file)
    authority=dict(engine=engine,catalog_root=value['catalog_root'])
    table_specs={name:value['tables'][name] for name in ('captures','readings')}
    scoped=daily.produce_html_metadata(**authority,raw_store=store,producer_records=records,
        tables_spec=table_specs,expected_heads={name:first['pins'][name] for name in table_specs},
        scope=dict(path=str(scope_file),**file_pin(scope_file)),
        unreadable_snapshot=unreadable_inventory(store,work=tmp_path/'old-unreadable'),
        batch_size=1,decided_at=value['decided_at'],work=tmp_path/'old-html')
    assert scoped['status']=='completed' and scoped['readings']['work_items']==1
    # Commit every new receipt and leaf reading first. Receipt discovery must not be
    # the source of truth for the later derived retry.
    leaves=daily.produce_daily(dict(value,work=str(tmp_path/'new-leaves')),
        engine=engine,raw_store=store,producer_records=records)
    assert leaves['status']=='completed'
    new=sorted(sha256(data).hexdigest() for data in payloads[1:])
    decision=tmp_path/'settled-html-refusal.jsonl'
    decision.write_text(json.dumps(dict(id='d'*64,body_sha256=new[-1],parser='html_metadata',
        parser_version=readings.current_version('html_metadata'),reason='timeout',decided_by='readings',
        decided_at=value['decided_at'],supersedes=None))+'\n')
    imported=import_unreadable(store,decision,decided_at=value['decided_at'])
    policy=dict(captures=first['pins']['captures'],versions=compatible_versions.current_pins(),
        max_stored_bytes=1<<20)
    enabled=dict(value,derived_parsers=['html_metadata'],derived_scopes={'html_metadata':policy})
    def invoke(name,**changes):
        return daily.produce_daily(dict(enabled,work=str(tmp_path/name),**changes),
            engine=engine,raw_store=store,producer_records=records)
    def forbidden(*args,**kwargs):raise AssertionError('Body opened before derived budget admission')
    with monkeypatch.context() as patch:
        patch.setattr(readings,'_execute_plan',forbidden)
        count_refusal=invoke('count-refusal',max_work_items=1)
        byte_refusal=invoke('byte-refusal',derived_scopes={'html_metadata':dict(policy,max_stored_bytes=1)})
    assert count_refusal['status']==byte_refusal['status']=='derived_budget_required'
    assert count_refusal['producerreports']['html_metadata']['work_items']==3
    assert byte_refusal['producerreports']['html_metadata']['budget']['stored_bytes']>1
    after_refusals=tables.resolve_tables(**authority,work=tmp_path/'after-budget-heads',tables=value['tables'])
    assert after_refusals==leaves['pins']
    bodies={row['body_sha'].hex():row for row in pq.read_table(value['body_inventory']).to_pylist()}
    missing_path=store.adapter.root/bodies[new[-2]]['relative_path']
    retained=missing_path.read_bytes();missing_path.unlink()
    # The derived pass appends once (ct-z4i9), so the missing body is the work it leaves.
    real_append=readings.append
    def stop_after_first(staged,**kwargs):
        assert staged['parser']=='html_metadata'
        real_append(staged,**kwargs)
        raise KeyboardInterrupt('interrupt after a derived native append')
    with monkeypatch.context() as patch:
        patch.setattr(readings,'append',stop_after_first)
        with pytest.raises(KeyboardInterrupt,match='derived native append'):
            invoke('interrupted')
    stopped=tables.resolve_tables(**authority,work=tmp_path/'stopped-daily-heads',tables=value['tables'])
    assert stopped['captures']==leaves['pins']['captures']
    assert stopped['readings']!=leaves['pins']['readings']
    assert records.find('readings',stopped['readings']) is not None
    partial=invoke('resumed-with-missing-body')
    assert partial['status']=='pending' and partial['new_receipt_keys']==[]
    derived=partial['producerreports']['html_metadata']
    assert derived['work_items']==1 and derived['pending_reads']==1
    assert derived['scope']['bodies_since_baseline']==4
    missing_path.write_bytes(retained)
    complete=invoke('resumed-complete')
    assert complete['status']=='completed' and complete['new_receipt_keys']==[]
    assert complete['producerreports']['html_metadata']['work_items']==1
    assert any(row['key']==imported['key'] for row in complete['provenance']['unreadable'])
    unchanged=invoke('unchanged')
    assert unchanged['status']=='completed' and unchanged['producerreports']['html_metadata']['work_items']==0
    assert unchanged['producerreports']['html_metadata']['read_bytes']==0 and unchanged['producers']=={}
    result=run_job(tmp_path/'daily-html-rows',engine,
        inputs=[tables.table_input('readings',unchanged['pins']['readings'])],steps=[],outputs=[],queries=[
        dict(name='rows',sql="SELECT encode(body_sha,'hex') AS sha,status FROM readings WHERE parser='html_metadata' ORDER BY sha"),
        dict(name='duplicates',sql='SELECT count(*) AS n FROM (SELECT body_sha,parser,parser_version FROM readings GROUP BY body_sha,parser,parser_version HAVING count(*)>1)')])
    assert result==dict(rows=[dict(sha=key,status='completed') for key in sorted([old,*new[:-1]])],duplicates=[dict(n=0)])


def test_daily_html_reconsiders_superseded_baseline_refusals(tmp_path,clean_tree):
    payloads=[f'<html><head><title>Baseline refusal {n}</title></head><body>Body {n}</body></html>'.encode()
        for n in range(2)]
    value,engine,store=native_fixture(tmp_path,2,payloads=payloads,url_suffix='.html')
    records=ProducerRecords(root=tmp_path/'ledger')
    base=daily.produce_daily(value,engine=engine,raw_store=store,producer_records=records)
    keys=[sha256(data).hexdigest() for data in payloads]
    version=readings.current_version('html_metadata')
    def save(name,rows):
        path=tmp_path/(name+'.jsonl')
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        return import_unreadable(store,path,decided_at=value['decided_at'])
    def decision(identifier,body,parser='html_metadata',supersedes=None):
        return dict(id=identifier*64,body_sha256=body,parser=parser,
            parser_version=readings.current_version(parser),reason='timeout',decided_by='readings',
            decided_at=value['decided_at'],supersedes=supersedes)
    original=save('baseline-refusals',[decision('a',keys[0]),decision('b',keys[1])])
    policy=dict(captures=base['pins']['captures'],versions=compatible_versions.current_pins(),
        max_stored_bytes=1<<20)
    enabled=dict(value,derived_parsers=['html_metadata'],derived_scopes={'html_metadata':policy})
    def invoke(name):
        return daily.produce_daily(dict(enabled,work=str(tmp_path/name)),
            engine=engine,raw_store=store,producer_records=records)
    settled=invoke('baseline-settled')
    assert settled['status']=='completed' and settled['producerreports']['html_metadata']['work_items']==0
    # A correction supersedes the metadata refusal without replacing it with a
    # current metadata refusal. The maintained selection must reopen that pair.
    correction=save('corrections',[decision('c',keys[0],parser='html',supersedes='a'*64),
        decision('d',keys[1],supersedes='b'*64)])
    reopened=invoke('baseline-reopened')
    assert reopened['status']=='completed' and reopened['new_receipt_keys']==[]
    derived=reopened['producerreports']['html_metadata']
    assert derived['work_items']==1 and derived['read_bytes']>0
    assert derived['scope']['bodies_since_baseline']==0
    assert derived['scope']['reconsidered_baseline_bodies']==2
    assert {row['key'] for row in reopened['provenance']['unreadable']}=={original['key'],correction['key']}
    unchanged=invoke('completed-and-replacement-active')
    assert unchanged['status']=='completed' and unchanged['producerreports']['html_metadata']['work_items']==0
    assert unchanged['producerreports']['html_metadata']['read_bytes']==0 and unchanged['producers']=={}
    rows=run_job(tmp_path/'reopened-reading',engine,
        inputs=[tables.table_input('readings',unchanged['pins']['readings'])],steps=[],outputs=[],queries=[
        dict(name='rows',sql="SELECT encode(body_sha,'hex') AS sha,parser_version,status FROM readings WHERE parser='html_metadata'")])['rows']
    assert rows==[dict(sha=keys[0],parser_version=version,status='completed')]
