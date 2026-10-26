"""Read-only review checks; no receipt values or source URLs are emitted."""
from pathlib import Path
import collections
import gzip
import hashlib
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
INPUT = Path('/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs')
RECEIPTS = Path('/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts')


def emit(name, value):
    result = {'basis': 'measured locally, not on the target runner', **value}
    (ROOT / (name + '.json')).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True), flush=True)


def inventory():
    import duckdb
    import pyarrow.parquet as pq
    started = time.monotonic()
    db = duckdb.connect()
    db.execute("SET threads=4")
    db.execute("SET memory_limit='4GB'")
    db.execute("SET temp_directory='review-duckdb-scratch'")
    p = str(INPUT)
    db.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet('{p}/captures.parquet')")
    db.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{p}/readings/*.parquet', union_by_name=true)")
    rows = db.execute('SELECT count(*), count(distinct body_key), count(distinct receipt_key) FROM c').fetchone()
    files = sorted((INPUT / 'readings').glob('*.parquet'))
    schemas = collections.Counter()
    fields = set()
    for f in files:
        names = pq.ParquetFile(f).schema_arrow.names
        fields.update(names)
        schemas[tuple(names)] += 1
    result = {
        'capture_rows': rows[0], 'capture_distinct_body_keys': rows[1],
        'capture_distinct_receipt_keys': rows[2],
        'capture_sha256': hashlib.file_digest((INPUT / 'captures.parquet').open('rb'), 'sha256').hexdigest(),
        'reading_files': len(files), 'reading_schema_shapes': len(schemas),
        'reading_identity_fields': sorted(x for x in fields if any(y in x for y in ('status', 'error', 'fingerprint', 'version', 'time', 'checked', 'opened', 'readable', 'page'))),
        'reading_statuses': db.execute('SELECT status, error_type, count(*) FROM r GROUP BY ALL ORDER BY count(*) DESC').fetchall(),
        'pdf_readings': db.execute("SELECT status, error_type, count(*), count(distinct body_key) FROM r WHERE list_contains(body_format,'pdf') GROUP BY ALL ORDER BY count(*) DESC").fetchall(),
        'body_sizes': db.execute('SELECT count(*), sum(n), max(n), count(*) FILTER (WHERE n > 100000000), count(*) FILTER (WHERE n > 104857600) FROM (SELECT body_key, max(bytes) n FROM c WHERE body_key IS NOT NULL GROUP BY body_key)').fetchone(),
        'seconds': round(time.monotonic()-started, 3),
        'limits': 'Parquet metadata and recorded facts only; no raw body, fresh PDF open, live bucket state, or target-runner performance.'
    }
    emit('inventory-check', result)


def receipts():
    started = time.monotonic()
    files = sorted(RECEIPTS.rglob('*.jsonl.gz'))
    counts = collections.Counter()
    shape_counts = collections.Counter()
    collision_shapes = collections.Counter()
    max_line = (0, '', 0)
    absolute = re.compile(r'^(?:/|[A-Za-z]:[\\/])')
    for i, f in enumerate(files):
        with gzip.open(f, 'rb') as stream:
            for lineno, raw in enumerate(stream, 1):
                counts['lines'] += 1
                counts['uncompressed_bytes'] += len(raw)
                if len(raw) > max_line[0]:
                    max_line = (len(raw), str(f.relative_to(RECEIPTS)), lineno)
                obj = json.loads(raw)
                shape_counts[type(obj).__name__] += 1
                stack = [(obj, ())]
                while stack:
                    value, trail = stack.pop()
                    if isinstance(value, dict):
                        renamed = collections.Counter()
                        for key, child in value.items():
                            local_key = bool(absolute.match(key))
                            new = re.split(r'[\\/]', key.rstrip('/\\'))[-1] if local_key else key
                            renamed[new] += 1
                            if local_key:
                                counts['absolute_key_names'] += 1
                            field = '<absolute-key>' if local_key else key
                            if key == 'original_path' and isinstance(child,str) and absolute.match(child):
                                counts['absolute_original_path_values'] += 1
                            if key.lower() in ('set-cookie','cookie','authorization'):
                                counts['sensitive_header_key_instances'] += 1
                            if isinstance(child, (dict, list)):
                                stack.append((child, trail + (field,)))
                        collision_count = sum(n-1 for n in renamed.values() if n>1)
                        if collision_count:
                            counts['key_basename_collisions'] += collision_count
                            collision_shapes['.'.join(trail)] += collision_count
                    elif isinstance(value, list):
                        stack.extend((child, trail+('[]',)) for child in value if isinstance(child,(dict,list)))
        if (i+1) % 400 == 0:
            print(json.dumps({'receipts_scanned':i+1,'lines':counts['lines']}), flush=True)
    emit('receipt-check', {
        'files': len(files), 'compressed_bytes': sum(f.stat().st_size for f in files),
        'counts': dict(counts), 'top_level_shapes': dict(shape_counts),
        'maximum_line': {'bytes':max_line[0], 'receipt_key':'receipts/'+max_line[1], 'line':max_line[2]},
        'collision_shapes':dict(collision_shapes), 'seconds':round(time.monotonic()-started,3),
        'limits':'Receipt mirror only; absolute-looking keys are a conservative candidate set, not the owner-approved cleanup field list. No live receipt race, backup contents, body bytes, or bucket-lock behavior checked.'
    })


if __name__ == '__main__':
    {'inventory':inventory,'receipts':receipts}[sys.argv[1]]()
