"""Process custody, loopback host lifecycle, and Arrow response streaming."""
import atexit
from collections.abc import Generator, Sequence
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
from typing import Any
from urllib.parse import urlsplit
import weakref

import httpx

from .binary import resolve_docspec_binary
from .models import (
    REQUIRED_LOOPBACK_CAPABILITIES,
    RESPONSE_LIMIT,
    DocSpecFailure,
)

_hosts: weakref.WeakValueDictionary[tuple[int, str], 'Host'] = weakref.WeakValueDictionary()
_lock = threading.RLock()


def acquire_host(
    command: Sequence[str],
    environment: dict[str, str] | None,
    workspace: Path | str,
    timeout: float,
    *,
    required_capabilities: Sequence[str] = REQUIRED_LOOPBACK_CAPABILITIES,
) -> 'Host':
    """Share custody only within this process and identical explicit settings."""
    def identity(path: Path | str, *, contents: bool = False) -> Any:
        try:
            info = Path(path).stat()
            if contents:
                return sha256(Path(path).read_bytes()).digest()
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
        except FileNotFoundError:
            return None  # Let native startup retain its missing-file diagnostic.

    capabilities = tuple(dict.fromkeys(required_capabilities))
    if not set(REQUIRED_LOOPBACK_CAPABILITIES).issubset(capabilities):
        raise ValueError('DocSpec loopback protocol 1 with request-deadline '
                         'and owned-stdin-eof support is required')
    cmd_list = list(command)
    inputs = tuple((option, identity(cmd_list[cmd_list.index(option) + 1], contents=True))
                   for option in ('--limits', '--remote') if option in cmd_list)
    settings = (tuple(command), environment, timeout, identity(cmd_list[0]), inputs, capabilities)
    key = (os.getpid(), str(workspace))
    with _lock:
        host = _hosts.get(key)
        if host is None:
            host = Host(command, environment, workspace, timeout, settings,
                        required_capabilities=capabilities)
            _hosts[key] = host
        elif host.settings != settings:
            raise ValueError('DocSpec workspace already has a host with different settings')
        host.check_alive()
        host.owners += 1
        return host


class ArrowResponse(io.RawIOBase):
    """Expose an HTTP body as a bounded blocking Arrow input, without staging it."""

    def __init__(self, response: httpx.Response, *, deadline: float | None = None) -> None:
        super().__init__()
        self.response = response
        self.chunks = response.iter_bytes()
        self.pending = b''
        self.tail = b''
        self.deadline = deadline

    def check_deadline(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')

    def readable(self) -> bool:
        return True

    def readinto(self, target: Any) -> int:
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

    def finish(self) -> None:
        """Require both Arrow's success terminator and complete HTTP framing."""
        if self.read(1) or self.tail != b'\xff\xff\xff\xff\x00\x00\x00\x00':
            diagnostic = json.dumps({
                'code': 'request_timeout',
                'message': 'DocSpec Arrow response lacks a complete stream terminator',
                'pre_admission': False,
            })
            cmd = [self.response.request.method, self.response.request.url.path] if hasattr(self, 'response') and self.response is not None else []
            err = DocSpecFailure(cmd, subprocess.CompletedProcess(cmd, 504, stderr=diagnostic))
            err.status_code = 504
            err.code = 'request_timeout'
            err.pre_admission = False
            raise err


class Host:
    def __init__(
        self,
        command: Sequence[str],
        environment: dict[str, str] | None,
        workspace: Path | str,
        timeout: float,
        settings: Any,
        *,
        required_capabilities: Sequence[str] = REQUIRED_LOOPBACK_CAPABILITIES,
    ) -> None:
        self.workspace = str(workspace)
        self.settings = settings
        self.timeout = timeout
        self.required_capabilities = tuple(required_capabilities)
        self.owners = 0
        self.pid = os.getpid()
        self.closed = False
        self.log = TemporaryFile(mode='w+b')
        self.responses: set[httpx.Response] = set()
        self.readiness = TemporaryDirectory(prefix='docspec-host-')
        ready = Path(self.readiness.name) / 'ready.json'
        self.command = [*command, 'serve', '--bind', '127.0.0.1:0', '--ready-file', str(ready),
                        '--shutdown-on-stdin-eof']
        self.client: httpx.Client | None = None
        self.process: subprocess.Popen[bytes] | None = None
        try:
            self.process = subprocess.Popen(self.command, env=environment,
                                            stdin=subprocess.PIPE,
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

    def _ready_address(self, value: Any) -> str:
        """Trust only the private record written by the owned native child."""
        required = set(REQUIRED_LOOPBACK_CAPABILITIES) | set(self.required_capabilities)
        if (not isinstance(value, dict) or value.get('protocol') != 'docspec-loopback'
                or type(value.get('version')) is not int or value['version'] != 1
                or type(value.get('pid')) is not int or self.process is None or value['pid'] != self.process.pid
                or not isinstance(value.get('capabilities'), list)
                or any(not isinstance(item, str) for item in value['capabilities'])
                or not required.issubset(value['capabilities'])):
            raise ValueError('DocSpec loopback protocol 1 with request-deadline '
                             'and owned-stdin-eof support is required')
        address = value.get('address')
        if not isinstance(address, str) or any(c.isspace() for c in address) or '%' in address:
            raise ValueError('DocSpec readiness requires an explicit bound loopback address')
        parsed = urlsplit(f'http://{address}')
        if (parsed.username is not None or parsed.password is not None or parsed.path
                or parsed.query or parsed.fragment or not parsed.port or parsed.hostname is None
                or not ipaddress.ip_address(parsed.hostname).is_loopback):
            raise ValueError('DocSpec readiness requires an explicit bound loopback address')
        return address

    def check_alive(self) -> None:
        if os.getpid() != self.pid:
            raise RuntimeError('DocSpec host cannot be used across a process fork')
        if self.closed:
            raise RuntimeError('DocSpec host is closed')
        if self.process is not None and self.process.poll() is not None:
            self.log.seek(0)
            diagnostic = self.log.read().decode('utf-8', errors='replace')
            if self.client is None:
                diagnostic = ('DocSpec loopback protocol 1 with request deadlines, '
                              '--ready-file and --shutdown-on-stdin-eof is required.\n' + diagnostic)
            raise DocSpecFailure(self.command, subprocess.CompletedProcess(
                self.command, self.process.returncode, stderr=diagnostic))

    @contextmanager
    def stream(
        self,
        method: str,
        path: str,
        *,
        deadline: float | None = None,
        dispatch: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Generator[tuple[httpx.Response, float], None, None]:
        self.check_alive()
        deadline = time.monotonic() + self.timeout if deadline is None else deadline
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('DocSpec response exceeded its wall-time limit')
        headers = dict(kwargs.pop('headers', {}))
        headers['docspec-timeout-ms'] = str(max(1, math.ceil(remaining * 1000)))
        if dispatch is not None:
            dispatch['submitted'] = True
        assert self.client is not None
        with self.client.stream(method, path, headers=headers, timeout=remaining, **kwargs) as response:
            self.responses.add(response)
            try:
                yield response, deadline
            finally:
                self.responses.discard(response)

    def request(self, method: str, path: str, *, deadline: float | None = None, **kwargs: Any) -> Any:
        with self.stream(method, path, deadline=deadline, **kwargs) as (response, dl):
            with ArrowResponse(response, deadline=dl) as stream:
                body = stream.read(RESPONSE_LIMIT + 1)
                if len(body) > RESPONSE_LIMIT:
                    raise ValueError('DocSpec response exceeded its metadata allowance')
            self.check_response(response, body=body)
            return json.loads(body)

    @staticmethod
    def check_response(response: httpx.Response, *, body: bytes | None = None) -> None:
        if not response.is_success:
            if body is None:
                response.read()
            diagnostic = (response.text if body is None
                          else body.decode(response.encoding or 'utf-8', errors='replace'))
            error = DocSpecFailure([response.request.method, response.request.url.path],
                subprocess.CompletedProcess([], response.status_code, stderr=diagnostic))
            error.status_code = response.status_code
            raise error

    def release(self) -> None:
        with _lock:
            self.owners -= 1
            if not self.owners:
                self.close()

    def close(self) -> None:
        if self.closed or os.getpid() != self.pid:
            return
        self.closed = True
        key = (self.pid, str(self.workspace))
        with _lock:
            if _hosts.get(key) is self:
                del _hosts[key]
        for response in tuple(self.responses):
            response.close()
        self.responses.clear()
        if self.client is not None:
            self.client.close()
        if self.process is not None and self.process.stdin is not None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=min(self.timeout, 2.0))
            except subprocess.TimeoutExpired:
                pass
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
def _close_hosts() -> None:
    for host in list(_hosts.values()):
        host.close()
