---
id: ct-l7uh
status: in_progress
deps: []
links: [ct-umtm]
created: 2026-11-08T18:59:37Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
---
# Refetch the twelve Oct 31 Wayback bodies not in raw

The twelve October 31 Wayback replay target/body pairs (ct-umtm) are recorded as not in raw: ledger .cache/archive-release/implementation/ct-umtm-20261108/wayback-not-in-raw.json. If wanted, refetch each exact Wayback body once through the maintained capture/recovery path (capture_schedule + retained import, as ct-rie2 did for USAID), verify its body hash against the ledger, and import only on qualified identity. Out of scope: proving semantic equivalence; one CHRG-110hhrg41994 counterpart is a possible but unproved match.


## Notes

**2026-11-09T17:57:05Z**

2026-11-09 owner decision: build the recovery route. Scope: add exact Internet Archive replay as a recovery source kind (exact-replay scope entry with expected body hash), recovery requirements for the twelve ct-umtm targets in publish-model.json, capture_schedule --campaign support in the workflow, and one supervised import verified against the ledger. Follow the ct-rie2 USAID campaign as the template. Scheduled after thread 1 (claude/ct-thread1-unattended) lands.

**2026-11-09T17:57:46Z**

2026-11-09 correction: no new source kind is needed. The URL model already unwraps web.archive.org/web/<ts>/<url> wrappers (engine-first-data-model.md, unwrap(url)), and the ct-rie2 recovery-campaign route (recovery_requirements parquet under recovery-identity-v1, capture_schedule --campaign, supervised import) is the existing path for exactly this. Scope is therefore: one requirements file listing the twelve ct-umtm targets with the ledger's expected body hashes, one campaign run, one supervised import; verify each body hash against .cache/archive-release/implementation/ct-umtm-20261108/wayback-not-in-raw.json. The only reason scheduled capture cannot take them is that it plans from the release scope, which has no replay family; campaigns do not use that scope.
**2026-11-09T16:36:52Z**

2026-11-09: not added to the first scheduled run. The maintained ordinary path cannot fetch these replays, and the maintained campaign path needs release-level inputs and a supervised import. Nothing was fetched, built or committed beyond this note.

Ledger check (read-only): wayback-not-in-raw.json (sha256 d22fe2c5...) holds 12 target/body pairs. They equal, as a set, the 12 retained_verified_replays in docs/experiments/url-normalization-validation-20261031/evidence/wayback-results.json (sha256 711b8f73...). Each of those carries an exact web.archive.org/web/<ts>id_/ replay URL with sha256, CDX digest and exact-replay validation all true. The replays total 31,373,355 bytes; the largest is 11,268,337, under the 16 MiB max_entity_bytes. Prior outcomes: 9 failed, 3 request_failed.

Why the scheduled run cannot take them:
1. It plans from the release's own capture_scope.json, url_state and profile. capture-scope has no web.archive.org entry, so a replay URL has no family and is never eligible.
2. ARCHIVE_CAPTURE_CUTOFF_URLS only reprioritises existing url_state keys. A replay URL unwraps (url-rules 'wayback') to the target's key, so a cutoff would re-request the live target, not the replay.
3. Ordinary capture stores whatever bytes arrive under the target key. It has no expected-hash check, so "import only on qualified identity" cannot hold there.

The maintained path is the ct-rie2/ct-umtm campaign: a version-2 profile whose recovery requirements include these 12 targets (historical_exact), a pinned campaign descriptor with replay candidates and expected sha256 from this ledger, capture_schedule --campaign, then the corpus_recovery qualification and single-writer import. That needs three things: a new requirements parquet in publish-model.json (moves the release), an exact-replay scope entry, and a supervised campaign run (capture-archive.yml takes no --campaign). This is owner-decision work, not a scheduling tweak.

**2026-11-09T21:48:35Z**

2026-11-09 campaign prepared offline (no network, no raw write; nothing fetched or imported). Evidence and scripts: .cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109/ (l7uh_prepare.py, l7uh_check.py, l7uh_plant.py, l7uh_writer_packet.py, execution-inputs.json).

Inputs (generated from the ledger + wayback-results.json, no typed hashes): cohort/{targets,candidates}.parquet, execution-inputs/recovery-requirements.parquet (12 rows, historical_exact, recovery-identity-v1, historical_only), version-2 capture_profile.json bound to that file, url_state.parquet from the maintained eligibility SQL over release 630164505301's 12 history rows (all eligible/no_satisfying_recovery), capture_scope.json = public scope + 12 literal ^replay$ patterns in 'documents' (local to this execution release only), local release 830efb25ec8f, descriptor execution-inputs/campaign.json sha256 51d2c760adf5a5b1... campaign.plan: 12 retained_candidate_pending. l7uh_check: PASS rows=12 total=31,373,355 max=11,268,337, both set directions; a planted wrong hash FAILs the check and the descriptor refuses it, restored bytes identical. capture_schedule dry run (no --apply, network denied by sandbox): due=12, queue = exactly the 12 replay URLs, none a live target.

OWNER DECISION before import: the engine's url_key unwrap gives 10 of 12 replays their target's key; 2 differ: FEMA.pdf (replay archives '//sites/...') and VA cpg_PTSD (replay 'PTSD-full...PDF' vs target 'PTSD-FULL...pdf'). Oct 31 'exact_replay_validation' compared the replay to the CDX 'original', not to the target literal. Keep as historical_exact, drop, or re-label those two. Also choose the identity evidence basis/match_basis and reviewer for the per-target request (decide() needs a strong identifier on both sides).

publish-model.json: NOT required for capture, import or publication (recoveries publish from retained_import captures + recovery provenance; requirements only label url_state 'satisfied'; none of the 12 targets is in capture scope). Optional 13-row file prepared in optional-model/ if the owner wants the label; fold into the MODS regeneration, not a separate one.

Runbook (clean writer checkout W, uv sync --frozen, hold the shared writer slot; I=<main>/.cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109; run=$I/writer-run):
1. Lookup prior work per target: L7UH_PACKET_CONFIG=<target cfg> .venv/bin/python $I/l7uh_writer_packet.py lookup --capture-work $run/scheduler --import-root $run/operations
2. Preview then capture (private local store only, no R2): .venv/bin/python -m congress_api.cli.capture_schedule --release-root $I/execution-inputs --campaign $I/execution-inputs/campaign.json --work $run/scheduler --engine-config $run/runtime.json --admission-db $run/scheduler/admission.sqlite --request-budget 12 --byte-budget 78878366 --spool-budget 100663296 --workers 1 --files-per-second 1 --max-discovery-jobs 1 --fetcher-binary <pinned source-fetch> --local-store $run/raw-stage [--apply]. Writes: capture journal, frozen receipts and bodies under $run (local create-only). Per-hop entity cap 11,268,338.
3. Per target: qualify the captured body from raw-stage (as ct-umtm requalify.py), write its packet-config.json (expected url/bytes/sha256 from execution-inputs.json, template, qualification), then freeze-request --receipt <frozen receipt.gz> --request $run/requests/<n>.json --decided-at <UTC> --decided-by <name>; import-keys (prints exact receipt/provenance keys).
4. Import (the only shared writes, R2 congressional-tech-raw, create-only): import-r2 --campaign $I/execution-inputs/campaign.json --request ... --operations $run/operations --runtime $run/runtime.json --bucket congressional-tech-raw --apply. Writes the body (if absent), receipts/documents/<date>/recovery-campaign-<op>.jsonl.gz and provenance/recoveries/<ts>-<op>.jsonl.

Identity gate before any R2 write: freeze-request and import_candidate require receipt_binding (HTTP 200, literal replay URL, one complete capture whose sha256 and bytes equal the ledger value), verify_local_file of the body against the ledger sha256, qualification 'qualified' (application/pdf for .pdf), campaign membership of the exact target/replay pair, and decide() accepted. Any mismatch stops before import and is kept as evidence. Expected: 12 accepted imports, each body sha256 equal to wayback-not-in-raw.json; then the release owner selects the receipts/provenance in the next coordinated release.
