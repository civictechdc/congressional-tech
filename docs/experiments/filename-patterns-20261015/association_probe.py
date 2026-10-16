"""Check a frozen, bounded sample of original publisher links against saved hashes.

Receipts are experiment evidence only. A successful match still needs normal
capture ingestion before it can establish a production source association.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from continuation import rank, save


def probe(output):
    candidates = json.loads((output / 'association-candidates.json').read_text())
    pools = defaultdict(list)
    for row in candidates:
        for url in row['occurrence'].get('source_link_url') or []:
            pools[(urlsplit(url).hostname, ','.join(row['proposed_kinds']))].append(dict(row, original_url=url))
    for rows in pools.values():
        rows.sort(key=lambda r: rank(r['document_id'] + r['original_url']), reverse=True)
    selected, urls = [], set()
    while len(selected) < 48 and pools:
        for key in sorted(list(pools)):
            row = pools[key].pop()
            if not pools[key]:
                del pools[key]
            if row['original_url'] in urls:
                continue
            urls.add(row['original_url'])
            selected.append(row)
            if len(selected) == 48:
                break
    destination = output / 'association-probe'
    destination.mkdir(exist_ok=False)
    save(destination / 'sample.json', dict(method='Up to 48 unique original URLs, round-robin publisher/kind strata with deterministic hash ranking before availability checks. No substitutes for failures.', records=selected))

    def one(row):
        url = row['original_url']
        receipt = dict(document_id=row['document_id'], original_url=url,
                       checked_at=datetime.now(timezone.utc).isoformat(), expected_body_keys=row['body_keys'])
        try:
            if urlsplit(url).scheme not in {'http', 'https'}:
                raise ValueError('Expected an HTTP(S) source URL')
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; CongressionalTech/1.0; document research)'})
            with urlopen(request, timeout=12) as response:
                receipt.update(http_status=response.status, final_url=response.url,
                               content_type=response.headers.get('Content-Type'))
                body = response.read(32 * 1024**2 + 1)
            if len(body) > 32 * 1024**2:
                raise ValueError('Response exceeds 32 MiB limit')
            sha = hashlib.sha256(body).hexdigest()
            receipt.update(sha256=sha, bytes=len(body))
            expected = {Path(k).name.removesuffix('.gz') for k in row['body_keys'] or []}
            receipt['status'] = ('matching_pdf' if sha in expected else 'different_pdf') if body.startswith(b'%PDF-') else 'not_pdf'
            # Preserve every returned PDF, including disagreements; HTML error
            # bodies are represented by their digest, status, type and final URL.
            if body.startswith(b'%PDF-'):
                (destination / (sha + '.pdf')).write_bytes(body)
        except HTTPError as error:
            receipt.update(status='http_error', http_status=error.code, final_url=error.url, error=str(error))
        except Exception as error:
            receipt.update(status='read_error', error=str(error))
        return receipt

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool, (destination / 'receipts.jsonl').open('x') as stream:
        for receipt in pool.map(one, selected):
            results.append(receipt)
            stream.write(json.dumps(receipt) + '\n')
            stream.flush()
            print(receipt['status'], receipt['original_url'], flush=True)
    save(destination / 'summary.json', dict(count=len(results), outcomes=dict(Counter(r['status'] for r in results)),
                                           http_status=dict(Counter(str(r.get('http_status')) for r in results))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    probe(parser.parse_args().output)
