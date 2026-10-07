"""Collect all discoverable House committee events, independently of API gaps.

One resumable queue per official site follows literal listing pages, sitemap
entries, archive filters and supported calendar APIs. A run budget pauses the
queue; it never declares unvisited pages complete. Source bytes, failed checks
and unmatched event pages remain available for the XML fallback and raw mirror.
"""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date
import hashlib
import json
import re
from threading import Event
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from congress_api.acquisition.refresh import due
from congress_api.acquisition.house import request, timestamp
from congress_api.parsers.committee_discovery import discover, key, task, comparison_key, listing_records, page_link_exclusion, pagination_field, UnrecognizedSitemap
from congress_api.parsers.committee_pages import event_identity, parse_event_page, same_site, listing_url
from congress_api.models.content import content_bytes
from congress_api.retention.committees import read as read_committees
from congress_api.retention.tables import read_state, write_state, write_csv
from congress_api.transport.http import HttpRequestError, RequestPacer

PARSER_VERSION = 5
PAGINATION_VERSION = 4
EVENT_FIELDS = 'site page title date type status'.split()
DOCUMENT_FIELDS = 'site page date kind name url'.split()
COVERAGE_FIELDS = 'site history events pending failed unavailable unrecognized_events discovery_gaps status'.split()
OPTIONAL_INDEXES = {'robots', 'sitemap', 'wordpress_types', 'calendar_index_hint'}


def directory(rows):
    """One site per official URL, with every retained committee association."""
    from congress_api.acquisition.house_fallback import committee_websites
    result = {}
    for (congress, code), urls in committee_websites(rows).items():
        for url in sorted(urls):
            host = (urlsplit(url).hostname or '').removeprefix('www.')
            entry = result.setdefault(host, dict(home=url, committees=[]))
            entry['committees'].append(dict(congress=congress, code=code))
    return result


def seeds(home):
    return [task(home, 'home'), task(urljoin(home, '/robots.txt'), 'robots'),
            task(urljoin(home, '/sitemap.xml'), 'sitemap')]


def _enqueue(saved, queue, queued, item, *, today, refresh, force=False):
    url = item['url']
    if item['kind'] == 'site_home' and (urlsplit(url).hostname or '').endswith('.house.gov'):
        saved.setdefault('linked_sites', {}).setdefault(url, item.get('discovered_from'))
    if not any(same_site(url, home) for home in [saved['home'], *saved.get('linked_sites', {})]) or _exclude(saved, item):
        return
    identifier = key(item)
    if identifier in saved['done'] or identifier in queued:
        return
    previous = saved['pages'].get(url)
    if previous and not force:
        day = (previous.get('event') or {}).get('date') or previous.get('checked')
        if refresh[0] <= 0 or (previous.get('parser_version') == PARSER_VERSION and not due(previous, day, '', today)):
            return
        refresh[0] -= 1
    queued.add(identifier)
    queue.append(item)


def _fetch(item, get):
    """Workers own only their response and receipts, never collection state."""
    receipts = []
    try:
        response = get(item['url'], receipts, **({'json_body': item['body']} if 'body' in item else {}))
        return response, receipts, None
    except (RuntimeError, ValueError, OSError) as error:
        return None, receipts, error


def _read(saved, item, fetched, *, today):
    # Retrying an observation appends its new request receipt; the failed
    # attempts remain evidence rather than disappearing on the next success.
    response, new_receipts, error = fetched
    receipts = [*saved['sources'].get(key(item), {}).get('receipts', []), *new_receipts]
    observation = dict(url=item['url'], kind=item['kind'], receipts=receipts)
    saved['sources'][key(item)] = observation
    if new_receipts and (body := receipts[-1].pop('content', None)):
        observation['content'] = body
        receipts[-1]['sha256'] = body['sha256']
    if error is not None:
        if isinstance(error, HttpRequestError) and item['kind'] in OPTIONAL_INDEXES and error.status in {401, 403, 404, 410}:
            observation.update(status=error.status, discovery_gap='index_not_available')
            return []
        raise error
    observation['final_url'] = getattr(response, 'url', None) or item['url']
    final = observation['final_url']
    if not any(same_site(final, home) for home in [saved['home'], *saved.get('linked_sites', {})]):
        if item['kind'] in {'home', 'site_home'} and (urlsplit(final).hostname or '').endswith('.house.gov'):
            saved.setdefault('linked_sites', {})[final] = item['url']
        else:
            raise ValueError('Official committee request redirected to another site')
    observation.update(status=response.status_code, kind=item['kind'])
    if response.status_code == 404:
        # A literal dead link is a recorded unavailability, not a transient
        # transport failure. Coverage reports it separately from parsed pages.
        return []
    if len(response.content) > 16 * 1024**2:
        raise ValueError('Committee listing exceeds the 16 MiB parser budget')
    body = response.content
    try:
        links = discover(body, {**item, 'url': observation['final_url']}, headers=getattr(response, 'headers', {}))
    except UnrecognizedSitemap as error:
        observation['discovery_error'] = str(error)
        if re.search(br'<html(?:\s|>)', body[:4096], re.I):
            observation['discovery_gap'] = 'sitemap_returned_html'
            links = discover(body, task(final))
        else:
            observation['discovery_gap'] = 'sitemap_unrecognized'
            links = []
    if item['kind'] == 'site_home' or item['kind'] == 'home' and not same_site(final, item['url']):
        links += seeds(final)[1:]
    identity = event_identity(body, observation['final_url']) if item['kind'] not in {'home', 'site_home', 'robots', 'sitemap', 'calendar_api', 'wordpress_types', 'wordpress_posts'} else None
    if not listing_url(final) and (item['kind'] == 'event' or identity):
        page = parse_event_page(body, observation['final_url'])
        page.update(checked=today.isoformat(), version='', parser_version=PARSER_VERSION)
        if receipts:
            page['retrieved_at'] = receipts[-1].get('completed_at')
        # The successful page owns its exact body; discovery references it.
        observation.pop('content', None)
        observation['page_url'] = final
        saved['pages'][final] = page
    _check_pagination(saved, item, links, source_body=body)
    return links


def _check_pagination(saved, item, links, *, source_body=None):
    """Stop servers that ignore a page/offset instead of walking forever."""
    parsed = urlsplit(item['url'])
    query = parse_qsl(parsed.query, keep_blank_values=True)
    pages = {k for k, _ in query if pagination_field(k)}
    body = item.get('body', {})
    if not pages and 'offset' not in body and '/page/' not in parsed.path:
        return
    records = listing_records(source_body, item['url']) if source_body is not None and item['kind'] not in {'calendar_api', 'wordpress_posts'} else None
    # For other layouts include discovered detail pages, not just event URLs.
    # Different bill pages can legitimately refer to the same markup hearing.
    if records is None:
        records = sorted({comparison_key(link) for link in links if link['kind'] == 'event'
                          or link['kind'] == 'html' and not listing_url(link['url'])
                          and urlsplit(link['url']).path != parsed.path})
    if not records:
        return
    series = comparison_key({**item, 'url': parsed._replace(path=re.sub(r'/page/\d+(?=/|$)', '/page/', parsed.path),
                 query=urlencode([(k, v) for k, v in query if k not in pages])).geturl(),
                 **({'body': {k: v for k, v in body.items() if k != 'offset'}} if body else {})})
    digest = hashlib.sha256(json.dumps(records).encode()).hexdigest()
    if saved.get('pagination_version') != PAGINATION_VERSION:
        saved['pagination'] = {}
        saved['pagination_version'] = PAGINATION_VERSION
    previous = saved.setdefault('pagination', {}).setdefault(series, {})
    current = comparison_key(item)
    if digest in previous and previous[digest] != current:
        raise ValueError('Listing repeated the same records at a different page or offset')
    previous[digest] = current


def resolve_error(saved, identifier, resolution):
    """Clear a current failure while retaining the original diagnostic."""
    if previous := saved['errors'].pop(identifier, None):
        saved.setdefault('resolved_errors', {}).setdefault(identifier, []).append(
            dict(failure=previous, resolved_at=timestamp(), resolution=resolution))


def _exclude(saved, item):
    # Apply the same rules to new links and requests saved by older versions.
    # These records describe admission decisions, never completed downloads.
    reason = None if item['kind'] in {'robots', 'sitemap'} else page_link_exclusion(item['url'])
    if not reason:
        return False
    identifier = key(item)
    saved['done'][identifier] = dict(item, outcome='excluded_' + reason)
    if identifier in saved.get('errors', {}):
        resolve_error(saved, identifier, 'excluded_' + reason)
    return True


def collect(rows, state, *, today, get, limit=None, refresh_limit=450, sites=None,
            checkpoint=lambda _: None, workers=8, stop=None):
    """Fetch across sites; one coordinator owns parsing, queues and checkpoints."""
    if not 1 <= workers <= 32:
        raise ValueError('workers must be between 1 and 32')
    stop = stop if stop is not None else Event()
    owners = directory(rows)
    if not owners:
        raise ValueError('The retained committee directory contains no House websites')
    if sites and set(sites) - set(owners):
        raise ValueError('Requested site is absent from the retained official committee directory')
    selected = sorted(host for host in owners if not sites or host in sites)
    queues, queued = {}, {}
    refresh = [refresh_limit]
    for host in selected:
        saved = state.setdefault(host, dict(pages={}, sources={}, done={}, pending=[], errors={}))
        saved.update(owners[host])
        queue = deque(saved['pending'])
        queued[host] = {key(item) for item in queue}
        queues[host] = queue
        if not queue:
            last = saved.get('discovery_checked')
            if last and (today - date.fromisoformat(last)).days < 7 and not saved['errors'] and saved.get('parser_version') == PARSER_VERSION:
                continue
            saved['done'] = {}
            saved['pagination'] = {}
            # Retry failed current listing/page observations on the next run;
            # the HTTP client still owns retries within each request.
            for error in list(saved['errors'].values()):
                _enqueue(saved, queue, queued[host], error['request'], today=today, refresh=refresh, force=True)
            for item in seeds(saved['home']):
                _enqueue(saved, queue, queued[host], item, today=today, refresh=refresh)
    attempted = completed = 0
    def save():
        for host in selected:
            saved = state[host]
            saved['pending'] = list(queues[host])
            saved['coverage'] = dict(pending=len(saved['pending']), failed=len(saved['errors']), events=len(saved['pages']),
                unrecognized_events=sum(not p.get('event') for p in saved['pages'].values()),
                discovery_gaps=sum(bool(o.get('discovery_gap')) for o in saved['sources'].values()),
                unavailable=sum(o.get('status') == 404 and o.get('kind') not in OPTIONAL_INDEXES for o in saved['sources'].values()),
                history='all discoverable', status='pending' if saved['pending'] else 'failed' if saved['errors'] else
                'no_recognized_events' if not saved['pages'] else
                'queue_exhausted_with_gaps' if any(o.get('discovery_gap') for o in saved['sources'].values()) else 'discovered_queue_exhausted')
        checkpoint(state)
    schedule, active, busy = deque(selected), {}, set()
    failure = None
    with ThreadPoolExecutor(min(workers, len(selected))) as pool:
        while True:
            for _ in range(len(schedule)):
                if failure or stop.is_set() or len(active) >= workers or (limit is not None and attempted >= limit):
                    break
                host = schedule.popleft()
                schedule.append(host)
                if host in busy:
                    continue
                saved, queue = state[host], queues[host]
                while queue:
                    item = queue[0]
                    identifier = key(item)
                    _exclude(saved, item)
                    if identifier not in saved['done']:
                        break
                    queue.popleft()
                    queued[host].remove(identifier)
                if not queue:
                    continue
                # Leave admitted requests pending until their results are
                # applied. Checkpoints can therefore resume an interrupted fetch.
                active[pool.submit(_fetch, item, get)] = (host, item)
                busy.add(host)
                attempted += 1
            if not active:
                break
            ready, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in ready:
                host, item = active.pop(future)
                busy.remove(host)
                saved, identifier = state[host], key(item)
                try:
                    fetched = future.result()
                    try:
                        links = _read(saved, item, fetched, today=today)
                        resolve_error(saved, identifier, 'successful_request')
                        for linked in links:
                            _enqueue(saved, queues[host], queued[host], linked, today=today, refresh=refresh)
                    except (RuntimeError, ValueError, OSError) as error:
                        saved['errors'][identifier] = dict(request=item, checked_at=timestamp(), error=str(error))
                except BaseException as error:
                    # An unexpected bug stops admission, but other admitted
                    # responses still drain into the final checkpoint.
                    failure = failure or error
                    continue
                queues[host].popleft()
                queued[host].remove(identifier)
                if final := saved['sources'].get(identifier, {}).get('page_url'):
                    saved['done'][key(task(final))] = dict(url=final, kind='event')
                saved['done'][identifier] = dict(url=item['url'], kind=item['kind'])
                completed += 1
                if not queues[host]:
                    saved['discovery_checked'] = today.isoformat()
                    saved['parser_version'] = PARSER_VERSION
                if completed % 25 == 0:
                    save()
    save()
    if failure:
        raise failure
    return dict(requests=attempted, sites=len(selected), pending=sum(len(q) for q in queues.values()),
                failed=sum(len(state[h]['errors']) for h in selected), events=sum(len(state[h]['pages']) for h in selected),
                discovery_gaps=sum(state[h]['coverage']['discovery_gaps'] for h in selected), stopped=stop.is_set())


def reparse_pages(state):
    """Correct saved readings from exact originals, with no new HTTP receipts.

    A wrongly admitted listing moves back to discovery sources. Its original
    bytes and request observations remain intact; queues and timestamps do not
    change. This explicit operation is safe only while the collector is stopped.
    """
    updated = listings = 0
    for saved in state.values():
        for url, previous in list(saved.get('pages', {}).items()):
            page = parse_event_page(content_bytes(previous['raw_html']), url)
            if page['page_kind'] == 'listing':
                observations = [o for o in saved.get('sources', {}).values() if o.get('page_url') == url]
                if not observations:
                    observation = saved.setdefault('sources', {}).setdefault(key(task(url)), dict(url=url, kind='html'))
                    observations = [observation]
                for observation in observations:
                    if observation.get('content') and observation['content'] != previous['raw_html']:
                        raise ValueError('Listing source body disagrees with retained page')
                    observation['content'] = previous['raw_html']
                    observation.pop('page_url', None)
                del saved['pages'][url]
                listings += 1
                continue
            # Checked/retrieved timestamps still describe the original request.
            saved['pages'][url] = {**previous, **page, 'parser_version': PARSER_VERSION}
            updated += 1
        saved.setdefault('coverage', {}).update(events=len(saved.get('pages', {})),
            unrecognized_events=sum(not p.get('event') for p in saved.get('pages', {}).values()))
    return dict(reparsed_pages=updated, restored_listings=listings)


def write_coverage(state, output_dir):
    write_csv(output_dir / 'house_site_coverage.csv',
        [dict(site=host, **{field: saved.get('coverage', {}).get(field, '') for field in COVERAGE_FIELDS[1:]})
         for host, saved in sorted(state.items())], COVERAGE_FIELDS)


def outputs(state, output_dir):
    events, documents = [], []
    for host, saved in sorted(state.items()):
        for url, page in sorted(saved.get('pages', {}).items()):
            event = page.get('event') or {}
            events.append(dict(site=host, page=url, title=page['title'], date=event.get('date'), type=event.get('type'),
                               status='observed' if event else 'unrecognized_event_date'))
            documents += [dict(site=host, page=url, date=event.get('date'), kind=kind, name=label, url=link)
                          for kind, label, link in page['documents']]
    write_coverage(state, output_dir)
    write_csv(output_dir / 'house_site_events.csv', events, EVENT_FIELDS)
    write_csv(output_dir / 'house_site_documents.csv', documents, DOCUMENT_FIELDS)


def main(committees, state_dir, output_dir, *, as_of=None, offline=False, reparse=False, site=None, limit=None, refresh_limit=450, zyte=False,
         workers=8, requests_per_second=None, stop=None):
    if limit is not None and limit < 0 or refresh_limit < 0:
        raise ValueError('Collection and refresh limits must be nonnegative')
    if reparse and not offline:
        raise ValueError('Reparsing requires --offline and a stopped collector')
    request_pacer = RequestPacer(requests_per_second) if requests_per_second is not None else None
    today = as_of or date.today()
    if not committees.exists():
        raise FileNotFoundError(committees)
    path = state_dir / 'house-sites.json.gz'
    state = read_state(path)
    rows = read_committees(committees)
    if offline:
        missing = set(site or directory(rows)) - set(state)
        if missing:
            raise ValueError('No saved committee site state for: ' + ', '.join(sorted(missing)))
        result = dict(mode='offline')
        if reparse:
            result.update(reparse_pages(state))
            write_state(path, state, compresslevel=3)
    else:
        def persist(value):
            write_state(path, value, compresslevel=3)
            write_coverage(value, output_dir)
        options = {'request_pacer': request_pacer} if request_pacer is not None else {}
        result = collect(rows, state, today=today, get=lambda url, checks, **kw: request(url, zyte, checks, **options, **kw),
                         limit=limit, refresh_limit=refresh_limit, sites=site, checkpoint=persist, workers=workers, stop=stop)
    outputs(state, output_dir)
    print(json.dumps(result, sort_keys=True), flush=True)
    if not offline and result['failed'] and not result.get('stopped'):
        raise RuntimeError(f"House site collection retained {result['failed']} failed requests; see house-sites.json.gz")
    return result
