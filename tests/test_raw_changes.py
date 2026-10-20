"""A catalog worker can catch up exact selected raw deliveries after restart."""
from congress_api.retention.raw_storage import RawStorage
from native_memory_helpers import MemoryNative, memory_raw_storage
from test_raw_storage import SelectorStore, captures, states


def test_changes_resume_after_worker_loss_without_capture_payload_reads():
    store = SelectorStore()
    storage = memory_raw_storage(store)
    empty = storage.snapshot()
    first = storage.publish(storage.prepare(empty, operation='a', captures=captures('a'), states=states('a')))
    last = storage.publish(storage.prepare(first, operation='b', captures=captures('b'), states=states('b')))
    restarted = RawStorage(store, storage.native)
    selected = restarted.snapshot()
    storage.native.reads.clear()
    changes = list(selected.changes_since(empty.identity))
    assert len(changes) == 2
    assert [c['previous_identity'] for c in changes] == [empty.identity, first.identity]
    assert [c['identity'] for c in changes] == [first.identity, last.identity]
    assert [list(selected.changed_state_urls(c)) for c in changes] == [[states('a')['url'][0].as_py()], [states('b')['url'][0].as_py()]]
    batches = [entry for change in changes for entry in selected.changed_capture_batches(change)]
    assert [entry['first_order'] for entry in batches] == [0, 1]
    assert [entry['rows'] for entry in batches] == [1, 1]
    assert storage.native.reads == []
    assert len(list(selected.changes_since(first.identity))) == 1


def test_receipt_only_operation_replay_is_bound_and_namespaced():
    import pytest
    storage = memory_raw_storage(SelectorStore())
    old = storage.snapshot()
    first = storage.publish(storage.prepare(old, operation='receipt:receipts/a',
        indexed_receipts=(value for value in ['receipts/a'])))
    assert first.has_receipt('receipts/a')
    assert first.completed_delivery('receipt:receipts/a')
    with pytest.raises(ValueError, match='request'):
        storage.prepare(first, operation='receipt:receipts/a', indexed_receipts=['receipts/b'])
    before = list(storage.store.writes)
    replay = storage.prepare(first, operation='receipt:receipts/a', indexed_receipts=['receipts/a'])
    assert replay['already_applied']
    storage.publish(replay)
    assert storage.store.writes == before
