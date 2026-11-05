# URL recommendations revalidated against the November 5 release

The address-repair mechanisms have largely landed. The remaining work is to resolve audited recoveries' acceptance and publication disposition, correct existing document-identity errors, and support additional URL spellings in public lookup. The October plan's blanket “proposed implementation” status is stale; neither code completion nor today's broader release checks close every original acceptance criterion.

The subsequent [three-agent root-cause analysis](root-causes.md) narrows these recommendations: the bill error comes from agreeing wrong filenames; lookup implements a deliberate fixed spelling; the twelve replay bodies are absent from selected inputs before publication; and ordinary scheduled capture and recovery campaigns have separate acceptance boundaries.

## What was checked

- **Public release and connected MCP:** `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`, published November 5, 2026. The live public pointer matched the MCP release and remained unchanged through this investigation. The connected `congress` MCP was queried directly, including verified PDF text. The alternate `congressional_tech` connector returned an unknown-tool error; it supplies no independent acceptance evidence.
- **Published population:** 356,735 document rows, 580,383 source rows, 611,729 URL lookup rows, 12,618 recovery rows, and 1,198,646 URL-state rows. These populations have different meanings.
- **Current code:** `c3ee2eec686ebcfe77140840b6c2f5fcc3a7bcbf`. Compared relevant source changes with audit commit `b918438e`. The principal normalization implementation landed in `87833380` on November 1; subsequent scheduler and document-outcome changes were included in the recheck.
- **Release custody:** fetched the live pointer and manifest; rehashed eight cached public assets used by this investigation against that manifest. Checked the actual frontend `lookupUrl` function against every published source row and the release's lookup table. Confirmed seven representative alternate-spelling outcomes through MCP SQL.
- **Focused regression:** 136 tests passed across `test_capture_scheduler.py`, `test_normalized_pipeline.py`, and `test_discovery_runtime.py`. This is a partial production-offline run, not a full lane. It includes all seven retained-address scheduler scenarios, archive guards, malformed-address repairs, and the real conflicting-bill PDF with a positive control. Peak process-tree RSS was 0.54 GiB. Initial preflight refused the default Poppler 26.10.0; rerunning with the existing pinned 26.06.0 installation passed. The pinned DocSpec local runtime was used.

## All eleven recommendations

| Earlier recommendation | Current status | Current evidence and remaining action |
| --- | --- | --- |
| 1. Find more valid Wayback copies | **Parser implemented and tested; publication gain unverified** | Empty lists preserve prior results; returned archive spellings must match the queried archive key; replay identity uses the exact returned spelling. Guard tests pass. None of the twelve body hashes verified in the October experiment appears in current saved, alternate, or recovery body references. Determine the disposition of those recoveries before claiming delivered documents. Their absence as these exact bytes does not prove the documents are absent in every representation. |
| 2. Fix Senate error-page and download-query rules | **Implemented and present in the published profile** | The live profile contains the corrected percent-decoding and fragment patterns. Its ten operational rules match the current registry; examples and explanatory fields are intentionally absent from the profile. The extra Senate download rule and Congress GPO-wrapper coverage have also landed. |
| 3. Make the downloader use repaired addresses | **Implemented and tested** | The native scheduler now chooses admissible candidates, handles existing bad state, prefers in-scope addresses, and suppresses repeated candidate attempts. All seven retained-address scenarios pass. This verifies selection behavior; it does not establish that every old failed target has since been fetched successfully. |
| 4. Preserve the original request, history, and campaign rules | **Implemented and tested; public campaign adoption unverified** | Candidate rows retain the target key and observations; tests cover campaign membership, requirements, satisfied/excluded targets, and candidate attempt suppression. The public release uses capture-profile version 1 and exposes only basic retry history. It does not expose the version-2 campaign eligibility fields needed to demonstrate active campaign completion protections. |
| 5. Verify the intended document | **Partially addressed; a published error remains** | New recovery acceptance detects the real H.R. 4824/H.R. 4755 conflict and leaves it for review. The same bytes remain publicly labeled H.R. 4775, while their first-page text identifies H.R. 4755. Adjudicate the demonstrated document's package and measure associations while preserving raw source claims. The recovery guard cannot safely qualify all ordinary originals or establish Congress/package version from their content. |
| 6. Repair demonstrated malformed prefixes | **Implemented in the recovery path and replayed on the real examples** | All five `mailto:https://…` literals produce HTTP candidates. The relative `File URL path` literal produces its candidate when its page context is supplied; it correctly produces none without that context. Four repaired bill URLs and the repaired Dallin Maybee URL have exact published source rows. The U.S. Code target has no exact source association in this check. These are existing documents, not five demonstrated publication additions. Automatic repair of every malformed meeting/link input is not established. |
| 7. Trim accidental trailing spaces | **Implemented as candidate repair** | The scheduler trims trailing `%20` while retaining the observed target key; recovery discovery also has a path-space repair. The tests cover suppression after a repaired attempt. All five PDF hashes retrieved in October remain published. Repeated-slash policy remains separate; this recheck does not establish universal URL equivalence or new documents from trimming. |
| 8. Support alternate spellings in public lookup | **Partly improved; substantial gaps remain** | Every exact source row resolves. Space-serialized lookups now reach the expected document in 470 of 491 cases, but query and percent-encoding variants still miss frequently. The lookup format still preserves query bytes. Three archive-unwrapped variants lead only to other document rows, so a general alias policy must preserve historical representations. |
| 9. Replace the ineffective error-address filter with a retry policy | **Reframe around the existing policy** | The model still retains observed addresses; filtering one input branch would not remove addresses supplied elsewhere. A deterministic family/age retry schedule already exists. Of 40,779 failed-address rows, 40,758 have a scheduled next attempt. Fifty-two failed rows are Senate `notfound` addresses. These counts do not prove inappropriate retries. Change retry behavior only after specifying which failures should stop or switch to candidates; do not delete history or call the earlier filter an effective repair. |
| 10. Separate recovery counts from document gains | **Still required; descriptions improved** | The release has 12,618 recovery rows, 11,166 distinct recovery body hashes, and 11,238 associated document rows. None is a count of newly verified semantic documents. All 12,618 `identity_note` values are empty; the earlier boilerplate is gone, which removes a misleading explanation but supplies no content-identity evidence. The original campaign target totals cannot be reconstructed from these public tables. |
| 11. Verify the combined publication and reader | **A real release has passed broader checks; original targeted gaps remain** | Today's release has recorded full release gates and live acceptance, and this investigation verified the current pointer, relevant bytes, MCP examples, and all exact source lookups. That supersedes the blanket implication that nothing has reached a validated release. It does not repair the observed bill mismatch, close URL alias gaps, demonstrate delivery of the twelve Wayback bodies, or supply the original seven-rule-to-final campaign/publication comparison. |

## Published bill mismatch, read through MCP

The current document has link key `f984b8439d21b0ef` and body hash `f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee`.

| Evidence | Current value |
| --- | --- |
| Filename | `BILLS-118HR4775ih.pdf` |
| Published package | `BILLS-118hr4775ih` |
| Published measure association | `118-hr-4775` |
| Verified PDF text, page 1 | Privacy Enhancing Technology Research Act; bill stamp `4755` |
| MCP bill record for H.R. 4755 | Privacy Enhancing Technology Research Act |
| MCP bill record for H.R. 4775 | Helping Tobacco Users Quit Act |
| MCP bill record for H.R. 4824 | Carbon Sequestration Collaboration Act |

The current source rows use Congress.gov and docs.house.gov filenames containing H.R. 4775. The old `hr-4824` target is not a current source row for this body. Therefore the current finding is a conflicting **published H.R. 4775 association**, not proof that the latest campaign still accepts H.R. 4824. Preserve the source claims and bytes while reviewing the document's derived association.

The Ashley Nunes download remains in URL state: the base address is recorded as stored from October 12, while the ampersand target has zero attempts. Neither exact target appears in published sources, and a metadata search for “Ashley Nunes” returned no documents. This does not prove that her testimony is absent under another name or inside a larger hearing document; it does show that the repaired-target publication journey remains unestablished.

## Current lookup results

These are source-row/variant cases, not missing-document counts. The script invokes the actual frontend function and checks the resulting key against the hash-verified current release. “Other rows only” means the expected row was absent even though lookup returned another row.

| Spelling tested | Cases | Expected document | No result | Other rows only |
| --- | ---: | ---: | ---: | ---: |
| Exact published source | 580,383 | 580,383 | 0 | 0 |
| Browser serialization of spaces | 491 | 470 | 21 | 0 |
| Lowercase percent-encoding hex | 1,006 | 1 | 1,005 | 0 |
| `&download=1` changed to `?download=1` | 4,804 | 14 | 4,790 | 0 |
| Congress search parameter removed | 174 | 0 | 174 | 0 |
| Tracking parameters removed | 13 | 0 | 13 | 0 |
| Timestamped Wayback wrapper removed | 67 | 10 | 54 | 3 |
| Trailing encoded/literal whitespace removed | 4 | 0 | 4 | 0 |

The final row is a spelling probe, including query-value whitespace; it is not a recommendation to rewrite every such URL. The earlier corpus safety objection to `%20` trimming remains withdrawn. No new distinct-document merge was demonstrated here.

## What remains to do

1. Review and correct the published H.R. 4775/H.R. 4755 package and measure associations, preserving the literal source evidence. Use a bounded document-level decision; do not apply the recovery guard wholesale or infer the exact package version from the bill number.
2. Determine the publication disposition of the twelve audited Wayback bodies and the unresolved Ashley target. Publish only qualified associations, recording alternate-version or scope decisions explicitly.
3. Define and implement lookup aliases for the demonstrated misses, with clear handling of multiple historical records.
4. Demonstrate campaign protections with the actual version-2 campaign inputs and publish metrics that distinguish targets, files, intended documents, and additions to the release.
5. Retain the current exact-source lookup check and add the selected aliases and corrected identities to release acceptance.

The original 120 Wayback response receipts are no longer present at their recorded temporary paths. A bounded filename search under the main checkout's retained archive directory did not find them. Their committed results remain historical evidence; this investigation reran current regression guards and checked their twelve recorded body hashes against the release, not the original 120-response experiment. No fresh origin fetches, full corpus rebuild, full test lane, or deployment was performed for this revalidation.

## Reproduction and evidence

The main checkout retains all new scripts, inputs, measurements, and MCP responses under [the investigation directory](../../../.cache/archive-release/investigations/url-revalidation-20261105/):

- [Release check and lookup results](../../../.cache/archive-release/investigations/url-revalidation-20261105/release-check.json), [Python driver](../../../.cache/archive-release/investigations/url-revalidation-20261105/check_release.py), and [actual-reader lookup driver](../../../.cache/archive-release/investigations/url-revalidation-20261105/lookup.mjs).
- [Initial MCP responses](../../../.cache/archive-release/investigations/url-revalidation-20261105/mcp-evidence.json) and [follow-up MCP responses](../../../.cache/archive-release/investigations/url-revalidation-20261105/mcp-followup-evidence.json), including body text, bill records, lookup examples, malformed-address matches, and all twelve Wayback body checks.
- [Malformed-input replay](../../../.cache/archive-release/investigations/url-revalidation-20261105/malformed-replay.json), [focused regression output](../../../.cache/archive-release/investigations/url-revalidation-20261105/focused-tests-pinned.log), and [test resource measurement](../../../.cache/archive-release/investigations/url-revalidation-20261105/focused-tests-pinned-watchdog.json).
- [Published release note](../../releases/2026-11-05-e145d24c389e.md) and [accepted release comparison](../../../model/jobs/release-causes/e4538f0064e1-e145d24c389e.json). Their full-lane and deployed-browser results were recorded by that release process; they were not rerun here.

Read-only public queries and focused local tests support the findings above. This revalidation changes documentation only.
