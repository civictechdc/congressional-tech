"""Prepare once from a publication; serve its selected release locally over stdio."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from . import __version__
from .models import ExplorerError
from .release import PUBLICATION, load_selection, prepare


def client_config(data_dir, client):
    """Print configuration only; never change another application's settings."""
    # Do not resolve the Python symlink: its virtualenv owns the dependencies.
    command = str(Path(sys.executable).absolute())
    args = ['-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(data_dir)]
    if client == 'codex':
        return f'[mcp_servers.congress]\ncommand = {json.dumps(command, ensure_ascii=False)}\nargs = {json.dumps(args, ensure_ascii=False)}'
    return json.dumps({'mcpServers': {'congress': {'command': command, 'args': args}}}, indent=2)


async def check_installation(data_dir):
    """Exercise the installed entry point, MCP handshake, and an actual data read."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(sys.executable,
        ['-m', 'congressional_explorer_mcp.cli', 'serve', '--data-dir', str(data_dir)], keep_alive=False)
    async with asyncio.timeout(30):
        async with Client(transport) as client:
            tools = await client.list_tools()
            info = (await client.call_tool('get_dataset_info')).data
            result = (await client.call_tool('query_sql', {'query': {
                'sql': 'SELECT filename FROM documents LIMIT 1'}})).data
            return dict(status='ok', version=__version__, release_id=info['release_id'],
                data_dir=str(data_dir), tables=len(info['tables']),
                tools=[tool.name for tool in tools], sample_rows=len(result['rows']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    sub = parser.add_subparsers(dest='command', required=True)
    descriptions = dict(prepare='Download or refresh the published data', inspect='Show the selected release',
        serve='Run the local stdio MCP server', config='Print client configuration without changing settings',
        check='Check the installed server and read one data row over MCP')
    for name, description in descriptions.items():
        command = sub.add_parser(name, help=description)
        command.add_argument('--data-dir', type=Path, default=Path.home() / '.cache/congress-explorer-mcp')
        if name == 'config':
            command.add_argument('--client', choices=('codex', 'claude-desktop', 'claude-code', 'cursor'), required=True)
        if name == 'prepare':
            command.add_argument('--publication', default=PUBLICATION, help='Current archive pointer or release manifest, URL or local path')
            command.add_argument('--archive-origin', help='Body archive origin; inferred for remote publications')
        if name == 'serve':
            command.add_argument('--query-timeout', type=float, default=10.0)
    args = parser.parse_args(argv)
    args.data_dir = args.data_dir.expanduser().absolute()
    try:
        if args.command == 'config':
            print(client_config(args.data_dir, args.client))
            return 0
        if args.command == 'prepare':
            selection = prepare(args.data_dir, args.publication, archive_origin=args.archive_origin)
        else:
            if not (args.data_dir / 'selection.json').exists():
                raise ExplorerError(f'No prepared data in {args.data_dir}. Run congress-explorer-mcp prepare --data-dir {json.dumps(str(args.data_dir))} first.')
            selection = load_selection(args.data_dir)
        if args.command == 'check':
            try:
                result = asyncio.run(check_installation(args.data_dir))
            except Exception as error:
                raise ExplorerError(f'MCP installation check failed: {error}. Run inspect with the same --data-dir to check the selected release.') from error
            print(json.dumps(result, indent=2))
            return 0
        if args.command == 'serve':
            from .server import create_server
            create_server(selection, timeout=args.query_timeout).run(transport='stdio', show_banner=False)
        else:
            print(json.dumps(dict(release_id=selection['release_id'], data_dir=str(args.data_dir.absolute()),
                tables={name: sum(part['rows'] for part in parts) for name, parts in selection['tables'].items()}), indent=2))
        return 0
    except (ExplorerError, OSError, ValueError, KeyError, TypeError) as error:
        print(f'Congress Explorer: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
