#!/usr/bin/env python3
"""Launch the local desktop packages outside the checkout over real stdio."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import zipfile

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from congressional_explorer_mcp import TOOL_NAMES
from congressional_explorer_mcp.validation import check_client

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]


async def check(config, root, data, first, env, publication, plan, require_research):
    # Resolve only the client's documented plugin-directory placeholder.
    def expand(value):
        for variable in ('${PLUGIN_ROOT}', '${CLAUDE_PLUGIN_ROOT}', '${__dirname}'):
            value = value.replace(variable, str(root))
        return value
    publication = publication if first else root / 'does-not-exist.json'
    transport = StdioTransport(config['command'], [expand(a) for a in config['args']] +
        ['--publication', str(publication)], env=dict(env, CONGRESS_MCP_DATA_DIR=str(data)),
        cwd=str(root.parent), keep_alive=False)
    async with Client(transport, timeout=120) as client:
        assert {tool.name for tool in await client.list_tools()} == TOOL_NAMES
        assert (data / 'selection.json').exists() != first, 'Discovery must not download data'
        result = await check_client(client, plan=plan, require_research=require_research)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--wheel', type=Path, help='Use an unpublished wheel for pre-release checks')
    parser.add_argument('--publication', default=str(REPO / 'model/fixtures/archive-contract/current/manifest.json'))
    parser.add_argument('--probe-plan', type=Path)
    parser.add_argument('--require-research', action='store_true')
    args = parser.parse_args()
    plan = json.loads(args.probe_plan.read_text()) if args.probe_plan else None
    version = json.loads((APP / 'server.json').read_text())['version']
    with tempfile.TemporaryDirectory(prefix='congress desktop ') as temp:
        base = Path(temp)
        env = dict(os.environ, UV_CACHE_DIR=str(base / 'uv-cache'))
        if args.wheel:
            env['UV_FIND_LINKS'] = str(args.wheel.resolve().parent)
        for suffix, manifests in [('mcpb', ['manifest.json']), ('plugin.zip', ['mcp.json', '.mcp.json'])]:
            root = base / suffix
            with zipfile.ZipFile(args.directory / f'congress-explorer-{version}.{suffix}') as archive:
                assert not any(n.endswith('.parquet') or '.venv/' in n or n.startswith('src/') for n in archive.namelist())
                archive.extractall(root)
            for name in manifests:
                manifest = json.loads((root / name).read_text())
                config = manifest['server']['mcp_config'] if suffix == 'mcpb' else manifest['mcpServers']['congress']
                if suffix == 'plugin.zip':
                    script = ' '.join(config['args'])
                    assert config['command'] == 'sh' and '$HOME/.local/bin' in script and '/opt/homebrew/bin' in script
                data = base / ('data-' + name)
                result = asyncio.run(check(config, root, data, True, env, args.publication, plan, args.require_research))
                assert asyncio.run(check(config, root, data, False, env, args.publication, plan, args.require_research))['release_id'] == result['release_id']
                print(json.dumps(dict(archive=suffix, manifest=name, **result)))


if __name__ == '__main__':
    main()
