"""Recognize explicit committee document forms from native PDF opening pages."""
from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

COVER_FIELDS = frozenset({'content_document_kind', 'content_citation', 'content_congress',
                         'content_amendment_type'})


def senate_hearing_citation(text: str) -> str | None:
    """Require the publication citation and cover structure, not topic words."""
    lines = [' '.join(line.split()) for line in text.upper().splitlines()]
    citation = next((match for line in lines if (match := re.fullmatch(
        r'S\.\s*H\s*RG\.\s*([1-9][0-9]{0,2})\s*[-–—]\s*([1-9][0-9]*)', line))), None)
    if (citation is None or 'HEARING' not in lines or 'BEFORE THE' not in lines
            or 'UNITED STATES SENATE' not in lines
            or not any(line.startswith('COMMITTEE ON ') for line in lines)
            or not any(re.fullmatch(r'U\.S\. GOVERNMENT (?:PUBLISHING|PRINTING) OFFICE', line) for line in lines)):
        return None
    return f'S. Hrg. {citation[1]}-{citation[2]}'


def document_page_fields(first: str, second: str = '') -> dict[str, list[str]]:
    """Recognize a document's opening form, not a citation or topic in its prose."""
    if citation := senate_hearing_citation(first):
        return {'content_document_kind': ['published-hearing'], 'content_citation': [citation]}
    # A blank/scanned cover can precede the first page of proceedings. Do not
    # search a later appendix when the opening page has a different form.
    opening = first.strip() or second.strip()
    lines = [re.sub(r'^\s*[·.]?\d{1,2}[·.]?\s+', '', line).strip()
             for line in opening.upper().splitlines()]
    clean = '\n'.join(line for line in lines if line)
    compact = re.sub(r'\s+', '', clean[:2200])
    senate = 'UNITEDSTATESSENATE' in compact or 'U.S.SENATE' in compact
    committee = 'COMMITTEEON' in compact or 'COMMITTEE' in compact and senate
    kind = None
    if (re.match(r'STENOGRAPHIC\s+TRANSCRIPT\b', clean) and senate and committee
            or senate and committee and re.search(
                r'THE(?:SUB)?COMMITTEEMET,PURSUANTTONOTICE', compact)
            and len(re.findall(r'^\s*[·.]?\d{1,2}[·.]?\s+', opening, re.M)) >= 8):
        kind = 'transcript'
    elif re.match(r'OPENING\s+STATEMENT\b', clean) or re.match(
            r"(?:SENATOR|SEN\.|CHAIRMAN|CHAIRWOMAN|RANKING MEMBER) [^\n]{1,90}['’]S OPENING STATEMENT\s*(?:\n|$)", clean):
        kind = 'opening-statement'
    elif re.match(r'SENATE\s+ARMED\s+SERVICES\s+COMMITTEE\s+PAPER\s+HEARING\s+QUESTIONS\b', clean):
        kind = 'questions-and-answers'
    elif ((re.match(r'(?:(?:PREPARED|WRITTEN)\s+)?(?:TESTIMONY|STATEMENT)\s+(?:OF|BY|BEFORE)\b', clean)
           or re.search(r'^TESTIMONY\s*\nBEFORE (?:THE )?(?:SPECIAL )?COMMITTEE\b', clean[:900], re.M))
          and senate and committee and 'BEFORE' in compact):
        kind = 'witness-statement'
    # Official legislative covers require their own measure line, chamber
    # heading and operative document wording. A referenced bill is insufficient.
    measure = re.search(r'(?m)^(?:\d+(?:ST|ND|RD|TH)\s+SESSION\s+)?(S\.|H\.\s*R\.)\s*(\d+)\s*$', clean)
    chamber = 'IN THE SENATE OF THE UNITED STATES' in clean or 'IN THE HOUSE OF REPRESENTATIVES' in clean
    fields = {}
    if measure and chamber:
        if re.search(r'^AMENDMENT IN THE NATURE OF A SUBSTITUTE\b', clean, re.M):
            kind = 'amendment'
            fields['content_amendment_type'] = ['substitute']
        elif re.search(r'^A BILL$', clean, re.M) and re.search(r'BE IT ENACTED', clean):
            kind = 'legislative-text'
        if kind in {'amendment', 'legislative-text'}:
            fields['content_citation'] = [('S.' if measure[1] == 'S.' else 'H.R.') + ' ' + measure[2]]
            if congress := re.search(r'\b(\d{1,3})(?:ST|ND|RD|TH)\s+(?:CONGRESS|CONG\.)', clean):
                fields['content_congress'] = [congress[1]]
    return {'content_document_kind': [kind], **fields} if kind else {}


def document_cover(data: bytes) -> dict[str, list[str]]:
    """Read at most two opening pages; unreadable or ambiguous content abstains.

    The caller bounds and validates the supplied body. No OCR or network access.
    """
    if not data.lstrip().startswith(b'%PDF-'):
        return {}
    try:
        pdf = PdfReader(BytesIO(data))
        # Some public PDFs set owner permissions but open without a password.
        # Required user passwords still abstain; no guessing or OCR is involved.
        if pdf.is_encrypted and not pdf.decrypt(''):
            return {}
        if not pdf.pages:
            return {}
        first = pdf.pages[0].extract_text() or ''
        if result := document_page_fields(first):
            return result
        # Second-page fallback is exclusively for coverless proceedings, not
        # a new cover or an opening statement embedded in a different document.
        if not first.strip() and len(pdf.pages) > 1:
            result = document_page_fields('', pdf.pages[1].extract_text() or '')
            if result.get('content_document_kind') == ['transcript']:
                return result
    except (PyPdfError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        return {}
    return {}
