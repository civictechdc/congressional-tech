"""Thin CLI transport for maintained DocSpec source-only dataset operations.

Callers supply exact native requests, stable operation identities, and partition
routing. DocSpec owns admission, versions, completion, concurrency and recovery.
Application publication must select a coherent set of exact completed pins;
independent native latest results are preparation, not an application snapshot.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import pyarrow as pa


class DocSpecFailure(RuntimeError):
    """The maintained CLI refused or failed; its original diagnostic is retained."""

    def __init__(self, command, result):
        self.command = tuple(command)
        self.returncode = result.returncode
        self.stderr = result.stderr
        super().__init__(result.stderr.strip() or f'DocSpec exited {result.returncode}')


class NativeDatasets:
    """Invoke the configured native owner; do not duplicate lifecycle decisions."""

    def __init__(self, binary, workspace, *, remote=None, limits=None, timeout=120):
        self.binary = str(Path(binary).resolve())
        self.workspace = Path(workspace).resolve()
        self.remote = Path(remote).resolve() if remote is not None else None
        self.limits = Path(limits).resolve() if limits is not None else None
        self.timeout = timeout

    def _call(self, *args, remote=True):
        command = [self.binary, '--workspace', str(self.workspace)]
        if self.limits is not None:
            command += ['--limits', str(self.limits)]
        if remote and self.remote is not None:
            command += ['--remote', str(self.remote)]
        command += list(map(str, args))
        result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode:
            raise DocSpecFailure(command, result)
        return json.loads(result.stdout) if result.stdout.strip() else None

    @contextmanager
    def _scratch(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='request-', dir=self.workspace) as directory:
            yield Path(directory)

    def _request(self, command, request):
        with self._scratch() as directory:
            path = directory / 'request.json'
            path.write_text(json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            return self._call(command, path)

    def hash_input(self, path):
        """Hash a local producer file without opening the configured remote host."""
        return self._call('hash', Path(path).resolve(), remote=False)

    def run(self, request):
        return self._request('run', request)

    def plan(self, request):
        return self._request('plan', request)

    def update(self, request):
        return self._request('update', request)

    def plan_update(self, request):
        return self._request('plan-update', request)

    def latest(self, dataset):
        return self._call('latest', dataset)

    def release(self, dataset, operation):
        return self._call('release', dataset, operation)

    @contextmanager
    def source_batches(self, pin):
        """Read one exact bounded partition pin through the configured native host.

        Native reading supplies the logical source fields, including nested
        values. Callers retain any application Arrow schema metadata separately;
        the native representation replaces application field metadata with native IDs.
        The temporary Arrow IPC file remains alive while the reader is open.
        """
        with self._scratch() as directory:
            release, output = directory / 'release.json', directory / 'source.arrow'
            release.write_text(json.dumps(pin, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            self._call('read', release, output, '--group', 'source')
            with output.open('rb') as stream:
                with pa.ipc.open_stream(stream) as reader:
                    yield reader
