"""Prepare once from a publication; serve its selected release locally over stdio."""
import argparse
import json
from pathlib import Path
import sys

from .models import ExplorerError
from .release import PUBLICATION, load_selection, prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'inspect', 'serve'):
        command = sub.add_parser(name)
        command.add_argument('--data-dir', type=Path, default=Path.home() / '.cache/congress-explorer-mcp')
        if name == 'prepare':
            command.add_argument('--publication', default=PUBLICATION, help='Current archive pointer or release manifest, URL or local path')
            command.add_argument('--archive-origin', help='Body archive origin; inferred for remote publications')
        if name == 'serve':
            command.add_argument('--query-timeout', type=float, default=10.0)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            selection = prepare(args.data_dir, args.publication, archive_origin=args.archive_origin)
        else:
            selection = load_selection(args.data_dir)
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
