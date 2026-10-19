"""Classify archived document content without accepting navigation or wrappers.

The caller must separately verify archive digest, response completeness, source
URL identity, and deferred-body exclusions before treating content as recovered.
"""
from lxml import html


def classify(raw):
    tree = html.fromstring(raw)
    title = ' '.join(' '.join(tree.xpath('//title/text()')).split())
    if any(value in title.lower() for value in (
        'session verification', 'rate limit reached', 'access denied',
        'request not accepted', 'page not found', '404 not found', 'just a moment',
    )):
        return dict(category='error_or_challenge', title=title, words=0, links=[])
    fields = tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " field-name-body ")]')
    for node in tree.xpath('//script|//style|//nav|//header|//footer'):
        node.drop_tree()
    text = ' '.join(' '.join(' '.join(node.itertext()).split()) for node in fields).strip()
    links = [dict(href=link.get('href'), text=' '.join(' '.join(link.itertext()).split()))
             for node in fields for link in node.xpath('.//a[@href]')]
    words = len(text.split())
    if text.lower().rstrip('.') == 'no prepared statement':
        category = 'historical_no_prepared_statement'
    elif not text:
        category = 'empty_document_body'
    elif words >= 100 and title:
        category = 'substantial_document_body'
    elif links:
        category = 'attachment_page'
    else:
        category = 'short_text_needs_review'
    return dict(category=category, title=title, words=words, text=text, links=links)


def classify_transcripts(raw):
    """Recognize printed hearing HTML in addition to Drupal document bodies."""
    result = classify(raw)
    if result['category'] != 'empty_document_body':
        return result
    tree = html.fromstring(raw)
    for node in tree.xpath('//script|//style|//nav|//header|//footer'):
        node.drop_tree()
    body = tree.find('body')
    text = ' '.join(' '.join((body if body is not None else tree).itertext()).split())
    normalized = text.lower()
    title = result['title'].lower()
    markers = ('hearing before', 'house of representatives', 'serial no.',
               'printed for the use of the committee')
    if ('committee on veterans' in title and len(text.split()) >= 500
            and all(marker in normalized for marker in markers)):
        return dict(result, category='substantial_document_body',
                    subtype='printed_hearing_transcript', text=text,
                    words=len(text.split()))
    return result
