"""Receipts describe the bytes consumed by a successful file upload."""
import hashlib

import pytest

from congress_api.retention.derived_files import file_identity
from viewer_publication.client import ConditionalManifestPublisher, GuardedPublicationClient


class Receiver:
    def __init__(self, path, behavior):
        self.path, self.behavior = path, behavior
        self.puts = 0
        self.data = b''

    def get_object(self, **kwargs):
        raise AssertionError('Acknowledged uploads must not need remote readback')

    def put_object(self, **kwargs):
        self.puts += 1
        body = kwargs['Body']
        if self.behavior == 'mutate':
            self.path.write_bytes(b'replaced')
        if self.behavior == 'partial':
            self.data = body.read(3)
        elif self.behavior == 'rewind_readinto':
            body.read(2)  # Model an SDK checksum/signing probe before sending.
            body.seek(0)
            buffer = bytearray(3)
            parts = []
            while count := body.readinto(buffer):
                parts.append(bytes(buffer[:count]))
            self.data = b''.join(parts)
        else:
            self.data = body.read()
        return {'ETag': hashlib.md5(self.data).hexdigest()}


def publish(kind, receiver, path, proof, after_write):
    key = 'viewer-publications/releases/test/payload'
    if kind == 'guarded':
        client = GuardedPublicationClient(receiver, guard=lambda: None,
            journal=lambda *args: None, after_write=lambda *args: after_write.append(args))
        if proof is None:
            receipt = client.upload_file(path, 'bucket', key)
        else:
            receipt = client.upload_verified_file(path, 'bucket', key, validation=proof)
        return receipt
    return ConditionalManifestPublisher(receiver, bucket='bucket').put_immutable_asset(
        key, path, validation=proof)


@pytest.mark.parametrize('kind', ['guarded', 'conditional'])
@pytest.mark.parametrize('proven', [False, True])
@pytest.mark.parametrize('behavior', ['mutate', 'partial'])
def test_acknowledged_wrong_or_partial_bytes_do_not_issue_receipts(tmp_path, kind, proven, behavior):
    path = tmp_path / 'payload'
    path.write_bytes(b'original')
    proof = file_identity(path) if proven else None
    receiver = Receiver(path, behavior)
    after_write = []
    with pytest.raises(ValueError, match='upload bytes'):
        publish(kind, receiver, path, proof, after_write)
    assert receiver.puts == 1
    assert after_write == []


@pytest.mark.parametrize('kind', ['guarded', 'conditional'])
@pytest.mark.parametrize('proven', [False, True])
def test_sdk_probe_rewind_and_readinto_check_the_final_consumed_pass(tmp_path, kind, proven):
    path = tmp_path / 'payload'
    path.write_bytes(b'original')
    proof = file_identity(path) if proven else None
    receiver = Receiver(path, 'rewind_readinto')
    receipt = publish(kind, receiver, path, proof, [])
    assert receiver.puts == 1 and receiver.data == b'original'
    assert receipt.bytes == 8 and receipt.sha256 == hashlib.sha256(receiver.data).hexdigest()


@pytest.mark.loopback
def test_real_boto_put_consumes_the_checked_body(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    received = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def do_PUT(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            received.append(raw)
            self.send_response(200)
            self.send_header('ETag', '"' + hashlib.md5(raw).hexdigest() + '"')
            self.send_header('Content-Length', '0')
            self.end_headers()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    sdk = boto3.client('s3', endpoint_url=f'http://127.0.0.1:{server.server_port}',
        region_name='us-east-1', aws_access_key_id='fixture', aws_secret_access_key='fixture',
        config=Config(signature_version=UNSIGNED, retries={'total_max_attempts': 1}))
    try:
        path = tmp_path / 'payload'
        path.write_bytes(b'actual SDK upload' * 1024)
        client = GuardedPublicationClient(sdk, guard=lambda: None,
            journal=lambda *args: None, after_write=lambda *args: None)
        receipt = client.upload_verified_file(path, 'fixture',
            'viewer-publications/releases/test/payload', validation=file_identity(path))
        assert received == [path.read_bytes()]
        assert client.confirm_transfer(receipt, bucket='fixture',
            key='viewer-publications/releases/test/payload', size=len(received[0]),
            sha256=hashlib.sha256(received[0]).hexdigest())
    finally:
        sdk.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize('kind', ['guarded', 'conditional'])
def test_proven_upload_hashes_the_transport_read_without_a_preflight_read(tmp_path, monkeypatch, kind):
    from pathlib import Path
    path = tmp_path / 'payload'
    path.write_bytes(b'original')
    proof = file_identity(path)
    original_open = Path.open
    consumed = []
    class Reader:
        def __init__(self, stream): self.stream = stream
        def __getattr__(self, name): return getattr(self.stream, name)
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def read(self, *args):
            chunk = self.stream.read(*args)
            consumed.append(len(chunk))
            return chunk
    def counted_open(target, *args, **kwargs):
        stream = original_open(target, *args, **kwargs)
        return Reader(stream) if target == path and args == ('rb',) else stream
    monkeypatch.setattr(Path, 'open', counted_open)
    receipt = publish(kind, Receiver(path, 'normal'), path, proof, [])
    assert receipt.bytes == sum(consumed) == 8


@pytest.mark.parametrize('kind', ['guarded', 'conditional'])
def test_stale_proof_with_identical_metadata_cannot_issue_upload_receipt(tmp_path, monkeypatch, kind):
    import congress_shared.custody as custody
    import congress_api.retention.derived_files as files
    path = tmp_path / 'payload'
    path.write_bytes(b'original')
    original_identity = custody.custody_identity
    def unchanged_timestamps(target):
        value = list(original_identity(target))
        value[3:5] = [1, 1]
        return tuple(value)
    monkeypatch.setattr(custody, 'custody_identity', unchanged_timestamps)
    monkeypatch.setattr(files, 'custody_identity', unchanged_timestamps)
    proof = file_identity(path)
    path.write_bytes(b'replaced')
    assert custody.custody_identity(path) == proof.custody
    after_write = []
    with pytest.raises(ValueError, match='upload bytes'):
        publish(kind, Receiver(path, 'normal'), path, proof, after_write)
    assert after_write == []
