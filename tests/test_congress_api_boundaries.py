"""Public names, package boundaries and source identities must survive refactors."""
import argparse
import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import tomllib
from congress_api.adapters.common import AdapterContext, digest
from congress_api.cli.common import source_args

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'packages/congress_api/src/congress_api'
SCRIPTS = {
    'house-meeting-records', 'senate-meeting-records', 'meeting-inventory',
    'gpo-fetch', 'gpo-match',
    'senate-captions', 'hearing-transcribe', 'gpo-transcripts',
    'congress-meetings', 'congress-committees', 'raw-source-sync',
}
VERSIONS = {
    ('parsers/house_evidence.py', 'SCHEMA_VERSION'): '1.1',
    ('parsers/senate.py', 'PARSER_VERSION'): 10,
    ('parsers/gpo_hearings.py', 'PARSER_VERSION'): '3',
    ('parsers/witness_pdf.py', 'PARSER_VERSION'): 2,
    ('transcripts/senate.py', 'CAPTURE_VERSION'): '3',
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
        package = 'congress_api' + ('.' + '.'.join(relative.parts[:-1]) if len(relative.parts) > 1 else '')
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                module = resolve_name('.' * node.level + (node.module or ''), package) if node.level else node.module or ''
                modules = [module] + [module + '.' + alias.name for alias in node.names]
            else:
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            assert not any(m.startswith(('congress_legacy', 'youtube_api', 'tinydb', 'congress_api.legacy',
                'congress_api.fetch', 'congress_api.analyze', 'congress_api.api', 'congress_api.xml_to_dict',
                'congress_api.json_to_tinydb')) for m in modules), path


def test_production_commands_do_not_require_legacy_dependencies():
    project = tomllib.loads((SOURCE.parents[1] / 'pyproject.toml').read_text())['project']
    assert not {'congress-legacy', 'youtube-api', 'tinydb'} & set(project['dependencies'])
    # A fresh interpreter cannot inherit optional modules imported by other tests.
    program = '''
import importlib
import importlib.abc
import sys

class NoLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'congress_legacy', 'youtube_api', 'tinydb'}:
            raise ImportError('Production attempted optional dependency: ' + fullname)

sys.meta_path.insert(0, NoLegacy())
for entry in sys.argv[1:]:
    module, function = entry.split(':')
    sys.argv = [module, '--help']
    try:
        getattr(importlib.import_module(module), function)()
    except SystemExit as result:
        assert result.code == 0, (entry, result.code)
'''
    result = subprocess.run([sys.executable, '-c', program, *project['scripts'].values()],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_committee_entrypoint_delegates_without_changing_main(monkeypatch):
    from congress_api.cli import committees
    monkeypatch.setattr(committees, 'main', lambda: 'existing-main-result')
    assert committees.parse_args_and_run() == 'existing-main-result'


def test_interpretation_cannot_import_acquisition_storage_or_command_wiring():
    forbidden = {'acquisition', 'transport', 'retention', 'cli', 'transcripts', 'replay', 'adapters'}
    for family in ('models', 'parsers', 'matching'):
        for path in (SOURCE / family).glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom):
                    modules = [node.module or '']
                    if node.module == 'congress_api':
                        modules += ['congress_api.' + alias.name for alias in node.names]
                else:
                    modules = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                for module in modules:
                    parts = module.split('.')
                    assert not (len(parts) > 1 and parts[0] == 'congress_api' and parts[1] in forbidden), (path, module)
                    assert module not in {'urllib.request', 'http.client'}, (path, module)
                    assert parts[0] not in {'requests', 'httpx', 'google', 'yt_dlp'}, (path, module)
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                    assert name not in {'open', 'read_text', 'read_bytes', 'write_text', 'write_bytes'}, (path, name)


def test_commands_resolve_to_cli_and_old_provider_packages_are_retired():
    project = tomllib.loads((SOURCE.parents[1] / 'pyproject.toml').read_text())['project']
    assert all(entry.startswith('congress_api.cli.') for entry in project['scripts'].values())
    assert {p.name for p in SOURCE.iterdir() if p.is_dir() and p.name != '__pycache__'} == {
        'models', 'parsers', 'acquisition', 'transport', 'retention', 'adapters',
        'matching', 'transcripts', 'replay', 'cli',
    }
