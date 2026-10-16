"""Decide whether retained bytes may be offered as a saved source response."""
from functools import lru_cache
import json
from pathlib import Path

from .document_evidence import response_failed

FIELDS = ('body_key', 'source_url', 'media_type', 'http_status', 'record_role',
          'source_record_type', 'capture_outcome', 'state_outcome',
          'response_usable', 'response_body_complete')


@lru_cache(maxsize=1)
def review_records():
    return json.loads(Path(__file__).with_name('saved_response_reviews.json').read_text())


@lru_cache(maxsize=1)
def reviewed_error_bodies():
    """An identified error page remains an error page through redirect aliases."""
    return frozenset(row['body_key'] for row in review_records()
                     if row['reviewed_category'] == 'soft_404')


@lru_cache(maxsize=1)
def content_reviews():
    """Reviews bind a content decision to the exact source URL and body digest."""
    return {(row['url'], row['body_key']): row['usable_content'] for row in review_records()}


def saved_response(row):
    """Keep failed captures as evidence without offering them as recovered content."""
    if not row.get('body_key') or row['body_key'] in reviewed_error_bodies():
        return False
    media = {value.split(';', 1)[0].strip().lower() for value in row.get('media_type') or []}
    if any(kind.startswith('video/') and kind != 'video/x-ms-wvx' for kind in media):
        return False
    # A content review may resolve an HTML validation abstention, but cannot
    # make explicitly incomplete bytes or a failed HTTP response complete.
    if set(row.get('response_body_complete') or []) == {'false'}:
        return False
    statuses = {int(value) for value in row.get('http_status') or [] if str(value).isdigit()}
    if statuses and not any(200 <= value < 300 for value in statuses):
        return False
    outcomes = set(row.get('capture_outcome') or [])
    if outcomes and outcomes <= {'retry_later', 'size_limit', 'resource_limit', 'timeout',
                                'request_failed', 'empty', 'incomplete'}:
        return False
    reviewed = content_reviews().get((row.get('source_url'), row['body_key']))
    if reviewed is not None:
        return reviewed
    if (row.get('record_role') == ['error-response']
            or 'error-page' in (row.get('source_record_type') or [])):
        return False
    # Current URL state can describe a newer failure than these retained bytes.
    # Use this source row's capture evidence, not a different capture's state.
    return not response_failed(row)
