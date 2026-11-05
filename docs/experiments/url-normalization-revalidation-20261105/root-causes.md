# Remaining URL findings: root-cause analysis

November 5, 2026. Three agents investigated before any ticket changes or implementation: one blind greybeard reviewer, one ETL reviewer for identity and lookup, and one ETL reviewer for recovery and campaigns. The parent checked the relevant source and reconciled their findings.

**The remaining issues have different owners.** The wrong bill association comes from promoting filename claims into document identity without considering contradictory body evidence. Alternate-address lookup follows a deliberately narrower rule than acquisition. The twelve audited Wayback bodies are absent before the selected model's publication stage; their upstream custody and acceptance remain unresolved. Scheduled capture is disabled, campaign requirements are not selected, and the recovery-note producer still generates text that publication filters out.

These findings do not justify reopening all normalization work or applying one recovery guard to every published PDF.

## Evidence boundary

- Source: `c3ee2eec686ebcfe77140840b6c2f5fcc3a7bcbf`.
- Public pointer and connected MCP: `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`.
- Reused the preceding [release revalidation](report.md): eight hash-verified public assets, the actual reader's lookup results for all 580,383 source occurrences, retained MCP responses, and 136 passing focused tests. Those tests were a partial run, not a full lane.
- New evidence includes a retained 66,128-byte PDF probe, limited synthetic controls of the bill-text helper, live MCP and GitHub reads, two hash-verified selected recovery-input files, and a bounded scan of retained capture evidence. The latter used 0.42 GiB peak RSS and about two seconds under the required watchdog.
- No production code, ticket, workflow setting, provenance record, or public release was changed. No acquisition campaign, full corpus rebuild, or full test lane was run.

## Findings and minimum completion evidence

| Finding | First relevant boundary | Classification | Minimum completion evidence |
| --- | --- | --- | --- |
| H.R. 4755 content published as H.R. 4775 | Filename claims become package and measure associations | Confirmed data error; existing policy lacks content adjudication | Remove unsupported package and direct bill associations for the demonstrated body, preserve raw claims, and verify both fields through the selected release and MCP |
| Alternate URL spellings miss lookup | Fixed public lookup keys differ from capture keys | Deliberate existing behavior; additional alias capability needed | Supported alias cases resolve while existing keys, all matching editions, and non-equivalent controls remain intact |
| Twelve audited Wayback bodies not delivered | No matching body in selected capture evidence and no matching decision in selected recovery inputs | Confirmed selected-input gap; upstream cause partly unresolved | Per-target custody, acceptance, import, selected-input, and publication disposition |
| Ashley target not delivered through its recorded URL | Discovery finds the file link, but selected file acquisition is absent | Confirmed acquisition gap; invocation/cutoff history unresolved | Explain the exact target's queue and receipt outcome, then follow qualified content through public attachment |
| Capture and campaign behavior lack operational acceptance | Disabled ordinary workflow; release has no campaign requirements | Two separate operational boundaries | One ordinary scheduled capture with receipt/body proof; separately, a requirements-bound campaign execution |
| Recovery explanation remains empty | Reconciler writes provenance boilerplate into an identity explanation | Confirmed producer defect with public compatibility filtering | Producer emits a supported explanation or null; legacy data and attachment remain intact |

## 1. The filename parser is doing what it was asked to do

For body `f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee`, both source filenames say `BILLS-118HR4775ih.pdf`. The body says *Privacy Enhancing Technology Research Act* and identifies H.R. 4755. MCP publishes `BILLS-118hr4775ih` and `118-hr-4775`.

The path is explicit:

1. [Source annotation](../../../model/sql/source-annotations-final.sql) derives package and measure claims from the filename reading. It preserves the publisher's wrong name accurately.
2. [Package selection](../../../model/sql/document-packages.sql) checks whether filename-derived bill candidates disagree. Both names agree on the same wrong number, so the conflict flag stays false.
3. [Document metadata](../../../model/sql/document-metadata.sql) independently unions filename-derived `measure_keys`. Clearing `package_id` alone would leave the wrong bill association searchable.

This matches the existing data-model policy. The missing capability is adjudicating a source claim when the retained document contradicts it. Recovery [acceptance](../../../packages/corpus_recovery/src/corpus_recovery/acceptance.py) performs a bill-text check on its own path; ordinary original-document aggregation does not use it. Existing provenance review verdicts have no package or measure override, so a correction is not an already-supported configuration toggle.

**Smallest repair boundary:** the demonstrated body's document-level package and direct measure assertions, with recorded evidence for the decision. Preserve the bytes, URLs, captured filenames, and source annotations. Do not automatically replace the package with `BILLS-118hr4755ih`: the body is a draft, and the identified bill does not establish an introduced-version package. A supported adjudication mechanism or narrowly defined aggregation rule needs an explicit design; hiding the document or suppressing it only in the reader would leave the underlying issue.

The recovery helper is not a universal substitute. The real retained PDF produces a contradiction for 4775 and 4824, and no bill-number contradiction for 4755. Synthetic controls show that an unnumbered draft becomes unverified, an additional reference to another bill can produce a conflict, and the same bill number in another Congress does not fail the text helper. These controls establish the helper's scope, not that the complete recovery decision accepts a mismatched Congress: that decision separately compares target and candidate identifiers.

Use the demonstrated body and agreeing-filename controls to qualify any future change. Do not infer a need for a global PDF scan from this one case. Existing `ct-flg9` addressed disagreeing filenames; `ct-j9o7` concerns missing package IDs. Neither is the exact demonstrated failure.

## 2. Public lookup intentionally does less than capture normalization

The public [lookup producer](../../../packages/viewer_publication/src/viewer_publication/archive_format.py) and [reader](../../../apps/site/src/components/explorer/reader/archive.ts) implement the fixed spelling in data-model section 8.2. They preserve query bytes and percent-encoding spelling. Capture normalization has different responsibilities and can propose a repaired fetch address while retaining the observed target.

All 580,383 exact source occurrences resolve. The release nevertheless misses 1,005 of 1,006 lowercase-percent spelling probes and 4,790 of 4,804 repaired-download probes. All 21 remaining browser-space misses are literal spaces serialized as `%20` (20 Oversight cases and one Rules case). These are lookup cases, not counts of missing documents.

The three Wayback-unwrapping cases that return a different row have distinct body hashes and shared version groups. They are separate representations already linked as versions, not proof of duplicate documents. Replacing lookup keys with acquisition normalization could erase this distinction.

**Smallest repair boundary:** add supported aliases without changing old keys. Start with validated percent-encoding equivalence and the demonstrated browser-space spellings. Qualify download-query repairs, query removal, and archive-address expansion separately; an alias must retain every matching edition. The same repaired address is not evidence that two bodies or editions are identical. No new distinct-document merge from trailing `%20` trimming was demonstrated.

## 3. The Wayback gap is upstream of the selected publication

The current model selects two recovery-decision files dated October 27: 24,028 and 57 records. Both match their recorded hashes. Neither contains any of the twelve October 31 replay hashes or their exact target URLs; neither includes version-2 recovery records. The selected model's retained capture evidence also contains none of the twelve hashes. Current public saved, alternate, and recovery references contain none.

This rules out a reader-only failure for these exact bytes. It does **not** prove that no later import ever happened outside the selected inputs. Nor does it prove that all twelve semantic documents are absent: a current `CHRG-110hhrg41994` record is one lead with different bytes, requiring content comparison before treating it as the same requested document.

All twelve original replay `body_path` locations now fail existence checks. They were temporary paths. The bounded retained-evidence search did not establish relocated bodies or a complete acceptance/import chain; it did not search every possible local or remote store. Historical `body_available: true` and replay checks remain historical evidence, not present custody proof.

**Next discriminating work:** resolve each recorded target and digest to a durable body or an explicit unavailable result; establish its intended relationship; find or produce the acceptance decision and import receipt; then follow those exact records into selected model inputs and public attachment. Reuse retained bodies and sealed stages when their pins match. Only unresolved custody should trigger bounded reacquisition. Compare with current removal notices before assigning them all to `ct-umtm`; twelve hashes do not automatically mean twelve publishable additions.

The [per-target dispositions](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/per-target-dispositions.json) preserve the individual cases and unresolved boundaries.

For Ashley Nunes, the stored base target is HTML classified as a wrapper with `is_real_file=false`. The retained link replay successfully discovers its download link, but no selected download capture or recovery resolves that target. “Stored” therefore does not mean “testimony downloaded.” The first missing handoff is file acquisition, not link discovery. Inspect the intended invocation's queue, cutoff and receipt records to distinguish no invocation, budget cutoff, refusal and failed acquisition. Exact source and target searches remain empty. Other files containing the surname are leads, not verified counterparts; a future acquisition still needs content and relationship evidence.

## 4. Two operational steps remain, with different inputs

The blind reviewer queried GitHub directly: `capture-archive.yml` is `disabled_manually`, and the workflow run query returned no runs. Repository `ARCHIVE_CAPTURE*` variables were absent; environment and organization variables were not inspected. The disabled workflow itself establishes that scheduled acceptance is incomplete. `ct-4jms` is the existing owner for a successful ordinary run and retained receipt/body evidence.

Separately, the current model selects no recovery requirements and publishes capture-profile version 1. The scheduler intentionally refuses a campaign without version 2, matching requirement pins, and explicit eligibility columns. This is a missing campaign-specific input and execution boundary, not a reason to weaken those checks or call the ordinary release invalid.

Complete ordinary scheduled capture and requirements-bound campaign execution separately. Local candidate-selection tests, the public release gate, and due retry timestamps do not establish either outcome. This investigation does not establish why the workflow was disabled or whether organization policy currently permits enabling it.

## 5. The explanation producer still needs correction

The reconciler writes `Reconciled from pinned accepted mappings …; receipt categories preserved` into `identity_note`, even though the pin already has its own evidence field. The model strips that exact generated text. Current MCP consequently shows 12,618 recovery occurrences and no non-null identity notes.

`ct-nh41` already owns the precise repair: emit an evidence-supported explanation of the recovered document's relationship, or null. Preserve historical immutable decisions and keep compatibility handling for supported old inputs. This is metadata work; it does not require fetching or reparsing bodies.

The same population contains 11,166 distinct recovery body hashes and 11,238 associated document rows. None measures newly delivered semantic documents. The campaign planner already maintains per-target dispositions. `run_recovery_campaign` returns its initial plan/counts even when imports run afterward; those values cannot establish final campaign progress without updated state and replanning. This is a reporting boundary, not proof that a current public count is incorrect.

Join the existing target ledger, qualification records, acknowledged imports, and release comparison to report separate target, qualified-body, accepted-relationship, imported, attached, and new-publication counts. Pin each to its input and release. The public recovery table alone cannot reconstruct the original campaign denominator; no new metrics framework is needed.

## Changes to the earlier recommendations

- Replace “apply the same guard to existing publications” with a bounded, content-supported document-association decision. Package and measure associations need separate verification.
- Describe lookup aliases as an additional capability. The existing exact-source lookup and fixed key format are working as specified.
- Replace “publish the twelve verified recoveries” with resolving twelve historical replay dispositions. Replay verification alone does not establish current custody, accepted identity, or publication gain.
- Split ordinary scheduled capture from campaign-specific release inputs and execution. Version 1 is valid for ordinary operation.
- Keep retry-policy changes conditional. Existing failure counts do not demonstrate that the deterministic retry schedule is wrong.
- Extend existing release checks with the demonstrated cases; do not introduce another gate framework or reopen implemented normalization solely because these separate boundaries remain incomplete.

## Review records

The main checkout retains the [investigation directory](../../../.cache/archive-release/investigations/url-root-cause-20261105/), including:

- [Blind greybeard review and exact GitHub commands](../../../.cache/archive-release/investigations/url-root-cause-20261105/greybeard.md).
- [Identity and lookup report](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/REPORT.md), [probes](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/probe-results.json), and [live MCP evidence](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/live-mcp.json).
- [Recovery and campaign report](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/report.md), [selected recovery inputs](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/selected-recovery-input-check.json), [capture/publication handoffs](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/handoff-check.json), and [resource report](../../../.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/handoff-watchdog.json).

Root causes are established for the identity-selection gap, lookup behavior, and note authoring. The selected-input and operational gaps are established; the twelve bodies' earlier custody/import history and the reason for the disabled workflow remain unresolved. No ticket was created, reopened, or closed by this investigation.
