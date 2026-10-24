---
id: ct-owh2
status: closed
deps: [ct-upl1, ct-3lz2, ct-qxqp, ct-r33r, ct-t130, ct-1h4g, ct-fyid, ct-qcf5, ct-fmgi, ct-07eg, ct-5yof]
links: []
created: 2026-10-20T16:52:26Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, review, qualification]
---
# Re-audit news_lake against C1-C9 and I1-I6 after review remediations

Final qualification gate after all adversarial review remediations land across contract, storage, adapters, identity, and analysis.

## Design

Run the full packages/news_lake test suite and the read-only packet checker (packages/news-lake/docs/checks/validate.py), verify schema byte-identity, audit README.md and docstrings against actual code behavior, and re-grade all six rubric categories.

## Acceptance Criteria

- All remediation tickets (ct-upl1, ct-3lz2, ct-qxqp, ct-r33r, ct-t130, ct-1h4g, plus mapping, adapter, analysis, performance, and export tickets) are closed with passing regression tests.
- packages/news-lake/docs/ remains untouched and byte-identical to shipped schema copy.
- README.md seams and limitations match the remediated implementation with zero overstated guarantees.


## Notes

**2026-10-20T17:30:56Z**

Final qualification complete. Full news_lake suite: 281 passed in 46.73s. Packet checker passes (schema/fixtures/shape/semantic cases). Shipped schema remains byte-identical to docs authority. README updated for atomic upserts, fencing, release gating, cursor monotonicity, evolved columns, adapter date/domain behavior, identity graph, analysis views, typed labels, C5 export, and remaining deferred work. All child remediation tickets closed.

**2026-10-20T18:09:49Z**

Addressed all 10 findings from the semi-formal code review: (1) cached table UUIDs, Arrow schemas, and allowed_extra per schema_id in Lake and avoided redundant catalog loads in Coordinator/_prepare and publish_release; (2) removed dead null check in _allowed_extra_fields; (3) extended schema evolution support to news.releases in append_release and _allowed_extra_by_kind; (4) generalized pending eligibility in analysis/selection.py to cover cluster-identical-text and classify-keywords; (5) added parametrized stale-epoch tests across all 9 ControlStore mutators; (6) clarified PageDrain.checkpoint() docstring; (7) added first-character casefold prefix filter in _find_occurrences; (8) expanded ccTLD public-suffix guard in outlet_domain; (9) added explicit invalid_outlet_domain check in outlet_for_domain; (10) documented and enforced shape + C2 credential checks in export_release. 290 passed in 38.97s.

**2026-10-20T18:28:05Z**

Implemented all 4 final professor recommendations: (1) O(1) pre-indexed mentions_by_version and story_by_version in _ReleaseScope; (2) column projection on validated heavy snapshots plus prior-snapshot ID recognition on modified append tables in _pinned_records; (3) offline Mozilla PSL integration via tldextract(suffix_list_urls=(), cache_dir=None) in outlet_domain; (4) atomic cross-system fencing via Lake.fenced_commit wrapping SqlCatalog.commit_table inside control._write_tx(epoch). 293 passed.

**2026-10-20T20:16:54Z**

docspec-rs optimization agent complete and committed (715a8c2): PARQUET_2_0 + ZSTD(3) + dictionary encoding + byte-based row groups (128 MiB) in export writer, batch_rows 8192, plan-captured projection pushdown, profiling harness (25 small files -> 1 after compact), 262-line iceberg_optimization_report.md incl. row-group skill-bug correction (set_max_row_group_size deprecated 58.0.0, bytes-vs-rows). Canonical suite --all-features green: lib 348, integration 313, worker 15, restore 2. news_lake: 307 passed incl. 5 docspec_backend parity tests.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 80 → 80, work 72 → 72.
- Problem: Its "4 final recommendations" follow-up added the O(releases x rows) prior-snapshot scan (releases.py:143-152).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:61
- Covered by: WS8 (ct-d8cf), which deletes the PyIceberg oracle path that holds the scan.
- See docs/reviews/2026-10-24-ticket-audit/README.md
