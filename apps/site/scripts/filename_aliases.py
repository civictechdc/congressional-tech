"""Resolve source aliases only to unambiguous, usable retained content."""
from collections import defaultdict
import re

import pyarrow.parquet as pq

from congress_api.parsers.archive_links import allowed_url, capture_links
from congress_api.retention.saved_responses import FIELDS, saved_response

BODY_KEY = re.compile(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.gz')


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
    match = BODY_KEY.fullmatch(key or '')
    return bool(match and match[1] == match[2][:2])


def catalog_aliases(path, accepted=()):
    """Keep literal sources intact; derive links from their recorded resolutions.

    Resolve across all observations of an original URL. Multiple destinations or
    usable body versions remain unresolved. Accepted recoveries take precedence.
    """
    source = pq.ParquetFile(path)
    columns = [name for name in (*FIELDS, 'source_resolved_url') if name in source.schema_arrow.names]
    candidates = defaultdict(set)
    saved_originals = set()
    accepted_originals = {r['original_url'] for r in accepted}
    for batch in source.iter_batches(columns=columns):
        for row in batch.to_pylist():
            original = row.get('source_url')
            if not original or original in accepted_originals:
                continue
            if saved_response(row):
                saved_originals.add(original)
            resolved = row.get('source_resolved_url') or []
            if resolved:
                # Include invalid/self destinations so they cannot hide a conflict.
                candidates[original].update(resolved)
            elif target := wrapped_target(original):
                candidates[original].add(target)
    targets = {}
    for original, choices in candidates.items():
        if original in saved_originals or len(choices) != 1:
            continue
        target = next(iter(choices))
        if target != original and allowed_url(target) == target:
            targets[original] = target
    wanted = set(targets.values())
    bodies = defaultdict(dict)
    for batch in source.iter_batches(columns=columns):
        for row in batch.to_pylist():
            url = row.get('source_url')
            if url in wanted and valid_body(row.get('body_key')) and saved_response(row):
                bodies[url][row['body_key']] = content_kind(row)
    for row in accepted:
        if row['kind'] == 'video' or not valid_body(row['body_key']):
            continue
        for url in (row['original_url'], row['recovered_url']):
            if url in wanted:
                bodies[url][row['body_key']] = row['kind']
    result = []
    for original, target in sorted(targets.items()):
        if len(bodies[target]) != 1:
            continue
        key, kind = next(iter(bodies[target].items()))
        result.append(dict(original_url=original, recovered_url=target, body_key=key,
                           kind=kind, recovery_status='recovered',
                           recovery_basis='resolved_source_url'))
    return result
