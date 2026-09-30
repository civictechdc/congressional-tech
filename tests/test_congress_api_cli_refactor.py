"""CLI validation stops invalid runs before workflows or credentials are used."""
import importlib
import sys
from unittest.mock import Mock
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('module,required', [
    ('meetings', []),
    ('gpo_fetch', []),
    ('gpo_transcripts', ['--out-dir', 'unused']),
    ('senate_captions', ['--out-dir', 'unused', '--urls', 'https://example.org/player']),
])
@pytest.mark.parametrize('count', ['0', '-1'])
def test_worker_counts_fail_at_cli_edge(monkeypatch, capsys, module, required, count):
    cli = importlib.import_module(f'congress_api.cli.{module}')
    workflow = Mock()
    monkeypatch.setattr(cli, 'main', workflow)
    monkeypatch.setattr(sys, 'argv', [module, *required, '--nthreads', count])
    with pytest.raises(SystemExit) as error:
        cli.parse_args_and_run()
    assert error.value.code == 2
    assert '--nthreads' in capsys.readouterr().err
    workflow.assert_not_called()


def test_gpo_refresh_limit_is_nonnegative_and_preserves_key_passthrough(monkeypatch):
    from congress_api.cli import gpo_fetch
    workflow = Mock()
    monkeypatch.setattr(gpo_fetch, 'main', workflow)
    monkeypatch.setattr(sys, 'argv', ['gpo-fetch', '--refresh-limit', '-1'])
    with pytest.raises(SystemExit) as error:
        gpo_fetch.parse_args_and_run()
    assert error.value.code == 2
    workflow.assert_not_called()
    monkeypatch.setattr(sys, 'argv', ['gpo-fetch', '--refresh-limit', '0', '--nthreads', '2', '--congress-api-key', 'mock-key'])
    gpo_fetch.parse_args_and_run()
    assert workflow.call_args.kwargs['refresh_limit'] == 0
    assert workflow.call_args.kwargs['nthreads'] == 2
    assert 'congress_api_key' not in workflow.call_args.kwargs


def test_committees_accepts_key_flag_without_forwarding_it(monkeypatch):
    from pathlib import Path

    from congress_api.cli import committees
    workflow = Mock()
    monkeypatch.setattr(committees, 'collect', workflow)
    monkeypatch.setattr(committees, 'load_congress_api_key', lambda: 'mock-key')
    monkeypatch.setattr(sys, 'argv', [
        'congress-committees', '--meetings-path', 'meetings.jsonl.gz',
        '--output-path', 'committees.jsonl.gz', '--congress-api-key', 'mock-key',
    ])
    committees.parse_args_and_run()
    assert workflow.call_args.kwargs['meetings_path'] == Path('meetings.jsonl.gz')
    assert workflow.call_args.kwargs['output_path'] == Path('committees.jsonl.gz')
    assert workflow.call_args.kwargs['api_key'] == 'mock-key'
    assert 'congress_api_key' not in workflow.call_args.kwargs


def test_house_parallel_threads_require_zyte(monkeypatch, capsys, tmp_path):
    from congress_api.cli import house
    workflow = Mock()
    monkeypatch.setattr(house, 'main', workflow)
    monkeypatch.setattr(sys, 'argv', [
        'house-meeting-records', '--meetings', str(tmp_path / 'm.jsonl.gz'),
        '--state-dir', str(tmp_path), '--output-dir', str(tmp_path),
        '--gpo-path', str(tmp_path / 'gpo.csv'), '--threads', '2',
    ])
    with pytest.raises(SystemExit) as error:
        house.parse_args_and_run()
    assert error.value.code == 2
    assert '--zyte' in capsys.readouterr().err
    workflow.assert_not_called()


def test_senate_historical_since_requires_site(monkeypatch, tmp_path):
    from congress_api.cli import senate
    monkeypatch.setattr(sys, 'argv', [
        'senate-meeting-records', '--meetings', str(tmp_path / 'm.jsonl.gz'),
        '--state-dir', str(tmp_path), '--output-dir', str(tmp_path),
        '--since', '2018-01-01',
    ])
    with pytest.raises(ValueError, match='explicit --site scope'):
        senate.parse_args_and_run()


def test_video_loader_preserves_cache_table_channel_identity(tmp_path):
    from congress_api.cli.gpo_match import load_videos
    (tmp_path / 'youtube_01.json').write_text('''{"youtube_videos_TABLE_CHANNEL": {"1": {"videoId": "vid", "channelId": "ROW_CHANNEL", "title": "Hearing", "description": "", "publishedAt": "2026-09-30T00:00:00Z"}}, "other": {}}''')
    videos = load_videos(tmp_path, [{'systemCode': 'missing'}, {'systemCode': 'hsvr00'}])
    assert list(videos) == ['hsvr00']
    assert videos['hsvr00'][0]['channel'] == 'TABLE_CHANNEL'
    assert videos['hsvr00'][0]['published'] == '2026-09-30'


@pytest.mark.parametrize('query,valid', [
    ('comm=epw&%66ilename=epw120623', True),
    ('comm=epw', False),
    ('comm=epw&filename=..%2Foutside', False),
    ('comm=epw&filename=..', False),
])
def test_transcriber_resolves_senate_filename_before_transcribing(tmp_path, monkeypatch, query, valid):
    from congress_api.cli import transcribe as cli
    gpo = tmp_path / 'gpo.csv'
    gpo.write_text('package_id,event_id\n')
    output = tmp_path / 'output'
    transcript = SimpleNamespace(to_json=lambda: '{}', turns=[], participants={})
    transcribe = Mock(return_value=transcript)
    monkeypatch.setattr(cli, 'transcribe', transcribe)
    monkeypatch.setattr(cli, 'render_gpo', lambda _: 'rendered')
    monkeypatch.setattr(cli.metadata, 'set_paths', Mock())
    monkeypatch.setattr(cli, 'context_for_event', lambda *a, **k: SimpleNamespace(youtube_ids=[], senate_urls=[]))
    monkeypatch.setattr(sys, 'argv', ['hearing-transcribe', '--event-id', '12', '--gpo-path', str(gpo),
        '--out-dir', str(output), '--senate-url', f'https://www.senate.gov/isvp/?{query}'])
    if valid:
        cli.parse_args_and_run()
        transcribe.assert_called_once()
        assert (output / 'epw120623.json').read_text() == '{}'
        assert (output / 'epw120623.gpo.txt').read_text() == 'rendered'
    else:
        with pytest.raises(SystemExit) as error:
            cli.parse_args_and_run()
        assert error.value.code == 2
        transcribe.assert_not_called()
        assert not list(output.iterdir())


@pytest.mark.parametrize('force', [False, True])
def test_transcriber_refuses_existing_outputs_unless_forced(tmp_path, monkeypatch, force):
    from congress_api.cli import transcribe as cli
    gpo = tmp_path / 'gpo.csv'
    gpo.write_text('package_id,event_id\n')
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'epw120623.json').write_text('old-json', encoding='utf-8')
    (output / 'epw120623.gpo.txt').write_text('old-gpo', encoding='utf-8')
    transcript = SimpleNamespace(to_json=lambda: 'new-json', turns=[], participants={})
    transcribe = Mock(return_value=transcript)
    monkeypatch.setattr(cli, 'transcribe', transcribe)
    monkeypatch.setattr(cli, 'render_gpo', lambda _: 'new-gpo')
    monkeypatch.setattr(cli.metadata, 'set_paths', Mock())
    monkeypatch.setattr(cli, 'context_for_event', lambda *a, **k: SimpleNamespace(youtube_ids=[], senate_urls=[]))
    argv = ['hearing-transcribe', '--event-id', '12', '--gpo-path', str(gpo),
            '--out-dir', str(output), '--senate-url', 'https://www.senate.gov/isvp/?comm=epw&filename=epw120623']
    if force:
        argv.append('--force')
    monkeypatch.setattr(sys, 'argv', argv)
    if force:
        cli.parse_args_and_run()
        transcribe.assert_called_once()
        assert (output / 'epw120623.json').read_text() == 'new-json'
        assert (output / 'epw120623.gpo.txt').read_text() == 'new-gpo'
        assert not list(output.glob('*.tmp'))
    else:
        with pytest.raises(SystemExit) as error:
            cli.parse_args_and_run()
        assert error.value.code != 0
        assert 'refusing to overwrite' in str(error.value)
        transcribe.assert_not_called()
        assert (output / 'epw120623.json').read_text() == 'old-json'
        assert (output / 'epw120623.gpo.txt').read_text() == 'old-gpo'
