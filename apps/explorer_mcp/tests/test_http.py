"""Exercise the CLI's real HTTP transport and compare it with local tool results."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

from fastmcp import Client
import httpx2 as httpx
import pytest

from congressional_explorer_mcp import __version__
from congressional_explorer_mcp.release import prepare
from congressional_explorer_mcp.server import create_server


@contextmanager
def http_server(root, publication, lazy):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    args = [sys.executable, '-m', 'congressional_explorer_mcp.cli', 'serve',
            '--transport', 'http', '--host', '127.0.0.1', '--port', str(port),
            '--data-dir', str(root)]
    if lazy:
        args += ['--prepare-if-missing', '--publication', str(publication)]
    url = f'http://127.0.0.1:{port}/mcp'
    with (root.parent / f'http-{port}.log').open('w+') as log:
        process = subprocess.Popen(args, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if httpx.get(url, timeout=.5).status_code == 405:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.05)
            else:
                log.seek(0)
                pytest.fail(f'HTTP server did not become ready: {log.read()}')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.mark.parametrize('lazy', [False, True])
def test_http_tools_and_stateless_clients_match_local(tmp_path, phase2, lazy):
    root = tmp_path / 'http-data'
    selected = prepare(tmp_path / 'local-data', phase2)
    if not lazy:
        prepare(root, phase2)
    with http_server(root, phase2, lazy) as url:
        if lazy:
            assert not (root / 'selection.json').exists()
        else:
            ready = httpx.get(url.removesuffix('/mcp') + '/ready')
            assert ready.status_code == 200
            assert ready.json() == dict(status='ready', version=__version__, release_id=selected['release_id'])
        # A stateless transport must not issue a process-specific session ID.
        response = httpx.post(url, headers={'Accept': 'application/json, text/event-stream'},
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-06-18', 'capabilities': {},
                'clientInfo': {'name': 'http-test', 'version': '1'},
            }})
        assert response.status_code == 200
        assert 'mcp-session-id' not in response.headers
        assert response.json()['result']['serverInfo']['version'] == __version__

        async def run():
            config = json.loads((Path(__file__).parents[1] / 'web/mcp.json').read_text())
            assert config['mcpServers']['congress']['type'] == 'streamable-http'
            config['mcpServers']['congress']['url'] = url
            async with Client(config) as remote, Client(create_server(selected)) as local:
                tools = await remote.list_tools()
                assert {tool.name for tool in tools} == {tool.name for tool in await local.list_tools()}
                if lazy:
                    assert not (root / 'selection.json').exists()
                for name, arguments in [
                    ('get_overview', {}),
                    ('get_dataset_status', {}),
                    ('get_dataset_info', {}),
                    ('search_documents', {'query': {'measure_key': '119-hr-1'}}),
                    ('search_entities', {'query': {'table': 'witnesses', 'text': 'Alex'}}),
                    ('get_entity', {'query': {'table': 'bills', 'id': '119-hr-1'}}),
                    ('get_entity', {'query': {'table': 'bills', 'id': '119-hr-1', 'mode': 'summary'}}),
                    ('query_sql', {'query': {'sql': 'SELECT count(*) AS n FROM documents'}}),
                ]:
                    assert (await remote.call_tool(name, arguments)).data == (await local.call_tool(name, arguments)).data
                found = (await remote.call_tool('search_documents', {'query': {'measure_key': '119-hr-1'}})).data
                arguments = {'query': found['rows'][0]['reference']}
                assert (await remote.call_tool('get_document', arguments)).data == (await local.call_tool('get_document', arguments)).data
                error = await remote.call_tool('query_sql', {'query': {'sql': 'DROP VIEW documents'}}, raise_on_error=False)
                assert error.is_error and 'read-only SELECT' in error.content[0].text
                for query, expected in [({'sql': 'SELECT FROM'}, 'Parser Error'),
                    ({'sql': 'SELECT imaginary_column FROM bills'}, 'imaginary_column'),
                    ({'sql': 'SELECT * FROM imaginary_table'}, 'imaginary_table'),
                    ({'sql': 'SELECT ? AS n'}, 'parameters: 1'),
                    ({'sql': 'SELECT ?::INTEGER AS n', 'parameters': ['bad']}, 'Conversion Error')]:
                    error = await remote.call_tool('query_sql', {'query': query}, raise_on_error=False)
                    assert error.is_error and expected in error.content[0].text
                async with Client(url) as second:
                    results = await asyncio.gather(*[
                        client.call_tool('query_sql', {'query': {'sql': f'SELECT {n} AS n'}})
                        for n, client in enumerate((remote, second))
                    ])
                    assert [result.data['rows'] for result in results] == [[{'n': 0}], [{'n': 1}]]
        asyncio.run(run())


def test_http_warm_startup_warms_replica_before_accepting_requests(tmp_path, phase2):
    start_script = (Path(__file__).parents[1] / 'cloudflare/start.sh').read_text()
    assert '--warm' in start_script
    root = tmp_path / 'warm-http-data'
    selected = prepare(root, phase2)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    args = [sys.executable, '-m', 'congressional_explorer_mcp.cli', 'serve',
            '--transport', 'http', '--warm', '--host', '127.0.0.1', '--port', str(port),
            '--data-dir', str(root)]
    url = f'http://127.0.0.1:{port}/mcp'
    with (tmp_path / f'http-warm-{port}.log').open('w+') as log:
        process = subprocess.Popen(args, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    if httpx.get(url, timeout=.5).status_code == 405:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.05)
            else:
                log.seek(0)
                pytest.fail(f'Warm HTTP server did not become ready: {log.read()}')

            async def run():
                # Direct /mcp traffic (without calling /ready first) reaches an already-warmed replica.
                async with Client(url) as client:
                    ballots = (await client.call_tool('get_member_ballots', {'query': {'limit': 1}})).data
                    assert ballots['release_id'] == selected['release_id']
                    assert len(ballots['rows']) == 1
            asyncio.run(run())
            ready = httpx.get(url.removesuffix('/mcp') + '/ready')
            assert ready.status_code == 200
            assert ready.json() == dict(status='ready', version=__version__, release_id=selected['release_id'])
        finally:
            process.terminate()
            process.wait(timeout=10)
