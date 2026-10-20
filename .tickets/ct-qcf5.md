---
id: ct-qcf5
status: closed
deps: []
links: []
created: 2026-10-20T16:52:07Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, adapters, rss, gdelt, mediacloud]
---
# Fix adapter redirect folding, subdomain outlets, date parsing, and HTML extraction

Multiple adapter edge cases violate C1-C4 or break cross-provider deduplication:
1. adapters/rss.py:166, 174 (_FeedItems.add) populates existing['urls'] with normalized redirect URLs but never reads existing['urls'] on lookup, so a second entry in the feed (or a subsequent poll) whose link matches an earlier entry's redirect URL fails to fold into the same item. Also, if the first entry for a duplicate URL lacks a title/body while the second entry has one, the second entry's state is discarded.
2. adapters/rss.py:307-311 derives outlet domain from parsed.feed.link (which may be a root domain, feed host, or relative path) while GdeltAdapter (gdelt.py:64) and MediaCloudAdapter (mediacloud.py:82) derive outlet domain from host_of(article_url). When articles live on a subdomain (e.g. news.example.com) while feed.link is www.example.com, RSS and GDELT/MediaCloud compute different outlet_ids and thus different item_ids.
3. adapters/rss.py:58-90 (_TextExtractor) joins every handle_data chunk with ' ', inserting spurious spaces around inline tags adjacent to punctuation or inside words (<a href='...'>Alex Doe</a>, Jr. -> 'Alex Doe , Jr.', <em>Pol</em>itics -> 'Pol itics').
4. adapters/rss.py:92-117 (publication_from_feed) does not parse ISO-8601 / RFC 3339 timestamps (Atom <published>/<updated> and dc:date), degrading all Atom dates to unknown; adapters/mediacloud.py:44-45 calls date.fromisoformat(raw) outside try/except ValueError (crashing on '0000-00-00' or '2026-02-30') and stamps naive 'YYYY-MM-DD 00:00:00' strings as UTC instants; adapters/common.py hardcodes basis='provider' everywhere with no support for basis='publisher'.
5. adapters/urls.py:17-22 (host_of) uses netloc.split(':', 1)[0] instead of urlsplit(url).hostname, breaking IPv6 literals ('[') and leaving trailing dots on FQDNs.

## Design

1. In _FeedItems.add, index all normalized redirect URLs in a lookup map -> item_id so redirect variants within a feed fold into one item, and backfill missing title/html/publication from later duplicate entries when the first entry lacked them.
2. Normalize outlet domain derivation across RSS, GDELT, and MediaCloud (falling back safely when feed.link is missing/relative, and reconciling same-publisher article subdomains) and use urlsplit(url).hostname.rstrip('.') in host_of.
3. In _TextExtractor, concatenate inline character data without injecting spaces mid-token while separating block-level elements with whitespace, then collapse whitespace.
4. Support ISO-8601 timestamps in publication_from_feed, wrap date.fromisoformat in try/except ValueError in mediacloud.parse_publish_date (and degrade midnight-invented or naive date strings appropriately), and support basis='publisher' vs 'provider'.

## Acceptance Criteria

- Two RSS entries where one links to the canonical URL and the other links to a same-publisher redirect URL fold into one item; if the first duplicate lacked a title and the second has one, a version is still extracted.
- Atom/ISO-8601 feed timestamps parse to instant/day precision instead of unknown; Media Cloud invalid dates ('0000-00-00', '2026-02-30') degrade to None (unknown) without raising ValueError.
- Inline HTML tags (<a href='x'>Alex Doe</a>, Jr. and <em>Pol</em>itics) extract without artificial spaces inside words or before punctuation.
- host_of handles IPv6 URLs and trailing-dot FQDNs cleanly.


## Notes

**2026-10-20T17:30:52Z**

RSS redirect-URL index folds later duplicates and backfills missing title/body; bounded subdomain outlet normalization reconciles RSS/GDELT/Media Cloud; inline HTML no longer inserts spaces; RFC 2822/ISO-8601/Atom dates parse with publisher basis; Media Cloud invalid/midnight-naive dates handled; host_of uses urlsplit. Adapter suites pass.
