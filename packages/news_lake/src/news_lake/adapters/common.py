"""Shared provider plumbing: fetch outcomes, captures, publications, outlets.

The outlet/item namespaces are shared by every adapter so the same article
found by two providers yields two discoveries but ONE item (C2/P1 overlap);
the discovery namespace keys on (capture, provider, url-or-external-id) so
replaying one captured result reuses ids while a new poll is a new
observation. Capture ids are fresh per fetch attempt (context id source).
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import re

from news_lake.context import adapter_namespace, format_instant, named_id
from news_lake.contract.errors import ContractError
from news_lake.contract.records import validate_shape
from news_lake.adapters.urls import normalize_url, redact_userinfo

OUTLET_NAMESPACE = adapter_namespace('outlet')
ITEM_NAMESPACE = adapter_namespace('item')
DISCOVERY_NAMESPACE = adapter_namespace('discovery')
_OUTLET_DOMAIN_PATTERN = re.compile(r'^[a-z0-9][a-z0-9.-]*[a-z0-9]$')


def item_id_for(outlet_id, canonical_url):
    """The single owner of the item identity UUID (C1).

    Provider overlap dedups at the item level only while every adapter derives
    the id the same way; a drifted copy would silently split one logical item
    into two. Keyed on (outlet, canonical url) under the shared item namespace.
    """
    return named_id(ITEM_NAMESPACE, f'item:{outlet_id or ""}:{canonical_url}')


@dataclass
class FetchOutcome:
    """One (simulated or real) fetch attempt handed to an adapter.

    outcome: 'succeeded' | 'not_modified' | 'failed' (C2).
    metadata_only: the fetch succeeded but the source is blocked/paywalled —
    keep response metadata, retain no payload (C5).
    """

    url: str
    status: int = None
    body: bytes = None
    outcome: str = 'succeeded'
    error_code: str = None
    access: str = 'restricted'
    rights_basis: str = None
    payload_uri: str = None
    media_type: str = None
    metadata_only: bool = False
    observed_at: str = None


def build_capture(context, provider, fetch, capture_id=None):
    """Build a capture record enforcing the C2/C5 outcome rules."""
    identifier = capture_id if capture_id is not None else context.new_id()
    now = context.now_string()
    record = {
        'kind': 'capture',
        'id': identifier,
        'recorded_at': now,
        'provider': provider,
        'request_url': redact_userinfo(fetch.url),
        'observed_at': fetch.observed_at if fetch.observed_at is not None else now,
    }
    if fetch.status is not None:
        record['http_status'] = fetch.status
    if fetch.outcome == 'failed':
        if not fetch.error_code:
            raise ValueError('a failed capture requires an error_code (C2)')
        record.update(access='metadata_only', status='failed', error_code=fetch.error_code)
    elif fetch.outcome == 'not_modified':
        record.update(access='metadata_only', status='not_modified')
    elif fetch.metadata_only:
        # Blocked/paywalled: no payload fields at all (schema forbids them).
        record.update(access='metadata_only', status='succeeded')
    else:
        if fetch.body is None:
            raise ValueError('a retained capture requires body bytes')
        if not fetch.payload_uri:
            raise ValueError('a retained capture requires a payload_uri (raw object)')
        if not fetch.rights_basis:
            raise ValueError('retained payloads require an explicit rights_basis (C5)')
        if fetch.access not in ('restricted', 'redistributable'):
            raise ValueError('retained payloads are restricted or redistributable (C5)')
        record.update(
            access=fetch.access,
            status='succeeded',
            payload_uri=fetch.payload_uri,
            payload_hash=sha256(fetch.body).hexdigest(),
            media_type=fetch.media_type or 'application/octet-stream',
            rights_basis=fetch.rights_basis,
        )
    return validate_shape(record)


def publication_unknown():
    """C3: absent/unparseable publication; never invent a timestamp."""
    return {'precision': 'unknown'}


def publication_day(value, basis='provider'):
    """Day precision from a reported date; basis provider (or publisher for feeds)."""
    day = value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))
    return {'precision': 'day', 'date': day.isoformat(), 'basis': basis}


def publication_instant(moment, basis='provider'):
    """Instant precision from a tz-aware reported time; basis provider by default."""
    if moment.tzinfo is None:
        raise ValueError('instant precision requires a timezone-aware time (C3: never invent midnight)')
    return {'precision': 'instant', 'at': format_instant(moment.astimezone(timezone.utc)), 'basis': basis}


def outlet_for_domain(domain, recorded_at, *, name=None, feed_url=None):
    """Deterministic outlet record for a publisher domain (shared namespace)."""
    if not isinstance(domain, str) or not _OUTLET_DOMAIN_PATTERN.fullmatch(domain):
        raise ContractError('invalid_outlet_domain', f'invalid outlet domain {domain!r}')
    record = {
        'kind': 'outlet',
        'id': named_id(OUTLET_NAMESPACE, f'outlet:{domain}'),
        'recorded_at': recorded_at,
        'name': name or domain,
        'domains': [domain],
    }
    if feed_url is not None:
        record['feed_urls'] = [redact_userinfo(feed_url)]
    return validate_shape(record)


def build_discovery(*, capture, item_id, provider, url, observed_at, recorded_at, mode,
                    external_id=None, query_revision=None, feed_url=None,
                    reported_title=None, reported_publication=None):
    """Discovery keyed on (capture, provider, external id or normalized url)."""
    url = redact_userinfo(url)
    key = external_id if external_id is not None else normalize_url(url)
    record = {
        'kind': 'discovery',
        'id': named_id(DISCOVERY_NAMESPACE, f'discovery:{capture["id"]}:{provider}:{key}'),
        'recorded_at': recorded_at,
        'capture_id': capture['id'],
        'item_id': item_id,
        'provider': provider,
        'url': url,
        'observed_at': observed_at,
        'mode': mode,
    }
    if external_id is not None:
        record['external_id'] = external_id
    if query_revision is not None:
        record['query_revision'] = query_revision
    if feed_url is not None:
        record['feed_url'] = redact_userinfo(feed_url)
    if reported_title is not None:
        record['reported_title'] = reported_title
    if reported_publication is not None:
        record['reported_publication'] = reported_publication
    return validate_shape(record)


def build_item(*, outlet_id, canonical_url, url_aliases, first_seen_at, recorded_at,
               content_type='news_article', current_version_id=None):
    """Item keyed on (outlet, canonical url): provider overlap dedups here."""
    canonical_url = redact_userinfo(canonical_url)
    aliases = list(dict.fromkeys(redact_userinfo(alias) for alias in url_aliases))  # dedupe, preserve order
    if canonical_url in aliases:
        aliases.remove(canonical_url)
    record = {
        'kind': 'item',
        'id': item_id_for(outlet_id, canonical_url),
        'recorded_at': recorded_at,
        'canonical_url': canonical_url,
        'url_aliases': aliases,
        'content_type': content_type,
        'first_seen_at': first_seen_at,
    }
    if outlet_id is not None:
        record['outlet_id'] = outlet_id
    if current_version_id is not None:
        record['current_version_id'] = current_version_id
    return validate_shape(record)
