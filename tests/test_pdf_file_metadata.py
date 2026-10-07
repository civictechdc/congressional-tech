"""Large retained PDFs keep bounded opening-page metadata without body copies."""

from pathlib import Path
import re
import sys

import pytest

from congress_api.parsers import pdf_tools
from congress_api.retention import capture_metadata as module
from congress_api.retention.capture_metadata import CaptureMetadata, read_document_file
from test_capture_metadata import readings
from test_raw_source_sync import MemoryStore

FIXTURE = Path(__file__).parent / 'fixtures/meeting_inventory/senate-burma-hearing-cover.pdf'


def large_pdf(path, size=17 * 1024**2):
    # A large unreferenced comment preserves the original PDF's object offsets.
    # Repeating startxref keeps the last trailer reachable to normal PDF readers.
    data = FIXTURE.read_bytes()
    xref = re.findall(rb'startxref\s+(\d+)', data)[-1]
    with path.open('wb') as output:
        output.write(data + b'\n%')
        output.seek(size)
        output.write(b'\nstartxref\n' + xref + b'\n%%EOF\n')
    return path


def test_large_pdf_opening_fields_match_existing_reader_without_read_bytes(tmp_path, monkeypatch):
    path = large_pdf(tmp_path / 'large.pdf')
    expected = module.inspect_document(FIXTURE.read_bytes())
    monkeypatch.setattr(Path, 'read_bytes', lambda *_: pytest.fail('whole-body read'))
    result = read_document_file(path, 'body-key', 'test')
    assert result['status'] == 'completed'
    assert result['error_type'] is None
    assert result['content_citation'] == ['S. Hrg. 117-16']
    assert {key: result[key] for key in expected} == expected


def test_large_non_pdf_retains_limit_without_reader(tmp_path, monkeypatch):
    path = tmp_path / 'large.xml'
    with path.open('wb') as output:
        output.write(b'<xml>')
        output.truncate(module.BODY_LIMIT + 1)
    monkeypatch.setattr(module, 'inspect_pdf_file', lambda _: pytest.fail('PDF reader on XML'))
    result = read_document_file(path, 'body-key', 'test')
    assert result['status'] == 'size_limit'
    assert result['error_type'] is None


def test_small_file_uses_existing_inspector(tmp_path):
    path = tmp_path / 'small'
    path.write_bytes(b'document')
    seen = []
    def inspect(data):
        seen.append(data)
        return {'body_format': ['xml']}
    result = read_document_file(path, 'body-key', 'test', inspect)
    assert seen == [b'document']
    assert result['status'] == 'completed'
    assert result['body_format'] == ['xml']


@pytest.mark.parametrize('error', [pdf_tools.PdfToolTimeoutError,
                                  pdf_tools.PdfToolMemoryError,
                                  pdf_tools.PdfToolOutputError,
                                  pdf_tools.PdfToolError])
def test_large_reader_refusal_preserves_pdf_fact_and_error(tmp_path, monkeypatch, error):
    path = large_pdf(tmp_path / 'large.pdf')
    def refuse(_):
        raise error('refused')
    monkeypatch.setattr(module, 'inspect_pdf_file', refuse)
    result = read_document_file(path, 'body-key', 'test')
    assert result['status'] == 'failed'
    assert result['error_type'] == error.__name__
    assert result['body_format'] == ['pdf']


def test_existing_readings_stay_reused_without_opening_path():
    store = MemoryStore()
    with CaptureMetadata(store, 'original') as metadata:
        metadata.accept(dict(body_key='existing', parser_fingerprint='old',
                             status='size_limit', error_type=None))
    with CaptureMetadata(store, 'later') as metadata:
        metadata.record_file('/does/not/exist.pdf', 'existing')
        assert metadata.counts == {'reused': 1}
    assert len(readings(store)) == 1
    assert readings(store)[0]['parser_fingerprint'] == 'old'


def test_explicit_refresh_appends_new_reading_without_replacing_old(tmp_path):
    store = MemoryStore()
    path = large_pdf(tmp_path / 'large.pdf')
    with CaptureMetadata(store, 'old') as metadata:
        metadata.accept(dict(body_key='existing', parser_fingerprint='old',
                             status='size_limit', error_type=None))
    with CaptureMetadata(store, 'new', refresh_body_keys=['existing']) as metadata:
        metadata.record_file(path, 'existing')
        metadata.record_file(path, 'existing')
        assert metadata.counts == {'completed': 1, 'reused': 1}
    assert sorted(row['status'] for row in readings(store)) == ['completed', 'size_limit']


def test_file_reader_restricts_pages_and_local_inputs(tmp_path):
    with pytest.raises(ValueError, match='first two'):
        pdf_tools.opening_page_text_file(FIXTURE, 3)
    with pytest.raises(pdf_tools.PdfToolError, match='regular local'):
        pdf_tools.page_count_file(tmp_path)
    path = tmp_path / 'not.pdf'
    path.write_text('not a PDF')
    with pytest.raises(pdf_tools.PdfToolError, match='not a PDF'):
        pdf_tools.page_count_file(path)


def test_blank_first_page_fallback_accepts_only_transcript(monkeypatch):
    monkeypatch.setattr(module, 'page_count_file', lambda _: 2)
    calls = []
    def text(path, page):
        calls.append(page)
        return '' if page == 1 else 'opening statement'
    monkeypatch.setattr(module, 'opening_page_text_file', text)
    monkeypatch.setattr(module, 'document_page_fields',
                        lambda first, second='': {'content_document_kind': ['opening-statement']} if second else {})
    assert module.inspect_pdf_file('file') == {'body_format': ['pdf']}
    assert calls == [1, 2]
    monkeypatch.setattr(module, 'document_page_fields',
                        lambda first, second='': {'content_document_kind': ['transcript']} if second else {})
    assert module.inspect_pdf_file('file')['content_document_kind'] == ['transcript']


def test_memory_refusal_kills_and_reaps_child(monkeypatch):
    real_popen = pdf_tools.subprocess.Popen
    children = []
    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(pdf_tools.subprocess, 'Popen', start)
    monkeypatch.setattr(pdf_tools, '_resident_bytes', lambda _: 1024)
    with pytest.raises(pdf_tools.PdfToolMemoryError, match='memory limit'):
        pdf_tools._run([sys.executable, '-c', 'import time; time.sleep(30)'], memory_limit=512)
    assert children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


def test_memory_guard_continues_after_child_closes_output(monkeypatch):
    calls = []
    def sample(_):
        calls.append(None)
        return 0 if len(calls) == 1 else 1024
    monkeypatch.setattr(pdf_tools, '_resident_bytes', sample)
    command = [sys.executable, '-c',
               'import os, time; os.close(1); os.close(2); time.sleep(30)']
    with pytest.raises(pdf_tools.PdfToolMemoryError):
        pdf_tools._run(command, memory_limit=512, timeout=2)
    assert len(calls) == 2


def test_unavailable_memory_measurement_refuses(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('ps unavailable')
    monkeypatch.setattr(pdf_tools.subprocess, 'run', fail)
    with pytest.raises(pdf_tools.PdfToolError, match='memory measurement unavailable'):
        pdf_tools._resident_bytes(1)
