"""Run one initialized parser with bounded inputs, output, time and sampled RSS.

This supervisor performs no storage reads, joins or provenance writes. A normal
parser result, including a rejection row, completes its input. Only process or
resource failures trigger the single retry. This is resource control, not a sandbox.
"""
import contextlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from congress_api.retention.process_resources import resident_bytes


class _Failure(Exception):
    pass


class ParserWorker:
    """Own one persistent subprocess for one explicit parser/version pair."""

    def __init__(self, parser, version, callable_path, *, timeout_seconds,
                 memory_bytes, max_input_bytes, max_output_bytes=8 * 1024**2):
        if (not parser or not version or not callable_path or
                not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or
                any(type(n) is not int or n <= 0 for n in
                    (memory_bytes, max_input_bytes, max_output_bytes))):
            raise ValueError('Parser identity and positive finite bounds are required')
        self.parser, self.version, self.callable_path = parser, version, callable_path
        self.timeout_seconds, self.memory_bytes = timeout_seconds, memory_bytes
        self.max_input_bytes, self.max_output_bytes = max_input_bytes, max_output_bytes
        self._directory = self._process = None
        self._buffer = bytearray()

    def __enter__(self):
        if self._directory is not None:
            raise RuntimeError('Parser worker context is already open')
        self._directory = TemporaryDirectory(prefix='parser-worker-')
        try:
            self._start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        self._stop()
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

    def _stop(self):
        if self._process is not None:
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait()
            self._process.stdin.close()
            self._process.stdout.close()
            self._process = None
        self._buffer.clear()

    def _start(self):
        command = [sys.executable, '-I', str(Path(__file__).resolve()),
                   self.callable_path, self._directory.name,
                   str(self.memory_bytes), str(self.max_output_bytes)]
        self._process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self._process.stdout.fileno(), False)
        os.set_blocking(self._process.stdin.fileno(), False)
        try:
            ready = self._response(time.monotonic() + max(5, self.timeout_seconds))
            if ready != {'ready': True}:
                raise _Failure('parser_crash')
        except _Failure as exc:
            self._stop()
            raise RuntimeError('Parser startup failed') from exc

    def _response(self, deadline):
        with selectors.DefaultSelector() as selector:
            selector.register(self._process.stdout, selectors.EVENT_READ)
            while True:
                if b'\n' in self._buffer:
                    line, _, rest = self._buffer.partition(b'\n')
                    self._buffer = bytearray(rest)
                    try:
                        return json.loads(line)
                    except (ValueError, UnicodeError) as exc:
                        raise _Failure('parser_crash') from exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _Failure('timeout')
                if resident_bytes(self._process.pid) > self.memory_bytes:
                    raise _Failure('memory_limit')
                for key, _ in selector.select(min(remaining, .05)):
                    chunk = os.read(key.fd, min(65536, self.max_output_bytes + 1 - len(self._buffer)))
                    if not chunk:
                        raise _Failure('parser_crash')
                    self._buffer.extend(chunk)
                    if len(self._buffer) > self.max_output_bytes:
                        raise _Failure('output_limit')

    def parse(self, input_id, payload):
        """Return the reading or a stable failure for caller-owned provenance."""
        if self._directory is None:
            raise RuntimeError('Parser worker requires an open context')
        if not input_id or not isinstance(payload, bytes):
            raise ValueError('A named input and bytes are required')
        if len(payload) > self.max_input_bytes:
            return {'status': 'size_limit'}
        path = Path(self._directory.name) / 'input'
        path.write_bytes(payload)
        try:
            for attempt in range(2):
                if self._process is None:
                    self._start()
                try:
                    # One tiny command, one input in flight: never block on input bytes.
                    if os.write(self._process.stdin.fileno(), b'parse\n') != 6:
                        raise _Failure('parser_crash')
                    response = self._response(time.monotonic() + self.timeout_seconds)
                    if not isinstance(response, dict):
                        raise _Failure('parser_crash')
                    if response.get('failure') in ('memory_limit', 'output_limit'):
                        raise _Failure(response['failure'])
                    if set(response) != {'value'}:
                        raise _Failure('parser_crash')
                    return {'status': 'completed', 'value': response['value']}
                except (BrokenPipeError, BlockingIOError):
                    reason = 'parser_crash'
                except _Failure as exc:
                    reason = str(exc)
                self._stop()
                if attempt == 1:
                    return {'status': 'unreadable', 'reason': reason, 'attempts': 2}
        except BaseException:
            self._stop()
            raise
        finally:
            path.unlink(missing_ok=True)


def _child():
    callable_path, directory, memory, output = sys.argv[1:]
    module, name = callable_path.rsplit(':', 1)
    if module.endswith('.py'):
        spec = importlib.util.spec_from_file_location('parser_callable', module)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
    else:
        loaded = importlib.import_module(module)
    function = getattr(loaded, name)
    if not callable(function):
        raise TypeError('Parser callable required')
    if sys.platform == 'linux':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (int(memory), int(memory)))
    protocol = sys.stdout
    def send(value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) + 1 > int(output):
            encoded = b'{"failure":"output_limit"}'
        protocol.buffer.write(encoded + b'\n')
        protocol.buffer.flush()
    send({'ready': True})
    for command in sys.stdin:
        if command != 'parse\n':
            raise ValueError('Invalid worker command')
        try:
            with contextlib.redirect_stdout(sys.stderr):
                value = function((Path(directory) / 'input').read_bytes())
            send({'value': value})
            del value
        except MemoryError:
            send({'failure': 'memory_limit'})
            return


if __name__ == '__main__':
    _child()
