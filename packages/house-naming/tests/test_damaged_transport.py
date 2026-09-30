"""Visible prefix fields do not repair concatenated-URL filename fragments."""
import gzip
import json

import pytest

from house_naming import Engine
from house_naming.filename_corpus import build_corpus
from house_naming.filenames import parse_filename


SOURCE = 'BILLS-115s585rfh.xmlhttps:'


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    return result


def additions(result):
    return [m for m in result['observations'] if m['rule'] == 'extension-protocol-suffix'
            or m['scope'].endswith('-payload-fragment')]


def test_actual_source_retains_readable_version_and_invalid_name(engine):
    result = checked(engine, SOURCE)
    assert not result['valid'] and result['issues'] == ['unsafe-or-empty-filename']
    assert result['matches'] == [] and result['stem_end'] == len(SOURCE)
    transport, fragment = additions(result)
    assert [(f['name'], f['raw'], f['start'], f['end']) for f in transport['fields']] == [
        ('embedded_extension', 'xml', 17, 20), ('protocol_marker', 'https:', 20, 26)]
    assert fragment['rule'] == 'fragment-legislative-text'
    assert fragment['scope'] == 'legislative-payload-fragment'
    field, = fragment['fields']
    assert (field['name'], field['raw'], field['start'], field['end']) == ('version_token', 'rfh', 13, 16)
    assert field['code'] == 'rfh' and field['label'] == engine.lookup('version', 'rfh')['label']
    assert 'full source name remains malformed' in fragment['description']
    assert not any(m['scope'] == 'legislative-payload' for m in result['observations'])
    assert not any(f['name'] == 'extension' for m in result['observations'] for f in m['fields'])
    assert any(f['name'] == 'payload' and f['raw'] == 's585rfh.xmlhttps:'
               for m in result['observations'] for f in m['fields'])
    assert [m.model_dump(mode='json') for m in parse_filename(SOURCE).matches] == result['observations']


@pytest.mark.parametrize('extension', ['xml', 'PDF', 'html', 'htm', 'docx', 'txt', 'csv', 'zip'])
@pytest.mark.parametrize('protocol', ['http:', 'HTTPS:'])
def test_existing_extension_vocabulary_and_payload_rules_are_reused(engine, extension, protocol):
    name = f' BILLS-119HR123ih.{extension}{protocol}  '
    result = checked(engine, name)
    transport, fragment = additions(result)
    assert [(f['name'], f['raw']) for f in transport['fields']] == [
        ('embedded_extension', extension), ('protocol_marker', protocol)]
    assert [(f['name'], f['raw']) for f in fragment['fields']] == [('version_token', 'ih')]
    assert not result['valid']


def test_query_is_retained_separately(engine):
    name = SOURCE + '?download=1'
    result = checked(engine, name)
    assert len(additions(result)) == 2
    assert any(f['name'] == 'query_text' and f['raw'] == '?download=1'
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'BILLS-115s585rfh.xml', 'BILLS-115s585rfh.xmlhttp',
    'BILLS-115s585rfh.xmlftp:', 'BILLS-115s585rfh.xmlhttps:extra',
    'BILLS-115s585rfh.unknownhttps:', 'BILLS-115s585rfhxmlhttps:',
    'BILLS-115s585rfh.xml-https:', 'https:', 'http:',
])
def test_unsupported_or_complete_endings_do_not_gain_transport_fields(engine, name):
    assert additions(checked(engine, name)) == []


@pytest.mark.parametrize('name', ['Notes.xmlhttps:', 'BILLS-119Services.xmlhttps:', '.pdfhttp:'])
def test_transport_syntax_does_not_invent_legislation(engine, name):
    result = checked(engine, name)
    transport, = additions(result)
    assert transport['rule'] == 'extension-protocol-suffix'
    assert not any(f['name'] == 'version_token' for m in result['observations'] for f in m['fields'])


def test_existing_complete_payload_is_not_repeated(engine):
    name = 'BILLS-119HR123ih-Notes.xmlhttps:'
    result = checked(engine, name)
    transport, = additions(result)
    assert transport['rule'] == 'extension-protocol-suffix'
    assert any(m['scope'] == 'legislative-payload' for m in result['observations'])


def test_fragment_does_not_clear_incomplete_payload_review(tmp_path):
    coverage = build_corpus([SOURCE, 'BILLS-115s585rfh.xml'], tmp_path)
    assert coverage['filenames_with_unparsed_structured_payload'] == 1
    assert coverage['structural_collisions'] == 0
    with gzip.open(tmp_path / 'review.jsonl.gz', 'rt') as stream:
        rows = list(map(json.loads, stream))
    row = next(r for r in rows if r['filename'] == SOURCE)
    assert row['unparsed_structured_payload']
    assert any(m['rule'] == 'fragment-legislative-text' for m in row['matches'])
