"""Run one initialized parser with bounded inputs, output, time and sampled RSS.

This supervisor performs no storage reads, joins or provenance writes. A normal
parser result, including a rejection row, completes its input. Only process or
resource failures trigger the single retry. Exhausted GETs stop the caller without
worker replay or an unreadable verdict. This is resource control, not a sandbox.
"""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import threading
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

from congress_api.retention.process_resources import resident_bytes,virtual_bytes
from congress_api.retention.concurrency import completed_map
from congress_api.retention.r2 import R2GetTransportExhausted


class _Failure(Exception):
    pass


def _address_space_limits(current_virtual_bytes,memory_bytes,hard_limit,*,infinity):
    """Leave one configured growth allowance above the initialized process."""
    if (type(current_virtual_bytes) is not int or current_virtual_bytes<=0
            or type(memory_bytes) is not int or memory_bytes<=0
            or type(hard_limit) is not int or type(infinity) is not int
            or (hard_limit<0 and hard_limit!=infinity)):
        raise ValueError('Address-space baseline, budget and inherited limit must be valid bytes')
    ceiling=current_virtual_bytes+memory_bytes
    if hard_limit!=infinity and ceiling>hard_limit:
        raise ValueError('The inherited address-space hard limit cannot fit the parser baseline and budget')
    return ceiling,ceiling


@contextlib.contextmanager
def reading_input():
    """Mark bounded raw I/O so an interrupted read cannot settle an input."""
    marker = os.environ.get('DOCSPEC_PARSER_IO_MARKER')
    if marker is None:
        raise RuntimeError('Raw read phase requires a supervised parser')
    path = Path(marker)
    path.touch()
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


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
        """Return parser results; propagate transport refusals without replay."""
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
                    (Path(self._directory.name) / 'phase').unlink(missing_ok=True)
                    # One tiny command, one input in flight: never block on input bytes.
                    if os.write(self._process.stdin.fileno(), b'parse\n') != 6:
                        raise _Failure('parser_crash')
                    response = self._response(time.monotonic() + self.timeout_seconds)
                    if not isinstance(response, dict):
                        raise _Failure('parser_crash')
                    if response.get('failure')=='transport_exhausted':
                        if set(response)!={'failure','message'} or not isinstance(response['message'],str):
                            raise RuntimeError('Invalid fatal transport response from parser worker')
                        raise R2GetTransportExhausted(response['message'])
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
                reading = (Path(self._directory.name) / 'phase').exists()
                if reading:
                    return {'status': 'read_error', 'reason': reason}
                if attempt == 1:
                    return {'status': 'unreadable', 'reason': reason, 'attempts': 2}
        except BaseException:
            self._stop()
            raise
        finally:
            path.unlink(missing_ok=True)



class ParserWorkerPool:
    """Bounded completed calls through independent maintained parser supervisors."""

    @staticmethod
    def validate_budget(workers,memory_budget,memory_bytes):
        if (type(workers) is not int or not 1<=workers<=32
                or type(memory_budget) is not int or memory_budget<=0
                or type(memory_bytes) is not int or memory_bytes<=0
                or workers*memory_bytes>memory_budget):
            raise ValueError('Parser workers1–32 and their combined memory must fit the explicit budget')

    def __init__(self,parser,version,callable_path,*,workers,memory_budget,
                 worker_factory=ParserWorker,**limits):
        self.validate_budget(workers,memory_budget,limits.get('memory_bytes'))
        # Reuse admission without starting a subprocess.
        ParserWorker(parser,version,callable_path,**limits)
        self.args=(parser,version,callable_path);self.limits=limits
        self.workers=workers;self.worker_factory=worker_factory
        self._executor=None;self._local=threading.local();self._started=[];self._lock=threading.Lock()
        self._contexts=contextlib.ExitStack()

    def __enter__(self):
        if self._executor is not None:raise RuntimeError('Parser pool is already open')
        self._executor=ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='parser')
        return self

    def _invoke(self,function,item):
        worker=getattr(self._local,'worker',None)
        if worker is None:
            context=self.worker_factory(*self.args,**self.limits)
            worker=context.__enter__()
            self._local.worker=worker
            with self._lock:
                self._contexts.push(context);self._started.append(context)
        return function(worker,item)

    def map(self,function,items):
        """Refill completed slots; the native batch writer supplies final ordering."""
        if self._executor is None:raise RuntimeError('Parser pool requires an open context')
        yield from completed_map(self._executor,lambda item:self._invoke(function,item),
            items,max_pending=4*self.workers)

    def __exit__(self,*error):
        try:
            if self._executor is not None:self._executor.shutdown(wait=True,cancel_futures=True)
        finally:
            self._executor=None
            try:self._contexts.__exit__(*error)
            finally:self._started.clear()


def _child():
    callable_path, directory, memory, output = sys.argv[1:]
    os.environ['DOCSPEC_PARSER_IO_MARKER'] = str(Path(directory) / 'phase')
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
    protocol = sys.stdout
    def send(value):
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) + 1 > int(output):
            encoded = b'{"failure":"output_limit"}'
        protocol.buffer.write(encoded + b'\n')
        protocol.buffer.flush()
    # Imports and protocol initialization can reserve large virtual ranges.
    # Establish headroom once; persistent inputs must never raise a hard limit.
    if sys.platform.startswith('linux'):
        import resource
        limits=_address_space_limits(virtual_bytes(os.getpid()),int(memory),
            resource.getrlimit(resource.RLIMIT_AS)[1],infinity=resource.RLIM_INFINITY)
        resource.setrlimit(resource.RLIMIT_AS,limits)
    send({'ready': True})
    for command in sys.stdin:
        if command != 'parse\n':
            raise ValueError('Invalid worker command')
        try:
            with contextlib.redirect_stdout(sys.stderr):
                value = function((Path(directory) / 'input').read_bytes())
            send({'value': value})
            del value
        except R2GetTransportExhausted as error:
            message=str(error)
            if error.__cause__ is not None:
                message+=' ('+type(error.__cause__).__name__+': '+str(error.__cause__)+')'
            send(dict(failure='transport_exhausted',message=message))
            return
        except MemoryError:
            send({'failure': 'memory_limit'})
            return


if __name__ == '__main__':
    _child()
