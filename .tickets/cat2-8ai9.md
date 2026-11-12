---
id: cat2-8ai9
status: closed
deps: []
links: [ct-jcnd, ct-ywz2, ct-yizl]
created: 2026-11-12T12:20:24Z
type: bug
priority: 0
assignee: mikewolfd
tags: [model, meetings, recordings, dates, horizontal-audit]
---
# Horizontal audit model integrity: m3u8 caption honesty, canonical list.witness_keys, plausible date precedence, soft-404 .pdf hides, and shell meeting backfill

From the 22-slice horizontal raw-data audit (P0-2 SQL, P1-5 SQL, P1-6 SQL, P1-8 SQL, P2-10a SQL): (1) entity-meetings.sql marks 657 Senate hearings with format='m3u8' HLS playlists (0 words of text, unpublished caption_resources) as captions.archived=1 / retained_track; (2) document-witness-keys.sql unions 71,913 superseded witness keys (43.0% of links) into list.witness_keys; (3) document-normalized.sql lets suspect filename_date (2031-01-19 on 295289, 1901-09-26 on 7870) override valid content_date/meeting_date and omits document_date_status from list.parquet; (4) 5 retained HTML 404 error pages saved under .pdf names (262153, 271440, 278019, 278840, 278874) publish visible as amendments/testimony, and 77 descriptions retain double-escaped &#39;/&quot;/&amp;; (5) 546 shell meetings (e.g. 100166) publish with null chamber/congress/committees/meeting_date despite unambiguous linked documents.

## Acceptance Criteria

m3u8 playlists without retained caption_resources report advertised_not_archived; list.witness_keys holds canonical keys only; plausible dates beat suspect filename_date; HTML 404 .pdf impostors hidden and entities decoded; unambiguous shell meetings backfilled from linked documents.

## Notes

**2026-11-12:** Closed on `claude/ct-wave-4-model`:
- `P0-2`: Added `retained_caption_tracks` (`caption_resources` with `status='retained'`) and restricted `m3u8` tracks in `model/sql/entity-meetings.sql` (`caption_tracks`) to playlists with at least one retained child caption resource, so unarchived Senate HLS playlists omit `source='captions'` from `meetings.transcripts` and report `advertised_not_archived`.
- `P1-5`: Removed backward supersession expansion in `model/sql/document-witness-keys.sql`, switched `per_key` to `RIGHT JOIN`s (eliminating `'document_witness_keys': 2` from `OUTER_BUILD_TRACKED`), and emitted canonical (`is_current`) `witness_keys` whenever any current key exists.
- `P1-6`: Aligned `date_plausible` in `model/sql/document-filename-facts.sql` with `DOCUMENT_DATE_STATUS` (`<= first_fetched + 30 days` and within Congress date bounds), ranked plausible `filename_date` -> `content_date` -> `meeting_date` -> `mods_date` -> suspect `filename_date` in `document-normalized.sql` and `document-recovery-normalized.sql`, restricted fallback `congress`-from-date derivation to non-filename dates `>= 1935-01-04` (excluding odd-year `01-03`), and promoted `document_date_status` into `list.parquet` (`archive_format.py`, `release-schema.json`, `docs/release-relationships.md`).
- `P1-8`: Hid HTML soft-404 error pages (`Error | ...`, `Page Not Found`, `404`, `Not Found | ...`, `File Not Found`, or `PAGE NOT FOUND` description) in `archive_model.py` (`normalized`, covering both `document-normalized` and `document-recovery-normalized`) while preserving legitimate HTML transcripts under `.pdf` names, and decoded residual HTML entities (`&amp;`, `&ldquo;`, `&rdquo;`, `&lsquo;`, `&rsquo;`, `&ndash;`, `&mdash;`, `&bull;`, `&#39;`, `&quot;`, `&nbsp;`) in `model/sql/page-descriptions.sql`.
- `P2-10a`: Backfilled unambiguous `chamber`, `congress`, `committees`, and `meeting_date` on shell meetings (`m.event_id IS NULL`) from non-hidden linked `ordered` documents in `model/sql/entity-meetings.sql` while keeping `chamber_basis='meeting_detail_missing'`.
- Verified end-to-end in `packages/viewer_publication/tests/test_horizontal_audit_wave4.py` plus full `viewer_publication` regression suite.

### Final Wave 4 Verification & Merge Closeout (2026-11-12)
- **Code Commit:** `4a19b8cb` (`claude/ct-wave-4-model`, fast-forwarded onto `origin/main`)
- **Hosted CI (`validate-explorer.yml`):** Run `43250539064` — **7/7 GREEN** (all 6 offline shards + Explorer bundle validation)
- **Blind Multi-Skill Review:** Round 3 **SHIP** (`0 P0, 0 P1, 0 P2`)
- **End-to-End 4-Hop Horizontal Verification:** Candidate release `a1a07698ef50066bf41f621751b0c83c5912e9a71e45bb7b40077d0658e44003` (`0` violations across all 36 invariants) + Playwright Chromium UI & live `ede659a056c0` comparison documented in `wave4_horizontal_e2e_trace.md`.
