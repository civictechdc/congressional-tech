"""Read static HTML and explicitly embedded page data without running scripts."""

import json

from lxml import etree, html


def page_trees(body):
    """Yield (source selector, HTML tree), including Next.js event HTML fields.

    Restrict embedded content to the current event, not recommendations, menus
    or unrelated JSON elsewhere on the page. Original bytes stay with callers.
    """
    try:
        tree = html.fromstring(body, parser=html.HTMLParser(no_network=True))
    except (etree.ParserError, ValueError):
        return
    yield '', tree
    for path, value in page_data(tree):
        if path != '__NEXT_DATA__/props/pageProps/event' or not isinstance(value, dict):
            continue
        pending = [(path, value, 0)]
        while pending:
            selector, item, depth = pending.pop()
            if depth > 12:
                continue
            if isinstance(item, dict):
                # Next.js also renders labeled links stored as data rather
                # than HTML (for example an event's hearing memorandum).
                if (isinstance(item.get('route'), str) and isinstance(item.get('label'), str)
                        and item.get('__typename') == 'ComponentElementLink'):
                    anchor = html.Element('a', href=item['route'])
                    anchor.text = item['label']
                    yield selector, anchor
                pending.extend((selector + '/' + str(k), v, depth + 1) for k, v in reversed(list(item.items())))
            elif isinstance(item, list):
                pending.extend((selector + '/' + str(i), v, depth + 1) for i, v in reversed(list(enumerate(item))))
            elif isinstance(item, str) and '<' in item and len(item) <= 4 * 1024**2:
                try:
                    yield selector, html.fromstring(item, parser=html.HTMLParser(no_network=True))
                except (etree.ParserError, ValueError):
                    continue


def page_data(tree):
    """Known serialized event records; malformed JSON leaves static HTML usable."""
    for node in tree.xpath('//script[@id="__NEXT_DATA__" or @type="application/ld+json"]'):
        try:
            data = json.loads(node.text or '')
        except (ValueError, RecursionError):
            continue
        if node.get('id') == '__NEXT_DATA__':
            props = data.get('props') if isinstance(data, dict) else None
            props = props.get('pageProps') if isinstance(props, dict) else None
            event = props.get('event') if isinstance(props, dict) else None
            if isinstance(event, dict):
                yield '__NEXT_DATA__/props/pageProps/event', event
        else:
            pending = data if isinstance(data, list) else [data]
            for value in pending:
                if isinstance(value, dict):
                    graph = value.get('@graph', [value])
                    for event in graph if isinstance(graph, list) else []:
                        if isinstance(event, dict) and event.get('@type') == 'Event':
                            yield 'application/ld+json', event
