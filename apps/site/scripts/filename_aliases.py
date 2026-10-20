"""Resolve source aliases only to unambiguous, usable retained content."""
from congress_api.retention.body_keys import body_key_digest
from congress_api.retention.source_aliases import wrapped_target


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
