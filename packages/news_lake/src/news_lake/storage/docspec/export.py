"""C5-authorized native Parquet export module for DocSpec engine."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any, Mapping

from news_lake.analysis.export import export_release
from news_lake.context import parse_instant
from news_lake.contract.records import TABLE_KINDS
from news_lake.storage.docspec.schema import (
    build_c5_export_policy,
    content_digest,
    dataset_id_for,
    kind_arrow_schema,
    records_to_arrow,
    sanitize_id,
    version_ref,
)


def _file_digest(path: str | Path) -> str:
    h = sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _ensure_release_read(records_or_release_read: Any) -> dict[str, Any]:
    if not (
        isinstance(records_or_release_read, dict)
        and 'tables' in records_or_release_read
        and isinstance(records_or_release_read.get('release'), dict)
        and records_or_release_read['release'].get('id')
    ):
        raise ValueError(
            'authorized export requires an exact published release read; '
            'raw record lists are not a release identity'
        )
    return records_or_release_read


def export_authorized(
    views: Any,
    records_or_release_read: Any,
    destination_dir: str | Path | None = None,
    *,
    as_of: Any = None,
    now: Any = None,
    authorized: bool = False,
    channel: str = 'public',
    dataset_pins: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply C5 rights and capture-expiry rules, then run native Parquet exports.

    Enforces ``news_lake.analysis.export.export_release`` and exports unchanged
    tables directly from their committed ``ReleasePin``s without creating duplicate
    staging datasets. For ``news.captures`` and ``news.versions``, uses declarative
    C5 ``ExportPolicy.computed_columns`` (``build_c5_export_policy``) to redact
    restricted or expired rows directly from the source pin natively.
    """
    release_read = _ensure_release_read(records_or_release_read)
    resolved_pins = views._resolve_source_pins(release_read)
    if dataset_pins is not None:
        for key, pin in dataset_pins.items():
            if isinstance(pin, dict):
                resolved_pins[key] = pin

    effective_now = as_of if as_of is not None else now
    if effective_now is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(effective_now, str):
        moment = parse_instant(effective_now)
    else:
        moment = effective_now
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment_iso = moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    expired_capture_ids = sorted({
        record['id']
        for record in release_read['tables'].get('news.captures', ())
        if isinstance(record, dict)
        and record.get('retain_until') is not None
        and parse_instant(record['retain_until']) < moment
    })

    filtered = export_release(release_read, authorized=authorized, now=effective_now)
    dest_root = Path(destination_dir).resolve() if destination_dir is not None else None
    if dest_root is not None:
        dest_root.mkdir(parents=True, exist_ok=True)

    pins = {}
    files = {}
    channel_id = sanitize_id(channel)
    for table_name, rows in sorted(filtered['tables'].items()):
        if not rows:
            continue
        kind = TABLE_KINDS[table_name]
        logical_dataset = dataset_id_for(table_name)
        export_dataset = sanitize_id(f'export_{logical_dataset}')
        columns = list(kind_arrow_schema(kind).names)
        orig_rows = release_read['tables'].get(table_name) or ()
        unchanged = rows == orig_rows
        pinned = resolved_pins.get(table_name) or resolved_pins.get(logical_dataset)
        if pinned is None:
            candidate = views.client.try_latest(logical_dataset)
            if (
                candidate is not None
                and candidate.get('dataset', {}).get('groups', {}).get('source', {}).get('rows')
                == len(orig_rows)
            ):
                pinned = candidate

        export_pin = None
        if pinned is not None and not unchanged and kind in ('capture', 'version'):
            c5_policy = build_c5_export_policy(
                kind,
                columns=columns,
                authorized=authorized,
                as_of=moment_iso,
                expired_capture_ids=expired_capture_ids,
            )
            c5_op = views._operation(
                f'exp-{kind}',
                content_digest([version_ref(pinned), channel_id, c5_policy]),
            )
            existing_c5 = views.client.try_export_pin(pinned['dataset']['dataset'], c5_op)
            if existing_c5 is not None:
                export_pin = existing_c5
            else:
                current_channel = views.client.try_latest_export(
                    pinned['dataset']['dataset'], channel_id
                )
                expected = current_channel['id'] if current_channel is not None else None
                c5_spec = {
                    'dataset': pinned['dataset']['dataset'],
                    'operation': c5_op,
                    'source': version_ref(pinned),
                    'channel': channel_id,
                    'expected': expected,
                    'policy': c5_policy,
                }
                export_pin = views.client.export(c5_spec)

        if export_pin is None:
            if unchanged and pinned is not None:
                source_pin = pinned
            else:
                arrow_table = records_to_arrow(kind, rows)
                admit_digest = content_digest([filtered['release']['id'], table_name, rows])
                admit_op = views._operation(f'admit-exp-{kind}', admit_digest)
                prior_pin = views.client.try_latest(export_dataset)
                if prior_pin is not None and prior_pin['dataset']['version'] == admit_op:
                    source_pin = prior_pin
                else:
                    source_pin = views.client.run_table(
                        arrow_table, export_dataset, admit_op, stream_ipc=True
                    )

            export_op = views._operation(
                f'exp-{kind}',
                content_digest([version_ref(source_pin), channel_id, columns]),
            )
            existing_export = views.client.try_export_pin(source_pin['dataset']['dataset'], export_op)
            if existing_export is not None:
                export_pin = existing_export
            else:
                current_channel = views.client.try_latest_export(
                    source_pin['dataset']['dataset'], channel_id
                )
                expected = current_channel['id'] if current_channel is not None else None
                export_spec = {
                    'dataset': source_pin['dataset']['dataset'],
                    'operation': export_op,
                    'source': version_ref(source_pin),
                    'channel': channel_id,
                    'expected': expected,
                    'policy': {
                        'group': 'source',
                        'rows': 'all',
                        'columns': columns,
                    },
                }
                export_pin = views.client.export(export_spec)

        pins[logical_dataset] = export_pin
        pins[table_name] = export_pin
        exported_path = Path(export_pin['object']['path'])
        if dest_root is not None:
            dest_file = dest_root / f'{logical_dataset}.parquet'
            if not dest_file.exists() or _file_digest(dest_file) != _file_digest(exported_path):
                try:
                    if dest_file.exists():
                        dest_file.unlink()
                    os.link(exported_path, dest_file)
                except OSError:
                    shutil.copyfile(exported_path, dest_file)
            files[logical_dataset] = str(dest_file)
            files[table_name] = str(dest_file)
        else:
            files[logical_dataset] = str(exported_path)
            files[table_name] = str(exported_path)

    result = {
        'release': filtered['release'],
        'tables': filtered['tables'],
        'pins': pins,
        'files': files,
    }
    for key, pin in pins.items():
        if not key.startswith('news.'):
            result[key] = pin
    return result
