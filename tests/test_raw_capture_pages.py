"""Capture publication pages reuse closed history and preserve exact order."""
from copy import deepcopy
import pytest

from congress_api.retention.raw_capture_pages import CapturePages


class Store:
    def __init__(self):
        self.objects, self.reads, self.writes = {}, [], []
        self.lose_reply = False
    def read(self, key):
        self.reads.append(key)
        return self.objects.get(key)
    def put(self, key, payload, *, immutable):
        assert immutable
        if key in self.objects:
            assert self.objects[key] == payload
        self.objects[key] = payload
        self.writes.append(key)
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError('reply lost after retention')


def entry(index):
    return dict(dataset=f'capture-{index}', version='initial', manifest=dict(
        path=f's3://test/native/{index}/release.json', digest=f'{index:064x}', bytes=512),
        first_order=index, rows=1)


def test_page_boundary_reuses_closed_page_without_reading_it():
    store = Store()
    pages = CapturePages(store)
    old = pages.append(None, [entry(i) for i in range(64)])
    old_payload = deepcopy(store.objects)
    store.reads.clear()
    new = pages.append(old, [entry(64)])
    assert store.reads == []
    assert all(store.objects[k] == v for k, v in old_payload.items())
    assert new['entries'] == 1
    assert list(pages.entries(new)) == [entry(i) for i in range(65)]
    assert list(pages.entries(old)) == [entry(i) for i in range(64)]
    writes = list(store.writes)
    assert pages.append(new, []) == new
    assert store.writes == writes


def test_lost_page_reply_resume_and_conflicting_or_reordered_metadata():
    store = Store()
    pages = CapturePages(store)
    store.lose_reply = True
    first = pages.append(None, [entry(0)])
    assert pages.append(None, [entry(0)]) == first
    assert len(store.objects) == 1
    with pytest.raises(ValueError, match='order'):
        pages.append(first, [entry(2)])
    store.objects[first['key']] = b'corrupt'
    with pytest.raises(ValueError, match='identity'):
        list(CapturePages(store).entries(first))
