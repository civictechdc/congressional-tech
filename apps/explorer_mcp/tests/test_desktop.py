"""Desktop setup must stay responsive, retry failures, and reuse selected data."""
import asyncio
from pathlib import Path
import sys
from threading import Event

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest
from congressional_explorer_mcp import TOOL_NAMES

from congressional_explorer_mcp.server import create_server


def test_desktop_entry_prepares_on_first_call_and_reuses_snapshot(tmp_path, phase2):
    data = tmp_path / 'Congress data'
    async def connect(publication, first):
        transport = StdioTransport(sys.executable, [str(Path(__file__).parents[1] / 'desktop.py'),
            '--data-dir', str(data), '--publication', str(publication)], keep_alive=False)
        async with Client(transport) as client:
            assert {tool.name for tool in await client.list_tools()} == TOOL_NAMES
            assert (data / 'selection.json').exists() != first
            info = (await client.call_tool('get_dataset_info')).data
            rows = (await client.call_tool('query_sql', {'query': {'sql': 'SELECT filename FROM documents LIMIT 1'}})).data
            assert len(rows['rows']) == 1
            return info['release_id']
    release = asyncio.run(connect(phase2, True))
    # A missing publication would fail if a warm start tried to refresh.
    assert asyncio.run(connect(tmp_path / 'no-publication.json', False)) == release


def test_first_setup_failure_can_retry_and_concurrent_calls_prepare_once(tmp_path, phase2, monkeypatch):
    from congressional_explorer_mcp import server
    from congressional_explorer_mcp.release import prepare
    attempts = []
    def flaky(data, publication):
        attempts.append(publication)
        if len(attempts) == 1:
            raise OSError('Temporary download failure')
        return prepare(data, publication)
    monkeypatch.setattr(server, 'prepare', flaky)
    async def run():
        async with Client(create_server(data_dir=tmp_path, publication=phase2)) as client:
            assert {tool.name for tool in await client.list_tools()} == TOOL_NAMES and not attempts
            with pytest.raises(Exception, match='Temporary download failure'):
                await client.call_tool('get_dataset_info')
            results = await asyncio.gather(*(client.call_tool('get_dataset_info') for _ in range(3)))
            assert len({r.data['release_id'] for r in results}) == 1
    asyncio.run(run())
    assert len(attempts) == 2


def test_existing_corrupt_selection_is_not_overwritten(tmp_path, phase2):
    (tmp_path / 'selection.json').write_text('broken')
    async def run():
        async with Client(create_server(data_dir=tmp_path, publication=phase2)) as client:
            with pytest.raises(Exception):
                await client.call_tool('get_dataset_info')
    asyncio.run(run())
    assert (tmp_path / 'selection.json').read_text() == 'broken'


def test_cancelled_first_call_finishes_preparation_without_a_second_writer(tmp_path, phase2, monkeypatch):
    from congressional_explorer_mcp import server
    from congressional_explorer_mcp.release import prepare
    started, finish = Event(), Event()
    attempts = []
    def slow(data, publication):
        attempts.append(publication)
        started.set()
        assert finish.wait(5), 'Test did not release the preparation thread'
        return prepare(data, publication)
    monkeypatch.setattr(server, 'prepare', slow)
    async def run():
        async with Client(create_server(data_dir=tmp_path, publication=phase2)) as client:
            first = asyncio.create_task(client.call_tool('get_dataset_info'))
            try:
                async with asyncio.timeout(5):
                    while not started.is_set():
                        await asyncio.sleep(.01)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            finally:
                finish.set()
            result = await client.call_tool('get_dataset_info')
            assert result.data['release_id']
    asyncio.run(run())
    assert len(attempts) == 1


def test_plugin_manifests_supply_gui_path_for_uvx_discovery():
    import json
    root = Path(__file__).parents[1]
    for name in ('mcp.json', '.mcp.json'):
        config = json.loads((root / name).read_text())['mcpServers']['congress']
        assert config['command'] == 'sh'
        script = config['args'][1]
        for entry in ('$PATH', '$HOME/.local/bin', '$HOME/.cargo/bin', '/opt/homebrew/bin', '/usr/local/bin'):
            assert entry in script


def test_built_plugins_keep_web_and_desktop_transports_separate(tmp_path):
    import json
    import subprocess
    import zipfile
    root = Path(__file__).parents[1]
    release = json.loads((root / 'server.json').read_text())
    subprocess.run([sys.executable, str(root / 'scripts/build_desktop.py'), '--check',
                    '--output-dir', str(tmp_path)], check=True, capture_output=True)
    for name, local in [('congress-explorer', True), ('congress-explorer-web', False)]:
        with zipfile.ZipFile(tmp_path / f'{name}-{release["version"]}.plugin.zip') as archive:
            manifest = json.loads(archive.read('plugin.json'))
            config = json.loads(archive.read('mcp.json'))['mcpServers']['congress']
            extension = manifest['extensions']['com.openai']
            assert manifest['name'] == name
            assert extension['requires_local_executor'] is local
            assert archive.read(extension['onboardingSkill'].removeprefix('./')) == (
                root / 'skills/explore-congress/SKILL.md').read_bytes()
            for asset in ('composerIcon', 'logo'):
                assert archive.read(extension['interface'][asset].removeprefix('./'))
            assert not any(path.startswith(('src/', 'cloudflare/', 'web/', '.venv/'))
                           for path in archive.namelist())
            if local:
                assert config['type'] == 'stdio' and 'url' not in config
                assert json.loads(archive.read('.mcp.json'))['mcpServers']['congress'] == config
            else:
                assert config == release['remotes'][0]
                assert config['type'] == 'streamable-http'
                assert 'command' not in config and '.mcp.json' not in archive.namelist()
