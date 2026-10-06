"""ZIP capture retains parent bytes and member occurrence provenance together."""

import gzip
from io import BytesIO
import struct
import warnings
from zipfile import ZipFile

import pytest

from congress_api.models.content import CapturedBody
from congress_api.retention.raw_archive import (
    Archive, BodyLimitExceeded, metadata_body_keys, prepare_capture,
)
from test_raw_source_sync import MemoryStore


URL = 'https://example.gov/files/hearing.zip'


def zip_bytes(entries):
    output = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with ZipFile(output, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
    return output.getvalue()


def response(data, url=URL, media='application/zip'):
    return dict(requested_url=url, url=url, complete=True, http_status=200,
                retrieved_at='2026-10-05T12:00:00Z',
                content=CapturedBody.from_bytes(data, media).source_dict())


def prepare(data, **kwargs):
    return prepare_capture(response(data), outcome='saved', links=[], **kwargs)


def test_parent_and_duplicate_members_retain_exact_bytes_and_provenance():
    data = zip_bytes([('directory/', b''), ('same.xml', b'<a/>'), ('same.xml', b'<b/>')])
    record, captures, bodies, _ = prepare(data)
    assert list(bodies.values()) == [data, b'<a/>', b'<b/>']
    assert [member['entry_index'] for member in record['archive_members']] == [1, 2]
    assert [cap['pointer'] for cap in captures] == [
        ['content', 'body'], ['archive_members', 0, 'content', 'body'],
        ['archive_members', 1, 'content', 'body']]
    assert all(cap['context_url'] == URL for cap in captures)
    assert [cap['original_path'] for cap in captures[1:]] == ['same.xml', 'same.xml']
    assert all(member['parent_archive_body_key'] == captures[0]['body_key']
               for member in record['archive_members'])
    assert len(metadata_body_keys(record, captures)) == 3


def test_member_links_recover_explicit_concatenation_with_member_provenance():
    urls = ['https://example.gov/a.xml', 'https://example.gov/b.xml']
    literal = ''.join(urls)
    record, _, _, _ = prepare(zip_bytes([
        ('links.xml', f'<bill><document href="{literal}"/></bill>'.encode())]))
    assert [link['url'] for link in record['links']] == urls
    for link in record['links']:
        assert link['original_url'] == literal
        assert link['attributes']['href'] == literal
        assert link['archive_member'] == {'entry_index': 0, 'original_name': 'links.xml'}
        assert link['member_body_key']


def test_synchronous_archive_stores_reads_and_indexes_all_members():
    store = MemoryStore()
    archive = Archive(store, 'zip-test')
    read_keys = []
    class Metadata:
        def record(self, data, key):
            assert gzip.decompress(store.read(key)) == data
            read_keys.append(key)
        def flush(self):
            pass
    archive.metadata = Metadata()
    data = zip_bytes([('same.xml', b'<a/>'), ('same.xml', b'<a/>'), ('other', b'bytes')])
    state = archive.record(response(data), outcome='saved', links=[])
    receipt = archive.pending[0]
    assert read_keys == metadata_body_keys(receipt['record'], receipt['captures'])
    assert len(read_keys) == 3  # Duplicate occurrences share one metadata reading.
    assert state['body_key'] == receipt['captures'][0]['body_key']
    assert all(cap['family'] == state['family'] for cap in receipt['captures'])
    archive.flush()
    assert len(archive.additions) == 4
    assert [cap['original_path'] for cap in archive.additions[1:]] == ['same.xml', 'same.xml', 'other']


def test_corrupt_member_is_evidence_and_does_not_get_a_capture():
    data = bytearray(zip_bytes([('bad', b'broken'), ('good', b'valid')]))
    name, extra = struct.unpack_from('<HH', data, 26)
    data[30 + name + extra] ^= 1
    record, captures, bodies, _ = prepare(bytes(data))
    assert [member['status'] for member in record['archive_members']] == ['corrupt_member', 'completed']
    assert len(captures) == len(metadata_body_keys(record, captures)) == 2
    assert list(bodies.values()) == [bytes(data), b'valid']


@pytest.mark.parametrize(('url', 'media', 'entries'), [
    ('https://example.gov/file.docx', 'application/octet-stream', [('word/document.xml', b'<a/>')]),
    (URL, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', [('word/document.xml', b'<a/>')]),
    (URL, 'application/octet-stream', [('[Content_Types].xml', b'<a/>'), ('word/document.xml', b'<a/>')]),
])
def test_office_packages_retain_only_outer_document(url, media, entries):
    data = zip_bytes(entries)
    record, captures, bodies, _ = prepare_capture(response(data, url, media), outcome='saved', links=[])
    assert 'archive_members' not in record
    assert len(captures) == 1 and list(bodies.values()) == [data]


def test_payload_budget_refuses_members_without_exceeding_retained_bytes():
    data = zip_bytes([('one', b'1234'), ('two', b'5678')])
    record, captures, bodies, _ = prepare(data, max_payload_bytes=len(data) + 9)
    assert [member['status'] for member in record['archive_members']] == ['completed', 'aggregate_size_limit']
    assert sum(map(len, bodies.values())) + 4 <= len(data) + 9
    assert len(captures) == 2
    record, captures, bodies, _ = prepare(data, max_payload_bytes=len(data))
    assert record['archive_processing']['status'] == 'aggregate_size_limit'
    assert len(captures) == 1
    with pytest.raises(BodyLimitExceeded):
        prepare(data, max_payload_bytes=len(data) - 1)


def test_member_links_require_literal_absolute_urls_and_retain_context():
    xml = b'<root><file href="relative.pdf"/><file href="https://example.gov/xml.pdf"/><file href="http://127.0.0.1/private.pdf"/></root>'
    html = b'<html><head><base href="https://example.gov/"></head><body><a href="local.pdf">PDF</a><a href="https://example.gov/html.pdf">PDF</a></body></html>'
    record, captures, bodies, _ = prepare(zip_bytes([('meeting.xml', xml), ('page.html', html)]))
    assert [link['url'] for link in record['links']] == [
        'https://example.gov/xml.pdf', 'https://example.gov/html.pdf']
    assert [link['archive_member']['entry_index'] for link in record['links']] == [0, 1]
    assert all(link['parent_url'] == URL and link['member_body_key'] in bodies
               for link in record['links'])


def test_nested_zip_member_is_retained_and_not_expanded():
    inner = zip_bytes([('inner.xml', b'<a/>')])
    record, captures, bodies, _ = prepare(zip_bytes([('inner.zip', inner)]))
    member, = record['archive_members']
    assert member['nested_archive']
    assert len(captures) == 2 and list(bodies.values())[1] == inner


def test_generic_zip_containing_office_document_keeps_all_outer_members():
    office = zip_bytes([('[Content_Types].xml', b'<Types/>'), ('word/document.xml', b'<a/>')])
    record, captures, bodies, _ = prepare(zip_bytes([('embedded.docx', office), ('file.pdf', b'%PDF-1.7\n%%EOF')]))
    assert [member['original_name'] for member in record['archive_members']] == ['embedded.docx', 'file.pdf']
    assert len(captures) == 3 and captures[-1]['media_type'] == 'application/pdf'


def test_malformed_archive_and_incomplete_capture_preserve_original_body():
    data = b'PK\x03\x04broken'
    record, captures, bodies, _ = prepare(data)
    assert record['archive_processing']['status'] == 'corrupt_archive'
    assert len(captures) == 1 and list(bodies.values()) == [data]
    partial = response(data)
    partial['complete'] = False
    record, captures, _, _ = prepare_capture(partial, outcome='incomplete', links=[])
    assert 'archive_members' not in record and metadata_body_keys(record, captures) == []
