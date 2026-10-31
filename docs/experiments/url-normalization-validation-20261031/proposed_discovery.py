"""Bounded discovery leads; acquisition, custody and acceptance belong to callers.

Every call is dispatched through the injected capture function, which must reserve
and account for the request before making it and retain the referenced evidence.
"""
from dataclasses import dataclass
from datetime import datetime
import base64
import hashlib
from itertools import islice
import json
import re
from urllib.parse import urlencode, urlsplit


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    complete: bool
    evidence: str
    content_type: str = ''
    final_url: str | None = None


def _source_url(url):
    try:
        p = urlsplit(url)
        return (p.scheme in ('http', 'https') and bool(p.hostname) and not (p.username or p.password or p.fragment)
                and not any(c.isspace() or ord(c) < 32 or c == '\\' for c in url)
                and (p.port is None or 0 < p.port < 65536))
    except (ValueError, TypeError):
        return False


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{14}', value):
        return False
    try:
        datetime.strptime(value, '%Y%m%d%H%M%S')
        return True
    except ValueError:
        return False


def _capture(call, kind, url):
    response = call(kind, url)
    if not isinstance(response, Response) or not response.evidence:
        raise ValueError('capture must return Response with durable evidence reference')
    return response


def webharvest_lookup(original, collection, call, *, parse_cdx, url_key, max_pages, page_size=1000):
    """Query a single exact URL, retaining each page's capture evidence.

    parse_cdx and url_key are the maintained Web Harvest helpers. The injected
    call must enforce response-byte limits in addition to these page limits.
    """
    if not _source_url(original) or not re.fullmatch(r'congress(?:10[9]|11[0-8])th', collection):
        raise ValueError('invalid target or collection')
    if max_pages < 1 or not 1 <= page_size <= 50000:
        raise ValueError('invalid page limit')
    expected = url_key(original)
    if expected is None:
        raise ValueError('invalid target key')
    seen, candidates, evidence = set(), {}, []
    resume = None
    reason = 'page_limit'
    for _ in range(max_pages):
        params = [('url', original), ('matchType', 'exact'), ('filter', 'statuscode:200'),
                  ('limit', str(page_size)), ('showResumeKey', 'true')]
        if resume:
            params.append(('resumeKey', resume))
        url = f'https://webharvest.gov/{collection}/timemap/cdx?' + urlencode(params)
        response = _capture(call, 'cdx', url)
        evidence.append({'url': url, 'ref': response.evidence, 'status': response.status,
                         'complete_body': response.complete})
        if response.status != 200 or not response.complete or response.final_url != url:
            reason = 'denied' if response.status in (401, 403, 429) else 'incomplete_response'
            break
        if not response.body and 'text/plain' not in response.content_type.lower():
            reason = 'invalid_empty_response'
            break
        try:
            rows, next_resume = parse_cdx(response.body)
            if any(r['status'] != '200' or r['urlkey'] != expected or url_key(r['url']) != expected for r in rows):
                raise ValueError('index filter mismatch')
        except (ValueError, UnicodeError, KeyError):
            reason = 'invalid_index_response'
            break
        for row in rows:
            if not _timestamp(row['timestamp']) or not _source_url(row['url']):
                reason = 'invalid_index_response'
                return {'complete': False, 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}
            replay = f"https://webharvest.gov/{collection}/{row['timestamp']}id_/{row['url']}"
            ident = (row['timestamp'], row['url'], row['digest'])
            candidates[ident] = {'target_url': original, 'url': replay, 'original_url': row['url'],
                                 'timestamp': row['timestamp'], 'digest': row['digest'],
                                 'source': 'webharvest', 'collection': collection, 'evidence': response.evidence}
        if not next_resume:
            reason = 'complete'
            break
        if next_resume in seen:
            reason = 'repeated_resume_key'
            break
        seen.add(next_resume)
        resume = next_resume
    return {'complete': reason == 'complete', 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}


def campaign_lookup(original, collection, capture, *, max_pages, page_size=1000):
    from corpus_recovery.cdx import key, parse_cdx
    return webharvest_lookup(original, collection, capture, parse_cdx=parse_cdx,
                             url_key=key, max_pages=max_pages, page_size=page_size)


def validate_wayback_replay(replay, original, timestamp):
    """Require an exact identity replay and exact literal original URL."""
    if not _source_url(original) or not _timestamp(timestamp):
        return False
    try:
        p = urlsplit(replay)
        return (p.scheme == 'https' and p.netloc == 'web.archive.org' and not p.fragment
                and replay == f'https://web.archive.org/web/{timestamp}id_/{original}')
    except ValueError:
        return False


def _wayback_page(body):
    """Parse the documented JSON CDX result, including its resume trailer."""
    data = json.loads(body)
    fields = ['urlkey', 'timestamp', 'original', 'mimetype', 'statuscode', 'digest', 'length']
    if data == []:
        return [], None
    if not isinstance(data, list) or not data or data[0] != fields:
        raise ValueError('invalid CDX header')
    rows, resume = [], None
    for index, item in enumerate(data[1:], 1):
        if item == [] and index == len(data) - 2:
            trailer = data[-1]
            if not isinstance(trailer, list) or len(trailer) != 1 or not isinstance(trailer[0], str) or not trailer[0]:
                raise ValueError('invalid CDX resume trailer')
            resume = trailer[0]
            break
        if not isinstance(item, list) or len(item) != len(fields) or not all(isinstance(v, str) for v in item):
            raise ValueError('invalid CDX row')
        rows.append(dict(zip(fields, item)))
    return rows, resume


def wayback_lookup(original, call, *, max_pages, page_size=1000, from_timestamp=None, to_timestamp=None):
    """Find exact literal-URL captures; a negative covers only this query window."""
    if not _source_url(original) or max_pages < 1 or not 1 <= page_size <= 50000:
        raise ValueError('invalid target or limits')
    for bound in (from_timestamp, to_timestamp):
        if bound is not None and not re.fullmatch(r'\d{4}(?:\d{2}){0,5}', bound):
            raise ValueError('invalid archive time bound')
    if from_timestamp and to_timestamp and from_timestamp.ljust(14, '0') > to_timestamp.ljust(14, '9'):
        raise ValueError('reversed archive time bounds')
    seen, candidates, evidence = set(), {}, []
    resume, reason = None, 'page_limit'
    for _ in range(max_pages):
        params = [('url', original), ('matchType', 'exact'), ('filter', 'statuscode:200'),
                  ('output', 'json'), ('limit', str(page_size)), ('showResumeKey', 'true')]
        if from_timestamp:
            params.append(('from', from_timestamp))
        if to_timestamp:
            params.append(('to', to_timestamp))
        if resume:
            params.append(('resumeKey', resume))
        url = 'https://web.archive.org/cdx/search/cdx?' + urlencode(params)
        response = _capture(call, 'cdx', url)
        evidence.append({'url': url, 'ref': response.evidence, 'status': response.status,
                         'complete_body': response.complete})
        if response.status != 200 or not response.complete or response.final_url != url:
            reason = 'denied' if response.status in (401, 403, 429) else 'incomplete_response'
            break
        try:
            rows, next_resume = _wayback_page(response.body)
            for row in rows:
                ts = row['timestamp']
                if (not _source_url(row['original']) or key(original) is None or row['urlkey'] != key(original) or key(row['original']) != key(original) or row['statuscode'] != '200'
                        or not _timestamp(ts)
                        or (from_timestamp and ts < from_timestamp.ljust(14, '0'))
                        or (to_timestamp and ts > to_timestamp.ljust(14, '9'))):
                    raise ValueError('CDX result outside query')
        except (ValueError, UnicodeError, TypeError):
            reason = 'invalid_index_response'
            break
        for row in rows:
            replay = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"
            ident = (row['timestamp'], row['original'], row['digest'])
            candidates[ident] = {'target_url': original, 'url': replay, 'original_url': row['original'],
                                 'timestamp': row['timestamp'], 'digest': row['digest'],
                                 'source': 'wayback', 'evidence': response.evidence}
        if not next_resume:
            reason = 'complete'
            break
        if next_resume in seen:
            reason = 'repeated_resume_key'
            break
        seen.add(next_resume)
        resume = next_resume
    return {'complete': reason == 'complete', 'reason': reason, 'candidates': list(candidates.values()),
            'evidence': evidence, 'window': {'from': from_timestamp, 'to': to_timestamp}}


def _verify_digest(body, digest):
    if digest and digest != '-':
        if not re.fullmatch(r'[A-Z2-7]{32}', digest):
            raise ValueError('unsupported archive digest')
        actual = base64.b32encode(hashlib.sha1(body).digest()).decode('ascii')
        if actual != digest:
            raise ValueError('archive replay digest mismatch')


def acquire_wayback(replay, original, timestamp, call, *, digest=None):
    if not validate_wayback_replay(replay, original, timestamp):
        raise ValueError('wayback replay identity mismatch')
    response = _capture(call, 'replay_raw', replay)
    if response.final_url != replay:
        raise ValueError('wayback final URL mismatch or unavailable')
    if response.status != 200 or not response.complete:
        raise ValueError('wayback replay incomplete')
    _verify_digest(response.body, digest)
    return response


def acquire_candidate(candidate, call, *, seen_identities):
    """Acquire one indexed replay as raw bytes, unless already retained or attempted."""
    url = candidate['url']
    if url in seen_identities:
        return None
    source, original, timestamp = candidate['source'], candidate['original_url'], candidate['timestamp']
    if source == 'wayback':
        return acquire_wayback(url, original, timestamp, call, digest=candidate.get('digest'))
    if source != 'webharvest' or not _source_url(original) or not _timestamp(timestamp):
        raise ValueError('invalid archive candidate')
    collection = candidate.get('collection')
    if not isinstance(collection, str) or not re.fullmatch(r'congress(?:10[9]|11[0-8])th', collection):
        raise ValueError('invalid Web Harvest collection')
    if url != f'https://webharvest.gov/{collection}/{timestamp}id_/{original}':
        raise ValueError('Web Harvest replay identity mismatch')
    response = _capture(call, 'replay_raw', url)
    if response.final_url != url or response.status != 200 or not response.complete:
        raise ValueError('Web Harvest replay incomplete or redirected')
    _verify_digest(response.body, candidate.get('digest'))
    return response


def house_listing_candidate(target, candidate, *, listing_url, listing_urls, evidence, target_version, candidate_version):
    """Return a House XML/PDF sibling only when a retained listing names both."""
    if not evidence or not target_version or target_version != candidate_version:
        return None
    urls = (target, candidate, listing_url)
    if not all(_source_url(u) and urlsplit(u).hostname == 'docs.house.gov' for u in urls):
        return None
    first, second = urlsplit(target), urlsplit(candidate)
    if (first.query or second.query or first.path[:-4] != second.path[:-4]
            or {first.path[-4:].lower(), second.path[-4:].lower()} != {'.pdf', '.xml'}
            or target not in listing_urls or candidate not in listing_urls):
        return None
    return {'target_url': target, 'url': candidate, 'source': 'house_listing',
            'listing_url': listing_url, 'evidence': evidence, 'version': target_version,
            'mapping': 'house-listed-sibling-v1'}


def acquire_candidates(candidates, call, *, allowed_targets, allowed_candidate_urls, seen_identities, max_candidates, max_considered=None):
    """Fetch at most max_candidates distinct, in-scope archive leads via capture."""
    if max_candidates < 1:
        raise ValueError('invalid candidate limit')
    if max_considered is None:
        max_considered = max_candidates * 4
    if max_considered < 1:
        raise ValueError('invalid consideration limit')
    seen = set(seen_identities)
    results = []
    limited = False
    for index, candidate in enumerate(islice(candidates, max_considered + 1)):
        if index == max_considered:
            limited = True
            break
        url = candidate.get('url')
        if (candidate.get('target_url') not in allowed_targets or not isinstance(url, str)
                or url not in allowed_candidate_urls or url in seen):
            continue
        if len(results) == max_candidates:
            limited = True
            break
        # Mark before dispatch so aliases in this call never trigger another attempt.
        seen.add(url)
        response = acquire_candidate(candidate, call, seen_identities=())
        results.append({'candidate': candidate, 'response': response})
    return {'results': results, 'limited': limited}


def relocated_search(target, stems, allowed_hosts, search, seen_identities, *, max_queries, max_pages, max_candidates, max_stems=1000):
    """Search exact/partial filename stems as leads; never fetch a candidate.

    search(query, page, hosts) returns a dict with candidates, evidence, complete and
    next_page. Caller owns attempt/inventory identities and request accounting.
    """
    if not _source_url(target) or min(max_queries, max_pages, max_candidates, max_stems) < 1:
        raise ValueError('invalid target or limits')
    hosts = {h.lower() for h in allowed_hosts}
    if not hosts or any(not re.fullmatch(r'[a-z0-9.-]+', h) for h in hosts):
        raise ValueError('invalid scope')
    raw_stems = list(islice(stems, max_stems + 1))
    stems_limited = len(raw_stems) > max_stems
    queries = list(dict.fromkeys(s.strip() for s in raw_stems[:max_stems]
                                if isinstance(s, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,127}', s.strip())))
    candidates, evidence, seen = [], [], set(seen_identities)
    complete = len(queries) <= max_queries and bool(queries) and not stems_limited
    pages = 0
    reason = 'complete' if complete else 'query_limit_or_no_query'
    for query in queries[:max_queries]:
        page = None
        page_tokens = set()
        while True:
            if pages >= max_pages:
                return {'complete': False, 'reason': 'page_limit', 'candidates': candidates, 'evidence': evidence}
            result = search(query, page, tuple(sorted(hosts)))
            pages += 1
            if not result.get('evidence'):
                raise ValueError('search response lacks evidence')
            evidence.append({'query': query, 'page': page, 'ref': result['evidence']})
            if not result.get('complete'):
                complete, reason = False, 'incomplete_search'
            page_candidates = result.get('candidates', [])
            if not isinstance(page_candidates, list):
                raise ValueError('search candidates must be a bounded list')
            truncated = len(page_candidates) > max_candidates
            for url in page_candidates[:max_candidates]:
                if not _source_url(url) or urlsplit(url).hostname.lower() not in hosts or url in seen:
                    continue
                if len(candidates) >= max_candidates:
                    return {'complete': False, 'reason': 'candidate_limit', 'candidates': candidates, 'evidence': evidence}
                seen.add(url)
                candidates.append({'target_url': target, 'url': url, 'source': 'relocated_search',
                                   'stem': query, 'evidence': result['evidence']})
            if truncated:
                return {'complete': False, 'reason': 'candidate_limit', 'candidates': candidates, 'evidence': evidence}
            token = result.get('next_page')
            if not token:
                break
            if token in page_tokens:
                return {'complete': False, 'reason': 'repeated_page', 'candidates': candidates, 'evidence': evidence}
            page_tokens.add(token)
            page = token
    return {'complete': complete, 'reason': reason, 'candidates': candidates, 'evidence': evidence}


def govinfo_document_candidate(target, package_id, *, expected_package_id, evidence):
    """Map a verified CDOC package identifier; no inferred bill/version aliases."""
    if not _source_url(target) or not evidence or package_id != expected_package_id:
        return None
    if not re.fullmatch(r'CDOC-\d{1,3}(?:hdoc|sdoc|tdoc)\d+', package_id):
        return None
    return {'target_url': target, 'url': f'https://www.govinfo.gov/content/pkg/{package_id}/pdf/{package_id}.pdf',
            'source': 'govinfo', 'package_id': package_id, 'identifier_evidence': expected_package_id,
            'evidence': evidence, 'mapping': 'govinfo-cdoc-package-pdf-v1'}


def govinfo_bill_candidate(target, congress, bill_type, number, version, *, source_identity, evidence):
    """Lead for a documented bill package with an explicitly evidenced version."""
    identity = {'congress': congress, 'bill_type': bill_type, 'number': number, 'version': version}
    if not _source_url(target) or not evidence or source_identity != identity:
        return None
    if (not isinstance(congress, int) or not 103 <= congress <= 999
            or bill_type not in {'hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'}
            or not isinstance(number, int) or number < 1
            or not isinstance(version, str) or not re.fullmatch(r'[a-z]{1,12}', version)):
        return None
    package = f'BILLS-{congress}{bill_type}{number}{version}'
    return {'target_url': target, 'url': f'https://www.govinfo.gov/content/pkg/{package}/pdf/{package}.pdf',
            'source': 'govinfo', 'package_id': package, 'identity': identity,
            'evidence': evidence, 'mapping': 'govinfo-bills-package-pdf-v1'}


def main():
    """Run a local JSON fixture without network access."""
    import argparse
    import base64
    import json
    from corpus_recovery.cdx import key, parse_cdx

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('fixture', help='JSON file with original, collection, pages, and max_pages')
    args = parser.parse_args()
    with open(args.fixture, encoding='utf-8') as stream:
        fixture = json.load(stream)
    pages = iter(fixture['pages'])
    def call(kind, url):
        page = next(pages) if kind == 'cdx' else fixture['replays'][url]
        return Response(status=page['status'], body=base64.b64decode(page['body_base64'], validate=True),
                        complete=page['complete'], evidence=page['evidence'],
                        content_type=page.get('content_type', 'text/plain'), final_url=page.get('final_url', url))
    if fixture.get('source', 'webharvest') == 'wayback':
        result = wayback_lookup(fixture['original'], call, max_pages=fixture['max_pages'],
                                from_timestamp=fixture.get('from'), to_timestamp=fixture.get('to'))
    else:
        result = webharvest_lookup(fixture['original'], fixture['collection'], call,
                                   parse_cdx=parse_cdx, url_key=key, max_pages=fixture['max_pages'])
    if 'max_candidates' in fixture:
        acquired = acquire_candidates(result['candidates'], call, allowed_targets={fixture['original']},
                                      allowed_candidate_urls={c['url'] for c in result['candidates']},
                                      seen_identities=set(fixture.get('seen_identities', [])),
                                      max_candidates=fixture['max_candidates'])
        result['acquired'] = [{'candidate': item['candidate'], 'evidence': item['response'].evidence,
                               'body_base64': base64.b64encode(item['response'].body).decode('ascii')}
                              for item in acquired['results']]
        result['candidate_limit_reached'] = acquired['limited']
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
