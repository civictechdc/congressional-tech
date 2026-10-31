"""Bounded discovery leads; acquisition, custody and acceptance belong to callers.

Every call is dispatched through the injected capture function, which must reserve
and account for the request before making it and retain the referenced evidence.
"""
from dataclasses import dataclass
import re
from urllib.parse import quote, urlencode, urlsplit


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
        return p.scheme in ('http', 'https') and bool(p.hostname) and not (p.username or p.password or p.fragment)
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
        if response.status != 200 or not response.complete:
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
            if not re.fullmatch(r'\d{14}', row['timestamp']) or not _source_url(row['url']):
                reason = 'invalid_index_response'
                return {'complete': False, 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}
            replay = f"https://webharvest.gov/{collection}/{row['timestamp']}id_/{row['url']}"
            ident = (row['timestamp'], row['url'], row['digest'])
            candidates[ident] = {'target_url': original, 'url': replay, 'original_url': row['url'],
                                 'timestamp': row['timestamp'], 'digest': row['digest'],
                                 'source': 'webharvest', 'evidence': response.evidence}
        if not next_resume:
            reason = 'complete'
            break
        if next_resume in seen:
            reason = 'repeated_resume_key'
            break
        seen.add(next_resume)
        resume = next_resume
    return {'complete': reason == 'complete', 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}


def validate_wayback_replay(replay, original, timestamp):
    """Require an exact identity replay and exact literal original URL."""
    if not _source_url(original) or not re.fullmatch(r'\d{14}', timestamp):
        return False
    try:
        p = urlsplit(replay)
        return (p.scheme == 'https' and p.netloc == 'web.archive.org' and not p.fragment
                and replay == f'https://web.archive.org/web/{timestamp}id_/{original}')
    except ValueError:
        return False


def acquire_wayback(replay, original, timestamp, call):
    if not validate_wayback_replay(replay, original, timestamp):
        raise ValueError('wayback replay identity mismatch')
    response = _capture(call, 'replay_raw', replay)
    if response.final_url != replay:
        raise ValueError('wayback final URL mismatch or unavailable')
    return response


def relocated_search(target, stems, allowed_hosts, search, seen_identities, *, max_queries, max_pages, max_candidates):
    """Search exact/partial filename stems as leads; never fetch a candidate.

    search(query, page) returns a dict with candidates, evidence, complete and
    next_page. Caller owns attempt/inventory identities and request accounting.
    """
    if not _source_url(target) or min(max_queries, max_pages, max_candidates) < 1:
        raise ValueError('invalid target or limits')
    hosts = {h.lower() for h in allowed_hosts}
    if not hosts or any(not re.fullmatch(r'[a-z0-9.-]+', h) for h in hosts):
        raise ValueError('invalid scope')
    queries = list(dict.fromkeys(s.strip() for s in stems if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,127}', s.strip())))
    candidates, evidence, seen = [], [], set(seen_identities)
    complete = len(queries) <= max_queries and bool(queries)
    pages = 0
    reason = 'complete' if complete else 'query_limit_or_no_query'
    for query in queries[:max_queries]:
        page = None
        page_tokens = set()
        while True:
            if pages >= max_pages:
                return {'complete': False, 'reason': 'page_limit', 'candidates': candidates, 'evidence': evidence}
            result = search(query, page)
            pages += 1
            if not result.get('evidence'):
                raise ValueError('search response lacks evidence')
            evidence.append({'query': query, 'page': page, 'ref': result['evidence']})
            if not result.get('complete'):
                complete, reason = False, 'incomplete_search'
            for url in result.get('candidates', []):
                if not _source_url(url) or urlsplit(url).hostname.lower() not in hosts or url in seen:
                    continue
                if len(candidates) >= max_candidates:
                    return {'complete': False, 'reason': 'candidate_limit', 'candidates': candidates, 'evidence': evidence}
                seen.add(url)
                candidates.append({'target_url': target, 'url': url, 'source': 'relocated_search',
                                   'stem': query, 'evidence': result['evidence']})
            token = result.get('next_page')
            if not token:
                break
            if token in page_tokens:
                return {'complete': False, 'reason': 'repeated_page', 'candidates': candidates, 'evidence': evidence}
            page_tokens.add(token)
            page = token
    return {'complete': complete, 'reason': reason, 'candidates': candidates, 'evidence': evidence}


def govinfo_document_candidate(target, package_id, *, expected_package_id):
    """Map a verified CDOC package identifier; no inferred bill/version aliases."""
    if not _source_url(target) or package_id != expected_package_id:
        return None
    if not re.fullmatch(r'CDOC-\d{1,3}(?:hdoc|sdoc|tdoc)\d+', package_id):
        return None
    return {'target_url': target, 'url': f'https://www.govinfo.gov/content/pkg/{package_id}/pdf/{package_id}.pdf',
            'source': 'govinfo', 'package_id': package_id, 'identifier_evidence': expected_package_id,
            'mapping': 'govinfo-cdoc-package-pdf-v1'}


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
    from webharvest_cdx import key, parse_cdx

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('fixture', help='JSON file with original, collection, pages, and max_pages')
    args = parser.parse_args()
    with open(args.fixture, encoding='utf-8') as stream:
        fixture = json.load(stream)
    pages = iter(fixture['pages'])
    def call(kind, url):
        page = next(pages)
        return Response(status=page['status'], body=base64.b64decode(page['body_base64'], validate=True),
                        complete=page['complete'], evidence=page['evidence'],
                        content_type=page.get('content_type', 'text/plain'))
    print(json.dumps(webharvest_lookup(fixture['original'], fixture['collection'], call,
                                      parse_cdx=parse_cdx, url_key=key,
                                      max_pages=fixture['max_pages']), indent=2))


if __name__ == '__main__':
    main()
