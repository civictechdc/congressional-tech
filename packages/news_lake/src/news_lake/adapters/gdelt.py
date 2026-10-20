"""GDELT adapter (offline skeleton): fixture response JSON -> records.

No live calls; live HTTP wiring stays deferred (P5/P1 skeleton). Honors C1-C3
exactly like the RSS adapter: URLs are normalized only by lowercasing
scheme/host and stripping the fragment with originals preserved as aliases,
and duplicate/redirected URLs fold into one item per (outlet, canonical url)
under the shared item namespace, so overlap with other providers dedups at
the item level while each provider's discovery remains its own observation.

Publication (C3): the GDELT DOC API exposes no article publication time — its
`seendate` is when GDELT acquired the document, and acquisition timestamps
MUST NOT substitute for publication time. GDELT items therefore record no
reported_publication (absent means unknown), never an invented one.
"""
import json

from news_lake.adapters.common import (
    FetchOutcome,
    build_capture,
    build_discovery,
    build_item,
    item_id_for,
    outlet_for_domain,
)
from news_lake.adapters.cursors import Page
from news_lake.adapters.urls import (
    host_of,
    normalize_url,
    outlet_domain,
    redact_userinfo,
    same_publisher,
)
from news_lake.context import AdapterContext, adapter_namespace
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('adapter:gdelt')
PROVIDER = 'gdelt'


class GdeltAdapter:
    def __init__(self, context=None, query_revision='doc-2.0:default'):
        self.context = context if context is not None else AdapterContext()
        self.query_revision = query_revision

    def parse_page(self, fetch, *, window_end, mode='backfill', capture_id=None):
        """One page fetch -> Page(records, checkpoint).

        Raises on a malformed page (missing url and similar): the page is not
        consumable, its checkpoint must not advance, and nothing commits.
        """
        if not isinstance(fetch, FetchOutcome):
            raise TypeError('parse_page takes a FetchOutcome; live HTTP wiring is deferred')
        capture = build_capture(self.context, PROVIDER, fetch, capture_id=capture_id)
        if capture['status'] != 'succeeded' or fetch.metadata_only:
            # Failed, not-modified, or metadata-only page: capture evidence only.
            return Page([capture])
        articles = self._load(fetch.body)
        recorded_at = capture['observed_at']
        outlets, items, discoveries, seen = {}, {}, [], set()
        for article in articles:
            url = article.get('url')
            if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
                raise ValueError(f'GDELT article without a usable url: {article!r}')
            domain = outlet_domain(host_of(url))
            outlet = outlets.setdefault(domain, outlet_for_domain(
                domain, recorded_at, name=article.get('domain') or domain))
            canonical = normalize_url(url)
            item_id = item_id_for(outlet['id'], canonical)
            aliases = []
            mobile = article.get('url_mobile')
            if isinstance(mobile, str) and mobile.startswith(('http://', 'https://')):
                mobile = redact_userinfo(mobile)
                if same_publisher(mobile, outlet['domains']) and mobile != canonical:
                    aliases.append(mobile)
            item = items.get(item_id)
            if item is None:
                item = build_item(
                    outlet_id=outlet['id'],
                    canonical_url=canonical,
                    url_aliases=aliases,
                    first_seen_at=capture['observed_at'],
                    recorded_at=recorded_at,
                )
                items[item_id] = item
            else:
                for alias in aliases:  # same item seen again: keep alias evidence
                    if alias not in item['url_aliases']:
                        item['url_aliases'].append(alias)
            title = (article.get('title') or '').strip() or None
            discovery = build_discovery(
                capture=capture,
                item_id=item_id,
                provider=PROVIDER,
                url=url,
                observed_at=capture['observed_at'],
                recorded_at=recorded_at,
                mode=mode,
                query_revision=self.query_revision,
                reported_title=title,
            )
            if discovery['id'] not in seen:
                seen.add(discovery['id'])
                discoveries.append(discovery)
        records = [*outlets.values(), capture, *discoveries, *items.values()]
        for record in records:
            validate_shape(record)
        return Page(
            records,
            checkpoint_ref=f'urn:news-lake:gdelt:{self.query_revision}:window:{window_end}',
            completed_until=window_end,
        )

    @staticmethod
    def _load(body):
        document = json.loads(body.decode('utf-8'))
        articles = document.get('articles') if isinstance(document, dict) else document
        if not isinstance(articles, list):
            raise ValueError('unexpected GDELT response shape')
        return articles
