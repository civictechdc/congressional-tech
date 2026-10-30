"""Installation boundary: generated client settings must launch the installed runtime."""
import asyncio
import json
from pathlib import Path
import sys
import tomllib

from fastmcp import Client
from congressional_explorer_mcp.cli import main
from congressional_explorer_mcp.release import prepare


def test_generated_client_configs_launch_the_same_release(tmp_path, phase2, capfd):
    root = tmp_path / 'Congress data "quoted"'
    selected = prepare(root, phase2)
    assert main(['config', '--client', 'codex', '--data-dir', str(root)]) == 0
    codex = tomllib.loads(capfd.readouterr().out)['mcp_servers']['congress']
    assert codex['command'] == str(Path(sys.executable).absolute())
    for client in ('claude-desktop', 'claude-code', 'cursor'):
        assert main(['config', '--client', client, '--data-dir', str(root)]) == 0
        settings = json.loads(capfd.readouterr().out)
        assert settings['mcpServers']['congress'] == codex
    async def run():
        async with Client(settings) as client:
            assert (await client.call_tool('get_dataset_info')).data['release_id'] == selected['release_id']
    asyncio.run(run())
    assert main(['check', '--data-dir', str(root)]) == 0
    result = json.loads(capfd.readouterr().out)
    assert result['status'] == 'ok' and result['release_id'] == selected['release_id']
    assert result['sample_rows'] == 1 and len(result['tools']) == 6


def test_setup_before_download_and_actionable_missing_data(tmp_path, capsys):
    root = tmp_path / 'not prepared'
    assert main(['config', '--client', 'codex', '--data-dir', str(root)]) == 0
    assert not root.exists()
    capsys.readouterr()
    assert main(['check', '--data-dir', str(root)]) == 1
    output = capsys.readouterr()
    assert not output.out and 'prepare --data-dir' in output.err


def test_check_fails_when_selected_files_are_missing(tmp_path, phase2, capsys):
    selected = prepare(tmp_path, phase2)
    Path(selected['tables']['list'][0]['path']).unlink()
    assert main(['check', '--data-dir', str(tmp_path)]) == 1
    assert 'status' not in capsys.readouterr().out
