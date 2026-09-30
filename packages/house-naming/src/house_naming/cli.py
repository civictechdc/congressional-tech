"""JSON command-line interface for the single bundled convention set."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .catalog import check_catalog, load_guide
from .compiler import filename_schema, records_schema
from .engine import Engine
from .errors import NamingError
from .io import dumps, read_json


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise NamingError('usage', message)


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog='house-naming', description='Offline House naming guide: 2012 source conventions')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='Validate bundled catalog structure and reference integrity')
    commands.add_parser('kinds', help='List all supported naming kinds')
    for command in ('validate', 'render'):
        sub = commands.add_parser(command)
        sub.add_argument('record', help='JSON record file, or - for stdin')
        if command == 'render':
            sub.add_argument('--plain', action='store_true', help='Output just the filename or URL')
    commands.add_parser('parse').add_argument('filename', help='Exact basename, not a path or URL')
    sub = commands.add_parser('extract', help='Read literal fields, uncertainty and retained source spans')
    sub.add_argument('filename', help='Literal source basename, including nonconforming names')
    sub.add_argument('--source-url', help='Optional original source URL for publisher conventions; no network requests')
    sub.add_argument('--member-surnames', help='Optional Congress-keyed surname JSON file, or - for stdin (at most 64 KiB)')
    sub = commands.add_parser('lookup')
    sub.add_argument('context')
    sub.add_argument('token')
    for command, arg in [('contexts', 'token'), ('committee', 'folder_code'),
                         ('source', 'source_id'), ('examples', 'value')]:
        commands.add_parser(command).add_argument(arg)
    sub = commands.add_parser('schema', help='Emit the standalone record schema')
    sub.add_argument('--filename-lexical', action='store_true', help='Emit the weaker filename candidate schema instead')

    try:
        args = parser.parse_args(argv)
        if args.command == 'check':
            data = {'status': 'passed', **check_catalog(load_guide())}
        elif args.command == 'schema':
            compile_schema = filename_schema if args.filename_lexical else records_schema
            data = compile_schema(load_guide())
        else:
            engine = Engine()
            command = args.command
            if command == 'kinds':
                data = engine.kinds()
            elif command in ('validate', 'render'):
                record = read_json(args.record)
                if command == 'validate':
                    data = {'valid': True, 'record': engine.validate(record)}
                else:
                    output = engine.render(record)
                    if args.plain:
                        print(output)
                        return 0
                    rule = engine.guide['patterns'][record['kind']]
                    data = {'kind': record['kind'], 'action': rule['action'], 'output': output,
                            'requires_interpretation': rule['requires_interpretation'], 'decisions': rule['decisions']}
            elif command == 'parse':
                data = engine.parse(args.filename)
                sys.stdout.write(dumps(data))
                return 0 if data['valid'] else 1
            elif command == 'extract':
                reference = read_json(args.member_surnames) if args.member_surnames else None
                data = engine.extract(args.filename, member_surnames=reference, source_url=args.source_url)
            elif command == 'lookup':
                data = engine.lookup(args.context, args.token)
            elif command == 'contexts':
                data = engine.contexts(args.token)
            elif command == 'committee':
                data = engine.committee(args.folder_code)
            elif command == 'source':
                data = engine.source(args.source_id)
            else:
                data = engine.examples(args.value)
        sys.stdout.write(dumps(data))
        return 0
    except NamingError as exc:
        sys.stderr.write(dumps({'error': exc.as_dict()}))
        return 2 if exc.code in ('usage', 'input-too-large', 'invalid-catalog', 'extraction-limit') else 1
    except BrokenPipeError:
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        sys.stderr.write(dumps({'error': {'code': 'io-or-configuration-error', 'message': str(exc), 'details': []}}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
