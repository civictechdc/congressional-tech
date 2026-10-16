#!/usr/bin/env python3
"""Explicit, sequential Web Harvest HTML acquisition; no import or publication.

Promotes the retained-first and Firecrawl request behavior from dated
recover_nara_html_continuation_04.py and recover_firecrawl_nara_scaled_02.py.
Historical evidence remains read-only. An attempted URL never becomes done merely
because it was present in a previous queue.
"""
import argparse
import base64
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit

import requests

from classify_recovery_html_transcripts import classify

DISPOSITIONS = {'qualified', 'terminal-content', 'review-required',
                'retryable-failure', 'active-reservation'}
DENIED_HEADERS = {'set-cookie', 'authorization', 'proxy-authorization', 'cookie'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def request_id(row, provider):
    return sha(json.dumps({'provider': provider, 'candidate': row['candidates'][0],
                           'original_urls': sorted(row['original_urls'])}, sort_keys=True).encode())


def process_identity(pid=None):
    """PID plus OS-reported start time and command protects against PID reuse."""
    pid = os.getpid() if pid is None else int(pid)
    value = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                           capture_output=True, text=True, check=False)
    return {'pid': pid, 'start_and_command': value.stdout.strip()} if value.returncode == 0 else None


def reservation_live(reservation):
    return bool(reservation.get('start_and_command') and
                process_identity(reservation['pid']) == reservation)


@contextmanager
def exclusive_run(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(directory / 'process.json', process_identity())
        yield


def exclusions(path):
    rows = read(path)
    return {r['url'] for r in rows}, {r['sha256'] for r in rows}


def disposition(record):
    """Attempted failures stay visible and require an explicit later retry grant."""
    category = record.get('content', {}).get('category')
    if record.get('valid'):
        return 'qualified'
    if category == 'historical_no_prepared_statement':
        return 'terminal-content'
    if category == 'error_or_challenge' or record.get('status', record.get('http_status')) in {401, 403, 429}:
        return 'retryable-failure'
    if record.get('error_type') or record.get('status', record.get('http_status', 0)) >= 500:
        return 'retryable-failure'
    return 'review-required'


def plan(queue, prior, reservations, deferred):
    forbidden_urls, _ = exclusions(deferred)
    previous = {}
    for path in prior:
        value = read(path)
        for record in value if isinstance(value, list) else [value]:
            for url in record.get('original_urls', [record.get('original_url')]):
                previous[url] = (record, str(path), sha(Path(path).read_bytes()))
    active = {}
    for path in reservations:
        reservation = read(path)
        if reservation_live(reservation['process']):
            for url in reservation['original_urls']:
                active[url] = str(path)
    rows = []
    for group in read(queue):
        for url in group['original_urls']:
            row = dict(original_url=url, candidates=group['candidates'], eligible=False)
            if url in forbidden_urls:
                row.update(disposition='review-required', reason='deferred_exclusion')
            elif url in active:
                row.update(disposition='active-reservation', evidence=active[url])
            elif url in previous:
                record, path, digest = previous[url]
                row.update(disposition=disposition(record), evidence=path,
                           evidence_sha256=digest, reason=record.get('content', {}).get('category', 'prior_attempt'))
            else:
                row.update(disposition='retryable-failure', reason='unattempted', eligible=True)
            rows.append(row)
    return {'rows': rows, 'counts': dict(Counter(r['disposition'] for r in rows)),
            'deferred_exclusions': len(forbidden_urls), 'automatic_retries': False}


def pagination_state(pages):
    """Explicit continuations only; row counts never establish completeness.

    Each retained page declares cursor, continuation, and complete. None ends a
    chain only when complete is explicitly true. Missing metadata stays unknown.
    """
    by_cursor = {p.get('cursor'): p for p in pages}
    cursor, seen = None, set()
    while cursor in by_cursor and cursor not in seen:
        seen.add(cursor)
        page = by_cursor[cursor]
        if 'continuation' not in page:
            return {'complete': False, 'reason': 'missing_continuation_metadata'}
        following = page['continuation']
        if following is None:
            return {'complete': page.get('complete') is True,
                    'reason': 'explicit_end' if page.get('complete') is True else 'unconfirmed_end'}
        cursor = following
    return {'complete': False, 'reason': 'continuation_cycle' if cursor in seen else 'missing_continuation_page',
            'continuation': cursor}


def load_config(path):
    config = read(path)
    if config['provider'] not in {'retained', 'direct', 'firecrawl'}:
        raise ValueError('Unsupported provider')
    if not 0 <= config.get('budget_usd', 0) <= 25:
        raise ValueError('Existing maximum budget is $25')
    if config['provider'] == 'firecrawl':
        if not config.get('credential_env') or config.get('max_requests', 0) <= 0:
            raise ValueError('Firecrawl needs credential_env and a finite max_requests')
        if config.get('request_ceiling_usd', 0) <= 0:
            raise ValueError('Explicit conservative per-request cost ceiling required')
        if config['max_requests'] * config['request_ceiling_usd'] + config.get('spent_to_date_usd', 0) > config.get('budget_usd', 0):
            raise ValueError('Request ceiling exceeds budget')
    if config.get('max_body_bytes', 8 * 1024**2) > 8 * 1024**2:
        raise ValueError('HTML body limit cannot exceed 8 MiB')
    return config


def checked_body(record):
    raw = Path(record['body_path']).read_bytes()
    if sha(raw) != record['sha256'] or len(raw) != record['bytes']:
        raise ValueError('Retained body hash or length changed')
    return raw


def fetch(row, config, directory, session):
    candidate = row['candidates'][0]
    url = candidate['replay_url']
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'webharvest.gov' or
            parsed.username or parsed.password or 'id_/' not in parsed.path or
            candidate.get('match_basis') != 'exact_canonical_url'):
        raise ValueError('Only exact indexed Web Harvest identity URLs are admitted')
    result = dict(original_urls=row['original_urls'], candidate=candidate,
                  requested_url=url, provider=config['provider'], valid=False,
                  complete=False, at=now(), rendered_copy=False)
    limit = config.get('max_body_bytes', 8 * 1024**2)
    if candidate.get('mime', '').startswith(('audio/', 'video/')):
        return dict(result, disposition='review-required', reason='media_excluded')
    try:
        if config['provider'] == 'retained':
            retained = row['retained']
            raw = checked_body(retained)
            result.update(status=retained['status'], complete=retained['complete'],
                          final_url=retained['final_url'], reused_evidence=retained['evidence'],
                          rendered_copy=retained.get('rendered_copy', False))
        elif config['provider'] == 'direct':
            with session.get(url, stream=True, allow_redirects=False,
                             timeout=(15, 45), headers={'Accept-Encoding': 'identity'}) as response:
                result.update(status=response.status_code, final_url=str(response.url),
                              headers={k.lower(): v for k, v in response.headers.items() if k.lower() not in DENIED_HEADERS})
                if response.headers.get('content-type', '').lower().startswith(('video/', 'audio/')):
                    raise ValueError('media_excluded')
                chunks, length = [], 0
                for chunk in response.iter_content(65536):
                    length += len(chunk)
                    if length > limit:
                        raise ValueError('HTML size limit')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                result['complete'] = True
        else:
            key = os.environ[config['credential_env']]
            payload = {'url': url, 'formats': ['rawHtml'], 'onlyMainContent': False,
                       'parsers': [], 'timeout': 60000, 'proxy': 'enhanced', 'maxAge': 0, 'waitFor': 5000}
            response = session.post('https://api.firecrawl.dev/v2/scrape', json=payload,
                                    headers={'Authorization': 'Bearer ' + key}, timeout=90)
            data = response.json().get('data') or {}
            metadata = data.get('metadata') or {}
            result.update(status=response.status_code, origin_status=metadata.get('statusCode'),
                          final_url=metadata.get('url'), rendered_copy=True,
                          provider_metadata={k: metadata.get(k) for k in ('sourceURL', 'url', 'statusCode', 'contentType', 'creditsUsed', 'scrapeId')})
            if metadata.get('contentType', '').lower().startswith(('video/', 'audio/')):
                raise ValueError('media_excluded')
            raw = (data.get('rawHtml') or '').encode()
            result['complete'] = bool(data.get('rawHtml'))
        if len(raw) > limit:
            raise ValueError('HTML size limit')
        body = directory / 'body.html'
        body.write_bytes(raw)
        result.update(body_path=str(body.resolve()), bytes=len(raw), sha256=sha(raw))
        digest = base64.b32encode(hashlib.sha1(raw).digest()).decode().rstrip('=')
        result.update(index_digest_matches=digest == candidate.get('digest', '').removeprefix('sha1:'),
                      sha1_base32=digest, content=classify(raw))
        _, forbidden = exclusions(config['deferred'])
        result['excluded_deferred_body'] = result['sha256'] in forbidden
        result['valid'] = bool(result['complete'] and result['status'] == 200 and
                               result['final_url'] == url and
                               (result['rendered_copy'] or result['index_digest_matches']) and
                               (not result['rendered_copy'] or result.get('origin_status', 200) == 200) and
                               not result['excluded_deferred_body'] and
                               result['content']['category'] == 'substantial_document_body')
        result['source_bytes_identity_claimed'] = bool(result['valid'] and not result['rendered_copy'])
    except Exception as error:
        # Exception text from HTTP libraries may contain credentials; retain type only.
        result.update(error_type=type(error).__name__, source_bytes_identity_claimed=False)
    result['disposition'] = disposition(result)
    return result


def acquire(queue, config, directory):
    rows = read(queue)
    forbidden, _ = exclusions(config['deferred'])
    if any(u in forbidden for r in rows for u in r['original_urls']):
        raise ValueError('Queue contains deferred originals')
    session = requests.Session()
    session.trust_env = False
    if config.get('cookie_env'):
        session.headers['Cookie'] = os.environ[config['cookie_env']]
    completed = []
    with exclusive_run(directory):
        pins = {'queue_sha256': sha(Path(queue).read_bytes()), 'config': config}
        manifest = directory / 'plan.json'
        if manifest.exists() and read(manifest) != pins:
            raise ValueError('Run inputs changed; use a new receipt directory')
        save(manifest, pins)
        for row in rows:
            target = directory / request_id(row, config['provider'])
            target.mkdir(exist_ok=True)
            receipt = target / 'receipt.json'
            if receipt.exists():
                completed.append(read(receipt))
                continue  # Failed receipts also require an explicit separate campaign.
            if len(completed) >= config.get('max_requests', len(rows)):
                break
            time.sleep(config.get('delay_seconds', 30))
            result = fetch(row, config, target, session)
            save(receipt, result)
            completed.append(result)
            save(directory / 'results.json', completed)
            save(directory / 'progress.json', {'completed': len(completed), 'total': len(rows),
                                               'dispositions': dict(Counter(r['disposition'] for r in completed))})
            if result.get('status') in {401, 402, 403, 429} or result.get('content', {}).get('category') == 'error_or_challenge':
                break
    session.close()
    return {'completed': len(completed), 'total': len(rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--prior', type=Path, action='append', default=[])
    p.add_argument('--reservation', type=Path, action='append', default=[])
    p.add_argument('--deferred', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('pagination')
    p.add_argument('--pages', type=Path, required=True)
    p = sub.add_parser('acquire')
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--receipts', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        value = plan(args.queue, args.prior, args.reservation, args.deferred)
        save(args.output, value)
        print(json.dumps(value['counts']))
    elif args.command == 'pagination':
        print(json.dumps(pagination_state(read(args.pages))))
    else:
        print(json.dumps(acquire(args.queue, load_config(args.config), args.receipts)))


if __name__ == '__main__':
    main()
