"""Body-text derivations, one small body per parser (data model §6.6).

Expectations come from the bodies' own words and page layout, not from re-running the rule.
"""
import gzip
import hashlib
from pathlib import Path
import signal
import time

import pytest

from body_text_fixtures import HTML, PAGE_ONE, PAGE_TWO, WEB_PAGE, XML, scanned_pdf, two_page_pdf, warc_member
from congress_api.parsers import body_text as bt
from congress_api.retention.sniff import read_sniff


def sniff(payload):
    return read_sniff(lambda start, length: payload[start:start + length], stored_size=len(payload))['format']


def derive(data, parser, strategy=None, deadline=30.0):
    return bt.derive(data, parser, strategy=strategy or bt.native_only(), page_deadline_seconds=deadline,
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


class FixedBackend:
    """An ImageBackend standing in for Apple Vision: its configuration names the macOS build."""
    def __init__(self):
        self.pages = 0

    def recognize(self, image):
        from spicy_docs.extraction import Recognition
        self.pages += 1
        return Recognition('VISION TEXT', {'backend': 'fixed', 'macos_build': '25Y111'}, None)


def test_the_declared_rule_recognizes_only_the_textless_page_and_records_it():
    backend = FixedBackend()
    reading = derive(scanned_pdf(), 'pdf_text', strategy=bt.page_rule(backend))
    assert backend.pages == 1 and reading.ocr_pages == (2,) and reading.macos_build == '25Y111'
    assert reading.text == PAGE_ONE + '\nVISION TEXT'
    assert reading.row()['fingerprint'] is None  # OCR output is not a native layer
    with pytest.raises(bt.OcrRequired):  # the default rule on a host without the engine
        derive(scanned_pdf(), 'pdf_text')


def footer_over_scan():
    """A GPO hearing page whose body is an inserted scan: only the VerDate footer is native text."""
    import pymupdf
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(180)
    page.insert_image(pymupdf.Rect(60, 60, 540, 700), pixmap=pixmap)
    footer = ['VerDate Nov 24 2008', '10:22 Feb 03, 2020', 'Jkt 000000', 'PO 00000', 'Frm 00558', 'Fmt 6601',
              'Sfmt 6602', 'C:\\USERS\\WR47328\\DESKTOP\\39567', 'WILDA']
    for i, line in enumerate(footer):
        page.insert_text((30, 720 + 8 * i), line, fontsize=6)
    return document.tobytes()


def test_the_rule_counts_text_after_gpo_normalization_so_a_footer_alone_goes_to_ocr():
    from spicy_docs.extraction import NativeText
    data = footer_over_scan()
    assert derive(data, 'pdf_text', strategy=NativeText()).text == ''  # GPO normalization drops the footer
    backend = FixedBackend()
    reading = derive(data, 'pdf_text', strategy=bt.page_rule(backend))
    assert backend.pages == 1 and reading.ocr_pages == (1,) and reading.text == 'VISION TEXT'


def test_the_declared_engine_is_vision_in_three_bands_on_raw_rgb_at_200_dpi():
    from spicy_docs.extraction import NativeOrOcr
    from spicy_docs.extraction.ocr import AppleVision, ExtractionError
    try:
        rule = bt.apple_vision()
    except (ImportError, ValueError, ExtractionError) as error:  # a host without Vision refuses the engine up front
        pytest.skip(f'no Apple Vision here: {error}')
    assert isinstance(rule.strategy, NativeOrOcr) and rule.strategy.normalize is bt.gpo_page
    assert rule.strategy.min_chars == bt.OCR_MIN_CHARS and rule.strategy.require_images
    backend = rule.strategy.backend
    assert isinstance(backend, AppleVision)
    assert {k: backend.configuration()[k] for k in ('recognition_level', 'language_correction', 'bands')} == dict(
        recognition_level='accurate', language_correction=False, bands=3)
    assert (rule.reader.dpi, rule.reader.raw_rgb) == (bt.OCR_DPI, True)


def test_a_blank_page_without_an_image_stays_native():
    import pymupdf
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), PAGE_ONE, fontsize=9)
    document.new_page()
    reading = derive(document.tobytes(), 'pdf_text')
    assert reading.status == 'completed' and reading.ocr_pages == () and reading.text == PAGE_ONE + '\n'


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


def test_web_page_text_has_no_script_or_css_and_block_elements_do_not_glue_words():
    reading = derive(WEB_PAGE, 'html_text')
    # Each block element's words on their own line; an inline <b> breaks nothing. spicy-docs 0.79.0 read
    # this page as its JSON-LD, CSS, script, <noscript> and <template> text, then
    # 'AboutChairHearingsArchived2021MarchThe full committee met.It adjourned.'
    assert reading.text == ('About\nChair\nHearings\nArchived\n2021\nMarch\n'
                            'The full committee met.\nIt adjourned.')
    for mark in ('JSONLD_MARK', 'CSS_MARK', 'SCRIPT_MARK', 'NOSCRIPT_MARK', 'TEMPLATE_MARK',
                 'schema.org', 'dataLayer', 'margin', 'Hearings | Committee'):
        assert mark.encode() in WEB_PAGE and mark not in reading.text
    assert derive(warc_member(WEB_PAGE), 'warc').text == reading.text


def test_html_tags_gpo_never_closes_do_not_refuse_the_body():
    # GPO prints literal <bullet> tags inside a report's <pre>; 300 unclosed ones passed the old depth of 256.
    reading = derive(b'<html><body><pre>' + b'<bullet> item\n' * 300 + b'</pre></body></html>', 'html_text')
    assert reading.status == 'completed' and reading.text == ' item\n' * 300


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
    assert 'U+FFFD' in BODY_TEXT_DECLARATIONS['pdf_text'] and f'raw RGB at {bt.OCR_DPI} dpi' in BODY_TEXT_DECLARATIONS['pdf_text']
    assert f'in {bt.OCR_BANDS} horizontal bands' in BODY_TEXT_DECLARATIONS['pdf_text']
    assert 'as normalize_gpo_pages leaves it' in BODY_TEXT_DECLARATIONS['pdf_text']


FIXTURES = __import__('pathlib').Path(__file__).parent / 'fixtures'


def test_real_gpo_cover_reads_natively_and_a_real_scan_waits_for_ocr():
    cover = derive((FIXTURES / 'document-covers/house-hearing.pdf').read_bytes(), 'pdf_text')
    assert cover.status == 'completed' and cover.fields == {'page_count': 1}
    assert 'U.S. GOVERNMENT PRINTING OFFICE' in cover.text and 'Superintendent of Documents' in cover.text
    with pytest.raises(bt.OcrRequired):  # a scanned witness statement: no native layer on page 1
        derive((FIXTURES / 'meeting_inventory/witness-scan-judiciary.pdf').read_bytes(), 'pdf_text')


def test_body_text_evidence_is_recorded_and_its_drift_is_named():
    import json
    from congress_api.lake import reading_version_diagnostics as diagnostics
    recorded = json.loads((diagnostics.ROOT / diagnostics.BASELINE).read_text())
    current = diagnostics.body_text_evidence(diagnostics.ImportClosure(diagnostics.ROOT))
    for parser in ('pdf_text', 'html_text', 'xml_text', 'warc'):
        assert recorded[parser]['version'] == current[parser]['version']
        assert recorded[parser]['sample_sha256'] == diagnostics.sample_digest(parser)
    moved = dict(current['pdf_text'], pymupdf='0.0.0')
    [(parser, message)] = diagnostics.drift_messages({'pdf_text': current['pdf_text']}, {'pdf_text': moved})
    assert parser == 'pdf_text' and '(pymupdf)' in message
    # A host without Vision has no OCR build to compare.
    assert not list(diagnostics.drift_messages({'pdf_text': current['pdf_text']},
                                               {'pdf_text': dict(current['pdf_text'], macos_build=None)}))


# ct-r91j (owner, 2026-11-11): reading evidence covers only the code a reader runs to turn a body into text.
BODY_TEXT = ('pdf_text', 'html_text', 'xml_text', 'warc')
PAGE = ('html', 'xml', 'json')


def edited_checkout(tmp_path, relative):
    """This checkout under tmp_path with one file's bytes changed: every entry is a link into the
    real tree except the folders leading to `relative` and `relative` itself, an edited copy."""
    from congress_api.lake.reading_version_diagnostics import ROOT
    source, mirror = ROOT, tmp_path / 'checkout'
    for part in Path(relative).parts:
        mirror.mkdir()
        for entry in source.iterdir():
            if entry.name != part:
                (mirror / entry.name).symlink_to(entry)
        source, mirror = source / part, mirror / part
    comment = b'#' if source.suffix == '.py' else b'--'
    mirror.write_bytes(source.read_bytes() + b'\n' + comment + b' an edit (ct-r91j test)\n')
    return tmp_path / 'checkout'


@pytest.fixture(scope='module')
def evidence_now():
    from congress_api.lake import reading_version_diagnostics as diagnostics
    return diagnostics.snapshot()


def moved_entries(before, root):
    from congress_api.lake import reading_version_diagnostics as diagnostics
    after = diagnostics.snapshot(root)
    assert set(after) == set(before)
    return {entry for entry in before if any(before[entry][field] != after[entry][field]
                                             for field in ('workspace_sha256', 'locked_sha256'))}


# Each was edited this week without any reader running it, and each edit warned on readers:
# W1 and W5 (client), W1 and W4 (provenance), ct-an6o and ct-p394 (versions), table I/O, and
# the retention tables the retention package's initializer re-exports.
@pytest.mark.parametrize('plumbing', [
    'packages/docspec_client/src/docspec_client/client.py',
    'packages/congress_api/src/congress_api/retention/provenance.py',
    'packages/congress_api/src/congress_api/lake/versions.py',
    'packages/congress_api/src/congress_api/lake/tables.py',
    'packages/congress_api/src/congress_api/retention/weekly_tables.py',
])
def test_an_edit_to_plumbing_no_reader_runs_leaves_every_reading_evidence_value(tmp_path, evidence_now, plumbing):
    assert moved_entries(evidence_now, edited_checkout(tmp_path, plumbing)) == set()


# Code a reader runs to turn a body into text still moves that reader: its parser, the derivation,
# the format sniff body text routes by, the shared dispatcher and worker, and the bundle's own SQL.
@pytest.mark.parametrize('code,readers', [
    ('packages/congress_api/src/congress_api/parsers/body_text.py', set(BODY_TEXT)),
    ('packages/congress_api/src/congress_api/lake/body_text.py', set(BODY_TEXT)),
    ('packages/congress_api/src/congress_api/retention/sniff.py', {'sniff', 'readings', *BODY_TEXT}),
    ('packages/congress_api/src/congress_api/parsers/archive_readings.py', {*PAGE, 'readings', *BODY_TEXT}),
    ('packages/congress_api/src/congress_api/parsers/html_metadata.py', {'html_metadata'}),
    ('packages/congress_api/src/congress_api/lake/readings.py',
     {'sniff', *PAGE, 'html_metadata', 'readings', *BODY_TEXT}),
    ('packages/congress_api/src/congress_api/retention/parser_worker.py',
     {'sniff', *PAGE, 'html_metadata', 'readings', *BODY_TEXT}),
    ('model/sql/sniff-facts.sql', {'readings'}),
    # The selection rule pinned-readings.sql reads (selected_readings_steps).
    ('packages/congress_api/src/congress_api/lake/compatible_versions.py', {'readings'}),
])
def test_an_edit_to_code_a_reader_runs_moves_that_readers_evidence(tmp_path, evidence_now, code, readers):
    assert readers <= moved_entries(evidence_now, edited_checkout(tmp_path, code))


def test_a_stopped_folder_is_neither_walked_nor_hashed(monkeypatch):
    """The walk stops at a STOP prefix, folder or file; evidence must drop by the same rule, not only exact files."""
    from congress_api.lake import reading_version_diagnostics as diagnostics
    folder = diagnostics.SOURCE / 'models'  # the page readers import from it
    assert any(path.startswith(folder.as_posix() + '/') for path in diagnostics.evidence_files()['html'])
    monkeypatch.setattr(diagnostics, 'STOP', (*diagnostics.STOP, folder))
    assert not [path for path in diagnostics.evidence_files()['html'] if path.startswith(folder.as_posix() + '/')]


def reader_runs(tmp_path):
    """Each group of entries and a call that runs its reader's worker callable over its fixture bodies:
    readings.parse_payload for the sniff, page and HTML metadata readers, parse_once_payload for the
    bundle, and lake/body_text.parse_payload for the body-text readers."""
    import json
    from congress_api.lake import body_text, compatible_versions, readings
    from congress_api.lake.reading_version_diagnostics import ROOT
    cases = [(case['body'].encode(), case['parser']) for case in json.loads((ROOT / 'model/fixtures/parser-cases.json').read_text())]
    bodies = {'pdf': (two_page_pdf(), 'pdf_text'), 'html': (HTML, 'html_text'), 'xml': (XML, 'xml_text'),
              'web': (WEB_PAGE, 'html_text'), 'warc': (warc_member(HTML), 'warc'), 'gzip': (gzip.compress(HTML), 'html_text'),
              'cover': ((FIXTURES / 'document-covers/house-hearing.pdf').read_bytes(), 'pdf_text')}
    metadata = (FIXTURES / 'html_metadata/marked-no-statement.html').read_bytes()
    written = iter(range(10 ** 6))

    def payload(stored, **fields):
        path = tmp_path / f'body-{next(written)}'
        path.write_bytes(stored)
        # The gzip storage case is known by its decoded hash; every other body by its stored bytes.
        plain = HTML if stored is bodies['gzip'][0] else stored
        return json.dumps(dict(fields, path=str(path), stored_bytes=len(stored),
                               body_sha=hashlib.sha256(plain).hexdigest())).encode()

    def body_text_worker():
        for data, parser in bodies.values():
            texts = tmp_path / f'texts-{next(written)}'
            texts.mkdir()
            body_text.parse_payload(payload(data, parser=parser, strategy=bt.DEFAULT_STRATEGY,
                                            page_deadline_seconds=0, texts=str(texts)))

    def bundle():
        for data, _ in cases:
            path = tmp_path / f'cache-{next(written)}'
            readings.parse_once_payload(payload(data, cache=str(path), known_format=None, skip_parsers=[],
                versions={name: 'sample' for name in compatible_versions.LEAF_PARSERS}))

    return {
        ('sniff',): lambda: [readings.parse_payload(payload(data, parser='sniff'))
                             for data in [data for data, _ in cases] + [data for data, _ in bodies.values()]],
        PAGE: lambda: [readings.parse_payload(payload(data, parser=parser)) for data, parser in cases],
        ('html_metadata',): lambda: readings.parse_payload(payload(metadata, parser='html_metadata')),
        ('readings',): bundle,
        BODY_TEXT: body_text_worker,
    }


def traced(run, evidence, monkeypatch):
    """Workspace files whose functions ran in `run`, with every reader cache emptied first, so what a run
    reaches does not depend on what ran before it in this process. Function bodies only: module and
    class bodies are import-time code, not reading."""
    import inspect
    import sys
    from congress_api.lake import body_text
    from congress_api.lake.reading_version_diagnostics import ROOT
    held = {str(ROOT / path) for files in evidence.values() for path in files}
    for module in list(sys.modules.values()):
        if getattr(module, '__file__', None) in held:
            for value in list(vars(module).values()):
                if callable(getattr(value, 'cache_clear', None)):
                    value.cache_clear()
    monkeypatch.setattr(body_text, '_STRATEGIES', {})
    ran = set()

    def profile(frame, event, arg):
        name = frame.f_code.co_filename
        if event == 'call' and frame.f_code.co_flags & inspect.CO_OPTIMIZED and '/src/' in name \
                and name.startswith(str(ROOT)) and '/.venv/' not in name:
            ran.add(Path(name).relative_to(ROOT).as_posix())

    sys.setprofile(profile)
    try:
        run()
    finally:
        sys.setprofile(None)
    return ran


def test_every_file_a_reader_runs_on_its_fixtures_is_in_its_evidence(tmp_path, monkeypatch):
    """The declared reader modules, checked against execution: each reader's worker callable runs its fixture
    bodies under a profiler, and every workspace file whose functions ran must be among that entry's evidence
    files. It cannot see branches the fixtures do not reach (the remote read path, most refusals)."""
    from congress_api.lake import reading_version_diagnostics as diagnostics
    monkeypatch.setenv('DOCSPEC_PARSER_IO_MARKER', str(tmp_path / 'io.phase'))
    evidence = diagnostics.evidence_files()
    for entries, run in reader_runs(tmp_path).items():
        ran = traced(run, evidence, monkeypatch)
        assert ran, entries
        for entry in entries:
            assert ran <= evidence[entry], (entry, sorted(ran - evidence[entry]))
