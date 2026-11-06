"""Own PDF decoding until it finishes or its request stops.

Only decoding runs in the child. Verified-body fetches, cache publication and
response slicing keep their existing owners and never run in a killed process.
"""
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
    # The application supports macOS and Linux. A new session owns both the
    # Python decoder and any Poppler fallback it starts.
    with subprocess.Popen(
        [sys.executable, '-m', __name__, str(deadline)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        try:
            pending_input = payload
            while True:
                check()
                try:
                    output, _ = process.communicate(input=pending_input, timeout=.02)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
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
                process.wait(timeout=.2)
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
