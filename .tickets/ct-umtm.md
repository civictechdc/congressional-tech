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

Researchers following retired links need a supported recovery or a clear account of the missing document. Baseline release `e145d24c389e` retained 429 notices. Account explicitly for the twelve replay target/body pairs in the October 31 Wayback audit, including pairs outside that notice population. Reuse completed searches and verified recoveries before reopening historical batches. The earlier NARA run verified ten Veterans Affairs transcripts and left other batches unfinished.

## Root causes (2026-11-05)

The historical NARA worker batched escaped URL keys before adding the complete query and encoding its separators. One retained direct response rejected a 4,207-byte request line against a 4,094-byte limit. Shorter retained requests succeeded, and proxies also rejected the oversized requests. The failure happened before index lookup. HTTP 429, verification pages and proxy errors are separate access conditions.

The twelve audited Wayback hashes are absent earlier than public rendering: none occurs in selected capture evidence or the two selected October 27 recovery-decision files (24,028 and 57 records, both hash-verified). No selected recovery decision names their exact targets. Their recorded temporary body paths are unavailable. This does not establish deletion, absence in another store, or that no import occurred elsewhere. The October 31 replay experiment verified bodies and recorded qualification digests; it did not itself author identity-acceptance decisions or import them. `campaign.import_candidate`, retained-import ingestion and model input selection own these successive handoffs.

An official `CHRG-110hhrg41994` document is a possible counterpart to one target, with different bytes; content equivalence remains unproved. Twelve body hashes are not twelve demonstrated missing semantic documents or twelve ready-to-publish recoveries.

## Merged repair and remaining recovery

Local `main` includes `9bb626d9` through merge `18049548`. The Web Harvest worker bounds the fully encoded request line and splits batches on explicit length refusals.

The audit accounted for all 429 notices. It found 417 original addresses, of which 375 point to current documents with different bytes. None of the addresses overlaps the unfinished historical National Archives batches. Of the 42 addresses without a current document, 40 exact historical bodies were held JSON, HTML or markup. The other two original PDF requests returned publisher homepages. [Notice audit](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/removal-notices/summary.json) · [Held-body checks](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/removal-notices/priority-local-bodies.json).

The Duke paper and USAID fact sheet mirror copies passed all-page qualification. The campaign reports two pending candidates and zero importable records. Each needs a complete timestamped receipt for the mirror bytes and source evidence tying the literal original request to the publication's identity. The old homepage keys retain null successors. [PDF evidence and proposed relations](../.cache/archive-release/implementation/production-mvp-20261105T190929Z/dates-captions-recovery/removal-notices/qualification-handoff/REVIEW.md).

The release coordinator owns disposition of the two PDF candidates, the twelve historical Wayback pairs and the remaining edition and address gaps. Keep accepted relationships separate from incomplete evidence in the final comparison and selected-release reader checks. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md).

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

**2026-11-06T18:43:09Z**

Local source-evidence preparation is complete in 81eb31ca1029b23ae5f37dbefda2286092ac67ea: one USAID requested-content cohort is supported by ecoi catalog record 2074278; all 429 removal notices and twelve audited Wayback pairs have explicit dispositions, with zero exact target/body-prefix overlap. Eight focused tests passed (partial lane). A fresh independent GPT-6.1 Sol xhigh reviewer loaded all four requested skills and APPROVED this exact bounded source/evidence slice after checking actual source, callers/consumers, tests and retained originals; no ct-umtm patch was requested. Review: .cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-umtm/REVIEW.md. No candidate acquisition, import or publication is established.

Remaining: the root rollup writer must integrate ct-rie2's existing catalog-attribution repair with ct-nh41 explanation handling before import; the observed reviewed rollup still had the old basis. ct-rie2 owns its active acknowledgement-validation repair and coordinated version-2 capture/import preparation; ct-m104 owns final shared build/publication and reader/MCP acceptance. Duke identity and twelve Wayback custody records remain review-required pending original evidence. Keep ct-umtm open: approval of local evidence preparation is not delivered recovery or full ticket acceptance.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-umtm/REVIEW.md).
