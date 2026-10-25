# CS 300 recheck: the specification set at d9730967

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-25.
Rechecked at `d9730967` against `c3b067c4`: *Architecture* (**A §n**), *Data Model* (**DM §n**),
*Implementation Plan* (**P §n**); the diff is saved beside this file. Measurements ran on the
read-only Oct 19 snapshot through the project venv (`prof3_spotchecks.py`,
`prof3_detail_view.py`; the Parquet files re-read were built in earlier passes). No network.

## Verdict

**Ready to build from, with one line to restore.** My must-fix (a reading's resolved links
depended on a mutable input) is fixed the way I asked: hrefs are stored as written and the model
resolves them, with the resolution primitives added to the engine as generic RFC 3986 functions.
Seven of my eight nice-to-haves landed; the eighth (a one-clause note in DM §6) is still open
and still minor. The edits are correct and linear. One edit regressed a number I had verified:
`detail`'s writer settings dropped the 16 KB / 64 KB page-size caps and kept only the 1,024-row
limit, which raises the per-view estimate from ≈49 KB to ≈110 KB while the text still says
70–90 KB.

**Grades.** Architecture **A (93)**, unchanged. Plan **A (93)**, +1 from A− (92).

## 1. My must-fix and nice-to-haves

| Item | Verdict | Where |
|---|---|---|
| **`base_url` dependence (must-fix)** | **Landed, as asked.** `base_href` is stored as written and each link's `href` as written; "A reading depends only on its body and its parser version"; the model resolves each `href` by RFC 3986 §5 against `base_href` when present, else against each context the page body was good-fetched at (URL for a top-level page, member path for an archive member). Invariant 1's re-run test is now provable. | DM §6.2 (`base_href`, `links[].href`, the new sentence); DM §7.2 "Link targets"; A §8.3; A §13.8 and P §6.3 C8 (generic URL functions) |
| Fingerprint pass vs. the pin: say which happens | Landed by removing the race rather than describing it: captures are ingested only by publish, so nothing lands between the lake steps and the pin; the "one run later" sentence is gone. | A §12 "Order"; DM §7.3 |
| `captures` ingest version in the profile; a fix is a new table | Landed. | DM §7.1 |
| `url_variants` recursion | Landed: applied once, and a test rejects a canonical URL that is itself a variant. | DM §7.2 |
| `link_url_key`'s frozen registry versions | Landed by a better design: link URL keys hash the exact `original_url`, so no registry or provenance change moves a published key; two spellings give two keys that open the same row. | DM §8.2; DM §7.2 (link URL keys MUST NOT use `url_key`) |
| DM §6 should carry the caps clause itself | **Not landed.** DM §6 still states the row-group sizes unconditionally; the condition lives only in P §5.1 M1.3. Minor. | — |
| `meetings.parquet` once per session | Landed as a reader MUST. | A §11.6 |
| Queue and a redirect's final URL | Landed, and better: the queue matches both the requested and the final URL of any fetch row, and recovery imports never hide an unfetched URL. | DM §7.7; invariant 12 |

## 2. The edits

### 2.1 Link resolution against every good-fetch context (DM §7.2)

**Correctness.** Resolving each `href` against the page's `<base href>` when present, else against
every context the body was good-fetched at, is the right reading of the data: a mirrored page
without a base legitimately links to each mirror's siblings, and an archive member's relative
links become endpoints in its own container. The model, not the lake, does it, so readings stay
pure functions of body and version.

**Big O.** The expansion is per distinct (body, context) pair, not per fetch. Measured on the
2xx HTML and XML bodies: **214,010 bodies, 277,202 pairs, a factor of 1.295**; the largest body
has 148 contexts (a GPO page returned for many bill-XML URLs), the 99.9th percentile is 3, and
only one body exceeds 100 contexts. Absolute hrefs collapse to one target after `url_key`, so
the real factor is below 1.3. With ≈4.2M links (the owner's estimate from 80 bodies) the work is
≈5.4M resolutions and `url_key`s per run: linear, tens of seconds, named in principle 4. The
engine's RFC 3986 functions (A §13.8) are the right boundary: resolution and percent-decoding
are generic; the host, `www.`, strip-list and wrapper rules stay in SQL and registries.

**Do the joins reduce first?** Yes. The queue groups targets by `url_key` ("one row per
`url_key`, under its byte-wise least target") before its anti-join against the requested and
final URLs of fetch rows (DM §7.7). `linked_from` reduces each page body to its first good fetch
before joining, so the join grows with links, not fetches (DM §7.10). Endpoint matching compares
`(url_key(context_url), member_path)` on both sides, a hash join. One clarification is worth a
clause: a target that resolves to a member path is an endpoint, not a URL, so the queue (which
fetches) should consider URL targets only; the capture-scope registry will exclude it in
practice, but say so.

### 2.2 `edition_bodies` (DM §7.5)

`ambiguous_bodies` plus every real body whose fingerprint equals one of theirs, excluded from
all rendition edges. This closes the hole I would have raised next: a re-packaged copy of a
contested edition at an uncontested endpoint could otherwise take a rendition edge and merge two
editions through a shared XML. Null fingerprints never match, so the closure cannot over-reach.
Computation: one group-by over endpoints, one join by fingerprint, linear. Invariant 14 and A
§9.3 match the definition.

### 2.3 Review precedence (DM §7.9)

Every remaining `duplicate_of` is an edge before grouping, so no requested merge is lost; `hide`
and the overrides apply after grouping, latest by `(decided_at, id)` among records that target
any of the document's link keys. Deterministic, and the fixtures in S now include two active
merges on one document and two merged documents with different title overrides (P §5.3).

### 2.4 The queue (DM §7.7)

Resolved targets from good-fetched pages whose role is not `error_response`, in the
capture-scope registry, whose `url_key` matches neither the requested nor the final URL of any
`mode = fetch` row; one row per `url_key`; recomputed each run from readings, never stored.
O(targets + URLs). Listing pages and metadata records feed it, which is how hearing documents
are discovered. The 16,753 waiting URLs cannot be reproduced from the snapshot (links are not in
it); my estimate from today's occurrences was 19,971 before the scope filter, the same
magnitude.

### 2.5 `detail`: 65,536-row groups and the per-view cost (DM §8.1)

The row groups are a good change: the reader fetches the offset index of the row groups it
needs (A §10.1), about 19 leaves × 64 pages × 16 B ≈ 20 KB per row group instead of one index
for the file. But the writer settings now read "65,536-row groups; an offset index, a 1,024-row
page limit and 1,024-value write batches on every leaf" and no longer name page sizes, so the
engine's default data-page size (1 MiB) applies. For the fold's value leaf that matters: 1,024
rows are ≈337 KB uncompressed, well under 1 MiB, so a page holds all 1,024 rows and a point
read costs ≈56 KB for that leaf alone, against ≈11 KB with the 64 KB cap. Recomputed from my
files: **≈49 KB per view under c3b067c4's settings, ≈110 KB under d9730967's**, while DM §8.1
and A §16.1 still say 70–90 KB. Restore "16 KB pages for `link_key`, `saved_body` and
`alternates.body`, 64 KB for the rest" beside the row limit, or restate the cost as about
110 KB. One line either way; the profile pins it, so decide before F0.

### 2.6 Occurrences at 1,695,040 rows (DM §7.10)

The new grain is one row per distinct `(source_id, member_path)` of a listed document's
members. 1,695,040 is 1,683,430 source files plus 11,610 extra member paths; I could not
reproduce it exactly without the effective-filename rule (my body-level count is 1,423,033
distinct `(body, context, member_path)`), but the magnitude and the direction are right, and the
**largest document has exactly 455** distinct source files (measured; the 99.9th percentile is
7), matching the text. 8–12 MB scales from my 22.7 MB at 4.7M rows. M2 now runs the 1.7M
occurrences (P §5.2).

### 2.7 Other edits

- A §7.1's write steps (run set → one HEAD on `…/<sha>.gz` → create-only PUT, 412 ⇒ `unchanged`
  with suffix `''`) are now unambiguous and consistent with `stored_suffix` and invariant 3.
- A §9.2 adds "not a placeholder" to the prose definition, matching DM §7.3.
- `good_fetch` as a named CTE (DM §7.3) and "the reading is missing or not completed" close the
  gap where a parsed format without a reading could have been a real file; DM §6.4's current
  record uses the same definition.
- `recovery order` gains the import row's receipt key as a tie-break (DM §7.5), so two
  recoveries equal in kind, time and body are ordered.
- `suffix(body)` is now one rule for saved files, alternates and recoveries (DM §7.5).
- A new sniff version re-reading 1.04M bodies "can change the format parsers' work lists, so
  the profile moves them together" (DM §6.2): correct, and a trap avoided.
- Date labels and the hearing filter moved to a reader section (A §11.6) with MUSTs: one home.
- B14 now says 64 URLs by the index with two decided by receipts, and defines "no complete 2xx
  copy" precisely (P §6.2).
- The engine's remote caps are to be removed in C0 "unless M1 keeps them" (P §6.3), consistent
  with M1.3.
- Uploads about 95 MB (A §16.1): list 2–3 + detail 55–70 + links 7–9 + occurrences 8–12 +
  recoveries 1–3 + meetings 1–2 + url_state 10 = 84–109 MB; 0.7 GB a week follows.

Nothing superlinear and nothing growing with history was introduced; the per-context resolution
is the only new multiplier and it is 1.3× (measured).

## 3. Spot-checks

| Claim | Where | Result | Status |
|---|---|---|---|
| 1,695,040 occurrences at the new grain | DM §7.10; P §5.2 "1.7M" | 1,683,430 source files + extra member paths; body-level count 1,423,033 | consistent in magnitude; taken |
| The largest document has 455 occurrences | DM §7.10 | 455 distinct source files in the largest document; p99.9 = 7 | **measured**, exact |
| 64 cut-off URLs with no complete 2xx copy | P §6.2 B14 | 64 (207 URLs have a cut-off body) | measured, exact |
| Link resolution against every context stays linear | DM §7.2 | 277,202 pairs / 214,010 bodies = 1.295; max 148; p99.9 = 3 | measured |
| 1.31M source URLs | P §5.2 | 1,313,678 | measured, exact |
| 1,158,426 `url_state` rows plus the queue | DM §7.7 | 1,158,426 requested URLs | measured, exact |
| 16,753 queued URLs | DM §7.7 | 19,971 unfetched link keys from old occurrences, before the scope filter | estimated; same magnitude |
| 287,765 bodies the server labels HTML or XML; 4.2M links | DM §6.2; P §6.4 | 287,765 exact; links from the owner's 80-body sample | measured / taken |
| `detail` 55–70 MB; 70–90 KB per view | DM §8.1; A §16.1 | ≈65 MB; ≈49 KB with page-size caps, ≈110 KB without them | estimated; **the per-view figure no longer matches the settings** (§2.5) |
| Occurrences 8–12 MB | DM §8.1 | 22.7 MB at 4.7M rows → ≈8 MB at 1.7M | estimated, consistent |
| Uploads about 95 MB; 0.7 GB a week | A §16.1, §10.3.7 | 84–109 MB; 7 × 95 MB | derived |
| 18 placeholders at *k* = 100; 34,000 HTML archive members; 148 / 297 / 1.4 GB | DM §7.3, §6.2 | unchanged from earlier passes | taken (measured earlier) |

## 4. Remaining items

1. **must-fix (one line).** DM §8.1 `detail` writer settings: restore the page-size caps (16 KB
   for `link_key`, `saved_body`, `alternates.body`; 64 KB for the rest) beside the 1,024-row
   limit, or restate the per-view cost in DM §8.1 and A §16.1 as about 110 KB.
2. nice-to-have — DM §6: one clause that the row-group sizes assume the engine's remote write
   caps go (P §5.1 M1.3 says it; the data model should too).
3. nice-to-have — DM §7.7: the queue considers URL targets only; a target that resolves to a
   member path is an endpoint inside a container, not something capture can fetch.
4. nice-to-have — DM §7.2: say that resolution is per distinct `(body, context)` pair (it is
   implied); the measured factor of 1.3 is worth recording in §5 or §16 as the sizing number for
   the link join.

## 5. Grades and verdict

**Architecture: A (93), unchanged.** The must-fix closed cleanly and moved the right primitive
into the engine; `edition_bodies`, `good_fetch`, the review precedence and the queue's
requested-or-final match are each a correctness improvement; every new cost is linear and named.
A one-line regression in `detail`'s writer settings keeps it from moving up.

**Plan: A (93), +1.** M2 now exercises `url_key`, link resolution and the link join on sampled
links and the real 1.7M occurrences; S's fixtures cover the cases the new rules were written
for (contested editions through re-packaged copies, relative links inside archives, listing
pages captured twice, two active merges); B14 is exact; C8 gives the URL functions conformance
vectors; D2 measures the readings table with links. Nothing of the order changed, and nothing
needed to.

**Verdict: ready to build from.** Restore the `detail` page-size caps (or the number) when the
profile is first written; the three clarifications can land as the sections are touched.
