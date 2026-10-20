"""The fixed bridge deletion exposes catalog dependency work that still grows."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'catalog_dependency_boundary', Path(__file__).parents[1] /
    'docs/experiments/incremental-catalog-20261019/measure.py')
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


def test_bridge_deletion_preserves_every_field_and_names_both_split_sides(tmp_path):
    result = measure.measure_case(tmp_path / 'case', unrelated=2)
    assert result['all_field_multiset_parity']
    assert result['removed_source_count'] == 1
    assert result['affected_old_group_members'] == 3
    assert result['affected_new_group_members'] == 2
    assert result['affected_new_group_count'] == 2
    assert result['recomputed_document_groups'] == 2
    assert result['reused_document_groups'] == 2
    assert result['receipts_read'] == result['bodies_read'] == result['classification_calls'] == 0


def test_fixed_deletion_has_explicit_unrelated_scan_counterexample(tmp_path):
    small = measure.measure_case(tmp_path / 'small', unrelated=2)
    large = measure.measure_case(tmp_path / 'large', unrelated=20)
    assert small['affected_new_group_members'] == large['affected_new_group_members'] == 2
    assert large['prior_source_rows_read'] - small['prior_source_rows_read'] == 18
    assert large['current_source_rows_visited'] - small['current_source_rows_visited'] == 18
    assert large['validation_rows_read'] - small['validation_rows_read'] == 36
    assert large['output_bytes'] > small['output_bytes']
    refusal = measure.require_bounded(small, large)
    assert refusal['status'] == 'blocked'
    assert refusal['reason'] == 'unrelated_catalog_rows_scanned'
    assert refusal['needs'] == ['retained_old_new_dependency_lookup', 'recoverable_native_partition_custody']
