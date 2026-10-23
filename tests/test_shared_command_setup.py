"""Shared imports are passive; command entrypoints retain logging and path defaults."""

import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


LEGACY_COMMANDS = [
    'congress_api.cli.meetings', 'congress_api.cli.committees',
    'congress_api.cli.gpo_fetch', 'congress_api.cli.gpo_match',
    'congress_api.cli.gpo_transcripts', 'congress_api.cli.inventory',
    'congress_api.cli.transcribe', 'youtube_api.fetch.main', 'youtube_api.analyze.main',
]
LOG_FORMAT = '%(levelname)s %(asctime)s : [%(name)s.%(funcName)s] %(message)s'


def run_python(code, *args):
    result = subprocess.run(
        [sys.executable, '-B', '-c', code, *args], capture_output=True, text=True,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize('existing_handler', [False, True])
def test_imports_preserve_root_logging_and_do_not_write(existing_handler):
    modules = [
        'congress_shared', 'congress_shared.auth', 'congress_shared.resources',
        'congress_shared.paths', 'congress_shared.cli', 'congress_shared.dates',
        'congress_shared.webvtt', 'youtube_api.tables',
        'youtube_api.fetch.youtube_event_fetcher', 'congress_api.acquisition.gpo',
        'congress_api.acquisition.meetings', 'congress_api.transcripts.context',
        'congress_api.transcripts.generate', *LEGACY_COMMANDS,
        'congress_api.cli.house', 'congress_api.cli.senate',
        'congress_api.cli.house_sites', 'congress_api.cli.senate_captions',
        'congress_api.cli.raw_sync', 'congress_api.cli.document_index',
        'youtube_api.captions.main', 'committee_explorer.export',
    ]
    run_python('''
import importlib, json, logging, os, sys
root = logging.getLogger()
if sys.argv[1] == 'True':
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('existing: %(message)s'))
    root.addHandler(handler)
    root.setLevel(logging.ERROR)
before = (root.level, list(root.handlers), [(h.level, h.formatter, h.stream) for h in root.handlers])
def audit(event, args):
    if event == 'open':
        _, mode, flags = args
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError(f'import attempted a write: {args[0]}')
    if event in ('os.mkdir', 'os.rename', 'os.remove', 'os.rmdir'):
        raise AssertionError(f'import attempted a filesystem change: {event}')
sys.addaudithook(audit)
for name in json.loads(sys.argv[2]):
    importlib.import_module(name)
    after = (root.level, list(root.handlers), [(h.level, h.formatter, h.stream) for h in root.handlers])
    assert after == before, name
''', str(existing_handler), json.dumps(modules))


@pytest.mark.parametrize('module', LEGACY_COMMANDS)
def test_command_help_explicitly_sets_legacy_logging(module):
    output = run_python('''
import importlib, json, logging, sys
module = importlib.import_module(sys.argv[1])
assert not logging.getLogger().handlers
sys.argv = ['command', '--help']
try:
    module.parse_args_and_run()
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError('help did not exit')
root = logging.getLogger()
assert len(root.handlers) == 1
handler = root.handlers[0]
print('LOG_STATE=' + json.dumps([root.level, handler.stream is sys.stdout, handler.formatter._fmt]))
''', module)
    assert 'usage:' in output
    assert json.loads(output.split('LOG_STATE=')[1]) == [20, True, LOG_FORMAT]


def test_existing_logging_configuration_is_respected():
    run_python('''
import logging, sys
from congress_shared.cli import configure_logging
root = logging.getLogger()
handler = logging.StreamHandler(sys.stderr)
root.addHandler(handler)
root.setLevel(logging.ERROR)
configure_logging()
configure_logging()
assert root.handlers == [handler]
assert root.level == logging.ERROR
''')


def test_paths_aliases_resources_and_argument_types(tmp_path, monkeypatch):
    from congress_shared import cli, paths, resources

    package = Path(resources.__file__).resolve().parent
    assert resources.PACKAGE_DIR == package
    assert resources.RESOURCE_DATA_DIR == paths.DEFAULT_OUTPUT_DIR == package / 'data'
    assert resources.CONGRESS_METADATA == json.loads((package / 'data/congress_metadata.json').read_text())
    assert resources.DEFAULT_CHANNELS_CSV == package / 'youtube/youtube-accounts.csv'
    assert resources.DEFAULT_CHANNELS_CSV.is_file()
    for name, filename in {
        'DEFAULT_TINYDB_DIR': '', 'DEFAULT_YOUTUBE_REPORT_FILE': 'youtube_event_id_report.csv',
        'DEFAULT_GPO_HEARINGS_FILE': 'gpo_hearings.csv', 'DEFAULT_MEETINGS_FILE': 'congress_meetings.jsonl.gz',
        'DEFAULT_HEARING_VIDEOS_FILE': 'gpo_hearing_videos.csv',
    }.items():
        assert getattr(paths, name) == package / 'data' / filename
    from congress_api.cli import gpo_match
    assert gpo_match.DEFAULT_OVERRIDES_FILE == paths.DEFAULT_OVERRIDES_FILE == package / 'data/hearing_video_overrides.csv'
    parser = argparse.ArgumentParser()
    cli.add_global_args(parser)
    cli.add_youtube_args(parser)
    defaults = parser.parse_args([])
    assert defaults.tinydb_dir == package / 'data'
    assert defaults.channels_csv_path == resources.DEFAULT_CHANNELS_CSV
    monkeypatch.chdir(tmp_path)
    explicit = parser.parse_args(['--tinydb_dir', './cache', '--channels-csv-path', './channels.csv'])
    assert explicit.tinydb_dir == tmp_path / 'cache'
    assert explicit.channels_csv_path == Path('./channels.csv')
    assert isinstance(explicit.channels_csv_path, Path)
    assert isinstance(defaults.channels_csv_path, Path)
    assert not (tmp_path / 'cache').exists()


@pytest.mark.parametrize('module,expected', [
    ('congress_api.cli.meetings', {'output_path': 'congress_meetings.jsonl.gz'}),
    ('congress_api.cli.gpo_fetch', {'output_path': 'gpo_hearings.csv'}),
    ('youtube_api.fetch.main', {'tinydb_dir': ''}),
    ('youtube_api.analyze.main', {'output_path': 'youtube_event_id_report.csv', 'tinydb_dir': ''}),
])
def test_commands_forward_existing_output_defaults(module, expected, monkeypatch):
    from congress_shared.resources import PACKAGE_DIR
    cli = importlib.import_module(module)
    calls = []
    monkeypatch.setattr(cli, 'main', lambda **args: calls.append(args))
    monkeypatch.setattr(cli, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['command', '--youtube-api-key', 'unused', '--congress-api-key', 'unused'])
    assert cli.parse_args_and_run() is None
    assert len(calls) == 1
    for name, filename in expected.items():
        assert calls[0][name] == PACKAGE_DIR / 'data' / filename
    assert not {'youtube_api_key', 'congress_api_key'} & calls[0].keys()


@pytest.mark.parametrize('loader,flag,environment,filenames', [
    ('load_congress_api_key', 'congress-api-key', 'DATA_GOV_API_KEY', ['.data.gov.api.key', '.data.gov.key']),
    ('load_youtube_api_key', 'youtube-api-key', 'YOUTUBE_API_KEY', ['.youtube.api.key']),
])
def test_credential_precedence_and_missing_key_error(loader, flag, environment, filenames, tmp_path, monkeypatch):
    from congress_shared import auth
    load = getattr(auth, loader)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    for filename in filenames:
        (tmp_path / filename).write_text(f'  {filename}\n')
    monkeypatch.setenv(environment, 'environment-key')
    monkeypatch.setattr(sys, 'argv', ['command', '--unrelated', 'value', f'--{flag}', 'argument-key'])
    assert load() == 'argument-key'
    monkeypatch.setattr(sys, 'argv', ['command'])
    assert load() == 'environment-key'
    monkeypatch.delenv(environment)
    for filename in filenames:
        assert load() == filename
        (tmp_path / filename).unlink()
    with pytest.raises(RuntimeError) as error:
        load()
    assert str(error.value) == f'{environment} not found. Provide via --{flag}, {environment} env var, or save it to {tmp_path / filenames[0]}'


def test_gpo_match_default_paths_and_coverage_selection(monkeypatch, tmp_path):
    from congress_api.cli import gpo_match as cli
    from congress_shared import paths, resources
    calls = []
    monkeypatch.setattr(cli, 'main', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(cli, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['gpo-match'])
    assert cli.parse_args_and_run() is None
    assert calls == [((
        paths.DEFAULT_HEARING_VIDEOS_FILE, paths.DEFAULT_TINYDB_DIR, resources.DEFAULT_CHANNELS_CSV,
        paths.DEFAULT_GPO_HEARINGS_FILE, paths.DEFAULT_MEETINGS_FILE, paths.DEFAULT_OVERRIDES_FILE,
        paths.DEFAULT_OUTPUT_DIR / 'gpo_hearing_video_coverage.csv',
    ), {'no_overrides': False})]
    monkeypatch.setattr(sys, 'argv', ['gpo-match', '--output-path', str(tmp_path / 'matches.csv'), '--no-overrides'])
    cli.parse_args_and_run()
    assert calls[-1][0][-1] == tmp_path / 'gpo_hearing_video_coverage.csv'
    assert calls[-1][1] == {'no_overrides': True}


def test_transcript_and_inventory_default_inputs(monkeypatch):
    from congress_api.cli import gpo_transcripts, inventory, transcribe
    from congress_shared import paths, resources
    calls = []
    monkeypatch.setattr(gpo_transcripts, 'main', lambda *args: calls.append(args))
    monkeypatch.setattr(gpo_transcripts, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['gpo-transcripts', '--out-dir', 'unused'])
    assert gpo_transcripts.parse_args_and_run() is None
    assert calls == [('unused', paths.DEFAULT_GPO_HEARINGS_FILE, None, None, None, None, 4)]
    monkeypatch.setattr(inventory, 'main', lambda **args: calls.append(args))
    monkeypatch.setattr(inventory, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['meeting-inventory', *[
        value for flag in ('meetings', 'state-dir', 'output-dir', 'gpo-path', 'videos-path', 'tinydb_dir', 'recordings')
        for value in (f'--{flag}', 'unused')
    ]])
    assert inventory.parse_args_and_run() is None
    assert calls[-1]['channels_csv_path'] == resources.DEFAULT_CHANNELS_CSV
    # Stop at the first post-parse step so no output directory or files are created.
    class Parsed(Exception):
        pass
    def capture_paths(*args):
        calls.append(args)
        raise Parsed
    monkeypatch.setattr(transcribe.metadata, 'set_paths', capture_paths)
    monkeypatch.setattr(transcribe, 'configure_logging', lambda: None)
    monkeypatch.setattr(sys, 'argv', ['hearing-transcribe', '--out-dir', 'unused'])
    with pytest.raises(Parsed):
        transcribe.parse_args_and_run()
    assert calls[-1] == (str(paths.DEFAULT_GPO_HEARINGS_FILE), str(paths.DEFAULT_MEETINGS_FILE))
