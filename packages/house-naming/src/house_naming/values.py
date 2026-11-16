"""Useful filename values, independent of strict convention validation or storage.

The catalog assigns categories and field roles. This module collects those
readings; it does not parse names, resolve people, or combine different sources.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

from .bill_codes import MAX_CONGRESS, MIN_CONGRESS, is_valid_congress
from .metadata import target_subject_spans
from .categories import (
    EVENT_KINDS,
    document_category_fields,
    document_families,
    filename_slot_info,
    is_slot_kind_ambiguous,
    resolve_verified_document_kind,
)

OMIT_FIELDS = frozenset({'payload', 'query_text', 'ignored_suffix', 'protocol_marker'})
GENERIC_KINDS = frozenset({'committee-document', 'committee-document-numbered'})
_WASHINGTON_TZ = ZoneInfo('America/New_York')
_YMD_ISO_RE = re.compile(
    r'^(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})'
    r'(?:[T\s]+(?P<hh>\d{1,2}):(?P<mm>\d{2})(?::(?P<ss>\d{2})(?:\.\d+)?)?'
    r'\s*(?P<tz>Z|[+-]\d{2}:?\d{2})?)?$',
    re.I | re.ASCII,
)
_YMD_COMPACT_RE = re.compile(r'^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$', re.ASCII)


def date_to_congress_constitutional(
    date_or_ymd: date | datetime | str | tuple[int, int, int] | None,
    *,
    max_congress: int | None = MAX_CONGRESS,
) -> int | None:
    """Map a calendar date or timestamp to its U.S. Congress under the 20th Amendment.

    Implements the constitutional Noon-January-3 session boundary (U.S. Const.
    amend. XX, § 1, effective 1935 for the 74th Congress; March 4 prior to 1935):
      - ``Jan 1`` and ``Jan 2`` of an odd-numbered year ``Y >= 1935`` belong to the
        outgoing Congress (e.g. ``2021-01-01`` and ``2021-01-02`` -> ``116``,
        fixing early-January off-by-one Congress errors).
      - ``Jan 3`` of an odd-numbered year ``Y >= 1935`` belongs to the new Congress
        for date-only inputs (e.g. ``2021-01-03`` -> ``117``, ``2023-01-03`` -> ``118``);
        when a ``datetime`` or timestamp with time-of-day is supplied on ``Jan 3`` of an
        odd year, times strictly before ``12:00`` noon (in ``America/New_York`` when
        timezone-aware) map to the outgoing Congress and ``>= 12:00`` noon map to the
        incoming Congress.
      - Even-numbered years (including ``Jan 1`` and ``Jan 2``, e.g. ``2022-01-02`` -> ``117``)
        always belong to the Congress that convened in ``Y - 1``.
    """
    if date_or_ymd is None or isinstance(date_or_ymd, (bool, int, float)):
        return None

    year: int
    month: int
    day: int
    before_noon: bool | None = None

    if isinstance(date_or_ymd, datetime):
        dt = date_or_ymd.astimezone(_WASHINGTON_TZ) if date_or_ymd.tzinfo is not None else date_or_ymd
        year, month, day = dt.year, dt.month, dt.day
        before_noon = dt.hour < 12
    elif isinstance(date_or_ymd, date):
        year, month, day = date_or_ymd.year, date_or_ymd.month, date_or_ymd.day
    elif isinstance(date_or_ymd, tuple) and len(date_or_ymd) == 3:
        y_raw, m_raw, d_raw = date_or_ymd
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (y_raw, m_raw, d_raw)):
            return None
        try:
            checked = date(y_raw, m_raw, d_raw)
        except ValueError:
            return None
        year, month, day = checked.year, checked.month, checked.day
    elif isinstance(date_or_ymd, str):
        s = date_or_ymd.strip()
        if not s:
            return None
        m_comp = _YMD_COMPACT_RE.match(s)
        if m_comp:
            y_i, m_i, d_i = int(m_comp.group('y')), int(m_comp.group('m')), int(m_comp.group('d'))
            try:
                date(y_i, m_i, d_i)
            except ValueError:
                return None
            year, month, day = y_i, m_i, d_i
        else:
            m_iso = _YMD_ISO_RE.match(s)
            if not m_iso:
                return None
            y_i, m_i, d_i = int(m_iso.group('y')), int(m_iso.group('m')), int(m_iso.group('d'))
            try:
                date(y_i, m_i, d_i)
            except ValueError:
                return None
            if m_iso.group('hh') is not None:
                norm_iso = s.replace('/', '-').replace('.', '-')
                if norm_iso.endswith(('Z', 'z')):
                    norm_iso = norm_iso[:-1] + '+00:00'
                elif m_iso.group('tz') and re.fullmatch(r'[+-]\d{4}', m_iso.group('tz')):
                    norm_iso = norm_iso[:-2] + ':' + norm_iso[-2:]
                try:
                    dt = datetime.fromisoformat(norm_iso)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(_WASHINGTON_TZ)
                    year, month, day = dt.year, dt.month, dt.day
                    before_noon = dt.hour < 12
                except ValueError:
                    hh, mm = int(m_iso.group('hh')), int(m_iso.group('mm'))
                    ss = int(m_iso.group('ss') or 0)
                    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                        return None
                    year, month, day = y_i, m_i, d_i
                    before_noon = hh < 12
            else:
                year, month, day = y_i, m_i, d_i
    else:
        return None

    if year < 1789:
        return None

    if year % 2 == 0:
        start_odd_year = year - 1
    elif year >= 1935:
        if month == 1 and (day < 3 or (day == 3 and before_noon is True)):
            start_odd_year = year - 2
        else:
            start_odd_year = year
    else:
        if month < 3 or (month == 3 and (day < 4 or (day == 4 and before_noon is True))):
            start_odd_year = year - 2
        else:
            start_odd_year = year

    if start_odd_year < 1789:
        return None
    congress = (start_odd_year - 1789) // 2 + 1
    if congress < MIN_CONGRESS:
        return None
    if max_congress is not None and congress > max_congress:
        return None
    return congress


def filename_metadata(result: dict, *, convention_matches: list[dict] | None = None) -> dict[str, list[str]]:
    """Flatten one extraction without losing source spellings or alternatives.

    Refined text supersedes its enclosing fallback in these useful values only;
    all original spans remain available in ``observations``. Strict validation
    adds convention-specific fields but is never required for literal readings.
    The caller may supply matches for the filename before a transport suffix;
    this does not change the original result's strict validation fields.
    """
    row = defaultdict(list)
    observations = result['observations']
    refinements = [field for match in observations
                   if match.get('scope') == 'subject-refinement'
                   for field in match['fields'] if field['name'] == 'subject_token']
    bioguides = {(f['start'], f['end']) for m in observations for f in m['fields']
                 if f['name'] == 'bioguide_token'}
    categories = []
    assigned_roles = set()
    empty_subjects = [(m['start'], m['end']) for m in observations
                      if m.get('rule') in {'document-subject-remainder', 'role-subject-remainder'}
                      and not m['fields']]
    concrete = [(f['start'], f['end']) for m in observations for f in m['fields']
                if f['name'] in {'amendment_token', 'measure_number', 'year_token', 'date_token',
                                'short_date_token', 'drafting_identifier'}]

    descriptions = [m for m in observations if m.get('rule') == 'document-description-remainder']
    # A structured amendment's subject describes its target. Labels inside
    # that slot remain useful without changing the amendment's document kind.
    target_spans = target_subject_spans(observations)
    primary_fields = {id(f) for f in document_category_fields(result.get('input'), observations)}

    def add(name, value):
        if value is not None and value != '':
            if not isinstance(value, (str, int)):
                raise TypeError(f'Expected a scalar metadata value for {name}')
            value = str(value)
            if value not in row[name]:
                row[name].append(value)

    for match in observations:
        for field in match['fields']:
            name = field['name']
            if name in OMIT_FIELDS:
                continue
            if name == 'description' and match.get('rule') != 'document-description-remainder' and any(
                    m['start'] <= field['start'] < field['end'] <= m['end'] for m in descriptions):
                continue
            if name in {'subject_token', 'name_token'} and any(
                    a <= field['start'] <= field['end'] <= b for a, b in empty_subjects):
                continue
            if name == 'generic_identifier' and match['scope'] in {'unmatched-stem', 'unmatched-date'} and any(
                    a <= field['start'] < field['end'] <= b for a, b in concrete):
                continue
            if name in {'subject_token', 'name_token'} and any(
                field['start'] <= part['start'] < part['end'] <= field['end']
                and (name == 'name_token' or (field['start'], field['end']) != (part['start'], part['end']))
                for part in refinements
            ):
                continue
            if name == 'congress' and not is_valid_congress(field['raw']):
                continue
            add(name, field['raw'])
            add(name + '_code', field.get('code'))
            add(name + '_label', field.get('label'))
            for value in field.get('candidates', ()):
                add(name + '_candidates', value)
            if name == 'fiscal_year_token' and len(field['raw']) == 4:
                add('fiscal_year', field['raw'])
            if category := field.get('category'):
                if field['name'] != 'amendment_marker' and any(
                        a <= field['start'] < field['end'] <= b for a,b in target_spans):
                    add('target_document_kind', category)
                elif id(field) in primary_fields and category not in categories:
                    categories.append(category)
            if role := field.get('role'):
                if not role.endswith('bioguide_id') or (field['start'], field['end']) in bioguides:
                    # Keep the established enum casing regardless of whether
                    # strict parsing accepts the file. The raw field above is
                    # always unchanged, including spelling and punctuation.
                    value = (field['code'] or field['raw']).lower() if role in {'publication_type', 'measure_type'} else field['raw']
                    if role == 'meeting_type' or role.endswith('bioguide_id'):
                        value = value.upper()
                    add(role, value)
                    assigned_roles.add(role)
                    if role == 'witness_id' and (field['start'], field['end']) in bioguides:
                        add('witness_id_type', 'bioguide')
        types = [f for f in match['fields'] if f['name'] == 'measure_token']
        numbers = [f for f in match['fields'] if f['name'] == 'measure_number']
        if len(types) == len(numbers) == 1:
            add('measure_references', (types[0]['code'] or types[0]['raw']).lower() + (numbers[0]['raw'].lstrip('0') or '0'))

    for match in result.get('matches', ()) if convention_matches is None else convention_matches:
        if 'congress' in match['record'] and not is_valid_congress(match['record']['congress']):
            continue
        for name, value in match['record'].items():
            if name == 'references':
                for reference in value:
                    column = reference['type'].replace('-', '_') + '_references'
                    text = (reference['measureType'] + str(reference['measureNumber'])
                            if reference['type'] == 'measure' else reference['raw'])
                    add(column, text)
            else:
                column = 'document_kind' if name == 'kind' else re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
                # A literal refinement can be narrower than a valid record's
                # composite slot (079Rev1 -> amendment 079, revision 1).
                if column not in assigned_roles:
                    if column in {'measure_type', 'publication_type'} and isinstance(value, str):
                        value = value.lower()
                    add(column, value)

    # A measure list with a Rules Committee Print is a document family.
    # A lone measure reference followed by arbitrary text is only a reference.
    if row.get('measure_list') and any(token.upper() == 'RCP' for token in row.get('print_token', [])):
        categories.append('bill-measure-list')

    # A strict witness-support reading is more specific than its Wstate prefix.
    # Likewise, a known QFR/roster token improves a generic committee document.
    kinds = row.get('document_kind', [])
    if any(kind == 'published-report' or kind.startswith('conference-') for kind in [*kinds, *categories]):
        # A report-family prefix does not reclassify a known report component.
        categories = [category for category in categories if category != 'committee-report']
    if 'bill-numbered' in categories:
        # A padded number or separator is not descriptive title text. The
        # literal numbered grammar is narrower than a fallback strict layout.
        kinds = [k for k in kinds if k not in {'bill-numbered-described', 'bill-titled-draft'}]
        row['document_kind'] = kinds
    if categories and (not kinds or set(kinds) <= GENERIC_KINDS):
        row['document_kind'] = categories
    else:
        # Layout categories remain useful, but must not hide explicit document
        # wording. Avoid adding a generic category to its specific counterpart.
        for category in categories:
            if not any(kind == category or kind.endswith('-' + category)
                       or category == 'biography' and kind == 'witness-biography'
                       for kind in kinds):
                add('document_kind', category)
    if {'questions-for-record', 'response'} <= set(row.get('document_kind', [])):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'response']
        add('document_kind', 'questions-for-record-response')
    if 'questions-for-record-response' in row.get('document_kind', []):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'questions-for-record']
    if 'witness-support' in row.get('document_kind', []):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'witness-statement']
    if set(row.get('document_kind', [])) - EVENT_KINDS - GENERIC_KINDS:
        row['document_kind'] = [kind for kind in row['document_kind'] if kind not in EVENT_KINDS]
    elif 'business-meeting' in row.get('document_kind', []):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'nomination']
    if row.get('amendment_id') and not row.get('amendment_identifier'):
        row['amendment_identifier'] = list(row['amendment_id'])
    if families := document_families(row.get('document_kind')):
        row['document_family'] = families
    slot_kind, slot_ambiguous = filename_slot_info(observations, document_kinds=row.get('document_kind'))
    if slot_kind is not None:
        row['filename_slot_kind'] = [slot_kind]
        row['is_slot_ambiguous'] = ['true' if slot_ambiguous else 'false']
    return dict(row)
