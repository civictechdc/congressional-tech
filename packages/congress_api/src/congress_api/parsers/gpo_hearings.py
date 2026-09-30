"""Interpret GovInfo metadata and transcript headings for the hearing summary.

GpoHearing describes the generated summary row, not the native MODS source model."""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

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
    first_year = 1789 + 2 * (congress - 1)
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
