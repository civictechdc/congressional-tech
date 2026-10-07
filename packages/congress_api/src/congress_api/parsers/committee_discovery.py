"""Read event listings and pagination without running JavaScript or guessing files.

Routes describe publisher platforms. Committee ownership comes from the retained
Congress.gov directory, not another hardcoded list of House domains.
"""
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from lxml import etree, html

from congress_api.parsers.committee_pages import calendar_links, same_site, listing_url
from congress_api.parsers.document_links import FILE, http_url

EVENT = re.compile(r'hearings?|events?|calendar|meetings?|mark[ -]?ups?|briefings?|listening.session|roundtables?|committee-activity|schedule|archiv', re.I)
RESOURCE = re.compile(r'\.(?:css|js|map|png|jpe?g|gif|svg|ico|woff2?|webp)$', re.I)
NEWS = re.compile(r'/(?:news|press|press-releases?|releases?|media/videos|media/press)', re.I)


def task(url, kind='html', *, body=None, parent=None):
    return dict(url=url, kind=kind, **({'body': body} if body is not None else {}), **({'discovered_from': parent} if parent else {}))


def key(request):
    return json.dumps([request['url'], request.get('body')], separators=(',', ':'), sort_keys=True)


def query_url(url, **values):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in values.items()})
    return urlunsplit(parts._replace(query=urlencode(query), fragment=''))


def event_url(url):
    """Recognized event-detail routes, separate from listing pagination."""
    parts = urlsplit(url)
    if listing_url(url):
        return False
    path = parts.path.rstrip('/')
    if NEWS.search(path) or '/wp-json/' in path:
        return False
    if {k.lower() for k, v in parse_qsl(parts.query) if v} & {'eventid', 'contentrecord_id', 'id'} and EVENT.search(path):
        return True
    if re.search(r'/(?:event|events|hearing|hearings|meeting|meetings|markups?|briefings?|business-meetings|public-events|film-screenings)/[^/]+$', path, re.I):
        return not re.search(r'/(?:all|page|month|day|today|list|calendar|feed|upcoming|past|archive|hearings|briefings|meetings|markups|film-screenings|public-events|\d{4})$', path, re.I)
    return bool(re.search(r'/media/announcement/(?:.*meeting|.*hearing)', path, re.I))


def _html_tasks(body, url):
    try:
        root = html.fromstring(body, parser=html.HTMLParser(no_network=True))
    except (etree.ParserError, ValueError):
        return []
    out = []
    listing = (EVENT.search(urlsplit(url).path) or urlsplit(url).path == '/media/announcements') and not event_url(url)
    for node in root.xpath('//a[@href] | //link[@href][@rel="next" or @rel="prev"]'):
        href = node.get('href', '')
        target = http_url(href, url)
        label = ' '.join(node.text_content().split())
        if target and not same_site(target, url) and (urlsplit(target).hostname or '').endswith('.house.gov') and re.fullmatch(r'(?:archived?|minority)(?: site| website)?', label, re.I):
            out.append(task(target, 'site_home', parent=url))
        if not target or not same_site(target, url) or FILE.search(target) or RESOURCE.search(urlsplit(target).path) or href.startswith('#') or '/wp-json/' in urlsplit(target).path:
            continue
        path = urlsplit(target).path
        # WordPress month calendars have unbounded previous/next months. Their
        # event archives, REST indexes and sitemaps enumerate actual entries.
        if re.search(r'/(?:month|day|today)(?:/|$)|/feed/?$|[?&](?:eventDate|tribe-bar-date)=', target):
            continue
        if NEWS.search(path) and not path.startswith('/media/announcement/'):
            continue
        pagination = listing and (re.search(r'[?&](?:page|pagenum_\w+|mt_page)=|/page/\d+', target, re.I)
                                  or node.get('rel') in {'next', 'prev'})
        if EVENT.search(path) or pagination or (listing and EVENT.search(label)) or path == '/media/announcements':
            out.append(task(target, 'event' if event_url(target) else 'html', parent=url))
    # Follow explicitly offered archive-year/Congress choices in GET filters.
    # Never submit search boxes, email forms, or POST form actions.
    if listing:
        for form in root.xpath('//form'):
            if form.get('method', 'get').lower() != 'get':
                continue
            selects = form.xpath('.//select[@name="Year" or @name="Congress" or @name="year" or @name="congress"]')
            for select in selects:
                destination = http_url(form.get('action') or url, url)
                if not destination or not same_site(destination, url):
                    continue
                defaults = {node.get('name'): node.get('value', '') for node in form.xpath('.//input[@type="hidden"][@name]')}
                for option in select.xpath('.//option[@value]'):
                    if re.fullmatch(r'\d{2,4}', option.get('value', '')):
                        out.append(task(query_url(destination, **defaults, **{select.get('name'): option.get('value')}), parent=url))
    return out


def discover(body, request, *, headers=None):
    """Next listing requests and event pages, with pagination kept explicit."""
    url, kind = request['url'], request['kind']
    if kind == 'robots':
        return [task(value, 'sitemap', parent=url) for value in re.findall(r'(?im)^sitemap:\s*(\S+)', body.decode('utf-8', 'replace'))
                if http_url(value) and same_site(value, url)]
    if kind == 'calendar_api':
        data = json.loads(body)
        connection = data.get('events_connection') if isinstance(data, dict) else None
        nodes = connection.get('nodes') if isinstance(connection, dict) else None
        if not isinstance(nodes, list):
            raise ValueError('Unrecognized committee calendar response')
        out = [task(link, 'event', parent=url) for link, _ in calendar_links(body, url)]
        if len(nodes) >= request['body']['limit']:
            out.append(task(url, kind, body={**request['body'], 'offset': request['body']['offset'] + len(nodes)}, parent=url))
        return out
    if kind == 'wordpress_types':
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError('Unrecognized WordPress type index')
        out = []
        for row in data.values():
            base = row.get('rest_base') if isinstance(row, dict) else None
            if isinstance(base, str) and re.fullmatch(r'[\w-]+', base) and EVENT.search(base) and 'file' not in base:
                out.append(task(urljoin(url, '/wp-json/wp/v2/' + base) + '?per_page=100&page=1&_fields=link,title,date,acf', 'wordpress_posts', parent=url))
        return out
    if kind == 'wordpress_posts':
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError('Unrecognized WordPress event listing')
        out = [task(row['link'], 'event', parent=url) for row in data if isinstance(row, dict) and http_url(row.get('link')) and same_site(row['link'], url)]
        page = int(dict(parse_qsl(urlsplit(url).query)).get('page', 1))
        total = (headers or {}).get('X-WP-TotalPages')
        has_more = page < int(total) if total and str(total).isdigit() else len(data) == 100
        if has_more:
            out.append(task(query_url(url, page=page + 1), kind, parent=url))
        return out
    if kind == 'sitemap':
        try:
            root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except (etree.XMLSyntaxError, ValueError) as error:
            raise ValueError('Unrecognized sitemap response') from error
        name = etree.QName(root).localname
        if name not in {'urlset', 'sitemapindex'}:
            raise ValueError('Unrecognized sitemap response')
        return [task(node.text, 'sitemap' if name == 'sitemapindex' else 'event' if event_url(node.text or '') else 'html', parent=url)
                for node in root.xpath('//*[local-name()="loc"]') if http_url(node.text) and same_site(node.text, url)
                and (name == 'sitemapindex' or EVENT.search(urlsplit(node.text).path))
                and not (name == 'urlset' and (NEWS.search(urlsplit(node.text).path) or FILE.search(node.text)))]
    out = _html_tasks(body, url)
    if kind in {'home', 'site_home'}:
        # Shared ASP.NET committee calendar template. The public list's "All"
        # filter and next-page links enumerate actual events without month loops.
        if b'/sysjs/' in body and b'.aspx' in body:
            out.append(task(urljoin(url, '/calendar/eventslisting.aspx?Timeframe=All'), 'calendar_index_hint', parent=url))
        if b'/wp-content/' in body or b'/wp-json/' in body:
            out.append(task(urljoin(url, '/wp-json/wp/v2/types'), 'wordpress_types', parent=url))
        if (urlsplit(url).hostname or '').removeprefix('www.') == 'energycommerce.house.gov':
            out.append(task(urljoin(url, '/api/events'), 'calendar_api', body=dict(offset=0, limit=20, sort=['startDatetime:asc']), parent=url))
    return out
