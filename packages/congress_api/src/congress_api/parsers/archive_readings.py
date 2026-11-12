"""Body-only page evidence for the engine-first archive model.

Links retain their literal addresses and document order. Resolution, grouping
and record roles belong to the model SQL.
"""

import hashlib
import html as html_text
import json
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlsplit

from lxml import etree, html
from pytz import timezone

from congress_api.parsers.xml import MODS_NS, mods_elements


GROUPS = {'li', 'tr', 'meeting-document', 'witness-document', 'document'}
LINK_ATTRIBUTES = {'a': 'href', 'link': 'href', 'object': 'data', 'embed': 'src', 'iframe': 'src'}
TEXT_LINKS = {'file-url', 'doc-url', 'url', 'uri'}
DATES = {'dateissued', 'datecreated', 'datepublished'}
META_DATES = {'date', 'dc.date', 'dc.date.issued', 'article:published_time', 'datepublished'}
REFRESH = re.compile(r'\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.*?)\s*$', re.I)
MONTHS = {name.lower(): index for index, name in enumerate(
    'January February March April May June July August September October November December'.split(), 1)}
# Cloudflare email obfuscation, decoded as its email-decode.min.js does in a
# browser: a data-cfemail element becomes its address as text, and an
# email-protection href becomes mailto:. The first byte is the XOR key.
CLOUDFLARE_LINK = '/cdn-cgi/l/email-protection'
CLOUDFLARE_ELEMENT = re.compile(rb'<(a|span)\b[^>]*\bdata-cfemail="([0-9a-fA-F]+)"[^>]*>.*?</\1\s*>', re.S | re.I)
CLOUDFLARE_HREF = re.compile(rb'href="' + CLOUDFLARE_LINK.encode() + rb'#([0-9a-fA-F]+)"')
# C0 controls other than tab, LF and CR are invisible and illegal in XML; a
# single one (such as a legacy \x1a EOF byte) can make trafilatura return
# nothing. They are removed only to retry that extraction: a ZIP member keeps
# the same controls as its direct copy, and must read the same.
CONTROLS = re.compile(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]')
# The one place that says which html readings this reader can change: an
# html reading with no fingerprint, or with a link whose href contains
# CLOUDFLARE_LINK. Every other reading is byte for byte what the reader
# without browser normalization produced, so a producer may keep it and re-read
# only these. The engine has no row-scalar test over a list of structs, so the
# set is a query over a readings relation; it may repeat a body_sha.
HTML_REREAD_SQL = (
    "SELECT body_sha FROM {readings} WHERE parser = 'html' AND fingerprint IS NULL "
    "UNION ALL SELECT body_sha FROM (SELECT body_sha, unnest(links) AS link FROM {readings} "
    "WHERE parser = 'html') WHERE strpos(link['href'], '" + CLOUDFLARE_LINK + "') > 0")
HEADING_DATE = re.compile(r'\b(' + '|'.join(MONTHS) + r')\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\b', re.I)


def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def fingerprint(text):
    text = normalized(text)
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def _name(node):
    return node.tag.rsplit('}', 1)[-1].rsplit(':', 1)[-1].lower() if isinstance(node.tag, str) else ''


def _text(node):
    return normalized(''.join(node.itertext()))


def _visible_xml_text(node):
    """Normalized visible text of an XML element, skipping `display="no"` subtrees, comments and PIs."""
    parts = []

    def walk(el):
        if not isinstance(el.tag, str) or (el.get('display') or '').lower() == 'no':
            return
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(node)
    return normalized(''.join(parts))


def _link(href, *, text='', tag='', basis='', group_path=None, **publisher):
    return dict(href=href, text=text, tag=tag, basis=basis, group_path=group_path,
                doc_type=publisher.get('doc_type'), add_date=publisher.get('add_date'),
                publish_date=publisher.get('publish_date'), remove_date=publisher.get('remove_date'))


def json_url_strings(value, path=()):
    """Yield every absolute HTTP URL string once at its original JSON location."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from json_url_strings(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from json_url_strings(child, (*path, index))
    elif isinstance(value, str):
        try:
            parsed = urlsplit(value)
        except ValueError:
            return
        if parsed.scheme.lower() in {'http', 'https'} and parsed.netloc:
            yield _link(value, tag=json.dumps(path, ensure_ascii=False, separators=(',', ':')),
                        basis='json_url')


def _publisher(node):
    attributes = {key.replace('_', '-'): value for key, value in node.attrib.items()}
    description = next((_text(child) for child in node if _name(child) == 'description'), '')
    return description, dict(doc_type=attributes.get('type') or attributes.get('doc-type'),
                            add_date=attributes.get('add-date'), publish_date=attributes.get('publish-date'),
                            remove_date=attributes.get('remove-date'))


def _nodes(tree):
    """Carry paths and nearest groups through one bounded-depth traversal."""
    stack = []
    for event, node in etree.iterwalk(tree, events=('start', 'end')):
        if event == 'end':
            stack.pop()
            continue
        name = _name(node)
        if stack:
            counts = stack[-1][1]
            counts[name] = counts.get(name, 0) + 1
            path = f'{stack[-1][0]}/{name}[{counts[name]}]'
            group = stack[-1][2]
        else:
            path, group = f'{name}[1]', None
        if name in GROUPS:
            description, publisher = _publisher(node)
            group = path, description, publisher
        stack.append((path, {}, group))
        yield node, name, path, group



def _node_links(node, name, group, *, prefix='', inherited_group=None, xml=False):
    if group:
        group_path, description, publisher = group
        group_path = prefix + '/' + group_path if prefix else group_path
    else:
        group_path, description, publisher = inherited_group, '', {}
    attribute = LINK_ATTRIBUTES.get(name)
    if attribute is not None and attribute not in node.attrib:
        attribute = None
    if attribute is None and xml:
        attribute = next((key for key in node.attrib
                          if key.rsplit('}', 1)[-1].lower() in {'href', 'src', 'url'}), None)
    if attribute is not None and (href := node.get(attribute)) is not None:
        yield _link(href, text=description or _text(node), tag=name, basis=attribute,
                    group_path=group_path, **publisher)
    elif name in TEXT_LINKS and not len(node) and (href := (node.text or '').strip()):
        yield _link(href, text=description, tag=name, basis='text', group_path=group_path, **publisher)
    if name == 'meta' and node.get('http-equiv', '').lower() == 'refresh':
        if match := REFRESH.fullmatch(node.get('content', '')):
            yield _link(match[1].strip('\'"'), tag=name, basis='meta_refresh', group_path=group_path)


def _embedded_links(value, script_path, path=(), inherited_group=None, depth=0):
    if depth > 64:
        raise RuntimeError('embedded_depth_limit')
    if isinstance(value, dict):
        component = (value.get('__typename') == 'ComponentElementLink'
                     and isinstance(value.get('route'), str) and isinstance(value.get('label'), str))
        for key, child in value.items():
            if component and key == 'route':
                yield _link(child, text=value['label'], tag=json.dumps([*path, key], separators=(',', ':')),
                            basis='next_link', group_path=inherited_group)
            else:
                yield from _embedded_links(child, script_path, (*path, key), inherited_group, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _embedded_links(child, script_path, (*path, index), inherited_group, depth + 1)
    elif isinstance(value, str):
        urls = list(json_url_strings(value, path))
        if urls:
            for link in urls:
                link['group_path'] = inherited_group
                yield link
        elif '<' in value:
            try:
                tree = html.fromstring(value, parser=html.HTMLParser(no_network=True))
            except (etree.ParserError, ValueError):
                return
            prefix = script_path + '@' + json.dumps(path, ensure_ascii=False, separators=(',', ':'))
            for node, name, _, group in _nodes(tree):
                yield from _node_links(node, name, group, prefix=prefix, inherited_group=inherited_group)



def _content_date(values):
    dates = set()
    for value in values:
        try:
            instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
            dates.add((instant.astimezone(timezone('America/New_York')) if instant.tzinfo else instant).date().isoformat())
        except ValueError:
            try:
                dates.add(date.fromisoformat(value).isoformat())
            except ValueError:
                continue
    return next(iter(dates)) if len(dates) == 1 else None


def _heading_dates(text):
    result = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text or '')
    for month, day, year in HEADING_DATE.findall(text or ''):
        try:
            result.append(date(int(year), MONTHS[month.lower()], int(day)).isoformat())
        except ValueError:
            continue
    return result


def _markup_facts(body, parser):
    """Read markup facts without interpreting links or extracting main content."""
    tree = (html.document_fromstring(body, parser=html.HTMLParser(no_network=True)) if parser == 'html'
            else etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)))
    links, date_values, meetings, fields = [], [], [], []
    title = heading = base = None
    for node, name, node_path, group in _nodes(tree):
        group_path, description, publisher = group if group else (None, '', {})
        if parser == 'html':
            if name == 'title' and title is None:
                title = _text(node) or None
            if name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'} and heading is None:
                heading = _text(node) or None
            if name == 'base' and base is None:
                base = node.get('href')
        if name in DATES and (value := _text(node)):
            date_values.append(value)
        if name == 'meta' and (node.get('name') or node.get('property') or '').lower() in META_DATES:
            date_values.append(node.get('content', ''))
        links.extend(_node_links(node, name, group, xml=parser == 'xml'))
        if name == 'script' and (node.get('id') == '__NEXT_DATA__' or node.get('type', '').lower() in {'application/json', 'application/ld+json'}):
            try:
                links.extend(_embedded_links(json.loads(node.text or ''), node_path, inherited_group=group_path))
            except (ValueError, RecursionError):
                pass  # Invalid embedded data does not invalidate the page's markup.
    if parser == 'xml' and tree.tag == '{http://www.loc.gov/mods/v3}mods':
        scopes = [tree, *tree.findall('m:relatedItem[@type="constituent"]', MODS_NS)]
        held = []
        for scope in scopes:
            for event in mods_elements(scope, 'eventId'):
                value = _text(event)
                if value.isascii() and value.isdecimal() and int(value) <= 2**63 - 1:
                    meetings.append(int(value))
                else:
                    fields.append(dict(field='unparsed_event_id', value=value))
            held.extend(_text(node) for node in mods_elements(scope, 'heldDate'))
        date_values = held or date_values
    elif parser == 'xml' and _name(tree) == 'amendment-doc':
        form = next((child for child in tree if _name(child) == 'amendment-form'), None)
        if form is not None and (form.get('display') or '').lower() != 'no':
            def _iter_visible_descendants(el):
                for ch in el:
                    if not isinstance(ch.tag, str) or (ch.get('display') or '').lower() == 'no':
                        continue
                    yield ch
                    yield from _iter_visible_descendants(ch)

            legis_num = next(
                (val for child in _iter_visible_descendants(form) if _name(child) == 'legis-num' and (val := _visible_xml_text(child))),
                '',
            )
            action_descs = [
                val for child in _iter_visible_descendants(form) if _name(child) == 'action-desc' and (val := _visible_xml_text(child))
            ]
            if legis_num:
                heading = legis_num
            action_text = ' '.join(action_descs)
            if legis_num and action_text:
                title = f'{legis_num} \u2014 {action_text}'
            elif legis_num or action_text:
                title = legis_num or action_text
    # Links/title/date evidence is complete before invisible nodes are removed.
    if parser == 'html':
        etree.strip_elements(tree, etree.Comment, with_tail=False)
        for node in list(tree.iter()):
            if node is tree or node.getparent() is None:
                continue
            hidden = ('hidden' in node.attrib or re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', node.get('style', ''), re.I))
            if _name(node) in {'head', 'script', 'style', 'noscript', 'template', 'svg'} or hidden:
                node.drop_tree()
    text = _text(tree)
    date_values.extend(_heading_dates(heading))
    return dict(xml_root=_name(tree) if parser == 'xml' else None, title=title, heading=heading,
                base_href=base, links=links, text_bytes=len(text.encode()),
                text_head=text.encode()[:2048].decode('utf-8', 'ignore'), content_date=_content_date(date_values),
                named_meetings=meetings, link_count=len(links), link_text_bytes=sum(len(link['text'].encode()) for link in links),
                fields=fields), text


def _reject_constant(_value):
    raise ValueError('Non-finite JSON number')


def _cloudflare_address(token):
    """Return the escaped address of one obfuscated token, or None when it is malformed."""
    try:
        data = bytes.fromhex(token.decode('ascii'))
        return html_text.escape(bytes(byte ^ data[0] for byte in data[1:]).decode('utf-8')).encode() if data else None
    except (ValueError, UnicodeError):
        return None


def browser_body(body):
    """Return the body a browser shows after Cloudflare's decoder, and the decoded count."""
    count = 0
    def element(match):
        nonlocal count
        address = _cloudflare_address(match[2])
        count += address is not None
        return match[0] if address is None else address
    def href(match):
        address = _cloudflare_address(match[1])
        return match[0] if address is None else b'href="mailto:' + address + b'"'
    if b'data-cfemail' in body:
        body = CLOUDFLARE_ELEMENT.sub(element, body)
    if CLOUDFLARE_LINK.encode() in body:
        body = CLOUDFLARE_HREF.sub(href, body)
    return body, count


def needs_browser_reading(row):
    """Whether a plain reading is in the set HTML_REREAD_SQL selects."""
    return row['parser'] == 'html' and (row['fingerprint'] is None
                                        or any(CLOUDFLARE_LINK in (link['href'] or '') for link in row['links']))


def read_page(body, parser):
    """Return deterministic evidence with explicit input failures.

    An html reading in the HTML_REREAD_SQL set is read again from the body a
    browser shows; when main-content extraction still yields nothing, its
    fingerprint is the visible text's. No visible text gives none.
    """
    row, text = _plain_reading(body, parser)
    if not needs_browser_reading(row):
        return row
    cleaned, emails = browser_body(body)
    if cleaned != body:
        row, text = _plain_reading(cleaned, parser)
    if row['status'] != 'completed':
        return row
    basis = 'main'
    if row['fingerprint'] is None and CONTROLS.search(cleaned):
        # Controls stay in what is read; they are removed only for the extraction they break.
        from trafilatura import extract
        stripped = CONTROLS.sub(b'', cleaned)
        main = extract(stripped, include_comments=False, output_format='txt')
        if main:
            row['fingerprint'], basis = fingerprint(main), 'main_without_controls'
        else:
            text = _markup_facts(stripped, parser)[1]
    if row['fingerprint'] is None:
        row['fingerprint'], basis = fingerprint(text), 'visible'
    row['fields'] = [*row['fields'], dict(field='fingerprint_basis', value=basis)]
    if emails:
        row['fields'].append(dict(field='cloudflare_emails', value=str(emails)))
    return row


def _plain_reading(body, parser):
    """Read the body as given; return the row and its visible text."""
    text = ''
    if parser not in {'html', 'xml', 'json'}:
        raise ValueError('Unsupported page parser')
    row = dict(parser=parser, status='completed', error_type=None, format=None, intact=None,
               xml_root=None, title=None, heading=None, text_bytes=None, text_head=None,
               link_count=None, link_text_bytes=None, content_date=None, named_meetings=[],
               base_href=None, links=[], fingerprint=None, fields=[])
    try:
        if parser == 'json':
            text = body.decode('utf-8')
            value = json.loads(text, parse_constant=_reject_constant)
            row['links'] = list(json_url_strings(value))
            row['fingerprint'] = fingerprint(text)
        else:
            values, text = _markup_facts(body, parser)
            row.update(values)
            if parser == 'html':
                from trafilatura import extract
                main = extract(body, include_comments=False, output_format='txt')
                row['fingerprint'] = fingerprint(main) if main else None
            else:
                row['fingerprint'] = fingerprint(text)
    except (etree.Error, UnicodeError, ValueError, RuntimeError) as error:
        row.update(status='error', error_type=type(error).__name__, fingerprint=None)
    return row, text
