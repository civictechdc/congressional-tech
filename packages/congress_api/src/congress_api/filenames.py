"""Lossless filename syntax extraction. A filename is evidence, not content truth.

Rules return all matching claims with exact offsets; they do not overwrite source
metadata, resolve people/committees, choose a date convention, or infer MIME types.
The shared-token corpus uses Unicode letter runs and ASCII digit runs, plus
ASCII CamelCase parts. These are observations, not inferred document types.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from congress_api.bill_codes import BILL_TYPES, BILL_VERSIONS, BILLS_HELP_URL, HOUSE_BILL_STAGES, HOUSE_NAMING_URL


class FilenameField(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    raw: str
    start: int
    end: int
    candidates: tuple[str, ...] = ()
    note: str | None = None
    code: str | None = None
    label: str | None = None
    vocabulary_url: str | None = None


class FilenameMatch(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule: str
    start: int
    end: int
    fields: tuple[FilenameField, ...]


class FilenamePiece(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    raw: str
    start: int
    end: int


class ParsedFilename(BaseModel):
    model_config = ConfigDict(frozen=True)
    filename: str
    stem_end: int
    matches: tuple[FilenameMatch, ...]
    pieces: tuple[FilenamePiece, ...]


@dataclass(frozen=True)
class FilenameRule:
    id: str
    pattern: str
    scope: str
    description: str
    flags: int = re.IGNORECASE
    fallback: int = 0


# Separate an outer layout from its inner payload so unusual suffixes are retained.
# "subject_token" is literal: it may be a name, an identifier, or something else.
UNSPONSORED = r'(?!.*-[A-Z][0-9]{6}-Amdt-)'
MEASURE_CODES = '|'.join(sorted(BILL_TYPES, key=lambda v: (-len(v), v)))
# PIH is defined by the House naming guide, separately from GovInfo's common
# versions. PIS remains an unverified source token; neither is shortened to IH/IS.
VERSION_CODES = '|'.join(sorted(set(BILL_VERSIONS) | {'pih', 'pis'}, key=lambda v: (-len(v), v)))
MEASURE_START = rf'-?(?P<measure_token>{MEASURE_CODES}|h)?(?P<measure_number>[0-9]+)'
VERSION_END = rf'(?P<version_token>{VERSION_CODES})(?P<version_number_token>[0-9]+)?(?:\((?P<annotation>[^()]*)\))?'
LEGISLATIVE_TEXT = UNSPONSORED + MEASURE_START + r'(?P<version_prefix>r[0-9]+)?' + VERSION_END + r'(?P<suffix>(?:[-_].*)?)'


def _exclude_full(pattern: str) -> str:
    """Exclude a more specific layout without duplicating its capture names."""
    return '(?!' + re.sub(r'\(\?P<[^>]+>', '(?:', pattern) + r'\Z)'


# Explicit user-reviewed boundary: Interiorih means Interior + ih, not Interio
# + rih. Limit the exception to descriptive text; an actual bare RIH code stays RIH.
DESCRIBED_VERSION_END = VERSION_END.replace('rih', r'(?<!Interio)rih')
DESCRIBED_LEGISLATION = (_exclude_full(LEGISLATIVE_TEXT) + UNSPONSORED + MEASURE_START
    + r'(?P<descriptor>[A-Za-z].*?)' + DESCRIBED_VERSION_END + r'(?P<suffix>(?:[-_].*)?)')
UNLISTED_LEGISLATIVE_VERSION = (_exclude_full(LEGISLATIVE_TEXT) + _exclude_full(DESCRIBED_LEGISLATION)
    + UNSPONSORED + MEASURE_START + r'(?P<version_token>[A-Za-z]{1,6})'
    + r'(?:\((?P<annotation>[^()]*)\))?(?P<suffix>(?:[-_].*)?)')
RULES = (
    FilenameRule('published-hearing', r'(?P<package_family>CHRG)-(?P<congress>[0-9]{3})(?P<publication_code>[hsj]hrg)(?P<publication_number>[0-9]+)(?P<suffix>.*)', 'stem', 'Published hearing package notation; suffix is not discarded.'),
    FilenameRule('published-report', r'(?P<package_family>CRPT)-(?P<congress>[0-9]{3})(?P<publication_code>[hs]rpt)(?P<publication_number>[0-9]+)(?P<suffix>.*)', 'stem', 'Published report package notation.'),
    FilenameRule('published-print', r'(?P<package_family>CPRT)-(?P<congress>[0-9]{3})(?P<publication_code>[hs]prt)(?P<publication_number>[0-9]+)(?P<suffix>.*)', 'stem', 'Published committee-print package notation.'),
    FilenameRule('committee-file', r'(?P<package_family>HHRG|HMKP|HMTG|CRPT)-(?P<congress>[0-9]{3})-(?P<committee_code>[A-Za-z]{2}[0-9]{2})-(?P<payload>.+)', 'stem', 'Committee routing code as printed; no committee identity lookup.'),
    FilenameRule('committee-print-file', r'(?P<package_family>CPRT)-(?P<congress>[0-9]{3})-(?P<publication_code>[HS]PRT)-(?P<committee_code>[A-Za-z]{2}[0-9]{2})-(?P<payload>.+)', 'stem', 'Committee-routed print notation.'),
    FilenameRule('legislative-file', r'(?P<package_family>BILLS)\s*-\s*(?P<congress>[0-9]{3})(?P<payload>.+)', 'stem', 'BILLS is a naming prefix; it does not establish document type.'),
    FilenameRule('report-file', r'(?P<package_family>HRPT|SRPT)-(?P<congress>[0-9]{3})-(?P<payload>.+)', 'stem', 'Loose report-prefixed filename.'),
    FilenameRule('amendment-file', r'(?P<package_family>AMNT|AMDT)-(?P<congress>[0-9]{3})-(?P<payload>.+)', 'stem', 'Amendment-prefixed filename.'),
    FilenameRule('dated-document', r'(?P<date_token>[0-9]{8})-(?P<document_token>[A-Za-z]+)(?P<document_number>[0-9]*)(?P<suffix>.*)', 'committee-payload', 'Date followed by a document token; unknown document tokens remain literal.'),
    FilenameRule('person-document', r'(?P<document_token>Wstate|Mstate|Bio|TTF)-(?P<subject_token>.*?)-(?P<date_token>[0-9]{8})(?P<suffix>(?:[-_].*)?)', 'committee-payload', 'A subject/name slot between document token and date; the slot can be empty.'),
    FilenameRule('token-date-document', r'(?!(?:Wstate|Mstate|Bio|TTF)-)(?P<document_token>[A-Za-z]+)(?P<document_number>[A-Za-z0-9-]*?)-(?P<date_token>[0-9]{8})(?P<suffix>(?:[-_].*)?)', 'committee-payload', 'Document token/identifier followed by date; identifiers can contain ranges or measure references.'),
    FilenameRule('date-only-document', r'(?P<date_token>[0-9]{8})', 'committee-payload', 'Date-only payload.'),
    FilenameRule('sponsored-amendment', r'-?(?P<subject_token>.+)-(?P<bioguide_token>[A-Z][0-9]{6})-(?P<amendment_marker>Amdt)-(?P<amendment_token>.+)', 'legislative-payload', 'Subject, sponsor identifier token, and amendment identifier; no identity resolution.'),
    FilenameRule('legislative-text', LEGISLATIVE_TEXT, 'legislative-payload', 'Number and recognized version token, with numeric modifiers and parenthetical annotations preserved separately. Absent bill type stays absent.'),
    FilenameRule('described-legislation', DESCRIBED_LEGISLATION, 'legislative-payload', 'Numbered legislation with intervening descriptive text and a recognized terminal version token. The description is not swallowed into the code.'),
    FilenameRule('legislative-unlisted-version', UNLISTED_LEGISLATIVE_VERSION, 'legislative-payload', 'Short version-shaped token not recognized by the more specific rules; keep it without assigning an official label.'),
    FilenameRule('measure-list', UNSPONSORED + r'-?(?P<measure_list>(?:SA)?(?:(?:HCONRES|SCONRES|HJRES|SJRES|HRES|SRES|HR|S|H)[0-9]+)+)(?P<suffix>(?:[-_].*)?)', 'legislative-payload', 'One or more printed measure references, possibly followed by a print or other suffix.'),
    FilenameRule('draft-legislation', r'(?P<version_token>pih|pis)(?P<suffix>(?:[-_].*)?)', 'legislative-payload', 'A draft/version token without a supplied measure number.'),
    FilenameRule('unnumbered-measure', r'-?(?P<measure_token>HCONRES|SCONRES|HJRES|SJRES|HRES|SRES|HR|S|H)(?P<number_placeholder>_+|X{2,})(?P<version_token>pih|pis|ih|is)(?P<suffix>(?:[-_].*)?)', 'legislative-payload', 'Explicit placeholder instead of a measure number; it does not become zero or a supplied number.'),
    FilenameRule('named-draft', r'(?P<draft_label>DiscussionDraft|Draft|CommitteeRules|CommitteeResolution|CommitteeRes|CommRes|TFITFR)(?P<identifier_token>[_0-9X-]*)(?P<version_token>pih|pis|ih|is)(?P<suffix>(?:[-_].*)?)', 'legislative-payload', 'Named draft/resolution syntax with an optional literal identifier.'),
    FilenameRule('labeled-subject-date', r'(?P<label>QFR Responses|Prepared Statement|Opening Statement|Written Testimony|Testimony|Witness List|Official Hearing Transcript)[ _-]+(?P<subject_token>.*?)[ _-]+(?P<date_token>(?:19|20)[0-9]{2}[-_.][0-9]{2}[-_.][0-9]{2})(?P<suffix>.*)', 'stem', 'Explicit label, opaque subject text and a year-first date.'),
    FilenameRule('labeled-date', r'(?P<label>Witness List|Official Hearing Transcript|Testimony|Opening Statement)[ _-]+(?P<date_token>[0-9]{1,4}[._-][0-9]{1,2}[._-][0-9]{2,4})(?P<suffix>.*)', 'stem', 'Explicit label followed by date-shaped text; ambiguous dates stay ambiguous.'),
    FilenameRule('compact-testimony', r'(?!.*senatebudgetcommitteetestimony$)(?P<subject_token>[A-Za-z]+?)(?P<document_token>jointtestimony|writtentestimony|writtenstatement|testimony)(?P<context_token>senatebudgetcommittee|usdigitaltrade|with[A-Za-z]+)?', 'stem', 'Joined lowercase words: opaque subject plus a testimony/statement marker and optional context; no person-name segmentation.'),
    FilenameRule('compact-context-testimony', r'(?P<subject_token>[A-Za-z]+?)(?P<context_token>senatebudgetcommittee)(?P<document_token>testimony)', 'stem', 'Joined subject/context/testimony naming convention.'),
    FilenameRule('compact-support', r'(?P<subject_token>[A-Za-z_]+?)(?P<document_token>supportfor|letterofrecommendationfor)(?P<recipient_token>[A-Za-z]+)', 'stem', 'Joined support/recommendation naming convention; both parties remain literal strings.'),
    FilenameRule('compact-transcript', r'(?P<date_or_number_token>[0-9]+)(?P<context_token>[A-Za-z]+?)(?P<document_token>transcript)', 'stem', 'Number followed by joined context/transcript wording; a date interpretation is not imposed.'),
    FilenameRule('compact-opening-statement', r'(?P<date_or_number_token>[0-9]+)(?P<document_token>openingstatement)(?P<context_token>[A-Za-z]+)', 'stem', 'Number and joined opening-statement wording, with the remaining context retained.'),
    FilenameRule('compact-tint', r'(?P<subject_token>[A-Za-z]+?)(?P<document_token>tint)', 'stem', 'Recurring joined tint suffix; its expansion and document contents are not inferred.'),
    FilenameRule('uuid', r'(?<![0-9A-Fa-f])(?P<opaque_uuid>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?![0-9a-f])', 'search', 'UUID-shaped identifier; no meaning or ownership inferred.'),
    FilenameRule('hex-identifier', r'(?<![A-Za-z0-9])(?P<opaque_hex>[0-9a-f]{16,})(?![A-Za-z0-9])', 'search', 'Opaque hexadecimal token; no hash algorithm inferred.'),
    FilenameRule('date-separated', r'(?<![0-9])(?P<date_token>(?:19|20)[0-9]{2}[ ._-][0-9]{1,2}[ ._-][0-9]{1,2}|[0-9]{1,2}[ ._-][0-9]{1,2}[ ._-](?:[0-9]{4}|[0-9]{2}))(?![0-9])', 'search', 'All valid supported date readings are retained; two-digit years are not expanded.'),
    FilenameRule('date-compact', r'(?<![0-9])(?P<date_token>[0-9]{8})(?![0-9])', 'search', 'Eight digits are only a date candidate, even when calendar-valid.'),
    FilenameRule('timestamp-shaped', r'(?<![0-9])(?P<date_token>(?:19|20)[0-9]{6})(?P<time_token>(?:[01][0-9]|2[0-3])[0-5][0-9][0-5][0-9])(?P<fraction_token>[0-9]{3})?(?![0-9])', 'search', 'Compact date/time-shaped sequence and optional millisecond digits; timezone and timestamp role are unknown.'),
    FilenameRule('short-date-compact', r'(?<![0-9])(?P<short_date_token>[0-9]{6})(?![0-9])', 'search', 'Six digits may encode a date or an unrelated number; no date or century is inferred.'),
    FilenameRule('named-month-date', r'(?<![A-Za-z])(?P<month_token>January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?[ _-]*(?P<day_token>[0-9]{1,2})(?:st|nd|rd|th)?(?:[, _-]+(?P<year_token>[0-9]{4}|[0-9]{2}))?(?![0-9])', 'search', 'Printed month/day and optional year tokens, without assigning an event date.'),
    FilenameRule('day-named-month-date', r'(?<![0-9])(?P<day_token>[0-9]{1,2})[ _-]*(?P<month_token>January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)[ _-]*(?P<year_token>[0-9]{4}|[0-9]{2})(?![0-9])', 'search', 'Printed day/month/year tokens, preserving an unspecified century.'),
    FilenameRule('bioguide-token', r'(?<![A-Za-z0-9])(?P<bioguide_token>[A-Z][0-9]{6})(?![A-Za-z0-9])', 'search', 'Bioguide-shaped token; not verified as an assigned identifier.'),
    FilenameRule('measure-reference', r'(?<![A-Za-z])(?P<measure_token>H\.?\s*CON\.?\s*RES\.?|S\.?\s*CON\.?\s*RES\.?|H\.?\s*J\.?\s*RES\.?|S\.?\s*J\.?\s*RES\.?|H\.?\s*RES\.?|S\.?\s*RES\.?|H\.?\s*R\.?|S\.?)[ _-]*(?P<measure_number>[0-9]+)', 'search', 'Measure-shaped notation; all occurrences are retained, without resolving a measure or Congress.'),
    FilenameRule('print-reference', r'(?<![A-Za-z])(?P<print_token>RCP)[ _-]*(?P<print_congress>[0-9]{3})[ _-]+(?P<print_number>[0-9]+)', 'search', 'Rules Committee Print reference, including mixed whitespace/hyphen separators.'),
    FilenameRule('fiscal-year', r'(?<![A-Za-z])(?P<fiscal_marker>FY)[ _-]?(?P<fiscal_year_token>[0-9]{4}|[0-9]{2})(?![0-9])', 'search', 'Fiscal-year token, preserving an unspecified century.'),
    FilenameRule('revision-token', r'(?<![A-Za-z0-9])(?P<revision_marker>Revision|Rev|Update|Version|U|V)[ _.-]?(?P<revision_number>[0-9]+)(?![A-Za-z0-9])', 'search', 'Explicit revision/update-looking token; no chronological ordering inferred.'),
    FilenameRule('revised-token', r'(?<![A-Za-z0-9])(?P<revision_marker>Revised)(?:[ _.-]?(?P<revision_number>[0-9]+))?(?![A-Za-z0-9])', 'search', 'Literal revised wording, with or without a printed number.'),
    FilenameRule('part-token', r'(?<![A-Za-z0-9])(?P<part_marker>Part|Pt)[ _.-]?(?P<part_number>[0-9]+)(?![A-Za-z0-9])', 'search', 'Explicit part marker and number.'),
    FilenameRule('amendment-reference', r'(?<![A-Za-z])(?P<amendment_marker>Amendment|Amdt|Amnt)[ _#.-]*(?P<amendment_token>[0-9]+[A-Za-z]?)(?![A-Za-z0-9])', 'search', 'Printed amendment marker and identifier; does not determine the contents of the file.'),
    FilenameRule('exhibit-reference', r'(?<![A-Za-z])(?P<exhibit_marker>Exhibit|Attachment|Agenda[ _-]+Item)[ _#.-]+(?P<item_token>[0-9]+[A-Za-z]?)(?![A-Za-z0-9])', 'search', 'Printed exhibit, attachment or agenda item identifier.'),
    FilenameRule('document-suffix', r'(?<![A-Za-z0-9])(?P<document_marker>SD|QFR|Vote|RCP)(?P<document_identifier>[0-9]+)(?![A-Za-z0-9])', 'search', 'Numbered document marker, including markers after a subject or date.'),
    FilenameRule('appropriation-routing', r'(?<![A-Za-z])(?P<scope_token>FC|SC)-(?P<committee_token>AP)-(?:(?P<fiscal_marker>FY)(?P<fiscal_year_token>[0-9]{4}|[0-9]{2})(?![0-9]))?(?:-(?P<committee_code>AP[0-9]{2}))?', 'search', 'Literal FC/SC, AP, fiscal-year and routing-code slots; unassigned slots stay empty.'),
    FilenameRule('publication-suffix-marker',
        r'(?<![A-Za-z0-9])(?!(?:part|pt)[ _.-]?[0-9]+(?![A-Za-z0-9]))'
        r'(?P<publication_marker>add|err|vol|v|part|pt)[ _.-]?(?P<publication_identifier>[0-9]+|[IVXLCDM]+|[A-Z])?(?![A-Za-z0-9])',
        'published-suffix-search', 'Literal publication suffix marker and identifier; Roman numerals and letters stay verbatim.'),
    FilenameRule('legislative-amendment-marker',
        r'(?<![A-Za-z0-9])(?P<amendment_marker>HAmdt|SAmdts?|ANS|AINS)(?P<amendment_token>[0-9]+[A-Za-z]?)?(?![A-Za-z0-9])',
        'legislative-text-search', 'Literal amendment-looking notation inside a legislative descriptor or suffix; no code expansion inferred.'),
    FilenameRule('filename-format-marker',
        r'(?<=[_-])(?P<filename_format_token>xml)(?![A-Za-z0-9])',
        'legislative-text-search', 'Separated XML wording inside a legislative filename, without inferring its content format.'),
    FilenameRule('house-stage-marker',
        r'(?<=[_-])(?P<version_token>PIH)(?=[_-]|$)',
        'legislative-text-search', 'Separated House pre-introduction stage retained inside a legislative descriptor or suffix.'),
)
# Additional families run only when the existing inner layouts do not match.
# Tier 1 has explicit structural markers; tier 2 has local identifiers;
# tier 3 retains less-specific descriptive drafts.
# Empty slots and local identifiers are observations, never invented bill numbers.
VERSION_SUFFIX = VERSION_END + r'(?P<suffix>(?:[-_].*)?)'
RULES += (
    FilenameRule('resolution-measure-list',
        r'\s*-?(?P<measure_token>HCONRES|SCONRES|HJRES|SJRES|HRES|SRES)_(?P<measure_number>[0-9]+)?'
        + rf'(?P<measure_list>(?:(?:{MEASURE_CODES})[0-9]+)+)'
        + r'(?:_(?P<numeric_suffix_token>[0-9]+))?(?:_(?P<filename_format_token>xml))?',
        'legislative-payload', 'Resolution notation followed by one or more measures; optional local numeric and format markers remain literal.', fallback=1),
    FilenameRule('placeholder-print-reference',
        rf'-?(?P<measure_token>{MEASURE_CODES})(?P<number_placeholder>_+|X{{2,}})-'
        r'(?P<print_token>RCP)(?P<print_congress>[0-9]{3})-(?P<print_number>[0-9]+)',
        'legislative-payload', 'An unnumbered measure referring to a numbered committee print; the print number is not a bill number.', fallback=1),
    FilenameRule('joined-title-local-code',
        rf'-?(?P<measure_token>(?-i:{MEASURE_CODES}))(?!(?:{VERSION_CODES})-)(?P<descriptor>(?-i:[A-Z][A-Z0-9]*))-(?P<local_code_token>(?-i:[A-Z]+))',
        'legislative-payload', 'Lowercase bill type joined to an uppercase local title and a separated uppercase code; no code expansion inferred.', fallback=1),
    FilenameRule('appropriations-file',
        rf'-?(?P<subject_token>(?:(?P<measure_token>{MEASURE_CODES})(?P<number_placeholder>_+)?|.*?))-(?P<scope_token>[A-Za-z]*)-(?P<committee_token>AP)-'
        r'(?:(?P<fiscal_marker>FY)(?P<fiscal_year_token>[0-9]{4}|[0-9]{2})(?![0-9]))?'
        r'(?:-(?P<committee_code>AP[0-9]{2})(?=-|$))?(?:-(?P<descriptor>.*))?',
        'legislative-payload', 'Appropriations routing slots, including blanks and literal unknown scope markers.', fallback=1),
    FilenameRule('house-amendment-file',
        r'(?P<subject_token>.+)-(?P<amendment_marker>HAmdt)(?P<amendment_token>[0-9]*)(?P<suffix>(?:[-_].*)?)',
        'legislative-payload', 'Subject followed by a House-amendment marker and optional number; no sponsor slot required.', fallback=1),
    FilenameRule('unverified-sponsor-amendment',
        r'(?!.*-AP-)-?(?P<subject_token>.+)-(?P<sponsor_identifier_token>[A-Z][A-Za-z0-9]{6})-(?P<amendment_marker>Amdt)-(?P<amendment_token>.+)',
        'legislative-payload', 'Preserve the sponsor-shaped slot without labeling a malformed token as a Bioguide identifier.', fallback=1),
    FilenameRule('substitute-file',
        r'(?P<subject_token>[A-Za-z]+[0-9]+)?(?P<amendment_marker>AnAmendmentintheNatureofaSubstitute|AmendmentintheNatureofaSubstitute|AINS|ANS)'
        r'(?P<target_marker>to)?' + rf'(?:(?P<measure_token>{MEASURE_CODES})?(?P<measure_number>[0-9]+))?'
        + r'(?P<descriptor>.*?)' + VERSION_SUFFIX,
        'legislative-payload', 'Explicit substitute marker, optional target reference, descriptive text and text version.', fallback=1),
    FilenameRule('numberless-versioned-file',
        rf'(?!.*-AP-)(?!-?(?:{MEASURE_CODES})[-_][A-Za-z])-?(?P<measure_token>{MEASURE_CODES})?'
        + r'(?P<number_placeholder>[_X-]+(?:[0-9]+|[A-Z][0-9]*)??)?' + VERSION_SUFFIX,
        'legislative-payload', 'An absent bill number or literal placeholder; neither becomes a numeric bill identifier.', fallback=1),
    FilenameRule('compound-local-file',
        r'-?(?P<local_identifier>[0-9]+(?:-[0-9X_]+)+|(?-i:[A-Z][A-Z0-9_]*?(?:-[A-Z0-9_]+?)+?)|[A-Za-z]{1,8}[0-9]+[A-Za-z]??)'
        + VERSION_SUFFIX,
        'legislative-payload', 'Compound or short local identifier, retained without resolving it as a bill or print number.', fallback=2),
    FilenameRule('committee-print-payload',
        r'-?(?P<print_token>CmtePrint|CommitteePrint|RCP)'
        r'(?:(?P<print_identifier>[0-9]+(?:(?!-JES(?:-|$))-(?:[0-9]+|[A-Z_]+?))?)|(?P<draft_label>Subtitle)(?P<local_identifier>[A-Z]))?'
        + '(?:' + VERSION_END + ')?'
        + r'(?:-(?P<explanation_token>JES)(?:-(?P<division_marker>DIVISION)-(?P<division_token>[A-Z]))?)?'
        r'(?P<suffix>(?:[-_].*)?)',
        'legislative-payload', 'Committee-print notation, local print ID, optional version and division markers.', fallback=1),
    FilenameRule('subtitle-file',
        r'(?P<draft_label>Subtitle)(?P<local_identifier>[A-Z])' + VERSION_SUFFIX,
        'legislative-payload', 'A subtitle letter and version, kept distinct from a bill number.', fallback=1),
    FilenameRule('text-of-measure',
        r'(?P<reference_marker>Textof)' + MEASURE_START + VERSION_SUFFIX,
        'legislative-payload', 'Explicit text-of wording before a bill reference and version.', fallback=1),
    FilenameRule('type-version-draft',
        rf'(?!.*-AP-)(?P<measure_token>{MEASURE_CODES})[-_]' + VERSION_SUFFIX,
        'legislative-payload', 'Bill type and separated version followed by an optional title; no bill number supplied.', fallback=1),
    FilenameRule('type-title-version-draft',
        rf'(?!.*-AP-)(?P<measure_token>{MEASURE_CODES})[-_](?P<descriptor>[A-Za-z].*?)[-_]' + VERSION_SUFFIX,
        'legislative-payload', 'Bill type, local title and separated terminal version.', fallback=1),
    FilenameRule('type-title-draft',
        rf'(?P<measure_token>{MEASURE_CODES})[-_](?P<descriptor>[A-Za-z].*)',
        'legislative-payload', 'Bill type and a title/description without an interpreted version or number.', fallback=2),
    FilenameRule('titled-introduced-draft',
        rf'(?!(?:{MEASURE_CODES})[-_])(?P<descriptor>[A-Za-z].*?)(?P<version_token>pih|pis|ih)(?P<suffix>(?:[-_].*)?)',
        'legislative-payload', 'Descriptive or local draft text ending in IH/PIH/PIS. Avoid arbitrary word endings such as Services/ES.', fallback=3),
)
COMPILED = tuple((r, re.compile(r.pattern, r.flags)) for r in RULES if not r.fallback)
FALLBACK_COMPILED = tuple((r, re.compile(r.pattern, r.flags)) for r in RULES if r.fallback)
PRIMARY_LEGISLATIVE_IDS = frozenset(r.id for r, _ in COMPILED if r.scope == 'legislative-payload')
EXTENSION = re.compile(r'\.(?P<extension>pdf|xml|html?|docx?|xlsx?|pptx?|txt|rtf|zip|csv|tsv|xsd)\Z', re.I)
TOKEN = re.compile(r'(?P<word>[^\W\d_]+)|(?P<number>[0-9]+)|(?P<separator>[\s\S])')
WORD = re.compile(r'[^\W\d_]+')
CAMEL_BOUNDARY = r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])'
CAMEL_SPLIT = re.compile(CAMEL_BOUNDARY)

# Date/time patterns take precedence; identifier/name assumptions are fallbacks.
# These rules run only after corpus matching leaves a name unmatched.
UNMATCHED_SUFFIX = r'(?P<ignored_suffix>pdf|-(?:testimony|tedtimony))?'
UNMATCHED_RULES = (
    FilenameRule('unmatched-leading-timestamp', r'(?P<date_token>(?:19|20)[0-9]{6})(?P<time_token>(?:[01][0-9]|2[0-3])[0-5][0-9][0-5][0-9])(?P<fraction_token>[0-9]{3})?(?![0-9])[ ._-]*(?P<name_token>.*?)' + UNMATCHED_SUFFIX,
                 'unmatched-date', 'Retain a calendar-plausible leading timestamp before applying generic-identifier assumptions.'),
    FilenameRule('unmatched-leading-date', r'(?P<date_token>(?:19|20)[0-9]{2}[ ._-][0-9]{1,2}[ ._-][0-9]{1,2}|[0-9]{1,2}[ ._-][0-9]{1,2}[ ._-](?:[0-9]{4}|[0-9]{2})|[0-9]{8}|[0-9]{5,6})(?![0-9])[ ._-]*(?P<name_token>.*?)' + UNMATCHED_SUFFIX,
                 'unmatched-date', 'Retain a calendar-plausible leading date; compact short dates keep their unspecified century and ambiguous order.'),
    FilenameRule('assumed-leading-identifier', r'(?P<generic_identifier>[0-9]+)[ ._-]*(?P<name_token>.*?)' + UNMATCHED_SUFFIX,
                 'unmatched-stem', 'Only after date/time recognition fails, leading digits are a generic identifier; remaining text is assumed to be a name.'),
    FilenameRule('assumed-name-with-identifier', r'(?P<name_token>(?![0-9]).+?)[ ._-]+(?P<generic_identifier>[0-9]+)' + UNMATCHED_SUFFIX,
                 'unmatched-stem', 'Assumed name followed by a separated numeric identifier, preserving both.'),
    FilenameRule('assumed-name', r'(?P<name_token>(?![0-9]).+?)' + UNMATCHED_SUFFIX,
                 'unmatched-stem', 'Remaining non-ZIP stem is assumed to be a name; remove only a hanging pdf or a terminal testimony/tedtimony suffix.'),
)
UNMATCHED_COMPILED = tuple((r, re.compile(r.pattern, r.flags)) for r in UNMATCHED_RULES)


def _short_date_plausible(raw: str) -> bool:
    """Check possible short-date orders without selecting a century or order."""
    parts = re.split(r'[ ._-]', raw)
    triples = []
    if len(parts) == 1 and raw.isascii() and raw.isdigit():
        if len(raw) == 6:
            a, b, c = int(raw[:2]), int(raw[2:4]), int(raw[4:])
            triples = [(c, a, b), (c, b, a), (a, b, c)]
        elif len(raw) == 5:
            year = int(raw[-2:])
            for split in (1, 2):
                a, b = int(raw[:split]), int(raw[split:-2])
                triples.extend([(year, a, b), (year, b, a)])
    elif len(parts) == 3 and all(p.isdigit() and len(p) <= 2 for p in parts):
        a, b, c = map(int, parts)
        triples = [(c, a, b), (c, b, a), (a, b, c)]
    for year, month, day in triples:
        try:
            # An existence check in a possible century, not an inferred year.
            date(2000 + year, month, day)
            return True
        except ValueError:
            pass
    return False


def date_readings(raw: str) -> tuple[tuple[str, ...], str]:
    if _short_date_plausible(raw):
        return (), 'Plausible short date; century and month/day/year order remain unspecified.'
    parts = re.split(r'[ ._-]', raw)
    triples = []
    if len(parts) == 1 and len(raw) == 8:
        triples = [(raw[:4], raw[4:6], raw[6:]), (raw[4:], raw[:2], raw[2:4]), (raw[4:], raw[2:4], raw[:2])]
    elif len(parts) == 3:
        if len(parts[0]) == 4:
            triples = [(parts[0], parts[1], parts[2])]
        elif len(parts[-1]) == 4:
            triples = [(parts[2], parts[0], parts[1]), (parts[2], parts[1], parts[0])]
        else:
            return (), 'Two-digit year; century and possibly month/day order are unspecified.'
    readings = set()
    for y, m, d in triples:
        try:
            if 1700 <= int(y) <= 2199:
                readings.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    return tuple(sorted(readings)), ('Date-shaped token only; filename does not establish its role.' if readings else 'No valid supported calendar reading; raw token retained.')


def _match(rule: FilenameRule, match: re.Match[str], offset: int) -> FilenameMatch:
    fields = []
    groups = match.groupdict()
    spans = {name: match.span(name) for name in groups}
    descriptor = groups.get('descriptor')
    version = groups.get('version_token')
    # A vocabulary hit is not evidence that a word ending is a version. Keep
    # reviewed joined introduction conventions; all other free-text joins need
    # a separator, digit, or visible uppercase-to-lowercase boundary.
    joined_introduction = bool(version and version.lower() in {'ih', 'pih', 'pis'}
                               and (version.islower() or version.isupper()))
    word_ending = bool(descriptor and version and spans['version_token'][0] == spans['descriptor'][1]
                       and descriptor[-1].isalpha() and not joined_introduction
                       and not (len(descriptor) >= 2 and descriptor[-2:].isupper() and version[0].islower()))
    # Prefer an explicit separated version over a possible ending of the word
    # immediately before it: ANSServices-ES means Services + ES, not Servic + es.
    if word_ending and groups.get('suffix'):
        separated = re.fullmatch(r'[-_]' + VERSION_SUFFIX, groups['suffix'], re.I)
        if separated:
            suffix_start = spans['suffix'][0]
            spans['descriptor'] = (spans['descriptor'][0], suffix_start + separated.start('version_token'))
            groups['descriptor'] = match.string[slice(*spans['descriptor'])]
            for name, raw in separated.groupdict().items():
                groups[name] = raw
                spans[name] = tuple(pos + suffix_start for pos in separated.span(name)) if raw is not None else (-1, -1)
            word_ending = False
    for name, raw in groups.items():
        if raw is None:
            continue
        start, end = spans[name]
        candidates, note = date_readings(raw) if name == 'date_token' else ((), None)
        if rule.scope == 'unmatched-stem' or rule.scope == 'unmatched-date' and name in {'name_token', 'ignored_suffix'}:
            note = 'User-specified assumption for otherwise unmatched filenames.'
        vocabulary = BILL_VERSIONS if name == 'version_token' else BILL_TYPES if name == 'measure_token' else {}
        code = raw.lower() if raw.lower() in vocabulary else None
        label = vocabulary.get(code)
        vocabulary_url = BILLS_HELP_URL if label else None
        if name == 'version_token' and raw.lower() in HOUSE_BILL_STAGES:
            code = raw.lower()
            label = HOUSE_BILL_STAGES[code]
            vocabulary_url = HOUSE_NAMING_URL
        if name == 'version_token' and rule.id == 'described-legislation':
            candidates = (code,) if code else ()
            note = 'Version-shaped suffix after descriptive text; its boundary is inferred from the filename.'
        if word_ending and name == 'version_token':
            candidates = tuple(sorted({raw.lower(), *(v for v in BILL_VERSIONS if raw.lower().endswith(v))}))
            code, label, vocabulary_url = None, None, None
            note = 'Possible ordinary word ending, not an established version boundary; the full text remains in descriptor.'
        if word_ending and name == 'descriptor':
            end = spans['version_token'][1]
            raw = match.string[start:end]
            note = 'Whole descriptive text retained across a possible version-shaped word ending.'
        if name == 'version_token' and not label and not candidates:
            note = 'No vocabulary mapping is implemented for this token; original spelling retained.'
        if name in {'version_prefix', 'version_number_token'}:
            note = 'Literal version modifier; its meaning is not defined by the GovInfo help-page vocabulary.'
        if name == 'numeric_suffix_token':
            note = 'Literal numeric filename suffix; its role is unspecified.'
        if name == 'filename_format_token':
            note = 'Format wording inside the filename; neither an extension nor a verified content format.'
        if name == 'local_code_token':
            note = 'Literal local code; no official version label or expansion inferred.'
        if name in {'member_marker', 'member_surname_token', 'title_token'}:
            note = 'Split using the longest supplied surname for this Congress; no member identity or sponsorship verified.'
        fields.append(FilenameField(name=name, raw=raw, start=start+offset, end=end+offset,
                                    candidates=candidates, note=note, code=code, label=label,
                                    vocabulary_url=vocabulary_url))
    return FilenameMatch(rule=rule.id, start=match.start()+offset, end=match.end()+offset, fields=tuple(fields))


@lru_cache(maxsize=256)
def member_title_pattern(surnames: tuple[str, ...]) -> str:
    """Build the Rep/name/title regex from supplied names, not a code allowlist.

    Publishers sometimes omit spaces, hyphens or apostrophes inside surnames.
    Require a capitalized title boundary or the end of the descriptor and prefer
    the longest source surname. Captures always retain the actual filename text.
    """
    patterns = []
    for name in sorted(set(surnames), key=lambda name: (-len(name), name)):
        parts = [p for p in re.split(r"[\s'’._-]+", name) if p]
        if parts:
            patterns.append(r"[\s'’._-]*".join(re.escape(p) for p in parts))
    return (r'(?P<member_marker>Rep)(?P<member_surname_token>'
            + ('|'.join(patterns) or r'(?!)')
            + r')(?P<title_token>(?-i:[A-Z]).*)?')


def parse_filename(filename: str, *, member_surnames: Mapping[str, tuple[str, ...]] | None = None) -> ParsedFilename:
    """Parse a basename; optional Congress-keyed surnames refine member/title spans.

    No file or network I/O occurs here. Without supplied names, the combined
    descriptor stays intact; CamelCase is insufficient to prove surname boundaries.
    """
    if '/' in filename or '\\' in filename or '\x00' in filename:
        raise ValueError('Expected a literal basename, not a path or URL.')
    stem_end = len(filename); matches = []
    # Preserve stacked extensions such as .docx.pdf as separate observations.
    while extension := EXTENSION.search(filename[:stem_end]):
        matches.append(FilenameMatch(rule='extension', start=extension.start(), end=extension.end(),
            fields=(FilenameField(name='extension', raw=extension['extension'], start=extension.start('extension'), end=extension.end('extension')),)))
        stem_end = extension.start()
    stem = filename[:stem_end]; payloads = []; congress = None
    for rule, regex in COMPILED:
        if rule.scope == 'stem' and (m := regex.fullmatch(stem)):
            matches.append(_match(rule, m, 0))
            congress = m.groupdict().get('congress', congress)
            if 'payload' in m.groupdict():
                scope = 'committee-payload' if rule.id == 'committee-file' else 'legislative-payload' if rule.id == 'legislative-file' else None
                if scope:
                    payloads.append((scope, m['payload'], m.start('payload')))
    for rule, regex in COMPILED:
        for scope, payload, offset in payloads:
            if rule.scope == scope and (m := regex.fullmatch(payload)):
                matched = _match(rule, m, offset)
                descriptor_field = next((f for f in matched.fields if f.name == 'descriptor'), None)
                uncertain_version = next((f for f in matched.fields if f.name == 'version_token' and f.candidates and f.code is None), None)
                descriptor = (descriptor_field.raw[:uncertain_version.start - descriptor_field.start] if uncertain_version
                              else descriptor_field.raw) if descriptor_field else None
                surnames = member_surnames.get(congress, ()) if member_surnames else ()
                if surnames and descriptor and descriptor.lower().startswith('rep'):
                    member = re.fullmatch(member_title_pattern(tuple(surnames)), descriptor, re.I)
                    if member:
                        fields = _match(rule, member, descriptor_field.start).fields
                        if uncertain_version:
                            fields = tuple(f.model_copy(update={'note': 'Title excludes a candidate version suffix; the full text remains in descriptor.'})
                                           if f.name == 'title_token' else f for f in fields)
                        matched = matched.model_copy(update={'fields': matched.fields + fields})
                suffix = m.groupdict().get('suffix')
                if surnames and suffix and suffix.lower().startswith(('-rep', '_rep')):
                    member = re.fullmatch(r'[-_]' + member_title_pattern(tuple(surnames))
                                          + r'(?P<version_token>pih|pis|ih)', suffix, re.I)
                    if member:
                        fields = _match(rule, member, offset + m.start('suffix')).fields
                        matched = matched.model_copy(update={'fields': matched.fields + fields})
                matches.append(matched)
        if rule.scope == 'search':
            matches.extend(_match(rule, m, 0) for m in regex.finditer(stem))
    for scope, payload, offset in payloads:
        if scope != 'legislative-payload' or any(m.rule in PRIMARY_LEGISLATIVE_IDS for m in matches):
            continue
        for tier in (1, 2, 3):
            recovered = [_match(rule, m, offset) for rule, regex in FALLBACK_COMPILED
                         if rule.fallback == tier and (m := regex.fullmatch(payload))]
            if recovered:
                matches.extend(recovered)
                break
    # Scoped searches refine retained text without changing the outer layout.
    legislative_ids = {r.id for r in RULES if r.scope == 'legislative-payload'}
    for parent in tuple(matches):
        for field in parent.fields:
            scope = ('published-suffix-search' if parent.rule in {'published-hearing', 'published-report', 'published-print'} and field.name == 'suffix'
                     else 'legislative-text-search' if parent.rule in legislative_ids and field.name in {'descriptor', 'suffix'} else None)
            if scope:
                for rule, regex in COMPILED:
                    if rule.scope == scope:
                        matches.extend(_match(rule, m, field.start) for m in regex.finditer(field.raw))
    pieces = tuple(FilenamePiece(kind=m.lastgroup, raw=m[0], start=m.start(), end=m.end()) for m in TOKEN.finditer(filename))
    return ParsedFilename(filename=filename, stem_end=stem_end, matches=tuple(matches), pieces=pieces)


def resolve_unmatched_filename(parsed: ParsedFilename) -> FilenameMatch | None:
    """Recognize leading dates/times, then apply identifier/name fallbacks.

    Call only after corpus matching finds no shared token or recurring layout.
    Preserve ambiguous dates rather than guessing their century or order.
    Known layouts and ZIP filenames are left alone.
    """
    stem_rules = {r.id for r in RULES if r.scope == 'stem'}
    if parsed.filename.lower().endswith('.zip') or any(m.rule in stem_rules for m in parsed.matches):
        return None
    stem = parsed.filename[:parsed.stem_end]
    for rule, regex in UNMATCHED_COMPILED:
        if match := regex.fullmatch(stem):
            if rule.scope == 'unmatched-date' and not (date_readings(match['date_token'])[0] or _short_date_plausible(match['date_token'])):
                continue
            return _match(rule, match, 0)
    return None


def shared_token_pattern(variants: tuple[str, ...], kind: str) -> str:
    """Exact corpus token variants, bounded to the same lexer as parse_filename.

    These regexes identify literal recurrence; a shared surname is not a document
    type and a repeated number is not automatically a date or meeting identifier.
    """
    if kind not in {'word', 'number', 'wordpart'}:
        raise ValueError(f'Unsupported token kind: {kind}')
    if not variants or any(not v or not (WORD if kind != 'number' else re.compile('[0-9]+')).fullmatch(v) for v in variants):
        raise ValueError('Variants must be nonempty whole tokens of the requested kind.')
    boundary = r'[^\W\d_]' if kind != 'number' else r'[0-9]'
    literals = '|'.join(re.escape(v) for v in sorted(set(variants), key=lambda s:(-len(s),s)))
    if kind == 'wordpart':
        return rf'(?:(?<!{boundary})|{CAMEL_BOUNDARY})(?P<token>{literals})(?:(?!{boundary})|{CAMEL_BOUNDARY})'
    return rf'(?<!{boundary})(?P<token>{literals})(?!{boundary})'


def filename_tokens(parsed: ParsedFilename) -> tuple[FilenamePiece, ...]:
    """Tokens for recurrence analysis, excluding all recognized extensions.

    Whole words remain available alongside CamelCase parts. No stemming or
    synonym merging: Statement, Statements and Testimony stay distinct.
    """
    tokens = []
    for piece in parsed.pieces:
        if piece.start >= parsed.stem_end or piece.kind == 'separator':
            continue
        tokens.append(piece)
        if piece.kind == 'word':
            start = piece.start
            for part in CAMEL_SPLIT.split(piece.raw):
                tokens.append(FilenamePiece(kind='wordpart', raw=part, start=start, end=start+len(part)))
                start += len(part)
    return tuple(tokens)


def registry(rules: tuple[FilenameRule, ...] = RULES) -> list[dict]:
    return [dict(id=r.id, pattern=r.pattern, scope=r.scope, flags=['IGNORECASE'] if r.flags else [],
                 description=r.description, fallback=r.fallback) for r in rules]
