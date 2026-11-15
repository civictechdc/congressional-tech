"""Select Congress.gov's explicit embedded USLM bill, preserving original bytes.

This publisher wrapper is separate from RDFa article selection. Other pages and
ambiguous, incomplete or empty wrappers keep the ordinary HTML rendition. Forms
are never removed by tag name; the complete selected bill keeps its contents.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import re
from urllib.parse import urlsplit

from spicy_docs.reading.html_index import HtmlIndexReader, children, descendants
from spicy_docs.reading.markup_structure import Elem

POLICY = 'congress-gov-embedded-uslm-bill/001'
SELECTOR = 'xml#billTextUslm.generated-html-container > bill[xmlns="http://schemas.gpo.gov/xml/uslm"]'
_NAMESPACE = 'http://schemas.gpo.gov/xml/uslm'
_BILL_TEXT_PATH = re.compile(r'/bill/[1-9][0-9]*(?:st|nd|rd|th)-congress/(?:house|senate)-bill/[1-9][0-9]*/text(?:/[a-z]+)?/?')
_READER = HtmlIndexReader('Congress.gov embedded bill', ValueError, max_bytes=64 << 20, max_events=1_000_000)


@dataclass(frozen=True)
class HtmlContentSelection:
    body: bytes | None = field(repr=False)
    evidence: dict


def select_congress_bill_content(body: bytes) -> HtmlContentSelection | None:
    """Select one complete, publisher-marked UTF-8 USLM bill or explain fallback.

    The cheap marker check avoids a second syntax read for ordinary pages. The shared
    index reader checks balanced head/wrapper scopes while tolerating unrelated broken
    navigation. Its byte spans select source bytes directly, without DOM serialization.
    """
    if b'billTextUslm' not in body:
        return None
    evidence = dict(policy=POLICY, outcome='fallback', selector=SELECTOR)

    def fallback(reason):
        return HtmlContentSelection(None, evidence | dict(reason=reason))

    try:
        tree = _READER.tree(body, max_bytes=64 << 20, scopes=frozenset({'head', 'xml'}))
    except (ValueError, UnicodeError, RecursionError):
        return fallback('unqualified_markup')
    heads = children(tree, 'head')
    canonical = [node.attributes.get('href') for head in heads for node in descendants(head, 'link')
                 if 'canonical' in (node.attributes.get('rel') or '').split()]
    if len(heads) != 1 or len(canonical) != 1 or not canonical[0]:
        return fallback('missing_or_ambiguous_publisher')
    try:
        url = urlsplit(canonical[0])
    except ValueError:
        return fallback('unqualified_publisher')
    if (url.scheme != 'https' or url.netloc not in {'www.congress.gov', 'congress.gov'}
            or url.query or url.fragment or _BILL_TEXT_PATH.fullmatch(url.path) is None):
        return fallback('unqualified_publisher')
    evidence['canonical_url'] = canonical[0]
    wrappers = [node for node in descendants(tree) if node.attributes.get('id') == 'billTextUslm']
    if len(wrappers) != 1:
        return fallback('missing_or_ambiguous_wrapper')
    wrapper = wrappers[0]
    if (wrapper.name != 'xml' or wrapper.byte_end is None or 'hidden' in wrapper.attributes
            or 'generated-html-container' not in (wrapper.attributes.get('class') or '').split()):
        return fallback('unqualified_wrapper')
    bills = children(wrapper, 'bill')
    if (len(bills) != 1 or bills[0].attributes.get('xmlns') != _NAMESPACE
            or bills[0].byte_end is None
            or any(part is not bills[0] if isinstance(part, Elem) else bool((part.text or '').strip())
                   for part in wrapper.parts)):
        return fallback('incomplete_or_ambiguous_bill')
    bill = bills[0]
    selected = body[bill.byte_start:bill.byte_end]
    # Keep the standalone XML reader's encoding meaning; never transcode an HTML
    # fragment or strip its namespace/processing instructions to make it parse.
    try:
        selected.decode('utf-8')
    except UnicodeError:
        return fallback('non_utf8_bill')
    return HtmlContentSelection(selected, evidence | dict(outcome='selected', rendition='uslm',
        byte_start=bill.byte_start, byte_end=bill.byte_end, selected_bytes=len(selected),
        selected_sha256=sha256(selected).hexdigest()))
