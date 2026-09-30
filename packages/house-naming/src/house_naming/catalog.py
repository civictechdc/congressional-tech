"""Offline catalog loading and integrity validation."""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import re
from typing import Any
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from .compiler import parts, record_schema, stem_pattern
from .errors import NamingError
from .io import loads


def _error(message: str) -> None:
    raise NamingError('invalid-catalog', message)


def _check_catalog(guide: dict[str, Any]) -> dict[str, int]:
    """Check structure plus every supported cross-reference and derived index.

    The guide is trusted executable configuration. This function is a consistency
    checker, not a sandbox for attacker-controlled regular expressions.
    """
    schema = loads(files('house_naming').joinpath('data').joinpath('guide.schema.json').read_bytes())
    errors = list(Draft202012Validator(schema).iter_errors(guide))
    if errors:
        first = errors[0]
        _error(f"Catalog schema violation at /{'/'.join(map(str, first.absolute_path))}: {first.message}")
    nodes, sections, examples = guide['source_nodes'], guide['sections'], guide['examples']
    extraction_ids = set()
    for rule in guide.get('extraction_rules', []):
        if rule['id'] in extraction_ids:
            _error(f"Duplicate extraction rule: {rule['id']}")
        extraction_ids.add(rule['id'])
        try:
            regex = re.compile(rule['pattern'], re.I | re.ASCII)
        except re.error as exc:
            _error(f"Bad extraction pattern {rule['id']}: {exc}")
        if not regex.groupindex:
            _error(f"Extraction pattern {rule['id']} has no named fields")
    for key, node in nodes.items():
        if node['section_id'] is not None and node['section_id'] not in sections:
            _error(f'Source {key} references an absent section')
    # All source-ref shapes are schema-controlled. No URI dereferencing occurs.
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if 'source_id' in value:
                target = nodes.get(value['source_id'])
                if target is None or target['page'] != value['page']:
                    _error(f"Missing source anchor or wrong page: {value['source_id']}")
            for key, item in value.items():
                if key in ('example_ids', 'source_example_ids'):
                    for target in item:
                        if target not in examples:
                            _error(f'Missing example: {target}')
                if key == 'footnote_ids':
                    for target in item:
                        if target not in guide['footnotes']:
                            _error(f'Missing footnote: {target}')
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(guide)
    expected_codes: dict[str, list[str]] = defaultdict(list)
    for context, entries in guide['codes'].items():
        for token, entry in entries.items():
            if token != entry['printed'].casefold():
                _error(f'Non-casefolded code key: {context}/{token}')
            expected_codes[token].append(context)
    if {k: sorted(v) for k, v in expected_codes.items()} != guide['code_index']:
        _error('code_index is not the exact inverse of codes')
    expected_examples: dict[str, list[str]] = defaultdict(list)
    for eid, example in examples.items():
        if example['value'] not in example['raw_text']:
            _error(f'{eid} is not an exact substring of its raw source paragraph')
        if example['section_id'] not in sections:
            _error(f'{eid} has no source section')
        expected_examples[example['value']].append(eid)
    if dict(expected_examples) != guide['example_index']:
        _error('example_index is not the exact inverse of examples')
    for key, committee in guide['committees'].items():
        if key != committee['folder_code']:
            _error(f'Committee key does not equal folder code: {key}')
    for key, section in sections.items():
        if key not in nodes:
            _error(f'Section {key} has no local text anchor')
        for sid in section['source_ids']:
            if sid not in nodes or nodes[sid]['section_id'] != key:
                _error(f'Section {key} has an invalid source membership')
        for child in section['child_ids']:
            if child not in sections or sections[child]['parent_id'] != key:
                _error(f'Section {key} has an invalid child link')
        parent = section['parent_id']
        if parent is not None and (parent not in sections or key not in sections[parent]['child_ids']):
            _error(f'Section {key} has an invalid parent link')
        visited = {key}
        while parent is not None:
            if parent in visited:
                _error('Section hierarchy contains a cycle')
            visited.add(parent)
            parent = sections[parent]['parent_id']
    for name, typ in guide['field_types'].items():
        Draft202012Validator.check_schema(typ)
        if 'default' in typ and not Draft202012Validator(typ).is_valid(typ['default']):
            _error(f'Invalid default for field type {name}')
        if 'pattern' in typ:
            try:
                re.compile(typ['pattern'])
            except re.error as exc:
                _error(f'Bad field pattern {name}: {exc}')

    enum_relationships = {
        'legislativeStage': ('version', False), 'measureTypeLower': ('measure', False),
        'measureTypePrinted': ('measure', True), 'meetingType': ('meeting', True),
        'appropriationStage': ('appropriation', True),
    }
    for typ, (context, printed) in enum_relationships.items():
        if context not in guide['codes'] or typ not in guide['field_types']:
            _error(f'Missing linked vocabulary/type: {context}/{typ}')
        expected = {e['printed'] if printed else k for k, e in guide['codes'][context].items()}
        if set(guide['field_types'][typ].get('enum', [])) != expected:
            _error(f'Field enum {typ} disagrees with code context {context}')
    types = guide['field_types']
    if 'pih' not in guide['codes']['consideration'] or set(types['untypedLegislativeStage']['enum']) != set(types['legislativeStage']['enum']) | {'pih'}:
        _error('Untyped stage values must match version codes plus the House PIH marker')
    for branch in types['references']['items']['oneOf']:
        for field, typ in [('measureType', 'measureTypeLower'), ('measureNumber', 'positiveInteger'), ('year', 'fiscalYear')]:
            if field in branch['properties'] and branch['properties'][field] != types[typ]:
                _error(f'Reference field {field} disagrees with shared type {typ}')
    for kind, rule in guide['patterns'].items():
        fields = rule['fields']
        if 'kind' in fields:
            _error('Reserved field present in catalog')
        if not set(rule['required']).issubset(fields):
            _error(f'{kind}: missing required field definitions')
        if any(t not in guide['field_types'] for t in fields.values()):
            _error(f'{kind}: unknown field type')
        Draft202012Validator.check_schema(record_schema(guide, kind))
        if rule['action'] == 'reference':
            if set(fields) != {'url'} or set(rule['required']) != {'url'}:
                _error('Reference rules must contain exactly a required url field')
            continue
        names = [name for _, name in parts(rule['stem_template']) if name]
        if len(names) != len(set(names)):
            _error(f'{kind}: repeated template field')
        derived = {'meetingSuffix'} if 'meetingSuffix' in names else set()
        calculated = set(rule.get('derived_fields', []))
        if not calculated.issubset(fields) or calculated.intersection(names):
            _error(f'{kind}: derived fields must be defined outside the filename template')
        target = rule.get('parse_as')
        if target is not None:
            if target == kind or target not in guide['patterns']:
                _error(f'{kind}: absent or self-referential parse target')
            if guide['patterns'][target]['action'] != 'filename' or 'parse_as' in guide['patterns'][target]:
                _error(f'{kind}: parse target must be a direct filename pattern')
        expected = set(fields) - {'extension', 'revision', 'meetingOccurrence'} - calculated
        if set(names) - derived != expected:
            _error(f'{kind}: template and field definitions disagree')
        defaulted = {name for name, typ in fields.items() if 'default' in guide['field_types'][typ]}
        if set(rule['required']) != (expected - defaulted) | {'extension'}:
            _error(f'{kind}: unexpected optional/required fields')
        if ('meetingSuffix' in names) != ('meetingOccurrence' in fields):
            _error(f'{kind}: meeting suffix has no matching occurrence field')
        extension = guide['field_types'][fields.get('extension', '')]
        if not extension.get('enum') or not all(re.fullmatch('[a-z]+', e) for e in extension['enum']) or fields.get('revision') != 'revision':
            _error(f'{kind}: unsupported finalizer types')
        if fields.get('meetingOccurrence', 'meetingOccurrence') != 'meetingOccurrence':
            _error(f'{kind}: unsupported meeting counter type')
        # One variable-length free-text capture per stem avoids a false promise
        # that two unconstrained delimited fields are uniquely separable.
        if sum(fields.get(n) in {'filenameToken', 'witnessId'} for n in names) > 1:
            _error(f'{kind}: multiple free-text stem fields are unsupported')
        try:
            re.compile(stem_pattern(guide, kind, capture=True))
            for template in rule.get('parse_templates', []):
                alternative = [name for _, name in parts(template) if name]
                if sorted(alternative) != sorted(names):
                    _error(f'{kind}: parse template must capture the same fields')
                re.compile(stem_pattern(guide, kind, capture=True, accept_case=True, template=template))
        except (re.error, ValueError) as exc:
            _error(f'{kind}: cannot compile template: {exc}')
    return {'patterns': len(guide['patterns']), 'source_examples': len(examples),
            'source_nodes': len(nodes),
            'committees': len(guide['committees']), 'code_entries': sum(map(len, guide['codes'].values()))}


def check_catalog(guide: dict[str, Any]) -> dict[str, int]:
    """Check a trusted catalog's closed schema, indices and references."""
    try:
        return _check_catalog(guide)
    except NamingError:
        raise
    except (ValueError, TypeError, KeyError, SchemaError) as exc:
        raise NamingError('invalid-catalog', f'Invalid catalog configuration: {exc}') from exc


@lru_cache(maxsize=1)
def _bundled() -> dict[str, Any]:
    base = files('house_naming').joinpath('data')
    guide = loads(base.joinpath('guide.json').read_bytes())
    check_catalog(guide)
    return guide


def load_guide() -> dict[str, Any]:
    """Return an independent mutable copy of the validated, bundled catalog."""
    return deepcopy(_bundled())
