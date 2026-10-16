"""Evidence boundary checks for the local PDF pilot tooling."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import pilot_audit
import pilot_extract
import pilot_review


@pytest.mark.parametrize(('native', 'ocr', 'method'), [
    ('short', 'longer recognized text', 'ocr'),
    ('native cover text', '', 'native_text'),
])
def test_ocr_uses_page_image_and_records_selected_text(tmp_path, monkeypatch, native, ocr, method):
    monkeypatch.setattr(pilot_extract.pdf_tools, 'page_count_file', lambda path: 1)
    monkeypatch.setattr(pilot_extract.pdf_tools, 'opening_page_text_file', lambda path, page: native)

    def run(command, **kwargs):
        if command[0] == 'pdftoppm':
            Path(command[-1] + '.png').write_bytes(b'image')
        else:
            assert command[0] == 'tesseract'
            assert Path(command[1]).name == 'abc.page-1.png'
            assert Path(command[1]).is_file()
        return SimpleNamespace(stdout=ocr)

    monkeypatch.setattr(pilot_extract.subprocess, 'run', run)
    body = pilot_extract.extract_pages(b'%PDF-example', 'abc', tmp_path)
    page, = body['pages']
    assert page['ocr_attempted'] is True
    assert page['method'] == method
    assert (tmp_path / page['text']).read_text() == (ocr if method == 'ocr' else native)
    assert page['text_sha256'] == pilot_extract.digest(tmp_path / page['text'])


def reference_fixture(tmp_path, monkeypatch):
    directory = tmp_path / 'development'
    directory.mkdir()
    data = b'%PDF-original'
    sha = hashlib.sha256(data).hexdigest()
    (directory / (sha + '.pdf')).write_bytes(data)
    text = directory / 'text.txt'
    text.write_text('REPORT\nA sample report.')
    info = dict(page=1, text=text.name, native_text=text.name,
                text_sha256=pilot_extract.digest(text), method='native_text')
    row = dict(document_id='doc', split='development', status='review_ready',
               bodies=[dict(sha256=sha, pages=[info])])
    source = tmp_path / 'sample.json'
    source.write_text(json.dumps(dict(records=[dict(document_id='doc', split='development',
                                                   body_keys=['bodies/sha256/' + sha + '.gz'])])))
    monkeypatch.setattr(pilot_review, 'OUT', tmp_path)
    monkeypatch.setattr(pilot_review, 'SAMPLE', source)
    monkeypatch.setattr(pilot_review, 'LABELS', tmp_path / 'labels.json')
    monkeypatch.setattr(pilot_review, 'records', lambda: {'doc': row})
    return row, directory / (sha + '.pdf'), text


@pytest.mark.parametrize('target', ['body', 'text', 'quote'])
def test_reference_rejects_changed_or_unsupported_evidence(tmp_path, monkeypatch, target):
    _, body, text = reference_fixture(tmp_path, monkeypatch)
    quote = 'REPORT'
    if target == 'body':
        body.write_bytes(b'%PDF-replaced')
    elif target == 'text':
        text.write_text('REPORT\nChanged contents.')
    else:
        quote = 'HEARING'
    with pytest.raises(AssertionError):
        pilot_review.add('development', [[1, 'report', 1, quote, 'Explicit cover']])
    assert not pilot_review.LABELS.exists()


def test_reference_is_idempotent_and_rejects_silent_relabel(tmp_path, monkeypatch):
    reference_fixture(tmp_path, monkeypatch)
    decision = [[1, 'report', 1, 'REPORT', 'Explicit cover']]
    pilot_review.add('development', decision)
    before = pilot_review.LABELS.read_bytes()
    pilot_review.add('development', decision)
    assert pilot_review.LABELS.read_bytes() == before
    with pytest.raises(AssertionError, match='silently replace'):
        pilot_review.add('development', [[1, 'hearing', 1, 'REPORT', 'Changed mind']])
    assert pilot_review.LABELS.read_bytes() == before


def test_opening_policy_does_not_classify_appendix_or_second_page_statement(monkeypatch):
    calls = []

    def fields(first, second=''):
        calls.append((first, second))
        return {'content_document_kind': [second]} if second else {}

    monkeypatch.setattr(pilot_audit.document_cover, 'document_page_fields', fields)
    assert pilot_audit.opening_fields('Report cover', 'transcript') == {}
    assert calls == [('Report cover', '')]
    assert pilot_audit.opening_fields('', 'opening-statement') == {}
    assert pilot_audit.opening_fields('', 'transcript') == {'content_document_kind': ['transcript']}
