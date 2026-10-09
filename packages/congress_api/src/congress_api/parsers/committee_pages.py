"""Read official event pages and discovery links; fetching stays with collectors."""

import re
import json
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit

from lxml import etree, html
from copy import deepcopy

from congress_api.models.content import RawContent

from congress_api.parsers.text import words
from congress_api.parsers.document_links import FILE, links_from_trees, http_url
from congress_api.parsers.page_content import page_data, page_trees
from congress_api.parsers.senate_page import (DATE, literal_document_kind, written_day,
    lines, witnesses, source_details_tree, document_kind, related_page)

def calendar_links(body, url):
    """Use the publisher's literal slugs and its documented /events/ route."""
    data = json.loads(body)
    connection = data.get('events_connection') if isinstance(data, dict) else None
    nodes = connection.get('nodes') if isinstance(connection, dict) else None
    if not isinstance(nodes, list):
        raise ValueError('Unrecognized committee calendar response')
    return [(urljoin(url, '/events/' + node['slug']), node.get('title', '')) for node in nodes[:20]
            if isinstance(node, dict) and isinstance(node.get('slug'), str)
            and re.fullmatch(r'[a-zA-Z0-9_-]+', node['slug']) and isinstance(node.get('title', ''), str)]


def same_site(url, home):
    parsed = urlsplit(http_url(url) or '')
    owner = urlsplit(home).hostname or ''
    return (parsed.hostname or '').removeprefix('www.') == owner.removeprefix('www.') and parsed.port in (None, 80, 443)


def discovery_links(body, url):
    """Literal anchors and sitemap entries, never guessed hearing slugs."""
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        if etree.QName(root).localname in {'urlset', 'sitemapindex'}:
            return [(node.text or '', '') for node in root.xpath('//*[local-name()="loc"]')]
    except (etree.XMLSyntaxError, ValueError):
        pass
    return [(node.get('href'), ' '.join(node.text_content().split()))
            for _, tree in page_trees(body) for node in tree.xpath('//a[@href]')]


def event_title(tree):
    """Prefer a subject heading over a category banner or empty site logo."""
    generic = {'hearings', 'hearing', 'events', 'calendar', 'meetings', 'business meetings', 'markups', 'home'}
    subject = ('//*[self::h1 or self::h2][contains(concat(" ",normalize-space(@class)," ")," main_page_title ")] | '
               '//article[contains(concat(" ",normalize-space(@class)," ")," post ")]'
               '//*[self::h1 or self::h2][contains(concat(" ",normalize-space(@class)," ")," title ")]')
    selectors = ((subject, True),
                 ('//*[contains(@class,"newsie-titler") or (contains(@class,"middleheadline") and not(self::h3))]', False),
                 ('//main//h1', False), ('//h1', False), ('//main//h2', False))
    for xpath, explicit in selectors:
        headings = [n for n in tree.xpath(xpath) if not n.xpath('ancestor::nav | ancestor::footer | ancestor::aside')]
        titles = list(dict.fromkeys(' '.join(n.text_content().split()) for n in headings))
        titles = [t for t in titles if t and t.lower() not in generic]
        if len(titles) == 1:
            return titles[0]
        if titles and explicit:
            return ''  # Conflicting subject headings cannot be resolved by a generic banner.
    return ''


def listing_url(url):
    """Recognize archive routes before reading dates from their child events."""
    parsed = urlsplit(url)
    if {k.lower() for k in parse_qs(parsed.query)} & {'eventid', 'contentrecord_id', 'id'}:
        return False
    return bool(re.search(r'/(?:committee-activity|events?|hearings?|meetings?|business-meetings|markups?|calendar|calendars|schedule)(?:/(?:all|past|upcoming|archive|page/\d+|\d{4}))?/?$|/(?:calendar|events?)/(?:default|eventslisting|list|schedule)\.aspx$', parsed.path, re.I))


def event_identity(body, url=''):
    """Use an explicit event date; publication timestamps are not event dates."""
    if listing_url(url):
        return None
    for _, tree in page_trees(body):
        for selector, event in page_data(tree):
            title = event.get('title') or event.get('name')
            day = event.get('startDatetime') or event.get('startDate')
            if isinstance(title, str) and isinstance(day, str):
                try:
                    parsed_day = date.fromisoformat(day[:10])
                except ValueError:
                    continue
                return dict(title=title, date=parsed_day.isoformat(), date_text=day, selector=selector)
        title = event_title(tree)
        if not title:
            continue
        times = tree.xpath('//*[@itemprop="startDate"]/@content | //*[@itemprop="startDate"]/@datetime')
        values = list(times)
        # Publisher event fields used by Drupal, the shared House calendar,
        # and WordPress event templates. Do not read generic article dates.
        for node in tree.xpath('//*[contains(@class,"field-evo-meeting-date") or contains(@class,"hearing__date") or contains(@class,"event-item__date") or contains(@class,"event-item__meta") or contains(@id,"_EventDate")]'):
            values.append(' '.join(node.text_content().split()))
        if re.search(r'eventsingle\.aspx', url, re.I):
            values += [' '.join(n.text_content().split()) for n in tree.xpath('//*[contains(@class,"topnewstext")]')]
        if ({k.lower() for k in parse_qs(urlsplit(url).query)} & {'id', 'contentrecord_id'}
                and re.search(r'/(?:hearings?|events?|markups?)(?:/|$)', urlsplit(url).path, re.I)):
            posts = tree.xpath('//article[contains(concat(" ",normalize-space(@class)," ")," post ")]')
            if len(posts) == 1:
                values += [' '.join(n.text_content().split()) for n in posts[0].xpath('./div[@class="header"]//span[@class="date"]')]
        for node in tree.xpath('//p | //div | //td | //span | //time'):
            value = ' '.join(node.text_content().split())
            if len(value) < 180 and re.match(r'^(?:(?:hearing |event |meeting )?date|when)\s*:', value, re.I):
                values.append(value)
        days = {day.isoformat() for value in values for match in DATE.finditer(value) if (day := written_day(match))}
        if len(days) == 1:
            return dict(title=title, date=next(iter(days)), selector='displayed event heading/date')
    return None


def publisher_document_link(anchor, page_url=''):
    """HTML documents qualify through their own label or local event section."""
    return bool((related_page(anchor, page_url) or {}).get('document_kind'))


def non_document_link(anchor, page_url):
    """A named media/intake/repository link overrides generic download prompts."""
    return (related_page(anchor, page_url) or {}).get('role') in {
        'media', 'registration', 'repository', 'related_coverage', 'unavailable'}


def content_trees(body):
    """Read event content without treating site navigation as its attachments."""
    for selector, tree in page_trees(body):
        for node in tree.xpath('//nav | //footer | //*[@role="navigation" or @role="contentinfo"]'):
            if node.getparent() is not None:
                node.drop_tree()
        yield selector, tree


def committee_document_links(body, url):
    return context_document_links(content_trees(body), url)


def context_document_links(trees, url):
    return [] if listing_url(url) else links_from_trees(trees, url,
        include_link=lambda anchor: publisher_document_link(anchor, url),
        exclude_link=lambda anchor: non_document_link(anchor, url))


def parse_event_page(body, url):
    """Reuse the Senate layout readers and the shared complete file-link reader.

    Embedded event markup is parsed for context but never replaces the original
    retained body. Unrecognized dates remain unknown, with every link retained.
    """
    trees = list(content_trees(body))
    # Keep decoded fragments inside one valid document. Concatenating a full
    # </html> with later fragments causes lxml to ignore the later witnesses.
    combined = html.Element('div')
    for _, tree in trees:
        tree = deepcopy(tree)
        for node in tree.iter():
            if node.tag in {'html', 'head', 'body'}:
                node.tag = 'div'
        etree.SubElement(combined, 'section').append(tree)
    etree.strip_elements(combined, etree.Comment, with_tail=False)
    markup = html.tostring(combined, encoding='unicode')
    people = witnesses(markup, url, plain=True)
    # Reuse the parsed tree: HTML serialization escapes spaces in href values,
    # which would detach occurrence context from the original document URL.
    metadata, people_metadata, page_metadata = source_details_tree(combined, url, people, plain=True,
        include_link=lambda anchor: publisher_document_link(anchor, url),
        exclude_link=lambda anchor: non_document_link(anchor, url))
    documents = []
    for link in context_document_links(trees, url):
        detail = metadata.setdefault(link.url, {})
        if not detail:
            detail.update(labels=[link.text], occurrences=[dict(labels=[link.text], attributes=[link.attributes],
                          source_selector=getattr(link, 'source_selector', None))])
        documents.append([document_kind(link.text, link.url, detail), link.text, link.url])
    event = event_identity(body, url)
    title = event['title'] if event else event_title(trees[0][1]) if trees else ''
    if not title and trees:
        title = ' '.join(trees[0][1].xpath('//title/text()'))
    return dict(title=title, event={**event, 'url': url} if event else None, page_kind='listing' if listing_url(url) else 'event_candidate',
        lines=sorted(lines(markup)), witnesses=people, documents=documents,
        document_metadata=metadata, witness_metadata=people_metadata, page_metadata=page_metadata,
        raw_html=RawContent.from_bytes(body, 'text/html').source_dict())


def match_event(body, url, meeting):
    """Same official committee plus exact event ID, or date and title subject."""
    identity = event_identity(body, url)
    if identity and identity['date'] != meeting.get('date', '')[:10]:
        return None
    event_id = str(meeting['eventId'])
    linked_events = {}
    for href, _ in discovery_links(body, url):
        parsed = urlsplit(http_url(href, url) or '')
        if parsed.hostname == 'docs.house.gov':
            for value in parse_qs(parsed.query).get('EventID', []):
                linked_events[value] = href
            if match := re.search(r'/meetings/[^/]+/[^/]+/\d{8}/(\d+)/', parsed.path):
                linked_events[match[1]] = href
    # An event index may link many hearings. Never assign all its documents to
    # one meeting just because one of those links carries the right event ID.
    if identity and set(linked_events) == {event_id}:
        return dict(method='explicit_house_event_link', event_id=event_id,
                    linked_url=linked_events[event_id], event=identity)
    subject = words(meeting.get('title', ''))
    if identity and not (set(linked_events) - {event_id}) and len(subject) >= 4 and subject <= words(identity['title']):
        return dict(method='same_committee_date_title', event_id=event_id, event=identity)
    return None


def document_groups(body, url, selector):
    """Use the shared link reader; preserve the page and exact source selector."""
    for order, link in enumerate(committee_document_links(body, url)):
        # The collector never downloads files or claims that an alternate URL
        # has identical bytes to a broken repository URL.
        yield dict(source='committee_html', source_url=url, selector=selector,
                   source_order=order, active=True, description=link.text,
                   legacy_kind=literal_document_kind(link.text, link.url),
                   metadata=dict(attributes=link.attributes, link=link.source_dict()),
                   files=[dict(url=link.url, format=urlsplit(link.url).path.rsplit('.', 1)[-1].upper() if FILE.search(link.url) else '',
                               active=True, selector=selector, metadata=dict(attributes=link.attributes))])
