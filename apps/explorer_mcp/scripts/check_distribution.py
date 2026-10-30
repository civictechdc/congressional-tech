#!/usr/bin/env python3
"""Install a wheel or the PyPI release outside the checkout and check real MCP access."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import zipfile

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path, nargs='?', help='Omit to verify the versioned PyPI release')
    args = parser.parse_args()
    registry = json.loads((APP / 'server.json').read_text())
    distribution = str(args.wheel.resolve()) if args.wheel else f"congressional-explorer-mcp=={registry['version']}"
    if args.wheel:
        with zipfile.ZipFile(distribution) as archive:
            metadata = archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode()
            assert f"Version: {registry['version']}\n" in metadata
            assert f"mcp-name: {registry['name']}" in metadata
            assert any(n.endswith('/licenses/LICENSE') for n in archive.namelist())
    with tempfile.TemporaryDirectory(prefix='congress-install-') as temporary:
        root = Path(temporary)
        env = dict(os.environ, UV_TOOL_DIR=str(root / 'tools'), UV_TOOL_BIN_DIR=str(root / 'bin'),
            UV_CACHE_DIR=str(root / 'uv-cache'))
        subprocess.run(['uv', '--no-config', 'tool', 'install', '--python', '3.12',
            '--default-index', 'https://pypi.org/simple', distribution], cwd=root, env=env, check=True)
        command = root / 'bin/congress-explorer-mcp'
        data = root / 'Congress data'
        def run(*args):
            return subprocess.check_output([str(command), *args], cwd=root, env=env, text=True)
        run('prepare', '--publication', str(REPO / 'model/fixtures/archive-contract/current/manifest.json'), '--data-dir', str(data))
        config = json.loads(run('config', '--client', 'claude-desktop', '--data-dir', str(data)))['mcpServers']['congress']
        assert Path(config['command']).is_absolute()
        assert config == tomllib.loads(run('config', '--client', 'codex', '--data-dir', str(data)))['mcp_servers']['congress']
        result = json.loads(run('check', '--data-dir', str(data)))
        assert result['status'] == 'ok' and result['sample_rows'] == 1 and len(result['tools']) == 6
        assert result['version'] == registry['version'] == registry['packages'][0]['version']
        alias_version = subprocess.check_output([str(root / 'bin/congressional-explorer-mcp'), '--version'], text=True)
        assert registry['version'] in alias_version
        print(json.dumps(dict(result, distribution=Path(distribution).name, configuration='json-and-toml'), indent=2))


if __name__ == '__main__':
    main()
