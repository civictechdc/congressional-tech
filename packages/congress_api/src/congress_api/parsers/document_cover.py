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
    return legislative_cover_fields(clean) or ({'content_document_kind': [kind]} if kind else {})


def legislative_cover_fields(clean: str) -> dict[str, list[str]]:
    """Require a measure heading, chamber and operative form, including drafts.

    A draft's blank number establishes its form but supplies no citation.
    Passed bills headed AN ACT are legislative text, without implying enactment.
    """
    measure = re.search(
        r'(?m)^(?:\d+(?:ST|ND|RD|TH|D)\s+SESSION\s+)?'
        r'(S\.(?:\s*(?:J\.|CON\.)?\s*RES\.)?|H\.\s*(?:R\.|(?:J\.|CON\.)?\s*RES\.))'
        r'\s*(\d+|L{2,})\s*$', clean)
    if not measure or not ('IN THE SENATE OF THE UNITED STATES' in clean
                          or 'IN THE HOUSE OF REPRESENTATIVES' in clean):
        return {}
    congress = re.search(r'\b(\d{1,3})(?:ST|ND|RD|TH)\s+(?:CONGRESS|CONG\.)', clean)
    if not measure[2].isdigit() and not congress:
        return {}
    fields = {}
    if re.search(r'^AMENDMENT IN THE NATURE OF A SUBSTITUTE\b', clean, re.M):
        kind = 'amendment'
        fields['content_amendment_type'] = ['substitute']
    elif (re.search(r'^AMENDMENT NO\.', clean, re.M)
          and re.search(r'^AMENDMENT INTENDED TO BE PROPOSED BY\b', clean, re.M)
          and re.search(r'^VIZ:', clean, re.M)):
        kind = 'amendment'
    elif (re.search(r'^(?:A BILL|AN ACT)$', clean, re.M)
          and re.search(r'^BE IT ENACTED\b', clean, re.M)):
        kind = 'legislative-text'
    elif (re.search(r'^(?:(?:JOINT|CONCURRENT) )?RESOLUTION$', clean, re.M)
          and re.search(r'^RESOLVED\b', clean, re.M)):
        kind = 'legislative-text'
    else:
        return {}
    if measure[2].isdigit():
        prefix = re.sub(r'\s+', '', measure[1])
        prefix = prefix.replace('CON.RES.', 'Con.Res.').replace('RES.', 'Res.')
        fields['content_citation'] = [prefix + ' ' + measure[2]]
    if congress:
        fields['content_congress'] = [congress[1]]
    return {'content_document_kind': [kind], **fields}


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
