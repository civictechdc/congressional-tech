#!/usr/bin/env python3
"""Explicit, bounded Web Harvest HTML acquisition; no import or publication.

Promotes the retained-first and Firecrawl request behavior from dated
recover_nara_html_continuation_04.py and recover_firecrawl_nara_scaled_02.py.
Historical evidence remains read-only. An attempted URL never becomes done merely
because it was present in a previous queue.
"""
import argparse
import base64
from collections import Counter
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit

import requests

from corpus_recovery.classify_recovery_html_transcripts import classify
from webharvest_validation import immutable, freeze, classify_cached, validate_pdf_frozen

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
    if category == 'error_or_challenge' or any(record.get(name) in {401, 402, 403, 429} for name in ('status', 'http_status', 'origin_status')):
        return 'retryable-failure'
    if record.get('error_type') or record.get('status', record.get('http_status', 0)) >= 500:
        return 'retryable-failure'
    return 'review-required'


def plan(queue, prior, reservations, deferred):
    forbidden_urls, forbidden_hashes = exclusions(deferred)
    previous = {}
    for path in prior:
        raw = Path(path).read_bytes()
        value = json.loads(raw)
        source_sha256 = sha(raw)
        for record in value if isinstance(value, list) else [value]:
            for url in record.get('original_urls', [record.get('original_url')]):
                previous[url] = (record, str(path), source_sha256)
    active = {}
    for path in reservations:
        reservation = read(path)
        for url in reservation['original_urls']:
            active[url] = (str(path), reservation_live(reservation['process']))
    rows = []
    for group in read(queue):
        for url in group['original_urls']:
            row = dict(original_url=url, candidates=group['candidates'], eligible=False)
            if url in forbidden_urls:
                row.update(disposition='review-required', reason='deferred_exclusion')
            elif url in active:
                path, live = active[url]
                row.update(disposition='active-reservation' if live else 'review-required',
                           evidence=path, reason='live_process' if live else 'stale_reservation_requires_review')
            elif url in previous:
                record, path, digest = previous[url]
                row.update(disposition='review-required' if record.get('sha256') in forbidden_hashes else disposition(record), evidence=path,
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
    if any('cursor' not in p for p in pages) or len({p['cursor'] for p in pages}) != len(pages):
        return {'complete': False, 'reason': 'missing_or_duplicate_cursor'}
    by_cursor = {p['cursor']: p for p in pages}
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
    if not 0 <= config.get('spent_to_date_usd', 0) <= 25:
        raise ValueError('Existing spend must be between zero and $25')
    if not 0 <= config.get('budget_usd', 0) <= 25:
        raise ValueError('Existing maximum budget is $25')
    if config['provider'] == 'firecrawl':
        if not config.get('credential_env') or type(config.get('max_requests')) is not int or config['max_requests'] <= 0:
            raise ValueError('Firecrawl needs credential_env and a finite max_requests')
        if config.get('request_ceiling_usd', 0) <= 0:
            raise ValueError('Explicit conservative per-request cost ceiling required')
        if config['max_requests'] * config['request_ceiling_usd'] + config.get('spent_to_date_usd', 0) > config.get('budget_usd', 0):
            raise ValueError('Request ceiling exceeds budget')
    if not 0 < config.get('max_body_bytes', 8 * 1024**2) <= 8 * 1024**2:
        raise ValueError('HTML body limit cannot exceed 8 MiB')
    if type(config.get('workers', 1)) is not int or not 1 <= config.get('workers', 1) <= 5:
        raise ValueError('Workers must be between one and five')
    if config.get('delay_seconds', 30) < 0:
        raise ValueError('Delay must be non-negative')
    return config


def checked_body(record):
    raw = Path(record['body_path']).read_bytes()
    if sha(raw) != record['sha256'] or len(raw) != record['bytes']:
        raise ValueError('Retained body hash or length changed')
    return raw


def fetch(row, config, directory, session, validation=None):
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
        download = directory / 'download.json'
        if download.exists():
            result = read(download)
            raw = checked_body(result)
            result['original_urls'] = row['original_urls']
            result['candidate'] = candidate
        elif config['provider'] == 'retained':
            retained = row['retained']
            raw = checked_body(retained)
            result.update(status=retained['status'], complete=retained['complete'],
                          final_url=retained['final_url'], reused_evidence=retained['evidence'],
                          rendered_copy=retained.get('rendered_copy', False),
                          origin_status=retained.get('origin_status'),
                          provider_metadata=retained.get('provider_metadata'))
        elif config['provider'] == 'direct':
            target_headers = {'Accept-Encoding': 'identity'}
            if config.get('cookie_env'):
                target_headers['Cookie'] = os.environ[config['cookie_env']]
            with session.get(url, stream=True, allow_redirects=False,
                             timeout=(15, 45), headers=target_headers) as response:
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
            if config.get('cookie_env'):
                payload['headers'] = {'Cookie': os.environ[config['cookie_env']]}
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
        if body.exists() and body.read_bytes() != raw:
            raise ValueError('Existing retained download changed')
        if not body.exists():
            with body.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        result.update(body_path=str(body.resolve()), bytes=len(raw), sha256=sha(raw))
        if not download.exists():
            immutable(download, result)
        digest = base64.b32encode(hashlib.sha1(raw).digest()).decode().rstrip('=')
        result.update(index_digest_matches=digest == candidate.get('digest', '').removeprefix('sha1:'),
                      sha1_base32=digest)
        if validation is None:
            result['content'] = classify(raw)
        else:
            cache, snapshot, validator = validation
            result['content'], result['classification'] = classify_cached(raw, cache, snapshot, validator)
        _, forbidden = exclusions(config['deferred'])
        result['excluded_deferred_body'] = result['sha256'] in forbidden
        result['valid'] = bool(result['complete'] and result['status'] == 200 and
                               result['final_url'] == url and
                               (result['rendered_copy'] or result['index_digest_matches']) and
                               (not result['rendered_copy'] or result.get('origin_status') == 200) and
                               not result['excluded_deferred_body'] and
                               result['content']['category'] == 'substantial_document_body')
        result['source_bytes_identity_claimed'] = bool(result['valid'] and not result['rendered_copy'])
    except Exception as error:
        # Exception text from HTTP libraries may contain credentials; retain type only.
        result.update(error_type=type(error).__name__, source_bytes_identity_claimed=False)
    result['disposition'] = disposition(result)
    return result


def receipt_rows(directory):
    """Read only immutable completed receipts; no aggregate is authoritative."""
    return [read(path) for path in sorted((directory / 'requests').glob('*/receipt.json'))]


def progress(directory, total):
    rows = receipt_rows(directory)
    return {'completed': len(rows), 'total': total,
            'dispositions': dict(Counter(r['disposition'] for r in rows)),
            'downloads_started': len(list((directory / 'downloads').glob('*/started.json'))),
            'complete': len(rows) == total}


def aggregate(directory):
    rows = receipt_rows(directory)
    save(directory / 'results.json', rows)  # One explicit final/recovery aggregation.
    value = progress(directory, read(directory / 'plan.json')['groups'])
    save(directory / 'progress.json', value)
    return value


def refused(record):
    return (any(record.get(name) in {401, 402, 403, 429} for name in ('status', 'origin_status'))
            or bool(record.get('headers', {}).get('retry-after'))
            or record.get('content', {}).get('category') == 'error_or_challenge')


def acquire(queue, config, directory):
    rows = read(queue)
    forbidden, _ = exclusions(config['deferred'])
    if any(u in forbidden for r in rows for u in r['original_urls']):
        raise ValueError('Queue contains deferred originals')
    if len({request_id(r, config['provider']) for r in rows}) != len(rows):
        raise ValueError('Duplicate queue groups')
    workers = config.get('workers', 5 if config['provider'] == 'firecrawl' else 1)
    if type(workers) is not int or not 1 <= workers <= 5:
        raise ValueError('Workers must be between one and five')
    with exclusive_run(directory):
        pins = {'queue_sha256': sha(Path(queue).read_bytes()), 'config': config,
                'deferred_sha256': sha(Path(config['deferred']).read_bytes()), 'groups': len(rows)}
        manifest = directory / 'plan.json'
        if manifest.exists() and read(manifest) != pins:
            raise ValueError('Run inputs changed; use a new receipt directory')
        if not manifest.exists():
            immutable(manifest, pins)
        snapshot = directory / 'validator'
        validator = freeze(snapshot, {'deferred_sha256': pins['deferred_sha256'],
                                      'provider': config['provider'], 'kind': 'html'})
        validation = (directory / 'classification-cache', snapshot, validator)
        existing = receipt_rows(directory)
        counts = Counter(r['disposition'] for r in existing)
        completed = len(existing)
        started = len(list((directory / 'downloads').glob('*/started.json')))
        for prior in existing:
            if prior.get('body_path'):
                checked_body(prior)
        if any(refused(prior) for prior in existing):
            return aggregate(directory)
        # Group aliases before parallel admission so one replay URL gets one request.
        jobs = {}
        for row in rows:
            target = directory / 'requests' / request_id(row, config['provider']) / 'receipt.json'
            if target.exists():
                continue
            download_id = sha((config['provider'] + row['candidates'][0]['replay_url']).encode())
            jobs.setdefault(download_id, []).append((row, target))
        ownership = process_identity()
        stop = threading.Event()
        start_lock = threading.Lock()
        admission_lock = threading.Lock()
        last_start = [None]
        interval = config.get('delay_seconds', 1 if config['provider'] == 'firecrawl' else 30)

        def interrupted(row, reason, evidence):
            return {'original_urls': row['original_urls'], 'candidate': row['candidates'][0],
                    'valid': False, 'disposition': 'review-required', 'reason': reason,
                    'request_evidence': str(evidence.resolve())}

        def work(group, download, fresh):
            begun = download / 'started.json'
            if fresh:
                # One global start clock, including all parallel worker sessions.
                with start_lock:
                    remaining = 0 if last_start[0] is None else max(0, interval - (time.monotonic() - last_start[0]))
                    if stop.wait(remaining) or stop.is_set():
                        return [(target, interrupted(row, 'stopped_before_request', begun)) for row, target in group]
                    last_start[0] = time.monotonic()
            session = requests.Session()
            session.trust_env = False
            results = []
            first = None
            try:
                for row, target in group:
                    if not fresh and not (download / 'download.json').exists():
                        result = interrupted(row, 'interrupted_request_without_complete_receipt', begun)
                    elif first is not None and not (download / 'download.json').exists():
                        result = dict(first, original_urls=row['original_urls'], candidate=row['candidates'][0])
                    else:
                        result = fetch(row, config, download, session, validation)
                    if refused(result):
                        with admission_lock:
                            stop.set()  # Stop admission before returning to the supervisor.
                    first = result
                    results.append((target, result))
            finally:
                session.close()
            return results

        pending = set()
        cursor = iter(jobs.items())
        exhausted = False
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while pending or not exhausted:
                while not exhausted and not stop.is_set() and len(pending) < workers:
                    try:
                        download_id, group = next(cursor)
                    except StopIteration:
                        exhausted = True
                        break
                    download = directory / 'downloads' / download_id
                    download.mkdir(parents=True, exist_ok=True)
                    begun = download / 'started.json'
                    fresh = not begun.exists()
                    with admission_lock:
                        if stop.is_set():
                            exhausted = True
                            break
                        if fresh:
                            if started >= config.get('max_requests', len(rows)):
                                exhausted = True
                                break
                            immutable(begun, {'process': ownership, 'at': now(),
                                              'requested_url': group[0][0]['candidates'][0]['replay_url'],
                                              'provider': config['provider']})
                            started += 1
                        pending.add(pool.submit(work, group, download, fresh))
                if stop.is_set():
                    exhausted = True
                if not pending:
                    break
                ready, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in ready:
                    for target, result in future.result():
                        immutable(target, result)
                        completed += 1
                        counts[result['disposition']] += 1
                        save(directory / 'progress.json', {'completed': completed, 'total': len(rows),
                             'dispositions': dict(counts), 'downloads_started': started,
                             'complete': completed == len(rows)})
        return aggregate(directory)


def qualify(sources, directory, deferred, *, kind='html', preview=False):
    """Snapshot completed receipts from any worker without mutable code pins.

    Input receipts identify complete response bodies with SHA-256 and length.
    Worker completion and current historical script bytes are never prerequisites.
    """
    forbidden_urls, forbidden_hashes = exclusions(deferred)
    with exclusive_run(directory):
        config = {'kind': kind, 'deferred_sha256': sha(Path(deferred).read_bytes())}
        snapshot = directory / 'validator'
        validator = freeze(snapshot, config)
        qualified = 0
        for source in sources:
            raw_receipt = Path(source).read_bytes()
            record = json.loads(raw_receipt)
            source_sha = sha(raw_receipt)
            output = directory / 'requests' / source_sha / 'receipt.json'
            if output.exists():
                prior = read(output)
                if prior.get('body_path'):
                    checked_body(prior)
                qualified += bool(prior['valid'])
                continue
            result = {'source_receipt': str(Path(source).resolve()), 'source_receipt_sha256': source_sha,
                      'validator_sha256': validator['validator_sha256'], 'valid': False,
                      'worker_completion_claimed': False, 'kind': kind,
                      'original_urls': record.get('original_urls', [record.get('original_url')]),
                      'rendered_copy': record.get('rendered_copy', False),
                      'provider': record.get('provider'), 'candidate': record.get('candidate'),
                      'requested_url': record.get('requested_url', record.get('url')),
                      'final_url': record.get('final_url', record.get('metadata', {}).get('url')),
                      'provider_metadata': record.get('provider_metadata', record.get('metadata'))}
            try:
                raw = checked_body(record)
                result.update(body_path=record['body_path'], bytes=len(raw), sha256=sha(raw))
                if sha(raw) in forbidden_hashes or any(u in forbidden_urls for u in result['original_urls']):
                    result['reason'] = 'deferred_exclusion'
                elif not record.get('complete', False) or record.get('status', record.get('http_status')) != 200:
                    result['reason'] = 'incomplete_or_unsuccessful_source'
                elif kind == 'pdf':
                    # Cache by body plus validator, shared by repeated source receipts.
                    cached = directory / 'pdf-cache' / (sha(raw) + '-' + validator['validator_sha256'])
                    acceptance = cached / 'acceptance.json'
                    if not acceptance.exists():
                        immutable(acceptance, validate_pdf_frozen(Path(record['body_path']), cached, snapshot, validator, preview=preview))
                    result['validation'] = read(acceptance)
                    result['valid'] = result['validation']['valid_pdf']
                else:
                    result['content'], result['classification'] = classify_cached(raw, directory / 'classification-cache', snapshot, validator)
                    candidate = record.get('candidate', {})
                    rendered = result['rendered_copy']
                    expected = candidate.get('replay_url')
                    actual = result['final_url']
                    archive_match = base64.b32encode(hashlib.sha1(raw).digest()).decode().rstrip('=') == candidate.get('digest', '').removeprefix('sha1:')
                    origin = record.get('origin_status', (result['provider_metadata'] or {}).get('statusCode'))
                    result['valid'] = bool(expected and expected == actual and
                                           candidate.get('match_basis') == 'exact_canonical_url' and
                                           (origin == 200 if rendered else archive_match) and
                                           result['content']['category'] == 'substantial_document_body')
                result['source_bytes_identity_claimed'] = bool(result['valid'] and kind == 'html' and not result['rendered_copy'])
            except Exception as error:
                result['error_type'] = type(error).__name__
            result['disposition'] = disposition(result)
            immutable(output, result)
            qualified += bool(result['valid'])
        save(directory / 'qualification-summary.json', {'source_receipts': len(sources), 'qualified': qualified,
             'worker_completion_claimed': False, 'validator_sha256': validator['validator_sha256']})
    return {'source_receipts': len(sources), 'qualified': qualified}


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
    p = sub.add_parser('aggregate')
    p.add_argument('--receipts', type=Path, required=True)
    p = sub.add_parser('qualify')
    p.add_argument('--source', type=Path, action='append', required=True)
    p.add_argument('--receipts', type=Path, required=True)
    p.add_argument('--deferred', type=Path, required=True)
    p.add_argument('--kind', choices=['html', 'pdf'], default='html')
    p.add_argument('--preview', action='store_true')
    p = sub.add_parser('acquire')
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--receipts', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        value = plan(args.queue, args.prior, args.reservation, args.deferred)
        save(args.output, value)
        print(json.dumps(value['counts']))
    elif args.command == 'aggregate':
        with exclusive_run(args.receipts):
            print(json.dumps(aggregate(args.receipts)))
    elif args.command == 'qualify':
        print(json.dumps(qualify(args.source, args.receipts, args.deferred, kind=args.kind, preview=args.preview)))
    elif args.command == 'pagination':
        print(json.dumps(pagination_state(read(args.pages))))
    else:
        print(json.dumps(acquire(args.queue, load_config(args.config), args.receipts)))


if __name__ == '__main__':
    main()
