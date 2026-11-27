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


def test_archive_tools_use_selected_release_over_http(tmp_path, phase2, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlsplit
    from congressional_explorer_mcp import ARCHIVE_SEARCH_TOOLS, TOOL_NAMES

    root = tmp_path / 'data'
    selected = prepare(root, phase2)['release_id']
    state = {'release': selected}
    path = '/page?id=doc%3A1&field=body&page=3&configVersion=' + 'a' * 64
    listing = 'https://example.gov/hearings'
    calls = []

    class Origin(BaseHTTPRequestHandler):
        def reply(self, data):
            raw = json.dumps(dict(data, release_id=state['release'])).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlsplit(self.path)
            calls.append(url.path)
            if url.path == '/v1/health':
                self.reply({'searchType': 'fulltext', 'serenedb': {'connected': True}, 'index': {'sections': 4}})
            else:
                assert url.path == '/v1/section' and parse_qs(url.query) == {'url': [path]}
                self.reply({'id': 'doc:1', 'url': path, 'content': 'Health evidence.', 'publisher_url': listing})

        def do_POST(self):
            assert self.path == '/v1/search'
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert request['mode'] == 'fulltext' and request['limit'] == 1
            hits = [] if request['q'] == 'absent' else [{'id': 'doc:1', 'url': path, 'publisher_url': listing}]
            self.reply({'results': hits})

    with ThreadingHTTPServer(('127.0.0.1', 0), Origin) as backend:
        thread = Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{backend.server_port}'
        monkeypatch.setenv('CONGRESS_MCP_SEARCH_ORIGIN', origin)
        try:
            with http_server(root, phase2, False) as url:
                async def verify():
                    async with Client(url, timeout=15) as client:
                        assert {t.name for t in await client.list_tools()} == TOOL_NAMES | ARCHIVE_SEARCH_TOOLS
                        results = (await client.call_tool('search_docs', {'query': 'health', 'limit': 1})).data
                        hit = results['results'][0]
                        assert hit['url'] == origin + path and hit['publisher_url'] == listing
                        assert (await client.call_tool('docs_health')).data['release_id'] == selected
                        page = (await client.call_tool('read_section', {'url': hit['url']})).data
                        assert page['content'] == 'Health evidence.' and page['url'] == hit['url']
                        assert (await client.call_tool('search_docs', {'query': 'absent', 'limit': 1})).data['results'] == []
                        prior = len(calls)
                        rejected = await client.call_tool('read_section', {'url': 'https://elsewhere.gov/'}, raise_on_error=False)
                        assert rejected.is_error and len(calls) == prior
                        state['release'] = 'f' * 64
                        for name, args in [('docs_health', {}), ('search_docs', {'query':'absent', 'limit':1}),
                                           ('read_section', {'url':hit['url']})]:
                            outcome = await client.call_tool(name, args, raise_on_error=False)
                            assert outcome.is_error and 'archive release' in outcome.content[0].text
                        status = (await client.call_tool('get_dataset_status')).data
                        assert status['release_id'] == selected and status['archive_document_search']['search'] == 'search_docs'
                asyncio.run(verify())
        finally:
            backend.shutdown()
            thread.join()


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


def test_archive_search_timeout_decoupled_from_query_timeout(tmp_path, phase2):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import os
    from threading import Thread
    from congressional_explorer_mcp.cli import main

    root = tmp_path / 'timeout-data'
    selected = prepare(root, phase2)['release_id']
    state = {'delay': 0.4}

    class SlowOrigin(BaseHTTPRequestHandler):
        def reply(self, data):
            raw = json.dumps(dict(data, release_id=selected)).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == '/v1/health':
                self.reply({'searchType': 'hybrid', 'serenedb': {'connected': True}, 'index': {'sections': 1}})
            else:
                self.send_error(404)

        def do_POST(self):
            assert self.path == '/v1/search'
            _ = self.rfile.read(int(self.headers['Content-Length']))
            time.sleep(state['delay'])
            self.reply({'results': [{'id': 'doc:1', 'url': '/page?id=doc%3A1', 'publisher_url': 'https://example.gov/'}]})

    @contextmanager
    def start_http(extra_args, extra_env=None):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        args = [sys.executable, '-m', 'congressional_explorer_mcp.cli', 'serve',
                '--transport', 'http', '--host', '127.0.0.1', '--port', str(port),
                '--data-dir', str(root), *extra_args]
        env = dict(os.environ, CONGRESS_MCP_SEARCH_ORIGIN=origin)
        if extra_env:
            env.update(extra_env)
        url = f'http://127.0.0.1:{port}/mcp'
        with (tmp_path / f'http-timeout-{port}.log').open('w+') as log:
            process = subprocess.Popen(args, stdout=log, stderr=log, env=env)
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
                process.wait(timeout=10)

    with ThreadingHTTPServer(('127.0.0.1', 0), SlowOrigin) as backend:
        thread = Thread(target=backend.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{backend.server_port}'
        try:
            # 1a. CLI --query-timeout 0.2 --search-timeout 2.0 allows 0.4s /v1/search while keeping query_sql timeout at 0.2s
            with start_http(['--query-timeout', '0.2', '--search-timeout', '2.0']) as url:
                async def verify_cli():
                    async with Client(url, timeout=15) as client:
                        res = (await client.call_tool('search_docs', {'query': 'health', 'limit': 1})).data
                        assert len(res['results']) == 1
                        slow_sql = await client.call_tool('query_sql', {
                            'query': {'sql': 'WITH RECURSIVE t(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM t WHERE x < 50000000) SELECT count(*) AS n FROM t'}
                        }, raise_on_error=False)
                        assert slow_sql.is_error
                asyncio.run(verify_cli())

            # 1b. CONGRESS_MCP_SEARCH_TIMEOUT=2.0 env var also overrides default cleanly alongside --query-timeout 0.2
            with start_http(['--query-timeout', '0.2'], {'CONGRESS_MCP_SEARCH_TIMEOUT': '2.0'}) as url:
                async def verify_env():
                    async with Client(url, timeout=15) as client:
                        res = (await client.call_tool('search_docs', {'query': 'health', 'limit': 1})).data
                        assert len(res['results']) == 1
                asyncio.run(verify_env())

            # 2. --search-timeout 0.1 with 0.3s delay fails cleanly with Archive search is unavailable
            state['delay'] = 0.3
            with start_http(['--search-timeout', '0.1']) as url:
                async def verify_short_timeout():
                    async with Client(url, timeout=15) as client:
                        err = await client.call_tool('search_docs', {'query': 'health', 'limit': 1}, raise_on_error=False)
                        assert err.is_error
                        assert 'Archive search is unavailable. Retry shortly.' in err.content[0].text
                asyncio.run(verify_short_timeout())
        finally:
            backend.shutdown()
            thread.join()

    # 3. Invalid CONGRESS_MCP_SEARCH_TIMEOUT and --search-timeout exit 1 with actionable stderr error
    for bad_env in ('0', '-1', 'abc'):
        res = subprocess.run(
            [sys.executable, '-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(root)],
            env=dict(os.environ, CONGRESS_MCP_SEARCH_TIMEOUT=bad_env),
            capture_output=True, text=True,
        )
        assert res.returncode == 1
        assert 'Archive search timeout must be a positive number' in res.stderr

    for bad_flag in ('0', '-1'):
        res = subprocess.run(
            [sys.executable, '-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(root), '--search-timeout', bad_flag],
            capture_output=True, text=True,
        )
        assert res.returncode == 1
        assert 'Archive search timeout must be a positive number' in res.stderr

    # Verify create_server itself validates search_timeout and ignores booleans/NaN/negative
    with pytest.raises(ValueError, match='Archive search timeout must be a positive number'):
        create_server(prepare(root, phase2), search_timeout=False)
    with pytest.raises(ValueError, match='Archive search timeout must be a positive number'):
        create_server(prepare(root, phase2), search_timeout=float('nan'))
    assert callable(main)
