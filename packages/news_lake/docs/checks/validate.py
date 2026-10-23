#!/usr/bin/env python3
"""Offline packet checks; NOT a provider integration or full Iceberg conformance test.

Run from any directory: python /path/to/checks/validate.py
Requires jsonschema with UUID/URI/date/date-time format checking.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:
    raise SystemExit('Missing dependency: install jsonschema before running this checker.') from exc

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schema/news-lake.schema.json').read_text())
FORMATS = FormatChecker()
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FORMATS)
TABLES = {
    k: definition['x-iceberg']['table']
    for k, definition in SCHEMA['$defs'].items() if 'x-iceberg' in definition
}
EXPECTED_TABLES = set(TABLES.values()) - {'news.releases'}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


from news_lake.contract.records import ContractError, validate_shape
from news_lake.contract.semantics import check_corpus


def shape(record: dict[str, Any]) -> None:
    try:
        validate_shape(record)
    except ContractError as exc:
        raise ValueError(f"Invalid {record.get('kind')}: {exc}") from exc


def corpus(records: list[dict[str, Any]]) -> None:
    """Check local semantic invariants via canonical contract checker."""
    try:
        check_corpus(records)
    except ContractError as exc:
        raise ValueError(str(exc)) from exc


def reject(test, value: Any, name: str) -> str:
    try:
        test(value)
    except ValueError:
        return f'PASS reject: {name}'
    raise ValueError(f'Unexpected acceptance: {name}')


def main() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    fixtures = [json.loads(line) for line in (ROOT / 'examples/records.jsonl').read_text().splitlines() if line]
    corpus(fixtures)
    kinds = {row['kind'] for row in fixtures}
    require(kinds == set(TABLES), 'Fixture set does not cover every record kind')
    base = {kind: next(row for row in fixtures if row['kind'] == kind) for kind in kinds}
    lines = [f'jsonschema {version("jsonschema")}', 'PASS schema: Draft 2020-12 metaschema',
             f'PASS fixtures: {len(fixtures)} records / {len(kinds)} record kinds',
             'PASS local references, output inputs, text hashes, offsets, intervals and release structure']

    def changed(record_kind: str, **updates: Any) -> dict[str, Any]:
        return {**copy.deepcopy(base[record_kind]), **updates}

    invalid = [
        ('unknown property', changed('item', unexpected=True)),
        ('failed capture without error code', changed('capture', status='failed')),
        ('non-finite numeric score', changed('mention', identity_confidence=float('nan'))),
        ('unknown kind', changed('item', kind='event')),
        ('explicit null', changed('item', outlet_id=None)),
        ('invalid UUID', changed('item', id='not-a-uuid')),
        ('invalid calendar date', changed('version', publication={'precision':'day','date':'2026-02-30','basis':'publisher'})),
        ('local-time timestamp', changed('item', first_seen_at='2026-10-20T04:00:00')),
        ('unknown date with invented timestamp', changed('version', publication={'precision':'unknown','at':'2026-10-20T00:00:00Z'})),
        ('date precision with timestamp', changed('version', publication={'precision':'day','date':'2026-10-20','basis':'publisher','at':'2026-10-20T00:00:00Z'})),
        ('metadata-only body', changed('version', access='metadata_only')),
        ('unresolved mention with canonical entity', changed('mention', resolution='unresolved')),
        ('out-of-range confidence', changed('mention', identity_confidence=1.01)),
        ('two classification value types', changed('classification', value_boolean=True)),
        ('failed run without reason', changed('run', status='failed')),
        ('non-person tenure', changed('entity', entity_type='place')),
        ('retraction with entity pair', changed('identity_decision', action='retract')),
    ]
    resolved = changed('mention'); resolved.pop('entity_id')
    invalid.append(('resolved mention without identity', resolved))
    for name, record in invalid:
        lines.append(reject(shape, record, name))

    # Positive shape variations make the tagged variants usable, not only restrictive.
    metadata = changed('version', access='metadata_only', publication={'precision':'unknown'})
    for key in ('text','text_hash','rights_basis'): metadata.pop(key, None)
    unresolved = changed('mention', resolution='unresolved', aboutness='unknown')
    unresolved.pop('entity_id')
    retraction = changed('identity_decision', action='retract', prior_decision_id=base['identity_decision']['id'])
    retraction.pop('left_id'); retraction.pop('right_id')
    variants = [metadata, unresolved, retraction,
                changed('run', status='failed', reason='fixture failure'),
                changed('version', publication={'precision':'instant','at':'2026-10-19T18:00:00.123456Z','basis':'provider'})]
    for slot, value in [('value_number', 0.5), ('value_boolean', False), ('value_strings', ['policy','local'])]:
        variant = changed('classification', **{slot:value})
        variant.pop('value_string'); variants.append(variant)
    for variant in variants: shape(variant)
    lines.append(f'PASS alternative shapes: {len(variants)}')

    def corpus_change(kind: str, **updates: Any) -> list[dict[str, Any]]:
        result = copy.deepcopy(fixtures)
        index = next(i for i, row in enumerate(result) if row['kind'] == kind)
        result[index].update(updates)
        return result

    semantic_cases = [
        ('duplicate physical ID', fixtures + [copy.deepcopy(fixtures[0])]),
        ('missing foreign key', corpus_change('mention', entity_id='00000000-0000-0000-0000-000000000001')),
        ('wrong text hash', corpus_change('version', text_hash='0'*64)),
        ('span beyond document', corpus_change('mention', occurrences=[{'field':'title','start':0,'end':1000}])),
        ('span surface mismatch', corpus_change('mention', surface='Someone Else')),
        ('inverted run times', corpus_change('run', finished_at='2026-10-19T00:00:00Z')),
        ('cyclic item redirect', corpus_change('item', superseded_by=base['item']['id'])),
        ('wrong-kind reference', corpus_change('mention', entity_id=base['item']['id'])),
    ]
    for name, records in semantic_cases:
        lines.append(reject(corpus, records, name))

    lines += [
        f'SUMMARY: {len(fixtures)} fixture records; {len(variants)} positive variants; '
        f'{len(invalid)} shape rejections; {len(semantic_cases)} local semantic rejections.',
        'NOT RUN: provider APIs, real raw-object checks, Iceberg/catalog writes or snapshot reads,',
        'fault injection, identifier-conflict/retraction graph evaluation, selection/view execution,',
        'access/retention enforcement, schema-evolution round trips, throughput or coverage benchmarks.',
        'Fixture URLs, object URIs, people, hashes and snapshot references are illustrative, not deployed resources.'
    ]
    print('\n'.join(lines))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
