"""Metadata workers use real spawned processes and preserve reader results."""

import asyncio
from functools import partial
import multiprocessing
import os
from pathlib import Path

import pytest

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.capture_metadata import CaptureMetadata, inspect_document, saved_readings
from congress_api.retention.raw_archive import Archive
from test_raw_source_sync import MemoryStore, response
from test_async_capture import AsyncMemoryStore, receipts


def synchronized_reader(data, *, barrier, pids):
    pids.append(os.getpid())
    barrier.wait(timeout=15)
    return inspect_document(data)


def test_three_readers_run_in_separate_processes_with_identical_metadata(monkeypatch):
    from congress_api.acquisition import raw_sync

    body = Path('tests/fixtures/meeting_inventory/senate-burma-hearing-cover.pdf').read_bytes()
    expected = inspect_document(body)
    # Trailing comments give each valid PDF a distinct identity without changing
    # the document. A barrier proves three readers are active simultaneously.
    with multiprocessing.get_context('spawn').Manager() as manager:
        pids = manager.list()
        inspect = partial(synchronized_reader, barrier=manager.Barrier(3), pids=pids)
        monkeypatch.setattr(raw_sync, 'CaptureMetadata', partial(CaptureMetadata, inspect=inspect))
        store = MemoryStore()
        result = asyncio.run(run_async(Archive(store, 'processes'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(3)],
            fetch=lambda u: response(u, body + b'\n% ' + u.encode()),
            workers=3, metadata_workers=3, limit=3))
        assert len(set(pids)) == 3
        assert os.getpid() not in pids
    assert result['body_metadata'] == {'completed': 3}
    rows = list(saved_readings(store))
    assert len(rows) == 3
    for row in rows:
        assert {key: row[key] for key in expected} == expected


def paused_reader(data, *, reading, release):
    reading.set()
    assert release.wait(10), 'Upload never overlapped the document reader'
    return inspect_document(data)


def test_metadata_reading_and_upload_overlap_for_one_file(monkeypatch):
    from congress_api.acquisition import raw_sync

    async def check(reading, release):
        uploaded = asyncio.Event()

        async def upload(key, data):
            assert await asyncio.to_thread(reading.wait, 10)
            uploaded.set()

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'reader-overlap'),
            [{'url': 'https://example.gov/one.pdf'}], workers=1,
            fetch=lambda u: response(u, b'%PDF-1.7\n%%EOF')))
        try:
            await asyncio.wait_for(uploaded.wait(), 10)
            assert not store.keys('receipts/')
            assert not store.keys('indexes/processing/body-results/')
        finally:
            release.set()
            await task
        assert len(receipts(store)) == 1

    with multiprocessing.get_context('spawn').Manager() as manager:
        reading, release = manager.Event(), manager.Event()
        inspect = partial(paused_reader, reading=reading, release=release)
        monkeypatch.setattr(raw_sync, 'CaptureMetadata', partial(CaptureMetadata, inspect=inspect))
        asyncio.run(check(reading, release))


def crashing_reader(data):
    if data.endswith(b'% crash'):
        os._exit(1)
    return inspect_document(data)


def test_process_crash_saves_completed_work_without_receipting_failed_reading(monkeypatch):
    from concurrent.futures.process import BrokenProcessPool
    from congress_api.acquisition import raw_sync

    monkeypatch.setattr(raw_sync, 'CaptureMetadata', partial(CaptureMetadata, inspect=crashing_reader))
    store = MemoryStore()
    body = Path('tests/fixtures/meeting_inventory/senate-burma-hearing-cover.pdf').read_bytes()
    urls = ['https://example.gov/0.pdf', 'https://example.gov/1.pdf']
    with pytest.raises(BrokenProcessPool):
        asyncio.run(run_async(Archive(store, 'crash'), [{'url': u} for u in urls],
            fetch=lambda u: response(u, body + (b'\n% crash' if u == urls[1] else b'')),
            workers=1, metadata_workers=1, limit=2))
    row, = receipts(store)
    assert row['record']['requested_url'] == urls[0]
    assert len(list(saved_readings(store))) == 1
    restored = Archive(store, 'resume')
    assert restored.state[urls[0]]['outcome'] == 'saved'
    assert restored.state[urls[1]]['outcome'] == 'pending'
