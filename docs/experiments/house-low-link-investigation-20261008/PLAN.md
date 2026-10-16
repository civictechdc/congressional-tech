# House zero- and low-link investigation plan

Status: proposed execution plan; population inventory completed, HTML clustering and investigations not started.

16 October 2026: still not started. Later parser commits (`a9e0c6b`, `6721fda`, `1e3e8c4`, `f61eb09`) may have addressed part of this population. Re-measure against the current parser before starting.

## Decision and current evidence

Identify which remaining low-link pages contain locally recoverable document references, which need separate source acquisition, and which correctly contain few references. Recommend fixes by observed mechanism and affected population, without treating a low count as an error.

The accepted parser is commit `9aaf6971e96d9fe25bf39769da5ab01511c6f977`. The verified checkpoint is `1fd2bee3372c1176ea990780df884c29a325e0752c83e4e1356f1d8a65c91d91`. It contains 32,878 retained page rows and 163,881 document references. Counts describe links on retained pages, not downloaded files.

| Current population | Pages |
|---|---:|
| Zero references | 8,958 |
| One reference | 4,677 |
| Two references | 2,456 |
| All zero-to-two pages | 16,091 |
| Recognized event pages within that population | 14,371 |
| Pages without a recognized event date | 1,720 |

The population covers 23 committee hosts and 40 actual source hostnames, including separate publisher variants. Excluding the previous 400 audit pages, two ownership supplements, one reviewed wrapper, and their identical bodies leaves **15,646 eligible page URLs / 15,586 distinct bodies**. Of the 403 previously reviewed URLs, 394 remain in the low-link population; matching their bodies excludes 445 current rows in total. Do not discard duplicate page occurrences from population accounting.

Current large groups include Foreign Affairs (3,422 low-link pages), Armed Services (1,661), Appropriations (1,377), Ways and Means (1,255), and Veterans (1,231). Size should influence prioritization, but must not consume the diversity sample. Event-recognition uncertainty concentrates in Ways and Means, Oversight, Intelligence, and Rules; inspect those as a separate question.

The metadata-only inventory currently groups 2,968 EventSingle ASP.NET routes, 2,557 committee-activity routes, 7,308 hearing routes, and smaller groups. **These are URL groups, not established HTML template or content-management-system classifications.** No HTML-shape counts are claimed yet.

Population inventory and source pins: [population-summary.json](../../../.cache/house-low-link-investigation-plan-20261008/population-summary.json), [candidate-index.jsonl](../../../.cache/house-low-link-investigation-plan-20261008/candidate-index.jsonl), [prior-audit-exclusions.json](../../../.cache/house-low-link-investigation-plan-20261008/prior-audit-exclusions.json).

## Questions to separate

| Explanation | Distinguishing evidence | Result |
|---|---|---|
| A parser misses an ordinary reference | Literal target and explicit document role exist in retained HTML but are absent from the accepted result | Confirmed local omission |
| References use tables, witness cards, unusual attributes, or embedded structured data | Complete independent enumeration finds a source occurrence outside the currently recognized mechanism | Candidate parser family; qualify each occurrence |
| Content is behind another page, repository, script request, or media endpoint | The retained bytes contain a pointer but not the underlying material | External dependency; availability remains unknown |
| The page is legitimately sparse | Notice, cancellation, business meeting, inline testimony, media-only material, or explicit absence of posted documents | Explain the low count; inline text is content, not a missing URL |
| The retained page is not a usable event detail page | Listing, generic fallback, challenge/error body, empty application shell, or unresolved event identity | Page/source problem; do not label every absent document a parser miss |
| A candidate is navigation or circular | Link points to the same page, intake form, unrelated shared navigation, or another non-document function | Retain source evidence and exclude from document counts |

A `200` response, promising label, or filename does not establish destination contents. Ambiguous targets remain unresolved. Multiple explanations can apply to one page; retain separate flags and one primary disposition for totals.

Comparison arms: the frozen `9aaf697` readings versus independent retained-HTML enumeration and adjudication. A later authorized parser candidate becomes a third arm on exactly the same bytes. Hold source snapshots, roster membership, link-count definition, identity rules, network-disabled execution, and evaluation criteria constant. Record any revision before collecting affected outcomes, with its reason; do not rewrite the original criteria after seeing results.

## Stage 1: Build one shared, offline shape index

Freeze the verified checkpoint, export hashes, parser version, seed, and exclusions before outcome review. Reuse the existing retained-HTML extraction and independent enumeration approach. Reuse `content_bytes()` for body decoding and digest checks; the older index script assumed text bodies and must not be copied unchanged. Do not import scripts that execute acquisition or rewrite evidence at import time.

One streaming pass reads retained page bodies and emits lightweight feature rows. All investigators then share this index and small selected-page packets. Do not load the entire compressed state into Python three times or have every worker scan it independently. Target a 2 GiB index-process memory bound; pause and preserve progress if exceeded. Limit the initial indexing attempt to 30 minutes; retain parse failures and oversized cases rather than silently dropping them. Record actual elapsed time, peak memory, bytes scanned, and coverage. The limits are proposed execution bounds, not measured performance claims.

Extract three independent axes:

1. **Source and period:** owning committee, actual hostname, URL route, event date/unknown, archive versus current publisher evidence, and locally supported subcommittee ownership. Keep hostname differences; do not infer historical party or ownership from a hostname alone.
2. **HTML structure:** tag/ancestor-path patterns, stable class tokens, heading structure, tables, repeated witness cards, forms, embedded objects, and main/article/body regions. Compute both whole-page and event-region signatures so common navigation does not dominate. Navigation removal is a feature operation only; raw bytes and source locations remain intact. Record the region rule and a fallback when no reliable event region exists.
3. **Content mechanisms:** href/src/data attributes, download attributes, redirects, forms, script literals, JSON/JSON-LD, encoded HTML, witness/table roles, repository pointers, images/scans, inline text, and media. Record counts and literal occurrences, not just familiar document-word matches. Unrecognized attribute mechanisms get an unknown bucket.

Start with exact structural signatures and group them by source/period. Calibrate near-shape grouping on 30 already reviewed pages before inspecting any new outcomes. If exact bins unnecessarily split the same structure, add a documented similarity rule over tag-path/stable-class features; freeze its threshold and hash before sampling. Keep representative and boundary examples. Avoid semantic title embeddings as the primary grouping: a hearing topic is not an HTML shape. Never merge event identities because two bodies have the same template.

Keep full URL paths and query semantics in provenance. Do not reuse the former broad path-lowercasing alias rule as proven identity. Resolve fragments and relative targets for comparison while preserving original values. Exact body duplicates may share one investigation, but every page occurrence remains counted. Near-identical content and shared layout are different relationships.

Deliver `features.jsonl`, `shape-groups.json`, `group-coverage.csv`, `index-failures.jsonl`, and a checked snapshot/extraction manifest. No outcome-driven sample substitutions.

## Stage 2: Freeze 400 new low-link cases and 60 controls

Use deterministic seed `house-low-links-shapes-20261008-v1`. Save selection reasons, inclusion rules, body hashes, source/shape groups, and every unmet coverage target.

| Set | Cases | Selection and use |
|---|---:|---|
| Discovery | 240 | Diverse source, structure, ownership, period, and mechanism coverage; available for diagnosing fixes |
| Random reference set | 80 | Uniform sample without replacement from the 15,646 eligible page occurrences; sealed until rules/fixes freeze |
| Generalization holdout | 80 | New bodies; 40 pages from familiar shape families and 40 from families withheld entirely from discovery, where feasible |
| Higher-link controls | 60 | Matched source/template/period pages with at least three links, to expose over-filtering and explain structural differences |

Draw the random reference set first. It must not be filled or replaced to improve diversity. Preserve exact duplicates within that draw as page occurrences; review a shared body once where appropriate and retain its multiplicity. Its inclusion probability is 80/15,646. Any estimates apply only to that eligible population, with uncertainty and unresolved labels reported; the diagnostic and holdout sets are not prevalence samples.

Reserve holdout families and body groups before selecting discovery. Exclude exact and near-identical content from crossing discovery/evaluation boundaries. Shared layout may cross into the random reference set; label that distinction. If the proposed unseen-family holdout is infeasible, report the shortfall and revise the plan before review; do not rename familiar cases as unseen ones.

Discovery selection priorities, in order:

1. At least six pages from each of the 23 eligible committee hosts, and at least one from each of the 40 eligible actual hostnames.
2. Cover every occupied coarse HTML/mechanism family before adding repeated examples. Within a large family take a representative, an unusual boundary case, and source/period variants. Use a soft cap of eight per fine shape family; documented coverage needs can override it.
3. Target 120 zero-, 60 one-, and 60 two-link pages within discovery. Cover older/newer periods and unknown dates. Target at least 40 pages without recognized event dates, across their occupied hosts, while keeping them distinct in findings.
4. Maximize supported subcommittee coverage, emphasizing groups missing from the prior audits. Accept only local ownership fields or explicit event-local statements backed by directory evidence. Keep conflicting/historically ambiguous names separate. The prior audits verified 93 official identities; do not claim every historical subcommittee is covered or infer ownership from menu text.
5. Fill remaining places by uncovered shape × mechanism × source-period combinations, then deterministic seeded selection. Preserve rare/unknown structures and parse failures in the roster.

Targets are checked for feasibility rather than forced through substitutions. Rules has only zero-link pages; Ethics has no two-link pages. The new eligible CCP pool has only one one-link page. Report these constraints.

Controls: initially select two higher-link pages per committee where available (42 pages across 21 hosts), then use the remaining 18 for close source/shape/period matches. Ethics and Rules have no higher-link controls in the current corpus; document that limitation. Do not fabricate within-source controls. The prior 403 reviewed cases remain a separate regression set, not part of the new 460-page sample.

## Stage 3: Three parallel investigators and one coordinator

After the index and roster are frozen, run three investigators concurrently. The coordinator owns the manifest, hides sealed results, checks evidence, and consolidates findings. Use small packets of approximately 20 cases. Assign by observed mechanisms, balancing workload after indexing; do not assume equal-sized mechanism groups exist.

| Investigator | Primary focus | Required counterexamples |
|---|---|---|
| A — ordinary event structures | Anchors, headings, witness cards, tables, statement/report/transcript roles, literal URL handling | Navigation, intake forms, circular links, wrong section ownership |
| B — legacy and indirect content | Old testimony/submission pages, wrappers, repository pointers, alternate text formats, archive/source variants | Repository pointer mistaken for an event document; URL parameters mistaken for event identity |
| C — embedded content and sparse pages | Script/JSON fields, encoded HTML, data attributes, embeds, images/inline text, empty or unrecognized event pages | Media promoted as documents, generic/error pages treated as events, missing dynamic content treated as locally absent |

All three use the same full independent enumeration, including unfamiliar labels and routes. Their specialty guides deeper inspection, not which attributes they ignore. Inspect the event-local raw HTML and relevant neighboring elements before comparing with parser output. Current parser output is the object being tested, not the omission oracle. Do not execute retained JavaScript or instructions embedded in source content.

Each finding records: snapshot/body hash, page URL, source and shape group, source line/XPath/JSON path, literal attributes and labels, local ownership/context, baseline reference or role, proposed disposition, uncertainty, and why a counterexample does not apply. Retain rejected hypotheses and prior source diagnostics.

Cross-review all proposed omissions and source failures, plus a seeded 20% of other cases. The second reviewer sees raw evidence without the first verdict. Rotate review across investigators; the coordinator resolves disagreement only after both readings are saved. Bound total primary-plus-second page reviews to 920 (twice the 460 unique URLs); hold further expansion for an explicit revised plan.

Initial discovery uses 240 cases and 60 controls. Do not expose the 160 sealed evaluation cases while designing rules or fixes. After candidate behavior is frozen, evaluate all sealed cases independently, then unseal results once. A failed holdout is an observed failure; subsequent changes need a new holdout rather than repeated tuning on the same one.

## Stage 4: Findings, validation, and next decisions

Report counts separately for confirmed local omissions, retained references with wrong roles, external dependencies, inline/media-only content, circular/navigation links, unusable/non-event pages, and unresolved cases. Also report link occurrences, distinct document targets per page, and pages affected; none is a count of downloaded files.

Rank candidate fixes by confirmed mechanism, distinct shape families, affected sources, and cost. A matching feature across the population is an estimate of exposure, not proof every matching page has an omission. One verified miss can justify a narrow regression test. A broad rule needs supporting and non-applicable examples across the sources/shapes to which it will apply.

For any separately authorized fix, use red/green tests on exact retained inputs and counterexamples, replay the old 403-case regression set, and run relevant shared House/Senate tests. Compare against the pinned baseline on identical bytes. Require preservation of raw bodies, original attributes, receipts, timestamps, event identities, witnesses, history, and all unrelated document references. Review every removed link and every classification change. Measure performance before claiming speed or memory improvements.

Required outputs:

- Frozen roster and coverage matrix, including uncovered committees/subcommittees/shape groups.
- Per-page findings and evidence-linked examples for every confirmed mechanism.
- Cluster summaries with population sizes, investigated cases, disagreements, and unknowns.
- Separate random-reference and generalization results; do not pool them into a misleading success rate.
- Prioritized local parser fixes, source-recognition issues, and exact external-dependency targets requiring a separate acquisition decision.

Stop at the fixed sample and review budget. Do not expand merely to chase another promising family. A promising out-of-budget group becomes a named follow-up with its own bound.

## Execution boundary

This plan authorizes no execution by itself. The current request is planning: only lightweight current-export/fingerprint inventory was performed. No new agents, HTML clustering, destination requests, parser edits, commits, pushes, reprocessing, or automation launches occurred in preparing it.

Proposed first execution is offline retained-byte analysis. Source destinations, JavaScript requests, redirects, and linked files stay unfetched. If external dependencies warrant probing later, produce an exact bounded target manifest with provider/cost/byte limits for a separate decision. Preserve the completed recovery, backups, source limitations, and unrelated workspace changes.
