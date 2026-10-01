"""Useful filename values, independent of strict convention validation or storage.

The catalog assigns categories and field roles. This module collects those
readings; it does not parse names, resolve people, or combine different sources.
"""
from __future__ import annotations

from collections import defaultdict
import re

from .metadata import target_subject_spans

OMIT_FIELDS = frozenset({'payload', 'query_text', 'ignored_suffix', 'protocol_marker'})
GENERIC_KINDS = frozenset({'committee-document', 'committee-document-numbered'})


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
    bill_descriptions = [(f['start'],f['end']) for m in observations for f in m['fields']
                         if (m.get('scope') == 'legislative-payload' and f['name'] in {'descriptor', 'suffix'})
                         or (m.get('scope') == 'legislative-text-search' and f['name'] == 'description')]

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
            add(name, field['raw'])
            add(name + '_code', field.get('code'))
            add(name + '_label', field.get('label'))
            for value in field.get('candidates', ()):
                add(name + '_candidates', value)
            if name == 'fiscal_year_token' and len(field['raw']) == 4:
                add('fiscal_year', field['raw'])
            if category := field.get('category'):
                if category == 'biography' and any(
                        a <= field['start'] < field['end'] < b for a,b in bill_descriptions):
                    pass  # Bio inside a bill title does not describe this file.
                elif field['name'] != 'amendment_marker' and any(
                        a <= field['start'] < field['end'] <= b for a,b in target_spans):
                    add('target_document_kind', category)
                elif category not in categories:
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
    if 'questions-for-record-response' in row.get('document_kind', []):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'questions-for-record']
    if 'witness-support' in row.get('document_kind', []):
        row['document_kind'] = [kind for kind in row['document_kind'] if kind != 'witness-statement']
    if row.get('amendment_id') and not row.get('amendment_identifier'):
        row['amendment_identifier'] = list(row['amendment_id'])
    return dict(row)
