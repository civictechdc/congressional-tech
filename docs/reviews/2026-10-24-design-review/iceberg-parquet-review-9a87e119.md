# Iceberg/Parquet final round

## Scope and method

- **Reviewed:** commit `9a87e119` (diff from `d9730967`), plus the new `docs/plans/bindings-20261025.md`.
- **Evidence:**
  - the pinned Oct 19 snapshot, queried with DuckDB through `wt/ct-viewer-publish/.venv`;
  - read-only public GETs, with an anonymous User-Agent;
  - docspec-rs at `d9c6719`, read in place;
  - parquet-rs 58.4 source.
- **Scripts:** `entry_idx.py` and `text_head.py` in the session scratchpad.

## Verdict

**Ready to build.** Two wording fixes are needed before E1, and none needs an owner decision:
1. how links match archive-member endpoints, now that the endpoint has `entry_index` (X1);
2. the file paths in bindings §3.3, and one spec MUST the engine doesn't meet (X2).

Everything else is minor.

## My recheck items (all landed)

| Item | Where |
|---|---|
| R1: `url_key` normalizes percent-encoding (RFC 3986 §6.2.2: hex case, unreserved, spaces); C8 gets golden vectors from today's fetcher | DM §7.2; plan C8; bindings C8 |
| R2: only publish and the weekly check ingest captures, and they never overlap | A §12 |
| R3: 64 KB data pages restored on `detail` and `occurrences`; view estimate 50–90 KB | DM §8.1; A §16.1 |
| Minor: ingest-mapping tables are named by version and dropped when no live or last-good profile names them; M1 checks whether a DROP purges files | DM §7.1; plan M1.2 |
| Links resolve once per `(page body, context)`, with the measured 1.3 contexts per page, and placeholder pages are skipped | DM §7.2 |

## Findings

### X1. `entry_index` in the endpoint: link matching and nulls (must fix, wording)

The endpoint is now `(context_url, member_path, entry_index)`, and DM §7.2 says endpoint matching compares all three. Two problems follow.

**1. Member links never match.**
- A link target is a URL, or, for a relative link inside an archive member, a member path in the same container.
- A resolved target has no `entry_index`, so a three-part equality never matches a member.
- As a result, `linked_from`, publisher format groups (rule a) and the queue all miss archive members.
- **Fix:**
  - link targets match endpoints on `(url_key(context_url), member_path)`, matching every entry with that path;
  - only capture-to-capture endpoint identity uses `entry_index`: `same_text`, edition-ambiguous endpoints, and fingerprint candidates.

**2. Nulls.**
- `member_path` and `entry_index` are null for every top-level page.
- A plain `=` join drops every top-level endpoint.
- **Fix:** say that endpoint comparisons are null-safe. DataFusion supports `IS NOT DISTINCT FROM` in join keys. Alternatively, the model can coalesce to `('', -1)`.

**Older receipts.**
- Their member capture entries carry no `entry_index`. It is in `record.archive_members[i].entry_index`, which the entry's `pointer` reaches.
- The pointer's position `i` is not the entry index, so the ingest mapping must follow the pointer, with a test sample. I checked a `documents` receipt with 100 member entries: the `captures[]` keys have no `entry_index`, and the `archive_members` records have one.

### X2. Bindings §3.3 against docspec-rs `d9c6719` (fix the Note; one spec relaxation)

**Correct as written:**
- `storage.rs:132-141` (table properties);
- `storage.rs:376-388` (2 MiB and 2,048-row remote caps);
- `catalog.rs:1163` (the `gc.enabled` reset);
- `append` at `storage.rs:858`;
- `query.rs`, `storage/pinned.rs`, `budget.rs`;
- `main.rs`, `error.rs`.

**Paths to fix** (`ds/` is `src/`):

| Bindings says | Actual |
|---|---|
| `batch.rs` | `src/storage/batch.rs` |
| `export/pipeline.rs:445-702` (and `:687-697`) | `src/engine/export/pipeline.rs` (736 lines; the offset-index switch is at 687-697) |
| `child.rs`, `facets.rs`, `parent.rs` | `src/engine/export/pipeline/{child,facets,parent}.rs` |
| `HashingFile` at `export.rs:658-697` | `src/engine/export.rs:658` (`src/export.rs` has 395 lines) |
| `topology.rs:31-280` | `src/engine/connected_components/topology.rs` (509 lines), plus `src/engine/connected_components.rs` |

**Facts to fix:**
- **`HashingFile`** hashes with BLAKE3 (`blake3::Hasher`). C3 already lists "SHA-256 and MD5" as work, so the Note should say "replace BLAKE3" rather than imply SHA-256 exists.
- **C4 connected components.**
  - Today's union-find uses `parent: Vec<usize>` (64-bit) and has no node-cap refusal; its only size refusal is `i64::MAX` rows.
  - A §13.4 says "MUST … over 32-bit IDs", and A §9.3 quotes 16 MB at 4M nodes.
  - Either mark C4 "Adapt (u32 IDs and the cap)", or relax the MUST to "dense integer IDs" and say 32 MB. The memory difference is 16 MB at today's size, so I'd relax the spec rather than change working code.
- **C8 libraries.** `url` 2.5.8 and `percent-encoding` 2.3.2 are only transitive (in `Cargo.lock`, not `Cargo.toml`). Add them as direct dependencies at the locked versions.
  - `url` follows WHATWG resolution. It encodes spaces as `%20`, which `url_key` now absorbs.
  - Resolving member paths needs a synthetic special-scheme base. The golden vectors decide whether it fits.
- **C3.** The current export also forces `write_batch_size(256)` and 16 KB pages when page-index columns are named (`pipeline.rs:690-697`). C3's per-file settings replace both.

### X3. Wider fingerprint scope: cost and plan shape (minor)

**Cost.**
- Rendition-group members add an estimated 20–45 GB of reads once, mostly PDF text, then grow with new groups. That is about 30k PDFs at roughly 1.4 MB each; text extraction at about 0.1–1 s each is a one-time job of a few hours, gated by the completeness check.

**Repeated work to name.**
- The candidate list now needs rendition-group membership: link resolution, `url_key`, and rules (a) and (b).
- So the `fingerprint` producer evaluates most of the model's link work before the pin, and the model evaluates it again.
- This is seconds to a minute at about 5.5M targets. Name it in A §16.1's repeated-work list, which still names only "the real-file rule".

**Do once.** The HTML, XML and JSON parsers already hold the visible text, so they can write `fingerprint` for every page in their own pass (one SHA-256 per page).
- The candidate pass then reads only formats no parser reads (PDF, Office files and others).
- HTML candidates are never fetched twice.
- Their fingerprints become body-intrinsic, independent of candidacy.

### X4. `text_head` size (minor)

- **Measured** on 150 HTML bodies: about 1.9 KB of raw text and 369 B per row after ZSTD in Parquet. That gives about 100 MB per HTML/XML parser version (est.), roughly 6× the rest of `readings` (16.5 MB).
- **Growth.** Every parser version is kept, so each new HTML parser version adds about 100 MB here, plus the links.
- **Plan shape.** The body-marker check scans this column every publish (about 100 MB; seconds). Keep it in the role computation: reduce `readings` to `(body_sha, record_role)` first, with the registry as a broadcast build side, before any join, so `text_head` never reaches a hash table.
- D2 already measures the table's size; add `text_head` to that.

### X5. Ingest-mapping tables in Basin (minor)

- **Maintenance.** It is enabled per table, so creating `captures_<version>` must also enable compaction and expiration. D6 names "all five tables" only.
- **Names.** Use a short version label in the table name rather than a full SHA-256; the profile maps label to digest.
- **Who drops the old table.** Today publish holds the lake credentials and maintenance holds the delete token (A §14). Say which job drops it, and with which credential.
- **If DROP doesn't purge.** If M1 shows Basin's DROP leaves the files, about 157 MB per mapping version stays as orphans. The weekly orphan report covers that.

## Checked and fine

- **`h_content_disposition`.** It feeds the effective filename. Older receipts recorded every header, so the backfill can fill it.
- **Body identity.** The SHA-256 of the entity after its transfer encoding is removed is what the fetcher computes today (bindings K5).
- **B0.** It rewrites receipts before the lock and before any lake build, and it keeps keys and line order. So `captures` ingest and the receipt-key input identity are unaffected.
- **The rest.** `withdraw` reviews, recovery rows per import row (PK = the import row's capture key), the committee-code registry and the meeting-ID prefix rule have no Iceberg or Parquet impact.
