# Technical Defense, Empirical Verification & Converged Fix Plan (Following GPT-6 Audits of `535375d1` & `cafb1b43` + Waves 1–6 Aggregation)

We have verified every claim in GPT-6’s initial audit (of commit `535375d1`) and follow-up response ([docs/url-normalization-defense-response.md](file:///Users/mikewolfd/Work/congressional-tech/docs/url-normalization-defense-response.md) and [docs/url-normalization-defense-response-evidence.json](file:///Users/mikewolfd/Work/congressional-tech/docs/url-normalization-defense-response-evidence.json) on commit `cafb1b43`) against the codebase, the lake `readings` table (`rebuild-885/tables/readings_full_0cb`), `publish_v20`, and `recovery_campaign_v1` (`plan`, both pinned generations of `plan_v2`, `track_a`, `track_b`, and `release_v2`).

In addition, we have aggregated all empirical URL parsing, normalization, candidate-generation, and qualification findings across **Holistic Recovery Waves 1–6** (`35,552` accepted recoveries in Waves 1–5 plus `1,375+` in Wave 6).

Below is:
1. **Executive Convergence Matrix** (incorporating all verified corrections from GPT-6’s response).
2. **Point-by-Point Verification of GPT-6’s 7 Response Points** with exact receipt hashes, SQL predicates, and artifact pins.
3. **Aggregated URL Parsing, Normalization & Recovery Findings Across Waves 1–6**.
4. **Final Converged, Production-Ready Fix Plan**.

---

## 1. Executive Convergence Matrix

| Topic | Status | Converged Verdict & Summary of Evidence |
| :--- | :--- | :--- |
| **1. Stage 7 Wayback CDX (`51/60` HTTP 200 failures)** | **Confirmed & Converged** | Both empty JSON `[]` (`36/60`) and SURT-matched `original` spelling differences (`15/24` non-empty hits) are confirmed in [discovery.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L117-L246). Implementing `([], None)` in `_wayback_page` and validating query SURT against both `row['urlkey']` and `key(row['original'])` while storing `row['original']` in `candidate['original_url']` preserves exact replay validation in `validate_wayback_replay` without modification. |
| **2. Stage 2 Scheduler (`min(url)`, `http://` scope drop, state & campaign membership)** | **Confirmed & Converged** | `min(url)` picks `&download=1` over `?download=1` and `http://` over `https://`. As GPT-6 noted, `url-normalized.sql` exports `(url, error, still_wrapped, base_key)` (not `u.value`), `capture_scheduler.py:392` takes `requested_url` from existing `url_state` rows (suppressing same-key seeds), and campaign mode (`line 381`) checks `campaign_targets.target_url = scoped.requested_url`. Repaired candidate selection must cover lone `&download=1` seeds, mixed spellings, existing state rows, and campaign target membership. |
| **3. House vs. Senate `&download=1` Distinction (`4,062` Senate successes vs. `1,563 + 226 + 3` House repaired recoveries)** | **Confirmed & Scoped** | All `4,062` distinct literal `&download=1` URLs with HTTP 200 `is_real_file = true` in `capture_sources.parquet` are on 4 Senate hosts (`finance`, `banking`, `appropriations`, `budget.senate.gov`); `0` are on House hosts (`19` House HTTP attempts on `democrats-transportation.house.gov`, all returning HTTP `410`). Across Waves 4–5, `1,563` + `226` (Poppler-verified) + `3` (DOCX) formerly pending House `&download=1` targets were recovered by fetching `?download=1`. We keep the distinction between attempted failing targets and unattempted targets without speculating on internal ColdFusion server configurations. |
| **4. `ashley-nunes-witness-testimony` & Wave 4/5 Attempted Cohort (`241` targets)** | **Conceded & Verified to the Receipt Byte** | GPT-6 is 100% right: in Wave 4 (`receipts/documents/2026-10-31/track-b-wave4-20261031-a13ed292de0ec3429d9594f856c98e74fd59c9a4673dce91e0b0b1e4aa267669.jsonl.gz`), `.../ashley-nunes-witness-testimony?download=1` redirected (`302`) to `/imo/media/doc/Ashley%20Nunes%20Witness%20Testimony.pdf` and returned HTTP 200 (`outcome = 'stored'`), **but the origin file on the committee server is `0 bytes` (`sha256 = e3b0c44...`, `sniffed_format = 'empty'`)**, so `qualification_status = 'unresolved'`, it is absent from `selected_recoveries_v2_plus.parquet`, and both its base and `&download=1` URLs are `eligible` (`no_satisfying_recovery`) in `release_v2/url_state.parquet`. Furthermore, `241` of the `1,664` Wave 4 pending House targets had Wave 4 `?download=1` attempt records (`226` subsequently verified by Poppler + `3` DOCX in Wave 5, leaving `12` in rebuilt `plan_v2`). |
| **5. Stage 1 `publisher-links.sql` vs. `resolved_link_targets` & `url_state_queue`** | **Conceded & Retitled** | `publisher-links.sql` associates resolved links with already-captured source identities (`copy_url_keys`), whereas acquisition discovers targets via `resolved_link_targets` in `archive_url_state.py:70-85` (where `url_state_queue` filters by scope, `target_member_path IS NULL`, and `NOT EXISTS` in `url_state_fetched_keys`, excluding the 4 self-fragment links at line 84). Separate keys for a wrapper page (`/download/<slug>`) and its downloadable document (`?download=1`) are proper model separation, not a defect. |
| **6. Stage 5 `senate-notfound` (`%2F` & `#main-nav`) vs. Global `(?:%20\|/)+$` Trim** | **Targeted Fixes Retained; Global Trim Withdrawn** | `senate-notfound` (`"decoder": "percent"` + `(?:#.*)?$`) and `download-ampersand-query` (`(?:#.*)?$`) are retained as targeted fixes. **Fix 4 (replacing `/$` with `(?:%20|/)+$` in `url-normalized.sql:48`) is withdrawn**: as GPT-6 proved natively, `(?:%20|/)+$` collapses `/report//` $\rightarrow$ `/report` (whereas `/$` yields `/report/`) and merges trailing `%20` across every host without evidence. |
| **7. Stage 6 Recovery Custody Joins (`archive_url_state.py:129-166`) & Stage 8 `DM8.2` Lookup Key** | **Converged** | Literal joins in `archive_url_state.py:129-166` are preserved intact (`capture_disposition` is `'eligible'`, `'satisfied'`, or `'excluded'`; `capture_reason` is `'qualified_recovery'`, `'no_satisfying_recovery'`, or `'scope_exclusion'`). Public `lookup_key` (`first 8 SHA-256 bytes of 'lookup:' || lookup_url`) is preserved intact under `DM8.2`. |

---

## 2. Point-by-Point Verification of GPT-6’s 7 Response Points

### Point 1: House vs. Senate `&download=1` Distinction & Cohort Precision
- **Verified Counts in `publish_v20/model/evidence/capture_sources.parquet`**:
  - All `4,062` distinct `requested_url`s ending in `&download=1` with `http_status = 200 AND is_real_file` are on 4 Senate hosts:
    - `www.finance.senate.gov`: `1,814` capture rows, `1,569` distinct URLs
    - `www.banking.senate.gov`: `1,419` capture rows, `1,417` distinct URLs
    - `www.appropriations.senate.gov`: `734` capture rows, `734` distinct URLs
    - `www.budget.senate.gov`: `342` capture rows, `342` distinct URLs
  - For House `requested_url`s (`^https?://[^/]*\.house\.gov/`) ending in `&download=1` with `http_status IS NOT NULL`, `capture_sources.parquet` contains `19` capture rows (`19` distinct URLs, all on `democrats-transportation.house.gov`), all with `http_status = 410, outcome = 'failed', record_role = 'error_response'`.
- **Precision Maintained**:
  - The original `3,231` `needs_acquisition` `&download=1` cohort (`3,227` House + `4` Senate) included both attempted failing targets and unattempted targets (`attempts = 0`).
  - Rather than speculating on internal ColdFusion rewrite rules across all House hosts, this evidence supports generating repaired `?download=1` fetch candidates for the demonstrated House `/download/` route while preserving observed target provenance.

---

### Point 2: `ashley-nunes-witness-testimony` & the `241` Attempted Wave 4 Targets
- **Concession on `ashley-nunes-witness-testimony`**:
  - Our prior update to `docs/url-normalization-trace.md` (lines 518–520) erroneously stated that `https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1` became `satisfied` / `accepted_recovery` in Wave 4 and appeared in `release_v2/recoveries.parquet`.
  - **Actual Verified State Across Artifacts**:
    1. **Wave 4 Receipt (`receipts/documents/2026-10-31/track-b-wave4-20261031-a13ed292de0ec3429d9594f856c98e74fd59c9a4673dce91e0b0b1e4aa267669.jsonl.gz`)**:
       - Requesting `candidate_url = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'` redirected (`302`) to `final_url = 'https://democrats-science.house.gov/imo/media/doc/Ashley%20Nunes%20Witness%20Testimony.pdf'` and returned `http_status = 200, outcome = 'stored'`.
       - **Why Qualification Rejected It**: The file stored on the committee’s server at `/imo/media/doc/Ashley%20Nunes%20Witness%20Testimony.pdf` is **`0 bytes`** (`bytes = 0`, `sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, `sniffed_format = 'empty'`) across all 3 rungs (`direct`, `zyte`, `firecrawl`). Thus `qualification_status = 'unresolved'`.
    2. **`track_a/selected_recoveries_v2_plus.parquet`**: `0` matching rows for `ashley-nunes-witness-testimony`.
    3. **`release_v2/url_state.parquet`**:
       - Base URL (`.../ashley-nunes-witness-testimony`): `attempts = 1, last_status = 200, last_outcome = 'stored', capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'`.
       - Ampersand URL (`.../ashley-nunes-witness-testimony&download=1`): `attempts = 0, last_status = NULL, last_outcome = NULL, capture_disposition = 'eligible', capture_reason = 'no_satisfying_recovery'`.
    4. **`plan_v2/url-dispositions.parquet`**: `disposition = 'needs_acquisition', subtype = 'needs_acquisition_walled_403_or_unattempted'`.
    5. **`release_v2/` Directory Structure**: Contains capture control files and URL state (`capture_profile.json`, `capture_scope.json`, `manifest.json`, `url_state.parquet`, `url_variants.parquet`); there is no `release_v2/recoveries.parquet`.
- **Exact Accounting of the `241` Wave-4-Attempted House Targets Across Both `plan_v2` Generations**:
  - In the first `plan_v2` generation (`sha256: 5f6639a2d55c6075c8be1a4994aac181665cce56465739e645fbf855071dfa3b`, `1,668` pending `&download=1` targets = `1,664` House + `4` Senate), **241** of the `1,664` pending House targets had Wave 4 `?download=1` attempt records in `b1_wave4_results.json` (`sha256: 8639e53d235da5d51eed70b56566415066d40c393d1cfc885010b3ee380b2fec`):
    - `231` HTTP 200 `outcome = 'stored'`, `qualification_status = 'unresolved'`
    - `3` HTTP 200 `outcome = 'unchanged'`, `qualification_status = 'unresolved'`
    - `3` HTTP 200 `outcome = 'size_limit'`, `qualification_status = NULL`
    - `2` HTTP 302 `outcome = 'failed'`, `qualification_status = NULL`
    - `2` `http_status = NULL`, `outcome = 'request_failed'`, `qualification_status = NULL`
    - (While the remaining `1,423` pending House targets had not yet had `?download=1` attempted.)
  - In Wave 5 (the second `plan_v2` generation checked by GPT-6, `sha256: b551043dac48970c961f0329cf8b89f8917c873608a95399aa3e590511d0aa0b`, `1,415` pending `&download=1` targets = `1,411` House + `4` Senate):
    - **226** of the `234` `unresolved` Wave 4 downloads (valid PDFs that had Adobe owner-permission encryption flags) were decrypted/verified with `qpdf`/Poppler and accepted under `subtype = 'retained_candidate_repaired_download_query_poppler_verified'`.
    - **3** were verified as `.docx` and accepted under `subtype = 'retained_candidate_repaired_download_query_docx'`.
    - **24** purged `404/410` `&download=1` targets were recovered via `302` `Location` filename matching against the corpus (`subtype = 'retained_candidate_redirect_location_corpus_match'`).
    - Exactly **12** of the `241` Wave-4-attempted House targets remained in `needs_acquisition` in that `plan_v2` generation (`241 - 226 - 3 = 12`): `3` HTTP 200 `stored` `unresolved` (`ashley-nunes-witness-testimony` at 0 bytes, plus 2 unreadable PDFs), `2` HTTP 200 `unchanged` `unresolved` (both 0-byte files), `3` HTTP 200 `size_limit` (`>16 MB` PDFs), `2` HTTP 302 `failed`, and `2` `request_failed`.

---

### Point 3: `publisher-links.sql` vs. `resolved_link_targets` & `url_state_queue`
- **Verified**:
  - `publish_v20/model/evidence/page_facts.parquet` confirms `link_count = 87, status = 'completed'` for `body_sha = from_hex('ae5ee73d95a8fada1e9491574799cf263d03114d3f84d830ed26a9f6e1e0934c')`.
  - [model/sql/publisher-links.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/publisher-links.sql#L1-L12) is a model evidence table associating resolved page links with already-captured source identities (`copy_url_keys`), not an acquisition discovery table.
  - Acquisition discovers targets independently from `resolved_link_targets` in [archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L70-L85).
  - Furthermore, not all 87 extracted links enter `url_state_queue`: `queue_literals` (`lines 77–85`) filters by `url_state_page_contexts`, `model_url_keys` (`error IS NULL AND url_key IS NOT NULL`), `url_state_scoped_targets` (`capture_scope`), `target_member_path IS NULL`, and `NOT EXISTS (SELECT 1 FROM url_state_fetched_keys f WHERE f.url_key = k.url_key)`. The 4 self-fragment links (`#main-nav`, `#skip-nav`, `#`, `#`) share the wrapper page's already-fetched `url_key` and are excluded by the `url_state_fetched_keys` check at line 84.
  - Preserving separate `url_key` identities for a wrapper landing page (`/download/<slug>`) and its downloadable document (`/download/<slug>?download=1`) is sound model design, not a defect.

---

### Point 4: Preserving Exact Replay Validation in Wayback Discovery (`discovery.py`)
- **Verified in [packages/corpus_recovery/src/corpus_recovery/discovery.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L117-L246)**:
  - `wayback_lookup` returns a plain `dict` (`{'complete': ..., 'reason': ..., 'candidates': ..., 'evidence': ..., 'window': ...}`); there is no `DiscoveryOutcome` class in `discovery.py`.
  - Returning `([], None)` from `_wayback_page(body)` when `json.loads(body)` is `[]` allows the pagination loop in `wayback_lookup` (`lines 166–215`) to retain any prior pages' `candidates`, `evidence`, and `window` and finish cleanly with `complete = True, reason = 'complete'`.
  - Validating a non-null query SURT (`query_key = key(original)`) against both `row['urlkey'] == query_key` and `key(row['original']) == query_key` (after `_source_url(row['original'])`), setting `candidate['target_url'] = original`, `candidate['original_url'] = row['original']`, `replay = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"`, and `ident = (row['timestamp'], row['original'], row['digest'])` means [acquire_candidate](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L227-L239) passes `candidate['original_url']` to `acquire_wayback` $\rightarrow$ `validate_wayback_replay`.
  - Thus `validate_wayback_replay` (`lines 117–126`) **remains 100% untouched** and continues to enforce exact host, timestamp, and URL matching on the archived spelling.

---

### Point 5: Fetch-Selection Across Existing `url_state` Rows & Campaign Membership
- **Verified in [capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L377-L406) and [url-normalized.sql](file:///Users/mikewolfd/Work/congressional-tech/model/sql/url-normalized.sql#L45-L52)**:
  - `url-normalized.sql` exports `(url, error, still_wrapped, base_key)`; internal CTE column `u.value` is not exported.
  - Sorting observed seed literals cannot synthesize `?download=1` when the only observed literal ends in `&download=1`.
  - In `capture_scheduler.py:392-396`, existing `url_state_latest` rows (`keyed_states`) use `s.requested_url` directly and suppress same-`url_key` rows from `seed_urls` (`LEFT ANTI JOIN keyed_states s ON o.url_key = s.url_key`).
  - In campaign mode (`capture_scheduler.py:381`), eligibility requires `EXISTS (SELECT 1 FROM campaign_targets t WHERE t.target_url = scoped.requested_url)`.
  - Therefore, repaired candidate generation must retain the observed `url` / `requested_url` and `campaign_targets.target_url` binding while supplying the admissible repaired fetch candidate across all four cases: (1) lone `&download=1` seed, (2) mixed `&download=1` and `?download=1` seeds, (3) existing `&download=1` state row with or without a `?download=1` seed, and (4) campaign targets fetched via repaired candidates (`campaign_candidates`).

---

### Point 6: Withdrawal of Global `(?:%20|/)+$` Path Trim in `url-normalized.sql`
- **Verified**:
  - In `model/sql/url-normalized.sql:48`, `regexp_replace(c.path, '/$', '')` strips at most a single trailing slash (mapping `https://example.gov/report/` $\rightarrow$ `example.gov/report` while keeping `https://example.gov/report//` $\rightarrow$ `example.gov/report/` and `https://example.gov/report%20` $\rightarrow$ `example.gov/report%20`).
  - Replacing `/$` with `(?:%20|/)+$` globally merges `/report`, `/report%20`, `/report/`, and `/report//` into `example.gov/report` across every host.
  - We withdraw Fix 4 (the global `(?:%20|/)+$` path trim) and retain only the targeted `senate-notfound` (`%2F` + `#fragment`) and `download-ampersand-query` (`#fragment` + `%20` before `&download=1`) rules.

---

### Point 7: Exact Artifact Counts, Regex Predicates, SHA-256 Pins & Code Descriptions
- **Exact Artifact Counts & SHA-256 Pins**:
  - `publish_v20/model/evidence/publisher_links.parquet`: **`913,034`** rows.
  - `publish_v20/release/sources.parquet`: **`605,848`** rows:
    - `regexp_matches(url, '%[0-9]{2}')` (two numeric digits, e.g. `%20`): **`16,543`** rows.
    - `regexp_matches(url, '%[0-9A-F][A-F]')` (second hex digit uppercase `A-F`): **`826`** rows.
    - `regexp_matches(url, '%([0-9A-Fa-f][A-F]|[A-F][0-9A-Fa-f])')` (either hex digit uppercase `A-F`): **`987`** rows.
    - `regexp_matches(url, '%([0-9A-Fa-f][a-f]|[a-f][0-9A-Fa-f])')` (either hex digit lowercase `a-f`): **`0`** rows.
  - `recovery_campaign_v1/plan/url-dispositions.parquet` (`sha256: 77f52032b8aea6dc308dd7d910843d8ac561bc5a960bd8663ba164cf1a0cf1f2`): **`1,202,155`** total rows (`35` rows matching `ends_with(target_url, '%20')`).
  - `recovery_campaign_v1/plan_v2/url-dispositions.parquet` (`1,202,155` total rows; `35` rows matching `ends_with(target_url, '%20')`):
    - Generation 1 (post-Wave 4, `sha256: 5f6639a2d55c6075c8be1a4994aac181665cce56465739e645fbf855071dfa3b`): `1,668` pending `&download=1` targets (`1,664` House + `4` Senate); `1,563` accepted under `retained_candidate_repaired_download_query`.
    - Generation 2 (post-Wave 5, `sha256: b551043dac48970c961f0329cf8b89f8917c873608a95399aa3e590511d0aa0b`): `1,415` pending `&download=1` targets (`1,411` House + `4` Senate); `1,563` `retained_candidate_repaired_download_query` + `226` `retained_candidate_repaired_download_query_poppler_verified` + `3` `retained_candidate_repaired_download_query_docx` + `24` `retained_candidate_redirect_location_corpus_match`.
- **Exact Code Descriptions**:
  - `_safe_reference(value)` ([capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L99-L113)): Pure boolean validation helper (`len <= 16384`, no control chars, `validate_record(value)`, `urlsplit` scheme in `{'', 'http', 'https'}`, hostname required when scheme present, no username/password, no `credential_parameters()` query keys). It does **not** call `urljoin` or replace spaces with `%20`.
  - `Fetcher._attempt` ([fetcher.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/fetcher.py#L89-L111)): Loops `for step in range(7):` (up to 6 redirects, returning `error='redirect_limit'` on `step == 6`), not a 10-redirect constant.
  - `lookupUrl(value: string)` ([archive.ts](file:///Users/mikewolfd/Work/congressional-tech/apps/site/src/components/explorer/reader/archive.ts#L25-L36)): Validates via `new URL(value)` (rejecting non-`https?:` and credentials), matches `/^([a-zA-Z][a-zA-Z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(\?[^#]*)?(?:#.*)?$/`, lowercases scheme/host, strips `^www\.`, strips `:80` only for `http` and `:443` only for `https`, and strips a single trailing slash `.replace(/\/$/, '')`.
  - Public `lookup_key` ([archive_format.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_format.py#L61-L82)): First **8 bytes** (`FixedSizeBinary(8)`) of `sha256('lookup:' || lookup_url)`.
  - Recovery eligibility ([archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L159-L167)): Emits `capture_disposition` in `{'excluded', 'satisfied', 'eligible'}` (never `'exhausted'`) and `capture_reason` in `{'scope_exclusion', 'qualified_recovery', 'no_satisfying_recovery'}` (never `'accepted_recovery'` or `'stored'`). For the `53` `/404?notfound=` rows in `release_v2/url_state.parquet`, `37` are `eligible` (`no_satisfying_recovery`) and `16` are `satisfied` (`qualified_recovery`).
  - `http://File URL path: /sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf`: Entered `captures` as a literal `requested_url` in legacy receipt `receipts/documents/2026-09-29/assemble-20260930.jsonl.gz` (`source_id = 59762db1...`). In `url_resolve`, a relative `'File URL path: ...'` string stays under the base host while an absolute `'http://File URL path: ...'` is rejected (`url_key IS NULL`); `campaign.py:83` extracted `host = 'File URL path: '` via regex on `target_url`.

---

## 3. Empirical URL Parsing, Normalization & Recovery Patterns Across Waves 1–6

Across Holistic Recovery Waves 1–6 (`35,552` accepted recoveries in Waves 1–5 + `1,375+` in Wave 6, reducing `needs_acquisition` from `41,111` baseline by over `91%`), seven structural URL and qualification patterns emerged that directly inform `url-rules.json`, `capture-scope.json`, candidate discovery, and qualification:

| Cohort / Pattern | Accepted Recoveries | Structural Root Cause & Pipeline Recommendation |
| :--- | ---: | :--- |
| **1. `http://` $\leftrightarrow$ `https://` & `.xml` $\leftrightarrow$ `.pdf` Siblings (`stored_https_or_pdf_sibling`)** | **17,447** (W1) + **61** (W6) | On `docs.house.gov/meetings/...` and `docs.house.gov/billsthisweek/...`, `http://` links failed `capture-scope.json`'s `^https://` regexes (`min(url)` picked `http://` over `https://`), and `.xml` witness/bill files had already-captured `.pdf` siblings at the identical path stem (`s/\.xml$/.pdf/i`). |
| **2. Legacy & Majority/Minority Committee Subdomain Aliasing (`v1_recovery_provenance`, `stored_r2_exact_filename`, W6 witness-date match)** | **12,592** + **2,008** (W1–W3) + **1,093** + **31** (W6) | Congressional committees routinely rename or split subdomains across Congresses while keeping files in shared or parallel buckets:<br>- `edlabor.house.gov/download/...&download=1` (`31` rows): domain renamed to `democrats-edworkforce.house.gov/download/...?download=1` (HTTP 200 over `$0` Direct).<br>- `democrats-transportation.house.gov/download/<mm>/<dd>/<yyyy>/<slug>&download=1` (`1,369` rows): `?download=1` redirects (`302`) to `/imo/media/doc/<file>.pdf` which returns `403 Forbidden`, **but `1,093` of those witness testimonies are already stored in `capture_evidence.parquet` under the `PW` committee's `transportation.house.gov/uploadedfiles/...` and `docs.house.gov/meetings/PW/...` buckets**!<br>- Drupal multisite authoring hosts (`edit-republicans.veterans.house.gov/sites/republicans.veterans.house.gov/files/...`, `222` rows; `archives-agriculture.house.gov/sites/republicans.agriculture.house.gov/files/...`, `31` rows) embed the canonical production host directly inside `/sites/<canonical-host>/files/...`. |
| **3. Path Case-Sensitivity on Case-Insensitive Committee File Servers (`exact_path_sibling` + W6 `capture_evidence` path match)** | **174** (W2) + **174** (W6) | `url-normalized.sql` lowercases `scheme` and `host` but preserves `path` case (`c.path`). In Wave 6, **155 of 158** `https://democrats-naturalresources.house.gov/UploadedFiles/<file>.pdf` targets were already stored in `capture_evidence.parquet` under `https://naturalresources.house.gov/uploadedfiles/<file>.pdf` (lowercase `/uploadedfiles/` on the majority domain). Case-insensitive path matching in candidate discovery recovers these at `$0` without altering `url_key` case semantics globally. |
| **4. House `/download/<slug>&download=1` $\rightarrow$ `?download=1` + Redirect-Location Filename Matching** | **1,606** (W4) + **229** (W5) + **25** (`Location` match) | Rewriting `&download=1` $\rightarrow$ `?download=1` recovered `1,835` House downloads directly. Even when `/imo/media/doc/<Actual_Filename>.pdf` returned `403`/`404` on the origin host, capturing the `302` `Location` header revealed the true underlying PDF filename (which often differs from the `/download/<slug>` URL slug) and matched `25` existing corpus documents (`redirect_location_corpus_match`). |
| **5. Canonical Cross-Host Coordinate Rewriting (`www.congress.gov` Meeting Docs $\rightarrow$ `docs.house.gov/meetings/...` & `t2GPO` $\rightarrow$ `govinfo.gov`)** | **173** (W6) + **4** (`govinfo_package_pdf`) | `www.congress.gov/<cong>/meeting/house/<event_id>/.../HHRG-<cong>-<cmte><subcmte>-...-<YYYYMMDD>.pdf` encodes the exact `docs.house.gov` coordinates (`<cmte>`, `<cmte><subcmte>`, `<YYYYMMDD>`, `<event_id>`, `<filename>`). Rewriting deterministically to `https://docs.house.gov/meetings/<cmte>/<cmte><subcmte>/<YYYYMMDD>/<event_id>/<filename>` recovers the authoritative PDF directly from `docs.house.gov` over `$0` Direct HTTP. |
| **6. WordPress REST API Discovery Endpoints (`/wp-json/wp/v2/...` vs. `/wp-json/oembed/1.0/embed`)** | **578** (W4–W5) + **858** (W6) recovered; **2,862** oEmbed excluded | HTML `<link rel="alternate" type="application/json" href=".../wp-json/wp/v2/hearings/<id>">` tags on Senate committee pages (`commerce`, `energy`, `drugcaucus`, `hsgac`, `indian`, `intelligence.senate.gov`) put `1,436` `/wp-json/wp/v2/` JSON endpoints into discovery. Unlike `/wp-json/oembed/1.0/embed` (`2,862` rows, excluded in `capture-scope.json`), `/wp-json/wp/v2/` endpoints return structured hearing JSON whose `"link"` field points back to the already-captured HTML hearing page. |
| **7. Post-Fetch Qualification Bottlenecks Masquerading as URL/Acquisition Failures** | **227** (owner-flag PDFs) + **3** (DOCX) + **15** (`>16 MB` PDFs) | Three qualification constraints caused valid HTTP 200 downloads to remain in `needs_acquisition`:<br>1. **Owner-encrypted PDFs (`227` Wave 4 `&download=1` repairs)**: Standard Adobe owner-permission flags (`encryption: yes (owner:...)`, readable without a user password) failed `qualify_pdf_bytes` until decrypted via `qpdf --decrypt` / verified with `pdftotext`.<br>2. **Multi-hundred-page hearing volumes `>16 MB` (`15` PDFs up to `157 MB`)**: Hit `Fetcher` `spool_limit = 16 MB` (`outcome = 'size_limit'`) or `QualificationConfig(max_input_bytes = 16 MB)` until raised to `256 MB` in Wave 6.<br>3. **DOCX downloads (`3` files)** and **0-byte origin files (`3` files, including `ashley-nunes-witness-testimony`)** served by `/download/...?download=1`. |

---

## 4. Final Converged, Production-Ready Fix Plan

### Fix 1 (P0 — Stage 7): Fix Wayback CDX Empty-List & SURT-Alias Handling in `discovery.py` While Preserving Exact Replay Validation
- **File**: [packages/corpus_recovery/src/corpus_recovery/discovery.py](file:///Users/mikewolfd/Work/congressional-tech/packages/corpus_recovery/src/corpus_recovery/discovery.py#L129-L215)
- **Exact Change**:
  1. In `_wayback_page(body: bytes)` (`lines 129–146`):
     - When `rows == []`, return `([], None)` so the caller (`wayback_lookup`) retains prior pages' `candidates`, `evidence`, and `window` and terminates cleanly with `complete = True, reason = 'complete'`.
  2. In `wayback_lookup(original: str, ...)` (`lines 158–215`):
     - Compute `query_key = key(original)` (via `corpus_recovery.cdx.key`); raise `ValueError('Invalid Wayback query URL')` if `not query_key`.
     - For each row, validate `_source_url(row['original'])`, `row['urlkey'] == query_key`, and `key(row['original']) == query_key` alongside the existing `row['timestamp']`, `row['digest']`, `row['statuscode'] == '200'`, and `from_timestamp` / `to_timestamp` window checks.
     - Construct `replay = f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"` and `ident = (row['timestamp'], row['original'], row['digest'])`.
     - Emit candidate with `'target_url': original`, `'url': replay`, and `'original_url': row['original']`.
  3. Leave `validate_wayback_replay` (`lines 117–126`) and `acquire_candidate` (`lines 227–239`) **unchanged**.

### Fix 2 (P0 — Stage 5): Targeted `senate-notfound` (`%2F` + `#fragment`) and `download-ampersand-query` (`#fragment`) Rules in `url-rules.json`
- **File**: [model/registries/url-rules.json](file:///Users/mikewolfd/Work/congressional-tech/model/registries/url-rules.json#L72-L92)
- **Exact Change** (with no modification to `model/sql/url-normalized.sql:48`):
  ```json
  {
    "id": "senate-notfound",
    "kind": "wrapper",
    "host_pattern": null,
    "pattern": "(?i)^(https?://(?:[a-z0-9-]+\\.)+senate\\.gov)/404\\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$",
    "replacement": "$1/$2",
    "decoder": "percent",
    "sample": "https://www.judiciary.senate.gov/404?notfound=download/01/06/2026/benton-sjq",
    "sample_basis": "Senate ColdFusion 404 redirect preserves requested target path"
  },
  {
    "id": "download-ampersand-query",
    "kind": "wrapper",
    "host_pattern": null,
    "pattern": "(?i)^(https?://(?:[a-z0-9-]+\\.)*(?:house|senate)\\.gov/download/[^?#]+?)(?:%20|\\s)*&download=1(?:#.*)?$",
    "replacement": "$1?download=1",
    "decoder": "none",
    "sample": "https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1",
    "sample_basis": "CreativeEngine download wrapper links append &download=1 without ?"
  }
  ```

### Fix 3 (P0 — Stages 2 & 6): Repaired Fetch Candidate Selection Preserving Existing State & Campaign Target Membership
- **Files**:
  - [packages/congress_api/src/congress_api/acquisition/capture_scheduler.py](file:///Users/mikewolfd/Work/congressional-tech/packages/congress_api/src/congress_api/acquisition/capture_scheduler.py#L365-L413)
  - [packages/viewer_publication/src/viewer_publication/archive_url_state.py](file:///Users/mikewolfd/Work/congressional-tech/packages/viewer_publication/src/viewer_publication/archive_url_state.py#L70-L85)
- **Exact Design**:
  - Generate admissible repaired fetch candidates (preferring `https://` over `http://` and rewriting `/download/<slug>(?:%20|\s)*&download=1(?:#.*)?$` $\rightarrow$ `/download/<slug>?download=1`) while retaining the observed `requested_url` state identity and `campaign_targets.target_url` membership across:
    1. Lone `&download=1` seeds (synthesizing the `?download=1` fetch candidate while tracking the target),
    2. Mixed `&download=1` and `?download=1` seeds sharing a `url_key` (preferring `?download=1` and `https://`),
    3. Existing `url_state_latest` rows with unattempted/failed `&download=1` `requested_url`s, and
    4. Campaign mode (`campaign_targets` / `campaign_candidates`), ensuring repaired candidate URLs satisfy campaign target membership (`capture_scheduler.py:381`) without orphaning attempt history or `capture_profile` invariants.
