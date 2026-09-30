"""Copy an explicit list of retained source files into .cache, verifying every byte.

Manifest rows contain source and destination paths. This preserves the original
file format, including gzip files and empty negative-result markers. It does not
delete originals, rewrite historical receipts, upload, or switch pipeline readers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_verified(source: Path, destination: Path, *, min_free_bytes=20 * 2**30):
    """Make an independent copy; never replace an existing different file."""
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free - before.st_size < min_free_bytes:
        raise OSError('Import would cross the minimum free-space limit')
    temporary = None
    try:
        with source.open('rb') as incoming, tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix='.import-', delete=False
        ) as outgoing:
            temporary = Path(outgoing.name)
            sha = hashlib.sha256()
            for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
                sha.update(chunk)
                outgoing.write(chunk)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Source changed during import')
        expected = sha.hexdigest()
        if temporary.stat().st_size != before.st_size or digest(temporary) != expected:
            raise ValueError('Copied file does not match source')
        try:
            # Link our temporary file atomically without replacing another file.
            # The original source is never linked to the destination.
            os.link(temporary, destination)
            status = 'copied'
        except FileExistsError:
            if not destination.is_file() or digest(destination) != expected:
                raise ValueError('Destination already exists with different contents')
            status = 'already_present'
        return {'source_path': str(source), 'cache_path': str(destination),
                'sha256': expected, 'bytes': before.st_size, 'status': status}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(manifest, cache, output, workers=8, min_free_gib=20):
    cache = cache.resolve()
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    destinations = set()
    for row in rows:
        destination = Path(row['destination']).resolve()
        if not destination.is_relative_to(cache):
            raise ValueError(f'Destination is outside cache: {destination}')
        if destination in destinations:
            raise ValueError(f'Duplicate destination: {destination}')
        destinations.add(destination)
        row['destination'] = str(destination)
    output.mkdir(parents=True, exist_ok=True)
    def copy(row):
        try:
            return copy_verified(Path(row['source']), Path(row['destination']),
                                 min_free_bytes=int(min_free_gib * 2**30))
        except Exception as error:
            return {'source_path': row['source'], 'cache_path': row['destination'],
                    'sha256': None, 'bytes': None, 'status': 'error',
                    'error': f'{type(error).__name__}: {error}'}
    results = []
    with (output / 'imports.jsonl').open('w') as journal, ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(copy, rows):
            result['cache_relative_path'] = str(Path(result['cache_path']).relative_to(cache))
            journal.write(json.dumps(result) + '\n')
            results.append(result)
            if len(results) % 1000 == 0:
                journal.flush()
                print(json.dumps({'processed': len(results), 'total': len(rows)}), flush=True)
    schema = pa.schema([('source_path', pa.string()), ('cache_path', pa.string()),
                        ('cache_relative_path', pa.string()),
                        ('sha256', pa.string()), ('bytes', pa.int64()),
                        ('status', pa.string()), ('error', pa.string())])
    pq.write_table(pa.Table.from_pylist(results, schema=schema), output / 'files.parquet', compression='zstd')
    errors = [r for r in results if r['status'] == 'error']
    summary = {'files': len(results), 'verified_files': len(results) - len(errors),
               'bytes': sum(r['bytes'] or 0 for r in results), 'errors': errors,
               'originals_deleted': False, 'historical_receipts_changed': False, 'uploaded': False}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2), flush=True)
    return int(bool(errors))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--cache', default=Path('.cache'), type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--min-free-gib', type=float, default=20)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    raise SystemExit(run(args.manifest, args.cache, args.output, args.workers, args.min_free_gib))
