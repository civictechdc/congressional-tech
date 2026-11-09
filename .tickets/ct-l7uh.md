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
