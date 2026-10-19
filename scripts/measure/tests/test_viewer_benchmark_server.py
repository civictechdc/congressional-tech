"""The local browser harness must serve exact bounded ranges and verified files."""
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('viewer_benchmark_server', ROOT / 'scripts/measure/viewer_benchmark_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def request(routes, path, byte_range=None, head=False):
    implementation = server.handler(routes)
    value = object.__new__(implementation)
    value.path = path
    value.headers = {} if byte_range is None else {'Range': byte_range}
    value.wfile = io.BytesIO()
    result = {'headers': {}}
    value.send_response = lambda status: result.update(status=status)
    value.send_header = lambda name, text: result['headers'].update({name: text})
    value.end_headers = lambda: None
    value.send_error = lambda status: result.update(status=status)
    value.serve(head=head)
    return result | {'body': value.wfile.getvalue()}


def test_exact_ranges_and_cors_headers(tmp_path):
    path = tmp_path / 'table.parquet'
    path.write_bytes(b'PAR1' + bytes(range(256)) * 512)
    result = request({'/table': path}, '/table?case=1', 'bytes=4-259')
    assert result['status'] == 206
    assert result['body'] == bytes(range(256))
    assert result['headers']['Content-Length'] == '256'
    assert result['headers']['Content-Range'] == f'bytes 4-259/{path.stat().st_size}'
    assert result['headers']['Access-Control-Allow-Origin'] == '*'
    assert 'Content-Range' in result['headers']['Access-Control-Expose-Headers']
    assert request({'/table': path}, '/table', 'bytes=0-3', head=True)['body'] == b''


@pytest.mark.parametrize('value', ['bytes=3-2', 'bytes=0-4', 'bytes=-1-3', 'bytes=0-1,2-3'])
def test_invalid_ranges_are_refused(value):
    assert request({'/file': b'PAR1'}, '/file', value)['status'] == 416


def test_routes_are_an_allowlist():
    assert request({'/file': b'PAR1'}, '/%2e%2e/private')['status'] == 404
    assert request({'/': b'<html>'}, '/')['headers']['Content-Type'].startswith('text/html')


def test_file_identity_and_path_are_verified(tmp_path):
    path = tmp_path / 'valid.bin'
    path.write_bytes(b'original')
    item = {'path': path.name, 'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}
    assert server.selected_file(tmp_path, item) == path
    path.write_bytes(b'changed!')
    with pytest.raises(ValueError, match='differs'):
        server.selected_file(tmp_path, item)
    with pytest.raises(ValueError, match='Invalid'):
        server.selected_file(tmp_path, dict(item, path='../escape.bin'))
