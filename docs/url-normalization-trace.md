# URL normalization and acquisition trace

The pipeline has reproducible URL-selection and parsing defects. Correcting them can recover addresses and satisfy campaign targets, but those outcomes do not establish additional documents or correct document identity. The accepted `hr-4824` recovery containing H.R. 4755 is a concrete counterexample.

This document reconciles the other agent's reports through `2716e9dc` with the [fifteen-assumption validation](experiments/url-normalization-validation-20261031/report.md) and a fresh comparison of the later Wave 6 artifacts. The [implementation plan](plans/url-normalization.md) gives the resulting priorities. The earlier [response](url-normalization-defense-response.md) remains a record of how the assessment changed.

## Evidence and units

Four outcomes must stay separate:

1. **Address recovery:** a repaired candidate retrieves bytes.
2. **Target acceptance:** the campaign records an accepted decision for an observed target URL.
3. **Document identity:** the returned content is the intended document, representation, and historical version.
4. **Publication gain:** a release contains an additional document that was previously absent.

The checked `publish_v20` has 4,129,878 capture-source rows, 913,034 publisher-link rows, 605,848 published source rows, and 367,008 published document rows. The campaign has 1,202,155 targets. These are different populations. Source-row counts, target counts, distinct hashes, and semantic documents are not interchangeable.

| Campaign generation | Accepted recovery | Needs acquisition | Retained candidate pending | Acquisition excluded | Usable direct |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original `plan` | 0 | 10,924 | 32,161 | 604 | 1,158,466 |
| Frozen `plan_v2` after Wave 5 | 35,552 | 4,589 | 0 | 3,548 | 1,158,466 |
| Latest `plan_v2` after Wave 6 | 37,536 | 2,605 | 0 | 3,548 | 1,158,466 |

The latest generation adds exactly 1,984 accepted targets and removes exactly 1,984 from `needs_acquisition` relative to the frozen Wave 5 generation. The former claim of a 41,111-target acquisition baseline is not supported by the cited original `plan`: it contains 10,924 acquisition targets plus 32,161 pending retained candidates. Their combined 43,085 unresolved targets become 37,536 accepted, 2,944 newly excluded, and 2,605 still pending. A reduction in unresolved targets includes exclusions and is not a document-recovery rate.

The selected-recovery table has 37,542 rows, six more than the accepted disposition count: six selected oEmbed targets remain excluded by scope. [Generation counts, transitions, hashes, and the six exceptions](experiments/url-normalization-validation-20261031/evidence/reconciliation-results.json) preserve this distinction. The numerical Wave 6 reconciliation does not independently validate every new content match.

## Stages 1–8

### 1. Extract links and resolve their page context

**Input:** retained parser readings with `links[].href`, `base_href`, and captured page context. **Output:** resolved target URLs, then separate discovery and publication associations.

[page-contexts.sql](../model/sql/page-contexts.sql) selects successful parsed page contexts, excluding placeholders and XML listings. It includes wrapper pages. [link-contexts.sql](../model/sql/link-contexts.sql) resolves the page base; [link-literals.sql](../model/sql/link-literals.sql) applies the narrowly defined concatenated-file repair only when no wrapper rule matches and the literal has no query, fragment, or whitespace. [link-parts.sql](../model/sql/link-parts.sql) assigns **zero-based** split positions.

[link-targets.sql](../model/sql/link-targets.sql) calls the native `url_resolve`, requires an HTTP(S) result, and applies the recognized-file check to repaired parts. Its errors are `repair_conflict`, `invalid_target`, and `invalid_repair`. [resolved-links.sql](../model/sql/resolved-links.sql) rejects all parts of a literal if a part is invalid. This is distinct from URL identity normalization later in the pipeline.

[publisher-links.sql](../model/sql/publisher-links.sql) associates resolved links with captured source identities through `copy_url_keys`. Acquisition instead uses `resolved_link_targets` in [archive_url_state.py](../packages/viewer_publication/src/viewer_publication/archive_url_state.py). An unfetched target can therefore be discovered without appearing in `publisher_links`.

**Check:** replaying the actual native link SQL on 14,157 retained wrapper contexts extracted 1,193,036 links, resolved 1,193,035, and rejected one. It found 8,053 ampersand download targets; 8,035 had exact state rows and 4,096 occurred in publisher links. All 87 Ashley Nunes links resolved, including its download target already present in state. The publisher-link join did not cause the cited discovery failure. [Replay evidence](experiments/url-normalization-validation-20261031/evidence/discovery-link-results.json).

**Malformed inputs:** the raw readings contain five `mailto:http...` links and one literal `http://File URL path: ...` link. The latter is already malformed in retained publisher input; the URL parser did not invent its host. Narrow prefix removal produces admissible HTTP URLs. Four mailto candidates already have retained and published bill PDFs, and the file-prefix candidate already has a retained Dallin Maybee PDF. One mailto candidate lacks matching retained bytes in this evidence. A missing Congress GPO-wrapper rule also identifies a candidate for an already published bill. [Raw readings](experiments/url-normalization-validation-20261031/evidence/malformed-results.json), [native checks](experiments/url-normalization-validation-20261031/evidence/remaining-results.json).

A nested-HTTP regex is a screening tool, not a count of corrupt links. The raw census includes 35,014 distinct Facebook sharing literals, 2,781 Web Harvest literals, and other valid wrappers. The earlier description of every nested-HTTP match as a concatenation defect is withdrawn.

### 2. Select requests in the scheduler

**Input:** seeds, discovered URLs, retained URL state, scope rules, and optional campaign membership. **Output:** admissible requests with priority and observation history.

[_safe_reference and plan_queue](../packages/congress_api/src/congress_api/acquisition/capture_scheduler.py) have separate jobs. `_safe_reference` validates a reference; it does not resolve it or change spaces. `plan_queue` computes identity keys, selects `min(url)` for seed representatives, preserves existing state rows' `requested_url`, suppresses seed alternatives with the same key, then applies scope and eligibility. Campaign mode additionally requires exact target membership.

**Check:** the actual planner selects the ampersand spelling for a lone ampersand seed, mixed ampersand/question-mark seeds, and an existing bad state row plus a good seed. A real HTTP/HTTPS pair with empty state produces no queue row because the selected HTTP spelling is out of scope; the same pair with retained state selects HTTPS successfully. A controlled substitution that changes the request without preserving the campaign target produces an empty campaign queue. [Seven executions](experiments/url-normalization-validation-20261031/evidence/scheduler-results.json).

The census finds 26,777 HTTP-first groups with an admissible alternative. These are potential exposures, not 26,777 lost documents: historical seed batches, retained state, and other acquisition paths affect actual outcomes. A repair must generate candidates for lone bad spellings and handle existing state and campaign membership; sorting alone is insufficient.

### 3. Fetch, follow redirects, and retain bytes

**Input:** the literal selected request. **Output:** the requested address, final or blocked destination, status, redirect observations, and retained response bytes.

[Fetcher._attempt](../packages/congress_api/src/congress_api/acquisition/fetcher.py) uses seven loop iterations, permitting up to six followed redirects. It resolves `Location` with `urljoin`, checks scope at each hop and on the adapter's final URL, and records failures rather than treating every HTTP 200 as a document. [Receipt privacy](../packages/congress_api/src/congress_api/retention/receipt_privacy.py) sanitizes credential-bearing URL parts before persistence.

**Observed host difference:** 4,062 distinct successful literal `&download=1` URLs are on Finance, Banking, Appropriations, and Budget Senate hosts. The checked House population has 19 HTTP attempts on the Democrats Transportation host, all 410. This supports repaired candidate generation on the demonstrated route. It does not prove a universal House failure rule or internal server rewrite configuration. [Pinned host census](url-normalization-defense-response-evidence.json).

**Limits:** an empty body, incomplete transfer, parser limit, permission flag, or size cutoff can leave a correctly routed request unqualified. Later campaign result labels describe those outcomes; they do not make every remaining target repairable by changing its URL. In Wave 6, the large-PDF retry category has 11 result rows and six qualified selections, not 15 independently verified recoveries in that category. [Latest result census](experiments/url-normalization-validation-20261031/evidence/reconciliation-results.json).

### 4. Build the model's URL input set

**Input:** capture sources, page contexts, resolved links, and recoveries. **Output:** distinct observed URL literals to be keyed.

[source-files.sql](../model/sql/source-files.sql) includes captured sources beyond real-file documents. [source-addresses.sql](../model/sql/source-addresses.sql) carries source addresses and good-fetch requested addresses under its body/context conditions. It is not a table restricted to `record_role='document'`.

[model-url-inputs.sql](../model/sql/model-url-inputs.sql) unions source addresses, qualifying capture contexts, resolved targets, recovery originals, and requested/final capture URLs. Its final filter rejects null/blank literals and the explicit `http://File URL path:%` prefix. Preserving an observed error address is distinct from deciding whether it should be scheduled again.

**Check:** all 80,764 error-response final addresses also enter through the source-address branch, and 80,761 additionally enter as contexts. All 55 Senate `notfound` error addresses survive another branch. Filtering only the final capture union removes **zero** addresses. A broader scheduling policy would need an explicit occurrence-aware definition; deleting address history globally is not supported by this result. [Input-route census](experiments/url-normalization-validation-20261031/evidence/followup-results.json).

### 5. Compute model identity keys

**Input:** URL literals, wrapper/strip rules, and explicit variants. **Output:** `url_normalized(url, error, still_wrapped, base_key)`, followed by `url_keys(input_id, url, url_key, error, still_wrapped)`.

[url-normalized.sql](../model/sql/url-normalized.sql) performs two wrapper passes, parses the resulting URL, normalizes percent encoding, removes the leading `www.`, fragment, and **one** trailing slash, filters configured query parameters, and sorts the remaining query pairs. The original `url` remains unchanged. Query filtering is in this SQL file, not in `url-keys.sql`.

[url-keys.sql](../model/sql/url-keys.sql) validates explicit variants and selects the final key. Invalid inputs retain an error and receive no usable key; they do not necessarily disappear as rows. A changed key does not change the fetch address.

The [current registry](../model/registries/url-rules.json) contains nine rules. The two Senate/download rules were committed in `535375d1`; they are not uncommitted work. The older publication and campaign key-preparation snapshots used the prior seven-rule registry. The current Wayback/LOC rules require fourteen-digit timestamps, and the Proofpoint decoder is named `proofpoint`. Current code, historical artifact behavior, and proposed fixes must be identified separately.

**Confirmed targeted defects:** `senate-notfound` lacks percent decoding and fragment support; `download-ampersand-query` lacks fragment support. Native execution of the proposals changes four Senate spellings and 30 ampersand-fragment spellings. With the separately tested trailing trim, 81 of 34,258 screened URLs change keys; **zero published-source keys change between the current nine-rule normalizer and the proposed correction**. This does not compare the older seven-rule publication policy with the complete proposed implementation. The only newly merged campaign groups are the known GPO error/PDF pair and a Finance clean/error-address pair. The clean Finance hearing itself redirects to an error page in retained captures, so its corrected key does not establish hearing recovery. [Native comparison](experiments/url-normalization-validation-20261031/evidence/normalization-results.json).

**Trailing `%20`:** the audit found no distinct-document collision in the checked corpus and withdrew that objection. Live paired requests for all 27 affected campaign paths yielded five PDFs after trimming, 19 HTTP-200 non-PDF responses, and three errors. All five complete PDF hashes were already published. This supports specific fetch-candidate repairs; it does not establish new documents or universal URL equivalence. The repeated-trailing-slash change in `(?:%20|/)+$` is a separate behavior and should be decided separately. The claim that the audit proved harmful document merges is incorrect. [Live outcomes and body comparison](experiments/url-normalization-validation-20261031/report.md#trailing-20-recovery-and-novelty-checked-separately).

### 6. Determine recovery eligibility and publication association

**Input:** observed URL state, requirements, recovery decisions, and retained captures. **Output:** eligibility/satisfaction and separate document associations.

[archive_url_state.py](../packages/viewer_publication/src/viewer_publication/archive_url_state.py) binds literal `original_url` values, body hashes, policy, target requirement, historical refresh policy, evidence hashes, supersession state, and unambiguous active decisions. It emits `eligible`, `satisfied`, or `excluded`; success has reason `qualified_recovery`. A bare normalized-key join cannot replace these checks.

[provenance-recovery-attachments.sql](../model/sql/provenance-recovery-attachments.sql) associates recovery rows with document components. It uses the key-matched copy component when unambiguous, otherwise the original component. It does not implement the simplified `document_id` join shown in the earlier trace.

**Check:** all 35 selected stored aliases have equal valid native target/candidate keys and complete import/decision bindings. Thirty-three bodies each belong to one published document. The other two are a video and an HTML download wrapper, neither a published document body in this generation. These checks do not independently establish every historical content identity. [Alias evidence](experiments/url-normalization-validation-20261031/evidence/remaining-results.json), [memberships](experiments/url-normalization-validation-20261031/evidence/alias-membership-results.json).

**Document-identity counterexample:** 1,563 accepted ampersand repairs bind to 1,561 complete PDF bodies; all hashes and receipts check, but 1,332 bodies were already published. The accepted `hr-4824` bytes visibly contain H.R. 4755, and the latest Wave 6 plan still accepts that same hash. The existing publication also associates it with `BILLS-118HR4775ih.pdf` filenames. This proves conflicting content identifiers, not the original cause of the mismatch. Format qualification and provenance retention cannot alone prove that the intended bill was recovered. [PDF, rendered page, receipts, and official bill comparisons](experiments/url-normalization-validation-20261031/report.md#accepted-bytes-can-still-be-the-wrong-document).

### 7. Discover and acquire historical archive candidates

**Input:** the target URL and a bounded archive query. **Output:** candidate replay URLs, returned archived spellings, evidence, and a completeness result for the query window.

[discovery.py](../packages/corpus_recovery/src/corpus_recovery/discovery.py) currently rejects empty Wayback JSON lists and requires the returned `original` to equal the query literal. [cdx.py](../packages/corpus_recovery/src/corpus_recovery/cdx.py) supplies SURT, the archive's normalized lookup key. A SURT match is a discovery relationship; replay identity and bytes still require verification.

**Check:** replaying 120 retained index responses against the experimental correction preserves 60 rate-limit failures and all nine previously valid outcomes. Of 51 invalid HTTP-200 responses, 46 become complete and five correctly remain page-limited. There are 145 candidate rows across 15 newly admitted targets. Twelve targets have retained replay bytes matching both SHA-256 and CDX SHA-1, with exact replay identity checks; three do not have matching qualified replay bytes in this evidence. [Replay evidence](experiments/url-normalization-validation-20261031/evidence/wayback-results.json).

The other agent's **237 CDX row occurrences and 88 differing original spellings are confirmed**. All 237 returned spellings have matching SURT keys and can form replay URLs that pass the exact identity validator. But rejecting a page because any original differs discards all its rows: the rejected pages contain 165 raw rows, producing the 145 newly admitted candidates after deduplication. These are compatible counts of different units. Constructing a valid replay URL for 237 rows does not prove retrieval or content identity for 237 documents. [Row-unit reconciliation](experiments/url-normalization-validation-20261031/evidence/wayback-row-unit-check.json).

The proposed fix returns `([], None)` for an empty page, validates a non-null query SURT against both the returned `urlkey` and returned `original`, preserves the campaign target separately, and builds replay/deduplication identity from the returned archived spelling. `validate_wayback_replay` remains exact and unchanged. Digest, status, time-window, redirect, and completeness controls remain necessary. The pagination control uses retained rows with a constructed continuation sequence; it is not proof of complete live archive coverage. [Negative controls](experiments/url-normalization-validation-20261031/evidence/wayback-guard-results.json).

### 8. Publish and look up source URLs

**Input:** published document addresses and the user's lookup spelling. **Output:** matching release document rows.

[archive_format.py](../packages/viewer_publication/src/viewer_publication/archive_format.py) and [lookupUrl](../apps/site/src/components/explorer/reader/archive.ts) implement the release's fixed lookup spelling. The frontend validates with `new URL` but builds the key spelling from the original text: lowercase host, remove leading `www.`, remove only the scheme's default port, strip fragment and one trailing slash, and preserve query bytes. It throws on invalid input; it does not return `null`. The key is the first eight SHA-256 bytes of `lookup:` plus that spelling. This has a different purpose from model identity or archive SURT.

**Check:** all 605,848 exact published source rows find their expected document. Actual frontend-function comparisons and six reader journeys against the manifest-verified local release establish these alternate-spelling outcomes:

| Variant | Source-row cases | Expected document | No result | Other rows only |
| --- | ---: | ---: | ---: | ---: |
| Browser-serialized spaces | 472 | 2 | 470 | 0 |
| Lowercase percent hex | 987 | 1 | 986 | 0 |
| Repaired download query | 4,270 | 10 | 4,256 | 4 |
| Removed Congress `q` | 174 | 0 | 174 | 0 |
| Removed tracking parameters | 13 | 0 | 13 | 0 |
| Unwrapped timestamped Wayback URL | 67 | 10 | 54 | 3 |

These are source-row/variant pairs, not distinct missing-document counts. The four download-query differences involve JSON wrapper versus PDF/other JSON rows; the three Wayback differences involve separate HTML bodies with the same hearing titles. Broader lookup aliases therefore need explicit association behavior, not an assumption that every alternate spelling identifies one interchangeable document. The existing exact lookup format is not broken by this evidence. [Results](experiments/url-normalization-validation-20261031/evidence/lookup-summary.json), [reader journeys](experiments/url-normalization-validation-20261031/evidence/lookup-journeys.json).

## Representative outcomes

| Observed input | What the evidence establishes | What it does not establish |
| --- | --- | --- |
| `mailto:https://www.congress.gov/116/bills/hr7045/BILLS-116hr7045ih.pdf` | The malformed literal is rejected; its repaired bill PDF already exists in publication. | A new document gained by repairing this link. |
| `.../ashley-nunes-witness-testimony&download=1` | The download link reached state. Wave 4's repaired request retained an empty response with unresolved qualification; both target/base remain eligible in the latest state. | Successful recovery or publication of Ashley's testimony, or a claim about the server's permanent contents. |
| Finance `/404?notfound=hearings%2F...#main-nav` | Fragment and encoded-slash key defects reproduce; the clean retained hearing request redirects to the error address. | Recovery of the hearing after correcting its key. |
| GPO `DEEPWATER_ReporttothePresident_FINAL.pdf%20` | Spaced URL returns 404; clean URL returns the already published 17,746,116-byte PDF. | A collision between distinct documents or an additional published body. |
| `.../hr-4824&download=1` | Repair retrieves a parseable PDF and receives an accepted decision, but the content identifies H.R. 4755. | Correct recovery of the bill named by the URL. |
| Wayback returned `http://`/`:80` spelling | Corrected discovery can preserve exact returned replay identity and validate retained digest-matching bytes. | Semantic identity from SURT alone or archive completeness beyond the checked query. |

The implementation remains proposed. See [the implementation plan and acceptance checks](plans/url-normalization.md) before treating any mechanism or campaign status count as production acceptance.
