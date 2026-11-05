---
id: ct-umtm
status: open
deps: []
links: [ct-9lxf, ct-tk10, ct-rie2]
created: 2026-11-02T17:20:05Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recovery, phase2]
---

# Recover documents behind the archive's removal notices

Start with the selected release's removal notices, then the remaining dead links. Release `e145d24c389e` retained 429 notices. Account explicitly for the twelve replay target/body pairs in the October 31 Wayback audit, including pairs outside that notice population. Reuse completed searches and verified recoveries before reopening historical batches. The earlier NARA run verified ten Veterans Affairs transcripts and left other batches unfinished.

## Root causes (2026-11-05)

The historical NARA worker batched escaped URL keys before adding the complete query and encoding its separators. One retained direct response rejected a 4,207-byte request line against a 4,094-byte limit. Shorter retained requests succeeded, and proxies also rejected the oversized requests. This is a confirmed failure before index lookup; HTTP 429, verification pages and proxy errors are separate access conditions. Overlap with the current 429 notices remains unmeasured.

The twelve audited Wayback hashes are absent earlier than public rendering: none occurs in selected capture evidence or the two selected October 27 recovery-decision files (24,028 and 57 records, both hash-verified). No selected recovery decision names their exact targets. Their recorded temporary body paths are unavailable. This does not establish deletion, absence in another store, or that no import occurred elsewhere. The October 31 replay experiment verified bodies and recorded qualification digests; it did not itself author identity-acceptance decisions or import them. `campaign.import_candidate`, retained-import ingestion and model input selection own these successive handoffs.

An official `CHRG-110hhrg41994` document is a possible counterpart to one target, with different bytes; content equivalence remains unproved. Twelve body hashes are not twelve demonstrated missing semantic documents or twelve ready-to-publish recoveries.

## Smallest useful change

Join notices, original targets and the twelve audited pairs to durable custody, qualification, acceptance, import acknowledgements and selected input records. Resolve the first missing handoff for each pair. Reuse held bodies and completed stages when their pins match. Shorten only applicable oversized NARA requests; reacquire only a bounded unresolved cohort after locating existing evidence. Keep source-identity decisions separate from successful downloads.

## Acceptance Criteria

- Pin the current release, capture snapshot and recovery inputs. Retain a disposition for all twelve audited pairs and every selected removal notice; report their intersection and keep targets outside the notice population visible. The initial twelve-pair ledger is `per-target-dispositions.json` under the evidence directory below.
- For each audited pair, record the current body location or a scoped unavailable result, acquisition receipt, qualification digest/configuration, accepted/rejected/review-required decision, import operation acknowledgement and receipt key, selected capture/provenance membership, and published attachment or explicit reason it is absent. Unknown and not-performed remain distinct from rejected or failed. Do not close unresolved work by treating missing evidence as a negative decision.
- If an acknowledged import exists, trace its receipt into the selected snapshot before attempting another import. Otherwise finish the maintained acceptance/import path only for candidates whose source relationship is established. Preserve original evidence and independently assess Congress, bill/version, document class, person and hearing date where applicable. Compare the `CHRG-110hhrg41994` lead by content before calling it equivalent.
- Reuse valid completed scopes and qualifications. For applicable NARA failures, verify the fully serialized request line fits the observed route limit and preserve incomplete/access-limited outcomes separately from valid empty results. Record exactly which targets needed new acquisition or qualification and why.
- Publish accepted additions through the maintained release path with Gate 1 cause records. Verify the exact target/body attachment, any changed notice, and the supported relationship through the selected reader and MCP. A non-published candidate needs an evidence-backed final disposition; a remaining pending candidate keeps this acceptance incomplete.
- Reconcile cohort totals from target dispositions through qualified bodies, accepted relationships, acknowledged imports, attachments and additions relative to the base release. Count distinct bodies and semantic-document gains separately; retain alternate-version, unresolved, refused and excluded outcomes. Reuse the existing ledger and release comparison rather than adding another metrics system.

## Coordination and evidence

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). Detailed evidence: `.cache/archive-release/investigations/url-root-cause-20261105/etl-recovery-campaign/`, especially `selected-recovery-input-check.json`, `handoff-check.json` and `per-target-dispositions.json`. The historical replay list is `docs/experiments/url-normalization-validation-20261031/evidence/wayback-results.json`.

The [MVP root-cause plan](../docs/plans/production-mvp-root-causes-20261105.md) retains the NARA request evidence. Preserve `.cache/document-bulk-recovery-20261014T1552Z/nara/` and `.cache/nara-filename-estimate-20261015/` under [ct-9lxf](ct-9lxf.md). [ct-tk10](ct-tk10.md) owns existing release gates. [ct-4jms](ct-4jms.md) owns the Ashley Nunes queue/capture trace; use this recovery ticket only if that trace establishes a need for an alternative candidate. [ct-rie2](ct-rie2.md) owns version-2 requirements and execution; its closure is not a substitute for these per-target dispositions.

## Notes

**2026-11-02T22:27:53Z**

2026-11-02: the merge-by-fingerprint conflicts expose likely wrong accepted recoveries (statement link to biography body; congress 103 vs 114). The recovery round should re-verify accepted recoveries whose link and copy disagree on congress, document class, person or hearing date.

**2026-11-05T20:18:07Z**

Integrated full encoded-request length limits and selective retry of server-rejected Web Harvest batches. The 429 current removal notices do not overlap the unfinished historical NARA batches. Two mirror PDFs passed all-page qualification but still lack complete timestamped capture evidence and final identity admission; they remain candidates, with no invented successors for the old HTML keys. Broad recovery remains open. Full build/publication waits all waves.
