"""Rows of every model relation in one retained model build, for the repeat-cost lint.

    .venv/bin/python scripts/measure/model_relation_rows.py RUN [--lake-metadata DIR] \
        > packages/viewer_publication/tests/fixtures/model-relation-rows.json

RUN holds the build's archive-model/job.json (or legacy model-scratch/job.json), steps.jsonl
and model-spec.json. Steps take their logged rows (views and queries are never scanned and are
left out); lake tables the total-records of their pinned snapshot (from local metadata_location
or --lake-metadata DIR/<name>.metadata.json verified by table UUID, schema id and snapshot id);
Parquet inputs their footers; spicy-regs tables the manifest; JSON-lines inputs their non-blank
lines, read from model-spec's SHA-256-verified source file when the build's private copy is gone.
An input it cannot count stops the script, and so does a step log whose last line was cut short
(`TornMetricLine`): its build did not finish.
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from docspec_client import metric_events

REPO_ROOT = Path(__file__).resolve().parents[2]


def lines(path):
    with (gzip.open if str(path).endswith('.gz') else open)(path, 'rt') as handle:
        return sum(1 for line in handle if line.strip())


def _load_json_maybe_gz(path: Path):
    raw = path.read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return json.loads(raw.decode('utf-8'))


def _verified_pin_path(pin: dict, repo_root: Path) -> Path:
    candidate = Path(pin['path'])
    if not candidate.exists() and '/model/' in pin['path']:
        candidate = repo_root / 'model' / pin['path'].partition('/model/')[2]
    if not candidate.exists():
        raise ValueError(f"pinned input missing: {pin['path']}")
    if 'size' in pin or 'sha256' in pin:
        raw = candidate.read_bytes()
        if 'size' in pin and len(raw) != pin['size']:
            raise ValueError(f"pinned input size mismatch for {candidate}: expected {pin['size']}, got {len(raw)}")
        if 'sha256' in pin:
            digest = hashlib.sha256(raw).hexdigest()
            if digest != pin['sha256']:
                raise ValueError(f"pinned input sha256 mismatch for {candidate}: expected {pin['sha256']}, got {digest}")
    return candidate


def _native_table_rows(item: dict, lake_metadata: Path | None) -> int:
    loc = item['metadata_location']
    if not loc.startswith('s3://') and Path(loc).exists():
        meta_path = Path(loc)
    elif lake_metadata is not None and (lake_metadata / f"{item['name']}.metadata.json").exists():
        meta_path = lake_metadata / f"{item['name']}.metadata.json"
    else:
        raise ValueError(
            f"cannot count native_table {item['name']} at {loc}: pass --lake-metadata DIR with {item['name']}.metadata.json"
        )
    metadata = _load_json_maybe_gz(meta_path)
    if 'table_uuid' in item and metadata.get('table-uuid') != item['table_uuid']:
        raise ValueError(
            f"{item['name']} metadata table_uuid mismatch: expected {item['table_uuid']}, got {metadata.get('table-uuid')}"
        )
    if 'schema_id' in item and 'schemas' in metadata:
        if not any(s.get('schema-id') == item['schema_id'] for s in metadata['schemas']):
            raise ValueError(f"{item['name']} schema_id {item['schema_id']} not found in {meta_path}")
    snapshots = [s for s in metadata.get('snapshots', []) if s.get('snapshot-id') == item['snapshot']]
    if len(snapshots) != 1:
        raise ValueError(f"{item['name']} snapshot {item['snapshot']} not found in {meta_path}")
    return int(snapshots[0]['summary']['total-records'])


def input_rows(item, sources, spicy, parquet_pins, *, lake_metadata=None, repo_root=REPO_ROOT):
    if item['kind'] == 'native_table':
        return _native_table_rows(item, lake_metadata)
    if item['name'] in spicy:
        return spicy[item['name']]
    if item['kind'] == 'parquet':
        parquet_path = Path(item['path'])
        if not parquet_path.exists() and item['name'] in parquet_pins:
            parquet_path = _verified_pin_path(parquet_pins[item['name']], repo_root)
        return pq.ParquetFile(parquet_path).metadata.num_rows
    if item['kind'] == 'json_lines':
        total = 0
        for f in item['files']:
            fpath = Path(f['path'])
            if not fpath.exists():
                fpath = _verified_pin_path(sources[f['key']], repo_root)
            total += lines(fpath)
        return total
    raise ValueError(f"cannot count input {item['name']} ({item['kind']})")


def relation_rows(run, *, lake_metadata=None, repo_root=REPO_ROOT, overlay_registries=False):
    run = Path(run)
    lake_meta = Path(lake_metadata) if lake_metadata is not None else None
    repo_root = Path(repo_root)
    job_path = run / 'archive-model/job.json' if (run / 'archive-model/job.json').exists() else run / 'model-scratch/job.json'
    job = json.loads(job_path.read_text())
    spec = json.loads((run / 'model-spec.json').read_text())
    sources = {
        f['key']: f
        for value in spec.values()
        if isinstance(value, list)
        for f in value
        if isinstance(f, dict) and 'key' in f and 'path' in f
    }
    parquet_pins = {}
    if isinstance(spec.get('recovery_requirements'), dict) and 'path' in spec['recovery_requirements']:
        parquet_pins['recovery_requirements_input'] = spec['recovery_requirements']
    spicy = {}
    if spec.get('spicy_regs'):
        manifest_pin = spec['spicy_regs'] if isinstance(spec['spicy_regs'], dict) else {'path': str(spec['spicy_regs'])}
        manifest = json.loads(_verified_pin_path(manifest_pin, repo_root).read_text())
        for name, table in manifest['tables'].items():
            spicy[name] = table['rows']
            spicy[f'spicy_{name}'] = table['rows']
    rows = {
        item['name']: input_rows(item, sources, spicy, parquet_pins, lake_metadata=lake_meta, repo_root=repo_root)
        for item in job['inputs']
    }
    for event in metric_events(run / 'steps.jsonl', prefix=''):
        if event['event'] == 'step' and event['storage'] not in ('view', 'query'):
            rows[event['name']] = event['rows']
    overlaid = []
    if overlay_registries:
        import tempfile
        from viewer_publication.archive_model import registry_inputs

        with tempfile.TemporaryDirectory() as tmp:
            for item in registry_inputs(Path(tmp) / 'registries', root=repo_root):
                if item['name'] not in rows:
                    rows[item['name']] = sum(lines(f['path']) for f in item['files'])
                    overlaid.append(item['name'])
    head = (run / 'head.txt').read_text().splitlines() if (run / 'head.txt').exists() else []
    out = dict(
        source='.cache/' + str(run.resolve()).partition('/.cache/')[2],
        head=head[0] if head else None,
        uncommitted=[line.split()[-1] for line in head[1:] if line[:3].strip() in ('M', '??', 'A')],
        rows=dict(sorted(rows.items())),
    )
    if overlaid:
        out['overlaid_registries'] = sorted(overlaid)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', help='Retained model build folder.')
    parser.add_argument('--lake-metadata', type=Path, default=None, help='Directory of fetched <name>.metadata.json files.')
    parser.add_argument('--repo-root', type=Path, default=REPO_ROOT, help='Repository root for SHA-256-verified pin fallbacks.')
    parser.add_argument(
        '--overlay-registries',
        action='store_true',
        help='Count committed model registries added after RUN without overwriting RUN relations.',
    )
    args = parser.parse_args(argv)
    json.dump(
        relation_rows(
            args.run,
            lake_metadata=args.lake_metadata,
            repo_root=args.repo_root,
            overlay_registries=args.overlay_registries,
        ),
        sys.stdout,
        indent=1,
    )
    sys.stdout.write('\n')


if __name__ == '__main__':
    main()
