"""Read literal source basenames without requiring a renderable convention.

Observed syntax, vocabulary meanings and last-resort assumptions stay separate.
Every field points into the unchanged input; date roles require an explicit convention.
"""
from __future__ import annotations

from datetime import date
from collections.abc import Mapping, Sequence
from functools import lru_cache
import re

from .errors import NamingError
from .bill_codes import BILL_VERSIONS, BILLS_HELP_URL
from .metadata import NUMBER_BOUNDARY_NOTE, starts_with_ordinal_suffix

HOUSE_NAMING_URL = "https://www.govinfo.gov/content/pkg/GOVPUB-Y1_2-PURL-gpo156119/pdf/GOVPUB-Y1_2-PURL-gpo156119.pdf"

MAX_SOURCE_BYTES = 16_384
MAX_REMAINDER_REFINEMENTS = 128
MAX_REMAINDER_TEXT = 262_144
STEM_PRIORITIES = (0, 1, 2)
PAYLOAD_PRIORITIES = (0, 1, 2, 3)
DATE_RULES = frozenset({'date-separated', 'date-compact', 'date-compact-unpadded',
                        'short-date-compact', 'short-date-unpadded', 'timestamp-shaped', 'addendum-number-date'})
# IDs used for procedural dispatch are implementation identifiers, not labels.
SUPPLEMENTAL_RULES = frozenset({
    'named-month-year', 'written-fiscal-year', 'source-amendment-reference',
    'senr-context', 'congress-wording', 'executive-session-wording',
    'managers-amendment-wording', 'notice-agenda-wording', 'summary-component-wording',
    'amendment-form-wording', 'managers-package-wording', 'edition-wording',
    'committee-mark-wording', 'ordered-reported-wording', 'legislative-text-wording',
    'action-by-wording', 'committee-resolution-wording', 'meeting-results-prefix',
    'meeting-results-suffix', 'executive-business-wording', 'bill-companion-abbreviation',
    'committee-print-wording', 'act-year-reference', 'bracketed-terminal-number',
    'budget-views-wording', 'oversight-plan-wording', 'joined-fiscal-year',
    'possible-month-day-prefix',
})
# The extractor dereferences these even when a filename has no matching layout.
REQUIRED_RULES = {
    'date-separated', 'measure-reference', 'support-reference',
    'document-qualifier', 'document-label-number', 'amendment-local-version',
}
# Only captures that procedural handlers require belong here; regex grammar
# remains in guide.json. Other rules need no Python entry.
RULE_INPUTS = {
    **{rid: ('search', set()) for rid in DATE_RULES},
    'date-separated': ('search', {'date_token'}),
    'measure-reference': ('search', {'measure_token', 'measure_number'}),
    'support-reference': ('document-wording-search', {'relation_wording'}),
    'document-qualifier': ('document-wording-search', {'qualifier_wording'}),
    'document-label-number': ('document-wording-search', {'local_number_token'}),
    'amendment-local-version': ('amendment-text-search', {'revision_marker', 'revision_number'}),
    'amendment-reference': ('search', {'amendment_token'}),
    'exhibit-reference': ('search', {'item_token'}),
    'document-suffix': ('search', {'document_identifier'}),
    'slide-reference': ('search', {'item_token'}),
    'partial-date': ('search', {'partial_date_token', 'partial_year_token', 'partial_month_token'}),
    'possible-month-day-prefix': ('document-wording-search', {'possible_month_day_token'}),
    'malformed-numeric-date': ('search', {'date_token'}),
    'gsa-project-reference': ('search', {'reference_identifier_token'}),
    'printed-citation': ('search', {'citation_marker'}),
    'named-month-year': ('document-wording-search', {'month_token', 'year_token'}),
    'congress-wording': ('document-wording-search', {'referenced_congress'}),
    'bill-companion-abbreviation': ('document-wording-search', {'document_abbreviation'}),
    'source-amendment-reference': ('document-wording-search', {'amendment_token'}),
    'meeting-results-prefix': ('document-wording-search', {'result_wording'}),
    'meeting-results-suffix': ('document-wording-search', {'result_wording'}),
    'budget-views-wording': ('document-wording-search', {'label'}),
    'oversight-plan-wording': ('document-wording-search', {'label'}),
    'revision-token': ('search', {'revision_marker', 'revision_number'}),
    'revised-token': ('search', {'revision_marker', 'revision_number'}),
    'assumed-name': ('unmatched-stem', {'ignored_suffix'}),
    **{name: ('stem', {'package_family', 'publication_code', 'publication_number'})
       for name in ('published-hearing', 'published-report', 'published-print')},
}
EXTENSION = re.compile(r'\.(?P<extension>pdf|xml|html?|docx?|xlsx?|pptx?|txt|rtf|zip|csv|tsv|xsd|jpe?g|png|mp[34]|m3u8|aspx|cfm)\Z', re.I | re.ASCII)
TOKEN = re.compile(r'(?P<word>[^\W\d_]+)|(?P<number>[0-9]+)|(?P<separator>[\s\S])')
QUERY = re.compile(r'[?&](?:[^?&=\s]+=[^&\s]*)(?:&[^?&=\s]+=[^&\s]*)*\Z')
FREE_FIELDS = {'payload', 'descriptor', 'suffix', 'subject_token', 'target_subject', 'title_token', 'name_token', 'filer_token', 'local_identifier', 'comparison_source', 'comparison_target'}
MALFORMED_DATE_NOTE = 'Date-shaped text with unsupported numeric component length; source digits are not repaired and no event date is established.'
MONTHS = {name: number for number, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}
# Source headers and filename counterparts are retained in the SENR review.
# These labels apply only inside that filename family, not as committee IDs.
SENR_SUBCOMMITTEES = {
    'np': 'National Parks', 'plfm': 'Public Lands, Forests, and Mining',
    'wp': 'Water and Power', 'w&p': 'Water and Power',
    'enr': 'Energy', 'energy': 'Energy',
}
PUBLICATION_LABELS = {
    'hprt': 'House committee print', 'sprt': 'Senate committee print',
    'jprt': 'Joint committee print', 'wprt': 'House Ways and Means committee print',
    'hrpt': 'House report', 'srpt': 'Senate report', 'erpt': 'Senate executive report',
    'hhrg': 'House hearing', 'shrg': 'Senate hearing', 'jhrg': 'Joint hearing',
}
PUBLICATION_NUMBER_NOTES = {
    'chrg': 'GovInfo jacket ID; not the hearing citation number or a meeting identifier. Source digits and leading zeros retained.',
    'cprt': 'GovInfo jacket ID when available, otherwise a print number; the filename alone does not distinguish them. Source digits retained.',
    'crpt': 'Congressional report number; conference status is not established by this filename. Source digits retained.',
}


@lru_cache(maxsize=256)
def member_title_pattern(surnames: tuple[str, ...], *, include_title: bool = True) -> str:
    """Use supplied spellings, allowing omitted surname punctuation only."""
    alternatives = []
    for surname in sorted(set(surnames), key=lambda value: (-len(value), value)):
        parts = [p for p in re.split(r"[\s'’._-]+", surname) if p]
        if parts:
            alternatives.append(r"[\s'’._-]*".join(re.escape(p) for p in parts))
    return (r'(?P<member_marker>Rep)(?P<member_surname_token>'
            + ('|'.join(alternatives) or r'(?!)')
            + r')' + (r'(?P<title_token>(?-i:[A-Z]).*)?' if include_title else ''))


def date_candidates(raw: str) -> tuple[list[str], bool, str]:
    """Calendar-valid readings; short years retain their unspecified century."""
    parts = re.split(r'[ ._-]', raw)
    triples = []
    short = []
    if len(parts) == 1 and raw.isascii() and raw.isdigit():
        if len(raw) == 8:
            triples = [(raw[:4], raw[4:6], raw[6:]), (raw[4:], raw[:2], raw[2:4]), (raw[4:], raw[2:4], raw[:2])]
        elif len(raw) == 7:
            # One unpadded month/day with a four-digit year. Preserve every
            # valid supported reading rather than selecting a date order.
            triples = [(raw[:4], raw[4:5], raw[5:]), (raw[:4], raw[4:6], raw[6:])]
            for split in (1, 2):
                a, b = raw[:split], raw[split:3]
                triples.extend([(raw[3:], a, b), (raw[3:], b, a)])
        elif len(raw) == 6:
            a, b, c = int(raw[:2]), int(raw[2:4]), int(raw[4:])
            short = [(c, a, b), (c, b, a), (a, b, c)]
        elif len(raw) == 5:
            for split in (1, 2):
                a, b, c = int(raw[:split]), int(raw[split:-2]), int(raw[-2:])
                short.extend([(c, a, b), (c, b, a)])
    elif len(parts) == 3 and all(p.isascii() and p.isdigit() for p in parts):
        if len(parts[0]) == 4:
            triples = [(parts[0], parts[1], parts[2])]
        elif len(parts[2]) == 4:
            triples = [(parts[2], parts[0], parts[1]), (parts[2], parts[1], parts[0])]
        elif all(len(p) <= 2 for p in parts):
            a, b, c = map(int, parts)
            short = [(c, a, b), (c, b, a), (a, b, c)]
    readings = set()
    for y, m, d in triples:
        try:
            if 1700 <= int(y) <= 2199:
                readings.add(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    for y, m, d in short:
        try:
            date(2000 + y, m, d)  # Existence in a possible century, not a chosen year.
            return [], True, 'Plausible short date; century and month/day/year order remain unspecified.'
        except ValueError:
            pass
    return sorted(readings), bool(readings), ('Calendar-valid date candidate; role is unknown.' if readings
                                            else 'No valid supported calendar reading; raw token retained.')


def bind_extraction_rules(guide: dict) -> dict[str, tuple[dict, re.Pattern]]:
    """Validate and compile the catalog at the same boundary that dispatches it."""
    bound = {}
    for rule in guide['extraction_rules']:
        rid, scope = rule['id'], rule['scope']
        if rid in bound:
            raise NamingError('invalid-catalog', f'Duplicate extraction rule: {rid}')
        try:
            regex = re.compile(rule['pattern'], re.I | re.ASCII)
        except re.error as exc:
            raise NamingError('invalid-catalog', f'Bad extraction pattern {rid}: {exc}') from exc
        fields = set(regex.groupindex)
        if 'label' in rule and 'label' not in fields:
            raise NamingError('invalid-catalog', f'Extraction rule {rid} supplies a label reading without a label capture')
        if not fields:
            raise NamingError('invalid-catalog', f'Extraction pattern {rid} has no named fields')
        if rid in DATE_RULES and not fields & {'date_token', 'short_date_token'}:
            raise NamingError('invalid-catalog', f'Extraction rule {rid} requires a date_token or short_date_token capture')
        priorities = (STEM_PRIORITIES if scope == 'stem' else PAYLOAD_PRIORITIES
                      if scope in {'committee-payload', 'legislative-payload'} else (0,))
        if rule['priority'] not in priorities:
            raise NamingError('invalid-catalog', f'Unsupported priority {rule["priority"]} for {scope} rule {rid}')
        if (scope == 'document-wording-search' and rid not in SUPPLEMENTAL_RULES | REQUIRED_RULES
                or scope == 'transport-search' and rid != 'extension-protocol-suffix'):
            raise NamingError('invalid-catalog', f'No {scope} handler for extraction rule {rid}')
        expected_scope, required = RULE_INPUTS.get(rid, (scope, set()))
        required = set(required)
        if scope == 'unmatched-date':
            required.add('date_token')
        if scope == 'published-suffix-search':
            required.update({'publication_marker', 'publication_identifier'})
        if 'revision_marker' in fields:
            required.add('revision_number')
        if fields & {'start_day_token', 'end_day_token'}:
            required.update({'month_token', 'year_token', 'start_day_token', 'end_day_token'})
        if scope != expected_scope or not required <= fields:
            raise NamingError('invalid-catalog', f'Extraction rule {rid} requires scope {expected_scope} and captures {sorted(required)}')
        bound[rid] = rule, regex
    missing = REQUIRED_RULES - bound.keys()
    if missing:
        raise NamingError('invalid-catalog', f'Missing required extraction rules: {sorted(missing)}')
    return bound


class Extractor:
    def __init__(self, guide: dict):
        self.guide = guide
        self.by_id = bind_extraction_rules(guide)
        self.rules = list(self.by_id.values())
        self.stem_ids = {r['id'] for r, _ in self.rules if r['scope'] == 'stem'}
        self.legislative_ids = {r['id'] for r, _ in self.rules if r['scope'] == 'legislative-payload'}
        versions = '|'.join(sorted([*guide['codes']['version'], 'pih', 'pis'], key=len, reverse=True))
        self.separated_version = re.compile(r'[-_](?P<version_token>' + versions + r')'
            r'(?P<version_number_token>[0-9]+)?(?:\((?P<annotation>[^()]*)\))?(?P<suffix>(?:[-_].*)?)\Z', re.I | re.ASCII)
        self.joined_measures = re.compile(r'(?P<measure_token>HCONRES|SCONRES|HJRES|SJRES|HRES|SRES|HR|S|H)(?P<measure_number>[0-9]+)', re.I | re.ASCII)

    def _field(self, name: str, raw: str, start: int, end: int, *, note=None) -> dict:
        return {'name': name, 'raw': raw, 'start': start, 'end': end,
                'candidates': [], 'note': note, 'code': None, 'label': None, 'context': None, 'vocabulary_url': None}

    def _meaning(self, field: dict, context: str, token: str | None = None) -> None:
        token = (token if token is not None else field['raw']).lower()
        entry = self.guide['codes'].get(context, {}).get(token)
        if entry:
            field.update(code=token, label=entry['label'], context=context,
                         vocabulary_url=f"{HOUSE_NAMING_URL}#page={entry['sources'][0]['page']}")

    def _match(self, rule: dict, hit: re.Match, offset: int) -> dict:
        groups = hit.groupdict()
        spans = {key: hit.span(key) for key in groups}
        # Subtitle letters are structured slots with their own version boundary;
        # only compound local identifiers need the free-text word-ending check.
        descriptive_field = 'local_identifier' if rule['id'] == 'compound-local-file' else 'descriptor'
        descriptor, version = groups.get(descriptive_field), groups.get('version_token')
        joined_introduction = version and version.lower() in {'ih', 'pih', 'pis'} and (version.islower() or version.isupper())
        word_ending = bool(descriptor and version and spans['version_token'][0] == spans[descriptive_field][1]
                           and descriptor[-1].isalpha() and not joined_introduction
                           and not (len(descriptor) >= 2 and descriptor[-2:].isupper() and version[0].islower()))
        if word_ending and groups.get('suffix'):
            separated = self.separated_version.fullmatch(groups['suffix'])
            if separated:
                suffix_start = spans['suffix'][0]
                spans[descriptive_field] = (spans[descriptive_field][0], suffix_start + separated.start('version_token'))
                groups[descriptive_field] = hit.string[slice(*spans[descriptive_field])]
                for key, value in separated.groupdict().items():
                    groups[key] = value
                    spans[key] = tuple(p + suffix_start for p in separated.span(key)) if value is not None else (-1, -1)
                word_ending = False
        fields = []
        for name, raw in groups.items():
            if raw is None:
                continue
            start, end = spans[name]
            if rule['id'] == 'legislative-unlisted-version' and name == 'version_token':
                # Position alone does not make SUS or ANS a text version. The
                # existing whole-slot marker rules supply their proper roles.
                refined = next((self._match(r, token, start + offset)['fields']
                                for r, rx in self.rules
                                if r['id'] in {'house-consideration-marker', 'legislative-amendment-marker'}
                                and (token := rx.fullmatch(raw))), None)
                if refined is not None:
                    fields.extend(refined)
                    continue
            field = self._field(name, raw, start + offset, end + offset)
            if name == 'label' and 'label' in rule:
                field.update(label=rule['label'], note=rule['description'])
            if rule['id'] in {
                'short-legislative-reference', 'short-measure-format-reference', 'short-legislative-companion', 'rcp-short-measure',
                'local-rcp-reference', 'local-formatted-file', 'local-code-prefix', 'bill-comparison',
                'treaty-citation', 'gao-reference', 'jct-reference', 'jct-compact-reference',
                'local-x-reference', 'drafting-identifier', 'question-component', 'outline-prefix',
                'partial-date', 'possible-month-day-prefix', 'abbreviated-component',
            }:
                field['note'] = rule['description']
            if name == 'report_subject_token':
                field['note'] = 'Literal numeric subject in a report-prefixed filename; may identify a measure, report or local item. No official number, embedded Congress or document identity is established; digits are not split or repaired.'
            if rule['id'] == 'bill-companion-abbreviation':
                field['note'] = 'Literal companion-file abbreviation; source context is required for expansion. No official bill version or document contents are established.'
            if rule['id'] == 'local-introduction-component' and name == 'local_identifier':
                field['note'] = 'Printed local identifier; no expansion, document type or committee identity is established.'
            if rule['id'] == 'act-year-reference':
                field['note'] = 'Printed Act-of-year reference; no enactment, document identity, Congress or event date is established.'
            if rule['id'] == 'substitute-target' and name in {'offering_marker', 'offerer_token'}:
                field['note'] = 'Printed offered-by wording; no person identity, authorship, actual offering or withdrawal status is established.'
            ordinal_tail = (groups.get('descriptor', '') if rule['id'] == 'described-legislation'
                            else hit.string[end:] if rule['id'] == 'measure-reference' else '')
            if name == 'measure_number' and starts_with_ordinal_suffix(ordinal_tail):
                field.update(name='ambiguous_number_token', note=NUMBER_BOUNDARY_NOTE)
            if name == 'ignored_suffix' and rule['id'] == 'legislative-text':
                field['note'] = 'Printed hanging pdf text; not an actual extension or verified file format.'
            if rule['id'] in {'published-hearing', 'published-report', 'published-print'} and name in {'publication_code', 'publication_number'}:
                family = groups['package_family'].lower()
                field['vocabulary_url'] = f'https://www.govinfo.gov/help/{family}'
                if name == 'publication_code':
                    field.update(code=raw.lower(), label=PUBLICATION_LABELS[raw.lower()])
                else:
                    field['note'] = PUBLICATION_NUMBER_NOTES[family]
            if rule['id'] == 'congress-wording':
                number = int(groups['referenced_congress'])
                ordinal = 'th' if 10 <= number % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
                field['note'] = 'Printed Congress reference; no primary Congress, calendar years or Congress for other references inferred.'
                if groups.get('congress_ordinal') and groups['congress_ordinal'].lower() != ordinal:
                    field['note'] += ' Ordinal does not agree with the printed number; source spelling retained.'
                if number == 0:
                    field['note'] += ' Congress number is not positive; source value retained.'
                elif groups['referenced_congress'].startswith('0'):
                    field['note'] += ' Leading zeros retained; no canonical number assigned.'
            if rule['id'] == 'executive-session-wording':
                field['note'] = 'Printed session wording; no event identity, occurrence, attendance or access status is verified.'
                field['label'] = 'Executive session' if name == 'meeting_wording' else raw.title()
            if rule['id'] == 'executive-business-wording':
                field['note'] = 'Printed meeting heading; no event identity, occurrence, attendance or access status is verified.'
                if name == 'meeting_abbreviation':
                    field['note'] += ' Abbreviation retained without expansion; source context is required for its meaning.'
                else:
                    field['label'] = 'Executive business meeting' if name == 'meeting_wording' else raw.title()
            if rule['id'] == 'senr-context':
                field['note'] = 'Printed SENR-family context; source spelling retained, with no verified event, access status or committee identifier.'
                field['label'] = {
                    'committee_token': 'Senate Committee on Energy and Natural Resources',
                    'committee_marker': 'Committee', 'subcommittee_marker': 'Subcommittee',
                    'nomination_wording': 'Nominations', 'field_marker': 'Field',
                }.get(name)
                if name == 'subcommittee_token':
                    field['label'] = SENR_SUBCOMMITTEES[raw.lower()]
                if name == 'meeting_wording':
                    wording = re.sub(r'[ _-]+', ' ', raw.lower())
                    field['label'] = {'hr': 'Hearing', 'hrg': 'Hearing', 'hearing': 'Hearing',
                                      'bus mtg': 'Business meeting', 'business meeting': 'Business meeting',
                                      'roundtable': 'Roundtable'}[wording]
            if name in {'date_token', 'short_date_token'}:
                field['candidates'], _, field['note'] = date_candidates(raw)
                if rule['id'] == 'malformed-numeric-date':
                    field['note'] = MALFORMED_DATE_NOTE
            if name == 'fiscal_year_token' and rule['id'] in {'written-fiscal-year', 'joined-fiscal-year'}:
                field['note'] = 'Printed fiscal year; no calendar date is established.'
                if len(raw) == 2:
                    field['note'] += ' The century remains unspecified.'
            if name == 'version_token':
                self._meaning(field, 'consideration' if raw.lower() == 'pih' else 'version')
                if not field['code'] and raw.lower() in BILL_VERSIONS:
                    field.update(code=raw.lower(), label=BILL_VERSIONS[raw.lower()], vocabulary_url=BILLS_HELP_URL)
                if not field['code']:
                    field['note'] = 'Literal version-shaped token without a vocabulary mapping.'
                if rule['id'] == 'described-legislation':
                    field['candidates'] = [field['code']] if field['code'] else []
                    field['note'] = 'Version-shaped suffix after descriptive text; its boundary is inferred from the filename.'
                if word_ending:
                    field.update(code=None, label=None, context=None, vocabulary_url=None,
                                 candidates=sorted({raw.lower(), *(v for v in self.guide['codes']['version'] if raw.lower().endswith(v))}),
                                 note='Possible word ending; the version boundary is not established.')
            if word_ending and name == descriptive_field:
                end = spans['version_token'][1]
                field.update(raw=hit.string[start:end], end=end + offset,
                             note='Full descriptive text retained across a possible version-shaped word ending.')
            if name in {'measure_token', 'covered_measure_token'}:
                self._meaning(field, 'measure', re.sub(r'[^A-Za-z]', '', raw))
            if name == 'degree_token':
                ordinal = re.split(r'[ _-]+', raw.lower())[0]
                degree = {'1st': '1', 'first': '1', '2nd': '2', 'second': '2', '3rd': '3', 'third': '3'}[ordinal]
                field.update(code=degree, label={'1': 'First degree', '2': 'Second degree', '3': 'Third degree'}[degree],
                             note='Literal degree wording; no amendment role, sequence number or interchamber meaning is established.')
            if rule['id'] == 'degree-target' and name == 'target_subject':
                field['note'] = 'Literal target wording between degree clauses; no person identity or verified amendment relationship is established.'
            if rule['id'] == 'measure-placeholder' and name == 'number_placeholder':
                field['note'] = 'Printed underscore placeholder; no measure number or Congress inferred.'
            if rule['id'] == 'printed-citation':
                citation = re.sub(r'[^A-Za-z]', '', groups['citation_marker']).lower()
                if name == 'citation_marker':
                    kind = citation if citation in {'shrg', 'sprt'} else citation[0] + 'rpt'
                    field.update(code=kind, label={
                        'shrg': 'Senate hearing citation', 'hrpt': 'House report citation',
                        'srpt': 'Senate report citation', 'sprt': 'Senate print citation',
                    }[kind])
                field['note'] = {
                    'citation_marker': 'Printed reference type; not verification of this file or its contents.',
                    'citation_congress': 'Congress of the printed citation; not inferred for other references.',
                    'citation_number': 'Printed hearing or report number; not a GovInfo hearing jacket number.',
                    'number_placeholder': 'Printed placeholder; no citation number inferred.',
                }[name]
                if citation == 'sprt':
                    field['vocabulary_url'] = 'https://www.govinfo.gov/help/cprt'
                    if name == 'citation_number':
                        field['note'] = 'Printed Senate print number; not a GovInfo jacket ID.'
            context = None
            if name == 'collection_token':
                context = 'collection'
            elif name == 'package_family' and rule['id'] in {
                'legislative-file', 'published-hearing', 'published-report', 'published-print',
                'committee-print-file', 'activity-report', 'unnumbered-conference-report',
            }:
                # The same prefix also occurs in notice/vote routes, where it
                # does not establish a publication collection or document type.
                context = 'collection'
            elif name == 'document_token' and (rule['scope'] in {'committee-payload', 'committee-print-search'} or rule['id'] == 'activity-report'):
                context = {'activities': 'report', 'sd': 'meeting-attachment'}.get(raw.lower(), 'document')
            elif name == 'local_code_token':
                field['note'] = 'Literal local code; no official version label or expansion inferred.'
                if rule['id'] not in {'local-code-prefix', 'updated-local-code'} and (raw.lower() != 'orh' or rule['id'] == 'house-consideration-marker'):
                    context = 'consideration'
            elif name == 'notice_marker':
                context = 'notice'
            elif name == 'meeting_token' or name == 'package_family' and rule['id'] == 'committee-file':
                context = 'meeting'
            elif name == 'scope_token':
                context = 'appropriation'
            elif name == 'enbloc_marker':
                context = 'amendment'
            elif name == 'amendment_marker' and raw.lower() == 'amdt' and rule['id'] in {
                'sponsored-amendment', 'unverified-sponsor-amendment', 'malformed-sponsor-slot',
            }:
                context = 'amendment'
            elif name == 'appropriation_kind':
                context = 'supplemental' if raw.lower() == 'suppl' else 'continuing-resolution'
            elif name == 'document_marker' and rule['id'] in {'witness-support-marker', 'meeting-support-marker'}:
                context = 'witness-attachment' if rule['id'] == 'witness-support-marker' else 'meeting-attachment'
            if context:
                self._meaning(field, context, 'orh-rule-legis-num' if name == 'local_code_token' and raw.lower() == 'orh' else raw)
                if name == 'local_code_token' and field['code']:
                    field['note'] = 'House consideration notation; not a GovInfo text version.'
            if name == 'amendment_marker' and raw.lower() in {'hamdt', 'samdt'}:
                suffix = groups.get('amendment_token') or ''
                if suffix in {'', '2', '3'}:
                    self._meaning(field, 'amendment', raw + suffix)
                    chamber = 'House' if raw.lower() == 'hamdt' else 'Senate'
                    degree = {'': 'first', '2': 'second', '3': 'third'}[suffix]
                    field['label'] = f'{chamber} amendment ({degree} degree)'
                    field['note'] = 'Interchamber amendment degree, not an amendment sequence number.'
            if name == 'amendment_token' and raw in {'2', '3'} and groups.get('amendment_marker', '').lower() in {'hamdt', 'samdt'}:
                fields.append(self._field('amendment_degree', raw, start + offset, end + offset,
                                          note='Interchamber amendment degree, not a sequence number.'))
            if name in {'version_prefix', 'version_number_token', 'numeric_suffix_token', 'filename_format_token'}:
                field['note'] = 'Printed local modifier; its role and contents are not inferred.'
            if name == 'filename_format_token':
                field['note'] = 'Format wording inside the filename; neither an extension nor a verified content format.'
            if name == 'local_number_token':
                field['note'] = 'Literal local numeric component; not an established bill or amendment sequence number.'
                if rule['id'] == 'bracketed-terminal-number':
                    field['note'] = 'Literal trailing bracketed number; no copy, revision, publication or document sequence is established.'
            if rule['id'] == 'amendment-local-version' and name in {'revision_marker', 'revision_number'}:
                field['note'] = 'Printed local V-number component; no GovInfo text version or revision history is established.'
            if name == 'qualifier_wording':
                field['note'] = 'Printed qualifier wording; access, edition and file contents are not verified.'
            if name == 'relation_wording':
                field['note'] = 'Printed support/opposition wording; file type and actual position are not established.'
            if rule['id'] == 'action-by-wording' and name in {'relation_wording', 'target_subject'}:
                field['note'] = 'Printed by relation and following text; no actor identity or actual reporting/amendment relationship is established.'
            if name == 'vote_wording':
                field['note'] = 'Printed voting-method wording; no vote occurrence, count, passage or result is verified.'
            if name == 'result_wording':
                field['note'] = rule['description']
            if rule['id'] in {'gsa-numbered-reference', 'gsa-project-reference'}:
                field['note'] = rule['description']
            if name == 'descriptor' and rule['id'] == 'attached-substitute':
                field['note'] = 'Boundary follows printed capitalization; the prefix is not an established person name.'
            if name == 'draft_label' and rule['id'] == 'draft-wording':
                field['note'] = rule['description']
            if name == 'filer_token':
                field['note'] = 'Literal filed-by wording; no author identity or sponsorship is established.'
                # Mixed-case Rep/Reps has a visible boundary. All-uppercase or
                # lowercase text stays whole rather than losing a surname S.
                member = re.fullmatch(r'(?P<member_marker>Reps|Rep)(?=[A-Z])(?P<name_token>[A-Za-z\'-]+)', raw)
                if member:
                    for part, text in member.groupdict().items():
                        fields.append(self._field(part, text, start + offset + member.start(part),
                            start + offset + member.end(part), note=field['note']))
            if name == 'revision_marker' and raw.lower() == 'u' and hit.end() == len(hit.string) and (groups['revision_number'] or '').strip('0'):
                self._meaning(field, 'revision')
                field.update(code='u', label='Document update', vocabulary_url=f'{HOUSE_NAMING_URL}#page=20', note='U1 denotes the first update since posting.')
            if name == 'part_marker' and rule['id'] == 'report-part':
                field.update(code='p', label='Report part', vocabulary_url=f'{HOUSE_NAMING_URL}#page=18', note='Part of the report, not its report number.')
            if name in {'report_component', 'division_marker'}:
                label = {'frontmatter':'Report front matter', 'signaturesheets':'Report signature sheets',
                         'som':'Joint statement of managers', 'division':'Report division', 'divison':'Report division'}.get(raw.lower())
                if label:
                    self._meaning(field, 'report')
                    field.update(code=raw.lower(), label=label, vocabulary_url=f'{HOUSE_NAMING_URL}#page=12')
            if name == 'part_number' and rule['id'] == 'report-part':
                field['note'] = 'Part of the report; not the report number.'
            if name in {'covered_measure_number', 'appropriation_sequence', 'enbloc_number', 'meeting_sequence', 'quarter_number'}:
                field['note'] = {
                    'covered_measure_number': 'Number of the measure covered by the Rules resolution; not the resolution number.',
                    'appropriation_sequence': 'Sequence within the stated fiscal year; not a bill number.',
                    'enbloc_number': 'Printed en bloc group number; not the individual amendment identifier.',
                    'meeting_sequence': 'Distinguishes meetings of this committee on the same date.',
                    'quarter_number': 'Quarter of the committee activity report.',
                }[name]
            if name == 'date_token' and rule['id'] == 'weekly-notice':
                field['note'] = 'Week start date; the House guide specifies Monday, including holidays.'
                if not field['candidates']:
                    field['note'] += ' No valid supported calendar reading; source value retained.'
                elif date.fromisoformat(field['candidates'][0]).weekday() != 0:
                    field['note'] += ' Printed date is not Monday; source value retained.'
            if rule['scope'] == 'unmatched-stem' or rule['scope'] == 'unmatched-date' and name in {'name_token', 'ignored_suffix'}:
                field['note'] = 'User-requested fallback assumption; not a verified person or identifier.'
            fields.append(field)
        if rule['id'] == 'partial-date':
            for field in fields:
                if field['name'] == 'partial_date_token':
                    month = groups['partial_month_token']
                    field['candidates'] = ([groups['partial_year_token']] if month.lower() == 'xx'
                                           else [groups['partial_year_token'] + '-' + month] if 1 <= int(month) <= 12 else [])
                    if not field['candidates']:
                        field['note'] += ' Invalid month; source components retained without repair.'
        if rule['id'] == 'possible-month-day-prefix':
            raw = groups['possible_month_day_token']
            fields.append(self._field('generic_identifier', raw, hit.start() + offset, hit.end() + offset,
                                     note='An identifier remains possible; the four digits also resemble a month/day.'))
        if rule['id'] == 'named-month-year':
            month = MONTHS[groups['month_token'][:3].lower()]
            year = int(groups['year_token'])
            field = self._field('month_year_token', hit[0], hit.start() + offset, hit.end() + offset,
                                note='Month/year precision; no day or event-date role is established.')
            if year:
                field['candidates'] = [f'{year:04d}-{month:02d}']
            else:
                field['note'] += ' Invalid calendar year; printed components retained.'
            fields.append(field)
        if groups.get('month_token') and groups.get('day_token'):
            month = MONTHS[groups['month_token'][:3].lower()]
            year = groups.get('year_token')
            values = []
            note = 'Calendar-plausible named date; year or century remains unspecified.'
            try:
                if year and len(year) not in {2, 4}:
                    raise ValueError('Unsupported printed year width')
                # A leap year permits February 29 when the year is unspecified;
                # this is a plausibility check, not an inferred year.
                y = int(year) if year and len(year) == 4 else 2000 + int(year or 0)
                candidate = date(y, month, int(groups['day_token']))
                if year and len(year) == 4:
                    values = [candidate.isoformat()]
                    note = 'Calendar-valid date candidate; role is unknown.'
            except ValueError:
                note = ('Unsupported printed year width; components retained without repairing the year.'
                        if year and len(year) not in {2, 4} else
                        'Invalid named calendar date; printed components retained.')
            field = self._field('date_token', hit[0], hit.start() + offset, hit.end() + offset, note=note)
            field['candidates'] = values
            fields.append(field)
        if groups.get('start_day_token') and groups.get('end_day_token'):
            values = []
            note = 'Calendar-valid same-month date range; the interval does not establish event dates.'
            try:
                month = MONTHS[groups['month_token'][:3].lower()]
                first = date(int(groups['year_token']), month, int(groups['start_day_token']))
                last = date(int(groups['year_token']), month, int(groups['end_day_token']))
                if last < first:
                    raise ValueError('Range ends before it starts')
                values = [first.isoformat() + '/' + last.isoformat()]
            except ValueError:
                note = 'Invalid named calendar range; printed components retained without repair.'
            field = self._field('date_range_token', hit[0], hit.start() + offset, hit.end() + offset, note=note)
            field['candidates'] = values
            fields.append(field)
        return {'rule': rule['id'], 'scope': rule['scope'], 'start': hit.start() + offset,
                'end': hit.end() + offset, 'fields': fields, 'description': rule['description']}

    @staticmethod
    def _overlaps(start: int, end: int, protected: list[tuple[int, int]]) -> bool:
        return any(start < b and end > a for a, b in protected)

    def _members(self, filename: str, observations: list[dict], member_surnames: Mapping) -> list[dict]:
        congress = next((f['raw'] for m in observations if m['rule'] == 'legislative-file'
                         for f in m['fields'] if f['name'] == 'congress'), None)
        surnames = member_surnames.get(congress, ())
        if (not isinstance(surnames, Sequence) or isinstance(surnames, (str, bytes))
                or any(not isinstance(value, str) or not value.strip() for value in surnames)):
            raise NamingError('invalid-member-reference', 'Member surnames must be a sequence of nonempty strings for each Congress')
        if not surnames:
            return []
        pattern = member_title_pattern(tuple(surnames))
        rule = {'id': 'member-title', 'scope': 'legislative-text-search',
                'description': f'Split using caller-supplied surnames for Congress {congress}; no person identity or sponsorship is established.'}
        results = []
        for parent in observations:
            if parent['rule'] not in self.legislative_ids:
                continue
            uncertain = next((f for f in parent['fields'] if f['name'] == 'version_token'
                              and f['candidates'] and not f['code']), None)
            for field in parent['fields']:
                text = field['raw']
                uncertain_title = False
                if field['name'] == 'descriptor' and text.lower().startswith('rep'):
                    if uncertain and field['start'] <= uncertain['start'] < field['end']:
                        text = text[:uncertain['start'] - field['start']]
                        uncertain_title = True
                    hit = re.fullmatch(pattern, text, re.I)
                elif field['name'] == 'suffix' and text.lower().startswith(('-rep', '_rep')):
                    hit = re.fullmatch(r'[-_]' + pattern + r'(?P<version_token>pih|pis|ih)', text, re.I)
                else:
                    continue
                if hit:
                    match = self._match(rule, hit, field['start'])
                    for part in match['fields']:
                        if part['name'] in {'member_marker', 'member_surname_token', 'title_token'}:
                            part['note'] = rule['description']
                            if part['name'] == 'title_token' and uncertain_title:
                                part['note'] += ' Candidate title excludes a possible version ending; the full descriptor remains available.'
                    results.append(match)
        # A printed Rep+surname may also occur at the end or within a title.
        # Read only roster-backed surnames and visible word boundaries, without
        # inventing first names, sponsorship or a title after the reference.
        reference = re.compile(member_title_pattern(tuple(surnames), include_title=False), re.I | re.ASCII)
        reference_rule = dict(rule, id='member-reference')
        occupied = {(f['start'], f['end']) for m in results for f in m['fields'] if f['name'] == 'member_surname_token'}
        for parent in observations:
            if parent['rule'] not in self.legislative_ids:
                continue
            for field in parent['fields']:
                if field['name'] not in {'descriptor', 'suffix', 'subject_token', 'amendment_token'}:
                    continue
                for hit in reference.finditer(field['raw']):
                    # Check after choosing the longest supplied surname. A
                    # failed Miller-Meeks boundary must not backtrack to Miller.
                    if hit.end() < len(field['raw']) and field['raw'][hit.end()].isalpha() and not field['raw'][hit.end()].isupper():
                        continue
                    a, b = hit.span('member_surname_token')
                    span = field['start'] + a, field['start'] + b
                    if span not in occupied:
                        match = self._match(reference_rule, hit, field['start'])
                        for part in match['fields']:
                            part['note'] = rule['description']
                        results.append(match)
                        occupied.add(span)
        return results

    def _support_references(self, filename: str, start: int, stem_end: int, observations: list[dict],
                            measure_spans: list[tuple[int, int]]) -> list[dict]:
        """Refine descriptive sides using existing source IDs, dates and suffixes."""
        stem = filename[start:stem_end]
        reference_rule, reference_regex = self.by_id['support-reference']
        hits = list(reference_regex.finditer(stem))
        if not hits:
            return []
        source_fields = [f for m in observations for f in m['fields']]
        hard_spans = [(f['start'], f['end']) for f in source_fields if f['name'] not in FREE_FIELDS | {'label'}]
        hard_spans.extend((f['start'], f['end']) for m in observations if m['rule'] == 'person-document'
                          for f in m['fields'] if f['name'] == 'subject_token')
        references = [h for h in hits
                      if not self._overlaps(start + h.start(), start + h.end(), hard_spans)]
        result = []
        if references:
            edge_names = {'opaque_identifier','opaque_uuid','opaque_hex','date_token','short_date_token',
                          'time_token','fraction_token','generic_identifier','local_number_token','ignored_suffix'}
            edges = [(f['start'], f['end']) for f in source_fields if f['name'] in edge_names
                     and not self._overlaps(f['start'], f['end'], measure_spans)]

            def trim_reference_side(a, b):
                while a < b:
                    while a < b and filename[a] in ' _-':
                        a += 1
                    while b > a and filename[b - 1] in ' _-':
                        b -= 1
                    next_a = max((y for x, y in edges if x == a and y <= b), default=a)
                    next_b = min((x for x, y in edges if y == b and x >= next_a), default=b)
                    if (next_a, next_b) == (a, b):
                        break
                    a, b = next_a, next_b
                return a, b

            for index, hit in enumerate(references):
                a, b = start + hit.start(), start + hit.end()
                containers = [(f['start'], f['end']) for f in source_fields
                              if f['name'] in FREE_FIELDS and f['start'] <= a and b <= f['end']
                              and not any(x < f['start'] < y or x < f['end'] < y for x, y in measure_spans)]
                left, right = min(containers, key=lambda span: span[1] - span[0], default=(start, stem_end))
                if index:
                    left = max(left, start + references[index - 1].end())
                if index + 1 < len(references):
                    right = min(right, start + references[index + 1].start())
                observed = self._match(reference_rule, hit, start)
                for name, x, y, location in [('subject_token', left, a, 'before'), ('target_subject', b, right, 'after')]:
                    x, y = trim_reference_side(x, y)
                    if x < y:
                        observed['fields'].append(self._field(name, filename[x:y], x, y,
                            note=f'Literal text {location} the printed wording; person identity, authorship and actual position are not established.'))
                        observed['start'] = min(observed['start'], x)
                        observed['end'] = max(observed['end'], y)
                result.append(observed)
        return result

    def extract(self, filename: str, *, member_surnames: Mapping[str, Sequence[str]] | None = None) -> dict:
        if not isinstance(filename, str):
            raise NamingError('invalid-filename', 'Filename must be a string basename')
        try:
            if len(filename.encode('utf-8')) > MAX_SOURCE_BYTES:
                raise NamingError('input-too-large', 'Source basename exceeds 16384 UTF-8 bytes')
        except UnicodeError as exc:
            raise NamingError('invalid-unicode', 'Source basename is not UTF-8 encodable') from exc
        if '/' in filename or '\\' in filename or '\x00' in filename:
            raise NamingError('invalid-filename', 'Expected a literal basename, not a path or URL')
        if member_surnames is not None and not isinstance(member_surnames, Mapping):
            raise NamingError('invalid-member-reference', 'Member surnames must be a Congress-keyed mapping')
        observations = []
        ignored = []
        start = len(filename) - len(filename.lstrip())
        end = len(filename.rstrip())
        if query := QUERY.search(filename, start, end):
            observations.append({'rule': 'query-shaped-suffix', 'scope': 'transport', 'start': query.start(), 'end': query.end(),
                                 'description': 'Query-shaped text retained separately; not proof of a URL or file format.',
                                 'fields': [self._field('query_text', query[0], query.start(), query.end())]})
            end = query.start()
        stem_end = end
        while hit := EXTENSION.search(filename, start, stem_end):
            observations.append({'rule': 'extension', 'scope': 'extension', 'start': hit.start(), 'end': hit.end(),
                                 'description': 'Literal extension; does not verify the file contents.',
                                 'fields': [self._field('extension', hit['extension'], hit.start('extension'), hit.end('extension'))]})
            stem_end = hit.start()
        stem = filename[start:stem_end]
        payloads = []
        for priority in STEM_PRIORITIES:
            found = False
            for rule, regex in self.rules:
                if rule['scope'] == 'stem' and rule['priority'] == priority and (hit := regex.fullmatch(stem)):
                    found = True
                    observations.append(self._match(rule, hit, start))
                    if 'payload' in hit.groupdict():
                        scope = ('committee-payload' if rule['id'] in {'committee-file', 'committee-vote-file'}
                                 else 'legislative-payload' if rule['id'] == 'legislative-file'
                                 else 'descriptive-payload' if rule['id'] == 'opaque-prefixed-source' else None)
                        if scope:
                            payloads.append((scope, hit['payload'], start + hit.start('payload')))
            if found:
                break
        for scope, payload, offset in payloads:
            if scope == 'descriptive-payload':
                observations.extend(self._match(rule, hit, offset) for rule, regex in self.rules
                                    if rule['scope'] == 'stem' and rule['priority'] == 2
                                    and rule['id'] != 'opaque-prefixed-source' and (hit := regex.fullmatch(payload)))
                continue
            for priority in PAYLOAD_PRIORITIES:
                found = [self._match(rule, hit, offset) for rule, regex in self.rules
                         if rule['scope'] == scope and rule['priority'] == priority and (hit := regex.fullmatch(payload))]
                if found:
                    observations.extend(found)
                    break
            else:
                # An incomplete BILLS payload can still state a substitute's
                # target. Reuse the whole-slot rule without inventing a version
                # or treating these visible parts as a complete payload layout.
                if scope == 'legislative-payload':
                    pos = int(payload.startswith('-'))
                    observations.extend(self._match(rule, hit, offset + pos)
                                        for rule, regex in self.rules
                                        if rule['id'] == 'substitute-target'
                                        and (hit := regex.fullmatch(payload[pos:])))
        if not any(m['rule'] in self.stem_ids for m in observations):
            for rule, regex in self.rules:
                if rule['scope'] == 'collection-prefix' and (hit := regex.fullmatch(stem)):
                    observations.append(self._match(rule, hit, start))

        # Specific payload slots must be visible even when a broader layout
        # matched first. Reserve their source spans before generic date/ID scans.
        for scope, payload, offset in payloads:
            if scope != 'legislative-payload':
                continue
            for rule, regex in self.rules:
                if rule['scope'] == 'legislative-payload-search':
                    hits = regex.finditer(payload)
                elif rule['id'] == 'unverified-sponsor-amendment':
                    hit = regex.fullmatch(payload)
                    hits = (hit,) if hit else ()
                else:
                    continue
                for hit in hits:
                    # The normal priority pass may already have selected it.
                    if not any(m['rule'] == rule['id'] and m['start'] == offset + hit.start()
                               and m['end'] == offset + hit.end() for m in observations):
                        observations.append(self._match(rule, hit, offset))

        # Refine owned legislative slots before generic date/member scans.
        # Explicit substitute targets and local component numbers keep their roles.
        for parent in tuple(observations):
            if parent['rule'] not in self.legislative_ids:
                continue
            for field in parent['fields']:
                if field['name'] not in {'descriptor', 'suffix'}:
                    continue
                for rule, regex in self.rules:
                    if rule['id'] not in {'local-introduction-component', 'substitute-target'}:
                        continue
                    raw = field['raw'].lstrip('-_') if rule['id'] == 'substitute-target' else field['raw']
                    offset = field['start'] + len(field['raw']) - len(raw)
                    if hit := regex.fullmatch(raw):
                        if not any(m['rule'] == rule['id'] and m['start'] == offset + hit.start()
                                   and m['end'] == offset + hit.end() for m in observations):
                            observations.append(self._match(rule, hit, offset))

        # Keep useful label/subject slots, but never establish a date by cutting
        # a longer numeric component. Retain the old split as an alternative.
        for match in observations:
            if match['rule'] not in {'labeled-date', 'labeled-subject-date'}:
                continue
            for field in match['fields']:
                if field['name'] != 'date_token' or field['end'] >= stem_end or not filename[field['end']].isdigit():
                    continue
                ignored.append({'rule': match['rule'], 'raw': filename[match['start']:match['end']],
                                'start': match['start'], 'end': match['end'],
                                'reason': 'Date field splits a numeric component; complete source text retained.',
                                'fields': [dict(f) for f in match['fields']]})
                old_end = field['end']
                complete_end = old_end
                while complete_end < match['end'] and filename[complete_end].isdigit():
                    complete_end += 1
                field.update(raw=filename[field['start']:complete_end], end=complete_end,
                             candidates=[], note=MALFORMED_DATE_NOTE)
                for suffix in match['fields']:
                    if suffix['name'] == 'suffix' and suffix['start'] == old_end:
                        suffix.update(raw=filename[complete_end:suffix['end']], start=complete_end)

        # Publication component numbers have explicit roles. Reserve them before
        # free-text date scans, just like the package's main publication number.
        for parent in tuple(observations):
            reported_bill = (parent['rule'] == 'legislative-text' and any(
                f['name'] == 'version_token' and f['code'] in {'rh', 'rs'} for f in parent['fields']))
            if parent['rule'] not in {'published-hearing', 'published-report', 'published-print'} and not reported_bill:
                continue
            for field in parent['fields']:
                if field['name'] == 'suffix':
                    for rule, regex in self.rules:
                        if rule['scope'] == 'published-suffix-search':
                            for hit in regex.finditer(field['raw']):
                                if reported_bill and not (hit['publication_marker'].lower() == 'p'
                                        and hit['publication_identifier'] and hit['publication_identifier'].isdigit()):
                                    continue
                                component = self._match(rule, hit, field['start'])
                                if reported_bill:
                                    for part in component['fields']:
                                        part['note'] = 'Literal p-number component in a reported-bill filename; no official report, part or page identity is established.'
                                if parent['rule'] == 'published-hearing':
                                    for part in component['fields']:
                                        if part['name'] == 'publication_marker' and part['raw'].lower() == 'err':
                                            part.update(note='GovInfo uses err for both hearing addenda and errata; the filename alone does not distinguish them.',
                                                        vocabulary_url='https://www.govinfo.gov/help/chrg')
                                observations.append(component)

        # Loose report subjects may be report numbers, measure numbers or local
        # IDs. Preserve them whole; only printed part wording supplies a role.
        for parent in tuple(observations):
            if parent['rule'] != 'report-file':
                continue
            for field in parent['fields']:
                if field['name'] != 'payload':
                    continue
                for rule, regex in self.rules:
                    if rule['id'] != 'numeric-report-subject' or not (hit := regex.match(field['raw'])):
                        continue
                    observations.append(self._match(rule, hit, field['start']))
                    tail = field['raw'][hit.end():]
                    for part_rule, part_regex in self.rules:
                        if part_rule['id'] in {'part-token', 'report-part'}:
                            observations.extend(self._match(part_rule, part, field['start'] + hit.end())
                                                for part in part_regex.finditer(tail))

        # A parsed local-ID slot supplies the boundary before a joined version.
        # Reserve its reference digits before any generic date scan.
        for parent in tuple(observations):
            if parent['rule'] == 'compound-local-file':
                for field in parent['fields']:
                    if field['name'] == 'local_identifier':
                        for rule, regex in self.rules:
                            if rule['id'] in {'gsa-numbered-reference', 'gsa-project-reference'} and (hit := regex.fullmatch(field['raw'])):
                                observations.append(self._match(rule, hit, field['start']))

        # Only free text slots can contain additional references or dates. Known
        # person IDs and dates must not produce accidental bills or revisions.
        # RCP uses short measure spellings that would be too broad to scan in
        # arbitrary prose. Read them only after a printed RCP prefix.
        if 'rcp-short-measure' in self.by_id and 'local-rcp-reference' in self.by_id:
            owned_spans = [(f['start'], f['end']) for m in observations for f in m['fields']
                           if f['name'] not in FREE_FIELDS
                           or m['rule'] == 'person-document' and f['name'] == 'subject_token']
            rcp_rule, rcp_regex = self.by_id['rcp-short-measure']
            for prefix in self.by_id['local-rcp-reference'][1].finditer(stem):
                if self._overlaps(start + prefix.start(), start + prefix.end(), owned_spans):
                    continue
                pos = prefix.end()
                while hit := rcp_regex.match(stem, pos):
                    if self._overlaps(start + hit.start(), start + hit.end(), owned_spans):
                        break
                    observations.append(self._match(rcp_rule, hit, start))
                    # Further references must be consecutive components,
                    # not unrelated short tokens later in prose.
                    pos = hit.end()
                    while pos < len(stem) and stem[pos] in '_-':
                        pos += 1
                    if pos == hit.end():
                        break
        protected = []
        for match in observations:
            for field in match['fields']:
                if field['name'] not in FREE_FIELDS or match['rule'] == 'person-document' and field['name'] == 'subject_token':
                    protected.append((field['start'], field['end']))

        searches = [(r, rx) for r, rx in self.rules if r['scope'] == 'search']
        reference_numbers = {'measure-reference': 'measure_number', 'amendment-reference': 'amendment_token',
                             'exhibit-reference': 'item_token', 'document-suffix': 'document_identifier',
                             'slide-reference': 'item_token'}
        separated_date = self.by_id['date-separated'][1]
        measure_regex = self.by_id['measure-reference'][1]
        measure_spans = [(start + m.start(), start + m.end()) for m in measure_regex.finditer(stem)]
        # Complete identifier/date forms reserve their spans before other scans.
        order = {'timestamp-shaped': 0, 'uuid': 1, 'hex-identifier': 2, 'bioguide-token': 3,
                 'gsa-project-reference': 2,
                 **{rid: 2 for rid in ('treaty-citation', 'gao-reference', 'jct-reference',
                     'jct-compact-reference', 'local-x-reference',
                     'short-legislative-reference', 'short-measure-format-reference', 'short-legislative-companion',
                     'local-rcp-reference', 'partial-date')},
                 'drafting-identifier': 4,
                 'question-component': 4, 'abbreviated-component': 4, 'slide-reference': 4,
                 'chair-mark-description': 4, 'document-list-wording': 4,
                 'revision-token': 4, 'revised-token': 4, 'part-token': 4, 'print-reference': 4,
                 'named-month-date': 4, 'day-named-month-date': 4,
                 'named-month-range': 4, 'addendum-number-date': 4, 'printed-citation': 4,
                 'measure-reference': 4, 'amendment-reference': 4,
                 'exhibit-reference': 4, 'document-suffix': 4,
                 'gsa-numbered-reference': 4,
                 'malformed-numeric-date': 4,
                 'degree-wording': 5, 'degree-local-number': 5, 'degree-target': 5,
                 'measure-placeholder': 5, 'questionnaire-wording': 5, 'biographical-wording': 5,
                 'remarks-wording': 5}
        date_rules = DATE_RULES
        revision_dates = [rx for r, rx in searches if r['id'] in date_rules and r['id'] != 'addendum-number-date']

        def candidates(rule, regex):
            if rule['id'] not in date_rules:
                for hit in regex.finditer(stem):
                    if (rule['id'] in {'document-wording', 'biographical-wording'} and 'label' in hit.groupdict()
                            and hit.start() and stem[hit.start() - 1].isalpha()):
                        preceding_word = re.search(r'[A-Za-z]+\Z', stem[:hit.start()])
                        if preceding_word and not preceding_word[0][0].isupper():
                            continue
                    # A complete malformed shape still needs a possible month
                    # in one of its first two components. Its year stays raw.
                    if rule['id'] == 'malformed-numeric-date' and min(
                            map(int, re.split(r'[._-]', hit['date_token'])[:2])) > 12:
                        continue
                    yield hit
                return
            hits = []
            pos = 0
            while hit := regex.search(stem, pos):
                hits.append(hit)
                pos = hit.start() + 1
            # An earlier numeric prefix can resemble a date only by crossing
            # the separator before the real date. Prefer consistent date
            # separators; retain all other candidates as observations/receipts.
            def priority(hit):
                raw = hit.groupdict().get('date_token', hit.groupdict().get('short_date_token'))
                separators = set(re.findall(r'[ ._-]', raw))
                return (len(separators) > 1, hit.start())
            yield from sorted(hits, key=priority)

        def search_candidates():
            named_ids = {'named-month-date', 'day-named-month-date', 'named-month-range'}
            named_done = False
            for rule, regex in sorted(searches, key=lambda item: order.get(item[0]['id'], 5)):
                if rule['id'] in named_ids:
                    if named_done:
                        continue
                    named_done = True
                    # A complete 5APR22 must reserve its span before APR22.
                    # Invalid complete shapes retain their own calendar warning.
                    named = [(r, h) for r, rx in searches if r['id'] in named_ids
                             for h in rx.finditer(stem)]
                    yield from sorted(named, key=lambda item: (item[1].start(), -item[1].end()))
                else:
                    yield from ((rule, hit) for hit in candidates(rule, regex))

        for rule, hit in search_candidates():
            a, b = start + hit.start(), start + hit.end()
            if rule['id'] in {'gsa-numbered-reference', 'gsa-project-reference'} and any(
                    m['rule'] == rule['id'] and m['start'] == a and m['end'] == b for m in observations):
                continue
            if rule['id'] == 'biographical-wording' and any(
                    f['name'] in {'label', 'document_token'} and f['start'] == a and f['end'] == b
                    for m in observations for f in m['fields']):
                continue
            if rule['id'] == 'degree-local-number' and not any(
                    m['rule'] == 'degree-wording' and m['end'] == a for m in observations):
                continue
            if rule['id'] == 'degree-target' and not any(
                    m['rule'] == 'degree-wording' and m['end'] <= a
                    and re.fullmatch(r'[ _-]+(?:[0-9]+[ _-]+)?', filename[m['end']:a])
                    for m in observations):
                continue
            if rule['id'] == 'dated-statement-suffix':
                if not any(m['rule'] in {'named-month-date','day-named-month-date'}
                           and m['start'] == start and m['end'] <= a for m in observations):
                    continue
                # A delimited abbreviation may already expose the same label.
                if any(m['rule'] == 'statement-abbreviation' and m['start'] <= a
                       and m['end'] == b for m in observations):
                    continue
            reason = None
            if number := reference_numbers.get(rule['id']):
                # Attachment 3-27-19 contains a complete separated date, not
                # an established attachment 3. A compact numeric reference
                # remains whole even when its digits also resemble a date.
                date_hit = separated_date.match(stem, hit.start(number))
                if date_hit and date_hit.end() > hit.end(number) and date_candidates(date_hit['date_token'])[1]:
                    reason = 'Reference would consume only a prefix of a complete separated date.'
            if self._overlaps(a, b, protected):
                reason = 'Overlaps a structured or already assigned token.'
            if rule['id'] in {'malformed-numeric-date', 'measure-placeholder'} and self._overlaps(a, b, measure_spans):
                reason = 'Overlaps an explicit measure reference.'
            if rule['id'] in date_rules:
                raw = hit.groupdict().get('date_token', hit.groupdict().get('short_date_token'))
                if not date_candidates(raw)[1]:
                    reason = 'No valid supported calendar reading.'
            if reason:
                ignored.append({'rule': rule['id'], 'raw': hit[0], 'start': a, 'end': b, 'reason': reason,
                                'fields': self._match(rule, hit, start)['fields']})
                continue
            observed = self._match(rule, hit, start)
            if rule['id'] in {'revision-token','revised-token'} and hit.groupdict().get('revision_number') and len(hit['revision_marker']) > 1:
                possible_date = next((d for rx in revision_dates
                                      if (d := rx.match(stem, hit.start('revision_number')))
                                      and date_candidates(d.groupdict().get('date_token', d.groupdict().get('short_date_token')))[1]), None)
                if possible_date:
                    ignored.append({'rule':rule['id'], 'raw':hit[0], 'start':a, 'end':b,
                                    'reason':'Date follows revision wording; no sequence number inferred.',
                                    'fields':[dict(f) for f in observed['fields']]})
                    observed['fields'] = [f for f in observed['fields'] if f['name'] != 'revision_number']
                    observed['end'] = start + hit.end('revision_marker')
                    observed['fields'][0]['note'] = 'Revision wording followed by date-shaped text; no revision number inferred.'
                    b = observed['end']
            observations.append(observed)
            if rule['id'] == 'gsa-project-reference':
                # The middle ID is atomic. Keep explicit FY wording in the
                # final segment available to the ordinary fiscal-year reader.
                protected.append((start + hit.start('reference_identifier_token'),
                                  start + hit.end('reference_identifier_token')))
            elif rule['id'] in order or rule['id'] in date_rules:
                protected.append((a, b))

        # Qualifiers belong to their filename wording, not to a verified access
        # or publication state. Group only neighboring words; names may precede
        # a terminal qualifier group, but unrelated title words cannot follow it.
        label_patterns = [rx for r, rx in self.rules
                          if r['id'] in {'questionnaire-wording', 'biographical-wording', 'remarks-wording'}]
        document_labels = [{'start': f['start'], 'end': f['end'], 'rule': m['rule']}
                           for m in observations for f in m['fields']
                           if f['name'] == 'label' and any(rx.fullmatch(f['raw']) for rx in label_patterns)]
        qualifier_rule, qualifier_regex = self.by_id['document-qualifier']
        qualifier_hits = [self._match(qualifier_rule, h, start) for h in qualifier_regex.finditer(stem)
                          if not self._overlaps(start + h.start(), start + h.end(), protected)]
        terminal_spans = [(f['start'], f['end']) for m in observations for f in m['fields']
                          if f['name'] in {'opaque_uuid','opaque_hex','date_token','short_date_token','time_token','fraction_token','filename_format_token'}]
        terminal_end = stem_end
        if hanging := re.search(r'pdf(?:-[0-9]+)?\Z', stem, re.I):
            terminal_end = start + hanging.start()
        groups = []
        for match in sorted([*document_labels, *qualifier_hits], key=lambda m: (m['start'], m['end'])):
            if groups and re.fullmatch(r'[ ._()\[\]-]*', filename[groups[-1][-1]['end']:match['start']]):
                groups[-1].append(match)
            else:
                groups.append([match])
        for group in groups:
            terminal = (all(filename[i] in ' ._()-[]0123456789'
                                or any(a <= i < b for a, b in terminal_spans)
                                for i in range(group[-1]['end'], terminal_end)))
            for match in group:
                # Remarks may be followed by a topic, such as Public Health.
                # Only preceding or terminal qualifiers are unambiguous here.
                adjacent = any(m['rule'] != 'document-qualifier'
                               and (m['rule'] != 'remarks-wording' or match['end'] <= m['start'])
                               for m in group)
                public = any(f['raw'].lower() == 'public' for f in match.get('fields', ()))
                prefix = (all(c in ' ._()-[]' for c in filename[start:match['start']])
                          and not any(f['name'] == 'label' for m in observations for f in m['fields']))
                allowed = adjacent or terminal or prefix
                if public:
                    allowed = adjacent or terminal and bool(document_labels)
                if match['rule'] == 'document-qualifier' and allowed:
                    observations.append(match)
                    protected.append((match['start'], match['end']))
        number_rule, number_regex = self.by_id['document-label-number']
        label_ends = {m['end'] for m in document_labels} | {
            m['end'] for m in observations if m['rule'] == 'document-qualifier'}
        for hit in number_regex.finditer(stem):
            a, b = start + hit.start(), start + hit.end()
            if a not in label_ends:
                continue
            observed = self._match(number_rule, hit, start)
            if self._overlaps(a, b, protected):
                ignored.append({'rule': number_rule['id'], 'raw': hit[0], 'start': a, 'end': b,
                                'reason': 'Overlaps a structured or already assigned token.', 'fields': observed['fields']})
            else:
                observations.append(observed)
                protected.append((a, b))

        for parent in tuple(observations):
            # A recognized container permits precise refinement of its slots,
            # unlike unrestricted searches through dates and person IDs.
            for field in parent['fields']:
                wanted = set()
                if field['name'] == 'measure_list':
                    # This slot is already recognized as joined references. Its
                    # literal SA prefix is not part of the first measure type.
                    pos = 2 if field['raw'].upper().startswith('SA') else 0
                    reference_rule = self.by_id['measure-reference'][0]
                    while hit := self.joined_measures.match(field['raw'], pos):
                        observations.append(self._match(reference_rule, hit, field['start']))
                        pos = hit.end()
                if parent['rule'] == 'person-document' and field['name'] == 'subject_token':
                    wanted.add('bioguide-token')
                if parent['rule'] in self.legislative_ids and field['name'] == 'subject_token':
                    wanted.update({'local-substitute-number','local-number-substitute','local-amendment-component','draft-wording'})
                if parent['rule'] in self.legislative_ids and field['name'] == 'annotation':
                    wanted.add('edition-wording')
                if parent['rule'] in {'sponsored-amendment', 'unverified-sponsor-amendment'} and field['name'] == 'amendment_token':
                    wanted.update({'revision-token','measure-reference','substitute-target','substitute-marker','compound-filing-target','draft-wording'})
                if wanted:
                    for rule, regex in self.rules:
                        if rule['id'] in wanted:
                            observations.extend(self._match(rule, hit, field['start']) for hit in regex.finditer(field['raw']))
            if parent['rule'] in {'dated-document','token-date-document','committee-print-payload'}:
                wanted = 'print-reference' if parent['rule'] == 'committee-print-payload' else 'document-suffix'
                for rule, regex in self.rules:
                    if rule['id'] == wanted:
                        observations.extend(self._match(rule, hit, parent['start'])
                                            for hit in regex.finditer(filename[parent['start']:parent['end']]))
            for field in parent['fields']:
                scopes = set()
                name = field['name']
                if parent['rule'] in self.legislative_ids and name in {'descriptor', 'suffix'}:
                    scopes.add('legislative-text-search')
                if parent['rule'] in self.legislative_ids and name == 'subject_token':
                    scopes.add('legislative-subject-search')
                if parent['rule'] in {'sponsored-amendment', 'unverified-sponsor-amendment'} and name == 'amendment_token':
                    scopes.add('amendment-text-search')
                if parent['rule'] == 'appropriations-file' and name == 'descriptor':
                    scopes.add('appropriation-text-search')
                if parent['rule'] in {'unnumbered-conference-report', 'report-file', 'published-report'} and name in {'payload', 'suffix'}:
                    scopes.add('report-text-search')
                if parent['rule'] == 'committee-print-file' and name == 'payload':
                    scopes.add('committee-print-search')
                if name == 'suffix':
                    if parent['rule'] == 'person-document' and any(f['name'] == 'document_token' and f['raw'].lower() == 'wstate' for f in parent['fields']):
                        scopes.add('witness-suffix-search')
                    elif parent['rule'] == 'meeting-notice':
                        scopes.add('meeting-suffix-search')
                for rule, regex in self.rules:
                    if rule['scope'] in scopes:
                        for hit in regex.finditer(field['raw']):
                            if rule['id'] == 'report-part' and any(
                                    m['rule'] == rule['id'] and m['start'] == field['start'] + hit.start()
                                    and m['end'] == field['start'] + hit.end() for m in observations):
                                continue
                            if rule['id'] not in {'numeric-report-subject', 'local-introduction-component'}:
                                observations.append(self._match(rule, hit, field['start']))

        # Reuse whole-slot rules for explicit filing targets and local IDs.
        # Full matches keep ordinals or descriptive tails out of bill numbers.
        for parent in tuple(observations):
            if parent['rule'] not in {'compound-filing-target','attached-substitute'}:
                continue
            for field in parent['fields']:
                wanted = ({'measure-reference','unnumbered-subject','placeholder-subject-title','committee-print-subject'}
                          if field['name'] == 'target_subject' else
                          {'local-substitute-number','local-number-substitute','local-amendment-component'}
                          if field['name'] == 'local_identifier' else set())
                for rule, regex in self.rules:
                    if rule['id'] in wanted:
                        if rule['id'] == 'local-amendment-component':
                            hits = regex.finditer(field['raw'])
                        else:
                            hit = regex.fullmatch(field['raw'])
                            hits = (hit,) if hit else ()
                        observations.extend(self._match(rule, hit, field['start']) for hit in hits)

        # Bare ANS_01 already has a whole-slot interpretation. Keep the new
        # component rule only when it exposes a field not already available.
        for match in tuple(observations):
            if match['rule'] == 'local-amendment-component' and all(
                any(field == other for m in observations if m is not match for other in m['fields'])
                for field in match['fields']
            ):
                observations.remove(match)
            if match['rule'] == 'measure-placeholder' and all(
                any({k: v for k, v in field.items() if k != 'note'} ==
                    {k: v for k, v in other.items() if k != 'note'}
                    for m in observations if m is not match for other in m['fields'])
                for field in match['fields']
            ):
                # Whole-slot rules already provide the same placeholder.
                observations.remove(match)

        # References discovered inside free text also take precedence over
        # generic numeric assumptions made by the final fallback.
        protected = list(set(protected) | {(f['start'], f['end'])
                         for m in observations for f in m['fields'] if f['name'] not in FREE_FIELDS})
        selected_dates = {(f['start'], f['end']) for m in observations for f in m['fields']
                          if f['name'] in {'date_token','short_date_token'}}
        local_numbers = {(f['start'], f['end']) for m in observations for f in m['fields']
                         if f['name'] == 'local_number_token'}

        def fallback_date_allowed(hit, offset):
            span = offset + hit.start('date_token'), offset + hit.end('date_token')
            return (date_candidates(hit['date_token'])[1]
                    and (span in selected_dates or not self._overlaps(*span, protected)))

        # A document label gives the remaining text a subject slot, but must
        # not hide dates or numeric prefixes previously exposed by fallback.
        def fallback(left, right):
            text = filename[left:right]
            for rule, regex in self.rules:
                if rule['scope'] not in {'unmatched-date','unmatched-stem'} or not (hit := regex.fullmatch(text)):
                    continue
                if rule['scope'] == 'unmatched-date' and not fallback_date_allowed(hit, left):
                    continue
                if 'generic_identifier' in hit.groupdict() and self._overlaps(
                        left + hit.start('generic_identifier'), left + hit.end('generic_identifier'), protected):
                    span = left + hit.start('generic_identifier'), left + hit.end('generic_identifier')
                    if span in local_numbers:
                        refined = self._match(rule, hit, left)
                        refined.update(rule='local-number-remainder',
                                       description='Fallback text around an assigned local number; the number retains its explicit role.')
                        refined['fields'] = [f for f in refined['fields'] if f['name'] != 'generic_identifier']
                        return refined
                    continue
                if any(m['rule'] in {'uuid','hex-identifier','bioguide-token'}
                       and m['start'] == left and m['end'] == right for m in observations):
                    return None
                return self._match(rule, hit, left)
            return None

        def selected_date_remainder(left, right, *, subject=False):
            selected = next((m for m in observations
                           if m['rule'] in {'named-month-date','day-named-month-date'}
                           and m['start'] == left and m['end'] < right), None)
            if selected is None:
                selected = next((m for m in observations if m['rule'] == 'malformed-numeric-date'
                                 and (m['start'] == left and m['end'] < right
                                      or m['end'] == right and m['start'] > left)), None)
            if selected is None:
                return None
            leading = selected['start'] == left
            a, b = (selected['end'], right) if leading else (left, selected['start'])
            if leading:
                while a < b and filename[a] in ' ._-':
                    a += 1
            else:
                while b > a and filename[b - 1] in ' ._-':
                    b -= 1
            if not (refined := fallback(a, b)):
                return None
            malformed = selected['rule'] == 'malformed-numeric-date'
            refined.update(rule=('subject-' if subject else 'unmatched-') + ('malformed' if malformed else 'named') + '-date-remainder',
                           scope='subject-refinement' if subject else 'unmatched-stem',
                           description=('Text outside a selected malformed date shape; its calendar value remains unknown.' if malformed else
                                        'Text remaining after a selected leading named date; the date does not establish an event or century.'))
            if subject:
                for part in refined['fields']:
                    if part['name'] == 'name_token':
                        part.update(name='subject_token', note=('Descriptive text outside a malformed date; no person identity is established.' if malformed else
                                                               'Descriptive text after a named date; no person identity is established.'))
            return refined

        for parent in tuple(observations):
            if parent['rule'] not in {'labeled-subject', 'subject-labeled', 'labeled-subject-date'}:
                continue
            for field in parent['fields']:
                if field['name'] != 'subject_token':
                    continue
                if refined := selected_date_remainder(field['start'], field['end'], subject=True):
                    observations.append(refined)
                    continue
                for rule, regex in self.rules:
                    if (rule['scope'] not in {'unmatched-date','unmatched-stem'}
                            or not (hit := regex.fullmatch(field['raw']))):
                        continue
                    # Reuse the existing hanging-suffix policy inside an explicit
                    # subject; a bare assumed-name match adds no new information.
                    suffix_only = rule['id'] == 'assumed-name'
                    if suffix_only and not hit['ignored_suffix']:
                        continue
                    if rule['scope'] == 'unmatched-date' and not fallback_date_allowed(hit, field['start']):
                        continue
                    if 'generic_identifier' in hit.groupdict() and self._overlaps(
                            field['start'] + hit.start('generic_identifier'),
                            field['start'] + hit.end('generic_identifier'), protected):
                        continue
                    refined = self._match(rule, hit, field['start'])
                    refined.update(rule='subject-' + rule['id'], scope='subject-refinement',
                                   description=('Hanging suffix inside an explicit document subject; the original subject remains available.'
                                                if suffix_only else
                                                'Date/number syntax inside an explicit document subject; no person identity is established.'))
                    for part in refined['fields']:
                        if part['name'] == 'name_token':
                            part.update(name='subject_token', note=('Descriptive text before a hanging suffix; no person identity is established.'
                                                                  if suffix_only else
                                                                  'Descriptive text remaining after a date or number; no person identity is established.'))
                    observations.append(refined)
                    break

        # These are the user's explicit final assumptions, after source layouts
        # and calendar-aware token recognition. ZIP stems are never person names.
        is_zip = any(f['name'] == 'extension' and f['raw'].lower() == 'zip' for m in observations for f in m['fields'])
        if stem and not is_zip and not any(m['rule'] in self.stem_ids or m['rule'] == 'collection-prefix' for m in observations):
            if refined := selected_date_remainder(start, stem_end) or fallback(start, stem_end):
                observations.append(refined)

        # Removing a prefix can expose a trailing date/ID or another prefix.
        # Keep the parent text and reuse the same fallback on shorter remainders.
        pending = [f for m in observations
                   if m['scope'] in {'unmatched-date','unmatched-stem','subject-refinement'}
                   for f in m['fields'] if f['name'] in {'name_token','subject_token'} and f['raw']]
        seen = set()
        pos = 0
        retained_text = sum(len(f['raw']) for m in observations for f in m['fields'])
        while pos < len(pending):
            field = pending[pos]
            pos += 1
            key = field['name'], field['start'], field['end']
            if key in seen:
                continue
            seen.add(key)
            refined = selected_date_remainder(field['start'], field['end'], subject=field['name'] == 'subject_token') or fallback(field['start'], field['end'])
            if not refined or (refined['rule'] != 'local-number-remainder'
                               and not any(f['name'] in {'date_token','generic_identifier'} for f in refined['fields'])):
                continue
            retained_text += sum(len(f['raw']) for f in refined['fields'])
            if pos > MAX_REMAINDER_REFINEMENTS or retained_text > MAX_REMAINDER_TEXT:
                raise NamingError('extraction-limit', 'Remainder refinement exceeds its work or retained-text limit.',
                                  [{'max_refinements': MAX_REMAINDER_REFINEMENTS,
                                    'max_retained_characters': MAX_REMAINDER_TEXT}])
            subject = field['name'] == 'subject_token'
            refined.update(rule='remainder-' + refined['rule'],
                           scope='subject-refinement' if subject else refined['scope'],
                           description='Additional date/number syntax in remaining text; the full parent text is retained.')
            for part in refined['fields']:
                if part['name'] == 'name_token':
                    if subject:
                        part.update(name='subject_token', note='Descriptive text remaining after a date or number; no person identity is established.')
                    if part['raw'] and (part['start'] > field['start'] or part['end'] < field['end']):
                        pending.append(part)
            observations.append(refined)
        observations.extend(self._support_references(filename, start, stem_end, observations, measure_spans))
        # Supplement descriptive text without rewriting earlier fallback readings.
        # Complete dates and concrete IDs already own their spans.
        supplemental_hits = [(r, h) for r, rx in self.rules
                             if r['id'] in SUPPLEMENTAL_RULES
                             for h in rx.finditer(stem)]
        if supplemental_hits:
            protected_fields = [f for m in observations for f in m['fields']
                                if f['name'] not in FREE_FIELDS | {'generic_identifier'}
                                or m['rule'] == 'person-document' and f['name'] == 'subject_token']
            protected = [(f['start'], f['end']) for f in protected_fields]
            for rule, hit in supplemental_hits:
                if rule['id'] in {'committee-print-wording', 'act-year-reference'}:
                    a = start + hit.start()
                    if a > start and filename[a - 1].isalpha() and not filename[a - 1].isascii():
                        continue
                if rule['id'] == 'act-year-reference' and starts_with_ordinal_suffix(stem[hit.end():]):
                    continue
                if rule['id'] == 'bill-companion-abbreviation':
                    a = start + hit.start('document_abbreviation')
                    if a > start and filename[a - 1].isalnum():
                        continue
                    if hit['document_abbreviation'].lower() == 'ma' and not any(
                        m['rule'] == 'measure-reference' and m['start'] == start and m['end'] < a
                        and any(f['name'] == 'measure_token' and f['code'] == 's' for f in m['fields'])
                        and all(c in ' ,_-' for c in filename[m['end']:a])
                        for m in observations
                    ):
                        continue
                if rule['id'] == 'executive-business-wording' and hit.groupdict().get('meeting_abbreviation'):
                    # The abbreviation alone has no established meeting meaning.
                    # Reuse the existing results-heading boundary as context.
                    a, b = hit.span('meeting_abbreviation')
                    if not any(m['rule'] in {'meeting-results-prefix', 'meeting-results-suffix'}
                               and m['start'] <= start + a and start + b <= m['end']
                               for m in observations):
                        continue
                if rule['id'] in {'meeting-results-prefix', 'meeting-results-suffix'}:
                    # Heading context may contain existing dates and session
                    # fields; only the newly captured word must be unclaimed.
                    a, b = hit.span('result_wording')
                    if not self._overlaps(start + a, start + b, protected):
                        observations.append(self._match(rule, hit, start))
                    continue
                # Keep generic labels alongside more specific phrases and context.
                reserved = ([(f['start'], f['end']) for f in protected_fields if f['name'] != 'label']
                            if rule['id'] in {'senr-context', 'summary-component-wording',
                                              'executive-business-wording',
                                              'budget-views-wording', 'oversight-plan-wording'} else protected)
                if rule['id'] in {'budget-views-wording', 'oversight-plan-wording'}:
                    # Retain a longer phrase, but avoid repeating an existing label.
                    a, b = hit.span('label')
                    if any(f['name'] == 'label' and (f['start'], f['end']) == (start + a, start + b)
                           for f in protected_fields):
                        continue
                if rule['id'] == 'managers-amendment-wording':
                    reserved = [(f['start'], f['end']) for f in protected_fields
                                if f['name'] != 'amendment_marker']
                if rule['id'] == 'amendment-form-wording':
                    a, b = start + hit.start(), start + hit.end()
                    if (a > start and filename[a - 1].isalnum()
                            or b < stem_end and filename[b].isalpha() and not filename[b].isascii()):
                        continue
                    # A manager's phrase already includes the narrower wording.
                    # Numbered amendment markers can coexist with the full label.
                    if any(f['name'] == 'label' and f['start'] <= a and b <= f['end']
                           for m in observations for f in m['fields']):
                        continue
                    reserved = [(f['start'], f['end']) for f in protected_fields
                                if f['name'] not in {'label', 'amendment_marker'}]
                if rule['id'] in {'ordered-reported-wording', 'legislative-text-wording', 'action-by-wording'}:
                    reserved = [(f['start'], f['end']) for f in protected_fields
                                if f['name'] not in {'label', 'qualifier_wording'}]
                if not self._overlaps(start + hit.start(), start + hit.end(), reserved):
                    observations.append(self._match(rule, hit, start))
                    if rule['id'] == 'source-amendment-reference':
                        part_rule, part_regex = self.by_id['amendment-local-version']
                        if part := part_regex.fullmatch(hit['amendment_token']):
                            observations.append(self._match(part_rule, part, start + hit.start('amendment_token')))
        if member_surnames:
            observations.extend(self._members(filename, observations, member_surnames))
        # A concatenated URL can leave a recognizable prefix without yielding a
        # valid filename. Preserve the original boundaries and expose fragments
        # separately; reuse the ordinary extension and payload rules.
        for rule, regex in self.rules:
            if rule['id'] != 'extension-protocol-suffix' or not (hit := regex.search(stem)):
                continue
            boundary = start + hit.start()
            extension = EXTENSION.search(filename, start, boundary)
            if extension is None:
                continue
            transport = self._match(rule, hit, start)
            transport['start'] = extension.start()
            transport['fields'].insert(0, self._field('embedded_extension', extension['extension'],
                extension.start('extension'), extension.end('extension'),
                note='Printed extension-like text before a protocol marker; not a final extension or verified file format.'))
            observations.append(transport)
            for scope, payload, offset in payloads:
                if scope not in {'legislative-payload', 'committee-payload'} or any(
                        m['scope'] == scope for m in observations):
                    continue
                prefix = filename[offset:extension.start()]
                for priority in (0, 1, 2, 3):
                    fragments = [self._match(r, h, offset) for r, rx in self.rules
                                 if r['scope'] == scope and r['priority'] == priority
                                 and (h := rx.fullmatch(prefix))]
                    if not fragments:
                        continue
                    known = {(f['name'], f['raw'], f['start'], f['end'])
                             for m in observations for f in m['fields']}
                    for fragment in fragments:
                        fragment['fields'] = [f for f in fragment['fields'] if f['raw']
                                              and (f['name'], f['raw'], f['start'], f['end']) not in known]
                        if fragment['fields']:
                            fragment.update(rule='fragment-' + fragment['rule'], scope=scope + '-fragment',
                                description=fragment['description'] + ' Readable prefix before extension-like text and a protocol marker; the full source name remains malformed.')
                            observations.append(fragment)
                    break
        pieces = [{'kind': hit.lastgroup, 'raw': hit[0], 'start': hit.start(), 'end': hit.end()} for hit in TOKEN.finditer(filename)]
        return {'input': filename, 'stem_end': stem_end, 'observations': observations,
                'pieces': pieces, 'suppressed': ignored}
