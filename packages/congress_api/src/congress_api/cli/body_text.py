"""Plan or execute the body-text producer (data model §6.6) against a local catalog.

    .venv/bin/python -m congress_api.cli.body_text --spec spec.json --plan
    .venv/bin/python -m congress_api.cli.body_text --spec spec.json --execute \\
        --durable-unreadable-root DIR [--ocr] [--parser-workers N] [--parser-memory-bytes BYTES] \\
        [--max-batches N]

The spec names the inputs as `congress_api.cli.readings` does: ``captures`` (an exact native pin or
a Parquet path), ``work``, ``decided_at``, the apply authority ``catalog_root`` and ``tables``
(``readings`` and ``body_text``), and exactly one body source: ``local_root`` or ``origin`` (the
archive origin, `congress_api.lake.body_text.ORIGIN`). ``filename_readings`` (pin or path) orders
the work newest Congress first; ``body_listing``, ``unreadable_files``, ``max_cache_bytes``,
``max_batch_items`` and ``parser_memory_bytes`` are optional. ``--ocr`` reads pages that need OCR with the declared Apple Vision engine; without
it such a body stays listed. Like the readings command it needs a local-only engine, so it cannot
move a shared catalog's heads, and it writes no gate-5 producer record.
"""
import argparse
import json
import os
from pathlib import Path

from congress_api.lake import body_text
from congress_api.retention.body_store import BodyStore, LocalAdapter

REQUIRED = {'captures', 'work', 'decided_at', 'catalog_root', 'tables'}
OPTIONAL = {'local_root', 'origin', 'body_listing', 'filename_readings', 'unreadable_files', 'max_cache_bytes',
            'max_batch_items', 'parser_memory_bytes'}


def main(argv=None):
    from docspec_client.client import NativeDatasets
    from congress_api.parsers.body_text import VISION_STRATEGY
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--engine-config', default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--plan', action='store_true', help='Only build and count the ordered work list')
    actions.add_argument('--execute', action='store_true', help='Read, stage and append batches in work-list order')
    parser.add_argument('--durable-unreadable-root', type=Path,
                        help='Explicit local durable raw store for unreadable decisions (required with --execute)')
    parser.add_argument('--ocr', action='store_true', help='Recognize pages that need OCR with Apple Vision')
    parser.add_argument('--parser-workers', type=int, default=1, help='Persistent supervised workers per batch')
    parser.add_argument('--parser-memory-bytes', type=int,
                        help='Total memory budget across body-text workers (defaults to body_text.PARSER_MEMORY_BYTES)')
    parser.add_argument('--max-batches', type=int, help='Stop after this many batches (status partial)')
    args = parser.parse_args(argv)
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    if args.execute != (args.durable_unreadable_root is not None):
        parser.error('--execute requires --durable-unreadable-root, and only it')
    spec = json.loads(args.spec.read_text())
    if not isinstance(spec, dict) or not REQUIRED <= spec.keys() or spec.keys() - REQUIRED - OPTIONAL:
        parser.error('Body-text spec requires captures, work, decided_at, catalog_root and tables')
    if ('local_root' in spec) == ('origin' in spec):
        parser.error('Body-text spec names exactly one body source: local_root or origin')
    if 'body_listing' in spec and 'local_root' in spec:
        parser.error('body_listing applies to origin reads, not local_root')
    with NativeDatasets.from_config(args.engine_config) as engine:
        if engine.remote is not None:
            parser.error('This local body-text command requires a local-only engine configuration')
        if engine.limits is None:
            parser.error('Parser workers require an explicit pinned native memory limit')
        memory = (args.parser_memory_bytes if args.parser_memory_bytes is not None
                  else spec.get('parser_memory_bytes', body_text.PARSER_MEMORY_BYTES))
        try:
            body_text.ParserWorkerPool.validate_budget(args.parser_workers, memory, body_text.WORKER_MEMORY_BYTES)
        except ValueError as error:
            parser.error(str(error))
        run_spec = {k: v for k, v in spec.items() if k != 'parser_memory_bytes'}
        result = body_text.run(**run_spec, engine=engine, execute=args.execute, max_batches=args.max_batches,
            unreadable_store=BodyStore(LocalAdapter(args.durable_unreadable_root)) if args.execute else None,
            parser_workers=args.parser_workers, parser_memory_bytes=memory,
            strategy=VISION_STRATEGY if args.ocr else None)
    print(json.dumps(result, default=str, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
