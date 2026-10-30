#!/usr/bin/env python3
"""Launch every packaged client configuration outside the checkout over real stdio."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import zipfile

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]


async def check(config, root, data, first):
    # Resolve only the client's documented plugin-directory placeholder.
    def expand(value):
        for variable in ('${PLUGIN_ROOT}', '${CLAUDE_PLUGIN_ROOT}', '${__dirname}'):
            value = value.replace(variable, str(root))
        return value
    publication = REPO / 'model/fixtures/archive-contract/current/manifest.json' if first else root / 'does-not-exist.json'
    transport = StdioTransport(config['command'], [expand(a) for a in config['args']] +
        ['--publication', str(publication)], env=dict(os.environ, CONGRESS_MCP_DATA_DIR=str(data)),
        cwd=str(root.parent), keep_alive=False)
    async with Client(transport, timeout=120) as client:
        assert len(await client.list_tools()) == 6
        assert (data / 'selection.json').exists() != first, 'Discovery must not download data'
        info = (await client.call_tool('get_dataset_info')).data
        rows = (await client.call_tool('query_sql', {'query': {'sql': 'SELECT filename FROM documents LIMIT 1'}})).data
        assert len(rows['rows']) == 1
        return info['release_id']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    version = json.loads((APP / 'server.json').read_text())['version']
    with tempfile.TemporaryDirectory(prefix='congress desktop ') as temp:
        base = Path(temp)
        for suffix, manifests in [('mcpb', ['manifest.json']), ('plugin.zip', ['mcp.json', '.mcp.json'])]:
            root = base / suffix
            with zipfile.ZipFile(args.directory / f'congress-explorer-{version}.{suffix}') as archive:
                assert not any(n.endswith('.parquet') or '.venv/' in n for n in archive.namelist())
                archive.extractall(root)
            for name in manifests:
                manifest = json.loads((root / name).read_text())
                config = manifest['server']['mcp_config'] if suffix == 'mcpb' else manifest['mcpServers']['congress']
                data = base / ('data-' + name)
                release = asyncio.run(check(config, root, data, True))
                assert asyncio.run(check(config, root, data, False)) == release
                print(json.dumps(dict(archive=suffix, manifest=name, release_id=release, status='ok')))


if __name__ == '__main__':
    main()
