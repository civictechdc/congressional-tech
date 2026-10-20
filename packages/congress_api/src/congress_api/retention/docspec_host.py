"""Process ownership and bounded HTTP I/O for the maintained local DocSpec API."""
import atexit
from hashlib import sha256
import io
import os
from pathlib import Path
import signal
import socket
import subprocess
from tempfile import TemporaryFile
import threading
import time
import weakref

import httpx


class DocSpecFailure(RuntimeError):
    """Native refusal or host failure, retaining its original diagnostic."""

    def __init__(self, command, result):
        self.command = tuple(command)
        self.returncode = result.returncode
        self.stderr = result.stderr
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
        # The native CLI accepts a bind address, not an inherited listener.
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        self.command = [*command, 'serve', '--bind', f'127.0.0.1:{port}']
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{port}',
                                   timeout=timeout, trust_env=False)
        self.process = None
        try:
            self.process = subprocess.Popen(self.command, env=environment,
                                            stdout=self.log, stderr=self.log)
            deadline = time.monotonic() + timeout
            while True:
                self.check_alive()
                try:
                    response = self.client.get('/__docspec_ready__', timeout=min(timeout, 0.1))
                    if response.status_code == 404:
                        break
                    raise RuntimeError('Unexpected DocSpec host readiness response')
                except httpx.TransportError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('DocSpec host startup timed out')
                    time.sleep(0.01)
            self.check_alive()
        except BaseException:
            self.close()
            raise

    def check_alive(self):
        if os.getpid() != self.pid:
            raise RuntimeError('DocSpec host cannot be used across a process fork')
        if self.closed:
            raise RuntimeError('DocSpec host is closed')
        if self.process is not None and self.process.poll() is not None:
            self.log.seek(0)
            diagnostic = self.log.read().decode('utf-8', errors='replace')
            raise DocSpecFailure(self.command, subprocess.CompletedProcess(
                self.command, self.process.returncode, stderr=diagnostic))

    def request(self, method, path, **kwargs):
        self.check_alive()
        response = self.client.request(method, path, **kwargs)
        self.check_response(response)
        return response.json()

    @staticmethod
    def check_response(response):
        if not response.is_success:
            response.read()
            raise DocSpecFailure([response.request.method, response.request.url.path],
                subprocess.CompletedProcess([], response.status_code, stderr=response.text))

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


@atexit.register
def _close_hosts():
    for host in list(_hosts.values()):
        host.close()


class ArrowResponse(io.RawIOBase):
    """Expose an HTTP body as a bounded blocking Arrow input, without staging it."""

    def __init__(self, response, *, deadline=None):
        super().__init__()
        self.chunks = response.iter_raw()
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
                self.pending = next(self.chunks, b'')
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
