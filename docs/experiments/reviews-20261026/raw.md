# Combined raw-update and GPO boundary review — October 26, 2026

**Verdict for reviewed main `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`: REQUEST CHANGES.** Two raw replay/recovery defects reproduced locally and are fixed in `114e3d9ee8e7886f32d1bf07ed5bd8b60c1e7d07`. A separate GPO-to-weekly-summary defect is addressed by GPO-owned `db1ac0454409df3edfbd457431e3428f4fd41a81`; its exact changed function and four new boundary cases passed an independent check. Do not treat that separate check as a test of a subsequently combined integration revision.

The raw/GPO scope is acceptable after both fixes are integrated. No remaining actionable defect was found in the bounded GPO ZIP acquisition and per-package retry paths examined here. This is source review plus local fixture execution, not production data qualification, a hosted workflow result, or deployed proof.

## Findings

### 1. BLOCKER / correctness: same-shape capture cache can substitute unselected source bytes

At reviewed main, `packages/congress_api/src/congress_api/retention/source_capture_inputs.py:55-95` accepted `.cache/docspec-catalog/captures-0.parquet` when its schema, row-group count, and per-group row counts matched the selected raw batches. None of those checks bound its receipt keys, body keys, or other values to the selected native pins. `attach()` checked schema and ordinal sequence (`:39-52`) and then attached the selected batch reference to those substituted values.

Evidence chain: raw dispatch calls `prepare_source_replay()`; its initial production path calls `SourceCaptureInputs.changed()` (`source_replay.py:218-240`); the cache could therefore supply a different receipt while claiming the selected raw input. The new regression changes only the cached receipt key while preserving schema, ordinals, and shape. It returned the wrong table on main.

**Fix:** remove the shape-only cache substitution and use `snapshot.capture_batch(entry)` in both normal and batched metadata-upload branches (`source_capture_inputs.py:55-74` at `114e3d9e`). Bounded batch reads and batched metadata writes remain. Existing exact replay checkpoints still avoid repeating accepted input work. Regression: `test_source_replay_capture_stream.py:118`, `test_replay_uses_selected_capture_bytes_not_a_same_shape_local_cache`.

### 2. BLOCKER / correctness: resumed qualification did not verify its retained interpreted file

At reviewed main, `catalog_raw_updates.py:379-393` checked request metadata and the immutable source-update reference, then reopened `interpreted-sources.parquet` without a retained file digest. Fresh qualification compared replayed output to the selected baseline, but that comparison was skipped after a worker loss once `source-update.json` existed. The production qualification proof intentionally omits row-digest pages (`source_update_proof.py:169-177`); its production verifier can return directly for that representation (`:231-265`). Consequently, the resumed interpreted file needs its own exact identity check.

Evidence chain: stop immediately before `update_native_catalog()`, rewrite one interpreted label while keeping a readable Parquet table with the same logical schema and row count, then resume. Main reached the publication owner with the altered data. A continuation missing an interpreted-file pin also reached publication. Both cases are now regression controls, and both leave the selected catalog unchanged after refusal.

**Fix:** store the interpreted file's maintained `file_identity()` alongside the request and proof, and call `check_identity()` before constructing `_RetainedSources` on resume (`catalog_raw_updates.py:380-389,664-667` at `114e3d9e`). Missing identity refuses explicitly; no implicit acceptance of old unpinned continuations. Regression: `test_catalog_raw_updates.py:712`, `test_qualification_resume_checks_retained_interpreted_values_before_publication`, with changed-file and missing-pin cases.

The fix adds one sequential checksum read when retaining and resuming the interpreted file; no speed claim follows. It reuses the existing custody/checksum primitive rather than adding a second proof format or per-row remote metadata writes.

### 3. WARNING / correctness: rejected-only GPO evidence was not a valid weekly summary input

Independently confirmed the GPO task's finding at reviewed main: `weekly_tables.py:623-635` searched `mods` and `listing` for timestamps, but omitted `manifest`, `failed_mods`, and `failed_manifest`. A parser-stale existing CSV row can fail MODS retrieval without a fresh listing or accepted prior evidence; the collector still writes its new `failed_mods` record (`acquisition/gpo.py:177-184,303-309`). `_iter_gpo_observation_rows()` passes that retained record to the mapper (`cli/sync_weekly_tables.py:154-163`), which raises for the missing timestamp (`weekly_tables.py:662-664`). The JSONL evidence itself remains retained; the weekly summary route fails to consume it.

**Separate fix reviewed, not duplicated here:** `db1ac045` adds all three sections to the timestamp/acquisition scan. Read its complete diff and new tests, then executed its exact committed mapper and four new test cases in an isolated in-memory module substitution. The stale-MODS test follows collector → persisted rejected bytes → weekly summary, and the three section cases assert their timestamps and acquisition labels. All four passed. GPO owns this commit; this worktree does not cherry-pick or edit its mapper.

## Patch summary and scope

The combined source includes the ordinary seed/code-update simplification, true source qualification, GPO per-package XML failure handling, bounded ZIP-member transport, cache reuse conditioned on package modification, shared ZIP-directory validation, and streamed HTTP response cleanup. The caller in `.github/workflows/update-data.yml:90-102` supplies GPO evidence and a bounded parser-refresh allowance; partial failure still permits independent meeting acquisition and persists progress (`:111-120`).

Review scope: raw CLI dispatch, source replay/input binding, qualification, native catalog admission, GPO acquisition/evidence models, ZIP/HTTP transport, common ZIP-directory validation, relevant tests, and workflow callers. Proposed redesigns and viewer/capacity internals are outside this report. The combined target was reviewed directly; this is not just a re-review of the earlier raw branch.

Preserved starting tip: `codex/backup-raw-source-guard-20261026` → `f52108e6009f5051f1487906e17b7ad7c3f800ce`. Empty rebase moved this task branch to exact main `ad222085`; no old or superseded patches were reapplied. Review-fix parent is that exact main revision.

## Function traces

Paths below are repository-relative. Line numbers describe the reviewed target except rows explicitly marked “fix”.

| Function | Source | Input → output | Verified behavior and important caller |
| --- | --- | --- | --- |
| `raw_sync.run` / `seed_files` | `cli/raw_sync.py:48,482-509` | Seed files, selected raw identity, runtime → catalog result/summary | Operation identity includes seed file digests and current requirements; metadata updates dispatch through the retained owner. Capture and qualification modes remain separate. |
| `_update_from_raw` | `retention/catalog_raw_updates.py:294,372-444` | Raw snapshot, ordered seeds, previous selection → closed interpreted changes | Fingerprints are provenance; incompatible formats refuse. A changed seed digest bypasses the unchanged-raw shortcut and supplies URL/event dependencies. |
| `_retain_previous_tables` | `retention/catalog_raw_updates.py:151-165` | Exact selected native tables → baseline Parquet files | Always streams selected values, with no same-shape historical-table substitution. Used only for explicit complete modes. |
| `prepare_source_replay` | `retention/source_replay.py:79-161` | Raw changes, selected receipt graph, seeds → retained replay | Continuation request binds raw identity, graph root, seeds, dependencies, and requirements; accepted replay files are checked by exact hashes. |
| `_prepare` | `retention/source_replay.py:218-310` | Changed input references and related dependencies → closed receipt set and old source IDs | Replays related receipts and closes dependencies; it does not call a complete catalog scan. |
| `SourceCaptureInputs.changed` / `attach` | `retention/source_capture_inputs.py:39-74` (fix) | Selected raw batch entries → exact capture tables and receipt edges | Uses selected native bytes, verifies ordinal sequence/schema, and retains immutable batch references. Caller: `_prepare`. |
| `collect_source_inputs` | `retention/source_inputs.py:37-70,150-164` | Seeds, receipt-backed captures, document context → source rows | Seeds add discovery context; retained receipt ownership is carried into final source identities. Caller: `SourceObservationTrace.replay`. |
| `qualify_complete_values` | `retention/catalog_qualification.py:11-71` | Selected baseline versus fresh observed tables → exact equality or refusal | Checks fields, mappings, row presence, and values; permits only null nullable additions. Production compares complete tables; tests also exercise the disk-backed path. No full-corpus memory claim. |
| `update_native_catalog` / `publish_native_catalog` | `retention/catalog_updates.py:46-91`; `catalog_selection.py:387-479` | Closed replacements/deletions plus source proof → selected native catalog | Verifies source basis, schema/reference checks and counts, preserves reused components, and selects using the expected prior version. |
| `gpo.main` / nested `fetch_one` | `acquisition/gpo.py:87-156,162-253` | Listing, pending packages, retained evidence → accepted row or recoverable package failure | Pending work survives listing-window advancement. Successful package metadata and failed responses occupy separate evidence fields. |
| `read_zip_member` | `transport/zip_member.py:179-209` | Package ZIP URL, exact member name → complete member bytes and provenance | Requires exactly one member, admits stored/DEFLATE only, checks compressed/expanded limits, and relies on stdlib CRC validation. Caller: `fetch_one`. |
| `_RangeFile._fetch` / `_preflight` / `read` | `transport/zip_member.py:65-176` | Bounded HTTP ranges → validated bytes | HTTP 206, exact URL/length/range and stable ETag or Last-Modified; finite request/transfer limits; directory preflight before `ZipFile` allocation. |
| `validate_zip_directory` | `retention/archive_members.py:132-146` | Directory bytes and expected count → validation/refusal | Checks actual entry boundaries/counts before allocation; shared by retained and ranged ZIP readers. |
| `get_with_retry` | `transport/http.py:137-198` | Direct HTTP headers/stream option → response or typed error | Preserves range headers across attempts and closes rejected streamed responses. Custom streaming/headers are prohibited through the unrelated Zyte path. |
| `gpo.write` / evidence models | `retention/gpo.py:160-181`; `models/gpo.py:165-189` | Per-package source observations → retained evidence | Source bytes, range provenance, package modification pin, and failed-response fields survive JSONL persistence and typed readback. |
| `gpo_observation_to_row` | `retention/weekly_tables.py:610-683` | Retained evidence → weekly timestamp/acquisition summary | Reviewed target omits failure sections; independently checked `db1ac045` includes them. Caller: weekly sync iterator. |

## Data flow and invariants

1. **Ordinary seed updates preserve history.** `retain_source_seeds()` calculates an ordered digest while spooling input (`source_replay.py:23-34`). Raw dispatch compares it to selected metadata (`catalog_raw_updates.py:372-377`), refreshes related URLs/events (`:431-444`), and carries untouched components forward. Disappearing hints do not silently delete retained documents; intentional complete reinterpretation remains explicit. Exact before/after requirements and the selected raw identity remain in the source-update proof (`:635-663`).
2. **Source facts belong to selected raw inputs.** Capture batch references escape into receipt ownership through `attach()`. Reusing a local payload solely because its shape matches breaks this property; finding 1 removes that substitution. Existing replay checkpoint hashes remain valid reuse authority (`source_replay.py:120-142`).
3. **Qualification compares real observed values.** Fresh output runs the maintained writer (`catalog_raw_updates.py:584-605`) and then compares against the actual native baseline. Finding 2 closes the gap between that accepted result and a resumed file. No selected output is copied into the observed side as a success shortcut.
4. **Publication is conditional and coherent.** `CatalogReferenceCheck` rejects duplicate or mismatched source/document references (`catalog_validation.py:65-98`). Native admission verifies source basis and schema compatibility (`catalog_selection.py:387-430`), computes counts from prepared/retired components (`:467-470`), and uses a conditional selector write with lost-acknowledgment recovery (`:475-479`).
5. **The GPO ZIP version stays pinned across ranges.** The initial tail selects a strong ETag or Last-Modified (`zip_member.py:45-58`); later responses must have the same source size and validator (`:99-107`). The tail is at most 65,557 bytes; directory/member limits are 1 MiB by default, total requested transfer is at most 3 MiB, and there are at most 16 admitted range calls (`:17-19,65-67`). These are bounds of this reader, not a throughput qualification of every downstream raw capture. The reader has no full-download fallback.
6. **A failed package remains retryable without erasing valid history.** A failed manifest goes to `failed_manifest`, accepted manifest/file metadata stays separate, and failed packages do not enter transcript backfill (`gpo.py:216-230,268-277`). Evidence, accepted CSV rows and remaining pending packages are flushed before exit status 1 (`:303-316`). A successful retry removes the failure marker and pending item (`:228-230,309`). Cached manifests are reused only with a matching package modification pin and no prior failed attempt (`:198-212`).

## Test behavior and boundary cases

| Tests / source | Assertion traced and execution result |
| --- | --- |
| `test_daily_seed_changes_refresh_metadata_and_keep_retained_documents`, `test_catalog_raw_updates.py:670` | Both production and test branches add a new URL, refresh a retained label, preserve unrelated values/component references, and retain documents after seed withdrawal. Whole-catalog/capture scans are forbidden inside the update. Passed. |
| `test_daily_code_fingerprint_changes_do_not_require_global_replay`, `:389`; incompatible-format control `:411` | Four fingerprint fields may change without forced replay; incompatible contribution format still refuses before native work and selector mutation. Passed. |
| Daily CLI retry test, `test_native_raw_cli.py:239` | Same raw selection plus changed seed file creates a distinct continuation; exact retry reuses completed work; a later implementation gets a fresh directory. Passed. |
| Qualification equality/refusal tests, `test_catalog_raw_updates.py:292,326,630,652` | Exact values qualify; an unreplayed historical fact refuses; same-shape baseline caches are not authority. Positive production-path fixture and real native variants passed. |
| New checksum-resume controls, `:712` | Worker loss before native grouping; altered file or missing pin then refuses before publication, preserving the selector. Both failed on target and pass with fix. |
| New capture-cache control, `test_source_replay_capture_stream.py:118` | Same schema/count/ordinals with a different cached receipt must not substitute selected bytes. Failed on target and passes with fix. |
| Worker-loss/source-replay tests, `test_catalog_raw_updates.py:97,475`; `test_source_replay_capture_stream.py:52,88` | Exact accepted retries resume without repeating raw input/native work; corrupted replay payload and changed continuation inputs refuse. Passed. |
| ZIP transport tests, `test_zip_member_transport.py:73-229` | Nonfirst member, comment/end signatures, Last-Modified fallback, HTML/ignored ranges/redirects/encoding/truncation, changed versions/sizes, missing/duplicate members, CRC, directory/resource limits and streamed retry cleanup. Passed. Read installed stdlib `ZipExtFile._read1` and `_update_crc` to confirm bounded DEFLATE output and end-of-member CRC behavior. |
| Collector failure tests, `test_gpo_acquisition_xml_failures.py:25-174` | Malformed/wrong XML, HTTP failure and wrong package retain old values, flush a valid neighboring package, keep pending retries beyond the next listing window, and do not swallow unexpected assertion failures. Passed. |
| Real range-reader collector test, `:177-222` | Real local `requests.Response`/ZIP reader fixture feeds the collector. Accepted manifest bytes/provenance persist; HTML soft errors retain bytes and pending state while the CSV row stays unchanged. Passed. |
| Cache/source fidelity tests, `test_gpo_source_fidelity.py:108-205`; typed evidence/adapter tests, `test_gpo_source_models.py:76,201` | Same-version cached manifests are reused; changed packages and prior failures refetch; old error manifests refresh; source bytes/unknown fields and parsed manifest file representations survive without new CSV columns. Passed. |
| GPO-owned new mapper tests at `db1ac045`, `test_gpo_acquisition_xml_failures.py:157-189` | Independently executed exact changed function with all four new cases. Includes failed-only stale MODS → stored bytes → weekly summary. Passed separately; not part of the 261-test branch suite. |

### Executed evidence

- **Red reproduction on target:** 3 failures across the two new defect tests (one same-shape capture case, two continuation-integrity cases).
- **After fix:** 6 targeted checks passed, including valid interruption/resume controls.
- **At exact fix commit `114e3d9e`: 261 tests passed in 121.16 seconds.** Log: `/tmp/ct-raw-combined-review-20261026.log`. Suite covered `test_catalog_raw_updates`, `test_native_raw_cli`, `test_source_update_proof`, `test_source_replay`, `test_source_replay_capture_stream`, `test_zip_member_transport`, `test_gpo_acquisition_xml_failures`, `test_gpo_source_fidelity`, `test_gpo_source_models`, `test_archive_members`, `test_http_policy`, `test_congress_api_boundaries`, and `.github/tests/test_raw_source_workflow.py`.
- Native fixture binary: existing `.cache/docspec-catalog/docspec-remote`; temporary workspaces, two compute threads, 512 MiB native memory and 256 MiB scratch. The maintained offline wrapper disabled external network access. Publisher responses in these tests are local fixtures, not live GovInfo calls.
- **Separate independent GPO check:** exact `db1ac045` mapper and four new cases passed using isolated in-memory module substitution; no mapper cherry-pick or shared-checkout edit.
- `git diff --check` passed. No full catalog rebuild, remote data write, hosted workflow dispatch, push, shared-main merge, or primary-checkout edit occurred here. Root-provided integration logs were not reused as evidence for this task's changed fix revision.

## Conclusion

**VERDICT: REQUEST CHANGES for `ad222085`; scoped approval after integrating `114e3d9e` and GPO-owned `db1ac045`.**

The ordinary-update simplification preserves retained documents and concrete admission checks. Fresh qualification performs real comparison, and the two additional fixes preserve exact raw/retained inputs across recovery. The GPO manifest reader and collector failure paths meet their stated bounded-acquisition and recoverability behavior in the reviewed source and fixtures. The separate weekly mapper gap has a reviewed and independently checked fix.

Coverage of this scope: **ADEQUATE**. Confidence: **HIGH** for reproduced/fixed defects and local collector behavior; production throughput, hosted/deployed state, and a later combined integration revision remain outside this evidence. No remaining blocker in this scope once both repair commits are integrated.
