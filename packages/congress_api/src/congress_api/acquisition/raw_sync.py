"""Bounded acquisition: concurrent body I/O, one durable metadata collector."""

import asyncio
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
import heapq
import multiprocessing
import time

import pyarrow.compute as pc

from congress_api.models.content import RawContent
from congress_api.parsers.archive_links import inspect_capture
from congress_api.retention.raw_archive import (
    BodyLimitExceeded, prepare_capture, body_payload, existing_body_info, metadata_body_keys,
    NON_DOWNLOAD_OUTCOMES,
)
from congress_api.retention import raw_progress as progress
from congress_api.retention.capture_metadata import BODY_LIMIT, CaptureMetadata, read_document
from congress_api.retention.r2 import threaded_bodies


class _ByteBudget:
    """Event-loop-owned reservations; readers wait before materializing bytes."""
    def __init__(self, capacity, changed):
        self.capacity, self.changed = capacity, changed
        self.used = self.peak = 0
        self.available = asyncio.Event()

    def fits(self, amount):
        return self.used + amount <= self.capacity

    def take(self, amount):
        assert self.fits(amount)
        self.used += amount
        self.peak = max(self.peak, self.used)

    async def acquire(self, amount):
        while not self.fits(amount):
            self.available.clear()
            await self.available.wait()
        self.take(amount)

    def release(self, amount):
        assert 0 <= amount <= self.used
        self.used -= amount
        self.available.set()
        self.changed.set()


def run_sync(archive, seeds, **options):
    """Synchronous CLI boundary; the capture lifecycle runs on one event loop."""
    return asyncio.run(run_async(archive, seeds, **options))


async def run_async(
    archive, seeds, *, fetch=None, fetch_spooled=None, limit=5000, workers=8, max_seconds=5400,
    stop=None, max_bytes=64 * 1024**2, max_buffer_bytes=2 * 1024**3,
    download_workers=16, max_spool_bytes=2 * 1024**3, metadata_workers=3, initial_only=False,
):
    # Reserve for a direct body plus the bounded Zyte response and decoded body.
    # After separation, retain only the actual distinct byte payload reservation.
    reservation = max_bytes * 3 + 1024**2
    if max_buffer_bytes < reservation:
        raise ValueError('Body buffer must hold three maximum file sizes plus 1 MiB')
    if workers < 1 or download_workers < 1 or metadata_workers < 1:
        raise ValueError('Capture workers must be positive')
    if (fetch is None) == (fetch_spooled is None):
        raise ValueError('Supply exactly one capture fetcher')
    # One native response file per capture at a time, including provider JSON.
    spool_reservation = max_bytes * 4 // 3 + 1024**2
    if fetch_spooled is not None and max_spool_bytes < spool_reservation:
        raise ValueError('Spool buffer must hold one maximum provider response')
    context = {}
    for item in seeds:
        url = archive.seed(item, publisher_link=True)
        if url:
            context.setdefault(url, []).append(item)
    now = datetime.now(timezone.utc)
    queue = deque(sorted(
        (s for s in archive.state.values()
         if (s['outcome'] == 'pending' if initial_only else s['outcome'] not in NON_DOWNLOAD_OUTCOMES)
         and (not s.get('next_attempt_at') or datetime.fromisoformat(s['next_attempt_at']) <= now)),
        key=lambda s: (s['outcome'] == 'retained', s.get('checked_at') or '', s['url'])))
    scheduled = {s['url'] for s in queue}
    delayed, retries = [], Counter()
    deadline = time.monotonic() + max_seconds
    counts, timings = Counter(), Counter()
    active, uploads, readings = set(), {}, {}
    ready = asyncio.Queue()
    changed = asyncio.Event()
    memory = _ByteBudget(max_buffer_bytes, changed)
    spool = _ByteBudget(max_spool_bytes, changed)
    submitted = downloading = 0
    fatal, collector_error = False, None
    metadata = CaptureMetadata(archive.store, archive.run_id)
    archive.metadata = metadata
    loop = asyncio.get_running_loop()
    reader_slots = asyncio.Semaphore(metadata_workers)

    def acquire(state, before_read):
        if state.get('body_key') and not state.get('links_scanned'):
            try:
                body = archive.body(state, max_bytes=max_bytes)
            except BodyLimitExceeded:
                return dict(requested_url=state['url'], url=state['url'],
                    retrieved_at=state.get('retrieved_at'), http_status=state.get('http_status'),
                    complete=False, error='retained_body_limit',
                    retained_body_key=state['body_key']), 'replay', None
            return dict(requested_url=state['url'], url=state['url'],
                http_status=state.get('http_status'), complete=True,
                retrieved_at=state.get('retrieved_at'),
                content=RawContent.from_bytes(body, state.get('media_type') or '').source_dict()), 'replay', None
        if fetch_spooled is not None:
            response, inspection = fetch_spooled(state['url'], before_read=before_read)
            return response, 'fetch', inspection
        return fetch(state['url']), 'fetch', None

    def prepare(response, mode, observations, inspection):
        outcome, links = (('retry_later', []) if response.get('retry_later') else
            inspection if inspection is not None else inspect_capture(response, replay=mode == 'replay'))
        for link in links:
            link['parent_url'] = response['requested_url']
            link['parent_sha256'] = response.get('content', {}).get('sha256')
        return prepare_capture(response, outcome=outcome, links=links, mode=mode,
                               context={'observations': observations}, scanned=outcome != 'inspection_deferred',
                               max_payload_bytes=reservation)

    def commit(result):
        record, captures, scanned, results = result
        for reading in results.values():
            if reading is None:
                metadata.counts['reused'] += 1
            else:
                metadata.accept(reading)
        archive.record_prepared(record, captures, scanned=scanned)
        if metadata.flush_due():
            archive.flush()

    async def in_writer(call, *args):
        # Do not let cancellation race a still-running writer with final save().
        future = loop.run_in_executor(writer_pool, partial(call, *args))
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await future
            raise

    async def collect(task):
        nonlocal fatal, collector_error
        try:
            result = task.result()
        except Exception as error:
            collector_error = collector_error or error
            fatal = True
            counts['collector_failed_tasks'] += 1
            progress.advance('collector_failed_tasks')
            return
        await in_writer(commit, result)
        record, _, _, results = result
        for key in results:
            readings.pop(key, None)
        outcome, mode = record['outcome'], record['mode']
        if outcome == 'retry_later' and retries[record['requested_url']] < 3:
            url = record['requested_url']
            retries[url] += 1
            heapq.heappush(delayed, (
                time.monotonic() + record['retry_later']['delay_seconds'], url))
        counts[outcome] += 1
        counts[mode] += 1
        counts['zyte_fallbacks'] += bool(record.get('prior_attempts'))
        progress.advance('capture_tasks_completed')
        progress.advance('usable_capture_results', int(outcome == 'saved'))
        progress.report('acquire_sources', completed=counts['fetch'] + counts['replay'], unit='capture_attempts')
        for link in record['links']:
            child = archive.state.get(link['url'])
            if child and child['outcome'] == 'pending' and child['url'] not in scheduled:
                queue.append(child)
                scheduled.add(child['url'])
        if record.get('provider_http_status') in (401, 403):
            fatal = True

    def completed(task):
        ready.put_nowait(task)
        changed.set()

    progress.report('acquire_sources', completed=0, unit='capture_attempts')
    with (ThreadPoolExecutor(max_workers=workers) as fetch_pool,
          ThreadPoolExecutor(max_workers=2) as cpu_pool,
          ProcessPoolExecutor(max_workers=metadata_workers,
                              mp_context=multiprocessing.get_context('spawn')) as reader_pool,
          ThreadPoolExecutor(max_workers=1) as writer_pool):
        body_context = getattr(archive.store, 'async_bodies', lambda: threaded_bodies(archive.store))
        try:
            async with body_context() as bodies:
                async def upload(data):
                    payload, info = await loop.run_in_executor(cpu_pool, body_payload, data)
                    started = time.monotonic()
                    created = await bodies.put(info['body_key'], payload)
                    if created is False:
                        actual = await bodies.read(info['body_key'])
                        info = await loop.run_in_executor(cpu_pool, existing_body_info, actual, info)
                    timings['body_upload_seconds'] += time.monotonic() - started
                    counts['body_uploads'] += 1
                    # Only this event loop mutates confirmed body identities.
                    archive.body_info[info['sha256']] = info
                    return info

                async def read_metadata(data, key):
                    started = time.monotonic()
                    if len(data) > BODY_LIMIT:
                        # A size-limit result needs no parsing or process copy.
                        result = metadata.reading(data, key)
                    else:
                        # Bound process copies as well as active readers. Bytes
                        # waiting for a slot remain in the parent's body budget.
                        async with reader_slots:
                            result = await loop.run_in_executor(reader_pool, read_document,
                                data, key, metadata.fingerprint, metadata.inspect)
                    timings['metadata_seconds'] += time.monotonic() - started
                    return result

                async def retain(key, data):
                    digest = key.rsplit('/', 1)[-1].removesuffix('.gz')
                    if digest in archive.body_info:
                        return archive.body_info[digest]
                    if key not in uploads:
                        uploads[key] = asyncio.create_task(upload(data))
                    task = uploads[key]
                    try:
                        return await asyncio.shield(task)
                    finally:
                        if task.done() and not task.cancelled() and task.exception() is None:
                            uploads.pop(key, None)

                async def process(state, spooled):
                    nonlocal downloading
                    held = 0 if spooled else reservation

                    async def reserve_memory():
                        nonlocal held
                        if not held:
                            await memory.acquire(reservation)
                            held = reservation

                    def before_read():
                        # Rust has finished writing a file. Its bytes stay on
                        # disk while this thread waits for processing capacity.
                        asyncio.run_coroutine_threadsafe(reserve_memory(), loop).result()

                    try:
                        started = time.monotonic()
                        try:
                            response, mode, inspection = await loop.run_in_executor(fetch_pool, acquire, state, before_read)
                        finally:
                            if spooled:
                                spool.release(spool_reservation)
                                downloading -= 1
                        timings['acquire_seconds'] += time.monotonic() - started
                        started = time.monotonic()
                        record, captures, data, scanned = await loop.run_in_executor(
                            cpu_pool, prepare, response, mode, context.get(state['url'], []), inspection)
                        del response
                        timings['prepare_seconds'] += time.monotonic() - started
                        size = sum(len(value) for value in data.values())
                        if size > held:
                            raise ValueError('Capture exceeded its reserved body payload budget')
                        memory.release(held - size)
                        held = size
                        changed.set()
                        keys = metadata_body_keys(record, captures)
                        reading_tasks = {}
                        for key in keys:
                            if key not in metadata.seen:
                                if key not in readings:
                                    readings[key] = asyncio.create_task(read_metadata(data[key], key))
                                reading_tasks[key] = readings[key]
                        pending = [retain(k, v) for k, v in data.items()]
                        pending.extend(asyncio.shield(task) for task in reading_tasks.values())
                        # Reading and retention share bytes, but neither needs
                        # the other's result. Both must finish before commit.
                        results = await asyncio.gather(*pending, return_exceptions=True)
                        for result in results:
                            if isinstance(result, BaseException):
                                raise result
                        return record, captures, scanned, {
                            key: reading_tasks[key].result() if key in reading_tasks else None
                            for key in keys}
                    finally:
                        memory.release(held)

                try:
                    while queue or active or delayed:
                        while delayed and delayed[0][0] <= time.monotonic():
                            _, url = heapq.heappop(delayed)
                            queue.appendleft(archive.state[url])
                        while (queue and not fatal and len(active) < workers and submitted < limit
                               and time.monotonic() < deadline and not (stop and stop.is_set())):
                            state = queue[0]
                            spooled = fetch_spooled is not None and not (
                                state.get('body_key') and not state.get('links_scanned'))
                            if spooled:
                                if downloading >= download_workers or not spool.fits(spool_reservation):
                                    break
                                spool.take(spool_reservation)
                                downloading += 1
                            else:
                                if not memory.fits(reservation):
                                    break
                                memory.take(reservation)
                            task = asyncio.create_task(process(queue.popleft(), spooled))
                            active.add(task)
                            task.add_done_callback(completed)
                            submitted += 1
                            progress.advance('capture_tasks_submitted')
                        if not active:
                            if (fatal or submitted >= limit or time.monotonic() >= deadline
                                    or (stop and stop.is_set()) or not delayed):
                                break
                            # Deferred attempts consume no worker, body or spool slot.
                            # A wait longer than this run belongs to the next checkpoint.
                            if delayed[0][0] >= deadline:
                                break
                        if ready.empty():
                            changed.clear()
                            try:
                                await asyncio.wait_for(changed.wait(), timeout=1)
                            except TimeoutError:
                                pass
                            if await in_writer(metadata.flush_due):
                                await in_writer(archive.flush)
                            continue
                        task = ready.get_nowait()
                        active.remove(task)
                        await collect(task)
                except BaseException:
                    # Finish admitted files before releasing the async client or
                    # saving indexes; no new files are admitted on this path.
                    await asyncio.gather(*active, return_exceptions=True)
                    for task in list(active):
                        try:
                            await collect(task)
                        except Exception:
                            pass  # Original failure remains authoritative.
                    raise
        finally:
            progress.report('save_capture_indexes')
            try:
                await in_writer(archive.save)
            finally:
                try:
                    await in_writer(metadata.writer.close)
                finally:
                    archive.metadata = None
    if collector_error is not None:
        raise collector_error
    if stop and stop.is_set():
        raise InterruptedError('Capture stopped; completed receipts and state were saved.')
    if fatal:
        raise RuntimeError('Zyte authorization failed; in-flight captures were retained before stopping.')
    return dict(
        counts,
        body_metadata=dict(metadata.counts),
        stage_seconds=dict(timings),
        peak_body_payload_reservation_bytes=memory.peak,
        peak_spool_reservation_bytes=spool.peak,
        accounting={
            "known_urls": len(archive.state),
            "known_urls_basis": "distinct normalized URLs in download state; includes source pages and retryable failures",
            "urls_by_source_family": dict(Counter(row.get("family") or "unknown" for row in archive.state.values())),
            "usable_capture_results_basis": "this run's completed tasks classified saved; includes linked source pages",
            "unique_retained_body_keys_basis": "distinct nonempty body keys referenced by the saved capture index; includes error/provider bytes and does not check storage existence",
            "excluded_media_urls": sum(row["outcome"] == "excluded_media" for row in archive.state.values()),
            "capture_tasks_submitted": submitted,
            "capture_tasks_completed": counts["fetch"] + counts["replay"],
            "fetch_tasks_completed": counts["fetch"],
            "retained_replays_completed": counts["replay"],
            "usable_capture_results": counts["saved"],
            "unique_retained_body_keys": pc.count_distinct(pc.filter(
                archive.captures["body_key"], pc.not_equal(archive.captures["body_key"], "")
            )).as_py(),
            "url_outcomes": dict(Counter(row["outcome"] for row in archive.state.values())),
        },
        attempted=submitted,
        initial_only=initial_only,
        known_urls=len(archive.state),
        remaining=sum(
            s["outcome"] not in NON_DOWNLOAD_OUTCOMES
            for s in archive.state.values()
        ),
        limit=limit,
        transport_budget_seconds=max_seconds,
    )
