"""Own PDF decoding until it finishes or its request stops.

Only decoding runs in the child. Verified-body fetches, cache publication and
response slicing keep their existing owners and never run in a killed process.
"""
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import signal
import subprocess
import sys
from threading import Event
import time

import anyio

from .models import ExplorerError

_CANCELLED = ContextVar('body_read_cancelled', default=None)
_PROCESS_OWNED = ContextVar('pdf_process_owned', default=False)

# Keep this small, independent of the parser's interpreter/GIL. This adapts
# scripts/measure/process_rss.py's owned-group leader without its measurement
# machinery: the installed wheel must not import repository-only scripts.
_OWNER = '''import os, signal, subprocess, sys, time
parent, deadline = int(sys.argv[1]), float(sys.argv[2])
group = os.getpgrp()
stopping = False
def requested(*args):
    global stopping
    stopping = True
signal.signal(signal.SIGTERM, requested)
if os.getppid() != parent or time.monotonic() >= deadline:
    raise SystemExit(1)
process = subprocess.Popen(sys.argv[3:])
while True:
    if stopping or os.getppid() != parent or time.monotonic() >= deadline:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        os.killpg(group, signal.SIGTERM)
        try:
            process.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        os.killpg(group, signal.SIGKILL)
    code = process.poll()
    if code is not None:
        raise SystemExit(code)
    time.sleep(.02)
'''


@contextmanager
def owned_pdf_process():
    """Reuse an extraction worker whose caller already owns its hard limits."""
    token = _PROCESS_OWNED.set(True)
    try:
        yield
    finally:
        _PROCESS_OWNED.reset(token)


async def run_body_read(function):
    """Signal even raw task cancellation, then wait for decoder cleanup."""
    cancelled, started, finished = Event(), Event(), Event()

    def run():
        started.set()
        token = _CANCELLED.set(cancelled)
        try:
            if not cancelled.is_set():
                return function()
        finally:
            _CANCELLED.reset(token)
            finished.set()

    try:
        return await anyio.to_thread.run_sync(run, abandon_on_cancel=True)
    except BaseException:
        cancelled.set()
        # A queued thread that has not started will see cancelled before doing
        # any work. An active thread must reap its decoder before we return.
        with anyio.CancelScope(shield=True):
            while started.is_set() and not finished.is_set():
                try:
                    await anyio.sleep(.01)
                except anyio.get_cancelled_exc_class():
                    # Raw asyncio.Task.cancel() can be repeated even inside an
                    # AnyIO shield. Finish cleanup before forwarding the first.
                    continue
        raise


def extract_pdf_pages(payload, *, deadline=None, backend_info=None):
    from .body_reader import MAX_BODY_BYTES, _check_deadline

    deadline = deadline if deadline is not None else time.monotonic() + 15
    cancelled = _CANCELLED.get()

    def check():
        _check_deadline(deadline)
        if cancelled is not None and cancelled.is_set():
            raise TimeoutError('Document text read cancelled; PDF decoder stopped')

    check()
    if len(payload) > MAX_BODY_BYTES:
        raise ExplorerError('PDF body exceeds size limit')
    if payload.find(b'%PDF-', 0, 1024) < 0:
        raise ExplorerError('Invalid or corrupt PDF body')
    if _PROCESS_OWNED.get():
        # Offline extraction already has a process-family RSS/deadline owner.
        # A new session would leave that owner's accounting and kill group.
        from .body_reader import _decode_pdf_pages
        return _decode_pdf_pages(payload, deadline=deadline, backend_info=backend_info)
    # The application supports macOS and Linux. A new session owns both the
    # independent owner monitor, decoder and any Poppler fallback it starts.
    with subprocess.Popen(
        [sys.executable, '-I', '-c', _OWNER, str(os.getpid()), str(deadline),
         sys.executable, '-m', __name__, str(deadline)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process, ThreadPoolExecutor(max_workers=1) as transfer_worker:
        try:
            # Keep one transfer alive. A retry without input can leave the
            # unwritten bytes stranded while the decoder waits for stdin EOF.
            transfer = transfer_worker.submit(process.communicate, payload)
            while not transfer.done():
                check()
                wait((transfer,), timeout=.02)
            output, _ = transfer.result()
            check()
            if process.returncode:
                raise ExplorerError('PDF decoder exited before completing the read')
            if len(output) > MAX_BODY_BYTES:
                raise ExplorerError('Decoded PDF text exceeds size limit')
            value = json.loads(output)
            if value.get('timeout'):
                raise TimeoutError(value['error'])
            if 'error' in value:
                raise ExplorerError(value['error'])
            if backend_info is not None:
                backend_info.update(value['backend'])
            return value['pages']
        finally:
            # Let subprocess.run reap a Poppler child before killing the whole
            # group. A stuck parser may ignore TERM, so KILL remains mandatory.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                # The leader gives the decoder .2 seconds, then reaps it.
                process.wait(timeout=.4)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def main():
    from .body_reader import MAX_BODY_BYTES, _decode_pdf_pages
    from .release import encoded

    def interrupt(signum, frame):
        # BaseException propagates through subprocess.run's kill/wait cleanup
        # instead of being treated as an ordinary parser failure or fallback.
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupt)
    try:
        payload = sys.stdin.buffer.read(MAX_BODY_BYTES + 1)
        if len(payload) > MAX_BODY_BYTES:
            raise ExplorerError('PDF body exceeds size limit')
        backend = {}
        pages = _decode_pdf_pages(payload, deadline=float(sys.argv[1]), backend_info=backend)
        output = encoded(dict(pages=pages, backend=backend))
        if len(output) > MAX_BODY_BYTES:
            raise ExplorerError('Decoded PDF text exceeds size limit')
    except Exception as error:
        output = encoded(dict(error=str(error)[:4000], timeout=isinstance(error, TimeoutError)))
    sys.stdout.buffer.write(output)


if __name__ == '__main__':
    main()
