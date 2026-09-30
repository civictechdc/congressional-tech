"""Prepare embedded cache captures for object storage, without uploading or deleting.

Run with the repository interpreter and an explicit JSONL input manifest. Each
manifest row has path, size and mtime_ns. Output contains content-addressed gzip
bodies, losslessly restorable JSON receipts, a Parquet capture index and an audit
for every input. Separate loose raw files are outside this operation's scope.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.bundles import restore, separate


SCHEMA = pa.schema([
    ('source_file', pa.string()), ('source_line', pa.int64()),
    ('receipt_file', pa.string()), ('receipt_line', pa.int64()),
    ('pointer_json', pa.string()), ('body_key', pa.string()),
    ('sha256', pa.string()), ('bytes', pa.int64()), ('fidelity', pa.string()),
    ('media_type', pa.string()), ('context_url', pa.string()),
    ('retrieved_at', pa.string()), ('captured_at', pa.string()),
    ('status_code', pa.int64()), ('http_status', pa.int64()),
])
MARKERS = ('"body_encoding"', '"raw_html"', '"raw_xml"', '"httpResponseBody"',
           '"browserHtml"', '"document_groups"', '"raw_body"', '"master"',
           '"source_responses"', '"prior_responses"', '"witness_observations"',
           '"status_code"', '"master_checks"', '"playlist"', '"segments"')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


class Store:
    def __init__(self, root, min_free_gib):
        self.root = root
        self.min_free = min_free_gib * 2**30
        self.known = set()
        self.lock = threading.Lock()

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        with self.lock:
            if key in self.known:
                return key
        path = self.root / key
        if not path.exists():
            if shutil.disk_usage(self.root).free < self.min_free:
                raise OSError('Stopped at minimum free disk space')
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f'.{threading.get_ident()}.tmp')
            try:
                temporary.write_bytes(gzip.compress(data, compresslevel=1, mtime=0))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        # Check existing objects too; filenames alone are not evidence of integrity.
        if self.get(key) != data:
            raise ValueError(f'Existing body is corrupt: {key}')
        with self.lock:
            self.known.add(key)
        return key

    def get(self, key):
        return gzip.decompress((self.root / key).read_bytes())


def run(manifest, output, workers, min_free_gib):
    output.mkdir(parents=True, exist_ok=True)
    for directory in ('receipts', 'indexes', 'audit'):
        (output / directory).mkdir(exist_ok=True)
    # Never overwrite a previous operation's receipts.
    if any((output / 'receipts').iterdir()):
        raise ValueError('Use a fresh output directory; existing receipts found')
    inputs = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    store = Store(output, min_free_gib)
    counts = Counter()
    lock = threading.Lock()
    started = time.monotonic()

    def shard(worker):
        receipt_key = f'receipts/embedded-{worker:02}.jsonl.gz'
        receipt_line = 0
        batch = []
        with (gzip.open(output / receipt_key, 'wt', encoding='utf-8') as receipts,
              (output / f'audit/inputs-{worker:02}.jsonl').open('w') as audit,
              pq.ParquetWriter(output / f'indexes/captures-{worker:02}.parquet', SCHEMA,
                               compression='zstd') as parquet):
            for item in inputs[worker::workers]:
                path = Path(item['path'])
                result = {'path': str(path), 'captures': 0, 'records': 0}
                try:
                    before = path.stat()
                    if before.st_size != item['size'] or before.st_mtime_ns != item['mtime_ns']:
                        raise ValueError('Input changed since inventory')
                    with path.open('rb') as handle:
                        result['source_sha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
                    opener = gzip.open if path.name.endswith('.gz') else open
                    with opener(path, 'rt', encoding='utf-8', newline='') as stream:
                        lines = stream if '.jsonl' in path.name else [stream.read()]
                        for line_number, text in enumerate(lines, 1):
                            if not text.strip():
                                continue
                            if not any(marker in text for marker in MARKERS):
                                continue
                            original = json.loads(text)
                            record, captures = separate(original, store.put)
                            if not captures:
                                continue
                            receipt = {'source_file': str(path),
                                       'source_line': line_number if '.jsonl' in path.name else None,
                                       'record': record, 'captures': captures}
                            line = encoded(receipt)
                            # Validate the actual serialized receipt and disk-backed bodies.
                            readback = json.loads(line)
                            if restore(readback['record'], readback['captures'], store.get) != original:
                                raise ValueError(f'Reconstruction differs at record {line_number}')
                            receipts.write(line + '\n')
                            receipt_line += 1
                            result['records'] += 1
                            result['captures'] += len(captures)
                            for capture in captures:
                                row = {key: capture.get(key) for key in SCHEMA.names}
                                row.update(source_file=str(path), source_line=receipt['source_line'],
                                           receipt_file=receipt_key, receipt_line=receipt_line,
                                           pointer_json=encoded(capture['pointer']))
                                batch.append(row)
                            if len(batch) >= 8192:
                                parquet.write_table(pa.Table.from_pylist(batch, schema=SCHEMA))
                                batch.clear()
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError('Input changed during extraction')
                    result['status'] = 'verified' if result['captures'] else 'no_embedded_capture'
                except Exception as error:
                    # Do not log validation errors with input values or response bodies.
                    result.update(status='error', error_type=type(error).__name__)
                audit.write(encoded(result) + '\n')
                with lock:
                    counts[result['status']] += 1
                    counts['files_scanned'] += 1
                    counts['captures'] += result['captures']
                    counts['records'] += result['records']
                    if counts['files_scanned'] % 2500 == 0:
                        progress = dict(counts, distinct_bodies=len(store.known),
                                        elapsed_seconds=round(time.monotonic() - started))
                        (output / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
                        print(encoded(progress), flush=True)
            if batch:
                parquet.write_table(pa.Table.from_pylist(batch, schema=SCHEMA))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(shard, range(workers)))
    summary = dict(counts, distinct_bodies=len(store.known),
                   input_files=len(inputs), elapsed_seconds=round(time.monotonic() - started),
                   scope='Embedded captures in the explicit input manifest; loose files remain in place',
                   original_caches_modified=False, uploaded=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(encoded(summary), flush=True)
    return 1 if counts['error'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--min-free-gib', type=float, default=20)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    raise SystemExit(run(args.manifest, args.output, args.workers, args.min_free_gib))
