"""URL normalization and publisher-domain evidence (C1).

Normalization is deliberately minimal — lowercase scheme/host and strip the
fragment — because C1 requires preserving original URLs: originals stay in
discovery.url and item.url_aliases, and only the comparison key is normalized.
Query strings, www prefixes, trailing slashes and encodings are never rewritten.
"""
from urllib.parse import urlsplit, urlunsplit

import tldextract

# Strictly offline PSL snapshot bundled with tldextract; never fetches over HTTP.
_PSL_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def normalize_url(url):
    """Lowercase scheme/host, redact userinfo, drop the fragment; everything else preserved."""
    parts = urlsplit(redact_userinfo(url))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ''))


def host_of(url):
    """Lowercase hostname without port, userinfo, IPv6 brackets, or trailing dot."""
    return (urlsplit(url).hostname or '').lower().rstrip('.')


def redact_userinfo(url):
    """Strip credentials from a URL before it reaches a stored record (C2).

    Keeps the rest of the URL (including host casing and IPv6 brackets) as
    evidence; only the userinfo prefix is removed when present.
    """
    parts = urlsplit(url)
    if '@' not in parts.netloc:
        return url
    netloc = parts.netloc.rsplit('@', 1)[1]
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


_OUTLET_LABELS = ('www.', 'm.', 'mobile.', 'amp.', 'news.', 'politics.')
_PUBLIC_SUFFIX_LABELS = frozenset({
    'ac', 'aero', 'asso', 'biz', 'co', 'com', 'coop', 'edu', 'fed',
    'go', 'gob', 'gov', 'gouv', 'gv', 'ind', 'inf', 'info', 'int',
    'jud', 'k12', 'leg', 'lg', 'mil', 'mod', 'mus', 'name', 'ne',
    'net', 'nhs', 'nic', 'nom', 'or', 'org', 'parliament', 'police',
    'presse', 'pro', 'sch', 'state', 'tm',
})


def outlet_domain(host):
    """The domain recorded on an outlet, with common subdomain labels dropped.

    Uses the bundled offline Mozilla Public Suffix List (via tldextract with
    network fetching disabled) plus a fallback label guard for synthetic RFC
    2606 test domains (.example): a leading www/m/mobile/amp/news/politics
    label is removed only while a registrable domain remains above the public
    suffix, and multi-part public suffixes such as example.co.uk stay intact.
    """
    host = (host or '').lower().rstrip('.')
    labels = host.split('.')
    while labels and (labels[0] + '.') in _OUTLET_LABELS:
        remaining = labels[1:]
        if len(remaining) < 2 or remaining[-2] in _PUBLIC_SUFFIX_LABELS:
            break
        extracted = _PSL_EXTRACT('.'.join( labels ))
        if extracted.suffix and (not extracted.subdomain or '.' in extracted.suffix):
            break
        labels = remaining
    return '.'.join(labels)


def same_publisher(url, domains):
    """True when the URL's host is one of the outlet domains or a subdomain.

    Redirect evidence may consolidate one publisher's URLs (C1); callers pass
    the outlet's recorded domains so a cross-domain link never merges.
    """
    host = host_of(url)
    return any(host == domain or host.endswith('.' + domain) for domain in domains)
