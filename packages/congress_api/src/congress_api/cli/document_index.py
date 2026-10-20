"""Local archive filename/document index command."""

import argparse
import json
from pathlib import Path

from congress_api.cli.raw_progress import ProgressLog
from congress_api.cli import raw_sync
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.document_index import (
    build,
    refresh_filename_metadata,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build or refresh raw-document filename tables"
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--inventory-dir",
        type=Path,
        help="Directory containing filenames.parquet and urls.parquet",
    )
    parser.add_argument('--rebuild', '--repair', dest='repair', action='store_true',
                        help='Explicitly reinterpret retained metadata with current rules')
    parser.add_argument('--inspect-bodies', action='store_true', help='Also inspect retained document contents')
    raw_sync.add_catalog_modes(parser.add_mutually_exclusive_group())
    parser.add_argument('--native-config', type=Path, help='Explicit maintained native runtime for raw archive updates')
    parser.add_argument('--catalog-directory', type=Path, help='Retain exact native catalog continuation inputs here')
    # Old invocations remain valid, but all refresh modes use the same updater.
    for flag in ('--documents-only', '--metadata-only', '--source-metadata-only'):
        parser.add_argument(flag, action='store_true', help=argparse.SUPPRESS)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    native_mode = (args.native_config is not None or raw_sync.operation_mode(args) != 'capture'
                   or any((args.archive / key).exists() for key in ('indexes/raw.json', 'indexes/captures.parquet', 'indexes/catalog.json')))
    if native_mode:
        if args.inventory_dir is not None:
            parser.error('Inventory import and native raw catalog operations are separate explicit operations')
        if args.repair or args.inspect_bodies:
            parser.error('Full rebuild and body inspection are not operational routes; qualify sources or name a source rule upgrade')
        if args.native_config is None:
            parser.error('--native-config is required for raw archive updates; adoption is explicit')
        forwarded = ['--native-config', str(args.native_config), '--summary',
                     str(args.archive / 'status/document-index.summary.json')]
        if args.catalog_directory is not None:
            forwarded.extend(['--catalog-directory', str(args.catalog_directory)])
        mode = raw_sync.operation_mode(args)
        if mode == 'capture':
            forwarded.append('--update-only')
        elif mode == 'qualify-sources':
            forwarded.append('--qualify-sources')
        elif mode in {'adopt-raw', 'adopt-catalog', 'upgrade-source-rules'}:
            forwarded.extend(['--' + mode, str(getattr(args, mode.replace('-', '_')))])
        request = raw_sync.parser().parse_args(forwarded)
        with ProgressLog(args.archive / 'status/document-index.json') as log:
            return raw_sync.run(request, log, store=LocalStore(args.archive))
    with ProgressLog(args.archive / 'status/document-index.json'):
        if args.inventory_dir is not None:
            result = build(args.archive, args.inventory_dir, workers=args.workers, inspect_bodies=args.inspect_bodies)
        elif (args.archive / 'indexes/document-filenames.parquet').exists():
            # A standalone filename table can still be reinterpreted without an archive.
            result = refresh_filename_metadata(args.archive, workers=args.workers, inspect_bodies=args.inspect_bodies, repair=args.repair)
        else:
            parser.error('An archive capture index or existing filename table is required')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
