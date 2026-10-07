"""Read event listings and pagination without running JavaScript or guessing files.

Routes describe publisher platforms. Committee ownership comes from the retained
Congress.gov directory, not another hardcoded list of House domains.
"""
import json
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

from lxml import etree, html

from congress_api.parsers.committee_pages import calendar_links, same_site, listing_url
from congress_api.parsers.document_links import http_url, is_document_url

EVENT = re.compile(r'hearings?|events?|calendar|meetings?|mark[ -]?ups?|briefings?|listening.session|roundtables?|committee-activity|schedule|archiv', re.I)
RESOURCE = re.compile(r'\.(?:css|js|map|png|jpe?g|gif|svg|ico|woff2?|webp)$', re.I)
NEWS = re.compile(r'/(?:news|press|press-releases?|releases?|media/videos|media/press)', re.I)


class UnrecognizedSitemap(ValueError):
    """An optional discovery endpoint did not supply a supported sitemap."""


def page_link_exclusion(value, base=''):
    """Keep obvious non-page links out of discovery, without rewriting them.

    Inspect only the path for embedded markup/URLs; queries may contain both.
    Two observed external link services were published without their scheme.
    Other dotted paths, explicit ./ paths and names with spaces stay literal.
    """
    target = http_url(value, base)
    if not target:
        return 'malformed_link'
    path = unquote(urlsplit(target).path)
    if re.search(r'<\s*/?[a-z][\w:-]*(?:\s|>|/)|https?:/', path, re.I) or re.match(
            r'^(?:bit\.ly|linktr\.ee)/', unquote(value), re.I):
        return 'malformed_link'
    if is_document_url(target, publisher_routes=True):
        return 'document_link'
    if RESOURCE.search(urlsplit(target).path):
        return 'resource'
    return None


def task(url, kind='html', *, body=None, parent=None):
    return dict(url=url, kind=kind, **({'body': body} if body is not None else {}), **({'discovered_from': parent} if parent else {}))


def key(request):
    return json.dumps([request['url'], request.get('body')], separators=(',', ':'), sort_keys=True)


def comparison_key(request):
    """Compare independent query fields without rewriting the source URL.

    Stable sorting preserves the order of repeated values for the same field.
    Source receipt and queue keys deliberately remain literal.
    """
    parts = urlsplit(request['url'])
    pairs = sorted(parse_qsl(parts.query, keep_blank_values=True), key=lambda pair: pair[0])
    return key({**request, 'url': parts._replace(query=urlencode(pairs), fragment='').geturl()})


def listing_records(body, url):
    """Fingerprint explicit listing rows, not their shared hearing references.

    ASP.NET event cards and Drupal view rows contain the actual listed records.
    Pagination, filter controls and changing site chrome sit outside these rows.
    Explicit empty calendars return []; unknown layouts return None so callers
    can use discovered detail links.
    """
    try:
        root = html.fromstring(body, parser=html.HTMLParser(no_network=True))
    except (etree.ParserError, ValueError):
        return None
    # Drupal also uses views-row for footer office addresses. Those are site
    # chrome, not evidence that two hearing listings contain the same records.
    main = root.xpath('//main | //*[@role="main"]')
    root = main[0] if main else root
    rows = root.xpath('.//article[contains(concat(" ",normalize-space(@class)," ")," article-item ")] | '
                      './/*[contains(concat(" ",normalize-space(@class)," ")," views-row ")] | '
                      './/*[contains(concat(" ",normalize-space(@class)," ")," views-view-responsive-grid__item ")]')
    rows = [row for row in rows if not row.xpath('ancestor::footer | ancestor::header | ancestor::nav | ancestor::aside')]
    if not rows:
        if listing_url(url):
            messages = root.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," errormsg ")]')
            if any(' '.join(node.text_content().split()).lower().rstrip('.') == 'no events found'
                   for node in messages if not node.xpath('ancestor::footer | ancestor::header | ancestor::nav | ancestor::aside')):
                return []
        return None
    return sorted({json.dumps([' '.join(row.text_content().split()), sorted({
        target for a in row.xpath('.//a[@href]') if (target := http_url(a.get('href'), url))
    })], ensure_ascii=False) for row in rows})


def pagination_field(name):
    """Query fields shared by listing discovery, filter resets and loop checks."""
    return name.lower() == 'page' or name.lower().startswith(('pagenum_', 'mt_page'))


def query_url(url, *, reset_pagination=False, **values):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in values.items()})
    if reset_pagination:
        query = {k: v for k, v in query.items() if not pagination_field(k)}
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
        if not target or not same_site(target, url) or page_link_exclusion(href, url) or href.startswith('#') or '/wp-json/' in urlsplit(target).path:
            continue
        path = urlsplit(target).path
        # WordPress month calendars have unbounded previous/next months. Their
        # event archives, REST indexes and sitemaps enumerate actual entries.
        if re.search(r'/(?:month|day|today)(?:/|$)|/feed/?$|[?&](?:eventDate|tribe-bar-date)=', target):
            continue
        if NEWS.search(path) and not path.startswith('/media/announcement/'):
            continue
        pagination = listing and (any(pagination_field(k) for k, _ in parse_qsl(urlsplit(target).query))
                                  or re.search(r'/page/\d+', path)
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
                        values = {**defaults, select.get('name'): option.get('value')}
                        out.append(task(query_url(destination, reset_pagination=True, **values), parent=url))
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
            raise UnrecognizedSitemap('Unrecognized sitemap response') from error
        name = etree.QName(root).localname
        if name not in {'urlset', 'sitemapindex'}:
            raise UnrecognizedSitemap('Unrecognized sitemap response')
        return [task(node.text, 'sitemap' if name == 'sitemapindex' else 'event' if event_url(node.text or '') else 'html', parent=url)
                for node in root.xpath('//*[local-name()="loc"]') if http_url(node.text) and same_site(node.text, url)
                and (name == 'sitemapindex' or EVENT.search(urlsplit(node.text).path))
                and not (name == 'urlset' and (NEWS.search(urlsplit(node.text).path) or page_link_exclusion(node.text)))]
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
