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


def shape(record: dict[str, Any]) -> None:
    def finite(value: Any) -> None:
        if isinstance(value, float):
            require(math.isfinite(value), 'Non-finite JSON number')
        elif isinstance(value, dict):
            for child in value.values(): finite(child)
        elif isinstance(value, list):
            for child in value: finite(child)
    finite(record)
    errors = list(VALIDATOR.iter_errors(record))
    require(not errors, f"Invalid {record.get('kind')}: {errors[0].message if errors else ''}")


def corpus(records: list[dict[str, Any]]) -> None:
    """Check a deliberately limited subset of local semantic invariants."""
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        shape(record)
        require(record['id'] not in by_id, 'Duplicate record ID in the candidate snapshot')
        by_id[record['id']] = record

    def get(identifier: str, kind: str) -> dict[str, Any]:
        require(identifier in by_id, f'Missing {kind} reference')
        result = by_id[identifier]
        require(result['kind'] == kind, f'Wrong reference kind: expected {kind}')
        return result

    def run_input(record: dict[str, Any], kind: str, identifier: str) -> None:
        run = get(record['run_id'], 'run')
        require(run['status'] == 'succeeded', 'Output points to a non-successful run')
        require({'kind':kind, 'id':identifier} in run['inputs'], 'Output input absent from run')

    fk = {
        'outlet_id':'outlet', 'capture_id':'capture', 'item_id':'item', 'run_id':'run',
        'version_id':'version', 'current_version_id':'version', 'superseded_by':'item',
        'entity_id':'entity', 'target_entity_id':'entity', 'left_id':'entity',
        'right_id':'entity', 'prior_decision_id':'identity_decision', 'story_id':'story'
    }
    memberships: set[tuple[str, str]] = set()
    for record in records:
        for field, kind in fk.items():
            if field in record:
                get(record[field], kind)
        kind = record['kind']
        if kind == 'item':
            if 'current_version_id' in record:
                require(get(record['current_version_id'], 'version')['item_id'] == record['id'],
                        'Current version belongs to another item')
            seen: set[str] = set()
            node = record
            while 'superseded_by' in node:
                require(node['id'] not in seen, 'Cyclic item redirect')
                seen.add(node['id'])
                node = get(node['superseded_by'], 'item')
        elif kind == 'entity':
            for field in ('tenures', 'affiliations'):
                for interval in record.get(field, []):
                    if 'from' in interval and 'to' in interval:
                        require(interval['from'] < interval['to'], 'Invalid dated interval')
        elif kind == 'identity_decision':
            if 'left_id' in record:
                require(record['left_id'] != record['right_id'], 'Reflexive identity decision')
            for identifier in record.get('evidence_capture_ids', []):
                get(identifier, 'capture')
        elif kind == 'run':
            for input_ref in record['inputs']:
                get(input_ref['id'], input_ref['kind'])
            start = datetime.fromisoformat(record['started_at'].replace('Z', '+00:00'))
            finish = datetime.fromisoformat(record['finished_at'].replace('Z', '+00:00'))
            require(start <= finish, 'Run finishes before it starts')
        elif kind == 'version':
            run_input(record, 'capture', record['capture_id'])
            if 'text' in record:
                actual = hashlib.sha256(record['text'].encode('utf-8')).hexdigest()
                require(actual == record['text_hash'], 'Text hash mismatch')
        elif kind in ('mention', 'classification'):
            run_input(record, 'version', record['version_id'])
            if kind == 'mention':
                source = get(record['version_id'], 'version')
                for span in record['occurrences']:
                    require(span['field'] in source, 'Mention references absent text field')
                    text = source[span['field']]
                    require(0 <= span['start'] < span['end'] <= len(text), 'Span out of bounds')
                    require(text[span['start']:span['end']] == record['surface'], 'Surface mismatch')
        elif kind == 'story':
            require(get(record['run_id'], 'run')['status'] == 'succeeded', 'Failed story run')
        elif kind == 'story_member':
            run_input(record, 'version', record['version_id'])
            require(get(record['story_id'], 'story')['run_id'] == record['run_id'], 'Story/member run mismatch')
            key = (record['run_id'], record['version_id'])
            require(key not in memberships, 'Multiple memberships in one clustering run')
            memberships.add(key)
        elif kind == 'release':
            names = [entry['table'] for entry in record['snapshots']]
            require(len(names) == len(set(names)) and set(names) == EXPECTED_TABLES,
                    'Release snapshot table set is incomplete or duplicated')
            for entry in record['snapshots']:
                if 'snapshot_id' in entry:
                    require(0 < int(entry['snapshot_id']) <= 9223372036854775807,
                            'Snapshot ID exceeds signed 64-bit range')
            processors = [entry['processor'] for entry in record['selections']]
            require(len(processors) == len(set(processors)), 'Multiple selections for one processor')


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
