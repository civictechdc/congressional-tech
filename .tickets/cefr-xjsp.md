---
id: cefr-xjsp
status: closed
deps: []
links: []
created: 2026-10-27T18:55:33Z
type: task
priority: 2
assignee: raw
---
# F2: schedule bounded capture from the live release

Run2 owner reassignment. New target path beside live raw_sync; site owns workflow wiring.

## Acceptance Criteria

Native due planning preserves queue/cutoff/time order and seed schedules; target capture uses Fetcher/ReceiptWriter/BodyStore with request-byte-spool bounds and no raw index/replay; local fixture contracts pass; first live run has exact owner command.


## Notes

**2026-10-27T18:59:14Z**

Contract suite authored first: six behavioral cases fail only because capture_scheduler does not exist (project runner, contracts-red.log). Implementation follows in a separate commit; no existing assertion changed.

**2026-10-27T19:09:26Z**

Implementation binds native public-release queue planning, bounded weekly seeds, immediate bounded discovery replans, B2/B3 writers and exact raw receipts. Focused scheduler/fetcher/receipt/store runner: 99 passed in3.23s (focused5.log); first broad import-fence run117pass/1new lake-fence issue, reported to D1 owner. No network/store run. Remaining: root independent CODE/ARCH review, first real E-release scope/due/cutoff-budget qualification and owner first live run.

**2026-10-27T19:29:00Z**

Confirmed F2 CODE/ARCH concerns reproduced cd94e9a8. Fixed full single-PUT allowance4ac9f494 (source314→317lines), unsafe discovery refusal a582b05f (317→341), and all-reviewed native cutoff dispositions in current follow-on (341→397). 104 focused checks pass4.28s on6fc6a94. Shared E url_key and D2 worker still pending; exact-alias regression contracts being added. Bounded replans cost O((D+2)*N) input passes, defaultD8→10passes, plus per-capture fetch/write work.

**2026-10-27T19:39:48Z**

Shared seam adapters now fail closed: missing model/sql/url-keys.sql or default ParserWorker refuses execution; no exact-string/normalizer or unbounded-reader fallback. Native state/seed/discovery/attempted/cutoff matching uses the supplied shared URL definition and validates one key per input, retaining literal requested output. The finite authored fixture adapter proves scheduler joins only; actual E definition/profile and default worker remain engine integration gates. 134 focused scheduler/fetcher/store/receipt/import checks pass6.34s. Shared URL definition digest is pinned across replans; bounded workers are cached per format. Source397→499lines, CLI81→85, tests361→385.

**2026-10-27T21:48:25Z**

Local scope complete: CODE/ARCH APPROVE including bounded shared-validator followup98abd12f; models-path bindingd64aecc3 passes69 focused checks18.32s (33scheduler/10profile/26import). Actual shared SQL/variants and persistent worker exercised with fake HTTP/local stores. Exact first-live command and release/Linux/budget prerequisites in docs/measurements/engine-first-20261027/f2/README.md; no live action ran.

**2026-10-28T01:49:38Z**

Owner retro-review reopened F2: contract-first fixtures require persist-before-inspection, capture-time sniff facts on returned receipt, drain queued work after discovery replan bound, and remove authored identity overrides. Local synthetic expected-red runner: 14 failed in 3.30s. No live HTTP/storage action, credentials, production branches or monkeypatch. Root retains review and live-run authority.

**2026-10-28T01:53:21Z**

Review correction implemented locally after contract af44f627: writer-enriched returned receipt drives discovery; discovery bound limits replans and drains planned queue; authored SQL/input override routes and unused finite fixture generator deleted. Actual-profile focused runner 84 passed in 15.44s; sniff/pending subset 36 passed in 1.67s using approved48636e5. Local fakes/stores only; no monkeypatch, live network/storage writes or credentials. Source total901->894 (fetcher158->155, writer132->150, scheduler522->508, CLI89->81). Independent parent CODE/ARCH review and broad group remain pending.

**2026-10-28T03:34:02Z**

Local review fixes complete: af44f627/6f2d9f80, archive-reopen refusal 714966f9/2f060977, completed-inspection facts 32ae2804/0e0ab719. Confirmed CODE/ARCH findings fixed forward; latest raw-writing correction CODE APPROVE. Combined real-profile scheduler/verifier/repair/fetcher/writer/archive group104PASS19.25s on approved9b59263 at9d250ef5, local fakes/stores only. Exact first-live owner command and Linux/release/budget gates remain README; no live run.

**2026-10-28T04:07:16Z**

Actual engine-built real releaseac866cc3 read-only CLI seam passes on9b:129url_state rows→89due/79linked-unfetched, request budget5 selects5queued rows, no seeds/HTTP/apply/storagewrites. The release reader/canary/browser checks also pass under site ownership. First live remains exact README command.

**2026-10-28T10:23:19Z**

Owner urgent display-only seed correction: refuse manifest.origin.kind=seed_v5 or display_only=true before scheduler data downloads, native queue work or capture. Contract-first local/fake-public and hand-built entrypoint fixtures; no live run. CODE review required before re-closing.

**2026-10-28T10:26:27Z**

Seed refusal contracts5dd031da failed19 cases before implementation. Final focused scheduler/new admission group passes52 cases13.60s on shared engine-b2fd2d8. Guard runs immediately after manifest and at direct planning/capture/binding/cutoff entrypoints; public inputs stop after pointer+manifest. Public origin is retained as manifest_origin beside transport origin. CODE review pending; no live capture.

**2026-10-28T10:30:30Z**

Seed authority correction reviewed APPROVE, no findings: codex-raw/run2/seed-progress-code-review/review.md. Contracts5dd031da ->6636eb6d; 52 focused scheduler checks passed13.60s, including local/public pre-download refusal and direct entrypoints. Local scope closed; first live remains exact owner command in docs/measurements/engine-first-20261027/f2/README.md. No live action.
