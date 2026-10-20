"""Executable fixture requirements, independent of the selected storage engine."""
from collections import Counter
import base64
from pathlib import Path
import importlib.util

import pyarrow as pa

SPEC = importlib.util.spec_from_file_location(
    'incremental_boundary_proof', Path(__file__).parents[1] / 'scripts/incremental_boundary_proof.py')
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)
FIXTURE = Path(__file__).parent / 'fixtures/incremental-boundary/acquisition-receipt.json'


def test_retained_reference_keeps_occurrences_nested_headers_and_null_empty_values():
    rows = proof.reference_rows(FIXTURE)
    assert len(rows) == 7  # parent ZIP, five members, one constructed duplicate observation
    assert Counter(r['body_sha256'] for r in rows).most_common(1)[0][1] == 2
    assert rows[-1]['provenance'] == rows[1]['provenance']
    headers = rows[0]['provenance']['headers']
    assert headers.count({'name': 'accept-ranges', 'value': 'bytes'}) == 2
    assert base64.b64decode(rows[0]['provenance']['acquisition_receipt_base64']) == FIXTURE.read_bytes()
    assert rows[0]['review'] is None and rows[1]['review'] == ''
    assert rows[0]['aliases'] is None and rows[2]['aliases'] == []
    assert pa.Table.from_pylist(rows, schema=proof.ROW_SCHEMA).to_pylist() == rows


def test_change_example_names_exact_old_new_scope_without_mutating_reference():
    rows = proof.reference_rows(FIXTURE)
    change = proof.change_example(rows)
    assert change['transform_versions'] == {'source': 'retained-package-v1', 'grouping': 'alias-v1'}
    assert change['deletions'] == [rows[2]['record_key']]
    assert change['changed_record_keys'] == [rows[1]['record_key'], rows[2]['record_key']]
    assert change['edges_before'] == [[rows[1]['record_key'], rows[0]['record_key']]]
    assert change['edges_after'] == [[rows[1]['record_key'], rows[3]['record_key']]]
    assert rows[1]['review'] == ''
    assert change['replacements'][0]['review'] == 'corrected-local-proof'
    assert proof.change_example(rows) == change


def test_expected_result_preserves_duplicate_observation_and_all_untouched_values():
    rows = proof.reference_rows(FIXTURE)
    change = proof.change_example(rows)
    expected = proof.expected_rows(rows, change)
    assert len(expected) == 6
    by_key = {r['record_key']: r for r in expected}
    assert rows[2]['record_key'] not in by_key
    assert by_key[rows[-1]['record_key']] == rows[-1]
    assert by_key[rows[3]['record_key']] == rows[3]
    assert by_key[rows[1]['record_key']]['aliases'] == [rows[3]['record_key']]
