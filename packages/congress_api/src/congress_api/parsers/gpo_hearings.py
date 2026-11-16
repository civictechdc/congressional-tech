"""Interpret GovInfo metadata and transcript headings for the hearing summary.

GpoHearing describes the generated summary row, not the native MODS source model."""

from collections.abc import Sequence
import json
import re
from dataclasses import dataclass
from datetime import date, datetime

from congress_shared.dates import congress_to_years
from congress_api.models.gpo import ModsDocument, ModsScope
from congress_api.parsers.gpo import parse_mods_document

## e.g. CHRG-118hhrg57177 -> congress 118, chamber h, jacket 57177
PACKAGE_ID_REGEX = re.compile(r"^CHRG-(\d+)([hsj])hrg(\w+)$")


CHAMBERS = {"h": "house", "s": "senate", "j": "joint"}


# Parser revisions queue bounded repairs even when GovInfo does not change a package.
PARSER_VERSION = "3"


## define columns in the output CSV
@dataclass
class GpoHearing:
    package_id: str
    congress: int
    chamber: str
    event_id: str
    committee_code: str
    committee_name: str
    subcommittees: str
    title: str
    held_date: str
    ## when GovInfo added it; for hearings before ~2009 this is when GPO
    ##  digitized old records, not when the transcript first came out
    date_ingested: str
    days_to_govinfo: str
    serial: str
    witness_count: int
    html_url: str
    pdf_url: str
    last_modified: str
    ## committee code exactly as GPO published it; `committee_code` is cleaned
    ##  (typos fixed, blanks filled from the committee name)
    committee_code_gpo: str = ""
    ## "hearing", or "errata" for errata cover sheets GPO files as separate packages
    record_type: str = "hearing"
    ## the hearing days the transcript's day headers give, ";"-separated, when they say
    ##  more than `held_date` does: every day of a multi-hearing volume, both days of a
    ##  two-day hearing, or the one day GPO got wrong. Blank when the transcript agrees
    ##  with `held_date` or has no day header (scanned prints).
    hearing_dates: str = ""
    ## "yes" once the transcript has been read for its day headers
    text_read: str = ""
    # All bodies/files explicitly listed in root and constituent metadata.
    # Singular columns remain the first value for older readers.
    committee_codes_gpo: str = ""
    committee_codes: str = ""
    html_urls: str = ""
    pdf_urls: str = ""
    # URL-keyed part labels preserve publisher distinctions such as hearing,
    # markup, errata and addendum without splitting the package identity.
    file_metadata: str = ""
    committee_metadata: str = ""
    # `serial` historically held preferredCitation; retain it for old readers.
    preferred_citation: str = ""
    serial_numbers: str = ""
    parser_version: str = ""
    document_class: str = ""
    granule_classes: str = ""
    held_dates: str = ""


def mods_witnesses(data):
    """Witness names and affiliations from MODS, including granule-only lists."""
    from congress_api.parsers.witness_names import is_name, person_key, witness
    found = {}
    ## Some Senate records put witnesses in granules only; deduplicate across both levels.
    for text in (data if isinstance(data, ModsDocument) else parse_mods_document(data)).witnesses:
        fields = witness(text)
        if is_name(fields["name"]):
            found[person_key(fields["name"])] = fields
    return list(found.values())


def mods_title(scope: ModsScope) -> str:
    """The published title, including GovInfo's errata-only title layout."""
    return scope.first('search_titles') or ((scope.titles[0].title or '').strip() if scope.titles else '') or scope.first('errata')


def parse_mods(package_id: str, mods: bytes | str | ModsDocument, last_modified: str) -> GpoHearing:
    """Pull the hearing-level fields out of a GovInfo MODS record."""
    document = mods if isinstance(mods, ModsDocument) else parse_mods_document(mods)
    root = document.root
    match = PACKAGE_ID_REGEX.fullmatch(package_id)
    if match is None:
        raise ValueError(f'Invalid GovInfo hearing package identifier: {package_id}')
    congress, chamber, _ = match.groups()

    # Root and constituent metadata describe package contents. Other related
    # items are cited laws/bills and must not contribute committee ownership.
    committees = root.committees + [c for part in document.constituents for c in part.committees]
    committee_codes = list(dict.fromkeys(c.authority_id.strip().lower()
                                        for c in committees if c.authority_id))
    committee_metadata = []
    for committee in committees:
        claim = {**committee.model_dump(by_alias=True, exclude_unset=True, exclude={'names', 'subcommittees'}),
                 'names': [{'type': n.type, 'name': n.text.strip()} for n in committee.names if n.text],
                 'subcommittees': [n.text.strip() for s in committee.subcommittees for n in s.names if n.text]}
        if claim not in committee_metadata:
            committee_metadata.append(claim)
    ## codes are lowercase in youtube-accounts.csv (a few MODS records aren't)
    committee_code = committee_codes[0] if committee_codes else ""
    committee_name = ""
    subcommittees = []
    for committee in committees:
        if not committee_name:
            committee_name = next((n.text or '' for n in committee.names if n.type == 'authority-standard'), '').strip()
        subcommittees += [
            name.text.strip()
            for subcommittee in committee.subcommittees for name in subcommittee.names
            if name.text
        ]

    ## some hearings span several days; the first is when it started
    held_dates = sorted(value.strip() for value in root.held_dates if value)
    held_date = held_dates[0] if held_dates else ""
    date_ingested = root.first('date_ingested')
    days_to_govinfo = ""
    if held_date and date_ingested:
        days_to_govinfo = str(
            (date.fromisoformat(date_ingested) - date.fromisoformat(held_date)).days
        )

    title = mods_title(root)

    scopes = [root, *document.constituents]
    serial_numbers = list(dict.fromkeys(serial.number.strip()
        for scope in scopes for serial in scope.serials if serial.number and serial.number.strip()))

    def rendition_urls(label):
        return list(dict.fromkeys(item.url.strip() for scope in scopes for item in scope.renditions
                                  if item.display_label == label and item.url and item.url.strip()))

    html_urls, pdf_urls = rendition_urls('HTML rendition'), rendition_urls('PDF rendition')
    file_metadata = {}
    for part in document.constituents:
        label = (part.titles[0].title or '').strip() if part.titles else ''
        part_type = part.first('granule_classes')
        for item in part.renditions:
            if item.display_label in ('HTML rendition', 'PDF rendition') and item.url:
                file_metadata[item.url.strip()] = {'title': label, 'granule_class': part_type}
                if part.titles:
                    for field in ('part_name', 'part_number', 'non_sort'):
                        value = getattr(part.titles[0], field)
                        if value is not None:
                            file_metadata[item.url.strip()][field] = value

    return GpoHearing(
        package_id=package_id,
        congress=int(congress),
        chamber=CHAMBERS[chamber],
        event_id=root.first('event_ids'),
        committee_code=committee_code,
        committee_code_gpo=committee_code,
        committee_codes_gpo=";".join(committee_codes),
        committee_codes=";".join(committee_codes),
        committee_metadata=json.dumps(committee_metadata, ensure_ascii=False, separators=(',', ':')) if committee_metadata else "",
        record_type="errata" if (root.first('is_errata').lower() == 'true'
            or root.first('granule_classes').upper() == 'ERRATA'
            or "[ERRATA]" in title.upper()) else "hearing",
        committee_name=committee_name,
        subcommittees="; ".join(dict.fromkeys(subcommittees)),
        title=" ".join(title.split()),
        held_date=held_date,
        date_ingested=date_ingested,
        days_to_govinfo=days_to_govinfo,
        serial=root.first('preferred_citations'),
        preferred_citation=root.first('preferred_citations'),
        serial_numbers=";".join(serial_numbers),
        parser_version=PARSER_VERSION,
        document_class=root.first('document_classes'),
        granule_classes=";".join(dict.fromkeys(value.strip() for scope in scopes
            for value in scope.granule_classes if value and value.strip())),
        held_dates=";".join(held_dates),
        witness_count=len(dict.fromkeys(value.strip() for scope in scopes
            for value in scope.witnesses if value and value.strip())),
        html_url=html_urls[0] if html_urls else "",
        pdf_url=pdf_urls[0] if pdf_urls else "",
        html_urls=";".join(html_urls),
        pdf_urls=";".join(pdf_urls),
        file_metadata=json.dumps(file_metadata, ensure_ascii=False, separators=(',', ':')) if file_metadata else "",
        last_modified=last_modified,
    )


MONTHS = "January February March April May June July August September October November December".split()


WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()


## a day header stands alone on its line: "WEDNESDAY, FEBRUARY 25, 2015", or in the prints
##  of some committees and in Appropriations volumes "Wednesday, February 25, 2015."
DAY = rf"({'|'.join(WEEKDAYS)}),\s+({'|'.join(MONTHS)})\s+(\d{{1,2}}),\s+(\d{{4}})"


DAY_HEADER = re.compile(rf"^[ \t]*{DAY}\.?[ \t]*$".replace("\\s+", "[ \\t]+"), re.IGNORECASE | re.MULTILINE)


## some volumes' HTML runs the page head and the day header together:
##  "DEPARTMENT OF HOMELAND SECURITY APPROPRIATIONS FOR 2022Wednesday, March 17, 2021DHS ..."
RUNNING_HEAD_DAY = re.compile(rf"APPROPRIATIONS FOR \d{{4}}\s*{DAY}", re.IGNORECASE)


def is_multi_hearing_volume(title: str) -> bool:
    """House Appropriations prints several hearings per volume ("... APPROPRIATIONS FOR 2016"),
    under a title that names none of them."""
    return bool(re.search(r"APPROPRIATIONS FOR \d{4}", title.upper()))


def hearing_days(text: str, congress: int, volume: bool = False) -> list[str]:
    """The days a transcript's day headers name, within the Congress's years. A hearing's print
    sets its day headers one way: where any is in capitals, a date in ordinary case standing
    alone is something else (the dateline of the hearing advisory that Ways and Means prints).
    A multi-hearing volume mixes the two, and every header counts. Headers are taken as printed:
    checking the weekday against the date drops more real days, whose weekday was misprinted,
    than false ones."""
    first_year, _ = congress_to_years(congress)
    capitals, ordinary = set(), set()
    for header in list(DAY_HEADER.finditer(text)) + (list(RUNNING_HEAD_DAY.finditer(text)) if volume else []):
        _, month, day, year = header.groups()
        if first_year - 1 <= int(year) <= first_year + 2:
            try:
                date = datetime(int(year), [m.lower() for m in MONTHS].index(month.lower()) + 1, int(day)).date().isoformat()
            except ValueError:
                continue
            (capitals if header.group(0) == header.group(0).upper() else ordinary).add(date)
    return sorted(capitals | ordinary if volume else capitals or ordinary)


## the chamber line that closes a title page's committee block
CHAMBER_LINE = re.compile(r"^[ \t]*(?:UNITED STATES SENATE|U\.S\. SENATE|(?:U\.S\. )?HOUSE OF REPRESENTATIVES)[ \t]*$", re.MULTILINE)


PARENT_BODY = re.compile(r"(?<![A-Z])((?:(?:SELECT|SPECIAL|JOINT) )?(?:COMMITTEE|COMMISSION|CAUCUS) ON [A-Z][A-Z,'\u2019 \-]*(?:\n[ \t]*(?:\n[ \t]*)*(?!(?:BEFORE THE|UNITED STATES)\b)[A-Z][A-Z,'\u2019 \-]*)?)")


SMALL_WORDS = {"on", "the", "and", "of", "for", "in", "to"}


def committee_on_title_page(text: str) -> str:
    """The committee a transcript's title page names, in GPO's style ("Committee on the Judiciary"), or "".
    The title page reads "BEFORE THE / SUBCOMMITTEE ON ... / OF THE / COMMITTEE ON THE JUDICIARY /
    UNITED STATES SENATE": the body wanted is the last one named before the chamber line."""
    chamber = CHAMBER_LINE.search(text[:8000])
    named = PARENT_BODY.findall(text[:chamber.start()]) if chamber else []
    if not named:
        return ""
    words = re.sub(r"\s+", " ", named[-1]).strip(" ,-").lower().split()
    return " ".join(w if i and w in SMALL_WORDS else w.capitalize() for i, w in enumerate(words))


_GPO_VERDATE_RE = re.compile(
    r"^\s*VerDate\b[^\n]*(?:Jkt\s+\d+|Frm\s+\d+|Fmt\s+\d+|Sfmt\s+\d+)[^\n]*$",
    re.I | re.M,
)
_GPO_COVER_CUE_RE = re.compile(
    r"\b(?:OVERSIGHT\s+|FIELD\s+|JOINT\s+)?HEARINGS?\s+BEFORE\s+THE\b",
    re.I,
)
_GPO_IMPRINT_OR_SERIAL_RE = re.compile(
    r"\b(?:SERIAL\s+NO\.\s*\d{1,3}|S\.\s*HRG\.\s*\d{1,3}|U\.S\.\s+GOVERNMENT\s+(?:PUBLISHING|PRINTING)\s+OFFICE)\b",
    re.I,
)
_GPO_TOC_OR_TURN_RE = re.compile(
    r"(?:^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES|"
    r"STATEMENTS|WITNESSES|PANEL\s+(?:[IVX]+|\d+|ONE|TWO|THREE))\s*$|"
    r"\b(?:The\s+(?:Chairman|Chairwoman|Chair)|(?:Senator|Representative|Mr\.|Ms\.|Mrs\.)\s+[A-Z][a-z]+)\s*\.\s+[A-Z])",
    re.M,
)
_STENO_COVER_RE = re.compile(
    r"\b(?:STENOGRAPHIC\s+TRANSCRIPT|ALDERSON\s+(?:COURT\s+)?REPORTING|RPTS\s+[A-Z0-9]+|DCN\s+\d+)\b",
    re.I,
)
_STENO_ROSTER_RE = re.compile(r"^\s*(?:APPEARANCES|PRESENT|ALSO\s+PRESENT)\s*:?\s*$", re.I | re.M)
_STENO_GAVEL_OR_INDEX_RE = re.compile(
    r"(?:^\s*(?:I\s*N\s*D\s*E\s*X|C\s*O\s*N\s*T\s*E\s*N\s*T\s*S)\s*$|"
    r"\[Whereupon\b|\bThe\s+(?:Chairman|Chairwoman|Chair)\s*(?:\[|\.))",
    re.M,
)
_GPO_GAVEL_CUT_RE = re.compile(
    r"(?:^\s*OPENING\s+STATEMENT\s+OF\s+(?:THE\s+)?HON\.?\s+[A-Z]|"
    r"^\s*The\s+(?:Chairman|Chairwoman|Chair)\s*(?:\[[^\]]+\])?\s*\.\s+(?:The\s+(?:committee|subcommittee|hearing)\s+will\s+come\s+to\s+order|Good\s+(?:morning|afternoon))|"
    r"\[Whereupon\b)",
    re.I | re.M,
)
_PANEL_LINE_RE = re.compile(
    r"^\s*PANEL\s+([IVXLC]+|\d+|ONE|TWO|THREE|FOUR|FIVE|SIX)(?:\s*[-–—:]\s*(.+))?$",
    re.I,
)
_LEADER_PAGE_RE = re.compile(r"(?:\s*[.·•]{2,}\s*|\s{3,})(\d{1,4})\s*$")
_TOC_SUBITEM_SKIP_RE = re.compile(
    r"^(?:prepared\s+statement|written\s+statement|statement\s*$|biography|truth\s+in\s+testimony|"
    r"responses?\s+to\s+(?:written\s+|post-hearing\s+|additional\s+)?questions|"
    r"answers?\s+to\s+(?:written\s+|post-hearing\s+|additional\s+)?questions|"
    r"questions?\s+for\s+the\s+record|"
    r"letters?\s+submitted|materials?\s+submitted|submissions?\s+for\s+the\s+record|"
    r"additional\s+material|appendix|index\b|opening\s+statement\s+of\b)",
    re.I,
)
_MEMBER_TOC_LINE_RE = re.compile(
    r"\b(?:a\s+(?:Representative|Senator|Delegate|Resident\s+Commissioner)\s+in\s+Congress|"
    r"U\.?\s*S\.?\s+(?:Senator|Representative)\s+from\s+(?:the\s+State\s+of\s+)?[A-Z]|"
    r"(?:Chairman|Chairwoman|Ranking\s+Member),\s*(?:Committee|Subcommittee)\s+on)\b",
    re.I,
)
_WITNESS_PREFIX_STRIP_RE = re.compile(
    r"^(?:Statement\s+of\s+|Testimony\s+of\s+)(?=(?:The\s+Honorable|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.|Gen\.|Adm\.|[A-Z][a-z]+))",
    re.I,
)
_STAPLED_TTF_CUE_RE = re.compile(
    r"\b(?:Truth\s+in\s+Testimony\s+Disclosure\s+Form|"
    r"Instructions\s+for\s+Completing\s+the\s+Truth\s+in\s+Testimony|"
    r"Witness\s+Disclosure\s+Requirement\s*[-–—:]?\s*[\"“']?Truth\s+in\s+Testimony)\b",
    re.I,
)
_STAPLED_TTF_BODY_RE = re.compile(
    r"\b(?:Witness\s+Name|nongovernmental\s+entit(?:y|ies)|fiduciary\s+positions?|"
    r"federal\s+grants?\s+or\s+contracts?|foreign\s+government|clause\s+2\(g\)\(5\))\b",
    re.I,
)
_STAPLED_BIO_HEAD_RE = re.compile(
    r"^\s*(?:Page\s+\d+(?:\s+of\s+\d+)?\s+)?"
    r"(?:CURRICULUM\s+VITAE|VITAE|R[EÉ]SUM[EÉ]|BIOGRAPHY(?:\s+OF\s+[A-Z][^\n]{1,80})?|"
    r"BIOGRAPHICAL\s+SKETCH(?:\s+OF\s+[A-Z][^\n]{1,80})?)\s*$",
    re.I | re.M,
)
_STAPLED_QFR_HEAD_RE = re.compile(
    r"^\s*(?:POST-HEARING\s+|ADDITIONAL\s+|WRITTEN\s+)?"
    r"(?:RESPONSES?\s+TO\s+|ANSWERS?\s+TO\s+)?QUESTIONS?\s+FOR\s+THE\s+RECORD\b",
    re.I | re.M,
)
_STAPLED_QFR_BODY_RE = re.compile(
    r"\b(?:Question\s*\d*\s*[:.]|Q\s*\d+\s*[:.]|Response\s*:|Answer\s*:)",
    re.I,
)
_STAPLED_VOTE_HEAD_RE = re.compile(
    r"\b(?:ROLL\s+CALL(?:\s+VOTE)?|VOTES\s+OF\s+THE\s+COMMITTEE)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class StapledPacketBoundary:
    """Contiguous 1-indexed page span inside a multi-artifact witness submission packet."""

    kind: str
    start_page: int
    end_page: int
    marker: str


def _join_pages_12(pages_1_to_2: str | Sequence[str]) -> str:
    if isinstance(pages_1_to_2, str):
        return pages_1_to_2
    return "\n".join(str(p or "") for p in list(pages_1_to_2)[:2])


def is_gpo_cover_roster_only(pages_1_to_2: str | Sequence[str]) -> bool:
    """Return True when GPO hearing pages 1-2 hold only the cover and standing committee roster."""
    raw = _join_pages_12(pages_1_to_2)
    flat = " ".join(raw.split())
    if not flat:
        return False
    if not (_GPO_COVER_CUE_RE.search(flat) and _GPO_IMPRINT_OR_SERIAL_RE.search(flat)):
        return False
    return not bool(_GPO_TOC_OR_TURN_RE.search(raw))


def is_steno_cover_roster_only(pages_1_to_2: str | Sequence[str]) -> bool:
    """Return True when stenographic transcript pages 1-2 hold only the cover and appearances roster."""
    raw = _join_pages_12(pages_1_to_2)
    if not raw.strip():
        return False
    if not (_STENO_COVER_RE.search(raw) and _STENO_ROSTER_RE.search(raw)):
        return False
    return not bool(_STENO_GAVEL_OR_INDEX_RE.search(raw))


def parse_gpo_contents_witnesses(contents_text: str) -> dict[str, object]:
    """Extract structured ``CONTENTS`` / witness-panel blocks and witness entries from GPO frontmatter."""
    cleaned = _GPO_VERDATE_RE.sub("", contents_text or "")
    m_cut = _GPO_GAVEL_CUT_RE.search(cleaned)
    if m_cut:
        cleaned = cleaned[:m_cut.start()]

    lines = [line.rstrip() for line in cleaned.splitlines()]
    has_contents_header = any(
        re.match(
            r"^\s*(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES|WITNESSES|STATEMENTS)\s*$",
            ln,
            re.I,
        )
        for ln in lines
    )

    # Merge wrapped GPO TOC witness lines where a hanging-indent continuation carries the leader dots + page
    merged_entries: list[str] = []
    pending = ""
    pending_indent = 0
    in_toc_zone = not has_contents_header
    for raw_ln in lines:
        expanded = raw_ln.expandtabs(4)
        cur_indent = len(expanded) - len(expanded.lstrip(" "))
        s = " ".join(raw_ln.split())
        if not s or set(s) <= {"-", "_", "=", "(", ")"}:
            if pending:
                merged_entries.append(pending)
                pending = ""
            continue
        if re.match(
            r"^(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|CHRONOLOGICAL\s+LIST\s+OF\s+WITNESSES|WITNESSES|STATEMENTS|PAGE)\s*$",
            s,
            re.I,
        ):
            in_toc_zone = True
            if pending:
                merged_entries.append(pending)
                pending = ""
            continue
        if not in_toc_zone:
            continue
        if _PANEL_LINE_RE.match(s):
            if pending:
                merged_entries.append(pending)
                pending = ""
            merged_entries.append(s)
            continue
        if DAY_HEADER.match(s):
            if pending:
                merged_entries.append(pending)
                pending = ""
            continue
        is_indented_cont = bool(pending) and cur_indent >= pending_indent + 2 and not _LEADER_PAGE_RE.search(pending)
        if is_indented_cont:
            pending = f"{pending} {s}"
            if _LEADER_PAGE_RE.search(pending):
                merged_entries.append(pending)
                pending = ""
        else:
            if pending:
                merged_entries.append(pending)
            pending = s
            pending_indent = cur_indent
            if _LEADER_PAGE_RE.search(pending):
                merged_entries.append(pending)
                pending = ""
    if pending:
        merged_entries.append(pending)

    panels: list[dict[str, object]] = []
    current_panel: str | None = None
    panel_bucket: list[dict[str, object]] = []
    witnesses: list[dict[str, object]] = []

    def flush_panel() -> None:
        nonlocal panel_bucket
        if current_panel is not None or panel_bucket:
            panels.append({"panel": current_panel, "witnesses": list(panel_bucket)})
            panel_bucket = []

    for entry in merged_entries:
        m_panel = _PANEL_LINE_RE.match(entry)
        if m_panel:
            flush_panel()
            token = m_panel.group(1).upper()
            word_to_roman = {"ONE": "I", "TWO": "II", "THREE": "III", "FOUR": "IV", "FIVE": "V", "SIX": "VI"}
            norm_tok = word_to_roman.get(token, token)
            current_panel = f"Panel {norm_tok}"
            continue

        page_num: int | None = None
        m_pg = _LEADER_PAGE_RE.search(entry)
        body_entry = entry[:m_pg.start()].strip(" .,;-") if m_pg else entry.strip()
        if m_pg:
            page_num = int(m_pg.group(1))

        if not body_entry or _TOC_SUBITEM_SKIP_RE.match(body_entry) or _MEMBER_TOC_LINE_RE.search(body_entry):
            continue
        body_entry = _WITNESS_PREFIX_STRIP_RE.sub("", body_entry).strip()
        # Require either a TOC page number or an explicit Panel block with person-shaped comma/title structure
        if page_num is None and current_panel is None:
            continue
        if not re.search(r"[A-Z][a-z]+", body_entry):
            continue

        parts = [p.strip() for p in body_entry.split(",") if p.strip()]
        if not parts:
            continue
        # Handle "Surname, Given Name, Position, Organization" vs "Hon. Given Surname, Position, Organization"
        honorific_lead = bool(
            re.match(r"^(?:The\s+Honorable|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.|Ambassador|Gen\.|Adm\.|Lt\.\s*Gen\.|Maj\.\s*Gen\.|Rear\s+Adm\.|Vice\s+Adm\.)\b", parts[0], re.I)
        )
        if (
            not honorific_lead
            and len(parts) >= 2
            and " " not in parts[0]
            and re.match(
                r"^(?:(?:The\s+Honorable|Hon\.|Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.|Ambassador|Gen\.|Adm\.)\s+)?"
                r"[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+(?:Jr\.|Sr\.|II|III|IV))?$",
                parts[1],
                re.I,
            )
        ):
            name = f"{parts[1]} {parts[0]}".strip()
            rem = parts[2:]
        else:
            name = parts[0]
            rem = parts[1:]

        if len(name.split()) < 2 and not honorific_lead:
            continue
        position = rem[0] if len(rem) >= 1 else ""
        organization = ", ".join(rem[1:]) if len(rem) >= 2 else ""

        rec: dict[str, object] = {
            "name": name,
            "position": position,
            "organization": organization,
            "panel": current_panel,
            "page": page_num,
        }
        witnesses.append(rec)
        panel_bucket.append(rec)

    flush_panel()
    norm_block = "\n".join(
        line.strip() for line in cleaned.splitlines() if line.strip()
    )[:3600]
    return {
        "has_contents_header": has_contents_header,
        "contents_block": norm_block,
        "panels": panels,
        "witnesses": witnesses,
    }


def extract_gpo_p3_p8_witness_panels(
    pages: Sequence[str],
    *,
    start_page: int = 3,
    end_page: int = 8,
) -> dict[str, object]:
    """Extract GPO witness panels and ``CONTENTS`` frontmatter from pages ``p3..p8`` (1-indexed)."""
    page_list = [str(p or "") for p in pages]
    cover_only = is_gpo_cover_roster_only(page_list[:2]) or is_steno_cover_roster_only(page_list[:2])
    lo = max(1, start_page) - 1
    hi = min(len(page_list), max(start_page, end_page))
    slice_pages = page_list[lo:hi] if lo < len(page_list) else []
    rescue_page_numbers = list(range(lo + 1, lo + 1 + len(slice_pages)))
    parsed = parse_gpo_contents_witnesses("\n\n".join(slice_pages)) if slice_pages else {
        "has_contents_header": False,
        "contents_block": "",
        "panels": [],
        "witnesses": [],
    }
    return {
        "cover_roster_only_p12": cover_only,
        "rescue_pages": rescue_page_numbers,
        **parsed,
    }


def _classify_backpage_start(page_text: str) -> tuple[str, str] | None:
    """Identify whether a back page starts a stapled TTF, biography/CV, QFR, or committee vote."""
    if not page_text or not page_text.strip():
        return None
    head = page_text[:1000]
    flat_head = " ".join(head.split())

    if _STAPLED_TTF_CUE_RE.search(flat_head[:700]) and _STAPLED_TTF_BODY_RE.search(page_text[:1800]):
        return "truth-in-testimony", "Truth in Testimony Disclosure Form"

    if _STAPLED_QFR_HEAD_RE.search(head[:550]) and _STAPLED_QFR_BODY_RE.search(page_text[:1800]):
        return "questions-and-answers", "Questions for the Record"

    if _STAPLED_VOTE_HEAD_RE.search(flat_head[:500]) and (
        re.search(r"\b(?:YEAS?|AYES?)\b", page_text[:1600], re.I)
        and re.search(r"\b(?:NAYS?|NOES?)\b", page_text[:1600], re.I)
    ):
        return "committee-vote", "Roll Call Vote"

    # Stapled CV / witness biography: explicit header or CV section grid without testimony salutation
    if not re.search(r"\b(?:thank\s+you\s+for\s+the\s+opportunity\s+to\s+testify|Respectfully\s+submitted)\b", page_text[:1400], re.I):
        if _STAPLED_BIO_HEAD_RE.search(head[:450]):
            return "witness-biography", "Witness Biography / CV"
        upper_lines = "\n".join(ln.strip() for ln in page_text[:2000].upper().splitlines() if ln.strip())
        if (
            re.search(r"^EDUCATION$", upper_lines, re.M)
            and re.search(r"^(?:PROFESSIONAL\s+|ACADEMIC\s+|WORK\s+)?EXPERIENCE$|^EMPLOYMENT(?:\s+HISTORY)?$", upper_lines, re.M)
            and len(re.findall(r"\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|PRESENT|CURRENT)\b", upper_lines)) >= 2
        ):
            return "witness-biography", "Curriculum Vitae"

    return None


def detect_stapled_witness_packet(pages: Sequence[str]) -> list[StapledPacketBoundary]:
    """Detect stapled multi-artifact witness packets (statement + stapled TTF / bio / QFR / vote).

    Returns an empty list when the PDF is a single-artifact document (or already begins as a
    standalone TTF, biography, QFR, or vote on page 1). When a witness statement has one or
    more stapled attachments starting on page ``>= 2``, returns contiguous 1-indexed spans
    covering ``1..N`` in page order.
    """
    page_list = [str(p or "") for p in pages]
    if len(page_list) < 2:
        return []
    # Do not split if page 1 is already a standalone TTF, bio/CV, QFR, or vote sheet.
    if _classify_backpage_start(page_list[0]) is not None:
        return []

    transitions: list[tuple[int, str, str]] = []
    active_kind = "witness-statement"
    for idx in range(1, len(page_list)):
        hit = _classify_backpage_start(page_list[idx])
        if hit is not None:
            new_kind, marker = hit
            # Multi-page TTF forms repeat headers on page 2 of the TTF; merge consecutive identical kinds
            if new_kind != active_kind:
                transitions.append((idx + 1, new_kind, marker))
                active_kind = new_kind

    if not transitions:
        return []

    spans: list[StapledPacketBoundary] = [
        StapledPacketBoundary(
            kind="witness-statement",
            start_page=1,
            end_page=transitions[0][0] - 1,
            marker="Prepared Witness Statement",
        )
    ]
    for i, (start_pg, kind, marker) in enumerate(transitions):
        end_pg = transitions[i + 1][0] - 1 if i + 1 < len(transitions) else len(page_list)
        spans.append(
            StapledPacketBoundary(
                kind=kind,
                start_page=start_pg,
                end_page=end_pg,
                marker=marker,
            )
        )
    return spans

