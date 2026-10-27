"""Contract loading, shape validation, routing derivation, schema-copy authority."""
import copy
import json
from importlib import resources

import pytest

from news_lake.contract import (
    ContractError,
    KIND_TABLES,
    TABLE_MUTATIONS,
    load_jsonl,
    parse_jsonl,
    validate_shape,
)
from news_lake_test_support import DOCS, DOCS_FIXTURES, DOCS_SCHEMA


def test_fixture_file_loads_and_covers_every_kind():
    records = load_jsonl(DOCS_FIXTURES)
    assert len(records) == 16
    assert {record['kind'] for record in records} == set(KIND_TABLES)


def test_shipped_schema_copy_is_byte_identical_to_docs_authority():
    shipped = (resources.files('news_lake.contract') / 'schema' / 'news-lake.schema.json').read_bytes()
    assert shipped == DOCS_SCHEMA.read_bytes()


def _resolve(node, schema):
    if isinstance(node, dict) and '$ref' in node:
        return schema['$defs'].get(node['$ref'].split('/')[-1], {})
    return node


def _instant_property_names(node, schema):
    """Collect property names whose (ref-resolved) definition is a date-time string."""
    names = set()
    node = _resolve(node, schema)
    if not isinstance(node, dict):
        return names
    for name, child in node.get('properties', {}).items():
        child = _resolve(child, schema)
        if child.get('type') == 'string' and child.get('format') == 'date-time':
            names.add(name)
        names |= _instant_property_names(child, schema)
    for key in ('items', 'if', 'then', 'not', 'anyOf', 'oneOf', 'allOf'):
        value = node.get(key)
        if isinstance(value, dict):
            names |= _instant_property_names(value, schema)
        elif isinstance(value, list):
            for element in value:
                names |= _instant_property_names(element, schema)
    return names


def test_instant_keys_match_the_schema_authority():
    """Drift guard: INSTANT_KEYS is a hand-maintained projection of the schema's
    instant-typed property names (context.py must stay import-free, so the
    derivation lives here). A schema evolution adding or renaming a date-time
    field without updating INSTANT_KEYS would silently break replay dedup."""
    from news_lake.context import INSTANT_KEYS
    from news_lake.contract.records import SCHEMA

    schema_names = set()
    for definition in SCHEMA['$defs'].values():
        schema_names |= _instant_property_names(definition, SCHEMA)
    assert schema_names == set(INSTANT_KEYS)


def test_docs_checker_passes_and_matches_validation_report(capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location('docs_validate', DOCS / 'checks' / 'validate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    captured = capsys.readouterr().out.strip()
    expected = (DOCS / 'checks' / 'validation-report.txt').read_text(encoding='utf-8').strip()
    assert captured == expected


def test_routing_is_derived_from_schema_annotations():
    assert KIND_TABLES == {
        'outlet': 'news.outlets', 'capture': 'news.captures', 'discovery': 'news.discoveries',
        'item': 'news.items', 'version': 'news.versions', 'entity': 'news.entities',
        'identity_decision': 'news.identity_decisions', 'run': 'news.runs', 'mention': 'news.mentions',
        'classification': 'news.classifications', 'story': 'news.stories',
        'story_member': 'news.story_members', 'release': 'news.releases',
    }
    upsert = {table for table, mutation in TABLE_MUTATIONS.items() if mutation == 'upsert'}
    assert upsert == {'news.outlets', 'news.items', 'news.entities'}
    assert set(TABLE_MUTATIONS.values()) <= {'upsert', 'append'}


def test_parse_jsonl_rejects_non_finite_numbers():
    base = '{"kind":"classification","id":"24dcd59e-3917-5efa-9032-9b17f9de74a1"'
    for token in ('NaN', 'Infinity', '-Infinity'):
        with pytest.raises(ContractError) as raised:
            parse_jsonl(base + f',"value_number":{token},"dimension":"genre",'
            '"recorded_at":"2026-10-20T04:00:00Z","version_id":"24dcd59e-3917-5efa-9032-9b17f9de74a0",'
            '"run_id":"2fc0c4e4-b4d2-5c52-bd42-f4f5d7318e79","taxonomy_version":"fixture-1"}')
        assert raised.value.rule == 'non_finite_number'


def test_parse_jsonl_rejects_json_nulls():
    with pytest.raises(ContractError) as raised:
        parse_jsonl('{"kind":"item","id":null}')
    assert raised.value.rule == 'json_null'
    with pytest.raises(ContractError, match='json_null'):
        parse_jsonl('{"kind":"item","id":"24dcd59e-3917-5efa-9032-9b17f9de74a0",'
                    '"url_aliases":[null]}')
    with pytest.raises(ContractError, match='json_null'):
        parse_jsonl('{"kind":"version","id":"24dcd59e-3917-5efa-9032-9b17f9de74a0",'
                    '"publication":{"precision":null}}')


def test_parse_jsonl_rejects_duplicate_physical_ids(fixture_records):
    line = json.dumps(fixture_records[0])
    with pytest.raises(ContractError) as raised:
        parse_jsonl(line + '\n' + line)
    assert raised.value.rule == 'duplicate_record_id'
    assert raised.value.record_id == fixture_records[0]['id']


def test_parse_jsonl_rejects_broken_json():
    with pytest.raises(ContractError) as raised:
        parse_jsonl('{"kind":')
    assert raised.value.rule == 'json_syntax'


def base(fixture_records, kind):
    return copy.deepcopy(next(record for record in fixture_records if record['kind'] == kind))


@pytest.mark.parametrize('name,kind,mutation,rule', [
    ('unknown property', 'item', lambda r: r.update(unexpected=True), 'shape'),
    ('failed capture without error code', 'capture', lambda r: r.update(status='failed'), 'shape'),
    ('unknown kind', 'item', lambda r: r.update(kind='event'), 'shape'),
    ('explicit null field', 'item', lambda r: r.update(outlet_id=None), 'json_null'),
    ('nested null field', 'version', lambda r: r.update(publication={'precision': None}), 'json_null'),
    ('null inside array', 'item', lambda r: r.update(url_aliases=[None]), 'json_null'),
    ('invalid uuid', 'item', lambda r: r.update(id='not-a-uuid'), 'shape'),
    ('uppercase uuid', 'item', lambda r: r.update(id=r['id'].upper()), 'shape'),
    ('invalid calendar date', 'version', lambda r: r.update(publication={'precision': 'day', 'date': '2026-02-30', 'basis': 'publisher'}), 'shape'),
    ('local-time timestamp', 'item', lambda r: r.update(first_seen_at='2026-10-20T04:00:00'), 'shape'),
    ('offset timestamp', 'item', lambda r: r.update(first_seen_at='2026-10-20T04:00:00+02:00'), 'shape'),
    ('unknown date with invented timestamp', 'version', lambda r: r.update(publication={'precision': 'unknown', 'at': '2026-10-20T00:00:00Z'}), 'shape'),
    ('date precision with timestamp', 'version', lambda r: r.update(publication={'precision': 'day', 'date': '2026-10-20', 'basis': 'publisher', 'at': '2026-10-20T00:00:00Z'}), 'shape'),
    ('metadata-only body', 'version', lambda r: r.update(access='metadata_only'), 'shape'),
    ('unresolved mention with canonical entity', 'mention', lambda r: r.update(resolution='unresolved'), 'shape'),
    ('resolved mention without identity', 'mention', lambda r: r.pop('entity_id'), 'shape'),
    ('out-of-range confidence', 'mention', lambda r: r.update(identity_confidence=1.01), 'shape'),
    ('non-finite numeric score', 'mention', lambda r: r.update(identity_confidence=float('nan')), 'non_finite_number'),
    ('infinite numeric score', 'mention', lambda r: r.update(identity_confidence=float('inf')), 'non_finite_number'),
    ('two classification value types', 'classification', lambda r: r.update(value_boolean=True), 'shape'),
    ('failed run without reason', 'run', lambda r: r.update(status='failed'), 'shape'),
    ('skipped run without reason', 'run', lambda r: r.update(status='skipped'), 'shape'),
    ('non-person tenure', 'entity', lambda r: r.update(entity_type='place'), 'shape'),
    ('retraction with entity pair', 'identity_decision', lambda r: r.update(action='retract'), 'shape'),
    ('eleven snapshot entries', 'release', lambda r: r.update(snapshots=r['snapshots'][:11]), 'shape'),
    ('thirteen snapshot entries', 'release', lambda r: r['snapshots'].append(dict(r['snapshots'][0])), 'shape'),
    ('duplicate selection processor', 'release', lambda r: r['selections'].append(dict(r['selections'][0])), 'shape'),
    ('unknown snapshot table', 'release', lambda r: r['snapshots'][0].update(table='news.derived'), 'shape'),
    ('zero snapshot id', 'release', lambda r: r['snapshots'][0].update(snapshot_id='0'), 'shape'),
])
def test_shape_rejections(fixture_records, name, kind, mutation, rule):
    record = base(fixture_records, kind)
    mutation(record)
    with pytest.raises(ContractError) as raised:
        validate_shape(record)
    assert raised.value.rule == rule
    assert raised.value.record_id is None or isinstance(raised.value.record_id, str)


def test_validate_shape_accepts_only_named_evolved_fields(fixture_records):
    item = copy.deepcopy(next(record for record in fixture_records if record['kind'] == 'item'))
    item['pilot_note'] = 'verified'
    validate_shape(item, allowed_extra={'pilot_note'})
    with pytest.raises(ContractError) as rejected:
        validate_shape(item)
    assert rejected.value.rule == 'shape'


def test_positive_shape_variants(fixture_records):
    metadata = base(fixture_records, 'version')
    for key in ('text', 'text_hash', 'rights_basis'):
        metadata.pop(key)
    metadata.update(access='metadata_only', publication={'precision': 'unknown'})
    unresolved = base(fixture_records, 'mention')
    unresolved.pop('entity_id')
    unresolved.update(resolution='unresolved', aboutness='unknown')
    retraction = base(fixture_records, 'identity_decision')
    retraction.pop('left_id'), retraction.pop('right_id')
    retraction.update(action='retract', prior_decision_id=fixture_records[6]['id'])
    failed = base(fixture_records, 'run')
    failed.update(status='failed', reason='fixture failure')
    instant = base(fixture_records, 'version')
    instant.update(publication={'precision': 'instant', 'at': '2026-10-19T18:00:00.123456Z', 'basis': 'provider'})
    numeric = base(fixture_records, 'classification')
    numeric.pop('value_string')
    numeric.update(value_number=0.5)
    boolean = base(fixture_records, 'classification')
    boolean.pop('value_string')
    boolean.update(value_boolean=False)
    strings = base(fixture_records, 'classification')
    strings.pop('value_string')
    strings.update(value_strings=['policy', 'local'])
    for record in (metadata, unresolved, retraction, failed, instant, numeric, boolean, strings):
        validate_shape(record)
