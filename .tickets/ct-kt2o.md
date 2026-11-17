---
id: ct-kt2o
status: open
deps: [ct-ha10]
links: [ct-46f3, ct-esuu, cat2-pkk1, ct-egoo]
created: 2026-11-11T00:35:01Z
type: feature
priority: 4
assignee: mikewolfd
parent: ct-woj3
tags: [data-model, witnesses, identity]
---
# Define deferred witness identity expansion beyond the delivered people model

## Current state — 17 November 2026

Deferred feature scope. Slice 2 (ct-ha10) has landed: people, person aliases, merge/split handling, person pages and an append-only reviewed-decision registry already exist. The registry is currently empty; that does not make its implementation missing. Retire the stale “acceptance defined when slice 2 lands” wording.

Remaining options are possible-same-person links across organizations, reviewed organization aliases and identity facts supported by archived statements. The retained joint CT/SpicyRegs plan remains the starting point. Reuse existing merge/split/alias infrastructure and keep source-bound identity evidence separate from an automatic person merge.

## Acceptance Criteria for the next bounded slice

1. Define a small first slice from the remaining options, its source evidence, intended consumer and explicit ambiguous outcome. Do not silently turn this parked feature into web acquisition or broad model extraction.
2. Express possible-person links as uncertain links, not automatic equality. Organization aliases alone must not merge people; preserve exact-name/organization and middle-initial/suffix safeguards where those govern identity.
3. Attach extracted identity facts to exact source/appearance evidence and verbatim spans when applicable. Use existing reviewed-decision and person-alias handling for corrections, with historical identity preserved.
4. Qualify the chosen slice against source-read cases and deliberately wrong-identity controls; record false merges and unresolved cases. Reuse delivered slice-2 evidence and UI/API paths instead of rebuilding them.

## Evidence and deferral

The retained `investigations/witness-identity-20261110/PLAN.md` sections 2/6 and `investigations/person-identity-contract-20261111/pc-contract-draft.md` section 7 describe the options. Current infrastructure includes `model/sql/person-aliases-fresh.sql`, `model/registries/person-decisions.json` and ct-ha10's closeout. This ticket remains open at its existing low priority; this editorial update does not start implementation.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`. Historical notes below are retained; the current scope and criteria above supersede their dated unfinished-work summaries.

## Notes

**2026-11-11T03:02:45Z**

2026-11-11 (session congress-1): deferred options the owner will come back to, recorded in .cache/archive-release/investigations/person-identity-contract-20261111/pc-contract-draft.md section 7: organization variant and parent lists as reviewed evidence (never an automatic key); a sentence-cue rule over archived biographies; checkable model extraction with verbatim spans (Fable advisor's trial design and estimates); the owner's SerpApi idea (two independent searches, name plus each organization, returning the same LinkedIn profile address, private evidence only); LinkedIn via RapidAPI or Bright Data left open (the spicy-regs review recommends against). First spicy-regs decision kind: LDA lobbyist to witness appearance after a 50-pair precision read (1,428 names where the lobbyist's firm or client equals the witness organization; 11 of 12 seeded reads the same person).

**2026-11-17T09:17:02Z**

Manual audit credits delivered slice-2 people, aliases and merge/split infrastructure. Rewrote this deferred ticket around the actual missing identity options and explicit acceptance for a small next slice. No new acquisition, model run or implementation started; existing low priority and joint CT/SpicyRegs ownership remain. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.
