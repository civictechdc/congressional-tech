"""Compile the trusted JSON catalog into validators and exact stem matchers.

The only template syntax is {fieldName}; no expressions, formatting directives,
attribute access, external references, or arbitrary code are supported.
"""
from __future__ import annotations
from copy import deepcopy
import re
from string import Formatter
from typing import Any

DRAFT = "https://json-schema.org/draft/2020-12/schema"
END = r"$(?![\s\S])"

def escape_literal(value: str) -> str:
    # Escape only regex metacharacters; Python re.escape also escapes '-' and
    # spaces, which are invalid identity escapes in ECMAScript Unicode mode.
    return re.sub(r'([.*+?^${}()|\[\]\\])', r'\\\1', value)

def parts(template: str) -> list[tuple[str, str | None]]:
    output = []
    for literal, name, spec, conversion in Formatter().parse(template):
        if name is not None and (not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name) or spec or conversion):
            raise ValueError("Templates permit only simple {fieldName} placeholders")
        output.append((literal, name))
    return output

def field_schema(guide: dict[str, Any], rule: dict[str, Any], field: str) -> dict[str, Any]:
    return deepcopy(guide['field_types'][rule['fields'][field]])

def record_schema(guide: dict[str, Any], kind: str) -> dict[str, Any]:
    rule = guide['patterns'][kind]
    return {
        '$schema': DRAFT, 'title': rule['title'], 'type': 'object',
        'additionalProperties': False, 'required': ['kind', *rule['required']],
        'properties': {'kind': {'type': 'string', 'const': kind},
                       **{k: field_schema(guide, rule, k) for k in rule['fields']}},
    }

def records_schema(guide: dict[str, Any]) -> dict[str, Any]:
    """One standalone schema for every kind; all references are local."""
    defs = {'field_' + name: deepcopy(schema) for name, schema in guide['field_types'].items()}
    for kind, rule in guide['patterns'].items():
        schema = record_schema(guide, kind)
        schema.pop('$schema')
        for field, typ in rule['fields'].items():
            schema['properties'][field] = {'$ref': '#/$defs/field_' + typ}
        defs['rule_' + kind] = schema
    return {
        '$schema': DRAFT, '$id': 'urn:house-naming:record',
        'title': 'House and GPO filename metadata records',
        'description': 'Guide conventions and observed filename layouts. Metadata validation only; calendar dates, URL structure and UTF-8 filename length also require the runtime. This is not certification of current House requirements.',
        'oneOf': [{'$ref': '#/$defs/rule_' + k} for k in guide['patterns']], '$defs': defs,
    }

def literal_pattern(value: str, *, accept_case: bool) -> str:
    return ''.join(f'[{c.lower()}{c.upper()}]' if accept_case and c.isascii() and c.isalpha()
                   else escape_literal(c) for c in value)


def lexeme(schema: dict[str, Any], *, accept_case: bool = False) -> str:
    """Pattern for a single lexeme; final schema validation also enforces bounds."""
    values = schema.get('enum')
    if 'const' in schema:
        values = [schema['const']]
    if values is not None:
        vals = sorted({str(x) for x in values}, key=lambda x: (-len(x), x))
        return '(?:' + '|'.join(literal_pattern(x, accept_case=accept_case) for x in vals) + ')'
    if schema['type'] == 'integer':
        minimum, maximum = schema.get('minimum'), schema.get('maximum')
        if minimum is not None and maximum is not None and minimum > 0 and len(str(minimum)) == len(str(maximum)):
            # Observed incomplete BILLS names join a three-digit Congress to
            # an untyped number. Their split must not depend on regex greediness.
            return r'[1-9][0-9]{' + str(len(str(minimum)) - 1) + '}'
        return r'(?:0|[1-9][0-9]{0,9})'
    pattern = schema.get('pattern')
    if pattern:
        if accept_case:
            pattern = pattern.replace('[A-Z]', '[A-Za-z]')
        if not pattern.startswith('^'):
            raise ValueError('A field pattern must be explicitly start-anchored')
        if pattern.endswith(END):
            return '(?:' + pattern[1:-len(END)] + ')'
        if pattern.endswith('$'):
            return '(?:' + pattern[1:-1] + ')'
        raise ValueError('A field pattern must be explicitly end-anchored')
    raise ValueError('Filename fields require an enum, const, integer type, or anchored pattern')

def stem_pattern(guide: dict[str, Any], kind: str, *, capture: bool,
                 accept_case: bool = False, template: str | None = None) -> str:
    rule = guide['patterns'][kind]
    out = []
    for literal, name in parts(template or rule['stem_template']):
        out.append(literal_pattern(literal, accept_case=accept_case))
        if name is None:
            continue
        if name == 'meetingSuffix':
            group = '(?P<meetingOccurrence>[1-9][0-9]{0,9})' if capture else r'[1-9][0-9]{0,9}'
            out.append('(?:-' + group + ')?')
        else:
            atom = lexeme(field_schema(guide, rule, name), accept_case=accept_case)
            out.append(f'(?P<{name}>{atom})' if capture else atom)
    return ''.join(out)

def filename_schema(guide: dict[str, Any]) -> dict[str, Any]:
    defs = {}
    for kind in guide['patterns']:
        if guide['patterns'][kind]['action'] != 'filename':
            continue
        # This portable schema is intentionally lexical, not a parser or a full
        # substitute for record validation and calendar/byte-length checks.
        rule = guide['patterns'][kind]
        stems = [stem_pattern(guide, kind, capture=False, accept_case=True, template=t)
                 for t in [rule['stem_template'], *rule.get('parse_templates', [])]]
        extension = lexeme(field_schema(guide, rule, 'extension'), accept_case=True)
        regex = '^(?:' + '|'.join(stems) + r')(?:-[Uu][1-9][0-9]{0,9})?\.' + extension + END
        defs[kind] = {'type': 'string', 'maxLength': 255, 'pattern': regex}
    return {'$schema': DRAFT, '$id': 'urn:house-naming:filename-lexical',
        'title': 'House and GPO lexical filename candidate schema',
        'description': 'A candidate filter only. May accept impossible dates, out-of-range counters or a generic-description overlap. Use Engine.parse for full runtime validation. Returns validity, not parsed fields or a unique classification.',
        'type': 'string', 'maxLength': 255,
        'anyOf': [{'$ref': '#/$defs/' + k} for k in defs], '$defs': defs}
