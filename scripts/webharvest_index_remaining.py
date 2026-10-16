#!/usr/bin/env python3
"""Read-only Web Harvest index audit of a retained remaining-URL snapshot.

No replay requests, downloads, proxy use, or catalog mutations. Retained complete
host searches cover negatives; incomplete searches provide positive leads only.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from surt import surt

FIELDS = ['urlkey', 'timestamp', 'url', 'mime', 'status', 'digest', 'unused', 'flags', 'length', 'offset', 'filename']
COLLECTIONS = [f'congress{n}th' for n in range(109, 119)]


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def load(path):
    return json.loads(path.read_text())


def key(url):
    try:
        p = urlsplit(url)
        if p.scheme not in {'http', 'https'} or not p.hostname or '.' not in p.hostname or p.username or p.password:
            return None
        if any(c.isspace() for c in p.netloc):
            return None
        return surt(url)
    except ValueError:
        return None


def parse_cdx(raw):
    rows, resume = [], None
    for line in raw.decode('utf-8').splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) == 11 and re.fullmatch(r'\d{14}', parts[1]):
            rows.append(dict(zip(FIELDS, parts)))
        elif len(parts) == 1 and re.fullmatch(r'[A-Za-z0-9_=-]+', parts[0]) and resume is None:
            resume = parts[0]
        else:
            raise ValueError('not_cdx_text')
    return rows, resume


def key_pattern(keys):
    """Factor a prefix tree while preserving exact literal matches."""
    import os
    def branch(values):
        prefix = os.path.commonprefix(values)
        tails = [v[len(prefix):] for v in values]
        groups = defaultdict(list)
        for tail in tails:
            groups[tail[:1]].append(tail)
        if list(groups) == ['']:
            return re.escape(prefix)
        options = [branch(group) if char else '' for char, group in sorted(groups.items())]
        return re.escape(prefix) + '(?:' + '|'.join(options) + ')'
    return '^' + branch(sorted(set(keys))) + '$'


def params(host, keys):
    return [('url', host), ('matchType', 'host'), ('filter', 'statuscode:200'),
            ('filter', 'urlkey:' + key_pattern(keys)), ('limit', '50000'), ('showResumeKey', 'true')]


def job_params(job):
    if job.get('mode') == 'host':
        return [('url', job['host']), ('matchType', 'host'), ('filter', 'statuscode:200'),
                ('collapse', 'urlkey'), ('limit', '50000'), ('showResumeKey', 'true')]
    return params(job['host'], job['keys'])


def batches(host, keys):
    batch = []
    for item in sorted(set(keys)):
        trial = batch + [item]
        if batch and len(urlencode(params(host, trial))) > 3600:
            yield batch
            batch = []
        batch.append(item)
    if batch:
        yield batch


class Audit:
    def __init__(self, output, delay, reuse_audits=(), host_first=False, *, bulk_recovery=None, archive_ladder=None):
        self.output, self.delay = output, delay
        self.reuse_audits = reuse_audits
        self.host_first = host_first
        self.session = requests.Session()
        self.session.trust_env = False
        self.bulk = bulk_recovery
        self.old = archive_ladder
        self.last = 0
        self.request_count = 0
        self.blocked = None
        self.covered = defaultdict(set)
        self.matches = defaultdict(dict)
        self.evidence = []
        self.errors = []
        self.jobs = []
        self.done_jobs = 0

    def prepare(self):
        paths = [self.bulk / 'targets.csv', self.bulk / 'publication-1386/accepted-additions.json',
                 self.bulk / 'publication-1386/complete.json', self.bulk / 'publication-1386/live-reader-verification.json',
                 self.old / 'coverage.json']
        raw = {str(p): p.read_bytes() for p in paths}
        records = list(csv.DictReader(io.StringIO(raw[str(paths[0])].decode('utf-8-sig'))))
        accepted = {r['original_url'] for r in json.loads(raw[str(paths[1])])}
        assert json.loads(raw[str(paths[2])])['complete']
        assert json.loads(raw[str(paths[3])])['verified']
        self.urls = sorted({r['url'] for r in records} - accepted)
        self.by_key, self.by_host = defaultdict(list), defaultdict(set)
        self.invalid = []
        for url in self.urls:
            canonical = key(url)
            if canonical is None:
                self.invalid.append(url)
                continue
            self.by_key[canonical].append(url)
            self.by_host[urlsplit(url).hostname.lower()].add(canonical)
        assert len(self.urls) == json.loads(raw[str(paths[2])])['remaining_urls']
        save(self.output / 'input-manifest.json', {'created_at': now(), 'remaining_urls': len(self.urls),
            'excluded_accepted_recoveries': len(accepted), 'collections': COLLECTIONS,
            'scope': 'All remaining URLs, including non-PDF and unlisted domains. Index metadata only, direct sequential requests.',
            'inputs': [{'path': p, 'sha256': digest(data), 'bytes': len(data)} for p, data in raw.items()]})
        save(self.output / 'remaining-urls.json', self.urls)
        for coverage in json.loads(raw[str(paths[-1])]):
            if coverage['source'] != 'congressional_web_harvest' or coverage['host'] not in self.by_host:
                continue
            valid, final_resume, evidence = True, None, []
            for request_id in coverage['requests']:
                candidates = sorted((self.old / 'requests').glob(request_id + '-*.json'))
                chosen = None
                for candidate in candidates:
                    receipt = load(candidate)
                    body_path = Path(receipt['body_path'])
                    if not receipt.get('complete') or receipt.get('status') != 200 or not body_path.exists():
                        continue
                    body = body_path.read_bytes()
                    if digest(body) != receipt['sha256']:
                        continue
                    query = parse_qs(urlsplit(receipt['url']).query)
                    if query.get('url') != [coverage['host']] or query.get('matchType') != ['host'] or 'statuscode:200' not in query.get('filter', []):
                        continue
                    try:
                        rows, resume = parse_cdx(body)
                        if any(row['status'] != '200' for row in rows):
                            raise ValueError('status_filter_not_applied')
                    except (ValueError, UnicodeError):
                        continue
                    chosen = (rows, resume, receipt, str(candidate))
                if chosen is None:
                    valid = False
                    continue
                rows, final_resume, receipt, meta_path = chosen
                proof = {'metadata': meta_path, 'body_path': receipt['body_path'], 'sha256': receipt['sha256']}
                evidence.append(proof)
                self.add_matches(rows, coverage['collection'], proof)
            complete = bool(valid and coverage['complete'] and final_resume is None and evidence)
            self.evidence.append({'host': coverage['host'], 'collection': coverage['collection'],
                                  'complete': complete, 'source': 'retained_host_index', 'requests': evidence})
            if complete:
                for canonical in self.by_host[coverage['host']]:
                    self.covered[canonical].add(coverage['collection'])
        for prior in self.reuse_audits:
            self.reuse_audit(prior)
        save(self.output / 'retained-coverage.json', self.evidence)
        for host in sorted(self.by_host, key=lambda h: (-len(self.by_host[h]), h)):
            for collection in reversed(COLLECTIONS):
                wanted = [k for k in self.by_host[host] if collection not in self.covered[k]]
                if wanted and self.host_first:
                    self.jobs.append({'host': host, 'collection': collection, 'keys': sorted(wanted), 'mode': 'host'})
                else:
                    for batch in batches(host, wanted):
                        self.jobs.append({'host': host, 'collection': collection, 'keys': batch})
        save(self.output / 'query-plan.json', self.jobs)
        self.report()

    def reuse_audit(self, prior):
        """Reuse complete, hash-verified target queries from an interrupted run."""
        if load(prior / 'remaining-urls.json') != self.urls:
            raise ValueError('prior_audit_target_snapshot_mismatch')
        for coverage in load(prior / 'coverage.json'):
            if coverage['source'] not in {'fresh_targeted_index', 'fresh_host_index'}:
                continue
            if coverage['collection'] not in COLLECTIONS or coverage['host'] not in self.by_host:
                continue
            expected = set(coverage['keys'])
            if not expected <= self.by_host[coverage['host']]:
                raise ValueError('prior_audit_unexpected_keys')
            proofs = []
            complete = False
            for proof in coverage['requests']:
                receipt = load(Path(proof['metadata']))
                raw = Path(proof['body_path']).read_bytes()
                expected_url = f"https://webharvest.gov/{coverage['collection']}/timemap/cdx?" + urlencode(job_params(coverage))
                if (receipt.get('status') != 200 or not receipt.get('complete')
                        or receipt['url'] != expected_url or digest(raw) != proof['sha256']
                        or receipt['sha256'] != proof['sha256']):
                    raise ValueError('prior_audit_evidence_mismatch')
                if not raw and 'text/plain' not in receipt['headers'].get('content-type', ''):
                    raise ValueError('prior_audit_empty_non_index_response')
                rows, resume = parse_cdx(raw)
                if any(r['status'] != '200' or (coverage.get('mode') != 'host' and r['urlkey'] not in expected) for r in rows):
                    raise ValueError('prior_audit_filter_mismatch')
                self.add_matches(rows, coverage['collection'], proof)
                proofs.append(proof)
                complete = resume is None
            if proofs:
                self.evidence.append({**coverage, 'complete': complete, 'reused_from': str(prior.resolve())})
                if complete:
                    for canonical in expected:
                        self.covered[canonical].add(coverage['collection'])

    def add_matches(self, rows, collection, evidence):
        for row in rows:
            if row['urlkey'] not in self.by_key or row['status'] != '200':
                continue
            ident = (collection, row['timestamp'], row['url'], row['digest'])
            self.matches[row['urlkey']][ident] = {**row, 'collection': collection, 'evidence': evidence,
                'replay_url': f"https://webharvest.gov/{collection}/{row['timestamp']}id_/{row['url']}",
                'availability': 'index_match_not_download_verified'}

    def fetch(self, job, attempt=0):
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.request_count += 1
        name = f'{self.request_count:05d}'
        path = self.output / 'requests' / (name + '.body')
        path.parent.mkdir(exist_ok=True)
        url = f"https://webharvest.gov/{job['collection']}/timemap/cdx?" + urlencode(job_params(job))
        receipt = {'requested_at': now(), 'url': url, 'attempt': attempt, 'route': 'direct', 'complete': False}
        try:
            with self.session.get(url, allow_redirects=False, timeout=(15, 45), stream=True) as response, path.open('wb') as stream:
                receipt.update(status=response.status_code, headers={k.lower(): v for k, v in response.headers.items() if k.lower() != 'set-cookie'})
                count = 0
                for chunk in response.iter_content(65536):
                    count += len(chunk)
                    if count > 32 * 1024 * 1024:
                        raise ValueError('index_response_size_limit')
                    stream.write(chunk)
                receipt['complete'] = True
        except (requests.RequestException, ValueError) as error:
            receipt['error_type'] = type(error).__name__
        finally:
            self.last = time.monotonic()
        raw = path.read_bytes() if path.exists() else b''
        receipt.update(bytes=len(raw), sha256=digest(raw), body_path=str(path.resolve()))
        save(path.with_suffix('.json'), receipt)
        if receipt.get('status') == 429 or b'rate limit reached' in raw[:16384].lower():
            if attempt < 2:
                print(json.dumps({'event': 'rate_limit_cooldown', 'seconds': 60, 'attempt': attempt}), flush=True)
                time.sleep(60)
                return self.fetch(job, attempt + 1)
            self.blocked = 'rate_limited_after_two_cooldowns'
        if receipt.get('status') in {401, 403} or b'session verification' in raw[:16384].lower():
            self.blocked = 'access_verification_required'
        if (not receipt['complete'] or receipt.get('status') in {500, 502, 503, 504}) and attempt < 1:
            return self.fetch(job, attempt + 1)
        if not receipt['complete'] or receipt.get('status') != 200 or self.blocked:
            raise ValueError(self.blocked or 'incomplete_or_http_error')
        if not raw and 'text/plain' not in receipt['headers'].get('content-type', ''):
            raise ValueError('empty_non_index_response')
        rows, resume = parse_cdx(raw)
        expected = set(job['keys'])
        if any(r['status'] != '200' or (job.get('mode') != 'host' and r['urlkey'] not in expected) for r in rows):
            raise ValueError('server_filter_not_applied')
        proof = {'metadata': str(path.with_suffix('.json').resolve()), 'body_path': str(path.resolve()), 'sha256': receipt['sha256']}
        self.add_matches(rows, job['collection'], proof)
        source = 'fresh_host_index' if job.get('mode') == 'host' else 'fresh_targeted_index'
        self.evidence.append({**job, 'source': source, 'complete': resume is None, 'resume': resume, 'requests': [proof], 'rows': len(rows)})
        if resume:
            if job.get('mode') == 'host':
                self.jobs.extend([{'host': job['host'], 'collection': job['collection'], 'keys': b}
                                  for b in batches(job['host'], job['keys'])])
            elif len(job['keys']) == 1:
                raise ValueError('single_url_index_truncated')
            else:
                midpoint = len(job['keys']) // 2
                self.jobs.extend([{**job, 'keys': job['keys'][:midpoint]}, {**job, 'keys': job['keys'][midpoint:]}])
            save(self.output / 'query-plan.json', self.jobs)
        else:
            for canonical in job['keys']:
                self.covered[canonical].add(job['collection'])

    def report(self):
        counts = Counter()
        with (self.output / 'url-results.jsonl').open('w') as stream:
            for url in self.urls:
                canonical = key(url)
                captures = list(self.matches.get(canonical, {}).values())
                complete = sorted(self.covered.get(canonical, set()))
                status = ('invalid_source_url' if canonical is None else 'http_200_capture_found' if captures else
                          'no_http_200_capture_in_checked_collections' if len(complete) == len(COLLECTIONS) else 'unresolved_index_coverage')
                row = {'original_url': url, 'urlkey': canonical, 'status': status,
                       'complete_collections': complete, 'unresolved_collections': sorted(set(COLLECTIONS) - set(complete)),
                       'captures': captures}
                stream.write(json.dumps(row) + '\n')
                counts[status] += 1
                if canonical is not None and len(complete) == len(COLLECTIONS):
                    counts['urls_with_complete_collection_coverage'] += 1
                if any(c['mime'].lower() in {'application/pdf', 'application/x-pdf'} for c in captures):
                    counts['urls_with_pdf_mime_capture'] += 1
        summary = {'updated_at': now(), 'remaining_urls': len(self.urls), 'valid_canonical_urls': len(self.by_key),
                   'domains': len(self.by_host), 'counts': dict(counts), 'direct_requests': self.request_count,
                   'planned_jobs': len(self.jobs), 'completed_jobs': self.done_jobs, 'blocked': self.blocked,
                   'scope': 'Web Harvest Congresses 109-118. Reused verified retained indexes and fresh filtered queries. Index matches are not downloaded or validated recoveries.'}
        save(self.output / 'summary.json', summary)
        save(self.output / 'coverage.json', self.evidence)
        save(self.output / 'query-errors.json', self.errors)
        return summary

    def run(self):
        self.prepare()
        print(json.dumps(self.report()), flush=True)
        while self.done_jobs < len(self.jobs) and not self.blocked:
            job = self.jobs[self.done_jobs]
            try:
                self.fetch(job)
            except (ValueError, UnicodeError) as error:
                self.errors.append({**job, 'reason': str(error)})
            self.done_jobs += 1
            summary = self.report()
            print(json.dumps({'done': self.done_jobs, 'total': len(self.jobs), 'host': job['host'], 'collection': job['collection'],
                              'counts': summary['counts'], 'blocked': self.blocked}), flush=True)
        save(self.output / 'completion.json', {'completed_at': now(), 'all_planned_queries_attempted': self.done_jobs == len(self.jobs), **self.report()})
        self.session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delay', type=float, default=5.0)
    parser.add_argument('--reuse-audit', type=Path, action='append', default=[])
    parser.add_argument('--host-first', action='store_true', help='Try larger host indexes before exact target batches')
    parser.add_argument('--bulk-recovery', type=Path, required=True,
                        help='Bulk recovery run holding targets.csv and publication-1386/ (first used: .cache/document-bulk-recovery-20261014T1552Z)')
    parser.add_argument('--archive-ladder', type=Path, required=True,
                        help='Archive ladder run holding coverage.json and requests/ (first used: .cache/document-archive-ladder-20261013T1835Z)')
    args = parser.parse_args()
    if (args.output / 'input-manifest.json').exists():
        raise ValueError('Use a new output directory to preserve prior audit evidence')
    args.output.mkdir(parents=True, exist_ok=True)
    Audit(args.output, args.delay, args.reuse_audit, args.host_first,
          bulk_recovery=args.bulk_recovery, archive_ladder=args.archive_ladder).run()


if __name__ == '__main__':
    main()
