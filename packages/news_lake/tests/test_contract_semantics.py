"""Corpus semantics (C7 local invariants): positive fixtures and rejections."""
import copy

import pytest

from news_lake.contract import ContractError, check_corpus


def by_kind(records, kind):
    return next(record for record in records if record['kind'] == kind)


def corpus(fixture_records):
    return copy.deepcopy([r for r in fixture_records if r['kind'] != 'release'])


def reject_case(records, rule, record_id):
    with pytest.raises(ContractError) as raised:
        check_corpus(records)
    assert raised.value.rule == rule
    assert raised.value.record_id == record_id


def test_fixture_corpus_passes(fixture_records):
    check_corpus(copy.deepcopy(fixture_records))


def test_two_cycle_corpus_passes(fixture_records, second_batch):
    check_corpus(corpus(fixture_records) + copy.deepcopy(second_batch))


def test_duplicate_physical_id_fails(fixture_records):
    records = copy.deepcopy(fixture_records) + [copy.deepcopy(fixture_records[0])]
    reject_case(records, 'duplicate_record_id', fixture_records[0]['id'])


def test_missing_foreign_key_fails(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'mention')['entity_id'] = '00000000-0000-0000-0000-000000000001'
    reject_case(records, 'missing_reference', by_kind(records, 'mention')['id'])


def test_wrong_reference_kind_fails(fixture_records):
    records = corpus(fixture_records)
    mention = by_kind(records, 'mention')
    mention['entity_id'] = by_kind(records, 'item')['id']
    reject_case(records, 'wrong_reference_kind', mention['id'])


def test_wrong_text_hash_fails(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'version')['text_hash'] = '0' * 64
    reject_case(records, 'text_hash_mismatch', by_kind(records, 'version')['id'])


def test_span_beyond_document_fails(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'mention')['occurrences'] = [{'field': 'title', 'start': 0, 'end': 1000}]
    reject_case(records, 'span_out_of_bounds', by_kind(records, 'mention')['id'])


def test_surface_mismatch_fails(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'mention')['occurrences'] = [{'field': 'title', 'start': 2, 'end': 6}]
    reject_case(records, 'surface_mismatch', by_kind(records, 'mention')['id'])


def test_span_on_absent_text_field_fails(fixture_records):
    records = corpus(fixture_records)
    version = by_kind(records, 'version')
    mention = by_kind(records, 'mention')
    for key in ('text', 'text_hash', 'rights_basis'):
        version.pop(key, None)
    version['access'] = 'metadata_only'
    mention['occurrences'] = [{'field': 'text', 'start': 0, 'end': 4}]
    reject_case(records, 'span_absent_field', mention['id'])


def test_run_finishes_before_it_starts(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'run')['finished_at'] = '2026-10-19T00:00:00Z'
    reject_case(records, 'run_finish_before_start', by_kind(records, 'run')['id'])


def test_cyclic_supersede_fails(fixture_records):
    records = corpus(fixture_records)
    item = by_kind(records, 'item')
    item['superseded_by'] = item['id']
    reject_case(records, 'cyclic_supersede', item['id'])


def test_current_version_of_another_item_fails(fixture_records, second_batch):
    records = corpus(fixture_records) + copy.deepcopy(second_batch)
    item = by_kind(records, 'item')
    other = next(r for r in records if r['kind'] == 'version' and r['item_id'] != item['id'])
    item['current_version_id'] = other['id']
    reject_case(records, 'current_version_mismatch', item['id'])


def test_invalid_tenure_interval_fails(fixture_records):
    records = corpus(fixture_records)
    entity = by_kind(records, 'entity')
    entity['tenures'] = [{'office': 'Mayor', 'jurisdiction': 'Example City',
                          'from': '2026-01-01', 'to': '2026-01-01'}]
    reject_case(records, 'invalid_interval', entity['id'])


def test_reflexive_identity_decision_fails(fixture_records):
    records = corpus(fixture_records)
    decision = by_kind(records, 'identity_decision')
    decision['right_id'] = decision['left_id']
    reject_case(records, 'reflexive_identity_decision', decision['id'])


def test_output_run_not_successful_fails(fixture_records):
    records = corpus(fixture_records)
    run = by_kind(records, 'run')
    mention_run = next(r for r in records if r['kind'] == 'run' and r['processor'] == 'mentions')
    mention_run.update(status='failed', reason='boom')
    reject_case(records, 'output_run_not_successful', by_kind(records, 'mention')['id'])


def test_output_input_absent_from_run_fails(fixture_records):
    records = corpus(fixture_records)
    extract_run = next(r for r in records if r['kind'] == 'run' and r['processor'] == 'extract')
    extract_run['inputs'] = [{'kind': 'version', 'id': by_kind(records, 'version')['id']}]
    reject_case(records, 'output_input_absent', by_kind(records, 'version')['id'])


def test_story_run_not_successful_fails(fixture_records):
    records = corpus(fixture_records)
    cluster_run = next(r for r in records if r['kind'] == 'run' and r['processor'] == 'cluster')
    cluster_run.update(status='failed', reason='boom')
    reject_case(records, 'story_run_not_successful', by_kind(records, 'story')['id'])


def test_story_member_run_mismatch_fails(fixture_records, second_batch):
    records = corpus(fixture_records) + copy.deepcopy(second_batch)
    member = by_kind(records, 'story_member')
    story = next(r for r in records if r['kind'] == 'story' and r['id'] == member['story_id'])
    mentions_run = next(r['id'] for r in records if r['kind'] == 'run' and r['processor'] == 'mentions')
    story['run_id'] = mentions_run  # succeeded run, so only the agreement rule can fire
    reject_case(records, 'story_member_run_mismatch', member['id'])


def test_multiple_memberships_per_run_version_fails(fixture_records):
    records = corpus(fixture_records)
    member = by_kind(records, 'story_member')
    clone = copy.deepcopy(member)
    clone['id'] = 'e0497e97-8d3f-5d94-b6a3-64c1d66b1c01'
    records.append(clone)
    reject_case(records, 'multiple_memberships', clone['id'])


def test_release_table_set_incomplete_fails(fixture_records):
    records = copy.deepcopy(fixture_records)
    release = by_kind(records, 'release')
    release['snapshots'][1]['table'] = release['snapshots'][0]['table']  # 12 entries, one table missing
    reject_case(records, 'release_table_set', release['id'])


def test_release_table_set_duplicated_fails(fixture_records):
    records = copy.deepcopy(fixture_records)
    release = by_kind(records, 'release')
    release['snapshots'][-1]['table'] = release['snapshots'][0]['table']  # 12 entries, one dup name
    reject_case(records, 'release_table_set', release['id'])


def test_release_snapshot_id_over_int64_fails(fixture_records):
    records = copy.deepcopy(fixture_records)
    release = by_kind(records, 'release')
    release['snapshots'][0]['snapshot_id'] = '9999999999999999999'  # pattern-legal, range-illegal
    reject_case(records, 'snapshot_id_range', release['id'])


def test_release_multiple_selections_per_processor_fails(fixture_records):
    records = copy.deepcopy(fixture_records)
    release = by_kind(records, 'release')
    second = dict(release['selections'][0])
    second['config_hash'] = 'f' * 64  # distinct entry, same processor
    release['selections'].append(second)
    reject_case(records, 'multiple_selections', release['id'])


def test_entity_evidence_capture_must_resolve(fixture_records):
    records = corpus(fixture_records)
    entity = by_kind(records, 'entity')
    entity['evidence_capture_ids'] = ['00000000-0000-0000-0000-000000000002']
    reject_case(records, 'missing_reference', entity['id'])


def _add_entity_pair(records, *, same_scheme=False):
    first, second = (
        {'kind': 'entity', 'id': 'bbbbbbbb-0000-4000-8000-000000000001',
         'recorded_at': '2026-10-20T04:00:00Z', 'entity_type': 'person',
         'name': 'Test One', 'aliases': [],
         'identifiers': [{'scheme': 'test-scheme', 'value': 'one'}]},
        {'kind': 'entity', 'id': 'bbbbbbbb-0000-4000-8000-000000000002',
         'recorded_at': '2026-10-20T04:00:00Z', 'entity_type': 'person',
         'name': 'Test Two', 'aliases': [],
         'identifiers': [{'scheme': 'test-scheme' if same_scheme else 'test-other',
                          'value': 'two'}]},
    )
    records.extend([first, second])
    return first, second


def test_decision_graph_cycles_are_corpus_failures(fixture_records):
    records = corpus(fixture_records)
    first, second = _add_entity_pair(records)
    records.append({
        'kind': 'identity_decision', 'id': 'aaaaaaaa-0000-4000-8000-000000000001',
        'recorded_at': '2026-10-20T05:00:00Z', 'action': 'same_as',
        'left_id': first['id'], 'right_id': second['id'],
        'decided_by': 'fixture:reviewer', 'reason': 'fixture merge',
    })
    records.append({
        'kind': 'identity_decision', 'id': 'aaaaaaaa-0000-4000-8000-000000000002',
        'recorded_at': '2026-10-20T06:00:00Z', 'action': 'same_as',
        'left_id': second['id'], 'right_id': first['id'],
        'decided_by': 'fixture:reviewer', 'reason': 'fixture cycle',
    })
    reject_case(records, 'decision_cycle', 'aaaaaaaa-0000-4000-8000-000000000002')


def test_contradictory_decisions_are_corpus_failures(fixture_records):
    records = corpus(fixture_records)
    first, second = _add_entity_pair(records)
    records.append({
        'kind': 'identity_decision', 'id': 'aaaaaaaa-0000-4000-8000-000000000003',
        'recorded_at': '2026-10-20T05:00:00Z', 'action': 'different_from',
        'left_id': first['id'], 'right_id': second['id'],
        'decided_by': 'fixture:reviewer', 'reason': 'distinct',
    })
    records.append({
        'kind': 'identity_decision', 'id': 'aaaaaaaa-0000-4000-8000-000000000004',
        'recorded_at': '2026-10-20T06:00:00Z', 'action': 'same_as',
        'left_id': first['id'], 'right_id': second['id'],
        'decided_by': 'fixture:reviewer', 'reason': 'contradiction',
    })
    reject_case(records, 'contradictory_decision', 'aaaaaaaa-0000-4000-8000-000000000004')


def test_authoritative_id_conflicts_are_corpus_failures(fixture_records):
    records = corpus(fixture_records)
    first, second = _add_entity_pair(records, same_scheme=True)
    records.append({
        'kind': 'identity_decision', 'id': 'aaaaaaaa-0000-4000-8000-000000000005',
        'recorded_at': '2026-10-20T05:00:00Z', 'action': 'same_as',
        'left_id': first['id'], 'right_id': second['id'],
        'decided_by': 'fixture:reviewer', 'reason': 'conflicting identifiers',
    })
    reject_case(records, 'authoritative_id_conflict', 'aaaaaaaa-0000-4000-8000-000000000005')


def test_cyclic_run_inputs_fail(fixture_records):
    records = corpus(fixture_records)
    run = next(r for r in records if r['kind'] == 'run' and r['processor'] == 'extract')
    version = by_kind(records, 'version')
    run['inputs'] = run['inputs'] + [{'kind': 'version', 'id': version['id']}]
    reject_case(records, 'input_cycle', run['id'])


def test_version_text_requires_a_successful_non_metadata_capture(fixture_records):
    records = corpus(fixture_records)
    capture = by_kind(records, 'capture')
    capture['status'] = 'failed'
    capture['error_code'] = 'http_500'
    reject_case(records, 'output_capture_not_successful', by_kind(records, 'version')['id'])

    records = corpus(fixture_records)
    capture = by_kind(records, 'capture')
    capture['access'] = 'metadata_only'
    for key in ('payload_uri', 'payload_hash', 'media_type', 'rights_basis'):
        capture.pop(key, None)
    reject_case(records, 'text_from_metadata_only_capture', by_kind(records, 'version')['id'])


def test_release_checkpoint_connector_keys_are_unique(fixture_records):
    records = copy.deepcopy(fixture_records)
    release = by_kind(records, 'release')
    release['checkpoints'] = [
        {'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:cp:1'},
        {'connector_key': 'rss:example', 'checkpoint_ref': 'urn:fixture:cp:2'},
    ]
    reject_case(records, 'duplicate_checkpoint_key', release['id'])


def test_credentials_must_be_redacted(fixture_records):
    records = corpus(fixture_records)
    capture = by_kind(records, 'capture')
    capture['request_url'] = 'https://user:secret@example.com/news/1'
    reject_case(records, 'unredacted_credentials', capture['id'])


def test_allow_extra_by_kind_permits_evolved_columns(fixture_records):
    records = corpus(fixture_records)
    by_kind(records, 'item')['pilot_note'] = 'verified'
    check_corpus(records, allow_extra_by_kind={'item': {'pilot_note'}})
    with pytest.raises(ContractError) as rejected:
        check_corpus(copy.deepcopy(records))
    assert rejected.value.rule == 'shape'


def test_validated_ids_still_receive_cross_record_checks(fixture_records):
    records = corpus(fixture_records)
    ids = {record['id'] for record in records}
    check_corpus(copy.deepcopy(records), validated_ids=ids)
    by_kind(records, 'mention')['entity_id'] = '00000000-0000-0000-0000-000000000001'
    reject_case(records, 'missing_reference', by_kind(records, 'mention')['id'])
