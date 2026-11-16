"""Recognize explicit committee document forms from native PDF opening pages."""
from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

COVER_FIELDS = frozenset({'content_document_kind', 'content_citation', 'content_congress',
                         'content_amendment_type'})

_EMBARGO_LINE_RE = re.compile(
    r'^(?:'
    r'(?:STRICTLY\s+)?EMBARGOED\s+(?:UNTIL|FOR\s+RELEASE)\b[^\n]*|'
    r'HOLD\s+FOR\s+RELEASE\b[^\n]*|'
    r'(?:NOT\s+)?FOR\s+RELEASE\s+(?:ON\s+DELIVERY|UNTIL)\b[^\n]*|'
    r'UNTIL\s+DELIVERY\b[^\n]*|'
    r'PLEASE\s+CHECK\s+AGAINST\s+DELIVERY\b[^\n]*'
    r')$',
    re.I,
)
_EMBARGO_ANY_RE = re.compile(
    r'(?:^\s*(?:STRICTLY\s+)?EMBARGOED\s+(?:UNTIL|FOR\s+RELEASE)\b|'
    r'\bEMBARGOED\s+UNTIL\s+(?:DELIVERY|\d{1,2}:\d{2}|THE\s+START\s+OF)|'
    r'^\s*HOLD\s+FOR\s+RELEASE\s+UNTIL\b|'
    r'\bFOR\s+RELEASE\s+ON\s+DELIVERY\b)',
    re.I | re.M,
)
_MEMBER_SPEAKER_RE = re.compile(
    r'\b(?:U\.?\s*S\.?\s+SENATOR|SENATOR|SEN\.|U\.?\s*S\.?\s+REPRESENTATIVE|REPRESENTATIVE|REP\.|'
    r'CONGRESSMAN|CONGRESSWOMAN|CHAIRMAN|CHAIRWOMAN|CHAIR\b|CO-CHAIR(?:MAN|WOMAN)?|'
    r'RANKING\s+MEMBER|VICE\s+CHAIR(?:MAN|WOMAN)?|DELEGATE|RESIDENT\s+COMMISSIONER)\b',
    re.I,
)
_NOMINEE_DESIGNATION_RE = re.compile(
    r'\b(?:NOMINEE\s+(?:TO\s+BE|FOR)\b|DESIGNATE\s+TO\s+BE\b|'
    r'NOMINATED\s+TO\s+(?:BE|SERVE\s+AS)\b|'
    r'APPEAR(?:ING)?\s+BEFORE\s+YOU\s+TODAY\s+AS\s+(?:THE\s+|PRESIDENT\s+[^\n]{1,40}\s+)?NOMINEE\b|'
    r'HONORED\s+TO\s+BE\s+NOMINATED\b)',
    re.I,
)
_HONORABLE_RE = re.compile(r'\b(?:THE\s+HONORABLE|HON\.)\b', re.I)
_WITNESS_EXEC_ROLE_RE = re.compile(
    r'\b(?:(?:DEPUTY\s+|UNDER\s+|ASSISTANT\s+|ACTING\s+)?SECRETARY\b|'
    r'(?:DEPUTY\s+|ACTING\s+)?ADMINISTRATOR\b|'
    r'(?:DEPUTY\s+|ACTING\s+)?COMMISSIONER\b|'
    r'COMPTROLLER\s+GENERAL\b|INSPECTOR\s+GENERAL\b|ATTORNEY\s+GENERAL\b|SURGEON\s+GENERAL\b|'
    r'(?:DEPUTY\s+|ASSOCIATE\s+|ACTING\s+|EXECUTIVE\s+|MANAGING\s+)?DIRECTOR\b|'
    r'AMBASSADOR\b|GENERAL\b|LIEUTENANT\s+GENERAL\b|MAJOR\s+GENERAL\b|BRIGADIER\s+GENERAL\b|'
    r'ADMIRAL\b|VICE\s+ADMIRAL\b|REAR\s+ADMIRAL\b|'
    r'CHIEF\s+EXECUTIVE\s+OFFICER\b|CEO\b|CHIEF\s+OPERATING\s+OFFICER\b|COO\b|'
    r'(?:VICE\s+)?PRESIDENT\b|(?:SENIOR\s+)?FELLOW\b|PROFESSOR\b|PROF\.\b|DEAN\b|PROVOST\b)',
    re.I,
)
_WITNESS_ACADEMIC_PREFIX_RE = re.compile(r'\b(?:DR\.|PH\.?D\.|M\.?D\.)', re.I)
_CRS_CODE_RE = re.compile(r'\b(R\d{4,5}|RL\d{4,5}|RS\d{4,5}|IF\d{5}|IN\d{5}|LSB\d{5})\b')
_GAO_REPORT_ID_RE = re.compile(r'\b(GAO-\d{2}-\d{3,6}[A-Z]?)\b')
_GAO_TESTIMONY_OR_CORRESP_RE = re.compile(r'\bGAO-\d{2}-\d{3,6}[TR]\b')
_CBO_BILL_CITATION_RE = re.compile(
    r'\b((?:H\.\s*R\.|S\.|H\.\s*(?:J\.|CON\.)?\s*RES\.|S\.\s*(?:J\.|CON\.)?\s*RES\.)\s*\d+)\b',
    re.I,
)


def _strip_leading_embargo_lines(clean: str) -> tuple[str, bool]:
    lines = clean.splitlines()
    idx = 0
    had_embargo = bool(_EMBARGO_ANY_RE.search(clean[:600]))
    while idx < min(len(lines), 6) and _EMBARGO_LINE_RE.match(lines[idx].strip()):
        had_embargo = True
        idx += 1
    return '\n'.join(lines[idx:]), had_embargo


def _extract_congress(clean: str, limit: int = 900) -> str | None:
    m = re.search(r'\b(1[0-2]\d)(?:ST|ND|RD|TH)\s+CONGRESS\b', clean[:limit])
    return m.group(1) if m else None


def _is_nominee_or_witness_opening(unembargoed: str) -> bool:
    """Return True only when positive nominee or non-Member witness evidence overrides ``OPENING STATEMENT``."""
    head = unembargoed[:900]
    lines = head.splitlines()
    if not lines:
        return False
    speaker_lines: list[str] = []
    for line in lines[:5]:
        if re.match(r'^(?:TO\s+CONDUCT\b|ROOM\s+|DIRKSEN\b|HART\b|RUSSELL\b|RAYBURN\b|LONGWORTH\b|CANNON\b)', line):
            break
        speaker_lines.append(line)
        if re.search(r'\bBEFORE\s+THE\b', line):
            break
    speaker_block = ' '.join(speaker_lines)
    if _MEMBER_SPEAKER_RE.search(speaker_block):
        return False
    if _NOMINEE_DESIGNATION_RE.search(head):
        return True
    has_before_committee = bool(
        re.search(
            r'\bBEFORE\s+THE\s+(?:U\.?\s*S\.?\s+)?(?:SENATE\s+|HOUSE\s+)?(?:PERMANENT\s+SELECT\s+|SELECT\s+|SPECIAL\s+)?(?:SUB)?COMMITTEE\b',
            head[:600],
        )
    )
    if not (re.match(r'OPENING\s+STATEMENT\s+(?:OF|BY)\s+', speaker_block) and has_before_committee):
        return False
    if _WITNESS_EXEC_ROLE_RE.search(speaker_block):
        return True
    if not _HONORABLE_RE.search(speaker_block) and _WITNESS_ACADEMIC_PREFIX_RE.search(speaker_block):
        return True
    return False


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
    unembargoed, has_embargo = _strip_leading_embargo_lines(clean)
    compact = re.sub(r'\s+', '', clean[:2200])
    senate = 'UNITEDSTATESSENATE' in compact or 'U.S.SENATE' in compact
    house = 'HOUSEOFREPRESENTATIVES' in compact or 'U.S.HOUSE' in compact
    committee = 'COMMITTEEON' in compact or ('COMMITTEE' in compact and (senate or house))
    kind = None
    if (re.match(r'STENOGRAPHIC\s+TRANSCRIPT\b', clean) and senate and committee
            or senate and committee and re.search(
                r'THE(?:SUB)?COMMITTEEMET,PURSUANTTONOTICE', compact)
            and len(re.findall(r'^\s*[·.]?\d{1,2}[·.]?\s+', opening, re.M)) >= 8):
        kind = 'transcript'
    elif re.match(
            r"(?:SENATOR|SEN\.|REPRESENTATIVE|REP\.|CHAIRMAN|CHAIRWOMAN|RANKING MEMBER) [^\n]{1,90}['’]S OPENING STATEMENT\s*(?:\n|$)",
            unembargoed):
        kind = 'opening-statement'
    elif re.match(r'OPENING\s+STATEMENT\b', unembargoed):
        # SFRC / Senate / Executive / Judicial nominee "Opening Statement" guard:
        # a nominee's or non-Member witness's "Opening Statement" is witness-statement, never opening-statement.
        kind = 'witness-statement' if _is_nominee_or_witness_opening(unembargoed) else 'opening-statement'
    elif re.match(r'SENATE\s+ARMED\s+SERVICES\s+COMMITTEE\s+PAPER\s+HEARING\s+QUESTIONS\b', unembargoed):
        kind = 'questions-and-answers'
    elif ((re.match(r'(?:(?:PREPARED|WRITTEN|ORAL)\s+)?(?:TESTIMONY|STATEMENT)\s+(?:OF|BY|BEFORE)\b', unembargoed)
           or re.search(r'^(?:PREPARED\s+|WRITTEN\s+)?(?:TESTIMONY|STATEMENT)\s*\nBEFORE (?:THE )?(?:U\.S\. )?(?:SENATE |HOUSE )?(?:PERMANENT SELECT |SELECT |SPECIAL )?(?:SUB)?COMMITTEE\b', unembargoed[:900], re.M))
          and committee and 'BEFORE' in compact):
        kind = 'witness-statement'
    existing = committee_resolution_fields(clean) or legislative_cover_fields(clean) or ({'content_document_kind': [kind]} if kind else {})
    # Preserve established readings. New forms require the first page, never
    # an attachment or a cover on the optional second page.
    return existing or (explicit_form_fields(clean, raw_first=first, has_embargo=has_embargo) if first.strip() else {})


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


def explicit_form_fields(
    clean: str,
    *,
    raw_first: str = '',
    has_embargo: bool = False,
) -> dict[str, list[str]]:
    """Recognize explicit Tier-1 committee and legislative-branch document covers."""
    if operative_amendment(clean):
        return {'content_document_kind': ['amendment']}
    if committee_vote_sheet(clean):
        return {'content_document_kind': ['committee-vote']}
    for check in (
        truth_in_testimony_fields,
        nominee_questionnaire_fields,
        lambda c: qfr_fields(c, has_embargo=has_embargo),
        subpoena_fields,
        attendance_sheet_fields,
        markup_notice_fields,
        witness_list_fields,
        cv_resume_fields,
        federal_register_fields,
        lambda c: crs_report_fields(raw_first, c),
        lambda c: gao_report_fields(raw_first, c),
        cbo_cost_estimate_fields,
        staff_report_fields,
    ):
        if fields := check(clean):
            return fields
    return {}


def truth_in_testimony_fields(clean: str) -> dict[str, list[str]]:
    """Recognize House Truth in Testimony (TTF) disclosure forms."""
    head = clean[:1200]
    flat = ' '.join(head.split())
    has_title = bool(
        re.search(
            r'\b(?:TRUTH\s+IN\s+TESTIMONY\s+DISCLOSURE\s+FORM|'
            r'INSTRUCTIONS\s+FOR\s+COMPLETING\s+THE\s+TRUTH\s+IN\s+TESTIMONY|'
            r'WITNESS\s+DISCLOSURE\s+REQUIREMENT\s*[-–—:]?\s*["“\']?TRUTH\s+IN\s+TESTIMONY)\b',
            flat[:700],
        )
    )
    has_form_fields = bool(
        re.search(
            r'\b(?:WITNESS\s+NAME|NONGOVERNMENTAL\s+ENTIT(?:Y|IES)|FIDUCIARY\s+POSITIONS?|'
            r'FEDERAL\s+GRANTS?\s+OR\s+CONTRACTS?|FOREIGN\s+GOVERNMENT|CLAUSE\s+2\(G\)\(5\))\b',
            flat,
        )
    )
    if not (has_title and has_form_fields):
        return {}
    fields = {'content_document_kind': ['testimony-disclosure']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def nominee_questionnaire_fields(clean: str) -> dict[str, list[str]]:
    """Recognize SFRC / SJQ / Senate executive & judicial nominee questionnaires (never QFR)."""
    flat = ' '.join(clean[:1400].split())
    is_questionnaire = bool(
        re.search(
            r'\b(?:QUESTIONNAIRE\s+FOR\s+(?:JUDICIAL\s+|NON-JUDICIAL\s+|EXECUTIVE\s+)?NOMINEES|'
            r'SENATE\s+(?:JUDICIARY\s+COMMITTEE|COMMITTEE\s+ON\s+FOREIGN\s+RELATIONS)\s+QUESTIONNAIRE|'
            r'BIOGRAPHICAL\s+AND\s+FINANCIAL\s+INFORMATION\s+REQUESTED\s+OF\s+NOMINEES|'
            r'NOMINEE\s+QUESTIONNAIRE\s+FOR\s+THE\s+COMMITTEE\s+ON\s+FOREIGN\s+RELATIONS)\b',
            flat[:750],
        )
        or (
            re.search(r'\bCOMMITTEE\s+ON\s+(?:FOREIGN\s+RELATIONS|THE\s+JUDICIARY|ARMED\s+SERVICES|FINANCE|BANKING)\b', flat[:600])
            and re.search(r'\b1\.\s*(?:FULL\s+)?NAME\b', flat[:900])
            and re.search(r'\bPOSITION\s+(?:TO\s+WHICH|FOR\s+WHICH)\s+NOMINATED\b', flat[:1200])
        )
    )
    if not is_questionnaire:
        return {}
    fields = {'content_document_kind': ['questionnaire']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def qfr_fields(clean: str, *, has_embargo: bool = False) -> dict[str, list[str]]:
    """Recognize Questions for the Record (QFR), guarded against SFRC nominee questionnaires & embargo banners."""
    if has_embargo or nominee_questionnaire_fields(clean):
        return {}
    head_lines = '\n'.join(clean.splitlines()[:12])
    flat_head = ' '.join(head_lines.split())
    flat = ' '.join(clean[:1600].split())
    # Exclude prepared witness testimony that merely closes with "happy to answer questions"
    if re.match(r'^(?:(?:PREPARED|WRITTEN|ORAL)\s+)?(?:TESTIMONY|STATEMENT|OPENING\s+STATEMENT)\s+(?:OF|BY)\b', flat_head):
        return {}
    has_qfr_heading = bool(
        re.search(
            r'^(?:POST-HEARING\s+|ADDITIONAL\s+|WRITTEN\s+|SENATE\s+[^\n]{0,60}\s+|HOUSE\s+[^\n]{0,60}\s+)?'
            r'(?:RESPONSES?\s+TO\s+|ANSWERS?\s+TO\s+)?QUESTIONS?\s+FOR\s+THE\s+RECORD\b',
            head_lines,
            re.M,
        )
        or re.search(
            r'\b(?:QUESTIONS\s+FOR\s+THE\s+RECORD\s+(?:SUBMITTED\s+(?:TO|BY)|FROM\s+(?:SENATOR|REPRESENTATIVE|REP\.|SEN\.|THE\s+HONORABLE|CHAIRMAN|RANKING\s+MEMBER))|'
            r'RESPONSES?\s+OF\s+[^\n]{2,90}\s+TO\s+QUESTIONS\s+FOR\s+THE\s+RECORD)\b',
            flat_head,
        )
    )
    has_qa_body = bool(
        re.search(
            r'\b(?:QUESTION\s*\d*\s*[:.]|Q\s*\d+\s*[:.]|RESPONSE\s*:|ANSWER\s*:|'
            r'SUBMITTED\s+BY\s+(?:SENATOR|REPRESENTATIVE|REP\.|SEN\.|CHAIRMAN|RANKING\s+MEMBER)\b|'
            r'HEARING\s+(?:ON|ENTITLED|BEFORE)\b|COMMITTEE\s+ON\b)',
            flat,
        )
    )
    if not (has_qfr_heading and has_qa_body):
        return {}
    fields = {'content_document_kind': ['questions-and-answers']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def subpoena_fields(clean: str) -> dict[str, list[str]]:
    """Recognize formal Congressional subpoenas, excluding notices/memos about subpoenas."""
    head = clean[:1400]
    flat = ' '.join(head.split())
    if re.match(r'^(?:MEMORANDUM|FOR\s+IMMEDIATE\s+RELEASE|PRESS\s+RELEASE|DEAR\s+)\b', flat):
        return {}
    if re.search(r'\b(?:NOTICE\s+OF\s+INTENT\s+TO\s+ISSUE\s+A\s+SUBPOENA|AUTHORIZING\s+(?:THE\s+)?ISSUANCE\s+OF\s+SUBPOENAS?)\b', flat[:700]):
        return {}
    has_authority = bool(
        re.search(
            r'\bBY\s+AUTHORITY\s+OF\s+THE\s+(?:HOUSE\s+OF\s+REPRESENTATIVES|UNITED\s+STATES\s+SENATE)\b',
            flat[:800],
        )
    )
    has_subpoena = bool(re.search(r'^SUBPOENA\b|\bSUBPOENA\s+(?:DUCES\s+TECUM|AD\s+TESTIFICANDUM)\b', head[:600], re.M))
    has_command = bool(
        re.search(r'\bYOU\s+ARE\s+HEREBY\s+COMMANDED\b|\bHEREBY\s+COMMANDED\s+TO\s+(?:BE\s+AND\s+APPEAR|PRODUCE)\b', flat)
    )
    if not ((has_authority and has_command) or (has_subpoena and has_command and 'COMMITTEE' in flat)):
        return {}
    fields = {'content_document_kind': ['subpoena']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def attendance_sheet_fields(clean: str) -> dict[str, list[str]]:
    """Recognize committee quorum / attendance sheets (distinct from roll-call vote tallies)."""
    head = clean[:1400]
    if re.search(r'\bROLL\s+CALL\b', head[:600]) or (
        re.search(r'\b(?:YEAS?|AYES?)\b', head) and re.search(r'\b(?:NAYS?|NOES?)\b', head)
    ):
        return {}
    has_heading = bool(
        re.search(
            r'^(?:(?:FULL\s+)?COMMITTEE\s+ATTENDANCE(?:\s+SHEET|\s+ROSTER)?|'
            r'(?:MARKUP|HEARING|SUBCOMMITTEE)\s+ATTENDANCE(?:\s+SHEET)?|'
            r'ATTENDANCE\s+(?:SHEET|RECORD|ROSTER)|'
            r'QUORUM\s+(?:AND\s+ATTENDANCE\s+)?SHEET)\b',
            head[:500],
            re.M,
        )
    )
    has_committee = 'COMMITTEE ON ' in head or 'SELECT COMMITTEE ' in head or 'SUBCOMMITTEE ON ' in head
    has_present = bool(re.search(r'\bPRESENT\b', head))
    members = len(re.findall(r'\b(?:MR\.|MRS\.|MS\.|DR\.|REP\.|SEN\.|SENATOR|REPRESENTATIVE)\s+[A-Z]', clean[:2400]))
    if not (has_heading and has_committee and has_present and members >= 3):
        return {}
    fields = {'content_document_kind': ['attendance-sheet']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def markup_notice_fields(clean: str) -> dict[str, list[str]]:
    """Recognize Committee Markup Notices, excluding post-markup action sheets/minutes."""
    head = clean[:1200]
    flat = ' '.join(head.split())
    if re.search(r'\b(?:MARKUP\s+ACTION\s+SHEET|THE\s+(?:SUB)?COMMITTEE\s+[^\n]{0,80}\bMET,\s+PURSUANT\s+TO\s+NOTICE|ORDERED\s+REPORTED\s+FAVORABLY)\b', flat):
        return {}
    if 'SUBPOENA' in flat[:500]:
        return {}
    explicit_banner = bool(
        re.search(
            r'^(?:(?:AMENDED|REVISED)\s+)?(?:NOTICE\s+OF\s+(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+|HYBRID\s+)?MARKUP|'
            r'(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+)?MARKUP\s+NOTICE)\b',
            head[:500],
            re.M,
        )
    )
    memo_markup_notice = bool(
        re.match(r'^(?:COMMITTEE\s+ON\s+[^\n]+\n+)?(?:1[0-2]\d(?:ST|ND|RD|TH)\s+CONGRESS\n+)?(?:MEMORANDUM|NOTICE)\b', head)
        and re.search(r'^(?:RE|SUBJECT)\s*:\s*(?:(?:AMENDED|REVISED)\s+)?(?:FULL\s+COMMITTEE\s+|SUBCOMMITTEE\s+)?MARKUP\b', head[:650], re.M)
    )
    has_schedule = bool(
        re.search(r'\b(?:WILL\s+MEET\b|CONVENING\b|DATE\s*:|TIME\s*:|PLACE\s*:|LOCATION\s*:|ROOM\s*:)', flat)
        and 'COMMITTEE' in flat[:800]
    )
    if not ((explicit_banner or memo_markup_notice) and has_schedule):
        return {}
    fields = {'content_document_kind': ['meeting-notice']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def witness_list_fields(clean: str) -> dict[str, list[str]]:
    """Recognize standalone Committee Witness Lists."""
    head = clean[:1000]
    if re.search(r'\b(?:SERIAL\s+NO\.|S\.\s*HRG\.|U\.S\.\s+GOVERNMENT\s+(?:PUBLISHING|PRINTING)\s+OFFICE|STENOGRAPHIC\s+TRANSCRIPT)\b', clean[:1800]):
        return {}
    has_banner = bool(
        re.search(
            r'^(?:(?:REVISED|UPDATED|TENTATIVE)\s+)?(?:WITNESS\s+LIST|LIST\s+OF\s+WITNESSES|WITNESSES\s*$)',
            head[:550],
            re.M,
        )
    )
    has_committee = bool(re.search(r'\b(?:COMMITTEE\s+ON|SUBCOMMITTEE\s+ON|SELECT\s+COMMITTEE|SPECIAL\s+COMMITTEE)\b', head))
    witness_cues = len(
        re.findall(
            r'(?:^PANEL\s+(?:[IVX]+|\d+|ONE|TWO|THREE)\b|^(?:\d+\.\s*)?(?:THE\s+HONORABLE|HON\.|MR\.|MS\.|MRS\.|DR\.|PROF\.|AMBASSADOR|GEN\.|ADM\.|LT\.\s*GEN\.)\s+[A-Z])',
            clean[:2400],
            re.M,
        )
    )
    if not (has_banner and has_committee and witness_cues >= 1):
        return {}
    fields = {'content_document_kind': ['witness-list']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


def cv_resume_fields(clean: str) -> dict[str, list[str]]:
    """Recognize witness CV / Resume / Biography covers."""
    if nominee_questionnaire_fields(clean) or truth_in_testimony_fields(clean):
        return {}
    head = clean[:800]
    if re.search(r'\b(?:THANK\s+YOU\s+FOR\s+THE\s+OPPORTUNITY\s+TO\s+(?:TESTIFY|APPEAR)|QUESTIONS\s+FOR\s+THE\s+RECORD)\b', clean[:1600]):
        return {}
    if re.match(r'^(?:(?:PREPARED|WRITTEN)\s+)?(?:TESTIMONY|STATEMENT)\s+(?:OF|BY)\b', head):
        return {}
    explicit_cv_banner = bool(
        re.search(
            r'^(?:CURRICULUM\s+VITAE|VITAE|R[EÉ]SUM[EÉ]|BIOGRAPHY\s+OF\s+[A-Z]|BIOGRAPHICAL\s+SKETCH(?:\s+OF)?\b)',
            head[:320],
            re.M,
        )
    )
    section_hits = sum(
        bool(re.search(pattern, clean[:2400], re.M))
        for pattern in (
            r'^EDUCATION\s*$',
            r'^(?:PROFESSIONAL\s+|ACADEMIC\s+|WORK\s+|EMPLOYMENT\s+)?EXPERIENCE\s*$|^EMPLOYMENT(?:\s+HISTORY)?\s*$',
            r'^(?:SELECTED\s+)?PUBLICATIONS\s*$|^HONORS(?:\s+AND\s+AWARDS)?\s*$|^AWARDS\s*$|^BOARD\s+MEMBERSHIPS?\s*$',
        )
    )
    date_ranges = len(re.findall(r'\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|PRESENT|CURRENT)\b', clean[:2400]))
    if not (explicit_cv_banner or (section_hits >= 2 and date_ranges >= 2)):
        return {}
    return {'content_document_kind': ['witness-biography']}


def federal_register_fields(clean: str) -> dict[str, list[str]]:
    """Recognize Federal Register notice/rule pages and extract ``<vol> FR <page>`` when present."""
    head = clean[:1200]
    flat = ' '.join(head.split())
    m_banner = re.search(
        r'(?:(\d{1,6})\s+)?FEDERAL\s+REGISTER\s*/\s*VOL\.\s*(\d{1,3})\s*,\s*NO\.\s*\d+\s*/\s*'
        r'(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\s*,\s*[A-Z]+\s+\d{1,2}\s*,\s*(?:19|20)\d{2}\s*/\s*'
        r'(?:NOTICES|RULES\s+AND\s+REGULATIONS|PROPOSED\s+RULES|PRESIDENTIAL\s+DOCUMENTS)(?:\s*/\s*(\d{1,6}))?',
        flat,
    )
    if not m_banner:
        return {}
    has_fr_structure = bool(
        re.search(r'\b(?:ACTION\s*:|SUMMARY\s*:|SUPPLEMENTARY\s+INFORMATION\s*:|BILLING\s+CODE\s+\d|CFR\s+PART\b)', clean[:2400])
    )
    if not has_fr_structure:
        return {}
    fields: dict[str, list[str]] = {'content_document_kind': ['federal-register-notice']}
    page_num = m_banner.group(1) or m_banner.group(3)
    vol_num = m_banner.group(2)
    if vol_num and page_num:
        fields['content_citation'] = [f'{vol_num} FR {page_num}']
    return fields


def crs_report_fields(raw_first: str, clean: str) -> dict[str, list[str]]:
    """Recognize CRS Reports (``R``, ``RL``, ``RS``, ``IF``, ``IN``, ``LSB``), excluding CRS Memoranda."""
    head = clean[:1000]
    if re.search(r'\b(?:MEMORANDUM|CONGRESSIONAL\s+DISTRIBUTION\s+MEMORANDUM|TESTIMONY\s+BEFORE\s+THE)\b', head[:650]):
        return {}
    has_crs_masthead = bool(
        re.search(
            r'\b(?:CONGRESSIONAL\s+RESEARCH\s+SERVICE|CRS\s+REPORT\s+FOR\s+CONGRESS|'
            r'CRS\s+IN\s+FOCUS|CRS\s+INSIGHT|CRS\s+LEGAL\s+SIDEBAR|'
            r'INFORMING\s+THE\s+LEGISLATIVE\s+DEBATE\s+SINCE\s+1914)\b',
            head,
        )
    )
    if not has_crs_masthead:
        return {}
    code_match = _CRS_CODE_RE.search(raw_first[:2600] if raw_first else clean[:2600])
    if not code_match:
        return {}
    return {
        'content_document_kind': ['crs-report'],
        'content_citation': [code_match.group(1).upper()],
    }


def gao_report_fields(raw_first: str, clean: str) -> dict[str, list[str]]:
    """Recognize GAO Reports while strictly excluding ``GAO-YY-NNNT`` testimony & ``R`` correspondence."""
    head = clean[:1100]
    if _GAO_TESTIMONY_OR_CORRESP_RE.search(clean[:2000]) or re.search(r'\bTESTIMONY\b', head[:900]):
        return {}
    has_gao_org = bool(
        re.search(
            r'\b(?:UNITED\s+STATES\s+GOVERNMENT\s+ACCOUNTABILITY\s+OFFICE|'
            r'U\.S\.\s+GOVERNMENT\s+ACCOUNTABILITY\s+OFFICE|'
            r'GAO\s+HIGHLIGHTS)\b',
            head,
        )
    )
    has_report_banner = bool(
        re.search(
            r'\b(?:REPORT\s+TO\s+(?:CONGRESSIONAL\s+(?:REQUESTERS|COMMITTEES)|THE\s+(?:CHAIRMAN|CHAIRWOMAN|RANKING\s+MEMBER|HONORABLE|COMMITTEE|SUBCOMMITTEE))|'
            r'WHY\s+GAO\s+DID\s+THIS\s+STUDY|WHAT\s+GAO\s+FOUND)\b',
            clean[:1600],
        )
    )
    if not (has_gao_org and has_report_banner):
        return {}
    fields: dict[str, list[str]] = {'content_document_kind': ['gao-report']}
    id_match = _GAO_REPORT_ID_RE.search(raw_first[:2400] if raw_first else clean[:2400])
    if id_match:
        code = id_match.group(1).upper()
        if not code.endswith(('T', 'R')):
            fields['content_citation'] = [code]
    return fields


def cbo_cost_estimate_fields(clean: str) -> dict[str, list[str]]:
    """Recognize CBO ``At a Glance`` and classic Congressional Budget Office Cost Estimates."""
    head = clean[:1800]
    flat = ' '.join(head.split())
    classic = bool(re.search(r'\bCONGRESSIONAL\s+BUDGET\s+OFFICE\s+COST\s+ESTIMATE\b', flat[:700]))
    at_a_glance = bool(
        re.search(r'\bAT\s+A\s+GLANCE\b', flat[:500])
        and re.search(r'\b(?:CONGRESSIONAL\s+BUDGET\s+OFFICE|WWW\.CBO\.GOV|CBO\.GOV)\b', flat)
        and re.search(
            r'\b(?:COST\s+ESTIMATE|BY\s+FISCAL\s+YEAR,\s*(?:MILLIONS|BILLIONS)\s+OF\s+DOLLARS|'
            r'PAY-AS-YOU-GO\s+CONSIDERATIONS|AS\s+ORDERED\s+REPORTED\s+BY)\b',
            flat,
        )
    )
    if not (classic or at_a_glance):
        return {}
    fields: dict[str, list[str]] = {'content_document_kind': ['cost-estimate']}
    m_bill = _CBO_BILL_CITATION_RE.search(flat[:650])
    if m_bill:
        norm_bill = re.sub(r'\s+', '', m_bill.group(1).upper())
        norm_bill = (
            norm_bill.replace('H.R.', 'H.R. ')
            .replace('H.J.RES.', 'H.J.Res. ')
            .replace('S.J.RES.', 'S.J.Res. ')
            .replace('H.CON.RES.', 'H.Con.Res. ')
            .replace('S.CON.RES.', 'S.Con.Res. ')
            .replace('H.RES.', 'H.Res. ')
            .replace('S.RES.', 'S.Res. ')
        )
        if norm_bill.startswith('S.') and not norm_bill.startswith(('S.J.', 'S.Con.', 'S.Res.', 'S. ')):
            norm_bill = 'S. ' + norm_bill[2:]
        fields['content_citation'] = [norm_bill.strip()]
    return fields


def staff_report_fields(clean: str) -> dict[str, list[str]]:
    """Recognize formal Committee Majority/Minority/Joint/Bipartisan Staff Reports."""
    head = clean[:1200]
    flat = ' '.join(head.split())
    if re.search(r'\b(?:FOR\s+IMMEDIATE\s+RELEASE|PRESS\s+RELEASE|MEMORANDUM|CONGRESSIONAL\s+RESEARCH\s+SERVICE|GOVERNMENT\s+ACCOUNTABILITY\s+OFFICE)\b', flat[:650]):
        return {}
    if re.search(r'\b(?:H\.\s*REPT\.|S\.\s*REPT\.|HOUSE\s+REPORT\s+1\d{2}|SENATE\s+REPORT\s+1\d{2})\b', flat[:650]):
        return {}
    has_staff_report_banner = bool(
        re.search(
            r'^(?:(?:MAJORITY|MINORITY|JOINT|BIPARTISAN|INTERIM|FINAL|SUBCOMMITTEE|COMMITTEE)\s+)*STAFF\s+REPORT\b',
            head[:700],
            re.M,
        )
        or re.search(
            r'\b(?:A\s+)?(?:MAJORITY|MINORITY|JOINT|BIPARTISAN)\s+STAFF\s+REPORT\s+(?:OF|PREPARED\s+(?:FOR|BY))\b',
            flat[:750],
        )
    )
    has_committee = bool(
        re.search(r'\b(?:COMMITTEE\s+ON|PERMANENT\s+SUBCOMMITTEE\s+ON|SELECT\s+COMMITTEE\s+ON|SPECIAL\s+COMMITTEE\s+ON)\b', flat)
        and re.search(r'\b(?:HOUSE\s+OF\s+REPRESENTATIVES|UNITED\s+STATES\s+SENATE|U\.S\.\s+SENATE|U\.S\.\s+HOUSE|1[0-2]\d(?:ST|ND|RD|TH)\s+CONGRESS)\b', flat)
    )
    if not (has_staff_report_banner and has_committee):
        return {}
    fields: dict[str, list[str]] = {'content_document_kind': ['staff-report']}
    if cong := _extract_congress(clean):
        fields['content_congress'] = [cong]
    return fields


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
