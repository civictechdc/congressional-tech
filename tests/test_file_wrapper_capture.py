"""Native Foundation differential fixtures and audited publisher wrappers."""
from hashlib import sha256
from pathlib import Path
import gzip
import json
import struct

import pytest

from congress_api.parsers.archive_links import inspect_body, inspect_capture
from congress_api.retention.raw_archive import prepare_capture, metadata_body_keys
from test_raw_source_sync import response

FIXTURES = Path(__file__).parent / 'fixtures/capture-failures'


def test_audited_wrapped_pdfs_keep_parent_and_exact_child_provenance():
    expected = [
        ('wrapped-letter.rtfd.gz', '2daf991590f244d55433d4067879b048e6e4037e6360a6d6949dda97f1f36561'),
        ('wrapped-testimony.rtfd.gz', '4f221abb22a48123d60198bf3878b9ef3bf2ada2ba73f2e722b99699dbac2ce5'),
    ]
    for name, digest in expected:
        body = gzip.decompress((FIXTURES / name).read_bytes())
        capture = response('https://example.gov/wrapped.pdf', body)
        outcome, links = inspect_capture(capture)
        assert outcome == 'saved'
        record, captures, bodies, scanned = prepare_capture(capture, outcome=outcome, links=links)
        member = record['archive_members'][0]
        assert member['container_format'] == 'apple_file_wrapper_v3_regular'
        assert member['source_offset'] == 16384
        assert member['status'] == 'completed'
        assert member['original_name'].endswith('.pdf')
        child = next(cap for cap in captures if cap['pointer'][0] == 'archive_members')
        assert child['sha256'] == digest
        assert sha256(bodies[child['body_key']]).hexdigest() == digest
        assert bodies[member['parent_archive_body_key']] == body
        assert child['body_key'] in metadata_body_keys(record, captures)


@pytest.mark.parametrize('path', sorted((FIXTURES / 'file-wrappers').glob('*.rtfd')))
def test_regular_file_subset_matches_native_foundation(path):
    from congress_api.parsers.file_wrapper import regular_file
    result = regular_file(path.read_bytes())
    assert result.data.tobytes() == path.with_suffix('.expected').read_bytes()
    assert '\x00' not in result.name
    if path.name.startswith('unicode'):
        assert result.name == ('空.pdf' if 'empty' in path.name else 'Témoignage 日本語.pdf')


@pytest.mark.parametrize('damage', ['truncate', 'trailing', 'version', 'names', 'length', 'padding', 'attributes'])
def test_unknown_or_damaged_wrapper_is_not_carved_for_pdf_magic(damage):
    from congress_api.parsers.file_wrapper import regular_file
    body = bytearray(gzip.decompress((FIXTURES / 'wrapped-letter.rtfd.gz').read_bytes()))
    if damage == 'truncate': body = body[:-1]
    elif damage == 'trailing': body += b'extra'
    elif damage == 'version': body[8] = 99
    elif damage == 'names': body[20:22] = b'xx'
    elif damage == 'length': body[101:105] = struct.pack('<I', 1)
    elif damage == 'attributes': body[-30] = 99
    else: body[300] = 1
    with pytest.raises(ValueError): regular_file(bytes(body))
    assert inspect_body(bytes(body), 'https://example.gov/a.pdf', 'application/pdf')[0] == 'unsupported_format'


def test_wrapper_extraction_obeys_payload_budget():
    body = gzip.decompress((FIXTURES / 'wrapped-letter.rtfd.gz').read_bytes())
    record, captures, bodies, _ = prepare_capture(response('https://example.gov/a.pdf', body),
        outcome='saved', links=[], max_payload_bytes=len(body) + 100)
    assert record['archive_members'][0]['status'] == 'member_size_limit'
    assert len(bodies) == 1
