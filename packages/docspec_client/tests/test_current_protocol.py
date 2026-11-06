"""Current protocol refusals never renegotiate input bytes or native semantics."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client import NativeDatasets, blake3_hex, restore_application_schema
from docspec_client.models import DocSpecFailure, PartitionSpec


@pytest.fixture
def source_table():
    schema = pa.schema([
        pa.field('id', pa.int32(), nullable=False, metadata={b'PARQUET:field_id': b'1'}),
        pa.field('chamber', pa.string()),
        pa.field('title', pa.string()),
        pa.field('body', pa.binary(32), metadata={b'PARQUET:field_id': b'4'}),
        pa.field('sittings', pa.list_(pa.struct([pa.field('room', pa.string())]))),
    ], metadata={b'origin': b'current-protocol-test'})
    return pa.Table.from_pylist([
        dict(id=1, chamber='house', title='First', body=b'a' * 32,
             sittings=[dict(room=None), dict(room=None)]),
        dict(id=2, chamber='senate', title=None, body=None, sittings=[]),
        dict(id=3, chamber=None, title='', body=b'b' * 32, sittings=None),
    ], schema=schema)


def failure(code, message, *, status=422, pre_admission=True, completed=None):
    stdout = '' if completed is None else json.dumps(dict(status='failed', completed=completed))
    result = SimpleNamespace(returncode=1, stdout=stdout,
                             stderr=json.dumps(dict(code=code, message=message,
                                                    pre_admission=pre_admission)))
    error = DocSpecFailure(('docspec', 'request'), result)
    error.status = status
    return error


@pytest.fixture
def producer(tmp_path, monkeypatch):
    import docspec_client.client as module

    client = NativeDatasets(tmp_path / 'unused-native-binary', tmp_path / 'workspace')
    writes = []
    write = module._write_producer_parquet

    def record_write(table, path, **settings):
        write(table, path, **settings)
        writes.append(dict(path=Path(path), data=Path(path).read_bytes(), settings=settings))

    def hash_local(path):
        data = Path(path).read_bytes()
        return dict(digest=blake3_hex(data), bytes=len(data))

    monkeypatch.setattr(module, '_write_producer_parquet', record_write)
    monkeypatch.setattr(client, 'hash_input', hash_local)
    monkeypatch.setattr(module.time, 'sleep', lambda _seconds: None)
    return client, writes


@pytest.mark.parametrize('operation', ['ingest', 'update'])
def test_ipc_415_is_the_original_refusal_without_parquet_fallback(tmp_path, monkeypatch, source_table, operation):
    import docspec_client.client as module

    client = NativeDatasets(tmp_path / 'unused-native-binary', tmp_path / 'workspace')
    refused = failure('unsupported_media_type', 'Arrow IPC is required by the caller', status=415)
    calls = []

    def reject_ipc(path, ipc_bytes, spec, *, blake3_digest=None, dispatch=None):
        with pa.ipc.open_stream(pa.py_buffer(ipc_bytes)) as reader:
            assert reader.read_all().equals(source_table, check_metadata=True)
        assert spec['operation'] == 'original-operation'
        digest = spec['expected_digest'] if operation == 'ingest' else spec['replacements']['digest']
        assert digest == blake3_digest == blake3_hex(ipc_bytes)
        calls.append(path)
        raise refused

    def no_fallback(*args, **kwargs):
        pytest.fail('A refused current protocol must not become a Parquet request')

    monkeypatch.setattr(client, '_request_ipc', reject_ipc)
    monkeypatch.setattr(client, '_request', no_fallback)
    monkeypatch.setattr(module, '_write_producer_parquet', no_fallback)
    with pytest.raises(DocSpecFailure) as caught:
        if operation == 'ingest':
            client.run_table(source_table, dataset='meetings', operation='original-operation',
                             definition='current', stream_ipc=True, native_types=True)
        else:
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'],
                                stream_ipc=True, native_types=True)
    assert caught.value is refused
    assert calls == ['/run' if operation == 'ingest' else '/updates/run']
    assert not client.workspace.exists()


@pytest.mark.parametrize('refusal', ['partition', 'operation_conflict', 'merge'])
def test_refused_feature_or_operation_never_changes_the_request(producer, monkeypatch, source_table, refusal):
    client, writes = producer
    if refusal == 'operation_conflict':
        refused = failure('operation_conflict', 'operation_conflict: original input differs', status=409)
    else:
        refused = failure('invalid_request', "unknown field 'partition_by'" if refusal == 'partition' else "unknown field 'merge'")
    calls = []

    def reject_once(path, request, *, dispatch=None):
        dispatch['submitted'] = True
        calls.append((path, deepcopy(request)))
        if len(calls) == 1:
            raise refused
        return dict(status='succeeded')  # The removed fallback would incorrectly reach this.

    def no_local_merge(*args, **kwargs):
        pytest.fail('A merge refusal must not read and reimplement the native base locally')

    monkeypatch.setattr(client, '_request', reject_once)
    monkeypatch.setattr(client, 'release', no_local_merge)
    monkeypatch.setattr(client, 'source_batches', no_local_merge)
    with pytest.raises(DocSpecFailure) as caught:
        if refusal == 'merge':
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'],
                                merge=dict(columns=dict(title='latest_or_backfill')))
        else:
            client.run_table(source_table, dataset='meetings', operation='original-operation',
                             definition='current', partition_by='chamber' if refusal == 'partition' else None,
                             row_group_size=None)
    assert caught.value is refused
    assert len(calls) == len(writes) == 1
    request = calls[0][1]
    assert request['operation'] == 'original-operation'
    digest = request['replacements']['digest'] if refusal == 'merge' else request['expected_digest']
    assert digest == blake3_hex(writes[0]['data'])
    if refusal == 'partition':
        assert request['partition_by'] == PartitionSpec.normalize('chamber')
    elif refusal == 'merge':
        assert request['merge'] == dict(columns=dict(title='latest_or_backfill'))
    assert not list(client.workspace.glob('request-*')), 'A definite pre-admission refusal permits cleanup'


@pytest.mark.parametrize('operation', ['ingest', 'update'])
def test_transient_retry_keeps_exact_native_operation_and_source(producer, monkeypatch, source_table, operation):
    client, writes = producer
    calls = []
    unconfirmed = failure('remote_unconfirmed', 'remote_unconfirmed: commit state is unknown',
                          status=503, pre_admission=False)

    def recover_same_operation(path, request, *, dispatch=None):
        dispatch['submitted'] = True
        calls.append((path, deepcopy(request)))
        if len(calls) == 1:
            raise unconfirmed
        return dict(operation=request['operation'], outcome='reconciled')

    monkeypatch.setattr(client, '_request', recover_same_operation)
    if operation == 'ingest':
        result = client.run_table(source_table, dataset='meetings', operation='original-operation', definition='current')
    else:
        result = client.update_table(source_table, dataset='meetings', operation='original-operation',
                                     definition='current', base='base', keys=['id'])
    assert result == dict(operation='original-operation', outcome='reconciled')
    assert len(calls) == 2 and calls[0] == calls[1]
    assert len(writes) == 1
    assert not list(client.workspace.glob('request-*'))


@pytest.mark.parametrize('operation', ['ingest', 'update'])
def test_unconfirmed_partial_failure_retains_original_bytes_request_and_report(producer, monkeypatch, source_table, operation):
    client, writes = producer
    completed = dict(outputs=[dict(name='completed-native-output', sha256='a' * 64)])
    unconfirmed = failure('remote_unconfirmed', 'remote_unconfirmed: commit state is unknown',
                          status=503, pre_admission=False, completed=completed)
    original_stdout = unconfirmed.stdout
    calls = []

    def lose_acknowledgment(path, request, *, dispatch=None):
        dispatch['submitted'] = True
        calls.append((path, deepcopy(request)))
        raise unconfirmed

    monkeypatch.setattr(client, '_request', lose_acknowledgment)
    with pytest.raises(DocSpecFailure) as caught:
        if operation == 'ingest':
            client.run_table(source_table, dataset='meetings', operation='original-operation', definition='current')
        else:
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'])
    assert caught.value is unconfirmed
    assert unconfirmed.stdout == original_stdout and unconfirmed.completed == completed
    assert len(calls) == 4 and all(call == calls[0] for call in calls)
    assert len(writes) == 1
    retained = unconfirmed.retained_input
    assert Path(retained['input']).read_bytes() == writes[0]['data']
    assert json.loads(Path(retained['request']).read_text()) == calls[0][1]
    restored = restore_application_schema(pq.read_table(retained['input']), expected_schema=source_table.schema)
    assert restored.equals(source_table, check_metadata=True)
    assert client.retained_producer_inputs()[0]['request'] == retained['request']


@pytest.mark.parametrize('operation', ['ingest', 'update'])
@pytest.mark.parametrize('later_failure', ['transport', 'dead_host', 'deadline', 'pre_admission'])
def test_prior_uncertain_submit_survives_a_different_later_failure(producer, monkeypatch, source_table, operation, later_failure):
    import httpx

    client, writes = producer
    completed = dict(outputs=[dict(name='completed-before-response-loss', sha256='b' * 64)])
    uncertain = failure('remote_unconfirmed', 'remote_unconfirmed: commit state is unknown',
                        status=503, pre_admission=False, completed=completed)
    if later_failure == 'transport':
        final = httpx.ConnectError('Connection failed before dispatch')
    elif later_failure == 'dead_host':
        final = failure('host_unavailable', 'DocSpec host exited before dispatch',
                        status=None, pre_admission=False)
    elif later_failure == 'deadline':
        final = TimeoutError('DocSpec request deadline exceeded before dispatch')
    else:
        final = failure('invalid_request', 'This later attempt was refused before admission')
    requests, dispatches = [], []

    def fail_after_uncertainty(path, request, *, dispatch=None):
        requests.append(deepcopy(request))
        dispatches.append(dispatch)
        if len(requests) == 1:
            dispatch['submitted'] = True
            raise uncertain
        assert not dispatch.get('submitted'), 'Each attempt needs its own dispatch state'
        if later_failure == 'pre_admission':
            dispatch['submitted'] = True
        raise final

    monkeypatch.setattr(client, '_request', fail_after_uncertainty)
    with pytest.raises(type(final)) as caught:
        if operation == 'ingest':
            client.run_table(source_table, dataset='meetings', operation='original-operation', definition='current')
        else:
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'])
    assert caught.value is final
    assert len(requests) == (4 if later_failure == 'transport' else 2)
    assert len({id(dispatch) for dispatch in dispatches}) == len(dispatches)
    assert all(request == requests[0] for request in requests)
    assert len(writes) == 1
    retained = final.retained_input
    assert Path(retained['input']).read_bytes() == writes[0]['data']
    assert json.loads(Path(retained['request']).read_text()) == requests[0]
    evidence = json.loads(Path(retained['failures']).read_text())
    assert evidence == final.producer_failures
    assert len(evidence) == len(requests)
    assert evidence[0]['submitted'] is True
    assert evidence[0]['stdout'] == uncertain.stdout and evidence[0]['completed'] == completed
    assert evidence[-1]['type'] == type(final).__name__
    assert evidence[-1]['submitted'] is (later_failure == 'pre_admission')
    if later_failure == 'pre_admission':
        assert evidence[-1]['pre_admission'] is True
    restored = restore_application_schema(pq.read_table(retained['input']), expected_schema=source_table.schema)
    assert restored.equals(source_table, check_metadata=True)


@pytest.mark.parametrize('operation', ['ingest', 'update'])
def test_definite_first_pre_admission_refusal_still_releases_producer_custody(producer, monkeypatch, source_table, operation):
    client, writes = producer
    refused = failure('invalid_request', 'Current request refused before admission')
    calls = []

    def reject(path, request, *, dispatch=None):
        dispatch['submitted'] = True
        calls.append(deepcopy(request))
        raise refused

    monkeypatch.setattr(client, '_request', reject)
    with pytest.raises(DocSpecFailure) as caught:
        if operation == 'ingest':
            client.run_table(source_table, dataset='meetings', operation='original-operation', definition='current')
        else:
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'])
    assert caught.value is refused
    assert len(calls) == len(writes) == 1
    assert not hasattr(refused, 'retained_input')
    assert not list(client.workspace.glob('request-*'))


@pytest.mark.parametrize('choice', ['missing_partition', 'missing_order', 'missing_merge', 'scalar_set_union'])
def test_invalid_caller_choices_reach_native_refusal_without_silent_changes(producer, monkeypatch, source_table, choice):
    client, writes = producer
    refused = failure('invalid_request', 'Native validation refuses the exact caller choice')
    calls = []

    def reject_choice(path, request, *, dispatch=None):
        dispatch['submitted'] = True
        calls.append(deepcopy(request))
        if choice == 'missing_partition':
            assert request['partition_by'][0]['column'] == 'not_in_source'
        elif choice == 'missing_order':
            assert request['merge']['order_by'] == 'not_in_source'
        elif choice == 'missing_merge':
            assert request['merge']['columns'] == dict(not_in_source='max')
        else:
            assert request['merge']['columns'] == dict(title='set_union')
        raise refused

    monkeypatch.setattr(client, '_request', reject_choice)
    with pytest.raises(DocSpecFailure) as caught:
        if choice == 'missing_partition':
            client.run_table(source_table, dataset='meetings', operation='original-operation',
                             definition='current', partition_by='not_in_source')
        else:
            merge = (dict(order_by='not_in_source', columns=dict(title='latest_or_backfill'))
                     if choice == 'missing_order' else dict(columns=dict(not_in_source='max'))
                     if choice == 'missing_merge' else dict(columns=dict(title='set_union')))
            client.update_table(source_table, dataset='meetings', operation='original-operation',
                                definition='current', base='base', keys=['id'], merge=merge)
    assert caught.value is refused
    assert len(calls) == len(writes) == 1
    assert not list(client.workspace.glob('request-*'))


def test_producer_layout_uses_current_policy_and_refuses_legacy_switch(tmp_path, source_table):
    from docspec_client.transport import _write_producer_parquet

    for row_group_size, groups in [(None, 1), (1, 3)]:
        path = tmp_path / ('current-auto.parquet' if row_group_size is None else 'current-explicit.parquet')
        _write_producer_parquet(source_table, path, row_group_size=row_group_size)
        assert pq.ParquetFile(path).metadata.num_row_groups == groups
        restored = restore_application_schema(pq.read_table(path), expected_schema=source_table.schema)
        assert restored.equals(source_table, check_metadata=True)
    legacy = tmp_path / 'unsupported-legacy.parquet'
    with pytest.raises(TypeError, match='_legacy_row_group_sizing'):
        _write_producer_parquet(source_table, legacy, _legacy_row_group_sizing=True)
    assert not legacy.exists()
