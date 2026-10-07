"""Collect all discoverable House committee events, independently of API gaps.

One resumable queue per official site follows literal listing pages, sitemap
entries, archive filters and supported calendar APIs. A run budget pauses the
queue; it never declares unvisited pages complete. Source bytes, failed checks
and unmatched event pages remain available for the XML fallback and raw mirror.
"""
from collections import deque
from datetime import date
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from congress_api.acquisition.refresh import due
from congress_api.acquisition.house import request, timestamp
from congress_api.parsers.committee_discovery import RESOURCE, discover, key, task
from congress_api.parsers.committee_pages import event_identity, parse_event_page, same_site, listing_url
from congress_api.models.content import content_bytes
from congress_api.parsers.document_links import FILE
from congress_api.retention.committees import read as read_committees
from congress_api.retention.tables import read_state, write_state, write_csv
from congress_api.transport.http import HttpRequestError

PARSER_VERSION = 2
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
        saved.setdefault('linked_sites', {})[url] = item.get('discovered_from')
    if not any(same_site(url, home) for home in [saved['home'], *saved.get('linked_sites', {})]) or (FILE.search(url) and item['kind'] not in {'sitemap', 'robots'}) or RESOURCE.search(urlsplit(url).path):
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


def _read(saved, item, *, today, get):
    receipts = []
    observation = dict(url=item['url'], kind=item['kind'], receipts=receipts)
    saved['sources'][key(item)] = observation
    try:
        response = get(item['url'], receipts, **({'json_body': item['body']} if 'body' in item else {}))
    except HttpRequestError as error:
        if item['kind'] in OPTIONAL_INDEXES and error.status in {401, 403, 404, 410}:
            observation.update(status=error.status, discovery_gap='index_not_available')
            return []
        raise
    finally:
        if receipts and (body := receipts[-1].pop('content', None)):
            observation['content'] = body
            receipts[-1]['sha256'] = body['sha256']
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
    except ValueError:
        if item['kind'] == 'sitemap' and re.search(br'<html(?:\s|>)', body[:4096], re.I):
            observation['discovery_gap'] = 'sitemap_returned_html'
            links = discover(body, task(final))
        else:
            raise
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
        saved['done'][key(task(final))] = dict(url=final, kind='event')
    _check_pagination(saved, item, links)
    return links


def _check_pagination(saved, item, links):
    """Stop servers that ignore a page/offset instead of walking forever."""
    parsed = urlsplit(item['url'])
    query = dict(parse_qsl(parsed.query))
    pages = {k: v for k, v in query.items() if k.lower() == 'page' or k.lower().startswith(('pagenum_', 'mt_page'))}
    body = item.get('body', {})
    if not pages and 'offset' not in body and '/page/' not in parsed.path:
        return
    events = sorted({link['url'] for link in links if link['kind'] == 'event'})
    if not events:
        return
    series = key({**item, 'url': parsed._replace(path=re.sub(r'/page/\d+', '/page/', parsed.path),
                 query=urlencode({k: v for k, v in query.items() if k not in pages})).geturl(),
                 **({'body': {k: v for k, v in body.items() if k != 'offset'}} if body else {})})
    digest = hashlib.sha256(json.dumps(events).encode()).hexdigest()
    previous = saved.setdefault('pagination', {}).setdefault(series, {})
    if digest in previous and previous[digest] != key(item):
        raise ValueError('Listing repeated the same events at a different page or offset')
    previous[digest] = key(item)


def collect(rows, state, *, today, get, limit=None, refresh_limit=450, sites=None, checkpoint=lambda _: None):
    """Fairly visit every site; persist pending work instead of hiding a page cap."""
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
            for error in saved['errors'].values():
                _enqueue(saved, queue, queued[host], error['request'], today=today, refresh=refresh, force=True)
            for item in seeds(saved['home']):
                _enqueue(saved, queue, queued[host], item, today=today, refresh=refresh)
    attempted = 0
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
    while any(queues.values()) and (limit is None or attempted < limit):
        for host in selected:
            if not queues[host] or (limit is not None and attempted >= limit):
                continue
            saved = state[host]
            item = queues[host].popleft()
            identifier = key(item)
            queued[host].remove(identifier)
            if identifier in saved['done']:
                continue
            if RESOURCE.search(urlsplit(item['url']).path):
                saved['done'][identifier] = dict(url=item['url'], kind=item['kind'], outcome='excluded_resource')
                continue
            attempted += 1
            # A failed request is retried on a later discovery cycle, never
            # repeatedly re-enqueued through this cycle's navigation links.
            saved['done'][identifier] = dict(url=item['url'], kind=item['kind'])
            try:
                links = _read(saved, item, today=today, get=get)
                saved['errors'].pop(identifier, None)
                for linked in links:
                    _enqueue(saved, queues[host], queued[host], linked, today=today, refresh=refresh)
            except (RuntimeError, ValueError, OSError) as error:
                saved['errors'][identifier] = dict(request=item, checked_at=timestamp(), error=str(error))
            if not queues[host]:
                saved['discovery_checked'] = today.isoformat()
                saved['parser_version'] = PARSER_VERSION
            if attempted % 25 == 0:
                save()
    save()
    return dict(requests=attempted, sites=len(selected), pending=sum(len(q) for q in queues.values()),
                failed=sum(len(state[h]['errors']) for h in selected), events=sum(len(state[h]['pages']) for h in selected),
                discovery_gaps=sum(state[h]['coverage']['discovery_gaps'] for h in selected))


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


def main(committees, state_dir, output_dir, *, as_of=None, offline=False, reparse=False, site=None, limit=None, refresh_limit=450, zyte=False):
    if limit is not None and limit < 0 or refresh_limit < 0:
        raise ValueError('Collection and refresh limits must be nonnegative')
    if reparse and not offline:
        raise ValueError('Reparsing requires --offline and a stopped collector')
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
            write_state(path, state)
    else:
        def persist(value):
            write_state(path, value)
            write_coverage(value, output_dir)
        result = collect(rows, state, today=today, get=lambda url, checks, **kw: request(url, zyte, checks, **kw),
                         limit=limit, refresh_limit=refresh_limit, sites=site, checkpoint=persist)
    outputs(state, output_dir)
    print(json.dumps(result, sort_keys=True), flush=True)
    if not offline and result['failed']:
        raise RuntimeError(f"House site collection retained {result['failed']} failed requests; see house-sites.json.gz")
    return result
