"""Real-reader regression checks for audit failures; no replacement readers."""
from io import BytesIO
from pathlib import Path
import gzip
import subprocess
import sys

import pytest
from pypdf import PdfWriter

from congress_api.parsers.archive_links import inspect_body
from congress_api.parsers.pdf_tools import PdfToolError, _run, opening_page_text, reader_versions
from congress_api.retention.capture_metadata import read_document

FIXTURES = Path(__file__).parent / 'fixtures/capture-failures'


def test_missing_terminal_eof_uses_structure_and_keeps_truncation_failed():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    data = output.getvalue().replace(b'%%EOF', b'')
    assert inspect_body(data, 'https://example.gov/file.pdf', 'application/pdf') == ('saved', 'pdf')
    assert inspect_body(data[:100], 'https://example.gov/file.pdf', 'application/pdf') == ('invalid_document', 'pdf')


@pytest.mark.parametrize('name', ['numeric-operand.pdf.gz', 'malformed-text-array.pdf.gz'])
def test_real_pdf_text_failures_recover_with_poppler(name):
    data = gzip.decompress((FIXTURES / name).read_bytes())
    assert opening_page_text(data, 1).strip()
    result = read_document(data, name, 'test-readers')
    assert result['status'] == 'completed'
    assert result['body_format'] == ['pdf']
    assert result['error_type'] is None


def test_pdf_tools_enforce_deadline_output_cap_and_reap():
    with pytest.raises(PdfToolError, match='deadline'):
        _run([sys.executable, '-c', 'import time; time.sleep(3)'], timeout=0.05)
    with pytest.raises(PdfToolError, match='output limit'):
        _run([sys.executable, '-c', 'print("x" * 10000)'], output_limit=100)
    with pytest.raises(PdfToolError, match='unavailable'):
        _run(['/nonexistent/capture-pdf-tool'])
    assert all('unavailable' != value for value in reader_versions().values())
