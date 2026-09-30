"""Public names, package boundaries and source identities must survive refactors."""
import argparse
import ast
import hashlib
from pathlib import Path
import re
import tomllib

from congress_api.adapters.common import AdapterContext, digest
from congress_api.inventory.common import source_args

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'packages/congress_api/src/congress_api'
SCRIPTS = {
    'house-meeting-records', 'senate-meeting-records', 'meeting-inventory',
    'congress-fetch', 'congress-analyze', 'gpo-fetch', 'gpo-match',
    'senate-captions', 'hearing-transcribe', 'gpo-transcripts',
    'congress-meetings', 'congress-committees',
}
VERSIONS = {
    ('house/evidence.py', 'SCHEMA_VERSION'): '1.1',
    ('senate/records.py', 'PARSER_VERSION'): 5,
    ('gpo/fetch.py', 'PARSER_VERSION'): '3',
    ('inventory/witness_lists.py', 'PARSER_VERSION'): 2,
    ('senate/captions.py', 'CAPTURE_VERSION'): '3',
    ('models/transcription.py', 'SCHEMA_VERSION'): '1.0',
}


def test_script_names_and_source_flags_are_stable():
    scripts = tomllib.loads((SOURCE.parents[1] / 'pyproject.toml').read_text())['project']['scripts']
    assert set(scripts) == SCRIPTS
    parser = argparse.ArgumentParser()
    source_args(parser)
    assert {option for action in parser._actions for option in action.option_strings} == {
        '-h', '--help', '--meetings', '--state-dir', '--output-dir', '--seed-cache', '--offline', '--as-of'}
    assert {action.dest for action in parser._actions if action.required} == {'meetings', 'state_dir', 'output_dir'}


def test_parser_version_registry_covers_every_owner():
    actual = {}
    for path in SOURCE.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {'SCHEMA_VERSION', 'PARSER_VERSION', 'CAPTURE_VERSION'}:
                        actual[(path.relative_to(SOURCE).as_posix(), target.id)] = ast.literal_eval(node.value)
    assert actual == VERSIONS, 'Update the compatibility registry and migration evidence with any version change.'


def test_only_adapters_import_canonical_meeting_models():
    for path in SOURCE.rglob('*.py'):
        if 'adapters' in path.relative_to(SOURCE).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                       else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            assert not any(m == 'committee_meeting' or m.startswith('committee_meeting.') for m in modules), path


def test_weekly_workflow_keeps_explore_tools_out_of_production():
    workflow = (ROOT / '.github/workflows/update-data.yml').read_text()
    assert not re.search(r'\bcongress-(?:fetch|analyze)\b', workflow)
    assert re.findall(r'^  (\w+):\n', workflow.split('\njobs:\n', 1)[1], re.M) == ['youtube', 'congress', 'meetings', 'committees']
    assert 'congress-meetings --output-path pipeline-data/congress_meetings.jsonl.gz' in workflow
    assert 'continue-on-error' not in workflow
    publication = (ROOT / '.github/workflows/publish-explorer.yml').read_text()
    assert 'types: [completed]' in publication
    assert 'offline-python.py -m committee_explorer.export' in publication


def test_digest_and_source_key_preserve_publisher_values():
    from datetime import datetime, timezone
    payload = {'name': 'José', 'empty': [], 'present': None, 'number': '01'}
    encoded = '{"empty":[],"name":"José","number":"01","present":null}'.encode()
    expected = hashlib.sha256(encoded).hexdigest()
    assert digest(payload) == expected == digest(dict(reversed(list(payload.items()))))
    assert len({digest(value) for value in ({}, {'x': None}, {'x': ''}, {'x': []}, {'x': 1}, {'x': '1'})}) == 6
    assert digest([1, 2]) != digest([2, 1])
    calls = []
    def ids(kind, key):
        calls.append((kind, key))
        return '994fa51d-96df-4fe1-9bc0-b2e6d31248fb'
    context = AdapterContext(datetime(2026, 9, 30, tzinfo=timezone.utc), 'snapshot', 'publisher', ids)
    source = context.source('native', payload)
    assert calls == [('source_record', f'publisher|snapshot|native|{expected}')]
    assert source.payload == payload


def test_production_imports_do_not_reenter_legacy_exploration():
    from importlib.util import resolve_name
    for path in SOURCE.rglob('*.py'):
        relative = path.relative_to(SOURCE)
        if relative.parts[0] in {'legacy', 'fetch', 'analyze'} or relative.name == 'json_to_tinydb.py':
            continue  # These are the quarantined code and compatibility aliases.
        package = 'congress_api' + ('.' + '.'.join(relative.parts[:-1]) if len(relative.parts) > 1 else '')
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                module = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
                modules = [module] + [module + '.' + alias.name for alias in node.names]
            else:
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert not any(m.startswith(('congress_api.legacy', 'congress_api.fetch', 'congress_api.analyze')) for m in modules), path


def test_legacy_modules_share_implementations_and_mutable_caches():
    from importlib import import_module
    aliases = {
        'fetch.main': 'legacy.fetch.main',
        'fetch.congress_committee_fetcher': 'legacy.fetch.congress_committee_fetcher',
        'fetch.congress_event_fetcher': 'legacy.fetch.congress_event_fetcher',
        'analyze.main': 'legacy.analyze.main',
        'analyze.committee': 'legacy.committee',
        'analyze.committee_summary': 'legacy.committee_summary',
        'analyze.committee_details': 'legacy.committee_details',
        'json_to_tinydb': 'legacy.json_to_tinydb',
    }
    for old, owner in aliases.items():
        assert import_module('congress_api.' + old) is import_module('congress_api.' + owner)
    # Fetch may share committee objects, but cannot import the analyze command.
    for path in (SOURCE / 'legacy/fetch').glob('*.py'):
        assert not re.search(r'\b(?:from|import)\s+[^\n]*analyze', path.read_text())


def test_committee_entrypoint_delegates_without_changing_main(monkeypatch):
    from congress_api import committee_metadata
    monkeypatch.setattr(committee_metadata, 'main', lambda: 'existing-main-result')
    assert committee_metadata.parse_args_and_run() == 'existing-main-result'


def test_inventory_http_calls_live_only_in_acquisition():
    for path in (SOURCE / 'inventory').glob('*.py'):
        if path.name == 'acquisition.py':
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert 'get_with_retry' not in {alias.name for alias in node.names}, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'get_with_retry', 'urlopen', 'request'}, path
