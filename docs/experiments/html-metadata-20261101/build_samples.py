"""Rebuild the reader and content cohorts from the captures index, and fetch their bodies.

Usage: build_samples.py CAPTURES.parquet OUT_DIR BODIES_DIR
The random strata reuse the earlier sample's shape. Order is a digest of a fixed seed
and the body digest, so the choice is reproducible. Only HTML bodies count toward a
quota. Writes sample-manifest.json; bodies stay in BODIES_DIR, outside Git.
"""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

import pyarrow.parquet as pq

from congress_api.parsers.html_metadata import is_html
from raw_bodies import read_body

SEED = 'html-metadata-20261101'
RANDOM = {'house/pages': 120, 'documents': 120, 'senate/pages': 60, 'govinfo/transcript-html': 30, 'external/provider-responses': 20}
STATEMENT = re.compile(r'witness-testimony|opening-statement|submission-for-the-record|prepared-statement', re.I)
STATEMENT_QUOTA = 300
OTHER_HOST_QUOTA = 200
SKIP_URL = re.compile(r'\.(?:pdf|mp[34]|zip|xlsx?|docx?|pptx?|png|jpe?g|gif|m3u8|xml|json)(?:$|\?)', re.I)
MAX_BYTES = 50_000_000


def order(row):
    return hashlib.sha256(f"{SEED}|{row['sha256']}".encode()).hexdigest()


def fetch(row, bodies):
    try:
        body, _ = read_body(row['sha256'])
    except Exception:
        return row, None
    (bodies / f"{row['sha256']}.gz").write_bytes(gzip.compress(body, 1))
    return row, is_html(body)


def fill(pool, rows, quota, why, bodies, chosen):
    """Walk candidates in batches; O(quota) fetches on HTML-heavy strata, bounded on others."""
    kept, position, attempts = 0, 0, 0
    rows = sorted(rows, key=order)
    while kept < quota and position < len(rows) and attempts < quota * 8:
        batch = rows[position:position + max(16, quota - kept)]
        position += len(batch)
        attempts += len(batch)
        for row, html in pool.map(lambda item: fetch(item, bodies), batch):
            if not html or kept >= quota or row['sha256'] in chosen:
                if row['sha256'] not in chosen:
                    (bodies / f"{row['sha256']}.gz").unlink(missing_ok=True)
                continue
            kept += 1
            chosen[row['sha256']] = dict(sha=row['sha256'], fam=row['family'], url=row['context_url'], status=row['http_status'], bytes=row['bytes'], why=why)
    return dict(quota=quota, kept=kept, candidates=len(rows), fetched=attempts)


def main():
    out, bodies = Path(sys.argv[2]), Path(sys.argv[3])
    bodies.mkdir(parents=True, exist_ok=True)
    families = sorted({*RANDOM, 'house/pages', 'documents'})
    table = pq.read_table(sys.argv[1], columns=['family', 'sha256', 'context_url', 'http_status', 'bytes'], filters=[('family', 'in', families)])
    unique = {}
    for row in table.to_pylist():
        url = row['context_url'] or ''
        if row['sha256'] and row['http_status'] == 200 and (row['bytes'] or 0) < MAX_BYTES and not SKIP_URL.search(url):
            unique.setdefault(row['sha256'], row)
    rows = list(unique.values())
    chosen, strata = {}, {}
    with ThreadPoolExecutor(8) as pool:
        for family, quota in RANDOM.items():
            strata['random_' + family] = fill(pool, [row for row in rows if row['family'] == family], quota, 'random_' + family, bodies, chosen)
        marked = [row for row in rows if row['family'] in {'house/pages', 'documents'} and STATEMENT.search(row['context_url'] or '')]
        strata['statement_url'] = fill(pool, marked, STATEMENT_QUOTA, 'statement_url', bodies, chosen)
        others = [row for row in rows if row['family'] in {'house/pages', 'documents'} and 'veterans.house.gov' not in (row['context_url'] or '') and row['sha256'] not in chosen]
        strata['other_host'] = fill(pool, others, OTHER_HOST_QUOTA, 'other_host', bodies, chosen)
    manifest = sorted(chosen.values(), key=lambda row: row['sha'])
    (out / 'sample-manifest.json').write_text(json.dumps(dict(seed=SEED, strata=strata, bodies=manifest), indent=0) + '\n')
    print(json.dumps(strata, indent=1), len(manifest), sum(row['bytes'] for row in manifest) / 1e6)


if __name__ == '__main__':
    main()
