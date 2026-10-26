# GPO and raw-source compatibility review — October 26, 2026

**Final verdict: APPROVE the traced GPO/raw-source changes at `6183938fcb2b0842d5e1f59072383aa7dd251d32`.** The mapper and raw custody findings below are resolved in that source. The final delta review and seven executed follow-up checks are recorded at the end of this report.

**Initial finding:** the earlier combined main revision omitted failed MODS and manifest timestamps from weekly observation summaries. A parser-stale package could retain its malformed response successfully, then stop weekly sync because the mapper reported a missing timestamp. Fixed separately in `db1ac0454409df3edfbd457431e3428f4fd41a81` with four regression cases, then integrated as `a3beabaca786a0e64c8e1ddae85caef3e3abd743`.

**Historical verdict for `ad222085`: REQUEST CHANGES.** It required that mapper fix and the raw custody corrections originally committed as `114e3d9ee8e7886f32d1bf07ed5bd8b60c1e7d07`. The following initial-review record preserves that evidence; final source approval does not imply hosted/deployed qualification.

## Reviewed revisions and scope

- Combined main reviewed: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.
- Own branch rebased onto that exact revision: `codex/gpo-xml-boundary`.
- Backup: `codex/gpo-xml-boundary-before-review-20261026`, pointing to `fb073f02b85cbab65701f3bc1aeb7a593df60ee2`.
- Git recognized all three original repair commits as already applied and dropped them during rebase. No old work was reapplied.
- Local remedied source checked: `db1ac0454409df3edfbd457431e3428f4fd41a81`.
- Independently inspected raw follow-up: `114e3d9ee8e7886f32d1bf07ed5bd8b60c1e7d07`. That commit was read directly from Git; it was not cherry-picked into this branch or executed here.

The review covers the combined GPO acquisition, XML parsing, ZIP range transport, shared HTTP/directory helpers, evidence models and writers, adapter mapping, weekly summary mapper, and GPO workflow persistence. It also traces raw seed identity, affected-input replay, source qualification, schema compatibility and continuation custody. Viewer rendering, Pages deployment and YouTube changes have separate owners and are outside this report. Proposed redesigns were excluded.

Paths in the source traces below are relative to `packages/congress_api/src/congress_api/`. Test paths are relative to `packages/congress_api/tests/`, except where marked otherwise. Line numbers refer to the reviewed main or explicitly named follow-up, not to an assumed future merge.

## Findings

### F1 — Failed checks can stop weekly sync

- Severity: **WARNING / P2**; category: correctness and missing regression coverage.
- Location on reviewed main: `retention/weekly_tables.py:623` and `:662`; caller `cli/sync_weekly_tables.py:154`.
- Evidence chain: `acquisition/gpo.py:177` catches malformed MODS and retains `failed_mods`. A parser-stale refresh need not have a new listing or prior retained MODS. The gzip writer accepts this record (`retention/gpo.py:176`), but the weekly mapper originally visited only `mods`, `listing`, transcripts and older generic observations. Its required timestamp remained empty and raised at line 664. Thus one valid failure receipt could stop conversion of the evidence file.
- Reproduction: `test_stale_mods_failure_remains_syncable_without_listing_or_prior_evidence` (`test_gpo_acquisition_xml_failures.py:157`) runs the collector with malformed MODS, no listing result and no prior evidence, then passes the retained gzip through the actual weekly iterator. It failed on main. Three direct section cases at line 179 also failed.
- Fix: `db1ac0454409df3edfbd457431e3428f4fd41a81` adds `manifest`, `failed_mods` and `failed_manifest` to the existing timestamp/acquisition scan. It retains existing summary fields and acquisition precedence. It changes neither accepted source bytes nor pending state, and does not mark the failed package successful. All four cases pass after the fix.

### F2 — Raw capture cache admission needed exact source identity

- Severity: **WARNING / P1**; category: correctness; already owned by the raw-source task.
- Location on reviewed main: `retention/source_capture_inputs.py:61`, `:83`, `:88`.
- Independent evidence: the production branch accepted a hardcoded local cache using schema, row-group count and row counts, then attached those rows to selected raw entry references. Those checks did not establish that the cached receipt values came from the selected raw release. `RawSnapshot.capture_batch` is the maintained selected-entry reader (`retention/raw_storage.py:569`).
- Cross-review of `114e3d9e`: `SourceCaptureInputs.changed` now calls `snapshot.capture_batch(entry)` in both batched and single-entry paths (`retention/source_capture_inputs.py:55–74` in that commit). Existing `attach` still checks the exact capture schema and ordinal range at lines 39–52. The new test supplies a same-shape cache containing a different receipt and asserts that selected bytes win (`test_source_replay_capture_stream.py:118` in that commit).
- Status: the follow-up removes the offending admission path. No competing change was made here. This conclusion is static review of the follow-up; its new test was not executed in this worktree.

### F3 — Qualification resume needed a retained-file hash

- Severity: **WARNING / P1**; category: correctness; already owned by the raw-source task.
- Location on reviewed main: `retention/catalog_raw_updates.py:379–393`.
- Independent evidence: continuation checked its request and retained source proof, then opened `interpreted-sources.parquet` without checking that file against an identity recorded before interruption. The production qualification proof does not independently enumerate every row digest (`retention/source_update_proof.py:169–177`), making the missing file binding material to this branch.
- Cross-review of `114e3d9e`: the writer records `file_identity(values.path)` before publishing the continuation descriptor (`retention/catalog_raw_updates.py:664–667` in that commit). Resume refuses a missing identity and checks current bytes/hash before opening the replacement stream or calling catalog publication (`:385–398`). `derived_files.check_identity` compares both byte length and SHA-256 (`retention/derived_files.py:72`). The added test changes retained values or removes the pin after a simulated stop and requires refusal before publication (`test_catalog_raw_updates.py:711–744` in that commit).
- Status: the follow-up addresses the identified missing binding. No competing change was made here. No additional defect was found in that four-file follow-up during static inspection.

## Patch summary

The GPO repair replaces an unavailable standalone `mets.xml` URL with the actual `{package_id}/dip.xml` member in the GovInfo ZIP. It adds bounded selected-member reads, source-version checks, strict package identification and retained request evidence. Known package failures retain the last usable row and manifest, flush unrelated work and remain pending. The scheduled job preserves completed CSV progress after saving its evidence snapshot, while the failed collection step still fails the job (`.github/workflows/update-data.yml:90–125`).

The raw repair separates ordinary code/seed refresh from an incompatible source contribution format. Routine changed seed URLs/events select affected retained inputs; explicit qualification or rule upgrade remains available for complete historical reinterpretation. It retains exact candidate/request binding and additive-schema checks (`retention/catalog_raw_updates.py:349–438`, `:611–636`; `cli/raw_sync.py:491–509`). The custody corrections above are necessary alongside those relaxed routine-update gates.

## Function trace

| Function or method | File:line | Input → output | Verified behavior |
| --- | --- | --- | --- |
| `gpo_fetch.parse_args_and_run` | `cli/gpo_fetch.py:55` | CLI options → `gpo.main` | Maintained scheduled command enters the repaired acquisition path. |
| `gpo.main` / `fetch_one` | `acquisition/gpo.py:86`, `:162` | CSV, pending file, listing and responses → rows, failure receipts, pending ledger | Queues pending and stale packages; merges worker results; writes before exit 1. |
| `parse_mods_document` / `parse_package_manifest` | `parsers/gpo.py:75`, `:107` | Exact XML bytes → typed source models | Wrong roots refuse; XML parser errors propagate to the package boundary; source bytes remain available. |
| Manifest acceptance/cache | `acquisition/gpo.py:198` | Retained same-version manifest or ZIP member → accepted manifest/files | A prior failure or changed package version forces a fetch; METS `OBJID` must equal the package ID. |
| `read_zip_member` | `transport/zip_member.py:179` | ZIP URL and exact member name → member bytes and source metadata | Selects a unique supported member; enforces compressed/expanded limits; uses stdlib ZIP reads. |
| `_RangeFile._fetch` | `transport/zip_member.py:65` | Requested byte range → received bytes and response receipt | Requires exact HTTP 206/range/URL, identity encoding and stable validator/size. HTTP 200 HTML refuses. |
| `_RangeFile._preflight` / `read` | `transport/zip_member.py:115`, `:160` | Tail/directory/member offsets → bounded seekable reads | Rejects unsupported ZIP64/split archives; validates directory before allocation; caches received ranges. |
| `get_with_retry` / `pace_request` | `transport/http.py:137`, `:125` | Direct request options → response or typed error | Streaming is opt-in; rejected streamed attempts close; host pacing and named retry policy remain shared. |
| `validate_zip_directory` | `retention/archive_members.py:132` | Bounded directory bytes/count → validation or refusal | Shared by retained and remote readers; validates actual entry counts, lengths and signature boundaries. |
| `gpo.read` / `gpo.write` | `retention/gpo.py:130`, `:160` | Gzip evidence ↔ typed record dictionaries | Validates body digests on read; stores accepted and rejected observations with new metadata intact. |
| Weekly iterator / mapper | `cli/sync_weekly_tables.py:154`; `retention/weekly_tables.py:610` | Gzip records → weekly summary rows | F1 fixed: failure-only observations supply genuine timestamps; no invented retrieval time is needed. |
| GPO representations | `adapters/gpo.py:334` | Retained manifest file locations → representations | Only absolute web URLs pass `web_url`; local `file://` entries are excluded; known URLs deduplicate. |
| `seed_files` / raw CLI `run` | `cli/raw_sync.py:48`, `:491` | JSON/JSONL hints and file identities → distinct operation directory | Candidate includes mode, raw selection, code requirements and seed file hashes; changed hints do not collide with old retries. |
| `_update_from_raw` | `retention/catalog_raw_updates.py:293` | Selected raw state, seeds and prior catalog → coherent catalog update | Rejects unqualified/incompatible inputs; unchanged raw plus unchanged seeds can return unchanged. |
| `changed_seed_dependencies` | `retention/catalog_raw_updates.py:426` | New seed URLs/events → dependency keys | Changed hints enter affected-input replay without scanning the complete catalog. |
| `prepare_source_replay` / `_prepare` | `retention/source_replay.py:79`, `:218` | Exact changes and dependency closure → repeatable retained replay | Binds retry request/checkpoint identities; replays complete affected owners and checks closure. |
| `SourceObservationTrace.replay` | `retention/source_observations.py:317` | Selected receipts and seeds → source facts and dependencies | Uses maintained document-source readers and `collect_source_inputs` at `retention/source_inputs.py:37`. |
| Schema admission | `retention/catalog_raw_updates.py:611`; `retention/catalog_batches.py:233` | Existing and new logical schemas → admitted nullable additions or refusal | Field order/type/metadata of retained fields must remain compatible; nonadditive changes refuse. |
| `_retain_previous_tables` / qualification comparison | `retention/catalog_raw_updates.py:150`, `:602` | Selected native tables and fresh replay → exact value comparison | Reads selected values; qualification compares freshly interpreted outputs, rather than copying a same-shaped baseline. |

The Python runtime implementation was inspected rather than inferred from its name: `zipfile.ZipExtFile._update_crc` at runtime `zipfile/__init__.py:1018` compares the completed member CRC and raises `BadZipFile` on mismatch. The corruption fixture exercises this boundary.

## Data flow and invariants

1. **Source bytes and parsed meaning remain separate.** `parse_package_manifest` retains exact content and publisher attributes, including string-valued sizes. `GpoEvidenceObservation` adds `source_zip` and `package_last_modified`; `GpoEvidenceRecord` retains `failed_mods` and `failed_manifest` (`models/gpo.py:165–190`). Those values escape into the gzip evidence file, not into fabricated content URLs.
2. **Failure does not advance package completion.** `completed` is populated only for a returned hearing (`acquisition/gpo.py:255–264`). Failed packages are excluded from transcript backfill at `:270–277`. The pending file excludes only completed packages at `:309`. Rejected bytes and valid neighboring rows are written at `:306–309` before the command exits with failure.
3. **Ranges describe one source version.** Archive length and strong ETag or Last-Modified are established from the first range; subsequent requests carry and verify that validator (`transport/zip_member.py:45–59`, `:99–107`). There is no full-download fallback. The selected member's byte count and CRC are separate from the archive metadata (`:197–205`).
4. **GPO pending state and raw interpretation cursors have separate ownership.** The GPO command's pending ledger is not consumed by raw catalog publication. Raw request identity instead includes its own selected raw identity and seed digest (`retention/catalog_raw_updates.py:339`). A later valid GPO-derived hint can create a new seed operation while failed GPO work remains pending. Static traces do not establish that an operational producer has delivered every such hint.
5. **Routine discovery changes preserve previous facts.** New seeds invalidate their URL/event dependencies (`:426–438`); unchanged components can retain their references. Withdrawing hints does not imply deletion. Explicit rule upgrade is the supported complete reinterpretation route (`:308`, `:402`). Tests exercise this policy rather than treating it as an accidental omission.
6. **Migration remains explicit.** Unqualified prior selections refuse at `:370`; changed source contribution format refuses at `:374–376`; changed logical field types refuse at `:617–618`. The GPO metadata additions are nested evidence fields, so they do not silently alter the filename catalog's logical field types.
7. **Continuation must bind payload as well as request.** F2 and F3 describe the gaps in reviewed main and the exact new checks in `114e3d9e`. Their fixes preserve the seed/format gates rather than replacing them.

## Test behavior and boundary cases

| Tests inspected | Expected behavior and evidence |
| --- | --- |
| `test_gpo_acquisition_xml_failures.py:36` | Malformed MODS/METS, wrong roots/package ID and request failures retain old rows/manifest, flush a valid neighbor and retry without another listing result. Executed. |
| `test_gpo_acquisition_xml_failures.py:157`, `:179` | F1 reproduction and three section cases: all four failed on main, then passed after the mapper repair. The integration case uses the actual collector, gzip reader and weekly iterator. |
| `test_gpo_acquisition_xml_failures.py:193`, `:213` | Unexpected parser assertions remain visible; actual ZIP transport with fake HTTP preserves HTTP-200 HTML refusal evidence and accepts a valid manifest. Executed. |
| `test_gpo_source_models.py:201` | Manifest-only addendum HTML/PDF locations become representations, with no new CSV columns or `file://` links; parsed MODS metadata survives. Executed. |
| `test_gpo_source_fidelity.py:157`, `:190` | Same-version cache reuse, changed/failing version refetch, and legacy error-observation bounded refresh. Executed. |
| `test_zip_member_transport.py:73`, `:86`, `:95`, `:137`, `:147`, `:161`, `:166`, `:183`, `:189`, `:211` | Nonfirst members; comment signatures; exact HTTP/range/source validation; weak-ETag fallback; missing/duplicate/corrupt members; allocation limits; streamed retry cleanup. Executed. |
| `test_congress_api_boundaries.py:76` | Evidence snapshot precedes partial-failure CSV persistence, no continue-on-error, and derived video commits keep their success gate. YAML/static shell checks executed; hosted Actions was not run. |
| `test_catalog_raw_updates.py:388`, `:411`, `:669` | Ordinary fingerprint changes do not require global replay; incompatible format refuses before publication; changed hints update metadata, preserve unrelated component references and retain withdrawn discovery facts. Executed with memory-backed source/catalog fixtures. |
| `test_native_raw_cli.py:239` | Changed seed bytes get a distinct candidate directory; exact retry and later code-only operation do not reacquire data. Executed with fakes. |
| `test_catalog_raw_updates.py:98`, `:326`; `test_source_replay_capture_stream.py:18`, `:52`, `:88` | Worker interruption resumes retained values; qualification refuses unproven facts; replay remains bounded/repeatable. Memory-backed cases executed; native-binary-dependent cases were skipped. |
| `114e3d9e:test_source_replay_capture_stream.py:118`; `114e3d9e:test_catalog_raw_updates.py:711` | Inspected regression assertions for wrong same-shape cache and changed/missing qualification file pin. Not executed here because the follow-up is not checked out; root owns combined integration verification. |

Concrete limitations are explicit refusals: no HTTP-range support, missing version validator, ZIP64, split archives, an oversized manifest or an unsupported member compression leaves work failed/pending. These paths are covered by local fixtures; this review does not infer that every production archive conforms. The first response can include a small entire ZIP when it fits the tail budget, but large packages do not fall back to full downloads.

### Executed checks

- Fix-focused run at `db1ac045`: **75 passed** (GPO failure/mapper, ZIP transport and HTTP policy).
- Combined GPO/raw/CLI/replay/workflow run at `db1ac045`: **283 passed, 12 skipped, 2 sandbox-blocked fixtures**. Both failures were `PermissionError` from the fixture's `ps` process inspection, not a data assertion.
- Targeted rerun with process inspection enabled: **4 passed**, including both previously blocked fixtures and two overlapping cases. Across the runs, all **285 runnable distinct cases passed**; the **12 native-binary-dependent cases were not executed** because this worktree had no configured qualified `DOCSPEC_BINARY`.
- Logs: `/tmp/gpo-combined-review-20261026-tests.log` and `/tmp/gpo-combined-review-20261026-workflow-retry.log`.
- `git diff --check` and the staged check passed for the fix.
- No new live GovInfo calls, full-catalog rebuilds, remote data writes, workflow executions, pushes or merges occurred during this review. Earlier two-package live evidence is historical evidence for the earlier commit, not a new hosted/deployed qualification of the merged source.

## Exploration notes

- **H1:** package isolation, range bounds and retained evidence should compose through weekly sync. ZIP/XML/pending traces confirmed the collector behavior; the weekly mapper refuted the end-to-end claim. F1 was reproduced and fixed.
- **H2:** ordinary seed changes should replay affected owners while preserving migration refusal and unrelated facts. The CLI candidate hash, changed dependency closure, schema checks and seed fixtures confirm that scoped behavior. This does not establish complete production delivery.
- **H3:** explicit qualification and retry must verify selected and retained bytes. Reading production-only cache admission and qualification resume refined this hypothesis: reviewed main had the F2/F3 gaps; static inspection of `114e3d9e` confirms the intended corrections and their focused test assertions.

## Initial conclusion at `ad222085`

**VERDICT: REQUEST CHANGES for `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.**

The GPO ZIP acquisition and routine seed-refresh paths achieve their central intent, but the reviewed main needs F1's weekly-summary correction and F2/F3's raw custody corrections. The GPO correction is committed separately as `db1ac0454409df3edfbd457431e3428f4fd41a81`; the raw corrections are in `114e3d9ee8e7886f32d1bf07ed5bd8b60c1e7d07` and were independently inspected without competing edits.

Coverage of runnable local paths: **ADEQUATE** for this scoped review. Confidence: **HIGH** for the reproduced mapper defect and **MEDIUM** for complete integration, because the native-dependent cases and new raw follow-up tests were not executed here. No additional GPO or seed-format regression was found in the traced paths. Final combined-head checks and hosted/deployed qualification remain separate responsibilities.

## Final source and delta review

**Final source SHA: `6183938fcb2b0842d5e1f59072383aa7dd251d32`. Final scoped verdict: APPROVE.**

The branch was rebased onto this exact main revision after preserving `9e3e8b14db7249bd62e92e92d2140e7eeb44c383` as `codex/gpo-review-before-final-source-20261026`. Git dropped `db1ac045` as already applied and preserved the report as rewritten commit `8625309b3ad243e3e29c839ab26bf94b089b860c`. The earlier source backup `codex/gpo-xml-boundary-before-review-20261026` still points to `fb073f02b85cbab65701f3bc1aeb7a593df60ee2`. The branch contains only review documentation beyond final main; it does not reapply any source fix.

Only the relevant `ad222085..6183938f` delta was checked in this final pass:

- `a3beabac` integrates the exact F1 mapper and regression-test changes from `db1ac045`. A direct file diff between the original fix and final source is empty for `weekly_tables.py` and `test_gpo_acquisition_xml_failures.py`.
- `c7b678bf` integrates the F2/F3 corrections from `114e3d9e`. A direct file diff between that reviewed follow-up and final source is empty for `catalog_raw_updates.py`, `source_capture_inputs.py` and their two changed test files.
- The remaining final commits change publisher identity coverage, the preparation deadline and the occurrence writer. They do not modify the GPO collector, ZIP transport, weekly mapper, seed-format gate or source replay functions traced here. Their broader review remains with their assigned owners; this pass did not repeat that audit.

Seven focused tests ran on the final source with no skips: the failed-only collector-to-weekly-sync case, three direct observation-section cases, two damaged/missing interpreted-file pin cases and the same-shape wrong-capture-cache case. **7 passed in 2.02 seconds.** Log: `/tmp/gpo-final-delta-review-20261026-tests.log`. This directly executes the raw follow-up cases that were static-only in the initial pass, using memory-backed fixtures rather than a native full-catalog operation.

The coordinating chat's final integration logs were also inspected: 264 cross-cutting Python checks passed in `/tmp/ct-post-review-integration-20261026.log`; 126 renderer/native checks passed in `/tmp/ct-post-review-occurrence-20261026.log`; 154 JavaScript checks passed in `/tmp/ct-post-review-js-20261026.log`. These are reported root runs, not runs performed by this reviewer, and are not added to earlier counts as unique coverage.

The three scoped findings are resolved in final main. Coverage is **ADEQUATE** for the traced changes; confidence is **HIGH** for those paths. The earlier twelve native-dependent skips remain a limitation of this reviewer's initial execution, not evidence of a production failure. There is no unresolved GPO/seed-migration issue or local blocker from this review. Hosted workflow execution, publication, full-catalog qualification and deployment remain separate claims. No publisher enablement, Pages setting or remote data was changed.
