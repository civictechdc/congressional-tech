"""Resolve source aliases only to unambiguous, usable retained content."""
import re

from congress_api.parsers.archive_links import allowed_url, capture_links
from congress_api.retention.body_keys import body_key_digest


def wrapped_target(value):
    """Recognize explicit URL wrappers; never infer a base or document version."""
    if not isinstance(value, str):
        return None
    candidate = None
    if value.startswith('ttps://'):
        candidate = 'h' + value
    elif value.startswith('mailto:https://') or value.startswith('mailto:http://'):
        candidate = value[len('mailto:'):]
    elif match := re.fullmatch(r'chrome-extension://[a-p]{32}/(https?://.+)', value):
        candidate = match[1]
    elif re.match(r'https?://(?:www\.)?lis\.gov/cgi-lis/t2GPO/', value):
        links = capture_links({'url': value})
        if len(links) == 1 and links[0].get('url_repair') == 'lis_gpo_wrapper':
            candidate = links[0]['url']
    return candidate if candidate and allowed_url(candidate) == candidate else None


def content_kind(row):
    media = ' '.join(row.get('media_type') or []).lower()
    if 'pdf' in media:
        return 'pdf'
    if 'xml' in media:
        return 'xml'
    if 'html' in media:
        return 'html'
    return 'doc'


def valid_body(key):
    return body_key_digest(key) is not None


def catalog_aliases(path, accepted=()):
    """Keep literal sources intact; derive links from their recorded resolutions.

    Resolve across all observations of an original URL. Multiple destinations or
    usable body versions remain unresolved. Accepted recoveries take precedence.
    """
    from filename_alias_index import AliasIndex
    with AliasIndex(path, accepted) as index:
        return index.aliases()
