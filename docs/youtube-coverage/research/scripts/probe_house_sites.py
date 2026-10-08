"""Probe explicit House requests without changing collection state or archives.

Input is a JSON list of {site, request} records. Each request keeps its literal
URL, kind and optional POST body. Outputs must use a new evidence directory.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import requests

from congress_api.parsers.committee_discovery import discover, key, listing_records
from congress_api.parsers.committee_pages import event_identity, committee_document_links
from congress_api.transport import http

MAX_BYTES = 2 * 1024 * 1024


class ProbeSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs.update(stream=True, timeout=(10, 20))
        return super().request(*args, **kwargs)


def probe(session, request, output_dir):
    """Keep one complete request together through fetching and interpretation."""
    started = time.monotonic()
    url = request['url']
    report = dict(request=request, failure_key=key(request), started_at=datetime.now(timezone.utc).isoformat())
    response = None
    try:
        options = dict(method='POST', json_body=request['body'], json_content_type='text/plain;charset=UTF-8') if 'body' in request else {}
        response = http.get_with_retry(session, url, attempts=1, allowed=tuple(range(200, 600)), **options)
        report.update(status=response.status_code, final_url=response.url, sent_url=response.request.url,
                      headers={k: v for k, v in response.headers.items() if k.lower() in
                               {'content-type', 'content-length', 'content-encoding', 'location', 'retry-after'}})
        data = bytearray()
        complete = True
        for chunk in response.iter_content(chunk_size=4096):
            data.extend(chunk)
            if b'%PDF-' in data[:1024] or len(data) >= MAX_BYTES or time.monotonic() - started > 45:
                complete = False
                break
        body = bytes(data)
        digest = hashlib.sha256(body).hexdigest()
        path = output_dir / 'responses' / (hashlib.sha256(key(request).encode()).hexdigest()[:24] + '.body')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(body)
        report.update(body_path=str(path), body_bytes=len(body), body_sha256=digest, body_complete=complete)
        if complete and body and response.status_code == 200:
            try:
                report['discovered_count'] = len(discover(body, {**request, 'url': response.url}, headers=response.headers))
            except (ValueError, KeyError, TypeError) as error:
                report['discovery_error'] = str(error)
            report['event_identity'] = event_identity(body, response.url)
            report['document_links'] = len(committee_document_links(body, response.url))
            records = listing_records(body, response.url)
            report['listing_records_count'] = len(records) if records is not None else None
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error), exception_types=http.exception_types(error))
    finally:
        if response is not None:
            response.close()
    report['seconds'] = round(time.monotonic() - started, 3)
    return report


def site_probe(rows, output_dir):
    with ProbeSession() as session:
        session.max_redirects = 5
        results = []
        for row in rows:
            results.append(dict(site=row['site'], **probe(session, row['request'], output_dir)))
            time.sleep(.75)
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.requests.read_text())
    if not isinstance(rows, list) or not rows or len({key(row['request']) for row in rows}) != len(rows):
        parser.error('Provide a nonempty list of distinct requests')
    groups = defaultdict(list)
    for row in rows:
        groups[urlsplit(row['request']['url']).hostname].append(row)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / 'probe-results.jsonl').open('x') as output, ThreadPoolExecutor(3) as pool:
        pending = [pool.submit(site_probe, group, args.output_dir) for group in groups.values()]
        for future in as_completed(pending):
            for report in future.result():
                output.write(json.dumps(report, ensure_ascii=False) + '\n')
            output.flush()


if __name__ == '__main__':
    main()
