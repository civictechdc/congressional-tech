# Iceberg/Parquet recheck of the specs

## Scope and method

- **Reviewed:** commit `d9730967` ("apply the five final spec reviews"), against `c3b067c4`.
- **Evidence:**
  - the pinned Oct 19 snapshot, queried with DuckDB through `wt/ct-viewer-publish/.venv`;
  - parquet-rs 58.4 source;
  - docspec-rs `Cargo.lock`;
  - `congress_api/parsers/document_links.py`.
- **Scripts:** `ctx_mult.py` and `fold_pages.py` in the session scratchpad.

## Verdict

**Ready to build.** Nothing blocks.

Before S writes `url_key` in SQL, fix one rule in DM §7.2 (R1): spaces in URLs. Also fix two wordings (R2, R3).

## What landed (all correct)

| Item | Where |
|---|---|
| F1: recovery link keys hash the exact URL | DM §8.2 |
| F1: the `url_variants` step applies once, and a test rejects chained variants | DM §7.2 |
| F2: `good_fetch` is defined once | DM §7.3 |
| F2: `good_fetch` is used for recency, the queue and `linked_from` | §6.4 (and §6.5 by reference), §7.7, §7.10 |
| F2: `real_files` is `good_fetch` plus the body conditions | DM §7.3 |
| F3: the queue takes links from any good-fetched page except error pages | DM §7.7 |
| F3: the queue compares fetch rows' requested and final URLs, and invariant 12 matches | DM §7.7, §10 |
| P1/P2: `detail` has 65,536-row groups, a 1,024-row page limit and 1,024-value write batches; the 16 KB clause is gone | DM §8.1 |
| P1/P2: the reader caches each row group's offset index | A §10.1, plan A1 |
| P3: readings run sniff, then html/xml/json, then fingerprint, and the sniff version moves together with the format parsers | A §12, DM §6.2 |
| `base_href` and `href` as written replace `base_url`; the model resolves each link against every good-fetch context | DM §6.2, §7.2 |
| C8: generic RFC 3986 resolution and percent-decoding in the engine | A §13 item 8, plan C8 |
| Minors: the fingerprint sentence is deleted, newly crossing placeholders are reported, and `readings`' size with links is measured in D2 | DM §7.3, plan D2 |
| `edition_bodies` closes the re-packaged-copy path | DM §7.5, invariant 14 |

## The cost and shape of per-context link resolution

**Measured.**
- 214,041 HTML/XML bodies have a 2xx fetch.
- They sit at 277,642 distinct contexts: 1.30 per body on average.
- Only one body has more than 100 contexts (190); the next has 52.

So about 4.2M links become about 5.5M resolved targets (est.). Resolving is effectively linear in links, and nothing blows up.

**Plan shape that keeps memory bounded:**
1. Build `contexts(page_sha, context)` from `good_fetch`: about 278k rows, small. This is the build side.
2. Probe it with the unnested links: 4.2M rows of `(page_sha, link_index, href, group_path)`.
3. Resolve with C8, then compute `url_key`.
4. Join to the source endpoints' `url_key` (1.31M) as the build side.
5. For `linked_from`, hash-aggregate to the earliest `(order key, page_sha, link_index)` per occurrence endpoint.
6. Only then re-attach `text`, `doc_type` and `add_date`.
7. For the queue, apply the capture-scope filter and dedupe by `url_key` first. Then anti-join with the filtered candidates as the build side, not the roughly 2–3M distinct fetch URLs.

That is about 12M UDF calls per publish across all `url_key` uses: seconds. M2 reports the build sizes.

**Not worth doing:** resolving absolute `href`s once instead of per context. At 1.30 contexts per page, it saves little and adds a branch.

## Findings

### R1. Spaces in URLs: the engine's link resolution must agree with how the fetcher resolved them (should fix in DM §7.2)

**How every historical `requested_url` was produced.** Today's fetcher uses `http_url` (`parsers/document_links.py:66-95`):
- Python `urljoin`;
- strip surrounding spaces;
- keep internal raw spaces;
- drop the fragment;
- remove dot segments;
- IDNA-encode the host;
- reject control characters, userinfo and non-HTTP schemes.

**Measured in the snapshot:** 2,408 captured URLs contain a raw space, and 18,825 contain `%20`.

**Why it matters.** The two kinds of resolver treat spaces differently:
- a WHATWG resolver, such as the `url` crate, encodes spaces as `%20`;
- RFC 3986 calls spaces invalid.

`url_key` decodes only unreserved escapes, and a space is not unreserved. So `a b.pdf` and `a%20b.pdf` get different keys. The result:
- `linked_from` misses those files;
- the queue requests each one again under the second spelling. That costs a wasted fetch (the 412 means no new storage), plus an extra source file and occurrence. Same-body edges keep it in the same document.

**Fix:**
- **`url_key`:** normalize percent-encoding fully, as in RFC 3986 §6.2.2:
  - uppercase the hex digits of escapes;
  - decode unreserved characters;
  - encode a space and any other character outside the URI character set as `%XX`.
- **C8's test vectors:** add golden vectors from today's `http_url` (surrounding and internal spaces, dot segments, fragments, IDNA hosts) beside RFC 3986 §5.4.
- **Policy:** the filters (HTTP(S) only, no userinfo, no control characters) belong in SQL, not in the engine function.
- **Libraries:** build C8 on the `url` 2.5.8 and `percent-encoding` 2.3.2 crates already in docspec-rs's lockfile, and check them against both vector sets.

### R2. Who ingests captures (wording)

- A §12 says: "Captures are ingested only by publish, so nothing lands between the lake steps and the pin."
- A §8.2 still has the weekly check append late receipts.

Both statements are compatible, because publish and the weekly job share one concurrency group. Say "only by publish and the weekly check, which never overlap".

### R3. `detail` per-view bytes (estimate)

- **What changed.** The 64 KB page-size clause went out with the 16 KB one, so string and fold leaves now page at the parquet-rs default of 1 MiB (`DEFAULT_PAGE_SIZE`). In practice, every leaf pages at 1,024 rows.
- **The estimate.** A view then reads about (file size × 1,024 ÷ rows) = 55–70 MB × 1,024 ÷ 0.65M ≈ **87–110 KB**, not 70–90 KB.
- **Fix:** either correct the figure, or restore a 64 KB data-page size limit. That limit binds only on string and fold leaves; the row limit governs the fixed-width keys. There is no byte budget (decision 35), so either is fine. F0 measures.
- **`occurrences`.** It is 8–12 MB at 1.7M rows, so a range read is a few KB per column; nothing changes.

### Minor

**DM §7.1, "a new `captures` table" when the ingest mapping changes.**
- Say how the new table is named, for example `captures_<mapping version>`, and named by the profile.
- Say when the old table is dropped.
- Basin's `DROP TABLE` purge behavior is undocumented, so confirm it in M1 before relying on it.

## Unchanged and still fine

- **Lake:** the table properties with three bounded retries, and the completeness gate.
- **Input identity:** with `base_url` gone, every reading is now body-intrinsic, which closes the rebuild nuance I raised in the last round.
- **Release writer settings:** `list`, `links`, `recoveries` and `meetings` are unchanged, and `meetings` is read once per session.
- **Data checks:** all 24 older-body ETags are plain MD5, and the same 18 placeholders appear either way.
