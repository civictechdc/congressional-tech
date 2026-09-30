"""Inspect literal recurrence and text remaining within extraction results.

These helpers perform no I/O. Repeated tokens are syntax, not document types;
residual prose can be correct free text rather than a missing parsing rule.
"""
from __future__ import annotations

from copy import deepcopy
import re

from .errors import NamingError

WORD = re.compile(r'[^\W\d_]+')
CAMEL_BOUNDARY = r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])'
CAMEL_SPLIT = re.compile(CAMEL_BOUNDARY)
DESCRIPTIVE_FIELDS = frozenset({
    'payload', 'descriptor', 'suffix', 'subject_token', 'title_token',
    'context_token', 'recipient_token', 'annotation', 'name_token', 'target_subject',
    'local_identifier', 'measure_list', 'filer_token',
})


def audit_check(condition: bool, message: str, *, filename: str | None = None) -> None:
    """Acceptance checks must execute under both ordinary and optimized Python."""
    if not condition:
        details = [{'filename': filename}] if filename is not None else []
        raise NamingError('audit-failed', message, details)


def filename_tokens(result: dict) -> list[dict]:
    """Return whole words/numbers plus ASCII CamelCase parts before extensions.

    Unicode letters and source offsets are preserved. No stemming, synonym
    merging or guessed surname boundaries occurs.
    """
    tokens = []
    for piece in result['pieces']:
        if piece['start'] >= result['stem_end'] or piece['kind'] == 'separator':
            continue
        tokens.append(dict(piece))
        if piece['kind'] == 'word':
            start = piece['start']
            for part in CAMEL_SPLIT.split(piece['raw']):
                tokens.append({'kind': 'wordpart', 'raw': part, 'start': start, 'end': start + len(part)})
                start += len(part)
    return tokens


def shared_token_pattern(variants: tuple[str, ...], kind: str) -> str:
    """Build a case-sensitive regex for observed spellings at token boundaries."""
    if kind not in {'word', 'number', 'wordpart'}:
        raise NamingError('invalid-token-kind', f'Unsupported token kind: {kind}')
    token = re.compile('[0-9]+') if kind == 'number' else WORD
    if (isinstance(variants, (str, bytes)) or not variants
            or any(not isinstance(v, str) or not token.fullmatch(v) for v in variants)):
        raise NamingError('invalid-token-variants', 'Variants must be nonempty whole tokens of the requested kind')
    boundary = r'[0-9]' if kind == 'number' else r'[^\W\d_]'
    literals = '|'.join(re.escape(v) for v in sorted(set(variants), key=lambda value: (-len(value), value)))
    if kind == 'wordpart':
        return rf'(?:(?<!{boundary})|{CAMEL_BOUNDARY})(?P<token>{literals})(?:(?!{boundary})|{CAMEL_BOUNDARY})'
    return rf'(?<!{boundary})(?P<token>{literals})(?!{boundary})'


def residual_fields(result: dict, *, field_names=frozenset({'descriptor', 'suffix'}),
                    include_unstructured: bool = False) -> list[dict]:
    """Subtract specific source fields from broader text captures.

    Broad captures and fallback assumptions do not conceal unexplained text.
    A date or identifier counts as extracted syntax, not verified meaning.
    """
    name = result['input']
    matches = result['observations']
    excluded = DESCRIPTIVE_FIELDS | frozenset(field_names)
    def simple_identifier(field):
        return field['name'] in {'amendment_token', 'document_number'} and re.fullmatch(r'[0-9]+[A-Za-z]?', field['raw'])
    specific = [(m['rule'], f) for m in matches for f in m['fields']
                if not m['scope'].startswith('unmatched-') and (f['name'] not in excluded or simple_identifier(f)) and f['raw']
                and not (f['name'] == 'version_token' and f['candidates'] and not f['code'])]
    targets = [(m['rule'], f) for m in matches for f in m['fields']
               if f['name'] in field_names and f['raw']
               and not simple_identifier(f)]
    if include_unstructured and not any(m['scope'] == 'stem' for m in matches):
        targets.append(('unstructured-stem', {'name': 'unstructured_stem',
                        'raw': name[:result['stem_end']], 'start': 0, 'end': result['stem_end']}))
    rows = []
    for rule, field in targets:
        if field['name'] == 'payload' and any(m['scope'].endswith('-payload')
                and m['start'] == field['start'] and m['end'] == field['end'] for m in matches):
            continue
        covered = [(r, f) for r, f in specific if f['start'] < field['end'] and f['end'] > field['start']]
        intervals = sorted((max(field['start'], f['start']), min(field['end'], f['end'])) for _, f in covered)
        spans = []
        cursor = field['start']
        for start, end in [*intervals, (field['end'], field['end'])]:
            left, right = cursor, start
            while left < right and not name[left].isalnum():
                left += 1
            while right > left and not name[right - 1].isalnum():
                right -= 1
            if left < right:
                spans.append({'raw': name[left:right], 'start': left, 'end': right})
            cursor = max(cursor, end)
        source_positions = {i for i in range(field['start'], field['end']) if name[i].isalnum()}
        covered_positions = {i for a, b in intervals for i in range(a, b) if name[i].isalnum()}
        residual_positions = {i for span in spans for i in range(span['start'], span['end']) if name[i].isalnum()}
        audit_check(source_positions == covered_positions | residual_positions,
                    'Residual fields do not cover the original text.', filename=name)
        audit_check(not covered_positions & residual_positions,
                    'Covered and residual fields overlap.', filename=name)
        rows.append({'rule': rule, 'field': deepcopy(field),
                     'covered_by': [{'rule': r, 'field': deepcopy(f)} for r, f in covered],
                     'residual_spans': spans})
    return rows
