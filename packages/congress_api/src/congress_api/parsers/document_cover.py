"""Recognize explicit committee document forms from native PDF opening pages."""
from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

COVER_FIELDS = frozenset({'content_document_kind', 'content_citation', 'content_congress',
                         'content_amendment_type'})


def _page_text(page, data, number, read_page):
    try:
        return page.extract_text() or ''
    except (PyPdfError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        # A separate parser handles readable PDFs with unsupported content
        # operands. Page selection and classification still follow the same rules.
        return read_page(data, number)


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
    if house_hearing_cover(first):
        return {'content_document_kind': ['published-hearing']}
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
    existing = committee_resolution_fields(clean) or legislative_cover_fields(clean) or ({'content_document_kind': [kind]} if kind else {})
    # Preserve established readings. New forms require the first page, never
    # an attachment or a cover on the optional second page.
    return existing or (explicit_form_fields(clean) if first.strip() else {})


def house_hearing_cover(text: str) -> bool:
    """Require a House publication cover; its serial is not a GPO citation."""
    original = [' '.join(line.split()) for line in text.splitlines() if line.strip()]
    lines = [line.upper() for line in original]
    if not lines or re.match(r'(?:REPORT|SUMMARY|MEMORANDUM|LETTER|DEAR|TESTIMONY|STATEMENT|PREPARED STATEMENT)\b', lines[0]):
        return False
    title_end = next((n for n in range(len(lines) - 1)
                      if lines[n:n + 2] == ['HEARING', 'BEFORE THE']), None)
    # Some readers emit the printing footer before the title. Permit those
    # publication details, but not prose introducing a reproduced cover.
    if title_end is None or title_end > 18:
        return False
    imprint = re.compile(r'(?:U\.S\. GOVERNMENT (?:PUBLISHING|PRINTING) OFFICE|'
                         r'WASHINGTON\s*:.*|FOR SALE BY THE SUPERINTENDENT OF DOCUMENTS.*|'
                         r'INTERNET:.*|FAX:.*|[\d\s–—-]+(?: PDF)?)')
    title = [line for line in original[:title_end] if not imprint.fullmatch(line.upper())]
    if len(title) > 8 or any(re.search(r'[a-z]', line) for line in title):
        return False
    return (
        any(re.fullmatch(r'SERIAL NO\.\s*\d{1,3}\s*[-–—]\s*\d+', line) for line in lines)
        and any(line in {'HOUSE OF REPRESENTATIVES', 'U.S. HOUSE OF REPRESENTATIVES'} for line in lines)
        and any(line.startswith('COMMITTEE ON ') for line in lines)
        and 'PRINTED FOR THE USE OF THE COMMITTEE' in ' '.join(lines)
        and any(re.fullmatch(r'U\.S\. GOVERNMENT (?:PUBLISHING|PRINTING) OFFICE', line) for line in lines)
    )


def explicit_form_fields(clean: str) -> dict[str, list[str]]:
    """Recognize operative amendments and completed committee vote sheets."""
    if operative_amendment(clean):
        return {'content_document_kind': ['amendment']}
    if committee_vote_sheet(clean):
        return {'content_document_kind': ['committee-vote']}
    return {}


def operative_amendment(clean: str) -> bool:
    """Accept drafting headers, then require a target, sponsor and instruction.

    Prefixes are deliberately limited: prose introducing a quoted amendment
    is not an amendment. A change to a substitute does not establish subtype.
    """
    lines = clean.splitlines()
    metadata = re.compile(
        r'(?:[A-Z]:[^\n]*\.XML|[A-Z]{2,}\d{3,}(?: [A-Z0-9]+)?|S\.L\.C\.|'
        r'\d+(?:ST|ND|RD|TH) CONGRESS[^\n]*|\[DISCUSSION DRAFT\]|'
        r'UPDATED DRAFT OF [A-Z]+ \d{1,2}, \d{4}|AMENDMENT #\d+)')
    while lines and metadata.fullmatch(lines[0]):
        lines.pop(0)
    opening = '\n'.join(lines)
    flat = ' '.join(opening.split())
    measure = r'(?:H\.\s*R\.|S\.)\s*(?:\d+|L{2,})\b'
    heading = (
        r'(?:A\s?MENDMENT(?: IN THE NATURE OF A SUBSTITUTE)? TO '
        r'(?:THE AMENDMENT IN THE NATURE OF A SUBSTITUTE TO )?'
        r'|SUBSTITUTE FOR THE AMENDMENT IN THE NATURE OF A SUBSTITUTE TO )'
        + measure)
    offered = re.search(r'\bO\s?FFERED BY\b', flat[:700])
    ordinary = re.match(heading, flat) and offered
    motion = (flat.startswith('AMENDMENT INTENDED TO BE PROPOSED BY ')
              and re.search(r'\bTO THE MOTION OF SENATOR\b.{1,200}\bCOMMITTEE ON\b', flat[:700]))
    if not (ordinary or motion):
        return False
    return bool(re.search(
        r'^(?:STRIKE\b|PAGE\s+\d+\b[^\n]{0,100}\b(?:STRIKE|INSERT|ADD)\b'
        r'|AMEND SECTION\b[^\n]{0,100}\bTO READ AS FOLLOWS\b)', opening[:1800], re.M))


def committee_vote_sheet(clean: str) -> bool:
    """Require a committee heading, roll call, vote columns and recorded marks."""
    lines = clean.splitlines()
    if lines and lines[0].startswith('DATE:'):
        lines = lines[1:]
    if not lines:
        return False
    opening = '\n'.join(lines)
    if lines[0] == 'VOTES OF THE COMMITTEE':
        heading = ('COMMITTEE ON ' in opening[:800]
                   and 'HOUSE OF REPRESENTATIVES' in opening[:800]
                   and 'ROLL CALL VOTE' in opening[:800])
    else:
        heading = (lines[0].startswith('COMMITTEE ON ')
                   and re.search(r'^(?:FULL COMMITTEE\s*[-–—]\s*)?ROLL CALL(?:\s*[#:]\s*\d+)?\s*$', opening[:800], re.M))
    if not heading:
        return False
    members = len(re.findall(r'\b(?:MR|MRS|MS|DR)\.\s+[A-Z]', opening))
    columns = re.search(r'\b(?:AYES?|YEAS?)\b', opening) and re.search(r'\b(?:NO|NAYS?)\b', opening)
    marks = len(re.findall(r'(?<!\w)X{1,2}(?!\w)|[✓✔]', opening))
    return bool(members >= 3 and columns and marks >= 3)


def committee_resolution_fields(clean: str) -> dict[str, list[str]]:
    """Require an explicit House committee heading and operative resolution.

    A filename, subject reference, or resolution quoted in ordinary prose cannot
    establish this form. The classification makes no claim about adoption.
    """
    if not re.match(r'IN THE COMMITTEE ON [^\n]+ OF THE HOUSE OF REPRESENTATIVES\s*\n', clean):
        return {}
    heading = re.search(r'^RESOLUTION\s*$', clean, re.M)
    if heading is None or not re.search(r'^RESOLVED\s*,?\s+THAT\b', clean[heading.end():], re.M):
        return {}
    fields = {'content_document_kind': ['committee-resolution']}
    congress = re.search(r'\b(\d{1,3})(?:ST|ND|RD|TH)\s+CONGRESS\b', clean[:heading.start()])
    if congress:
        fields['content_congress'] = [congress[1]]
    return fields


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


def document_cover(data: bytes, read_page, *, strict: bool = False) -> dict[str, list[str]]:
    """Read at most two opening pages; unreadable or ambiguous content abstains.

    The caller bounds and validates the supplied body and supplies
    `read_page(data, number)`, its bounded reader for pages pypdf cannot extract
    (retention.pdf_tools.opening_page_text). No OCR or network access.
    Capture can request errors to distinguish unreadable PDFs from abstentions.
    """
    if not data.lstrip().startswith(b'%PDF-'):
        return {}
    try:
        with BytesIO(data) as stream, PdfReader(stream) as pdf:
            # Some public PDFs set owner permissions but open without a password.
            # Required user passwords still abstain; no guessing or OCR is involved.
            if pdf.is_encrypted and not pdf.decrypt(''):
                return {}
            if not pdf.pages:
                return {}
            first = _page_text(pdf.pages[0], data, 1, read_page)
            if result := document_page_fields(first):
                return result
            # Second-page fallback is exclusively for coverless proceedings, not
            # a new cover or an opening statement embedded in a different document.
            if not first.strip() and len(pdf.pages) > 1:
                result = document_page_fields('', _page_text(pdf.pages[1], data, 2, read_page))
                if result.get('content_document_kind') == ['transcript']:
                    return result
    except (PyPdfError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        if strict:
            raise
        return {}
    return {}
