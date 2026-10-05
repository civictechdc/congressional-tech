"""Download files ahead without admitting their payloads to memory early."""
import asyncio
import threading

import pytest

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from congress_api.parsers.archive_links import inspect_capture
from test_raw_source_sync import response
from test_async_capture import AsyncMemoryStore, receipts


def test_downloads_fill_separate_spool_while_processing_waits():
    async def check():
        downloaded, upload_started = threading.Event(), asyncio.Event()
        release = asyncio.Event()
        calls, reads = [], []

        def fetch(url, *, before_read):
            calls.append(url)  # Native download has finished; its file stays on disk.
            if len(calls) == 4:
                downloaded.set()
            before_read()
            reads.append(url)
            result = response(url, b'%PDF-1.7\n' + url.encode() + b'\n%%EOF')
            return result, inspect_capture(result)

        async def upload(key, data):
            upload_started.set()
            await release.wait()

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'spooled'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(4)],
            fetch_spooled=fetch, workers=4, download_workers=4, max_bytes=1024**2,
            max_buffer_bytes=4*1024**2, max_spool_bytes=10*1024**2))
        try:
            assert await asyncio.to_thread(downloaded.wait, 2)
            await asyncio.wait_for(upload_started.wait(), 2)
            assert len(reads) == 1
            assert not receipts(store)
        finally:
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['saved'] == 4
        assert result['peak_body_payload_reservation_bytes'] <= 4*1024**2
        assert result['peak_spool_reservation_bytes'] <= 10*1024**2

    asyncio.run(check())


def test_spool_budget_blocks_new_downloads_until_files_are_consumed():
    async def check():
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def fetch(url, *, before_read):
            calls.append(url)
            entered.set()
            assert release.wait(3)
            before_read()
            result = response(url, b'%PDF-1.7\n' + url.encode() + b'\n%%EOF')
            return result, inspect_capture(result)

        async def upload(*args):
            pass

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'disk-bound'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(4)],
            fetch_spooled=fetch, workers=4, max_bytes=1024**2,
            max_spool_bytes=3*1024**2))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await asyncio.sleep(.02)
            assert len(calls) == 1
        finally:
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['saved'] == 4
        assert result['peak_spool_reservation_bytes'] <= 3*1024**2

    asyncio.run(check())


@pytest.mark.parametrize('cancel', [False, True])
def test_stop_drains_files_waiting_for_memory_without_more_downloads(cancel):
    async def check():
        downloaded, release = threading.Event(), threading.Event()
        stop = threading.Event()
        calls = []

        def fetch(url, *, before_read):
            calls.append(url)
            if len(calls) == 4:
                downloaded.set()
            assert release.wait(3)
            before_read()
            result = response(url, b'%PDF-1.7\n' + url.encode() + b'\n%%EOF')
            return result, inspect_capture(result)

        async def upload(*args):
            await asyncio.sleep(.01)

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'stop-spool'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(12)],
            fetch_spooled=fetch, workers=8, download_workers=4, max_bytes=1024**2,
            max_buffer_bytes=4*1024**2, stop=stop))
        try:
            assert await asyncio.to_thread(downloaded.wait, 2)
            if cancel:
                task.cancel()
                await asyncio.sleep(0)
            else:
                stop.set()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError if cancel else InterruptedError):
            await asyncio.wait_for(task, 5)
        assert len(calls) == len(receipts(store)) == 4
        assert len(Archive(store, 'resume').captures) == 4

    asyncio.run(check())


def test_spooled_inspection_is_reused_by_the_collector(monkeypatch):
    from congress_api.acquisition import raw_sync

    def forbidden(*args, **kwargs):
        pytest.fail('Capture was inspected again after the fetcher classified it')

    monkeypatch.setattr(raw_sync, 'inspect_capture', forbidden)

    def fetch(url, *, before_read):
        before_read()
        result = response(url, b'%PDF-1.7\n%%EOF')
        return result, inspect_capture(result)

    async def upload(*args):
        pass

    store = AsyncMemoryStore(upload)
    result = asyncio.run(run_async(Archive(store, 'one-inspection'),
        [{'url': 'https://example.gov/one.pdf'}], fetch_spooled=fetch))
    assert result['saved'] == 1
