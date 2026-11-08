"""Body-text derivations, one small body per parser (data model §6.6).

Expectations come from the bodies' own words and page layout, not from re-running the rule.
"""
import gzip
import hashlib
import signal
import time

import pytest

from body_text_fixtures import HTML, PAGE_ONE, PAGE_TWO, XML, scanned_pdf, two_page_pdf, warc_member
from congress_api.parsers import body_text as bt
from congress_api.retention.sniff import read_sniff


def sniff(payload):
    return read_sniff(lambda start, length: payload[start:start + length], stored_size=len(payload))['format']


def derive(data, parser, strategy=None, deadline=30):
    return bt.derive(data, parser, strategy=strategy or bt.NativeOnly(), page_deadline_seconds=deadline,
                     sniff_format=sniff, max_bytes=64 << 20)


def test_two_page_pdf_keeps_page_starts_as_utf8_offsets():
    reading = derive(two_page_pdf(), 'pdf_text')
    assert reading.status == 'completed' and reading.ocr_pages == () and reading.macos_build is None
    assert reading.text == PAGE_ONE + '\n' + PAGE_TWO
    assert reading.page_offsets == (0, len(PAGE_ONE.encode()) + 1)
    assert reading.text.encode()[reading.page_offsets[1]:].decode() == PAGE_TWO
    row = reading.row()
    assert row['text_bytes'] == len(reading.text.encode()) and row['text_head'] == reading.text
    assert row['fingerprint'] == hashlib.sha256(' '.join(reading.text.split()).encode()).hexdigest()
    assert {f['field']: f['value'] for f in row['fields']} == {'page_count': '2'}


def test_native_only_leaves_a_textless_image_page_for_ocr():
    with pytest.raises(bt.OcrRequired):
        derive(scanned_pdf(), 'pdf_text')


class FakeOcr:
    """Native text, except a page the declared rule sends to OCR reads as a fixed recognition."""
    def extract(self, page):
        from spicy_docs.extraction import NativeText, Observation, PageContent, TextBlock
        content = NativeText().extract(page)
        if not bt.needs_ocr(page, content.observations[0]):
            return content
        block = TextBlock('RECOGNIZED PAGE TEXT', observation='ocr')
        return PageContent((block,), (Observation('ocr', block.text, {'backend': 'fake'}, None, (block,)),))


def test_an_injected_strategy_reads_the_textless_page_and_records_it():
    reading = derive(scanned_pdf(), 'pdf_text', strategy=FakeOcr())
    assert reading.status == 'completed' and reading.ocr_pages == (2,)
    assert reading.text == PAGE_ONE + '\nRECOGNIZED PAGE TEXT'
    assert reading.row()['fingerprint'] is None  # OCR output is not a native layer
    import platform
    assert (reading.macos_build is not None) == (platform.system() == 'Darwin')


class FailsPageTwo:
    def extract(self, page):
        from spicy_docs.extraction import ExtractionError, NativeText
        if page.number == 2:
            raise ExtractionError('render exceeds max_pixels')
        return NativeText().extract(page)


def test_a_failed_page_is_an_error_with_no_text():
    reading = derive(two_page_pdf(), 'pdf_text', strategy=FailsPageTwo())
    assert (reading.status, reading.error_type, reading.text) == ('error', 'failed_pages', None)
    assert reading.fields['failed_pages'] == [2] and reading.fields['page_count'] == 2
    assert reading.row()['text_bytes'] is None and reading.row()['fingerprint'] is None


class Slow:
    def extract(self, page):
        time.sleep(5)


def test_page_deadline_interrupts_the_page_and_restores_the_handler():
    before = signal.getsignal(signal.SIGALRM)
    started = time.monotonic()
    with pytest.raises(bt.PageDeadline):
        derive(two_page_pdf(), 'pdf_text', strategy=Slow(), deadline=0.2)
    assert time.monotonic() - started < 3
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_not_a_pdf_is_an_error_reading():
    assert derive(b'%PDF-1.7\nnot really', 'pdf_text').status == 'error'


def test_html_pre_transcript_keeps_its_layout_and_drops_the_title():
    reading = derive(HTML, 'html_text')
    assert reading.text == 'STATEMENT OF THE WITNESS\n\n    Mr. Chairman, thank you.\n'
    assert reading.page_offsets == (0,) and reading.fields == {'page_count': 1}


def test_xml_elements_become_lines():
    assert derive(XML, 'xml_text').text == 'Oversight\nThe committee met.'
    assert derive(b'<hearing><unclosed>', 'xml_text').status == 'error'


def test_warc_unwraps_its_payload_and_reads_it_by_sniffed_format():
    reading = derive(warc_member(HTML), 'warc')
    assert reading.status == 'completed' and reading.text == derive(HTML, 'html_text').text
    assert reading.fields['payload_format'] == 'html' and reading.fields['http_status'] == 200
    assert reading.fields['payload_sha256'] == hashlib.sha256(HTML).hexdigest()
    pdf = derive(warc_member(two_page_pdf(), content_type='application/pdf'), 'warc')
    assert pdf.text == PAGE_ONE + '\n' + PAGE_TWO and pdf.fields['payload_format'] == 'pdf'


def test_warc_payload_with_content_encoding_is_decoded():
    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter
    import io
    out = io.BytesIO()
    writer = WARCWriter(out, gzip=True)
    headers = StatusAndHeaders('200 OK', [('Content-Type', 'text/html'), ('Content-Encoding', 'gzip')],
                               protocol='HTTP/1.1')
    writer.write_record(writer.create_warc_record('https://example.senate.gov/a', 'response',
        payload=io.BytesIO(gzip.compress(HTML, mtime=0)), http_headers=headers))
    assert derive(out.getvalue(), 'warc').text == derive(HTML, 'html_text').text


def test_unreadable_envelope_and_unsupported_payload_are_errors_not_hashes():
    broken = derive(gzip.compress(b'WARC/1.0\r\nnot a record'), 'warc')
    assert (broken.status, broken.error_type, broken.fields) == ('error', 'warc_unreadable', {})
    other = derive(warc_member(b'\x89PNG\r\n\x1a\n' + b'\0' * 32, content_type='image/png'), 'warc')
    assert (other.status, other.error_type, other.fields['payload_format']) == ('error', 'unsupported_payload', 'image')
    with pytest.raises(bt.EnvelopeRefused):
        bt.warc_payload(b'not gzip', max_bytes=1 << 20)


def test_body_text_ids_are_their_declarations_and_name_the_page_rule():
    from congress_api.lake.reading_versions import BODY_TEXT_DECLARATIONS, READING_VERSIONS
    assert set(BODY_TEXT_DECLARATIONS) == {'pdf_text', 'html_text', 'xml_text', 'warc'}
    for parser, declaration in BODY_TEXT_DECLARATIONS.items():
        assert READING_VERSIONS[parser] == hashlib.sha256(declaration.encode()).hexdigest()
    # A threshold the code uses must be the one its ID declares; moving it needs a new ID.
    assert f'under {bt.OCR_MIN_CHARS} non-whitespace' in BODY_TEXT_DECLARATIONS['pdf_text']
    assert bt.GARBLED_ISSUE in BODY_TEXT_DECLARATIONS['pdf_text']
