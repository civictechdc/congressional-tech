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
    # file_references is projected whole, so its fields are read.
    assert 'file_references/*/http_status' in read
    # A container of read fields is not itself reported as unread.
    assert 'record' not in unread
    assert 'record/recovery_basis' in unread


def test_report_uses_the_paths_the_plan_projects():
    from congress_api.lake import receipt_metadata
    sql = receipt_metadata.source_plan(files=[])['steps'][0]['sql']
    # The plan's projection is built from exactly the exposed list, so the report cannot drift.
    assert receipt_metadata.projection('__raw_line', receipt_metadata.source_paths())[0] in sql
    declared = {'/'.join(path) for path in coverage.mapper_paths()}
    # ct-bxqa: the owner status keys are read at record and list-item level.
    assert {'record/status', 'record/master_attempts/*/status', 'record/receipt/status',
            'record/*/master_attempts/*/status', 'record/*/receipt/status'} <= declared
