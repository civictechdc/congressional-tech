#!/usr/bin/env python3
"""Generate thin client packages that install the versioned server from PyPI."""
import argparse
import json
from pathlib import Path
import zipfile

APP = Path(__file__).resolve().parents[1]
REPO = APP.parents[1]


def launch(version):
    return dict(command='uvx', args=['--python', '3.12', '--from',
        f'congressional-explorer-mcp=={version}', 'congress-explorer-mcp',
        'serve', '--prepare-if-missing'])


def generated_files():
    release = json.loads((APP / 'server.json').read_text())
    identity = dict(name='congress-explorer', version=release['version'],
        description=release['description'], author={'name': 'Civic Tech DC'},
        homepage=release['websiteUrl'], repository=release['repository']['url'],
        license='Apache-2.0', keywords=['congress', 'hearings', 'legislation', 'research'])
    interface = dict(displayName='Congress Explorer', shortDescription='Explore Congress from your assistant',
        longDescription=release['description'], developerName='Civic Tech DC', category='Productivity',
        capabilities=['Read'], websiteURL=release['websiteUrl'],
        supportURL=release['repository']['url'] + '/issues',
        defaultPrompt=['Find hearings about artificial intelligence and list their witnesses.'],
        brandColor='#0b1a30', composerIcon='./assets/icon.svg', logo='./assets/icon.svg')
    entry = dict(name=identity['name'], source='./apps/explorer_mcp', description=identity['description'])
    return {
        APP / 'plugin.json': {'$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
            **identity, 'extensions': {'com.openai': dict(interface=interface,
                requires_local_executor=True, onboardingSkill='./skills/explore-congress/SKILL.md')}},
        APP / 'mcp.json': {'$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
            'mcpServers': {'congress': dict(type='stdio', **launch(release['version']))}},
        APP / '.claude-plugin/plugin.json': identity,
        APP / '.mcp.json': {'mcpServers': {'congress': dict(type='stdio', **launch(release['version']))}},
        APP / 'manifest.json': dict(manifest_version='0.4', name=identity['name'],
            display_name='Congress Explorer', version=identity['version'],
            description=identity['description'], author=identity['author'], homepage=identity['homepage'],
            documentation=identity['homepage'], support=interface['supportURL'], icon='assets/icon.png',
            license=identity['license'], keywords=identity['keywords'], tools_generated=True,
            long_description='Explore congressional metadata locally. The first question downloads the public '
                'snapshot (about 65 MiB as of October 2026); later sessions reuse it. Document bodies are not '
                'downloaded. Python and dependencies are managed by uv. macOS and Linux; Windows is not supported.',
            server=dict(type='uv', entry_point='desktop.py', mcp_config=dict(command='uv', args=[
                'run', '--project', '${__dirname}', '--python', '3.12', '--no-dev',
                'python', '${__dirname}/desktop.py'])),
            compatibility=dict(platforms=['darwin', 'linux'], runtimes={'python': '>=3.12,<3.13'})),
        REPO / '.claude-plugin/marketplace.json': dict(name='congressional-tech',
            owner=identity['author'], description='Explore public congressional data locally.', plugins=[entry]),
        REPO / '.agents/plugins/marketplace.json': dict(name='congressional-tech',
            interface={'displayName': 'Congressional Tech'}, plugins=[dict(entry,
                policy=dict(installation='AVAILABLE', authentication='ON_INSTALL'), category='Productivity')]),
    }


def build(output):
    """An explicit allowlist keeps caches, datasets, tests and credentials out."""
    version = json.loads((APP / 'server.json').read_text())['version']
    common = ['README.md', 'LICENSE', 'assets/icon.svg', 'assets/icon.png']
    plugin = common + ['plugin.json', 'mcp.json', '.claude-plugin/plugin.json', '.mcp.json', 'skills/explore-congress/SKILL.md']
    output.mkdir(parents=True, exist_ok=True)
    for suffix, paths in [('mcpb', common + ['manifest.json', 'desktop.py']), ('plugin.zip', plugin)]:
        target = output / f'congress-explorer-{version}.{suffix}'
        contents = {name: (APP / name).read_bytes() for name in paths}
        if suffix == 'mcpb':
            contents['pyproject.toml'] = ('[project]\nname = "congress-explorer-desktop"\n'
                f'version = "{version}"\nrequires-python = ">=3.12,<3.13"\n'
                f'dependencies = ["congressional-explorer-mcp=={version}"]\n').encode()
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(contents.items()):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check committed manifests without rewriting them')
    parser.add_argument('--output-dir', type=Path, help='Also build .mcpb and compatible plugin ZIP')
    args = parser.parse_args()
    for path, value in generated_files().items():
        content = json.dumps(value, indent=2) + '\n'
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f'Stale desktop metadata: {path}. Run scripts/build_desktop.py.')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if args.output_dir:
        build(args.output_dir)


if __name__ == '__main__':
    main()
