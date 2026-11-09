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

**2026-11-09T21:55:30Z**

2026-11-09 identity measurement (offline; .cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109/l7uh_identity.py, identity-results.json, identity/). Runs the maintained acceptance.decide() unchanged on records read by identity_source(), one record per side; only body custody, receipt_binding and qualification are stubbed because they need a captured body.

Correction: a literal compare finds 8 of 12 replays differ from their target, not 4. Scheme only: hcfa, legion, developingchild, cssp. Port :80: napawash; crr (also http vs https). Double slash: FEMA. Case and scheme: VA (PTSD-full...PDF). Exact: irs, piie, samhsa, clairemontialoux. The Oct 31 discovery deliberately relaxed the maintained 'row original == target' rule to SURT equality (wayback.py), and that is how these 8 were found.

decide() results by document basis:
- literal (target: requested_url in our Oct 12/15 capture receipt row; candidate: the CDX original, i.e. the replay suffix): 4 accepted, 8 rejected conflicting_document.
- engine url_key (derived): 10 accepted; FEMA and VA rejected.
- SURT/Wayback urlkey (derived on our side; case-folds): 12 accepted, VA included.
- one shared record (Duke pattern): 12 accepted. A wrong value planted in that record is still accepted, so it checks nothing.
Plant: a wrong candidate document on an accepted literal row (clairemontialoux) gives rejected conflicting_document.
Release 630164505301 holds no native ID for any of the 12 (no source, document or recovery row; url_state only), so a meeting/document/package basis cannot be built. Only literal is source-native under the acceptance docstring, and its candidate side is reconstructed from the replay URL because the CDX JSON rows were not retained.

Label: recovery rows look the same with or without requirements. Only the url_state row changes, and it is readable through the Explorer MCP SQL view and the site reader's urlState(). In the unfinished Nov 9 nightly candidate, USAID shows satisfied/qualified_recovery/21ebd7b7, while Duke (recovery published, row 288704, no requirement) shows eligible/no_satisfying_recovery.

Recommendation (owner to confirm): literal basis. Run the campaign on the 4 exact targets: no code change, re-run l7uh_prepare.py on the filtered pairs, 4 requests. Keep the 8 variants as not_in_raw with the spelling reason recorded. Admitting the 6 scheme/port variants would need a named, reviewed match rule in acceptance.py (a code change, separate ticket); putting engine keys into the records needs no code but would present a derived key as a source-native ID. SURT would also admit VA by case-folding, against the module's explicit rule. FEMA and VA stay out under every source-native basis. Fold the requirements rows for the imported targets (and Duke) into the MODS regeneration so their url_state reads satisfied.

**2026-11-09T22:26:09Z**

2026-11-09 live local run (owner decision relayed by the orchestrator: all 12, Wayback urlkey/SURT basis; fetch authorised; the R2 import is run by the orchestrator, not here). Nothing was written to R2 or any remote. Evidence: .cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109/.

Fetch (UA congressional-tech-recovery/1.0, 1 file/s, one worker, maintained capture_schedule into a private local store writer-run/raw-stage):
- 12 Wayback CDX rows (separate campaign 87f4cd5d; 3,906 bytes). All HTTP 200, one distinct row each (hcfa listed twice), and every Wayback urlkey equals corpus_recovery.cdx.key(target).
- Replays run 1: 10 stored. legion stopped at 9,818,347 bytes (response_limit): the scheduler sets each per-request cap to (byte budget minus bytes already fetched)/7, so the prepared budget of 7 x largest body was too small once other bodies had been fetched. piie returned HTTP 500.
- Retry campaign 0e8a6e97 (those 2 targets only, budget 7 x largest + the rest): both stored. The retry was one request about one minute after the 500.
- Total fetched: 41,337,398 bytes, including the 9,818,347-byte partial and the 141,790-byte error page.
Check (shasum/gzip/wc/jq only): L7UH_BODYCHECK PASS ledger=12 matched=12 stored_pairs=12. Two failed-attempt bodies are listed as extras. All 12 also match Wayback's SHA-1 digests (openssl + base32). Planted byte in a copied store (irs): FAIL matched=11, exit 1.
Identity: per-target records in packets/NN. Target document = cdx.key(literal target) (ours); candidate document = the Wayback CDX urlkey (publisher), with the CDX row, its receipt and body pinned. Both are named-reviewer records: identity_source() cannot read the CDX JSON (a list of arrays) as a receipt-backed record. Difference classes: exact 4, scheme 4, port 80 1, scheme+port 80 1, double slash 1 (FEMA), scheme+case 1 (VA). All 12 qualified (Poppler 26.10). freeze-request and import-keys done (decided_at 2026-11-09T22:40:00Z, decided_by owner-approved-2026-11-09-claude-session). Offline rehearsal of import-r2 against a LocalAdapter: 12 accepted; keys equal import-keys output.
Import (not run): .cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109/l7uh_import_r2_commands.sh, 12 commands. Creates 36 keys (12 bodies/sha256/<2>/<sha>, 12 receipts/documents/2026-11-09/recovery-campaign-<op>.jsonl.gz, 12 provenance/recoveries/20261109T224000+0000-<op>.jsonl), listed in import-key-list.json. HEAD-check the body keys first.
Optional 14-row requirements (USAID + Duke from its own campaign file, checked against its accepted decision + 12): .cache/archive-release/investigations/ct-l7uh-wayback-campaign-20261109/optional-model/recovery-requirements-ct-l7uh-duke-20261109.parquet, sha256 9e7d07e1949986b356c2955b8eb0af75b0e76c129c7e70509ae8942eacafa9d0, 2,807 bytes; for the MODS regeneration.
