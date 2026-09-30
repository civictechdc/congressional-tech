# Congress API maintenance audit

The September 30, 2026 audit covered all 108 Python files in the ten
responsibility directories under `packages/congress_api/src/congress_api`.
Ten GPT-6.1 agents each owned one directory. The primary agent reviewed the
combined diff, traced changed callers and tests, corrected integration defects,
and ran independent validation. The comparison baseline is `5d55b0d`.

The existing directory boundaries remain useful. This change removes repeated
work, reuses existing parsing and timestamp helpers, closes file handles, and
fixes concrete rejection and failure paths. Explicit publisher models,
source-specific acquisition policies, matching rules and replay protections
remain separate.

## Findings and resulting behavior

| Finding | Result | Evidence |
| --- | --- | --- |
| Month-based Eastern offsets could produce the wrong scheduled hearing time | Time conversion uses the date's actual daylight-saving rules | `transcripts/context.py:153`; `tests/test_congress_api_transcripts_refactor.py` |
| A failed audio probe could become an empty successful transcript; invalid chunk steps could prevent progress | Failed probes raise; invalid chunk settings fail before I/O | `transport/audio.py:62`, `:77`; `tests/test_congress_api_transport_refactor.py` |
| Missing optional Gemini token accounting caused valid generated text to be retried or discarded | Valid turns return on the first successful response; missing counts follow the existing zero-count convention | `transport/gemini.py:87`; transport regression tests |
| Invalid worker counts and direct-library budgets failed late or selected surprising work | CLI and workflow checks reject invalid settings before their dependent work; valid defaults, zero budgets and optional limits retain their meaning | `cli/common.py:23`; acquisition and CLI regression tests |
| Malformed recording references and Senate listing-check values could crash adapters | Original payloads remain retained; recording values produce the existing invalid-reference issue; malformed listing checks do not assert freshness | `adapters/recordings.py:13`, `adapters/senate.py:112`; adapter regression tests |
| GPO replay parsed irrelevant malformed cache before deciding to preserve acquired evidence | Acquired MODS is admitted or skipped before cache interpretation; admitted invalid cache still records a failure | `replay/gpo.py:29`; replay regression tests |
| Six writers left partial temporary files on failure | Writers clean temporary files and preserve the previous destination when serialization or replacement fails | Retention trace below; retention regression tests |
| The transcriber had a second Senate URL parser that could fail after transcription | It uses `parse_player_url` before transcription, accepts encoded query keys, and requires a single filename for output | `cli/transcribe.py:38`; CLI regression tests |
| The HTTP metadata test required sockets despite the offline CI gate | The test now parses actual HTTP bytes in memory, preserving duplicate headers and proving metadata inspection does not read the body | `tests/test_http_response_metadata.py` |

Source paths above and below are relative to
`packages/congress_api/src/congress_api`; test paths are relative to the repository.
The daylight-saving, invalid-input, malformed-evidence and failure-path changes
are deliberate behavior corrections. They are not described as byte-equivalent
refactors.

## Directory coverage

| Directory | Files audited | Main decision |
| --- | ---: | --- |
| `models` | 14 | Resolve House scalar XML children once; retain explicit native schemas |
| `parsers` | 21 | Share House XML setup, simplify speaker matching, count repeated witness indexes once |
| `matching` | 14 | Simplify title dates; reuse nominee, access and membership calculations |
| `acquisition` | 8 | Partition refresh work in one pass and validate budgets early |
| `adapters` | 14 | Reuse timestamp validation and handle malformed retained evidence |
| `transcripts` | 6 | Correct Eastern times and close CSV readers |
| `cli` | 12 | Reuse argument validators, close readers and reuse Senate URL interpretation |
| `transport` | 6 | Correct audio and optional Gemini-accounting failure paths |
| `retention` | 9 | Complete temporary-file cleanup without changing serializers |
| `replay` | 4 | Move GPO protection before parsing; House and Senate need no changes |

## Function traces

These are the changed behavior paths. Imports, a redundant local `re` import,
and documentation corrections have no separate runtime behavior.

| Function and location | Input and output | Caller and verified behavior |
| --- | --- | --- |
| `models/house.py:133` `text_fields` | XML node and field model -> scalar model | House field properties; aliases, missing/empty and first-child behavior preserved |
| `models/house.py:242` `field_location` | Meeting details -> typed field location | House parser/adapters; nested state remains a node |
| `parsers/house_xml.py:11` `_parse_house_xml` | Bytes/string/element/model -> typed House XML | Two public parsers; expected root and original-byte capture preserved |
| `parsers/house_xml.py:27` `parse_house_meeting` | Supplied meeting XML -> meeting model | House acquisition/evidence; existing model returns by identity |
| `parsers/house_xml.py:31` `parse_house_witnesses` | Supplied witness XML -> witness model | House acquisition/evidence; rejection messages and retained bytes preserved |
| `parsers/speaker_names.py:31` `match` | Participants, reference and preference -> participant key | Transcript parsing/context/generation; suffix, fallback, order and preference preserved |
| `parsers/senate_page.py:239` `source_details` | HTML, URL and people -> metadata | Senate page parser; repeated names still refuse ambiguous ownership |
| `matching/recordings.py:108` `title_dates` | Upload title -> date set | Recording inventory; accepted formats and invalid-date/Unicode rejection preserved |
| `matching/completeness.py:48` `build` | Meetings and supplied observations -> rows | Inventory CLI; witness priority, shared-print filtering and access unchanged |
| `matching/gpo_committees.py:58` `clean_rows` | Hearing rows -> updated rows | GPO acquisition/replay; primary code and source spelling preserved |
| `acquisition/gpo.py:79` `main` | Paths and collection options -> saved evidence/CSV | GPO CLI; worker rejection precedes credentials and pending writes |
| `acquisition/house.py:133` `main` | Source paths/state/options -> state and tables | House CLI; valid refresh ordering/bounds and partial-state safeguards preserved |
| `acquisition/senate.py:218` `main` | Source paths/state/options -> state and tables | Senate CLI; negative budgets fail before reads |
| `adapters/inventory.py:24` `records` | Retained observations -> source records/assessments | Explorer exporter; timezone and future-time rejection preserved |
| `adapters/recordings.py:13` `recording_reference` | Retained token -> recording identity or refusal | Recording, meeting and Senate adapters; valid identity construction unchanged |
| `adapters/senate.py:59` `_live_receipt` | Page, URL and current time -> usable receipt or none | Senate adapter; mode, URL, status and timestamp checks preserved |
| `adapters/senate.py:112` `records` | Retained sites/pages -> normalized records | Explorer exporter; source payloads and identities preserved |
| `cli/common.py:23` `positive` | Argument text -> positive integer or error | Four thread-count parsers; no workflow invoked for invalid counts |
| `cli/gpo_fetch.py:12` `parse_args_and_run` | Arguments -> collection call | Console entrypoint; valid options and unknown key flags preserved |
| `cli/gpo_transcripts.py:12` `parse_args_and_run` | Arguments -> transcript call | Console entrypoint; positive workers required |
| `cli/meetings.py:12` `parse_args_and_run` | Arguments -> meeting collection | Console entrypoint; positive workers required |
| `cli/senate_captions.py:28` `parse_args_and_run` | Arguments -> caption workflow | Console entrypoint; validation precedes workflow invocation |
| `cli/gpo_match.py:40` `load_videos` | Cache directory/channels -> video index | GPO matching CLI; table-suffix channel identity and missing-file numbering preserved |
| `cli/gpo_match.py:85` `main` | Saved inputs -> matching output | Console entrypoint; file handles close, CSV interpretation unchanged |
| `cli/transcribe.py:38` `parse_args_and_run` | Recording options -> JSON/text artifacts | Console entrypoint; recording precedence retained, Senate stem resolved before processing |
| `replay/gpo.py:29` `replay` | Saved CSV/cache/evidence -> output and receipt | Replay CLI; acquired evidence skips irrelevant malformed cache |
| `retention/gpo.py:64` `write_observation` | Typed observation -> alias JSON | Published/generated transcript workflows; unset-field serialization preserved |
| `retention/gpo.py:90` `write` | Package dictionary -> gzip JSONL | Acquisition/replay; sorted compact UTF-8 and deterministic headers preserved |
| `retention/tables.py:37` `write_csv` | Ordered rows/fields -> CSV | Acquisition/inventory/replay; UTF-8, row order and CRLF preserved |
| `retention/tables.py:58` `write_state` | State -> deterministic gzip JSON | Acquisition/inventory/replay; temporary path differs from any destination |
| `retention/rejected_pages.py:8` `retain_rejected_page` | Rejected payload -> appended sidecar | Congress collectors; payload/time/indentation unchanged |
| `retention/transcripts.py:12` `retain_response` | SDK response -> retained capture | Gemini transport; explicit absent body and serialization preserved |
| `transcripts/context.py:81` `gpo_rows` | Configured CSV -> cached rows | Roster/context preparation; missing-file, order and newline behavior preserved |
| `transcripts/context.py:153` `et_time` | Aware timestamp -> Eastern time text | `context_for_event` -> generated scheduled-time fallback; actual timezone transitions applied |
| `transcripts/generate.py:59` `from_gpo` | Package/CSV -> transcript | Transcriber CLI; reader closes, duplicate last-row selection preserved |
| `transcripts/gpo.py:39` `main` | GPO CSV/options -> published text | GPO transcript CLI; reader closes, interpretation and capture policy unchanged |
| `transcripts/senate.py:151` `main` | Player URLs/index -> caption artifacts | Caption CLI; index reader closes, last-row behavior preserved |
| `transport/audio.py:62` `duration` | Local media -> duration or probe failure | Chunking/transcription; nonzero process exit raises |
| `transport/audio.py:77` `chunks` | Media and chunk settings -> paths/offsets | Transcription; invalid settings fail before probe; valid offsets preserved |
| `transport/gemini.py:87` `transcribe_window` | Recording window -> turns/events/usage | Transcription and recursive splitting; capture still precedes parsing |

## Invariants and review corrections

The primary agent inspected the changed paths and relevant callers/tests, rather
than relying on worker reports. Review caught and corrected:

- An assignment expression that overwrote the selected primary committee code.
- A narrowed exception handler that stopped rejecting Unicode month-regex edge cases.
- A new cleanup path that could delete the destination when it was named `state.tmp`.
- A typing regression in the shared House XML helper.
- Proposed shared CSV reads that would change embedded newline interpretation.

The primary agent also reproduced the transcriber URL failure before fixing it;
both initial regression cases failed against the old implementation. Added cases
check that path-valued filenames are rejected before transcription.

The retained byte formats, digest encoding, domain/source keys, alias reuse,
parser/schema/capture versions and ten console names remain unchanged. The
existing identity, source-fidelity, boundary and exporter tests exercise these
invariants. Observation timestamps remain separate from import times, and
replay does not invent a retrieval time. No saved source data was rewritten.

## Validation

Final integrated result: **4,452 tests and 31 subtests passed** in 64.89 seconds
with network connections disabled. Ruff's `E9,F` checks and `git diff --check`
also passed. A source/test digest taken before the suite still matched after
completion, confirming that no worker changed the tested Python files mid-run.

The primary agent executed the repository CI command with its virtual environment:

```sh
.venv/bin/python .github/scripts/offline-python.py -m pytest -q \
  tests packages/committee_meeting/tests packages/house-naming/tests
ruff check packages/congress_api/src/congress_api \
  tests/test_congress_api_*_refactor.py tests/test_http_response_metadata.py \
  --select E9,F
git diff --check
```

Additional checks executed by the primary agent:

- Verified the parser oracle's original files against Git, then repeated 14,336
  speaker comparisons, eight House XML comparisons including object identity,
  and fifteen Senate metadata comparisons.
- Independently extracted baseline House model functions and compared 1,448
  readings; compared 1,684 upload-title date cases and twenty primary/additional
  committee-code cases against baseline functions. All matched.
- Generated short local audio with real `ffmpeg`; verified three readable
  chunks at the expected offsets and real `ffprobe` rejection of a missing file.
- Supplied an actual installed Gemini SDK response model with no usage metadata
  to a mocked client. Valid turns and one source capture survived without retry.
- Executed the corrected README surname example using the retained fixture.

The initial offline baseline had 4,370 passes and one local-socket fixture
failure; that fixture passed normally. The in-memory HTTP test fixes that
validation incompatibility without weakening the no-network runner.

Local receipts are under `/tmp/congress-api-audit/`, including the full test log,
baseline comparison script/log, pre-fix CLI failures and tested source digest.
Worker reports are `/tmp/congress-api-audit-<directory>.md`.

## Remaining limits

This is local code and fixture validation, not a full historical-corpus replay
or live publisher/Gemini qualification. No push or deployment occurred.
The following existing behaviors remain follow-up candidates:

- `transport/audio.py:69` and `:77`: cached cuts/chunks use rounded time or part
  names rather than all requested parameters; reusing a directory with changed
  chunk settings needs an explicit cache policy.
- `transcripts/generate.py:135`: transcription mutates objects from its hearing
  context. The current CLI creates one context per run; reuse across multiple
  runs needs separate handling.
- `transport/gemini.py:127`: broad retry and exhausted-window fallback still
  require source receipts to distinguish persistent failure from empty output.
- Retention uses fixed adjacent temporary names and assumes one writer per
  destination; this change adds neither locking nor crash-durability guarantees.

The dated committee integration proposal contains historical source paths. It
identifies those citations as belonging to its original reviewed checkout, so
this audit did not rewrite that historical evidence.

## Review decision

**APPROVE the integrated patch.** The local changes have adequate regression
coverage and passed independent review and the full offline gate. Confidence is
high for the changed paths. This establishes a useful maintenance pass; it does
not establish that every package-wide design or failure-handling problem has
been resolved. Future work should target the concrete remaining behaviors above,
rather than expand the patch with cosmetic extraction.
