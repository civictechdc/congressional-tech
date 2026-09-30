"""Migration checks: preserve original bytes, unknown fields and historical text."""
import copy
import gzip
import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from congress_api.models.content import RawContent
from congress_api.retention.bundles import restore, separate


def extract(value):
    bodies = {}

    def put(data):
        key = RawContent.from_bytes(data, '').sha256
        bodies[key] = data
        return key

    record, captures = separate(value, put)
    return record, captures, bodies


def test_exact_bytes_metadata_and_duplicate_content_roundtrip():
    raw = RawContent.from_bytes(b'\xff\x00\r\nPDF', 'application/pdf').source_dict()
    value = {'url': 'https://example.gov/a', 'unknown': {'keep': None},
             'history': [raw, raw], 'empty': [], 'status_code': 403}
    original = copy.deepcopy(value)
    record, captures, bodies = extract(value)
    assert len(captures) == 2 and len(bodies) == 1
    assert {c['fidelity'] for c in captures} == {'exact-bytes'}
    assert all(c['context_url'] == value['url'] and c['status_code'] == 403 for c in captures)
    assert restore(record, captures, bodies.__getitem__) == original == value


def test_caption_text_can_differ_from_original_bytes():
    value = {'segments': [{'url': 'https://example.gov/a.vtt', 'text': '\ufffd\n',
                           'raw_body': RawContent.from_bytes(b'\xff\r\n', 'text/vtt').source_dict()}]}
    record, captures, bodies = extract(value)
    assert {c['fidelity'] for c in captures} == {'exact-bytes', 'saved-text'}
    assert restore(record, captures, bodies.__getitem__) == value


def test_old_html_empty_bodies_and_unknown_fields_survive():
    value = {'evidence': {'document_groups': [], 'html': '', 'unknown': {'x': 1}},
             'raw_xml': '<root>\r\n</root>', 'other': {'html': '<fragment>', 'text': 'parsed text'}}
    record, captures, bodies = extract(value)
    assert len(captures) == 2
    assert record['other'] == value['other']
    assert all(c['fidelity'] == 'saved-text' for c in captures)
    assert restore(record, captures, bodies.__getitem__) == value


def test_declared_digest_mismatch_fails():
    value = RawContent.from_bytes(b'original', 'text/html').source_dict()
    value['body'] = 'changed'
    with pytest.raises(ValidationError, match='digest mismatch'):
        extract(value)


def test_corrupt_or_duplicate_restoration_fails():
    record, captures, bodies = extract({'raw_html': '<html></html>'})
    with pytest.raises(ValueError, match='integrity'):
        restore(record, captures, lambda _: b'corrupt')
    with pytest.raises(ValueError, match='occupied'):
        restore(record, captures * 2, bodies.__getitem__)


@pytest.mark.parametrize('status_key', ['httpResponseStatusCode', 'statusCode'])
def test_zyte_and_url_map_context(status_key):
    value = {'https://example.gov/page': {'httpResponseBody': '/w==',
                                        status_key: 200, 'browserHtml': '<p>Hello</p>'}}
    record, captures, bodies = extract(value)
    assert len(captures) == 2
    assert all(c['context_url'] == 'https://example.gov/page' for c in captures)
    assert restore(record, captures, bodies.__getitem__) == value


@pytest.mark.parametrize('mode', ['exact', 'corrupt', 'legacy'])
def test_disk_migration_roundtrip_and_corrupt_input_report(tmp_path, mode):
    pq = pytest.importorskip('pyarrow.parquet')
    corrupt = mode == 'corrupt'
    raw = RawContent.from_bytes(b'<html>\r\nTest</html>', 'text/html').source_dict()
    if corrupt:
        raw['sha256'] = '0' * 64
    original = {'url': 'https://example.gov/source', 'content': raw, 'unknown': ['preserved']}
    if mode == 'legacy':
        original = {'url': 'https://example.gov/a.vtt', 'text': 'WEBVTT\r\n', 'status_code': 200}
    source = tmp_path / 'state.json.gz'
    source_bytes = gzip.compress(json.dumps(original).encode())
    source.write_bytes(source_bytes)
    manifest = tmp_path / 'inputs.jsonl'
    manifest.write_text(json.dumps({'path': str(source), 'size': source.stat().st_size,
                                    'mtime_ns': source.stat().st_mtime_ns}) + '\n')
    output = tmp_path / 'archive'
    script = Path(__file__).resolve().parents[1] / 'docs/youtube-coverage/research/scripts/extract_raw_bundles.py'
    result = subprocess.run([sys.executable, str(script), '--manifest', str(manifest),
                             '--output', str(output), '--workers', '1', '--min-free-gib', '0'],
                            capture_output=True, text=True)
    assert result.returncode == int(corrupt), result.stderr
    summary = json.loads((output / 'summary.json').read_text())
    assert source.read_bytes() == source_bytes
    assert summary.get('error', 0) == int(corrupt)
    assert pq.read_table(output / 'indexes/captures-00.parquet').num_rows == int(not corrupt)
    with gzip.open(output / 'receipts/embedded-00.jsonl.gz', 'rt') as stream:
        receipts = [json.loads(line) for line in stream]
    if corrupt:
        assert not receipts
    else:
        receipt = receipts[0]
        assert restore(receipt['record'], receipt['captures'],
                       lambda key: gzip.decompress((output / key).read_bytes())) == original
