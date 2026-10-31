# Response to the URL normalization defense

The defense strengthens the case for a targeted House download repair and correctly withdraws the wrapper exclusion, blanket recovery join, and public lookup failure claims. I accept those revisions. The remaining plan needs changes before implementation, and the updated trace still claims recovery outcomes that its cited artifacts do not show.

This response addresses commit `cafb1b43`. Its changes since `535375d1` are documentation only. The prior native reproductions therefore still apply. New measurements, SQL, artifact hashes, and a native comparison of the proposed trailing-space change are recorded in [the response evidence](url-normalization-defense-response-evidence.json).

1. **The House versus Senate distinction is correct and materially improves the diagnosis.**

   My earlier reply should have separated the hosts when reporting 4,062 successful literal URLs. All 4,062 are on the four Senate hosts named in the defense; none are House URLs. For House requested URLs ending in `&download=1`, the checked capture table contains 19 HTTP attempts, all returning 410. The campaign transition also confirms 1,563 formerly pending targets accepted under `retained_candidate_repaired_download_query`, and the selected-recovery table contains 1,606 targets with that candidate source.

   This supports generating repaired fetch candidates for the demonstrated House route. It does not establish the servers' internal ColdFusion rewrite configuration, a universal failure rule for every House host, or that all 3,231 original pending targets had failed HTTP attempts. That cohort explicitly includes unattempted targets. Keep those distinctions in the explanation.

2. **The Ashley Nunes recovery claim is false in the checked evidence.**

   The revised trace, lines 518–520, says the target was recovered, became satisfied, and appears in `release_v2/recoveries.parquet`. The actual records are:

   | Evidence | Observed result |
   | --- | --- |
   | Wave 4 request for `.../ashley-nunes-witness-testimony?download=1` | HTTP 200, `outcome=stored`, `qualification_status=unresolved` |
   | `selected_recoveries_v2_plus.parquet` | No matching target |
   | `release_v2/url_state.parquet`, base URL and ampersand URL | Both `eligible`, with `no_satisfying_recovery` |
   | Frozen campaign `plan_v2`, ampersand URL | `needs_acquisition` |
   | `release_v2/recoveries.parquet` | File absent; this directory contains capture control files and URL state |

   The Wave 4 receipt is `receipts/documents/2026-10-31/track-b-wave4-20261031-a13ed292de0ec3429d9594f856c98e74fd59c9a4673dce91e0b0b1e4aa267669.jsonl.gz`. Successful fetching is established; accepted recovery and publication are not.

   The defense's line 99 also says all 1,664 remaining House targets have never had the repaired URL fetched. Reconstructing that Wave 4 cohort from the original plan minus the accepted `repaired_download_query` targets finds **241 distinct targets with repaired-URL attempt records**: 234 stored or unchanged responses with unresolved qualification, three size limits, two failed 302 responses, and two request failures. Their next actions must reflect those outcomes.

3. **The publisher link explanation is useful, but it does not identify another acquisition defect.**

   The retained page facts confirm 87 extracted links. [publisher-links.sql](../model/sql/publisher-links.sql#L1) associates resolved links with source identities; the four self-fragment links can match the wrapper's captured address while an unfetched download target cannot. Acquisition discovers targets independently through `resolved_link_targets` in [archive_url_state.py](../packages/viewer_publication/src/viewer_publication/archive_url_state.py#L70). The ampersand target's zero-attempt state already proves it reached discovery.

   Retitle “Bug 1A” as an explanation of this distinction. Also remove “all 87 enter `url_state_queue`”: that queue applies scope, member-path, key, and previously-fetched filters. The four self-fragment links share an already-fetched key and are excluded by the check at line 84. Preserve the separate identities of a wrapper page and its downloadable document; their different keys are not themselves a defect.

4. **The Wayback repair can preserve exact replay validation.**

   The 36 empty responses and 15 rejected SURT aliases remain confirmed. Implement empty JSON handling in `_wayback_page` as `([], None)` so the caller retains prior candidates, evidence, and query-window information. The proposed `DiscoveryOutcome` return type does not exist in this implementation.

   Validate a non-null query SURT against both the returned `urlkey` and the validated returned `original`. Preserve the requested campaign URL in `target_url`, set candidate `original_url` to the returned archived spelling, and use that spelling in both the replay URL and deduplication identity. [acquire_candidate](../packages/corpus_recovery/src/corpus_recovery/discovery.py#L227) already passes candidate `original_url` to the replay validator. Its exact host, timestamp, and URL checks can remain intact. Retain the existing digest, status, completeness, time-window, and pagination checks.

5. **The fetch-selection proposal needs to cover existing states and campaign membership.**

   Prefer admissible repaired candidates while retaining the observed URL and campaign target. Sorting alone cannot create `?download=1` when the only observed spelling contains `&download=1`. Also, `url_normalized` currently exports `url`, `error`, `still_wrapped`, and `base_key`; it does not expose the internal `u.value` cited by the proposed change.

   Changing seed selection alone leaves existing state rows untouched: [capture_scheduler.py](../packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L392) takes their `requested_url` directly and suppresses same-key seed alternatives. Campaign mode additionally requires exact target membership at line 381, so replacing that address without preserving the campaign target can exclude the repaired request. Cover lone ampersand seeds, mixed spellings, existing bad state plus a good seed, and campaign targets fetched through repaired candidates. Keep attempt history, eligibility, and the selected capture profile consistent across those cases.

6. **The corpus check found no distinct-document collision from trailing-space trimming.**

   My earlier objection established that different URL spellings could receive the same key; it did not establish that different documents would merge. The follow-up check materially narrows that concern. Across **1,202,155 campaign rows**, 27 normalized paths end in encoded spaces. Only one affected key has an existing clean counterpart: the GPO Deepwater report. The encoded-space address returned a **196-byte HTML 404**; the clean address returned the **17,746,116-byte PDF** that appears in the published release. This is not evidence of two distinct documents. None of the 27 affected addresses has a capture marked `is_real_file=true`; their retained responses include wrappers, errors, and one HTML address classified as `document` but not as a real file.

   Across **605,848 published source rows** representing 529,386 distinct URLs, a broad screen selected 19,397 unique URLs containing encoded spaces, whitespace, repeated slashes, or any wrapper recognized by the current registry. Running the actual current and proposed normalization SQL on that set produced **zero changed published-source keys**. Native execution also confirmed all 27 campaign key changes and their agreement with the proposed clean addresses.

   I withdraw the claim that this change threatens distinct documents in the checked corpus, and the requirement for a publisher restriction on that basis. This check does not prove equivalence for every future URL, nor does it establish that all 27 clean addresses retrieve the intended content. Preserve observed URLs and qualify recovered content. The proposed `(?:%20|/)+$` expression also changes repeated trailing-slash behavior; keep that separate from the encoded-space repair unless it is intentional. No affected repeated-slash campaign keys were found. The confirmed Senate fragment and encoded-slash defects remain appropriate fixes.

7. **Finish correcting the trace and bind its counts to specific artifacts.**

   The defense's percentage table reports 1,004,352 publisher-link rows and 191,836 campaign rows. The cited `publish_v20` publisher table has **913,034** rows; both checked campaign plans have **1,202,155**. The table's uppercase regex also tests only the second hex digit: it returns 826 source rows, while testing either digit returns the stated 987. Include the actual predicate and any population filter.

   `plan_v2` was rebuilt during this review. The earlier checked generation had 1,668 pending ampersand targets; the frozen replacement has 1,415, of which 1,411 are House targets. The original 1,563 repaired-query transitions remain present. These are distinct generations, not contradictory counts; the evidence JSON preserves their hashes.

   Several substantive code descriptions remain wrong after the revision: `_safe_reference` validates rather than calling `urljoin`; the fetcher uses seven loop iterations rather than a ten-redirect constant; the displayed `lookupUrl` implementation is not the current function; and the public lookup key is the first eight SHA-256 bytes of `lookup:` plus the lookup spelling. The recovery eligibility code emits `eligible`, `satisfied`, or `excluded`, never `exhausted`, and uses `qualified_recovery` rather than `accepted_recovery` as its success reason. The quoted malformed-host derivation also conflicts with the earlier native reproduction: a relative `File URL path:` string stays under the base host, while an absolute malformed host is rejected.

The implementation priorities are now clearer: repair Wayback discovery, fix the targeted fragment/encoding cases, and carry repaired fetch candidates through existing scheduler state and campaign rules. Preserve literal recovery requirements and the existing public lookup format. The corpus check supports dropping the distinct-document objection to trailing-space trimming. Correct the remaining acquisition-versus-qualification-versus-publication claims before calling the plan production ready.
