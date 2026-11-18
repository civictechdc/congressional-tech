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
from urllib.parse import quote, unquote, urlencode, urlsplit


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


_WEBHARVEST_COLLECTION = re.compile(r'congress(?:109|11[0-8])th')


def webharvest_collections(year):
    """Harvests that close the Congress sitting in `year` and the next one.

    A harvest is taken as a Congress ends, so a document can sit in either. Years
    are coarse: a document from 1-2 January of an odd year belongs to the previous
    Congress. Only the maintained collections (109th to 118th) are returned.
    """
    if type(year) is not int:
        raise ValueError('invalid year')
    congress = (year - 1789) // 2 + 1
    return [name for name in (f'congress{congress}th', f'congress{congress + 1}th') if _WEBHARVEST_COLLECTION.fullmatch(name)]


def _publisher_site(host):
    """House and Senate subdomains are separate publishers; elsewhere the last two labels."""
    host = host.lower()
    labels = host.removeprefix('www.').split('.')
    return '.'.join(labels[-3:] if host.endswith(('.house.gov', '.senate.gov')) else labels[-2:])


def _base_name(url):
    return unquote(urlsplit(url).path.rsplit('/', 1)[-1]).lower()


def _check_webharvest(original, collection, max_pages, page_size):
    if not _source_url(original) or not _WEBHARVEST_COLLECTION.fullmatch(collection):
        raise ValueError('invalid target or collection')
    if max_pages < 1 or not 1 <= page_size <= 50000:
        raise ValueError('invalid page limit')


def _webharvest_pages(original, collection, call, query, *, parse_cdx, url_key, max_pages, page_size, row_ok, keep, source, **extra):
    """Page one checked Web Harvest CDX query; a row failing row_ok voids its page, keep selects leads."""
    seen, candidates, evidence = set(), {}, []
    resume = None
    reason = 'page_limit'
    for _ in range(max_pages):
        params = [*query, ('limit', str(page_size)), ('showResumeKey', 'true')]
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
            if any(r['status'] != '200' or url_key(r['url']) != r['urlkey'] or not row_ok(r) for r in rows):
                raise ValueError('index filter mismatch')
        except (ValueError, UnicodeError, KeyError):
            reason = 'invalid_index_response'
            break
        for row in rows:
            if not _timestamp(row['timestamp']) or not _source_url(row['url']):
                reason = 'invalid_index_response'
                return {'complete': False, 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}
            if not keep(row):
                continue
            replay = f"https://webharvest.gov/{collection}/{row['timestamp']}id_/{row['url']}"
            ident = (row['timestamp'], row['url'], row['digest'])
            candidates[ident] = {'target_url': original, 'url': replay, 'original_url': row['url'],
                                 'timestamp': row['timestamp'], 'digest': row['digest'],
                                 'source': source, 'collection': collection, 'evidence': response.evidence, **extra}
        if not next_resume:
            reason = 'complete'
            break
        if next_resume in seen:
            reason = 'repeated_resume_key'
            break
        seen.add(next_resume)
        resume = next_resume
    return {'complete': reason == 'complete', 'reason': reason, 'candidates': list(candidates.values()), 'evidence': evidence}


def webharvest_lookup(original, collection, call, *, parse_cdx, url_key, max_pages, page_size=1000):
    """Query a single exact URL, retaining each page's capture evidence.

    parse_cdx and url_key are the maintained Web Harvest helpers. The injected
    call must enforce response-byte limits in addition to these page limits.
    """
    _check_webharvest(original, collection, max_pages, page_size)
    expected = url_key(original)
    if expected is None:
        raise ValueError('invalid target key')
    return _webharvest_pages(original, collection, call, [('url', original), ('matchType', 'exact'), ('filter', 'statuscode:200')],
                             parse_cdx=parse_cdx, url_key=url_key, max_pages=max_pages, page_size=page_size,
                             row_ok=lambda r: r['urlkey'] == expected, keep=lambda r: True, source='webharvest')


def campaign_lookup(original, collection, capture, *, max_pages, page_size=1000):
    from corpus_recovery.cdx import key, parse_cdx
    return webharvest_lookup(original, collection, capture, parse_cdx=parse_cdx,
                             url_key=key, max_pages=max_pages, page_size=page_size)


def webharvest_name_lookup(original, collection, call, *, damaged_digest, max_pages, page_size=20,
                           media_type='application/pdf'):
    """Find the target's exact file name anywhere on its publisher site in one harvest.

    Run it when the exact-address lookup in this collection yields no capture, or
    only captures whose digest equals damaged_digest (the damaged body's base32
    SHA-1, as CDX records it). A lead must have the same base name (case-insensitive),
    the given media type and a different digest. The match is by name only: the
    same name can be a different document, renamed copies are missed, and a file
    published between two harvests holds only what the next harvest saw.
    """
    from corpus_recovery.cdx import key, parse_cdx
    _check_webharvest(original, collection, max_pages, page_size)
    if not isinstance(damaged_digest, str) or not re.fullmatch(r'[A-Z2-7]{32}', damaged_digest):
        raise ValueError('invalid damaged digest')
    target_key, name = key(original), _base_name(original)
    if target_key is None or not name:
        raise ValueError('invalid target key or name')
    site = _publisher_site(urlsplit(original).hostname)
    stem = name.rsplit('.', 1)[0] if '.' in name else name
    query = [('url', site), ('matchType', 'domain'), ('filter', 'urlkey:.*' + re.escape(quote(stem, safe='')) + '.*'),
             ('filter', 'statuscode:200')]
    def in_query(row):
        host = (urlsplit(row['url']).hostname or '').lower()
        return stem in unquote(row['urlkey']) and (host == site or host.endswith('.' + site))
    def same_name_other_copy(row):
        return (_base_name(row['url']) == name and row['mime'] == media_type and row['urlkey'] != target_key
                and re.fullmatch(r'[A-Z2-7]{32}', row['digest']) is not None and row['digest'] != damaged_digest)
    return _webharvest_pages(original, collection, call, query, parse_cdx=parse_cdx, url_key=key,
                             max_pages=max_pages, page_size=page_size, row_ok=in_query, keep=same_name_other_copy,
                             source='webharvest_name', mapping='same-site-file-name-harvest-v1')


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
    """Find SURT-matched captures with exact archived replay identity; a negative covers only this query window."""
    from corpus_recovery.cdx import key
    if not _source_url(original) or max_pages < 1 or not 1 <= page_size <= 50000:
        raise ValueError('invalid target or limits')
    expected = key(original)
    if expected is None:
        raise ValueError('invalid target key')
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
                if (not _source_url(row['original'])
                        or row['urlkey'] != expected
                        or key(row['original']) != expected
                        or row['statuscode'] != '200'
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


def validate_webharvest_replay(candidate):
    """Require the exact harvest replay of the candidate's recorded harvested address.

    A name match (`webharvest_name`) must also keep the target's publisher site and
    base name; an address match was tied to its target by the exact lookup.
    """
    source, original, timestamp = candidate.get('source'), candidate.get('original_url'), candidate.get('timestamp')
    if source not in ('webharvest', 'webharvest_name') or not _source_url(original) or not _timestamp(timestamp):
        raise ValueError('invalid archive candidate')
    collection = candidate.get('collection')
    if not isinstance(collection, str) or not _WEBHARVEST_COLLECTION.fullmatch(collection):
        raise ValueError('invalid Web Harvest collection')
    if candidate.get('url') != f'https://webharvest.gov/{collection}/{timestamp}id_/{original}':
        raise ValueError('Web Harvest replay identity mismatch')
    target = candidate.get('target_url')
    if source == 'webharvest_name' and (
            not _source_url(target) or _base_name(original) != _base_name(target)
            or _publisher_site(urlsplit(original).hostname) != _publisher_site(urlsplit(target).hostname)):
        raise ValueError('Web Harvest name match identity mismatch')


def shared_prefix(damaged, candidate):
    """Count the leading bytes a damaged body shares with a candidate body (any bytes-like, mmap included).

    Identity evidence, not a rule. The hypothesis that a cut-off file equals the
    intact file up to the cut is not yet verified on real bytes, so no threshold
    accepts or rejects a candidate until the first real fetches set one; unrelated
    PDFs already share their header line. Qualification stays required.
    """
    left, right = memoryview(damaged), memoryview(candidate)
    limit, same, chunk = min(len(left), len(right)), 0, 1 << 16
    while same < limit:
        step = min(chunk, limit - same)
        if left[same:same + step] != right[same:same + step]:
            same += next(i for i in range(step) if left[same + i] != right[same + i])
            break
        same += step
    return {'shared_prefix_bytes': same, 'damaged_bytes': len(left), 'candidate_bytes': len(right)}


def acquire_candidate(candidate, call, *, seen_identities):
    """Acquire one indexed replay as raw bytes, unless already retained or attempted."""
    url = candidate['url']
    if url in seen_identities:
        return None
    if candidate['source'] == 'wayback':
        return acquire_wayback(url, candidate['original_url'], candidate['timestamp'], call, digest=candidate.get('digest'))
    validate_webharvest_replay(candidate)
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


def acquire_candidates(candidates, call, *, allowed_targets, allowed_candidate_urls, seen_identities, max_candidates, max_considered=None,
                       damaged_body=None):
    """Fetch at most max_candidates distinct, in-scope archive leads via capture.

    With damaged_body, each result also records shared_prefix(damaged_body, body).
    """
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
        result = {'candidate': candidate, 'response': response}
        if damaged_body is not None:
            result['shared_prefix'] = shared_prefix(damaged_body, response.body)
        results.append(result)
    return {'results': results, 'limited': limited}


# One re-upload migration put larger copies one month later (ct-z4w5); six months
# either side bounds one target to twelve candidate requests.
MAX_NEIGHBOR_MONTHS = 6
_UPLOAD_MONTH_PATH = re.compile(
    r'(?P<root>(?:/[^/]+)*/wp-content/uploads)/(?P<year>(?:19|20)\d\d)/(?P<month>0[1-9]|1[0-2])/(?P<name>[^/]+)')


def neighbor_folder_candidates(target, *, months=1):
    """Propose the same file name in adjacent upload-month folders on the same host.

    Only a `/wp-content/uploads/YYYY/MM/<file>` target qualifies, and no request
    is made. The claim is only "same host, same file name" (`mapping`). A caller
    must acquire the lead through the campaign candidate table, qualify it (every
    page renders) and accept identity from source-native records. Bytes identical
    to a damaged target reuse its failed qualification by digest, so they never
    pass. Renamed copies, other folder layouts and other hosts are out of reach.
    """
    if type(months) is not int or not 1 <= months <= MAX_NEIGHBOR_MONTHS:
        raise ValueError('invalid neighbor month bound')
    if not _source_url(target):
        return []
    parts = urlsplit(target)
    found = _UPLOAD_MONTH_PATH.fullmatch(parts.path)
    if parts.query or not found:
        return []
    base = int(found['year']) * 12 + int(found['month']) - 1
    candidates = []
    for offset in (sign * step for step in range(1, months + 1) for sign in (1, -1)):
        year, month = divmod(base + offset, 12)
        url = f"{parts.scheme}://{parts.netloc}{found['root']}/{year:04d}/{month + 1:02d}/{found['name']}"
        candidates.append({'target_url': target, 'url': url, 'source': 'neighbor_folder',
                           'mapping': 'same-host-file-name-adjacent-upload-month-v1'})
    return candidates


# Query kind -> (accepted shape, candidate source). The kind also names the
# candidate field that records the query.
_SEARCH_KINDS = {
    'stem': (r'[A-Za-z0-9][A-Za-z0-9._-]{2,127}', 'relocated_search'),
    'phrase': (r"[^\W_][\w .,:;'&()/-]{2,255}", 'descriptive_search'),
}


def relocated_search(target, stems, allowed_hosts, search, seen_identities, *, max_queries, max_pages, max_candidates, max_stems=1000, kind='stem'):
    """Search file-name stems, or descriptive phrases with kind='phrase', as leads; never fetch a candidate.

    search(query, page, hosts) returns a dict with candidates, evidence, complete and
    next_page. Caller owns attempt/inventory identities and request accounting.
    Only results on allowed_hosts become candidates, whatever the index returns.
    """
    if not _source_url(target) or min(max_queries, max_pages, max_candidates, max_stems) < 1:
        raise ValueError('invalid target or limits')
    if kind not in _SEARCH_KINDS:
        raise ValueError('invalid search kind')
    shape, source = _SEARCH_KINDS[kind]
    hosts = {h.lower() for h in allowed_hosts}
    if not hosts or any(not re.fullmatch(r'[a-z0-9.-]+', h) for h in hosts):
        raise ValueError('invalid scope')
    raw_stems = list(islice(stems, max_stems + 1))
    stems_limited = len(raw_stems) > max_stems
    # Collapsing whitespace leaves stems as stripped: their shape admits no space.
    queries = list(dict.fromkeys(q for q in (' '.join(s.split()) for s in raw_stems[:max_stems] if isinstance(s, str))
                                 if re.fullmatch(shape, q)))
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
                candidates.append({'target_url': target, 'url': url, 'source': source,
                                   kind: query, 'evidence': result['evidence']})
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
