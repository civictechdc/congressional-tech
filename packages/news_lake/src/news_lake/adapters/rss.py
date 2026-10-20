"""RSS adapter: an offline pipeline from fixture feed bytes to contract records.

capture -> discovery -> item -> version, plus the extraction run. IDs are
deterministic: items derive from (outlet, canonical url) and discoveries from
(capture, provider, external id or url) under shared documented namespaces, so
replaying one captured result reuses every id while a new successful poll is a
new observation (C2). Capture ids are minted per fetch attempt by the caller's
id source; cross-crash stability comes from the storage journal (slice 2).

Live HTTP wiring stays deferred: callers hand over FetchOutcome objects. The
default text processor is a minimal stdlib HTML->text extractor, documented as
a placeholder — the packet defers the live extractor choice. Extraction runs
over the HTML the feed itself carries (content:encoded / summary); fetching
article pages is part of the deferred live wiring.
"""
import email.utils
import re
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser

import feedparser

from news_lake.adapters.common import (
    FetchOutcome,
    build_capture,
    build_discovery,
    item_id_for,
    outlet_for_domain,
    publication_day,
    publication_instant,
    publication_unknown,
)
from news_lake.adapters.urls import (
    host_of,
    normalize_url,
    outlet_domain,
    redact_userinfo,
    same_publisher,
)
from news_lake.context import AdapterContext, adapter_namespace, build_run, named_id
from news_lake.contract.records import validate_shape

NAMESPACE = adapter_namespace('adapter:rss')
PROVIDER = 'rss'
PROCESSOR = 'extract'
PROCESSOR_VERSION = 'stdlib-html-1'
EXTRACTOR_CONFIG = {
    'extractor': 'stdlib-html-text',
    'drop_tags': ['script', 'style'],
    'whitespace': 'collapse',
}

_DATE_ONLY_ISO = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_DATE_ONLY_RFC = re.compile(r'^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$')


class _TextExtractor(HTMLParser):
    """Minimal stdlib HTML->text: drop script/style, keep text, unescape entities.

    Inline tags contribute no whitespace, so '<em>Pol</em>itics' stays one
    token; block-level boundaries do, keeping separate blocks apart.
    """

    _SKIP = {'script', 'style'}
    _BLOCK = {
        'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'tr', 'td', 'th', 'section', 'article', 'header', 'footer',
        'blockquote', 'pre',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK and not self._skip:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK and not self._skip:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self._skip and data:
            self.parts.append(data)


def extract_text(html):
    """Placeholder default processor: strip tags, collapse whitespace.

    The packet defers the live extractor choice; this only guarantees a
    deterministic, honest baseline (it never fabricates content).
    """
    extractor = _TextExtractor()
    extractor.feed(html)
    return ' '.join(''.join(extractor.parts).split())


def publication_from_feed(raw):
    """C3 date policy for a feed-reported date, basis publisher.

    RFC 2822 and ISO-8601/RFC 3339 (Atom published/updated, dc:date) are
    recognized. time+timezone -> instant; date-only, or time without a
    timezone -> day (the date is known, the time is not verifiable, so it is
    dropped rather than frozen at an invented midnight); absent/unparseable
    -> unknown.
    """
    if not raw:
        return publication_unknown()
    raw = raw.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None:
            return publication_instant(parsed, basis='publisher')
        return publication_day(parsed.date(), basis='publisher')
    if _DATE_ONLY_ISO.match(raw):
        try:
            return publication_day(date.fromisoformat(raw), basis='publisher')
        except ValueError:
            return publication_unknown()
    iso = raw[:-1] + '+00:00' if raw.endswith(('Z', 'z')) else raw
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None:
            return publication_instant(parsed, basis='publisher')
        return publication_day(parsed.date(), basis='publisher')
    try:
        if _DATE_ONLY_RFC.match(raw):
            return publication_day(datetime.strptime(raw, '%d %b %Y').date(), basis='publisher')
    except ValueError:
        return publication_unknown()
    return publication_unknown()


def _entry_html(entry):
    """The richest HTML the feed carries for an entry, or None."""
    content = entry.get('content')
    if content:
        return content[0].get('value')
    return entry.get('summary') or None


def _entry_title(entry):
    title = (entry.get('title') or '').strip()
    return title or None  # C4: titles are never fabricated


class _FeedItems:
    """Folds entries into items; duplicate/redirected URLs merge (C1)."""

    def __init__(self, outlet, first_seen_at, recorded_at):
        self.outlet = outlet
        self.first_seen_at = first_seen_at
        self.recorded_at = recorded_at
        self.by_id = {}  # item id -> {'item':…, 'urls': set, 'entry': winning entry}
        self.by_url = {}  # normalized url -> item id (primary + same-publisher redirects)
        self.order = []

    def add(self, entry, state=None):
        """Fold one entry; returns the item id (first entry wins)."""
        primary = entry.get('link')
        if not primary:
            return None
        primary = redact_userinfo(primary)
        canonical = normalize_url(primary)
        extras = [redact_userinfo(url) for url in self._redirect_urls(entry)]
        keys = [canonical, *(normalize_url(url) for url in extras)]
        item_id = next((self.by_url[key] for key in keys if key in self.by_url), None)
        if item_id is None:
            item_id = item_id_for(self.outlet['id'], canonical)
        incoming = state if state is not None else _entry_state(entry)
        existing = self.by_id.get(item_id)
        if existing is None:
            item = {
                'kind': 'item',
                'id': item_id,
                'recorded_at': self.recorded_at,
                'outlet_id': self.outlet['id'],
                'canonical_url': canonical,
                'url_aliases': [],
                'content_type': 'news_article',
                'first_seen_at': self.first_seen_at,
            }
            existing = {'item': item, 'urls': {canonical}, 'entry': incoming}
            self.by_id[item_id] = existing
            self.order.append(item_id)
        else:
            self._backfill(existing['entry'], incoming)
        # Every URL variant this entry carries resolves to the same item later.
        for key in keys:
            self.by_url.setdefault(key, item_id)
        existing['urls'].update(keys)
        # C1: originals that differ from the canonical form survive as aliases.
        aliases = existing['item']['url_aliases']
        canonical_url = existing['item']['canonical_url']
        for original in [primary, *extras]:
            if original != canonical_url and original not in aliases:
                aliases.append(original)
        return item_id

    @staticmethod
    def _backfill(existing, incoming):
        """Keep first-entry state, filling only fields the first entry lacked."""
        for field in ('title', 'html'):
            if not existing.get(field) and incoming.get(field):
                existing[field] = incoming[field]
        current = existing.get('publication') or {}
        replacement = incoming.get('publication') or {}
        if current.get('precision') == 'unknown' and replacement.get('precision') != 'unknown':
            existing['publication'] = replacement

    def _redirect_urls(self, entry):
        """Same-publisher permalink/guid/link URLs usable as redirect evidence.

        Only URLs on the outlet's own domains participate; a cross-domain
        canonical link never merges appearances (C1).
        """
        candidates = []
        entry_id = entry.get('id')
        if isinstance(entry_id, str) and entry_id.startswith(('http://', 'https://')):
            if same_publisher(entry_id, self.outlet['domains']):
                candidates.append(entry_id)
        for link in entry.get('links', []):
            href = link.get('href')
            if isinstance(href, str) and href.startswith(('http://', 'https://')):
                if same_publisher(href, self.outlet['domains']):
                    candidates.append(href)
        return candidates


def _entry_state(entry):
    return {
        'title': _entry_title(entry),
        'publication': publication_from_feed(entry.get('published') or entry.get('updated')),
        'html': _entry_html(entry),
        'external_id': _external_id(entry),
    }


def _external_id(entry):
    """An opaque (non-permalink) guid is a provider external id."""
    entry_id = entry.get('id')
    if isinstance(entry_id, str) and not entry_id.startswith(('http://', 'https://')) and entry_id.strip():
        return entry_id.strip()
    return None


class RssAdapter:
    """Turns fetched feed bytes into contract-valid records (offline)."""

    def __init__(self, context=None):
        self.context = context if context is not None else AdapterContext()

    def ingest(self, fetch, *, outlet=None, mode='live', capture_id=None):
        """One fetch attempt -> capture + (when parseable) content records."""
        if not isinstance(fetch, FetchOutcome):
            raise TypeError('ingest takes a FetchOutcome; live HTTP wiring is deferred')
        capture = build_capture(self.context, PROVIDER, fetch, capture_id=capture_id)
        if capture['status'] != 'succeeded':
            return [capture]
        parsed = feedparser.parse(fetch.body)
        if not parsed.entries:
            return [capture]

        recorded_at = capture['observed_at']
        outlet = outlet or self._derive_outlet(parsed, fetch, recorded_at)
        items = _FeedItems(outlet, capture['observed_at'], recorded_at)

        discoveries, seen = [], set()
        for entry in parsed.entries:
            state = _entry_state(entry)
            item_id = items.add(entry, state=state)
            if item_id is None:
                continue
            discovery = build_discovery(
                capture=capture,
                item_id=item_id,
                provider=PROVIDER,
                url=entry['link'],
                observed_at=capture['observed_at'],
                recorded_at=recorded_at,
                mode=mode,
                external_id=state['external_id'],
                feed_url=fetch.url,
                reported_title=state['title'],
                reported_publication=state['publication'],
            )
            if discovery['id'] not in seen:  # duplicate URLs: first observation wins
                seen.add(discovery['id'])
                discoveries.append(discovery)

        records = [outlet, capture, *discoveries]
        records.extend(state['item'] for state in items.by_id.values())
        records.extend(self._extract(capture, items, recorded_at, mode))
        for record in records:
            validate_shape(record)
        return records

    # -- extraction -----------------------------------------------------------

    def _extract(self, capture, items, recorded_at, mode):
        """One run for the capture; a version per titled item (C4)."""
        titled = [state for state in items.by_id.values() if state['entry']['title'] is not None]
        if not titled:
            return []
        run = build_run(
            NAMESPACE,
            self.context,
            processor=PROCESSOR,
            processor_version=PROCESSOR_VERSION,
            config=dict(EXTRACTOR_CONFIG),
            inputs=[{'kind': 'capture', 'id': capture['id']}],
            mode=mode,
        )
        records = [run]
        for state in titled:
            entry = state['entry']
            text = ''
            if capture['access'] in ('restricted', 'redistributable') and entry['html']:
                text = extract_text(entry['html'])
            version = {
                'kind': 'version',
                'id': named_id(NAMESPACE, f'version:{state["item"]["id"]}:{run["id"]}'),
                'recorded_at': recorded_at,
                'item_id': state['item']['id'],
                'capture_id': capture['id'],
                'run_id': run['id'],
                'title': entry['title'],
                'publication': entry['publication'],
                'access': 'metadata_only' if not text else capture['access'],
            }
            if text:
                version['text'] = text
                version['text_hash'] = sha256(text.encode('utf-8')).hexdigest()
                version['rights_basis'] = capture['rights_basis']
            state['item']['current_version_id'] = version['id']
            records.append(version)
        return records

    def _derive_outlet(self, parsed, fetch, recorded_at):
        link = (parsed.feed.get('link') or '').strip()
        domain = outlet_domain(host_of(link))
        if not domain:  # missing or relative feed link: use the fetched feed host
            domain = outlet_domain(host_of(fetch.url))
        name = (parsed.feed.get('title') or domain).strip()
        return outlet_for_domain(domain, recorded_at, name=name, feed_url=fetch.url)
