# Removal-notice source evidence: one USAID cohort

The source-evidence handoff supports one USAID document candidate. It preserves
all 429 removal-notice dispositions and extends the existing ledger for the
twelve audited Wayback pairs. No campaign, candidate acquisition, import, model
run or publication was performed. `ct-umtm` remains open because its release and
reader acceptance is incomplete.

The checked base is `742dbe70b42f0618e95816cd7cf0e6ba2f9939b0`. The freshly read
public pointer still selects `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`.
The retained audit names capture snapshot `8278161579173569099`. The selected
live-input record, model specification, historical replay audit and both selected
recovery-decision files still match their recorded hashes. The prior selected
capture/publication scans were reused; this work does not qualify the release
coordinator's newer candidate.

Durable evidence is under
`/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/reviewed-non-news-20261106/ct-umtm/`.
Start with [the reconciliation](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/reviewed-non-news-20261106/ct-umtm/reconciliation.json)
and [the cohort descriptor](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/reviewed-non-news-20261106/ct-umtm/cohort/campaign.json).

## The bounded cohort

[ecoi catalog record 2074278](https://www.ecoi.net/en/document/2074278.html)
explicitly associates its native catalog identifier with both the literal old
USAID request and the selected mirror URL. Its metadata names Fact Sheet #16,
fiscal year 2022, dated May 20, 2022. The retained qualified PDF's cover confirms
that issue and date.

| Field | Selected value |
| --- | --- |
| Requirement | `requested_content` |
| Refresh policy | `historical_only` |
| Proposed relationship | `recovered_document`, subject to the existing acceptance/import path |
| Original request | `https://www.usaid.gov/sites/default/files/documents/2022-05-20_USG_Ukraine_Complex_Emergency_Fact_Sheet_16.pdf` |
| Mirror | `https://www.ecoi.net/en/file/local/2074278/2022-05-20_USG_Ukraine_Complex_Emergency_Fact_Sheet_16.pdf` |
| Mirror body SHA-256 | `dd7d7f3536700f1b41bc6e7e504b40b168c089aed249158be384efbdff77bee9` |
| Body size | 361,013 bytes |
| Catalog identifier authority | ecoi.net; the identifier is not issued by USAID |
| Catalog review | Named AI review, raw HTML pin and exact extraction fields retained |

Both identifier specs derive from **one catalog record explicitly linking two
URLs**. They are not independent publisher confirmations. `document="2074278"`
is copied from `dc.identifier`; no identifier was assembled from the filename,
title or issue number. The PDF itself does not print this catalog identifier.

`scripts/corpus_recovery/prepare_ecoi_notice_candidate.py` prepares the pinned
reviewed metadata and exercises the maintained `identity_source()` reader.
It requires the literal original URL, exact mirror link, matching catalog ID,
title and complete date. It performs no HTTP requests or imports and leaves
acceptance `review_required`. The real artifacts are in `usaid-2074278/`; the
one-target tables and descriptor are in `cohort/`. `cohort/source-evidence.json`
is supporting evidence, **not an import request**.

The retained Duke PDF also still matches its all-page qualification, but its
shared source-native identifier is unresolved. NCJ 304432 has not been bound to
both the literal original request and the selected mirror bytes. Keep it under
review rather than inventing identifier equality.

## What ct-rie2 and the release owner must finish

1. Preserve the cohort's original descriptor/request bindings. Select the actual
   version-2 requirements, state/profile and explicit eligibility through the
   maintained path; this evidence package does not select those inputs.
2. Set `match_basis` to `source_catalog_document_identifier` in the import
   request. The importer preserves this catalog attribution in the receipt and
   decision; ecoi's ID does not identify the original publisher's record.
   `ct-nh41` continues to own authored public explanations.
3. Obtain one complete timestamped receipt for the exact mirror URL using the
   maintained capture path. Cap its body at 361,014 bytes. Reuse the retained
   qualification only if the body remains exactly 361,013 bytes with the pinned
   digest and validator/configuration. A changed or failed response remains
   separate evidence. The catalog-page observation cannot supply this receipt.
4. Run the existing acceptance/import once, reconcile the operation acknowledgement
   and receipt key, then follow those exact inputs through the release comparison,
   reader and MCP. Preserve the USAID homepage keys `5c1767950ecb2bdc` and
   `0bf90c57369641ee` with null successors: a PDF is not a successor to homepage
   bytes. A new target/body attachment and a new semantic document are separate
   counts; semantic gain remains unproved until the candidate comparison.

## Remaining notice and Wayback dispositions

| Notice disposition | Notices |
| --- | ---: |
| Current document at original address; historical content equivalence unassessed | 375 |
| Exact prior non-PDF body held; source role still needs review | 40 |
| Original PDF request returned a homepage; mirror under review | 2 |
| Historical original address unavailable | 12 |
| Total | 429 |

`notice-dispositions.json` retains every notice key, original-address evidence and
prior body locations. Held HTML, JSON or markup is not counted as a recovered
document. A different current body at the old address does not prove an edition
relationship or justify replacing a retired body key.

`per-target-dispositions.json` extends the earlier twelve-pair ledger. None of
the twelve literal targets or audited body-key prefixes intersects these 429
notices. All twelve exact bodies are unavailable at the recorded temporary paths
and the point-looked-up keys in the five named local stores. This is a scoped
locator result, not evidence of deletion or global absence. Full acquisition
receipts and qualification records/configurations are unavailable in the examined
package; the historical qualification digests remain recorded.

Every pair remains `review_required`, with unknown import acknowledgement and
zero matches in the pinned selected capture/recovery evidence. This session
performed no import. Unknown historical execution is not “not performed.” The
`CHRG-110hhrg41994` official lead has different bytes; content equivalence remains
unproved while the audited replay body is unavailable. The unrelated 116th
Congress suffix match is not an accepted counterpart.

The merged Web Harvest repair `9bb626d9` is an ancestor of this checkout. The
existing notice audit finds no overlap with unfinished historical NARA batches,
so this handoff does not restart those searches or turn access failures into
empty results.

## Verification

The task checkout ran `uv sync --frozen` and used its pinned local-only runtime.
The focused offline test file passed all eight checks, including wrong original
URL, wrong catalog ID, missing mirror link, incomplete date and oversized-input
refusals. The runner reported `production-offline (partial: 1 of 501 lane files;
not a lane result): exit 0`. Existing `sniff`/`readings` workspace-evidence drift
warnings retained their pinned versions and matched their bounded fixed fixtures;
no parser or reading-version change was made.

Both held PDFs and both qualification records were verified against their exact
body, validator and configuration pins without rerendering. The cohort descriptor
passed the maintained loader and custody checks. The independent consultant
confirmed that the catalog ID is native evidence and identified the importer
attribution gap. No full lane, full-corpus build or deployed recovery is claimed.
