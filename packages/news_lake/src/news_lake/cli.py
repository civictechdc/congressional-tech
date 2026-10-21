"""Production CLI for ``news_lake`` backed by ``DocSpecLake`` and ``DocSpecNewsViews``.

``DocSpecLake`` and ``DocSpecNewsViews`` are the single production runtime owner
for the 10 raw news datasets, 3 relational bridge datasets (``entity_roots``,
``selected_mentions``, ``survivor_items``), 2 native views
(``politician_articles``, ``coverage_daily``), and C5-authorized native Parquet
exports.

The PyIceberg table coordinator (``news_lake.storage.coordinator``) and pure-Python
view evaluators (``news_lake.analysis.views`` when ``docspec_views=None``) are
retained as the reference differential test oracle (invoked by ``--verify-oracle``
and the ``test_docspec_backend`` parity suite).
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from news_lake.analysis.export import export_release
from news_lake.analysis.views import coverage_daily, politician_articles
from news_lake.context import format_instant
from news_lake.contract.records import parse_jsonl
from news_lake.storage.control import ControlStore
from news_lake.storage.coordinator import Coordinator
from news_lake.storage.docspec_backend import (
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    DocSpecClient,
    DocSpecLake,
    DocSpecNewsViews,
)
from news_lake.storage.releases import publish_release, read_release


def _default_control_path(workspace):
    return Path(workspace).resolve() / 'control.sqlite'


def _load_json_arg(value, default):
    if value is None:
        return default
    path = Path(value)
    if path.is_file():
        return json.loads(path.read_text(encoding='utf-8'))
    return json.loads(value)


def _cmd_publish(args):
    workspace = Path(args.workspace).resolve()
    control_path = Path(args.control).resolve() if args.control else _default_control_path(workspace)
    control_path.parent.mkdir(parents=True, exist_ok=True)
    raw = Path(args.input).read_text(encoding='utf-8')
    records = parse_jsonl(raw)
    recorded_at = args.recorded_at or format_instant(datetime.now(timezone.utc))
    selections = _load_json_arg(args.selections, [])
    checkpoints = _load_json_arg(args.checkpoints, [])

    control = ControlStore(control_path)
    with DocSpecClient(workspace, binary=args.binary) as client:
        lake = DocSpecLake(
            client,
            lifecycle_compact_interval=args.lifecycle_compact_interval,
        )
        coordinator = Coordinator(lake, control)
        release = publish_release(
            coordinator,
            records,
            release_id=args.release_id,
            recorded_at=recorded_at,
            selections=selections,
            checkpoints=checkpoints,
        )
        return {
            'backend': 'docspec',
            'release': release,
            'lifecycle_compactions': lake.lifecycle_compactions,
        }


def _cmd_views(args):
    workspace = Path(args.workspace).resolve()
    control_path = Path(args.control).resolve() if args.control else _default_control_path(workspace)
    control = ControlStore(control_path)
    with DocSpecClient(workspace, binary=args.binary) as client:
        lake = DocSpecLake(
            client,
            lifecycle_compact_interval=args.lifecycle_compact_interval,
        )
        views = DocSpecNewsViews(
            client,
            lifecycle_compact_interval=args.lifecycle_compact_interval,
        )
        full_mode = args.mode == 'full' or not views.pins
        release_read = read_release(
            lake,
            control,
            args.release_id,
            tables=None if (full_mode or args.verify_oracle) else (),
        )
        if full_mode:
            views.materialize(release_read)
        else:
            views.update_bridges(release_read)
        pa_rows = politician_articles(release_read, docspec_views=views, mode=args.mode)
        cov_rows = coverage_daily(release_read, docspec_views=views, mode=args.mode)
        oracle_verified = False
        if args.verify_oracle:
            oracle_pa = politician_articles(release_read)
            oracle_cov = coverage_daily(release_read)
            if pa_rows != oracle_pa:
                raise RuntimeError('politician_articles diverged from reference oracle')
            if cov_rows != oracle_cov:
                raise RuntimeError('coverage_daily diverged from reference oracle')
            oracle_verified = True
        return {
            'backend': 'docspec',
            'release_id': args.release_id,
            'mode': args.mode,
            'oracle_verified': oracle_verified,
            'politician_articles': pa_rows,
            'coverage_daily': cov_rows,
            'lifecycle_compactions': views.lifecycle_compactions,
        }


def _cmd_export(args):
    workspace = Path(args.workspace).resolve()
    control_path = Path(args.control).resolve() if args.control else _default_control_path(workspace)
    destination = Path(args.destination).resolve()
    control = ControlStore(control_path)
    with DocSpecClient(workspace, binary=args.binary) as client:
        lake = DocSpecLake(
            client,
            lifecycle_compact_interval=args.lifecycle_compact_interval,
        )
        release_read = read_release(lake, control, args.release_id)
        views = DocSpecNewsViews(
            client,
            lifecycle_compact_interval=args.lifecycle_compact_interval,
        )
        exported = export_release(
            release_read,
            authorized=args.authorized,
            now=args.as_of,
            docspec_views=views,
            destination_dir=destination,
            channel=args.channel,
        )
        return {
            'backend': 'docspec',
            'release_id': args.release_id,
            'channel': args.channel,
            'authorized': args.authorized,
            'files': exported['files'],
        }


def _cmd_compact_lifecycle(args):
    workspace = Path(args.workspace).resolve()
    with DocSpecClient(workspace, binary=args.binary) as client:
        lake = DocSpecLake(client)
        views = DocSpecNewsViews(client)
        lake_reports = lake.compact_lifecycle()
        view_reports = views.compact_lifecycle()
        return {
            'backend': 'docspec',
            'lake_datasets': lake_reports,
            'view_datasets': view_reports,
        }


def build_parser():
    parser = argparse.ArgumentParser(
        prog='news-lake',
        description='Political news lake CLI backed by DocSpecLake and DocSpecNewsViews.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    def add_common(p):
        p.add_argument('--workspace', required=True, help='DocSpec workspace directory')
        p.add_argument('--control', default=None, help='ControlStore SQLite path (default: <workspace>/control.sqlite)')
        p.add_argument('--binary', default=None, help='Explicit docspec binary path')
        p.add_argument(
            '--lifecycle-compact-interval',
            type=int,
            default=DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
            help='Compact dataset lifecycle every N mutations (0 disables automatic compaction)',
        )

    p_pub = sub.add_parser('publish', help='Validate and publish a JSONL batch as a pinned release')
    add_common(p_pub)
    p_pub.add_argument('--input', required=True, help='Path to input records JSONL file')
    p_pub.add_argument('--release-id', required=True, help='Release UUID')
    p_pub.add_argument('--recorded-at', default=None, help='Canonical UTC timestamp (default: now)')
    p_pub.add_argument('--selections', default=None, help='JSON array or file path of processor selections')
    p_pub.add_argument('--checkpoints', default=None, help='JSON array or file path of connector checkpoints')
    p_pub.set_defaults(func=_cmd_publish)

    p_views = sub.add_parser('views', help='Materialize bridges and compute C9 views natively')
    add_common(p_views)
    p_views.add_argument('--release-id', required=True, help='Published release UUID')
    p_views.add_argument('--mode', choices=('full', 'incremental'), default='full')
    p_views.add_argument('--verify-oracle', action='store_true', help='Verify native output against the Python reference oracle')
    p_views.set_defaults(func=_cmd_views)

    p_exp = sub.add_parser('export', help='Run C5-authorized native Parquet export for a published release')
    add_common(p_exp)
    p_exp.add_argument('--release-id', required=True, help='Published release UUID')
    p_exp.add_argument('--destination', required=True, help='Output directory for exported Parquet files')
    p_exp.add_argument('--authorized', action='store_true', help='Include restricted/unexpired payloads')
    p_exp.add_argument('--as-of', default=None, help='UTC instant for capture expiry evaluation')
    p_exp.add_argument('--channel', default='public', help='Export channel name')
    p_exp.set_defaults(func=_cmd_export)

    p_comp = sub.add_parser('compact-lifecycle', help='Compact obsolete lifecycle revisions across workspace datasets')
    p_comp.add_argument('--workspace', required=True, help='DocSpec workspace directory')
    p_comp.add_argument('--binary', default=None, help='Explicit docspec binary path')
    p_comp.set_defaults(func=_cmd_compact_lifecycle)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
