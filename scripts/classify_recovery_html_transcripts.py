"""Recognize printed hearing HTML in addition to Drupal document bodies."""
from lxml import html
from classify_recovery_html import classify as classify_drupal


def classify(raw):
    result = classify_drupal(raw)
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
