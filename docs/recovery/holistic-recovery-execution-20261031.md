# Holistic recovery implementation record

Started from `72d0349838de7a0a9c5fceb9030d4a23dd34dc2c` on 2026-10-31.
**Status: local implementation and acceptance complete.** All seven fixes are integrated; independent review findings are resolved. Production data and external acceptance limits below remain explicit.

## Recovered execution

The five app task sessions were stopped after their permission failures. Their
preserved commits were selectively integrated into the managed
`holistic-recovery-integration` checkout. The coordinator implemented campaign
planning, acceptance, discovery wiring and integration directly. GPT-6.1 Sol
subagents with high reasoning completed bounded capture, qualification and native
publication work in that same checkout without additional approval prompts.
The implementation is merged into primary `main` at
`04800bfd9967c1ecc462d4825f5fc272a4b57120`. Pre-existing local ticket and
documentation edits remain unchanged.

Independent GPT-6.1 Sol high reviewers loaded ETL Workflow, Greybeard and
Semi-Formal Code Review. Reviews traced actual consumers and found defects beyond
the initially passing tests. Those findings are tracked below; a passing subset
is not substituted for final integrated verification.

## Implementation and evidence map

| Finding | Implemented owner | Maintained verification |
| --- | --- | --- |
| Inconsistent baseline totals | `congress_shared.campaign` pins input tables; `corpus_recovery.campaign.plan` writes a native ledger, counts, requirements and manifest | `test_campaign.py`: conservation, literal membership, duplicates, changed pins, state/profile/requirement binding and zero acquisition |
| Identity inferred by reconciliation | `corpus_recovery.acceptance` extracts facts from pinned source records, binds actual receipt/body/qualification and compares required native identifiers | Wrong meeting/witness/date/version/document, supported alias, source mutation, updated revision with explicit relationship evidence, readable wrong body |
| Recovery did not reach scheduling | Version-2 provenance/profile, native eligibility and capture consumer; explicit refresh intent remains independent of recovery relationship | Native eligibility matrix and `test_recovery_publication_journey.py` through importer, native model, public publisher, actual browser/reader and real queue |
| Missing execution paths | Packaged campaign plan/import CLIs; CDX parser, archive/runtime adapters, scoped search and source-specific mapping leads; capture campaign selector | Discovery/runtime and CLI fixtures; invalid replay identity cannot dispatch; partial searches remain unresolved; raw replay stays on disk |
| Downloads/imports/publication repeated after failure | Existing capture runner with durable attempts and frozen receipts; stable provenance writes; existing publication continuation owner | Fresh-process SIGKILL, lost acknowledgments, changed inputs, uncertain outcomes, stable replay and selected-pointer readback |
| Unbounded ladder/capacity assumptions | Three-rung raw-byte ladder, shared persistent request/spend admission, byte/scratch controls, explicit provider error policy | Mixed rungs/redirects, concurrent reservations, exhausted-cap continuation, shared actual CLI ledger and measured successful maximum admitted body |
| Sniffing treated as readability | Shared bounded qualification with pinned implementation/tools/configuration, parser decoding and all-page Poppler rendering | Fake/truncated/corrupt PDF, decoding/resource limits, cache reuse/invalidation, subprocess cleanup, frozen legacy behavior; actual Web Harvest PDF caller uses streamed custody |

## Independent findings and closure

Capture review initially requested changes for spent-cap continuation, concurrent
byte over-admission, automatic fallback after unknown/provider quota outcomes,
orphaned spools on approved retry, missed cleanup after commitment, and a capacity
test that could accept a failure receipt. The first reported 16 MiB capacity
measurement is **invalid and superseded**. The final fixture verifies the
successful decoded/stored body's size and digest and shared all-page qualification.

Recovery review found an ignored Wayback predicate, inability to accept an
explicitly supported changed revision, whole-PDF materialization in the historical
caller, and separate CLI admission databases. Completed repairs reject invalid replays
before requests, require pinned revision relationship evidence, pass streamed
custody through current frozen validators, and expose the same persistent budget
path on both CLIs. The scoped review approved those repaired paths with final
refresh-policy/shared-CLI checks assigned to the coordinator.

The blind greybeard review found accepted live pages could stop refreshing,
incomplete native builds could not resume, and canary-failure continuation repeated
acknowledged upload work. Explicit refresh intent, fresh owned stages for incomplete
models, atomic control writes, and reconciled asset acknowledgments close those
findings. The independent recheck approved all three repairs.

## Final verification

Code commit: `4924d06c3109b2926f6a13fb81c3f93d2547f11c` (implementation commit
`12ac8bf221172c19ceabf2706fd1a7b295ba1895` plus the final early-authority guard).
The final combined run passed **630 tests, zero failures, errors, or skips**, in
98.88 seconds. It covers shared custody, recovery, Web Harvest, capture/transport,
receipts/provenance, native models, publication continuation, Chromium/Node reader
checks and the actual scheduler. `uv lock --check --offline` also passed. Earlier
site build, archive unit (13) and archive tools (13) checks passed; site code did
not change afterward.

The first combined run found an early-refusal regression: the public capture
wrapper created work state before rejecting display-only releases. The guard now
runs before any work-directory/lock creation; 19 dedicated refusal tests passed.
Two other failures came from the test runner placing temporary work inside the
checkout, contrary to the existing CLI guard. The final run used an external
owned temporary directory and kept that guard intact.

All three independent Sol high reviews approve their scopes after rechecking the
repairs. The coordinator's final run includes their cross-component seams.
The five stopped app sessions were read back as idle and their worktrees were
pruned after integration. Superseded drafts, duplicate backups and temporary Git
refs were subsequently removed. Codex protects this chat's active integration
checkout from deletion; its generated caches and build outputs were removed.
The primary checkout's pre-existing edits remain unchanged.

The [machine-readable acceptance record](evidence/20261031-local-acceptance.json)
contains the tested commit, test paths, versions, configured limits and final
resource sample. A valid **16,777,216-byte PDF** was captured, stored with its exact
digest, decoded and rendered on all pages. With one worker, observed peak process
tree RSS was **239,534,080 bytes** and peak owned disk was **72,766,125 bytes**.
This includes native and qualification/Poppler children, with 34 samples at a
nominal 10 ms interval. It is one fixture workload, not a hard transient ceiling
or throughput comparison. Logical wire/body sizes and peak disk are measured;
total filesystem I/O bytes are not instrumented.

The same 630 tests passed on merged `main` in 100.79 seconds, with no failures,
errors or skips, and the site build passed. This checkout's only committed
difference from the tested integration was a pre-existing ticket. Final JUnit,
logs, invocation, runtime settings and resource measurements remain in the
primary checkout at `.cache/holistic-recovery-preservation-20261031/validation/`.
The original review evidence is retained alongside them in `baseline-review/`.
Temporary test bodies, browser dependencies, build outputs, staging scripts and
superseded run logs were pruned. The committed summary and maintained tests
remain available independently of those local records.

## Acceptance boundaries

- Production `publish_v20` and `capture_rust_batch1..10` inputs were not located
  and pinned. Correct production membership/counts and recovery yield remain
  unknown. The planner is tested against authored local input sets.
- Validation used local fixtures and services. No production acquisition, paid
  request, remote publication or push was performed. Live source mappings, archive availability,
  provider behavior/pricing and remote upload capacity remain operational checks.
- The integrated journey uses actual native model producers, the publication
  controller, Chromium, the shipped reader and the scheduler. A local object
  service and transport adapter stand in for production storage. This does not
  qualify production upload memory/network behavior.
- Version-2 provenance is a trusted producer attestation. The campaign producer
  establishes real qualification and identity bindings; generic administrative
  provenance writers are trusted. Native hash syntax checks alone do not prove
  qualification.
- Qualification uses process limits and sampled process-tree RSS on macOS.
  Sampling does not prove a hard transient memory ceiling. One measured worker
  does not qualify 16 workers or production throughput.
- Historical standalone validator snapshots retain their original behavior and
  identity. New snapshots pin and invoke the shared qualifier. No corpus-wide
  replay or retired v6 publication work is required.

## Reproduction

Use installed workspace packages from the checkout being tested and verify that
editable imports resolve there. `test-suites.toml` lists package roots
and native prerequisites. Set `DOCSPEC_JOB_CONFIG` to a pinned DocSpec runtime;
these runs use revision `eb40c5457a450c3820900583af5b4da13313ca96`, binary SHA-256
`8d33f1d03540fb0bc8160eac18e0121c0cde428feaeb77b4e815abf805f2d819`, 512 MiB
native memory, 256 MiB native scratch, and two native threads.

The publication journey is explicitly in the maintained native-loopback lane.
It additionally needs freshly built site assets and the repository's pinned
Playwright/Chromium setup. Campaign CLI input schemas and actual commands
are documented in `packages/corpus_recovery/README.md`.
