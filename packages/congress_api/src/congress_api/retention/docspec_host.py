"""Process ownership and bounded HTTP I/O for the maintained local DocSpec API."""
import atexit
from contextlib import contextmanager
from hashlib import sha256
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
from tempfile import TemporaryDirectory, TemporaryFile
import threading
import time
import weakref
from urllib.parse import urlsplit

import httpx


class DocSpecFailure(RuntimeError):
    """Native refusal or host failure, retaining its original diagnostic."""

    def __init__(self, command, result):
        self.command = tuple(command)
        self.returncode = result.returncode
        self.stderr = result.stderr
        self.status_code = None
        super().__init__(result.stderr.strip() or f'DocSpec exited {result.returncode}')


_hosts = weakref.WeakValueDictionary()
_lock = threading.RLock()


def acquire_host(command, environment, workspace, timeout):
    """Share custody only within this process and identical explicit settings."""
    def identity(path, *, contents=False):
        try:
            info = Path(path).stat()
            if contents:
                return sha256(Path(path).read_bytes()).digest()
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        except FileNotFoundError:
            return None  # Let native startup retain its missing-file diagnostic.

    inputs = tuple((option, identity(command[command.index(option) + 1], contents=True))
                   for option in ('--limits', '--remote') if option in command)
    settings = (tuple(command), environment, timeout, identity(command[0]), inputs)
    key = (os.getpid(), str(workspace))
    with _lock:
        host = _hosts.get(key)
        if host is None:
            host = Host(command, environment, timeout, settings)
            _hosts[key] = host
        elif host.settings != settings:
            raise ValueError('DocSpec workspace already has a host with different settings')
        host.check_alive()
        host.owners += 1
        return host


class Host:
    def __init__(self, command, environment, timeout, settings):
        self.settings = settings
        self.timeout = timeout
        self.owners = 0
        self.pid = os.getpid()
        self.closed = False
        self.log = TemporaryFile(mode='w+b')
        self.responses = set()
        self.readiness = TemporaryDirectory(prefix='docspec-host-')
        ready = Path(self.readiness.name) / 'ready.json'
        self.command = [*command, 'serve', '--bind', '127.0.0.1:0', '--ready-file', str(ready)]
        self.client = None
        self.process = None
        try:
            self.process = subprocess.Popen(self.command, env=environment,
                                            stdout=self.log, stderr=self.log)
            deadline = time.monotonic() + timeout
            while True:
                self.check_alive()
                try:
                    mode = ready.lstat().st_mode
                    if not stat.S_ISREG(mode) or mode & 0o077:
                        raise ValueError('DocSpec readiness record must be a private regular file')
                    with ready.open('rb') as record:
                        encoded = record.read(4097)
                    if len(encoded) > 4096:
                        raise ValueError('DocSpec readiness record exceeds its metadata allowance')
                    value = json.loads(encoded)
                except (FileNotFoundError, json.JSONDecodeError):
                    value = None  # The child may still be writing its one record.
                if value is not None:
                    address = self._ready_address(value)
                    self.client = httpx.Client(base_url=f'http://{address}',
                                               timeout=timeout, trust_env=False)
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('DocSpec host startup timed out')
                time.sleep(0.01)
            self.check_alive()
        except BaseException:
            self.close()
            raise

    def _ready_address(self, value):
        """Trust only the private record written by the owned native child."""
        if (not isinstance(value, dict) or value.get('protocol') != 'docspec-loopback'
                or type(value.get('version')) is not int or value['version'] != 1
                or type(value.get('pid')) is not int or value['pid'] != self.process.pid
                or not isinstance(value.get('capabilities'), list)
                or 'request-deadline' not in value['capabilities']):
            raise ValueError('DocSpec loopback protocol 1 with request-deadline support is required')
        address = value.get('address')
        if not isinstance(address, str):
            raise ValueError('DocSpec readiness requires an explicit bound loopback address')
        parsed = urlsplit(f'http://{address}')
        if (parsed.username is not None or parsed.password is not None or parsed.path
                or parsed.query or parsed.fragment or not parsed.port
                or not ipaddress.ip_address(parsed.hostname).is_loopback):
            raise ValueError('DocSpec readiness requires an explicit bound loopback address')
        return address

    def check_alive(self):
        if os.getpid() != self.pid:
            raise RuntimeError('DocSpec host cannot be used across a process fork')
        if self.closed:
            raise RuntimeError('DocSpec host is closed')
        if self.process is not None and self.process.poll() is not None:
            self.log.seek(0)
            diagnostic = self.log.read().decode('utf-8', errors='replace')
            if self.client is None:
                diagnostic = ('DocSpec loopback protocol 1 with request deadlines and '
                              '--ready-file is required.\n' + diagnostic)
            raise DocSpecFailure(self.command, subprocess.CompletedProcess(
                self.command, self.process.returncode, stderr=diagnostic))

    @contextmanager
    def stream(self, method, path, *, deadline=None, dispatch=None, **kwargs):
        self.check_alive()
        deadline = time.monotonic() + self.timeout if deadline is None else deadline
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')
        headers = dict(kwargs.pop('headers', {}))
        headers['docspec-timeout-ms'] = str(max(1, math.ceil(remaining * 1000)))
        if dispatch is not None:
            # From this point a failed response cannot establish whether native
            # work was admitted. Earlier startup/deadline failures send no request.
            dispatch['submitted'] = True
        with self.client.stream(method, path, headers=headers, timeout=remaining, **kwargs) as response:
            self.responses.add(response)
            try:
                yield response, deadline
            finally:
                self.responses.discard(response)

    def request(self, method, path, *, deadline=None, **kwargs):
        with self.stream(method, path, deadline=deadline, **kwargs) as (response, deadline):
            with ArrowResponse(response, deadline=deadline) as stream:
                body = stream.read()
            self.check_response(response, body=body)
            return json.loads(body)

    @staticmethod
    def check_response(response, *, body=None):
        if not response.is_success:
            if body is None:
                response.read()
            diagnostic = (response.text if body is None
                          else body.decode(response.encoding or 'utf-8', errors='replace'))
            error = DocSpecFailure([response.request.method, response.request.url.path],
                subprocess.CompletedProcess([], response.status_code, stderr=diagnostic))
            error.status_code = response.status_code
            raise error

    def release(self):
        with _lock:
            self.owners -= 1
            if not self.owners:
                self.close()

    def close(self):
        if self.closed or os.getpid() != self.pid:
            return
        self.closed = True
        key = (self.pid, self.command[self.command.index('--workspace') + 1])
        with _lock:
            if _hosts.get(key) is self:
                del _hosts[key]
        for response in tuple(self.responses):
            response.close()
        self.responses.clear()
        if self.client is not None:
            self.client.close()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=min(self.timeout, 5))
            except subprocess.TimeoutExpired:
                try:
                    self.process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    try:
                        self.process.kill()
                    except ProcessLookupError:
                        pass
                    self.process.wait()
        self.log.close()
        self.readiness.cleanup()


@atexit.register
def _close_hosts():
    for host in list(_hosts.values()):
        host.close()


class ArrowResponse(io.RawIOBase):
    """Expose an HTTP body as a bounded blocking Arrow input, without staging it."""

    def __init__(self, response, *, deadline=None):
        super().__init__()
        self.chunks = response.iter_bytes()
        self.pending = b''
        self.tail = b''
        self.deadline = deadline

    def check_deadline(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')

    def readable(self):
        return True

    def readinto(self, target):
        view = memoryview(target)
        count = 0
        while count < len(view):
            self.check_deadline()
            if not self.pending:
                try:
                    self.pending = next(self.chunks, b'')
                except httpx.TransportError:
                    self.check_deadline()
                    raise
                self.check_deadline()
                if not self.pending:
                    break
            length = min(len(self.pending), len(view) - count)
            piece = self.pending[:length]
            view[count:count + length] = piece
            self.tail = (self.tail + piece)[-8:]
            self.pending = self.pending[length:]
            count += length
        return count

    def finish(self):
        """Require both Arrow's success terminator and complete HTTP framing."""
        if self.read(1) or self.tail != b'\xff\xff\xff\xff\x00\x00\x00\x00':
            raise OSError('DocSpec Arrow response lacks a complete stream terminator')
