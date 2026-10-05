"""Capture overlaps storage waits and drains only admitted, bounded work."""
import asyncio
from contextlib import asynccontextmanager
import gzip
import hashlib
import json
import threading

import pytest

from congress_api.acquisition.raw_sync import run_async
from congress_api.retention.raw_archive import Archive
from congress_api.retention.capture_metadata import CaptureMetadata
from test_raw_source_sync import MemoryStore, response


class AsyncMemoryStore(MemoryStore):
    def __init__(self, upload):
        super().__init__()
        self.upload = upload

    @asynccontextmanager
    async def async_bodies(self):
        owner = self

        class Bodies:
            async def put(self, key, data):
                await owner.upload(key, data)
                return owner.put(key, data, immutable=True)

            async def read(self, key):
                return owner.read(key)

        yield Bodies()


def receipts(store):
    return [json.loads(line) for key in store.keys('receipts/')
            for line in gzip.decompress(store.read(key)).splitlines()]


def test_uploads_overlap_and_receipts_wait_for_confirmation():
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        uploads = []

        async def upload(key, data):
            uploads.append(key)
            if len(uploads) == 2:
                entered.set()
            await release.wait()

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'overlap'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(2)],
            fetch=lambda u: response(u, b'%PDF-1.7\n' + u.encode() + b'\n%%EOF'), workers=2, limit=2))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert not store.keys('receipts/')
            assert not store.keys('indexes/processing/body-results/')
        finally:
            release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['attempted'] == 2
        assert len(receipts(store)) == 2
        assert all(r['download_state']['body_key'] in store.objects for r in receipts(store))

    asyncio.run(check())


def test_stop_drains_uploads_without_admitting_more_files():
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        stop = threading.Event()
        calls = []

        async def upload(key, data):
            entered.set()
            await release.wait()

        def fetch(url):
            calls.append(url)
            return response(url, b'%PDF-1.7\n' + url.encode() + b'\n%%EOF')

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'drain'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(10)],
            fetch=fetch, workers=2, limit=10, stop=stop))
        await asyncio.wait_for(entered.wait(), 2)
        stop.set()
        release.set()
        with pytest.raises(InterruptedError):
            await asyncio.wait_for(task, 5)
        assert len(calls) == len(receipts(store)) == 2
        assert Archive(store, 'resume').state[calls[0]]['outcome'] == 'saved'

    asyncio.run(check())


def test_upload_failure_drains_other_success_without_receipting_failed_body():
    async def check():
        both = asyncio.Event()
        entered = []

        async def upload(key, data):
            entered.append(key)
            if len(entered) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            if b'/0.pdf' in gzip.decompress(data):
                raise OSError('storage interrupted')

        store = AsyncMemoryStore(upload)
        with pytest.raises(OSError, match='storage interrupted'):
            await run_async(Archive(store, 'failure'),
                [{'url': f'https://example.gov/{i}.pdf'} for i in range(2)],
                fetch=lambda u: response(u, b'%PDF-1.7\n' + u.encode() + b'\n%%EOF'), workers=2, limit=2)
        row, = receipts(store)
        assert row['record']['requested_url'].endswith('/1.pdf')

    asyncio.run(check())


def test_byte_budget_applies_backpressure_before_fetching():
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def upload(key, data):
            entered.set()
            await release.wait()

        def fetch(url):
            calls.append(url)
            return response(url, b'%PDF-1.7\n' + url.encode() + b'\n%%EOF')

        store = AsyncMemoryStore(upload)
        capacity = 4 * 1024**2
        task = asyncio.create_task(run_async(Archive(store, 'budget'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(3)], fetch=fetch,
            workers=8, limit=3, max_bytes=1024**2, max_buffer_bytes=capacity))
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.sleep(0.02)
        assert len(calls) == 1
        release.set()
        result = await asyncio.wait_for(task, 5)
        assert result['attempted'] == 3
        assert result['peak_body_payload_reservation_bytes'] <= capacity

    asyncio.run(check())


def test_task_cancellation_drains_and_checkpoints_admitted_files():
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        uploads = []

        async def upload(key, data):
            uploads.append(key)
            if len(uploads) == 2:
                entered.set()
            await release.wait()

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'cancel'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(10)],
            fetch=lambda u: response(u, b'%PDF-1.7\n' + u.encode() + b'\n%%EOF'), workers=2))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert len(receipts(store)) == len(uploads) == 2
        assert len(Archive(store, 'resume').captures) == 2

    asyncio.run(check())


def test_same_body_is_uploaded_and_interpreted_once_across_concurrent_aliases():
    async def check():
        uploads = []

        async def upload(key, data):
            uploads.append(key)
            await asyncio.sleep(0.01)

        store = AsyncMemoryStore(upload)
        result = await run_async(Archive(store, 'aliases'),
            [{'url': f'https://example.gov/{i}.pdf'} for i in range(8)],
            fetch=lambda u: response(u, b'%PDF-1.7\n%%EOF'), workers=8, limit=8)
        assert len(uploads) == 1
        assert len(receipts(store)) == 8
        assert result['body_metadata'] == {'failed': 1, 'reused': 7}

    asyncio.run(check())


def test_metadata_reading_and_upload_overlap_for_one_file(monkeypatch):
    from congress_api.acquisition import raw_sync
    reading, release = threading.Event(), threading.Event()

    class PausedReader(CaptureMetadata):
        def reading(self, data, key):
            reading.set()
            assert release.wait(3), 'Upload never overlapped the document reader'
            return super().reading(data, key)

    monkeypatch.setattr(raw_sync, 'CaptureMetadata', PausedReader)

    async def check():
        uploaded = asyncio.Event()

        async def upload(key, data):
            assert await asyncio.to_thread(reading.wait, 2)
            uploaded.set()

        store = AsyncMemoryStore(upload)
        task = asyncio.create_task(run_async(Archive(store, 'reader-overlap'),
            [{'url': 'https://example.gov/one.pdf'}], workers=1,
            fetch=lambda u: response(u, b'%PDF-1.7\n%%EOF')))
        try:
            await asyncio.wait_for(uploaded.wait(), 1)
            assert not store.keys('receipts/')
            assert not store.keys('indexes/processing/body-results/')
        finally:
            release.set()
            await task
        assert len(receipts(store)) == 1

    asyncio.run(check())


@pytest.mark.parametrize('corrupt', [False, True])
def test_async_conflict_verifies_and_preserves_existing_body(corrupt):
    async def check():
        raw = b'%PDF-1.7\nretained before its receipt\n%%EOF'
        digest = hashlib.sha256(raw).hexdigest()
        key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        original = gzip.compress(b'wrong bytes' if corrupt else raw, compresslevel=9, mtime=19)

        class OrphanStore(MemoryStore):
            @asynccontextmanager
            async def async_bodies(self):
                owner = self

                class Bodies:
                    async def put(self, actual_key, payload):
                        assert actual_key == key
                        return False

                    async def read(self, actual_key):
                        assert actual_key == key
                        return owner.read(key)

                yield Bodies()

        store = OrphanStore()
        store.objects[key] = original
        archive = Archive(store, 'orphan')
        run = run_async(archive, [{'url': 'https://example.gov/orphan.pdf'}],
                        fetch=lambda u: response(u, raw))
        if corrupt:
            with pytest.raises(ValueError, match='Stored body checksum mismatch'):
                await run
            assert not receipts(store)
            assert not store.keys('indexes/processing/body-results/')
            assert digest not in archive.body_info
        else:
            result = await run
            assert result['saved'] == 1
            assert archive.body_info[digest]['stored_sha256'] == hashlib.sha256(original).hexdigest()
            assert archive.body_info[digest]['stored_bytes'] == len(original)
            assert len(receipts(store)) == 1
        assert store.objects[key] == original

    asyncio.run(check())
