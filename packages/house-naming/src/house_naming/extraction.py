"""Read literal source basenames without requiring a renderable convention.

Observed syntax, vocabulary meanings and last-resort assumptions stay separate.
Every field points into the unchanged input; date roles require an explicit convention.
"""
from __future__ import annotations

from datetime import date
from collections.abc import Mapping, Sequence
from functools import lru_cache
import re
from urllib.parse import urlsplit

from .errors import NamingError
from .extraction_catalog import bind_extraction_rules, compile_pattern
from .metadata import NUMBER_BOUNDARY_NOTE, starts_with_ordinal_suffix

HOUSE_NAMING_URL = "https://www.govinfo.gov/content/pkg/GOVPUB-Y1_2-PURL-gpo156119/pdf/GOVPUB-Y1_2-PURL-gpo156119.pdf"

MAX_SOURCE_BYTES = 16_384
MAX_REMAINDER_REFINEMENTS = 128
MAX_REMAINDER_TEXT = 262_144
STEM_PRIORITIES = (0, 1, 2)
PAYLOAD_PRIORITIES = (0, 1, 2, 3)
EXTENSION = re.compile(r'\.(?P<extension>pdf|xml|html?|docx?|xlsx?|pptx?|txt|rtf|zip|csv|tsv|xsd|jpe?g|png|mp[34]|m3u8|aspx|cfm)\Z', re.I | re.ASCII)
TOKEN = re.compile(r'(?P<word>[^\W\d_]+)|(?P<number>[0-9]+)|(?P<separator>[\s\S])')
QUERY = re.compile(r'[?&](?:[^?&=\s]+=[^&\s]*)(?:&[^?&=\s]+=[^&\s]*)*\Z')
MALFORMED_DATE_NOTE = 'Date-shaped text with unsupported numeric component length; source digits are not repaired and no event date is established.'
MONTHS = {name: number for number, name in enumerate(
    ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


def remaining_spans(filename, start, end, covered):
    """Keep disjoint literal text after assigned spans, trimming separators only."""
    result, pos = [], start
    spans = sorted((max(a, start), min(b, end)) for a, b in covered if a < end and start < b)
    for a, b in [*spans, (end, end)]:
        if a > pos:
            left, right = pos, a
            while left < right and filename[left] in ' ._-()[]':
                left += 1
            while right > left and filename[right - 1] in ' ._-()[]':
                right -= 1
            if left < right:
                result.append((left, right))
        pos = max(pos, b)
    return result


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
            triples = [(raw[:4], raw[4:6], raw[6:])]
            # Delimiter-free publisher aliases also append counters to short
            # dates. Support the observed 19xx/20xx trailing-year convention;
            # other centuries require an explicit year-first/separated date.
            if raw[4:6] in {'19', '20'}:
                triples.extend([(raw[4:], raw[:2], raw[2:4]), (raw[4:], raw[2:4], raw[:2])])
        elif len(raw) == 7:
            # One unpadded month/day with a four-digit year. Preserve every
            # valid supported reading rather than selecting a date order.
            triples = ([(raw[:4], raw[4:5], raw[5:]), (raw[:4], raw[4:6], raw[6:])]
                       if raw[:2] in {'19', '20'} else [])
            for split in (1, 2):
                a, b = raw[:split], raw[split:3]
                if raw[3:5] in {'19', '20'}:
                    triples.extend([(raw[3:], a, b), (raw[3:], b, a)])
        elif len(raw) == 6:
            if raw[2:4] in {'19', '20'}:
                triples = [(raw[2:], raw[:1], raw[1:2]), (raw[2:], raw[1:2], raw[:1])]
            a, b, c = int(raw[:2]), int(raw[2:4]), int(raw[4:])
            short = [(c, a, b), (c, b, a), (a, b, c)]
        elif len(raw) == 5:
            for split in (1, 2):
                a, b, c = int(raw[:split]), int(raw[split:-2]), int(raw[-2:])
                short.extend([(c, a, b), (c, b, a)])
    elif (len(parts) == 2 and all(p.isascii() and p.isdigit() for p in parts)
          and len(parts[0]) <= 2 and len(parts[1]) == 6 and parts[1][2:4] in {'19', '20'}):
        a, b, y = parts[0], parts[1][:2], parts[1][2:]
        triples = [(y, a, b), (y, b, a)]
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




class Extractor:
    def __init__(self, guide: dict):
        self.guide = guide
        self.by_id = bind_extraction_rules(guide)
        self.rules = list(self.by_id.values())
        self.rule_order = {r['id']: i for i, (r, _) in enumerate(self.rules)}
        self.roles = {role: self.by_id[rid] for role, rid in guide['extraction_roles'].items()}
        self.searchable_fields = {f for r, _ in self.rules for f in r.get('searchable_fields', ())}
        self.stem_ids = {r['id'] for r, _ in self.rules if r['scope'] in {'stem', 'source-stem'}}
        self.legislative_ids = {r['id'] for r, _ in self.rules if r['scope'] == 'legislative-payload'}
        self.separated_version = self._pattern('separated_version')
        self.joined_measures = self._pattern('joined_measures')
        self.filer_member = self._pattern('filer_member')
        self.refinements = {}
        for rule, _ in self.rules:
            stages = {}
            for route in rule.get('refine', ()):
                children = [(r, rx) for r, rx in self.rules
                            if r['id'] in route.get('rules', ()) or r['scope'] == route.get('scope')]
                stages.setdefault(route['stage'], []).append((route, children))
            self.refinements[rule['id']] = stages

    def _pattern(self, name):
        return compile_pattern(self.guide, name)

    def _apply_reading(self, field, reading):
        if 'house_context' in reading:
            self._meaning(field, reading['house_context'], reading['house_token'])
        field.update({k: v for k, v in reading.items() if k not in {'house_context', 'house_token', 'label_case'}})
        if reading.get('label_case') == 'title':
            field['label'] = field['raw'].title()

    def _read_vocabularies(self, field, rule, groups):
        for lookup in rule.get('field_vocabularies', {}).get(field['name'], ()):
            if lookup.get('fallback') and field['code'] is not None:
                continue
            raw = groups.get(lookup.get('from', field['name']))
            if raw is None:
                continue
            key = raw.lower()
            normalizer = lookup.get('normalize')
            if normalizer == 'words':
                key = re.sub(r'[ _-]+', ' ', key)
            elif normalizer == 'first-word':
                key = re.split(r'[ _-]+', key)[0]
            elif normalizer == 'letters':
                key = re.sub(r'[^a-z]', '', key)
            vocabulary = lookup['vocabulary']
            if vocabulary.startswith('house:'):
                self._meaning(field, vocabulary[6:], key)
            else:
                entry = self.guide['extraction_vocabularies'][vocabulary].get(key)
                if entry:
                    self._apply_reading(field, entry)

    def _option(self, match, name):
        return self.by_id.get(match['rule'], ({},))[0].get(name)

    def _uses(self, match, processor):
        return processor in (self._option(match, 'processors') or ())

    def _searchable(self, match, field):
        rule = self.by_id.get(match['rule'])
        return field['name'] in (rule[0].get('searchable_fields', ()) if rule else self.searchable_fields)

    def _refine(self, parent, filename, observations, stage):
        routes = self.refinements.get(parent['rule'], {}).get(stage, ())
        if not routes:
            return
        fields = [dict(name='$match', raw=filename[parent['start']:parent['end']], start=parent['start'])] if stage == 'match' else parent['fields']
        for field in fields:
            selected = []
            for route, children in routes:
                if route['field'] != field['name']:
                    continue
                when = route.get('when')
                if when and not any(f['name'] == when['field'] and f['raw'].lower() in when['values'] for f in parent['fields']):
                    continue
                selected.extend((route, rule, regex) for rule, regex in children)
            # A field can select several scopes. Preserve catalog order across
            # their union, just as the ordinary candidate scan does.
            seen = set()
            for route, rule, regex in sorted(selected, key=lambda item: self.rule_order[item[1]['id']]):
                if stage == 'scopes' and rule.get('whole_slot_only'):
                    continue
                trim = route.get('trim_for', {}).get(rule['id'], '')
                raw = field['raw'].lstrip(trim)
                offset = field['start'] + len(field['raw']) - len(raw)
                mode = 'search' if rule['id'] in route.get('search_rules', ()) else route['mode']
                unique = route.get('unique') or stage == 'scopes' and rule.get('unique_refinement')
                key = rule['id'], trim, mode, bool(unique)
                if key in seen:
                    continue
                seen.add(key)
                hit = None if mode == 'search' else getattr(regex, mode)(raw)
                hits = regex.finditer(raw) if mode == 'search' else (hit,) if hit else ()
                for hit in hits:
                    if unique and any(m['rule'] == rule['id'] and m['start'] == offset + hit.start()
                                      and m['end'] == offset + hit.end() for m in observations):
                        continue
                    observations.append(self._match(rule, hit, offset))

    def _field(self, name: str, raw: str, start: int, end: int, *, note=None) -> dict:
        return {'name': name, 'raw': raw, 'start': start, 'end': end,
                'candidates': [], 'note': note, 'code': None, 'label': None, 'context': None,
                'vocabulary_url': None, 'role': None, 'category': None}

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
        descriptive_field = rule.get('version_boundary_field', 'descriptor')
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
            if name in rule.get('capture_rules', {}):
                # Position alone does not make SUS or ANS a text version. The
                # existing whole-slot marker rules supply their proper roles.
                refined = next((self._match(r, token, start + offset)['fields']
                                for r, rx in self.rules
                                if r['id'] in rule['capture_rules'][name]
                                and (token := rx.fullmatch(raw))), None)
                if refined is not None:
                    fields.extend(refined)
                    continue
            field = self._field(name, raw, start + offset, end + offset)
            if name == 'label' and 'label' in rule:
                field.update(label=rule['label'], note=rule['description'])
            self._apply_reading(field, rule.get('field_readings', {}).get(name, {}))
            self._read_vocabularies(field, rule, groups)
            ordinal_tail = (hit.string[end:] if rule.get('ordinal_tail') == '$after'
                            else groups.get(rule.get('ordinal_tail'), '') or '')
            if name == 'measure_number' and starts_with_ordinal_suffix(ordinal_tail):
                field.update(name='ambiguous_number_token', note=NUMBER_BOUNDARY_NOTE)
            if 'congress-ordinal' in rule.get('processors', ()):
                number = int(groups['referenced_congress'])
                ordinal = 'th' if 10 <= number % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
                field['note'] = 'Printed Congress reference; no primary Congress, calendar years or Congress for other references inferred.'
                if groups.get('congress_ordinal') and groups['congress_ordinal'].lower() != ordinal:
                    field['note'] += ' Ordinal does not agree with the printed number; source spelling retained.'
                if number == 0:
                    field['note'] += ' Congress number is not positive; source value retained.'
                elif groups['referenced_congress'].startswith('0'):
                    field['note'] += ' Leading zeros retained; no canonical number assigned.'
            if name in {'date_token', 'short_date_token'}:
                field['candidates'], _, field['note'] = date_candidates(raw)
                if 'malformed-date' in rule.get('processors', ()):
                    field['note'] = MALFORMED_DATE_NOTE
            if name == 'fiscal_year_token' and 'fiscal-year' in rule.get('processors', ()):
                field['note'] = 'Printed fiscal year; no calendar date is established.'
                if len(raw) == 2:
                    field['note'] += ' The century remains unspecified.'
            if name == 'version_token':
                if not field['code']:
                    field['note'] = 'Literal version-shaped token without a vocabulary mapping.'
                if 'inferred-version' in rule.get('processors', ()):
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
            if name == 'filer_token':
                field['note'] = 'Literal filed-by wording; no author identity or sponsorship is established.'
                # Mixed-case Rep/Reps has a visible boundary. All-uppercase or
                # lowercase text stays whole rather than losing a surname S.
                member = self.filer_member.fullmatch(raw)
                if member:
                    for part, text in member.groupdict().items():
                        fields.append(self._field(part, text, start + offset + member.start(part),
                            start + offset + member.end(part), note=field['note']))
            if name == 'revision_marker' and raw.lower() == 'u' and hit.end() == len(hit.string) and (groups['revision_number'] or '').strip('0'):
                self._meaning(field, 'revision')
                field.update(code='u', label='Document update', vocabulary_url=f'{HOUSE_NAMING_URL}#page=20', note='U1 denotes the first update since posting.')
            if name == 'date_token' and 'week-start' in rule.get('processors', ()):
                field['note'] = 'Week start date; the House guide specifies Monday, including holidays.'
                if not field['candidates']:
                    field['note'] += ' No valid supported calendar reading; source value retained.'
                elif date.fromisoformat(field['candidates'][0]).weekday() != 0:
                    field['note'] += ' Printed date is not Monday; source value retained.'
            fields.append(field)
        if 'partial-date' in rule.get('processors', ()):
            for field in fields:
                if field['name'] == 'partial_date_token':
                    month = groups['partial_month_token']
                    field['candidates'] = ([groups['partial_year_token']] if month.lower() == 'xx'
                                           else [groups['partial_year_token'] + '-' + month] if 1 <= int(month) <= 12 else [])
                    if not field['candidates']:
                        field['note'] += ' Invalid month; source components retained without repair.'
        if 'possible-month-day' in rule.get('processors', ()):
            raw = groups['possible_month_day_token']
            fields.append(self._field('generic_identifier', raw, hit.start() + offset, hit.end() + offset,
                                     note='An identifier remains possible; the four digits also resemble a month/day.'))
        if 'month-year' in rule.get('processors', ()):
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
        congress = next((f['raw'] for m in observations for f in m['fields'] if f['name'] == self.by_id.get(m['rule'], ({},))[0].get('roster_congress')), None)
        surnames = member_surnames.get(congress, ())
        if (not isinstance(surnames, Sequence) or isinstance(surnames, (str, bytes))
                or any(not isinstance(value, str) or not value.strip() for value in surnames)):
            raise NamingError('invalid-member-reference', 'Member surnames must be a sequence of nonempty strings for each Congress')
        if not surnames:
            return []
        pattern = member_title_pattern(tuple(surnames))
        rule = {'id': 'member-title', 'scope': 'legislative-text-search',
                'field_vocabularies': {'version_token': [
                    {'vocabulary': 'house:version'}, {'vocabulary': 'house-version-overrides'},
                    {'vocabulary': 'govinfo-bill-versions', 'fallback': True}]},
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
        reference_rule, reference_regex = self.roles['support']
        hits = list(reference_regex.finditer(stem))
        if not hits:
            return []
        source_fields = [f for m in observations for f in m['fields']]
        hard_spans = [(f['start'], f['end']) for m in observations for f in m['fields']
                      if not self._searchable(m, f) and f['name'] != 'label']
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
                containers = [(f['start'], f['end']) for m in observations for f in m['fields']
                              if self._searchable(m, f) and f['start'] <= a and b <= f['end']
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

    def _subject_remainders(self, filename: str, observations: list[dict]) -> list[dict]:
        """Refine descriptive subjects using fields already recognized elsewhere.

        Never join disjoint pieces or reinterpret structured witness/member IDs.
        A single remaining text span is a subject, not a resolved person.
        """
        labels = [f for m in observations for f in m['fields']
                  if f['name'] in {'label', 'amendment_marker', 'document_token'} and f.get('category')]
        if not labels:
            return []
        removable = {'label', 'date_token', 'short_date_token', 'time_token', 'fraction_token',
                     'opaque_identifier', 'opaque_uuid', 'opaque_hex', 'qualifier_wording',
                     'revision_marker', 'revision_number', 'local_number_token', 'ignored_suffix',
                     'committee_token', 'committee_marker', 'subcommittee_token', 'subcommittee_marker',
                     'meeting_wording', 'field_location_token', 'field_marker', 'session_period',
                     'nomination_wording', 'fiscal_marker', 'fiscal_year_token', 'month_year_token',
                     'month_token', 'year_token', 'filename_format_token', 'context_token', 'question_identifier'}
        spans = [(f['start'], f['end']) for m in observations for f in m['fields']
                 if f['name'] in removable and f['raw']]
        # Conjunctions connect document labels, not parts of a person's name.
        for left in labels:
            for right in labels:
                if left['end'] < right['start'] and re.fullmatch(
                        r'[ _-]*(?:and|&)[ _-]*', filename[left['end']:right['start']], re.I):
                    spans.append((left['end'], right['start']))
        if any(f.get('category') == 'amendment' for f in labels):
            spans.extend((f['start'], f['end']) for m in observations for f in m['fields']
                         if f['name'] in {'measure_token', 'measure_number', 'amendment_marker', 'amendment_token'})
        results, seen = [], {(f['start'], f['end']) for m in observations for f in m['fields']
                             if f['name'] == 'subject_token' and f['raw']}
        for parent in observations:
            explicit = self._uses(parent, 'subject-remainder') or parent['scope'] == 'subject-refinement'
            fallback = parent['scope'] in {'unmatched-date', 'unmatched-stem'}
            payload = self._option(parent, 'payload_scope') == 'descriptive-payload'
            if not (explicit or fallback or payload):
                continue
            for field in parent['fields']:
                if field['name'] != ('subject_token' if explicit else 'payload' if payload else 'name_token'):
                    continue
                a, b = field['start'], field['end']
                if fallback and not any(a <= f['start'] < f['end'] <= b for f in labels):
                    continue
                # Remove only recognized complete components within this span.
                remaining = remaining_spans(filename, a, b, spans)
                # Recognized interior fields may be part of the title itself,
                # such as FY 2024 in a budget hearing. Trim the edges while
                # preserving the contiguous source text between them.
                left, right = (remaining[0][0], remaining[-1][1]) if remaining else (b, b)
                # Leading grammatical wording belongs to a label-to-subject
                # transition. Do not remove 'on' from a statement's topic.
                if explicit and any(f['end'] <= a and f.get('category') in {
                        'questions-for-record', 'questions-for-record-response', 'witness-statement'} for f in labels):
                    if prefix := re.match(r'(?:to|of|for)[ _-]+', filename[left:right], re.I):
                        left += prefix.end()
                counter = re.fullmatch(r'[A-Za-z]+([0-9]{1,3})', filename[left:right])
                counter_field = None
                if counter:
                    counter_start = left + counter.start(1)
                    counter_field = self._field('local_number_token', filename[counter_start:right], counter_start, right,
                        note='Terminal number in an unstructured document subject; no revision or person identity inferred.')
                    right = counter_start
                has_text = any(c.isalpha() for c in filename[left:right])
                if (left, right) in seen and has_text:
                    continue
                if (left, right) == (a, b) and not payload and has_text:
                    continue
                fields = []
                if left < right and has_text:
                    fields.append(self._field('subject_token', filename[left:right], left, right,
                        note='Literal descriptive subject; no author, witness or member identity inferred.'))
                if counter_field:
                    fields.append(counter_field)
                # Only trim edges of an existing subject. Interior context can
                # divide a title; do not manufacture a new title by joining it.
                seen.add((left, right))
                results.append({'rule': 'document-subject-remainder', 'scope': 'subject-refinement',
                    'start': a, 'end': b,
                    'description': 'Subject text remaining after recognized filename components; no person identity inferred.',
                    'fields': fields})
        return results

    def _description_remainders(self, filename, observations):
        """Retain report text and titles alongside their other extracted fields."""
        fields = [f for m in observations for f in m['fields']]
        containers = [(m, f) for m in observations for f in m['fields']
                      if (self._uses(m, 'report-description') and f['name'] == 'payload')
                      or (self._uses(m, 'description-remainder') and f['name'] == 'description')]
        results, seen = [], set()
        for parent, field in containers:
            remove = {'revision_marker', 'revision_number', 'measure_token', 'number_placeholder',
                      'amendment_marker', 'amendment_token', 'filename_format_token'}
            if self._uses(parent, 'report-description'):
                remove |= {'label', 'fiscal_marker', 'fiscal_year_token', 'measure_number',
                           'part_marker', 'part_number', 'report_subject_token'}
            spans = [(f['start'], f['end']) for f in fields if f['name'] in remove]
            a, b = field['start'], field['end']
            remaining = remaining_spans(filename, a, b, spans)
            # Preserve each literal fragment; never join across removed text.
            parts = [self._field('description', filename[x:y], x, y)
                     for x, y in remaining if any(c.isalpha() for c in filename[x:y])]
            key = a, b
            if key not in seen and (self._uses(parent, 'report-description')
                                     or [(f['start'], f['end']) for f in parts] != [(a, b)]):
                seen.add(key)
                results.append(dict(rule='document-description-remainder', scope='subject-refinement',
                                    start=a, end=b, description='Literal description outside assigned components.', fields=parts))
        return results

    def extract(self, filename: str, *, member_surnames: Mapping[str, Sequence[str]] | None = None,
                source_url: str | None = None) -> dict:
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
        source_host = None
        if source_url is not None:
            try:
                if not isinstance(source_url, str) or len(source_url.encode('utf-8')) > MAX_SOURCE_BYTES:
                    raise ValueError
                if any(c.isspace() or ord(c) < 32 for c in source_url):
                    raise ValueError
                source = urlsplit(source_url)
                if (source.scheme not in {'http', 'https'} or not source.hostname
                        or source.username is not None or source.password is not None):
                    raise ValueError
                if source.port not in {None, 80, 443}:
                    raise ValueError
                source_host = source.hostname
            except (ValueError, UnicodeError) as exc:
                raise NamingError('invalid-source-url', 'Source context must be an HTTP(S) URL without credentials, at most 16384 UTF-8 bytes') from exc
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
        # Local publisher aliases qualify whole basenames, never a token inside
        # an official witness/member slot. The supplied URL is not dereferenced.
        if source_url is not None:
            for rule, regex in self.rules:
                if rule['scope'] != 'source-stem':
                    continue
                if source_host not in rule.get('source_hosts', ()) and source_url not in rule.get('source_urls', ()):
                    continue
                if hit := regex.fullmatch(stem):
                    observations.append(self._match(rule, hit, start))
        for priority in (() if any(m['scope'] == 'source-stem' for m in observations) else STEM_PRIORITIES):
            found = False
            for rule, regex in self.rules:
                if rule['scope'] == 'stem' and rule['priority'] == priority and (hit := regex.fullmatch(stem)):
                    found = True
                    observations.append(self._match(rule, hit, start))
                    if 'payload' in hit.groupdict():
                        scope = rule.get('payload_scope')
                        if scope:
                            payloads.append((scope, hit['payload'], start + hit.start('payload')))
            if found:
                break
        for scope, payload, offset in payloads:
            if scope == 'descriptive-payload':
                for priority in STEM_PRIORITIES:
                    found = False
                    for rule, regex in self.rules:
                        if (rule['scope'] != 'stem' or rule['priority'] != priority
                                or rule.get('payload_scope') == 'descriptive-payload'
                                or not (hit := regex.fullmatch(payload))):
                            continue
                        found = True
                        observations.append(self._match(rule, hit, offset))
                        if child_scope := rule.get('payload_scope'):
                            payloads.append((child_scope, hit['payload'], offset + hit.start('payload')))
                    if found:
                        break
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
                                        if rule['id'] == self.roles['substitute_target'][0]['id']
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
                elif rule.get('payload_probe'):
                    hit = regex.fullmatch(payload)
                    hits = (hit,) if hit else ()
                else:
                    continue
                for hit in hits:
                    # The normal priority pass may already have selected it.
                    if not any(m['rule'] == rule['id'] and m['start'] == offset + hit.start()
                               and m['end'] == offset + hit.end() for m in observations):
                        observations.append(self._match(rule, hit, offset))

        for parent in tuple(observations):
            self._refine(parent, filename, observations, 'before-search')

        # Keep useful label/subject slots, but never establish a date by cutting
        # a longer numeric component. Retain the old split as an alternative.
        for match in observations:
            if not self._uses(match, 'complete-date-token'):
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
            if not self._uses(parent, 'publication-components'):
                continue
            options = self._option(parent, 'publication_components') or {}
            if options.get('versions') and not any(f['name'] == 'version_token' and f['code'] in options['versions'] for f in parent['fields']):
                continue
            for field in parent['fields']:
                if field['name'] == 'suffix':
                    for rule, regex in self.rules:
                        if rule['scope'] == 'published-suffix-search':
                            for hit in regex.finditer(field['raw']):
                                if options.get('numbered_markers') and not (
                                    hit['publication_marker'].lower() in options['numbered_markers']
                                    and hit['publication_identifier'] and hit['publication_identifier'].isdigit()
                                ):
                                    continue
                                component = self._match(rule, hit, field['start'])
                                for part in component['fields']:
                                    self._apply_reading(part, options.get('reading', {}))
                                    self._read_vocabularies(part, options, hit.groupdict())
                                observations.append(component)

        # Loose report subjects may be report numbers, measure numbers or local
        # IDs. Preserve them whole; only printed part wording supplies a role.
        for parent in tuple(observations):
            if not self._uses(parent, 'numeric-subject-parts'):
                continue
            for field in parent['fields']:
                if field['name'] != 'payload':
                    continue
                for rule, regex in self.rules:
                    if rule['id'] != self.roles['numeric_report_subject'][0]['id'] or not (hit := regex.match(field['raw'])):
                        continue
                    observations.append(self._match(rule, hit, field['start']))
                    tail = field['raw'][hit.end():]
                    for part_rule, part_regex in self.rules:
                        if part_rule['id'] in {self.roles['generic_part'][0]['id'], self.roles['report_part'][0]['id']}:
                            observations.extend(self._match(part_rule, part, field['start'] + hit.end())
                                                for part in part_regex.finditer(tail))

        for parent in tuple(observations):
            self._refine(parent, filename, observations, 'local-reference')

        # Only free text slots can contain additional references or dates. Known
        # person IDs and dates must not produce accidental bills or revisions.
        # RCP uses short measure spellings that would be too broad to scan in
        # arbitrary prose. Read them only after a printed RCP prefix.
        if 'short_measure' in self.roles and 'print_prefix' in self.roles:
            owned_spans = [(f['start'], f['end']) for m in observations for f in m['fields']
                           if not self._searchable(m, f)]
            rcp_rule, rcp_regex = self.roles['short_measure']
            for prefix in self.roles['print_prefix'][1].finditer(stem):
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
                numeric_subject = (match['scope'] == 'legislative-payload'
                                   and field['name'] == 'subject_token' and field['raw'].isdigit())
                if numeric_subject or not self._searchable(match, field):
                    protected.append((field['start'], field['end']))

        searches = [(r, rx) for r, rx in self.rules if r['scope'] == 'search']
        separated_date = self.roles['separated_date'][1]
        measure_regex = self.roles['measure'][1]
        measure_spans = [(start + m.start(), start + m.end()) for m in measure_regex.finditer(stem)]
        # Complete identifier/date forms reserve their spans before other scans.
        date_rules = {r['id'] for r, _ in searches if 'numeric-date' in r.get('processors', ())}
        revision_dates = [rx for r, rx in searches if r['id'] in date_rules and r.get('revision_candidate', True)]

        def candidates(rule, regex):
            if rule['id'] not in date_rules:
                for hit in regex.finditer(stem):
                    if ('capitalized-label-boundary' in rule.get('processors', ()) and 'label' in hit.groupdict()
                            and hit.start() and stem[hit.start() - 1].isalpha()):
                        preceding_word = re.search(r'[A-Za-z]+\Z', stem[:hit.start()])
                        if preceding_word and not preceding_word[0][0].isupper():
                            continue
                    # A complete malformed shape still needs a possible month
                    # in one of its first two components. Its year stays raw.
                    if 'malformed-date' in rule.get('processors', ()) and min(
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
                # Prefer a complete four-digit-year reading over a crossing
                # short-date fragment, without assuming a century for either.
                return (not bool(date_candidates(raw)[0]), len(separators) > 1, hit.start())
            yield from sorted(hits, key=priority)

        def search_candidates():
            done = set()
            for rule, regex in sorted(searches, key=lambda item: item[0].get('scan_order', 5)):
                group = rule.get('candidate_group')
                if group:
                    if group in done:
                        continue
                    done.add(group)
                    candidates_in_group = [(r, h) for r, rx in searches if r.get('candidate_group') == group
                                           for h in rx.finditer(stem)]
                    yield from sorted(candidates_in_group, key=lambda item: (item[1].start(), -item[1].end()))
                else:
                    yield from ((rule, hit) for hit in candidates(rule, regex))

        for rule, hit in search_candidates():
            a, b = start + hit.start(), start + hit.end()
            if rule.get('unique_search') and any(
                    m['rule'] == rule['id'] and m['start'] == a and m['end'] == b for m in observations):
                continue
            if rule.get('unique_label') and any(
                    f['name'] in {'label', 'document_token'} and f['start'] == a and f['end'] == b
                    for m in observations for f in m['fields']):
                continue
            if 'following-degree' in rule.get('processors', ()) and not any(
                    m['rule'] == self.roles['degree'][0]['id'] and m['end'] == a for m in observations):
                continue
            if 'between-degrees' in rule.get('processors', ()) and not any(
                    m['rule'] == self.roles['degree'][0]['id'] and m['end'] <= a
                    and re.fullmatch(r'[ _-]+(?:[0-9]+[ _-]+)?', filename[m['end']:a])
                    for m in observations):
                continue
            if 'leading-date-label' in rule.get('processors', ()):
                if not any(self._option(m, 'leading_date')
                           and m['start'] == start and m['end'] <= a for m in observations):
                    continue
                # A delimited abbreviation may already expose the same label.
                if any(m['rule'] == self.roles['statement_label'][0]['id'] and m['start'] <= a
                       and m['end'] == b for m in observations):
                    continue
            reason = None
            if number := rule.get('reference_number'):
                # Attachment 3-27-19 contains a complete separated date, not
                # an established attachment 3. A compact numeric reference
                # remains whole even when its digits also resemble a date.
                date_hit = separated_date.match(stem, hit.start(number))
                if date_hit and date_hit.end() > hit.end(number) and date_candidates(date_hit['date_token'])[1]:
                    reason = 'Reference would consume only a prefix of a complete separated date.'
            if self._overlaps(a, b, protected):
                reason = 'Overlaps a structured or already assigned token.'
            if rule.get('respect_measure') and self._overlaps(a, b, measure_spans):
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
            if 'revision-date' in rule.get('processors', ()) and hit.groupdict().get('revision_number') and len(hit['revision_marker']) > 1:
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
            if reserve := rule.get('reserve'):
                protected.append((a, b) if reserve == 'match' else
                                 (start + hit.start(reserve), start + hit.end(reserve)))

        # An explicit measure reference also supplies legislative context in
        # descriptive names. Reuse the bounded marker, outside assigned fields.
        if not payloads and any(m['rule'] == self.roles['measure'][0]['id'] for m in observations):
            for role in ('descriptive_substitute', 'substitute_marker'):
                rule, regex = self.roles[role]
                for hit in regex.finditer(stem):
                    a, b = start + hit.start(), start + hit.end()
                    if not self._overlaps(a, b, protected):
                        observations.append(self._match(rule, hit, start))
                        protected.append((a, b))

        # Qualifiers belong to their filename wording, not to a verified access
        # or publication state. Group only neighboring words; names may precede
        # a terminal qualifier group, but unrelated title words cannot follow it.
        label_patterns = [rx for r, rx in self.rules
                          if r.get('qualifier_anchor')]
        document_labels = [{'start': f['start'], 'end': f['end'], 'rule': m['rule']}
                           for m in observations for f in m['fields']
                           if f['name'] == 'label' and any(rx.fullmatch(f['raw']) for rx in label_patterns)]
        qualifier_rule, qualifier_regex = self.roles['qualifier']
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
                adjacent = any(m['rule'] != self.roles['qualifier'][0]['id']
                               and (not self._option(m, 'qualifier_before_only') or match['end'] <= m['start'])
                               for m in group)
                public = any(f['raw'].lower() == 'public' for f in match.get('fields', ()))
                prefix = all(c in ' ._()-[]0123456789' or any(a <= i < b for a,b in terminal_spans)
                             for i,c in enumerate(filename[start:match['start']], start))
                # A leading qualifier can precede an unstructured subject and
                # its document label. Other topic labels (e.g. Final report
                # discusses Smith SJQ) make that interpretation unsupported.
                labels_after = [f for m in observations for f in m['fields']
                                if f['name'] == 'label' and f['start'] >= match['end']]
                prefix = prefix and all(f.get('category') in {
                    'testimony', 'statement', 'witness-statement', 'witness-list',
                    'questions-for-record', 'questions-for-record-response', 'questionnaire'} for f in labels_after)
                allowed = adjacent or terminal or prefix
                if public:
                    # Public servants / Public health describes a topic. A
                    # trailing Public or Public before the label is different.
                    allowed = terminal and bool(document_labels) or any(
                        m['rule'] != self.roles['qualifier'][0]['id'] and match['end'] <= m['start']
                        for m in group)
                if match['rule'] == self.roles['qualifier'][0]['id'] and allowed:
                    observations.append(match)
                    protected.append((match['start'], match['end']))
        number_rule, number_regex = self.roles['label_number']
        label_ends = {m['end'] for m in document_labels} | {
            m['end'] for m in observations if m['rule'] == self.roles['qualifier'][0]['id']}
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
            for field in parent['fields']:
                if field['name'] == 'measure_list':
                    pos = 2 if field['raw'].upper().startswith('SA') else 0
                    reference_rule = self.roles['measure'][0]
                    while hit := self.joined_measures.match(field['raw'], pos):
                        observations.append(self._match(reference_rule, hit, field['start']))
                        pos = hit.end()
            for stage in ('fields', 'match', 'scopes'):
                self._refine(parent, filename, observations, stage)
        for parent in tuple(observations):
            self._refine(parent, filename, observations, 'targets')

        # Bare ANS_01 already has a whole-slot interpretation. Keep the new
        # component rule only when it exposes syntax not already available.
        # A qualified reading on the whole-slot marker is not a second number.
        for match in tuple(observations):
            if self._option(match, 'deduplicate_fields') == 'syntax' and all(
                any(all(field[key] == other[key] for key in ('name', 'raw', 'start', 'end'))
                    for m in observations if m is not match for other in m['fields'])
                for field in match['fields']
            ):
                observations.remove(match)
            if self._option(match, 'deduplicate_fields') == 'reading' and all(
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
                         for m in observations for f in m['fields'] if not self._searchable(m, f)})
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
                if any(self._uses(m, 'atomic-identifier')
                       and m['start'] == left and m['end'] == right for m in observations):
                    return None
                return self._match(rule, hit, left)
            return None

        def selected_date_remainder(left, right, *, subject=False):
            selected = next((m for m in observations
                           if self._option(m, 'leading_date')
                           and m['start'] == left and m['end'] < right), None)
            if selected is None:
                selected = next((m for m in observations if self._uses(m, 'malformed-date')
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
            malformed = self._uses(selected, 'malformed-date')
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
            if not self._uses(parent, 'subject-remainder'):
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
                    suffix_only = 'suffix-only-fallback' in rule.get('processors', ())
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
        if stem and not is_zip and not any(m['rule'] in self.stem_ids or m['scope'] == 'collection-prefix' for m in observations):
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
                             if r.get('scan_stage') == 'supplemental' or (r['scope'] == 'document-wording-search' and r.get('scan_stage') != 'context')
                             for h in rx.finditer(stem)]
        if supplemental_hits:
            protected_fields = [f for m in observations for f in m['fields']
                                if not self._searchable(m, f) and f['name'] != 'generic_identifier']
            protected = [(f['start'], f['end']) for f in protected_fields]
            for rule, hit in supplemental_hits:
                if 'measure-context' in rule.get('processors', ()) and not any(
                        b <= start + hit.start() for a, b in measure_spans):
                    continue
                if 'numeric-date' in rule.get('processors', ()):
                    raw = hit.groupdict().get('date_token', hit.groupdict().get('short_date_token'))
                    if not date_candidates(raw)[1]:
                        continue
                if 'ascii-left-boundary' in rule.get('processors', ()):
                    a = start + hit.start()
                    if a > start and filename[a - 1].isalpha() and not filename[a - 1].isascii():
                        continue
                if 'avoid-ordinal-tail' in rule.get('processors', ()) and starts_with_ordinal_suffix(stem[hit.end():]):
                    continue
                if 'companion-context' in rule.get('processors', ()):
                    a = start + hit.start('document_abbreviation')
                    if a > start and filename[a - 1].isalnum():
                        continue
                    if hit['document_abbreviation'].lower() == 'ma' and not any(
                        m['rule'] == self.roles['measure'][0]['id'] and m['start'] == start and m['end'] < a
                        and any(f['name'] == 'measure_token' and f['code'] == 's' for f in m['fields'])
                        and all(c in ' ,_-' for c in filename[m['end']:a])
                        for m in observations
                    ):
                        continue
                if 'heading-abbreviation' in rule.get('processors', ()) and hit.groupdict().get('meeting_abbreviation'):
                    # The abbreviation alone has no established meeting meaning.
                    # Reuse the existing results-heading boundary as context.
                    a, b = hit.span('meeting_abbreviation')
                    if not any(self._option(m, 'reserve_field') == 'result_wording'
                               and m['start'] <= start + a and start + b <= m['end']
                               for m in observations):
                        continue
                if rule.get('reserve_field'):
                    # Heading context may contain existing dates and session
                    # fields; only the newly captured word must be unclaimed.
                    a, b = hit.span(rule['reserve_field'])
                    if not self._overlaps(start + a, start + b, protected):
                        observations.append(self._match(rule, hit, start))
                    continue
                # Keep generic labels alongside more specific phrases and context.
                reserved = [(f['start'], f['end']) for f in protected_fields
                            if f['name'] not in rule.get('allow_overlap_fields', ())]
                if rule.get('unique_label'):
                    a, b = hit.span('label')
                    if any(f['name'] == 'label' and (f['start'], f['end']) == (start + a, start + b)
                           for f in protected_fields):
                        continue
                if 'amendment-label-boundary' in rule.get('processors', ()):
                    a, b = start + hit.start(), start + hit.end()
                    if (a > start and filename[a - 1].isalnum()
                            or b < stem_end and filename[b].isalpha() and not filename[b].isascii()):
                        continue
                    # A manager's phrase already includes the narrower wording.
                    # Numbered amendment markers can coexist with the full label.
                    if any(f['name'] == 'label' and f['start'] <= a and b <= f['end']
                           for m in observations for f in m['fields']):
                        continue
                if not self._overlaps(start + hit.start(), start + hit.end(), reserved):
                    observations.append(self._match(rule, hit, start))
                    self._refine(observations[-1], filename, observations, 'supplemental')
        observations.extend(self._subject_remainders(filename, observations))
        observations.extend(self._description_remainders(filename, observations))
        if member_surnames:
            observations.extend(self._members(filename, observations, member_surnames))
        # A concatenated URL can leave a recognizable prefix without yielding a
        # valid filename. Preserve the original boundaries and expose fragments
        # separately; reuse the ordinary extension and payload rules.
        for rule, regex in self.rules:
            if rule['scope'] != 'transport-search' or not (hit := regex.search(stem)):
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
        return {'input': filename, **({'source_url': source_url} if source_url is not None else {}),
                'stem_end': stem_end, 'observations': observations,
                'pieces': pieces, 'suppressed': ignored}
