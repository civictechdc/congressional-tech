"""Compile and validate the literal reader's catalog references before use."""
from __future__ import annotations

import re

from .errors import NamingError


# These are algorithm inputs, not filename rule IDs. The catalog supplies the
# rule for each role; changing a rule's ID does not change its behavior.
ROLE_INPUTS = {
    'separated_date': ('search', {'date_token'}),
    'measure': ('search', {'measure_number', 'measure_token'}),
    'support': ('document-wording-search', {'relation_wording'}),
    'qualifier': ('document-wording-search', {'qualifier_wording'}),
    'label_number': ('document-wording-search', {'local_number_token'}),
    'substitute_target': ('legislative-subject-search', {'target_subject'}),
    'numeric_report_subject': ('report-text-search', {'report_subject_token'}),
    'short_measure': ('legislative-subject-search', {'measure_number', 'measure_token'}),
    'print_prefix': ('search', set()),
    'degree': ('search', {'degree_token'}),
    'statement_label': ('search', {'label'}),
    'report_part': ('report-text-search', {'part_number', 'part_marker'}),
    'generic_part': ('search', set()),
    'descriptive_substitute': ('legislative-text-search', set()),
    'substitute_marker': ('legislative-subject-search', set()),
}
PROCESSOR_INPUTS = {
    'numeric-date': set(),
    'measure-context': set(),
    'congress-ordinal': {'referenced_congress'},
    'malformed-date': {'date_token'},
    'fiscal-year': {'fiscal_year_token'},
    'inferred-version': {'version_token'},
    'week-start': {'date_token'},
    'partial-date': {'partial_month_token', 'partial_date_token', 'partial_year_token'},
    'possible-month-day': {'possible_month_day_token'},
    'month-year': {'month_token', 'year_token'},
    'complete-date-token': {'date_token'},
    'publication-components': {'suffix'},
    'numeric-subject-parts': {'payload'},
    'capitalized-label-boundary': {'label'},
    'following-degree': {'local_number_token'},
    'between-degrees': {'target_subject'},
    'leading-date-label': {'label'},
    'revision-date': {'revision_marker', 'revision_number'},
    'subject-remainder': {'subject_token'},
    'report-description': {'payload'},
    'description-remainder': {'description'},
    'suffix-only-fallback': {'ignored_suffix'},
    'atomic-identifier': set(),
    'ascii-left-boundary': set(),
    'avoid-ordinal-tail': set(),
    'companion-context': {'document_abbreviation'},
    'heading-abbreviation': {'meeting_abbreviation'},
    'amendment-label-boundary': {'label'},
}
PATTERN_INPUTS = {
    'separated_version': {'version_token', 'version_number_token', 'annotation', 'suffix'},
    'joined_measures': {'measure_token', 'measure_number'},
    'filer_member': {'member_marker', 'name_token'},
}


def _fail(message):
    raise NamingError('invalid-catalog', message)


def compile_pattern(guide, name):
    spec = guide.get('extraction_patterns', {}).get(name)
    if spec is None:
        _fail(f'Missing extraction pattern: {name}')
    pattern = spec['pattern']
    for key, vocabulary in spec.get('vocabularies', {}).items():
        context = vocabulary['context']
        if context not in guide['codes'] or '{' + key + '}' not in pattern:
            _fail(f'Invalid vocabulary expansion in extraction pattern {name}')
        tokens = [*guide['codes'][context], *vocabulary.get('extra', ())]
        pattern = pattern.replace('{' + key + '}', '|'.join(re.escape(v) for v in sorted(tokens, key=len, reverse=True)))
    try:
        return re.compile(pattern, re.ASCII | (re.I if spec.get('ignore_case', True) else 0))
    except re.error as exc:
        _fail(f'Bad extraction pattern {name}: {exc}')


def bind_extraction_rules(guide):
    """Reject missing captures, unknown operations and invalid refinement routes."""
    def check_reading(reading):
        if 'house_context' in reading:
            context, token = reading['house_context'], reading.get('house_token')
            if token not in guide['codes'].get(context, {}):
                _fail(f'Unknown House vocabulary reference: {context}/{token}')

    def check_lookups(lookups, fields, rid):
        for lookup in lookups:
            vocab = lookup['vocabulary']
            if not (vocab in guide.get('extraction_vocabularies', {})
                    or vocab.startswith('house:') and vocab[6:] in guide['codes']):
                _fail(f'Unknown extraction vocabulary in {rid}: {vocab}')
            if lookup.get('normalize') not in {None, 'words', 'first-word', 'letters'}:
                _fail(f'Unknown vocabulary normalization in {rid}')
            if 'from' in lookup and lookup['from'] not in fields:
                _fail(f'Vocabulary lookup in {rid} references absent capture {lookup["from"]}')

    for entries in guide.get('extraction_vocabularies', {}).values():
        for token, reading in entries.items():
            if token != token.lower():
                _fail(f'Extraction vocabulary key is not lowercase: {token}')
            check_reading(reading)
    bound = {}
    for rule in guide.get('extraction_rules', ()):
        rid, scope = rule['id'], rule['scope']
        if rid in bound:
            _fail(f'Duplicate extraction rule: {rid}')
        try:
            regex = re.compile(rule['pattern'], re.I | re.ASCII)
        except re.error as exc:
            _fail(f'Bad extraction pattern {rid}: {exc}')
        fields = set(regex.groupindex)
        if not fields:
            _fail(f'Extraction pattern {rid} has no named fields')
        required = set(rule.get('field_readings', {})) | set(rule.get('field_vocabularies', {}))
        generated = {'subject_token', 'target_subject'} if guide.get('extraction_roles', {}).get('support') == rid else set()
        required.update(set(rule.get('searchable_fields', ())) - generated)
        if 'label' in rule:
            required.add('label')
        if rule.get('reserve') and rule['reserve'] != 'match':
            required.add(rule['reserve'])
        if rule.get('reference_number'):
            required.add(rule['reference_number'])
        for option in ('version_boundary_field', 'roster_congress', 'reserve_field'):
            if option in rule:
                required.add(rule[option])
        if rule.get('ordinal_tail') and rule['ordinal_tail'] != '$after':
            required.add(rule['ordinal_tail'])
        if rule.get('ordinal_tail'):
            required.add('measure_number')
        required.update(rule.get('capture_rules', {}))
        if rule.get('payload_scope'):
            required.add('payload')
            if scope != 'stem' or rule['payload_scope'] not in {
                'committee-payload', 'legislative-payload', 'descriptive-payload'
            }:
                _fail(f'Invalid payload route in {rid}')
        if rule.get('unique_label') or rule.get('qualifier_anchor'):
            required.add('label')
        for processor in rule.get('processors', ()):
            if processor not in PROCESSOR_INPUTS:
                _fail(f'Unknown extraction processor {processor} in {rid}')
            required.update(PROCESSOR_INPUTS[processor])
            if processor == 'numeric-date' and not fields & {'date_token', 'short_date_token'}:
                _fail(f'Numeric date processor in {rid} requires a date capture')
        for reading in rule.get('field_readings', {}).values():
            check_reading(reading)
        for lookups in rule.get('field_vocabularies', {}).values():
            check_lookups(lookups, fields, rid)
        if scope == 'unmatched-date':
            required.add('date_token')
        if scope == 'published-suffix-search':
            required.update({'publication_marker', 'publication_identifier'})
        if 'revision_marker' in fields:
            required.add('revision_number')
        if fields & {'start_day_token', 'end_day_token'}:
            required.update({'month_token', 'year_token', 'start_day_token', 'end_day_token'})
        for route in rule.get('refine', ()):
            if route.get('stage') not in {'before-search', 'local-reference', 'fields', 'match', 'scopes', 'targets', 'supplemental'}:
                _fail(f'Unknown refinement stage in {rid}')
            if route.get('mode') not in {'match', 'fullmatch', 'search'}:
                _fail(f'Unknown refinement mode in {rid}')
            if route['field'] != '$match':
                required.add(route['field'])
            if (route['field'] == '$match') != (route['stage'] == 'match'):
                _fail(f'Whole-match refinement in {rid} requires the match stage')
            if 'when' in route:
                required.add(route['when']['field'])
                if any(value != value.lower() for value in route['when']['values']):
                    _fail(f'Refinement condition in {rid} requires lowercase values')
        if not required <= fields:
            _fail(f'Extraction rule {rid} references absent captures {sorted(required - fields)}')
        qualified = bool(rule.get('source_hosts') or rule.get('source_urls'))
        if (scope == 'source-stem') != qualified:
            _fail(f'Extraction rule {rid} requires source qualifiers exactly for source-stem scope')
        priorities = ((0, 1, 2) if scope == 'stem' else (0, 1, 2, 3)
                      if scope in {'committee-payload', 'legislative-payload'} else (0,))
        if rule['priority'] not in priorities:
            _fail(f'Unsupported priority {rule["priority"]} for {scope} rule {rid}')
        bound[rid] = rule, regex
    if not bound:
        _fail('Missing extraction rules')
    for role, (scope, captures) in ROLE_INPUTS.items():
        rid = guide.get('extraction_roles', {}).get(role)
        if rid not in bound:
            _fail(f'Missing extraction role {role}: {rid}')
        rule, regex = bound[rid]
        if rule['scope'] != scope or not captures <= regex.groupindex.keys():
            _fail(f'Extraction role {role} requires scope {scope} and captures {sorted(captures)}')
    for role, rid in guide.get('extraction_roles', {}).items():
        if role not in ROLE_INPUTS or rid not in bound:
            _fail(f'Unknown extraction role or rule: {role}/{rid}')
    graph = {rid: set() for rid in bound}
    for rid, (rule, _) in bound.items():
        for children in rule.get('capture_rules', {}).values():
            if not children or not set(children) <= bound.keys():
                _fail(f'Invalid capture replacement in {rid}')
            graph[rid].update(children)
        components = rule.get('publication_components', {})
        if components:
            if 'publication-components' not in rule.get('processors', ()):
                _fail(f'Publication options in {rid} require the publication-components processor')
            check_reading(components.get('reading', {}))
            component_fields = set().union(*(set(rx.groupindex) for child, rx in bound.values()
                                           if child['scope'] == 'published-suffix-search'))
            for field, lookups in components.get('field_vocabularies', {}).items():
                if field not in component_fields:
                    _fail(f'Publication reading in {rid} references absent capture {field}')
                check_lookups(lookups, component_fields, rid)
        for route in rule.get('refine', ()):
            children = set(route.get('rules', ())) if 'rules' in route else {
                key for key, (child, _) in bound.items() if child['scope'] == route['scope']
                and not (route['stage'] == 'scopes' and child.get('whole_slot_only'))}
            if not children or not children <= bound.keys():
                _fail(f'Invalid child rules in {rid}: {sorted(children - bound.keys())}')
            if not (set(route.get('search_rules', ())) | set(route.get('trim_for', {}))) <= children:
                _fail(f'Refinement options reference unselected children in {rid}')
            graph[rid].update(children)
    visited, pending = set(), set()

    def visit(rid):
        if rid in pending:
            _fail(f'Recursive extraction refinement at {rid}')
        if rid in visited:
            return
        pending.add(rid)
        for child in graph[rid]:
            visit(child)
        pending.remove(rid)
        visited.add(rid)

    for rid in graph:
        visit(rid)
    for name, fields in PATTERN_INPUTS.items():
        if not fields <= compile_pattern(guide, name).groupindex.keys():
            _fail(f'Extraction pattern {name} requires captures {sorted(fields)}')
    return bound
