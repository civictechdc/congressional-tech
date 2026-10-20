"""Media Cloud adapter (offline skeleton): fixture response JSON -> records.

No live calls; live HTTP wiring stays deferred (P5/P1 skeleton). Same C1-C3
discipline as the other adapters: shared item/outlet namespaces make provider
overlap dedup at the item level, while each page fetch is its own capture and
therefore its own discovery (C2).

Publication (C3): Media Cloud reports `publish_date` per story, in UTC per
its API contract. A timestamp is kept as an instant (basis provider — the
timezone comes from the provider contract, not invented here); a date-only
value, or a naive timestamp at exactly midnight, degrades to day precision;
anything absent or unparseable stays unknown. The `next` page token becomes
the checkpoint reference; a page with no token closes the window.
"""
import json
import re
from datetime import date, datetime, time, timezone

from news_lake.adapters.common import (
    FetchOutcome,
    build_capture,
    build_discovery,
    build_item,
    item_id_for,
    outlet_for_domain,
    publication_day,
    publication_instant,
)
from news_lake.adapters.cursors import Page
from news_lake.adapters.urls import host_of, normalize_url, outlet_domain
from news_lake.context import AdapterContext, adapter_namespace
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('adapter:mediacloud')
PROVIDER = 'mediacloud'
_DATE_ONLY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def parse_publish_date(raw):
    """provider-reported publication -> precision dict, or None (unknown)."""
    if not raw:
        return None
    raw = raw.strip()
    if _DATE_ONLY.match(raw):
        try:
            return publication_day(date.fromisoformat(raw))
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if parsed.time() == time(0, 0):
            # Midnight is the invented time of a date-only value: keep the day.
            return publication_day(parsed.date())
        parsed = parsed.replace(tzinfo=timezone.utc)  # Media Cloud stores UTC
    return publication_instant(parsed)


class MediaCloudAdapter:
    def __init__(self, context=None, query_revision='api-v2:default'):
        self.context = context if context is not None else AdapterContext()
        self.query_revision = query_revision

    def parse_page(self, fetch, *, window_end, mode='backfill', capture_id=None, next_token=None):
        """One page fetch -> Page(records, checkpoint).

        Raises on a malformed story (missing url and similar): the page is not
        consumable and its checkpoint must not advance.
        """
        if not isinstance(fetch, FetchOutcome):
            raise TypeError('parse_page takes a FetchOutcome; live HTTP wiring is deferred')
        capture = build_capture(self.context, PROVIDER, fetch, capture_id=capture_id)
        if capture['status'] != 'succeeded' or fetch.metadata_only:
            # Failed, not-modified, or metadata-only page: capture evidence only.
            return Page([capture])
        document = json.loads(fetch.body.decode('utf-8'))
        stories = document.get('stories') if isinstance(document, dict) else document
        if not isinstance(stories, list):
            raise ValueError('unexpected Media Cloud response shape')
        recorded_at = capture['observed_at']
        outlets, items, discoveries, seen = {}, {}, [], set()
        for story in stories:
            url = story.get('url')
            if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
                raise ValueError(f'Media Cloud story without a usable url: {story!r}')
            domain = outlet_domain(host_of(url))
            outlet = outlets.setdefault(domain, outlet_for_domain(domain, recorded_at))
            canonical = normalize_url(url)
            item_id = item_id_for(outlet['id'], canonical)
            if item_id not in items:
                items[item_id] = build_item(
                    outlet_id=outlet['id'],
                    canonical_url=canonical,
                    url_aliases=[],
                    first_seen_at=capture['observed_at'],
                    recorded_at=recorded_at,
                )
            title = (story.get('title') or '').strip() or None
            discovery = build_discovery(
                capture=capture,
                item_id=item_id,
                provider=PROVIDER,
                url=url,
                observed_at=capture['observed_at'],
                recorded_at=recorded_at,
                mode=mode,
                external_id=str(story['stories_id']) if story.get('stories_id') is not None else None,
                query_revision=self.query_revision,
                reported_title=title,
                reported_publication=parse_publish_date(story.get('publish_date')),
            )
            if discovery['id'] not in seen:
                seen.add(discovery['id'])
                discoveries.append(discovery)
        records = [*outlets.values(), capture, *discoveries, *items.values()]
        for record in records:
            validate_shape(record)
        token = next_token if next_token is not None else (document.get('next') if isinstance(document, dict) else None)
        if token:
            checkpoint_ref = f'urn:news-lake:mediacloud:{self.query_revision}:next:{token}'
        else:
            checkpoint_ref = f'urn:news-lake:mediacloud:{self.query_revision}:window:{window_end}'
        return Page(records, checkpoint_ref=checkpoint_ref, completed_until=window_end)
