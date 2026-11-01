"""The coverage report classifies the committed fb408404 fixture's paths."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('capture_fixture_coverage', ROOT / 'scripts/measure/capture_fixture_coverage.py')
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)
FIXTURE = ROOT / 'packages/congress_api/tests/fixtures/fb408404_receipt_lines.jsonl'


def test_report_names_the_fb408404_pointer_classes_and_partitions_paths():
    value = coverage.report([json.loads(text)['row'] for text in FIXTURE.read_text().splitlines()])
    assert {'provider_response/raw_path', 'previous_receipt/raw_path', 'results/*/raw/path'} <= set(value['pointers'])
    read, unread, unexercised = (set(value[name]) for name in
        ('read_by_mapper', 'fixture_paths_not_read', 'mapper_paths_not_exercised'))
    assert read and unread and unexercised
    assert not (read & unread or read & unexercised or unread & unexercised)
    assert 'record/http_status' in read
    # The unread fact behind the ct-d0o0 report: the mapper never reads this path.
    assert 'record/previous_receipt/body_complete' in unread


def test_spy_restores_the_projection():
    original = coverage.receipt_metadata.projection
    assert coverage.mapper_paths()
    assert coverage.receipt_metadata.projection is original
