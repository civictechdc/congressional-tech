# Holistic recovery implementation record

Started 2026-10-31 from code `72d0349838de7a0a9c5fceb9030d4a23dd34dc2c`.
The architecture plan in this directory defines the intended behavior. This record tracks execution; it does not assert completion.

## Scope and completion

Implement all seven validated fixes through the existing owners. Finish usable entry points, integration, proportional regression checks, failure/restart checks, and independent review. Preserve the primary checkout's unrelated changes. Do not restart retired v6 publication work or change unrelated runtimes. Do not acquire the corpus, spend provider credits, or publish production data as an implementation test. Missing production baseline and live-provider acceptance must remain explicit, not guessed.

Implementation sessions use GPT-6.1 Terra with high reasoning. Independent review uses GPT-6.1 Sol with high reasoning and the ETL Workflow, Greybeard, and Semi-Formal Code Review skills. Local completion and resolved material findings are the goal, not speed.

## Parallel ownership

| Session | Primary ownership | Integration obligations |
| --- | --- | --- |
| Recovery evidence | `packages/corpus_recovery`, shared campaign descriptor if needed, qualification script delegation | Pinned ledger, identity acceptance, body qualification/cache, actual import entry point; integrate discovery and capture outputs after other slices arrive |
| Native feedback | `packages/viewer_publication`, `model/sql`, capture/recovery registries, `congress_api/models/archive_profile.py` | Native eligibility, current acceptance/rejection, required reader/profile versions, existing publication continuation; coordinate scheduler consumer with capture owner |
| Durable capture | `congress_api/acquisition`, transport, retention receipt writer, capture CLI | Stable attempt/receipt identity, restart, provider ladder, request/cost/resource limits, campaign-only selection, eligibility-aware scheduler consumption |
| Discovery | New discovery adapter module(s) and focused tests; source-specific Web Harvest helper changes | Maintained CDX path, Wayback replay validation, scoped relocated search, source mapping; return evidence-rich candidates through the recovery owner, not a second importer |

No shared-file concurrent edits. Each implementation session uses its own checkout, preserves commits, and reports exact integration points. The coordinator owns integration, final plan/status updates, and combined journeys. Missing cross-slice wiring is unfinished work, not grounds to call a slice's objective complete.

## Integration seams

- Accepted identity must bind target URL, target requirement, candidate/body/receipt identity, qualification, relationship kind, and evidence. No filename-only success.
- Native eligibility preserves HTTP facts and evaluates current accepted or rejected decisions for a pinned requirement. Current live-page refresh remains distinct from historical recovery.
- Campaign selection is an immutable descriptor plus pinned metadata tables. Resolve the shared schema with the recovery owner; avoid large URL arrays and reverse package dependencies.
- Discovery returns candidates and source evidence, never acceptance. Provider calls use the capture owner's common attempt and budget boundary.
- Durable receipt/provenance writes reconcile an uncertain acknowledgment using stable bytes and keys. Publication continuation remains with the existing archive publication owner.
- Reuse checks precede payload opening. Every new retained file has an owner, protected lifetime, and cleanup condition.

## Evidence still required

- Reconciled target memberships and changed-pin refusal on fixtures; actual production baseline only if located and pinned.
- Identity adversarial cases, format qualification, cache reuse/invalidation, and mutable-file custody.
- Accepted/withdrawn/counterpart/excluded/freshness behavior through published output and the actual scheduler.
- Failure and fresh-process restart around download, body/receipt/provenance acknowledgment, native output, and release selection.
- Bounded archive pagination/search candidates, scope violations, and actual command journeys.
- Mixed provider/redirect/retry scenarios with shared request/spend reservations and bounded memory/disk behavior.
- Independent findings-first code review, blind architecture critique, resolved material findings, and verification at the integrated head.

## Current state

Implementation not yet integrated. Review not yet run. Production counts and live acquisition acceptance remain unverified.
