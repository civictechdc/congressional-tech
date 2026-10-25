# Final Iceberg/Parquet review of the specs

## Scope and method

- **Reviewed:** commit `c3b067c4` ("give each spec rule one home and apply the final reviews"):
  - `docs/engine-first-architecture.md`;
  - `docs/engine-first-data-model.md`;
  - `docs/plans/simplification-plan-20261024.md`.
- **Lens:** Iceberg, Parquet and query plans, plus a check that W1–W8 and the owner decisions (items 62–69) were applied as decided.
- **Evidence:**
  - the pinned Oct 19 snapshot, queried with DuckDB through `wt/ct-viewer-publish/.venv`;
  - 24 read-only HEADs of older bodies on the public `r2.dev` origin.
- **Scripts:** `final_checks.py` in the session scratchpad.

## Verdict

**Ready to build.** Everything from the W-review landed as decided:
- links on the HTML/XML readings, with `group_path` and `base_url`;
- the `.gz` existence check, plus `stored_suffix` on every capture;
- `.pdf` keys from verification records;
- the lake table properties, with C0 stopping the `gc.enabled` reset;
- B13 before B10, with B10 skipping verified keys;
- the queue of linked-but-unfetched URLs;
- `recoveries.parquet`, with `rec_start`/`rec_len` (detail is now 19 leaves, which I counted);
- every W8 minor.

The "one home per rule" restructure reads well. The architecture now cites the data model instead of restating it.

**Checked and fine:**
- Invariant 2 forbids multipart ETags. Older bodies satisfy it: I HEADed 24 of them in four size bands, up to more than 100 MB, and all have plain MD5 ETags.
- The 18 placeholder bodies are the same whether URLs are counted exactly or normalized. They are captions, playlists and small HTML; the largest is 341 KB.

Three rules still need a wording fix before E1 is written. None needs an owner decision.

## Findings

### F1. Recovery link keys can still move (medium)

DM §8.2 keys a recovery's original link on `link_url_key(original_url)`: `url_key` under the registry versions fixed when link keys were first published. This has two problems.

- **Moving keys.** `url_key`'s last step consults provenance `url_variants` (DM §7.2). That is not a registry and is not pinned, so a new variant record changes an already-published key, and a shared recovery link stops resolving.
- **Complexity.** Every model profile must carry two versions of two registries forever: the old ones for keys, the current ones for joins.

**Fix:** key on the exact original URL, `sha256('url:' || original_url)`.
- Attachment still matches on `url_key`, so nothing else changes.
- Two spellings of one link get two keys, and both resolve to the same row (`links` already maps many keys to one row).
- The key never moves, and the pinned old registry versions go away.

Also, make `url_key`'s variant step apply once, and add a test that no canonical URL is itself a variant. As written, `url_key(canonical_url)` can recurse.

### F2. "Real fetch" is used for bodies that are never real files (medium)

Three rules pick a fetch by "real fetch":
- **DM §6.4 and §6.5:** the current committee or meeting record is the one "whose latest real fetch is newest";
- **DM §7.10:** `linked_from` reduces each linking page "to its first real fetch".

Read literally, a real fetch is a `real_files` row, and these bodies never are one:
- API responses get the `api` role;
- listing pages get the `listing` role.

So committee names, meeting titles and almost every "linked from" would come out empty.

**Fix:**
- Define `good_fetch := mode = 'fetch' and complete and outcome in ('stored','unchanged') and http_status between 200 and 299` once, in §7.3.
- Use it in those three places, and in `base_url`'s "first capture row".
- Write `real_files` as `good_fetch` plus the body conditions.

### F3. The capture queue skips House meeting XML (medium-low)

DM §7.7 queues child URLs from "the links of a real page or listing page". House meeting XML has the `source_record` role, so it is excluded. Yet it is the most structured list of hearing documents (`/committee-meeting/meeting-documents/meeting-document/files/file`), and `meeting_ref` already reads its links.

**Fix:**
- Queue from the links of any good-fetched page whose role is not `error_response`; the capture-scope registry already limits what is followed.
- Make invariant 12 match the rule: queue rows only where no capture row's requested URL shares the `url_key`. As written, the invariant says "URLs", while the rule compares `url_key`s.

### F4. Minor

1. **The fingerprint "one run later" sentence.** DM §7.3 says "A body that lands between the two gets its fingerprint one run later". It contradicts §7.1, under which publish refuses when a pinned version's work list is not empty. It also can't happen: publish is serialized, capture doesn't write the lake, and `fingerprint` runs last before the pin. Delete the sentence.

2. **Relative links on pages captured in several places.** 28,160 of 175,197 HTML bodies (16%) were captured at more than one directory. `base_url` resolves relative links against only the first capture URL, and "first" can change when a late receipt carries an earlier time.
   - Keep `href` as written beside `child_url` (cheap), so a later parser version can re-resolve without re-reading bodies.
   - Invariant 1's re-run uses the recorded `base_url`.
   - S's sample should include a listing page captured in two places.
   - Many of the 16% are probably shared error pages, which supply no links. That was not measured.

3. **Placeholders over time.** A real document mirrored at more than 100 URLs would silently stop being a real file, and its links would open the not-found notice (§8.2). Have the model report bodies that newly cross *k* in each release.

4. **`readings` size.** The figure of 16.5 MB "before links" needs a with-links estimate: about 4.2M links. Measure it in D2.

## Areas the parent asked about

### The `links` column on `readings`

**Type.** `list<struct<8 × string>>` is a valid Iceberg v2 type. DataFusion `unnest`s it, and iceberg-rust's reader prunes it by field ID when the role rule doesn't project it. So classifying bodies never reads link bytes.

**Join plan.** The plan that keeps hash-join builds narrow (A §13.6):
1. Unnest about 4.2M links.
2. Project `(page_sha, link_index, url_key(child_url))`.
3. Join to the 1.7M source-file `url_key`s as the build side.
4. Reduce to the earliest `(page_sha, link_index)` per occurrence `url_key`.
5. Then re-attach `text`, `doc_type` and `add_date`.

Carrying `text` through the join would put strings on the probe side, needlessly. M2 now includes this join.

**`url_key` in SQL.**
- `url_key` in plain DataFusion SQL needs nested `replace` calls for "decode percent-escapes of unreserved characters" (up to about 130 for both hex cases), plus Proofpoint's `-XX` decoding.
- Parameter sorting works with `string_to_array` / `array_sort` / `array_to_string`.
- This is workable. M2 should time it, and S could restrict decoding to the escapes the data actually contains.

**Size.** Unmeasured with links; see F4.4.

### Table properties and conflict retry

These are now consistent:
- `commit.retry.num-retries = 0` stops iceberg-rust's own re-send.
- The producer's three bounded retries recompute the work list.
- `gc.enabled` is true, and C0 stops the reset.
- M1.2 confirms that expiration deletes files under exactly these properties.

The backfill and the daily run write different parser versions, so they can't duplicate each other's rows. When the profile has just moved to a new version, the recompute-on-conflict rule covers both runs.

### Model profile and the completeness gate

The gate holds. Two things need saying.

**P3. Producer order inside `readings` (minor).**
- The HTML, XML and JSON work lists depend on the `sniff` reading's format, and `fingerprint` depends on the HTML reading.
- A §12 should say: `sniff`, then HTML/XML/JSON, then `fingerprint`.
- Moving the pinned sniff version can enlarge the format parsers' work lists, so the gate then refuses until they catch up. That is correct, but operators should move the sniff version together with the format parsers.

**Backfills.** Batch commits to an unpinned version never affect the gate, which is evaluated only on pinned versions at the pinned snapshot.

### The input-identity argument

The argument is sound for the early skip, because a lake row never changes once written.

One column is history-dependent: `base_url`, the body's first capture URL. A late receipt with an earlier time changes what a rebuild would choose, so a rebuild can resolve a few relative links differently under the same identity. This affects rebuild equivalence (principle 1), not publish. The fix is in F4.2.

### Release writer settings

**P1. The 16 KB page setting on `detail`'s key columns does nothing (low).**
- parquet-rs 58.4 checks a column's page size only after each mini-batch of `write_batch_size` values (`column/writer/mod.rs:475-495, 757-768`).
- With 1,024-row write batches, `saved_body` (fsb 32) closes pages at about 32 KB, and `link_key` at the 1,024-row limit (8 KB).
- The per-column limit does exist (`set_column_data_page_size_limit`), but at this batch size it never binds for fixed-width columns.
- Fix: drop the 16 KB clause for `detail`. The 1,024-row limit is what governs. Re-estimate the per-view bytes in F0; the key leaves alone are about 8 + 32 KB plus alternates.
- `links.parquet` (fsb 8 at 16 KB) is unaffected in practice.

**P2. `detail`'s row-group size is unstated (low).**
- The first view fetches the offset index of all 19 leaves for the row group it touches.
- With a single row group, that covers all 0.65M rows. The fold's leaves dominate, because their pages hold only tens of rows. This is a rough estimate of 0.1–0.5 MB per session.
- Fix: state 65,536-row groups, as for `list`, so a first view fetches about a tenth of that. Or measure both in F0.

**Checked and fine:**
- V2 data pages for `DELTA_BYTE_ARRAY` filenames;
- dictionary-encoded `date32`;
- the column index on `links.link_key`, which needs Page statistics on that column only (`set_column_statistics_enabled`);
- the pinned `created_by`.

### The two new release files

- **`recoveries.parquet`.** About 24k rows; its `(list_row, ordinal)` order is unique; offset index; read by range. It fits the reader's existing occurrence-range path. At 1–3 MB it could also be read whole, but range reads keep one code path.
- **`meetings.parquet`.**
  - It is ordered by `(chamber, event_id)`, which is unique, so it is deterministic.
  - Read whole is fine at 1–2 MB.
  - Invariant 16 ties it to `meeting_keys`.
  - Its `meeting_date` and `committee_names` come from the current record, so F2's `good_fetch` definition decides which record that is.

## Decisions preserved

These were spot-checked:
- **Items 62–65:** links on readings, the older-copy check, the queue and the recoveries file.
- **Items 66–69:**
  - ambiguous bodies take no rendition edges (§7.5, invariant 14);
  - the crash gap is accepted (A §7.1);
  - publish and the weekly job share one concurrency group (A §10.3.7, §12);
  - one home per rule.
- **Earlier decisions:** PDF first, keep-2 retention, and the typed `detail` core all hold. VARIANT stays parked under the same three conditions.

## Still with the owner

**The bucket lock (plan B1).** It gates B13 and therefore F's switch checklist.
