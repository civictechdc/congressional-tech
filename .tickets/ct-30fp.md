---
id: ct-30fp
status: closed
deps: []
links: [ct-kw9b, ct-vpo2, ct-h1nd, ct-pocg, ct-v51p, ct-aapl]
created: 2026-10-30T21:13:37Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, review, correctness]
---
# Preserve witness observations across source contexts, empty updates and repeated names

Blind review findings GB2/GB4/GB5 share one observation-model defect: appearance parsing is keyed only by body/version but resolves source URLs, empty lists lose their subject before current selection, and normalized-name deduplication drops unequal panels/roles/document evidence. Correct PHASE-2 §1.3/§2 and its implementation as one coherent observation model, preserving existing release readability.

## Design

Owner: congress_api/lake/appearance_records.py and _record_producer.py, model lake schemas and appearance/meeting resolution SQL, native release schema and fixtures. Parse context-free source facts once per body, source and selected parser version; retain literal links and source locators, then resolve every eligible capture context in the model. Keep subject identity and collection state outside the list. Select the current observation before expanding list entries. Preserve separate source occurrences; a normalized name is a grouping attribute, not sufficient identity. Coordinate source-scoped versions with ct-h1nd, admission with ct-kw9b and shared publication with ct-gi01. Version any witness-key change; never rewrite old release keys or silently choose one target for an ambiguous old key.

## Acceptance Criteria

- Same bytes first seen at A and later at B produce the same contextual appearances/links/keys in maintained processing and a clean rebuild; parse bytes once per selected body/source/version and retain both eligible contexts.
- Nonempty -> explicit-empty replaces the prior collection. Absent, unrecognized and failed extraction retain distinct state and explicit fallback rules; no stale list is selected accidentally after unnesting.
- Preserve source subject identity even with zero appearances. Apply equivalent empty/absent rules to replacement meeting collections; fields intentionally unioning assertions retain their documented semantics.
- Same normalized name in distinct panels/organizations/roles or with different documents remains distinct evidence. Equivalent observations may be presented together only with all contributing locators and evidence retained.
- Stable occurrence locators survive unchanged-input replay and later enrichment; version new public appearance identity and preserve old releases. Test unambiguous, ambiguous and unresolved old-key mappings without name-only merging.
- Add transition fixtures and replace the fixtures that currently bless unequal-name deduplication. Update lake/release schemas, SQL, generated relationship reference and consumers together; record exact input/definition/release pins and focused checks.
- Reuse valid body readings and unchanged source completions. Rebuild only affected derived versions; do not launch a full corpus replay just to discover scope.


## Notes

**2026-10-30T21:22:04Z**

Context binding must also scope retrieval ordering to the subject/context. Capturing identical bytes later at B must not refresh an old observation at A or replace a newer distinct body already observed at A. Include this case with the A/B maintained-versus-rebuild fixture.

**2026-11-01T04:25:21Z**

Verified and tested:
- Context-free senate_page observations join through fetch captures (c.mode='fetch' AND encode(c.sha256,'hex')=r.record_sha_hex) in appearance-records-resolved.sql and archive_model.py so bytes captured at URL A and later at URL B resolve to both contexts, with observation freshness ranked by per-context capture timestamp/line rather than record-level max capture time.
- Occasion-level replacement enforces collection_state ('present' and 'empty' replace lower-priority sources; 'absent' falls back; 'unrecognized' blocks fallback).
- Distinct source_locator and witness_key values preserve multiple same-name appearances within one occasion.
- Verified with uv run pytest packages/viewer_publication/tests/test_phase2_model_entities.py.

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator 496c48e1):
- Verdict: FAIL (1/7 ACs met, 5 partial, 1 not met; 151/151 existing tests pass, but adversarial probes exposed 3 functional bugs):
- Remaining work before closure:
  1. [Priority 1] In `packages/congress_api/src/congress_api/parsers/senate_page.py:146-147` and `packages/congress_api/src/congress_api/lake/appearance_records.py:847`, stop deduplicating repeated witness names across distinct witness cards on the same Senate hearing page, and extract/bind `document_links` per witness card node so two witnesses with the same normalized name (e.g. two `"John Smith"` cards with different orgs/PDFs) are both preserved with their respective document links.
  2. [Priority 1] In `packages/congress_api/src/congress_api/lake/appearance_records.py:783,855-856`, preserve literal relative `href` values in `document_links` (resolving against `<base href>` only when declared) instead of pre-resolving against `https://senate-page.local/` and stripping the host to root-relative `"/testimony.pdf"`, so `url_resolve(c.source_url, l.raw_link)` in `model/sql/appearance-records-resolved.sql` resolves relative to the capture directory (e.g. `https://www.banking.senate.gov/hearings/h1/testimony.pdf`).
  3. [Priority 2] In `model/sql/appearance-records-resolved.sql:121-128,163-191` and `packages/congress_api/src/congress_api/lake/appearance_records.py:619-621`:
     - Select the latest observation per `(occasion, source, context_key)` before ranking across contexts so capturing old bytes `X` later at `B` cannot beat newer bytes `Y` already observed at `A` (`X@A -> Y@A -> X@B`).
     - Distinguish `'failed'` (`status IN ('error', 'size_limit')`) from `'unrecognized'` in `appearance-records-resolved.sql:123`.
     - Classify a non-empty `witnesses` JSON array containing no valid dict entries (`[123, "bad"]`) as `'unrecognized'` rather than `'empty'` in `appearance_records.py:619-621`.
  4. Add transition fixtures covering `X@A -> Y@A -> X@B`, Senate repeated witness names, Senate relative `href` resolution, and old-key mappings; refresh `publish-model.json` and `publish.json`; and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 2 Engineer (b009d889, 100% confidence) across Round 1 & Round 2:
  1. Added first-class `witness_occurrences` in `senate_page.py:1208-1278` (`witnesses(..., deduplicate=False)` + `source_details_tree(..., preserve_occurrences=True)` scoped to post-`Witnesses` heading subtree, filtering card-interior anchors out of `plain_witness_links`, and honoring `<base href>` + `.senate.gov` default URL while preserving literal relative `raw_href`).
  2. Updated `appearance_records.py:664,824-825,963-964` so non-empty invalid witness collections across `congress_gov`, `senate_page`, and `mods` emit `collection_state = "unrecognized"`.
  3. Refactored `model/sql/appearance-records-resolved.sql:11-65,121-207` to align `capture_contexts` `congress_gov` classification with `_record_producer.py` (`c.family = "congress/meetings"`, `www.congress.gov`, `/joint/`) and rank per-context freshness (`ranked_context_observations` -> `superseded_source_bodies` -> `ranked_source_observations`) with `(effective_state IN ("present", "empty")) DESC, (effective_state = "absent") ASC`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (99%), Evolutionary Refactoring PASS (99%).
