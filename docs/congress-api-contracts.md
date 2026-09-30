# Congress API compatibility and maintenance

The acquisition tools retain publisher inputs; source parsers interpret bytes;
`adapters/` translate source models into `committee_meeting`. The exporter owns
persistent IDs and publication. These boundaries and the interfaces below are
preserved by the refactor. See the [source-model review](../packages/congress_api/SOURCE_MODEL_REVIEW.md)
for the source-value and original-byte fidelity gate.

## Commands and artifacts

These twelve console script names are stable. Default data paths are relative
to `packages/congress_shared/src/congress_shared/data/`, not the working directory.
Paths marked required have no default. CLI `--help` is safe without credentials.

| Command | Primary artifacts and paths | Invocation family |
| --- | --- | --- |
| `congress-meetings` | `congress_meetings.jsonl.gz`: native meeting JSONL; sibling `.pending.json` retry state and `.gz.rejected.json` rejected listing pages | Custom; `--output-path`, `--nthreads` (5) |
| `congress-committees` | Required `--output-path`: gzip JSONL committee snapshots; adjacent `.rejected.json` when listing validation fails | Custom; required `--meetings-path`, optional `--gpo-path` |
| `gpo-fetch` | `gpo_hearings.csv`; optional `--evidence-path`: gzip JSONL of retained MODS/HTML and acquisition receipts | Custom; `--output-path`, `--chambers` (`hsj`), `--min-congress`, `--full-relist`, `--nthreads` (4), `--refresh-limit` (100) |
| `gpo-match` | `gpo_hearing_videos.csv`; default coverage file beside it, named `gpo_hearing_video_coverage.csv` | Global `--tinydb_dir`; `--gpo-path`, `--meetings`, `--channels-csv-path`, `--overrides`, `--no-overrides`, `--output-path`, `--coverage-path` |
| `house-meeting-records` | Required `--state-dir/house.json.gz`; `--output-dir/{house_documents_found,house_witnesses_found,house_amendments_found}.csv` | Source flags; required `--gpo-path`; `--refresh-limit` (400), `--limit`, `--zyte`, `--threads` |
| `senate-meeting-records` | `--state-dir/senate.json.gz`; `--output-dir/{senate_hearing_pages_found,senate_witnesses_found,senate_documents_found}.csv` | Source flags; `--refresh-limit` (450), repeatable `--site`, `--since`, `--limit` |
| `meeting-inventory` | `--state-dir/inventory.json.gz`; `--output-dir/{hearing_text_sources,meetings_without_records,meeting_completeness,meeting_witnesses}.csv` | Source flags; required `--gpo-path`, `--videos-path`, `--tinydb_dir`, `--recordings`; optional `--channels-csv-path`, `--youtube-caption-index`, `--senate-caption-index` |
| `gpo-transcripts` | Required `--out-dir/<package>.txt`, with original HTML observation in `source/<package>.json`, including short rejected text | Custom; `--gpo-path`, `--congress`, `--committee`, `--chamber`, `--package-ids`, `--nthreads` (4) |
| `senate-captions` | Required `--out-dir/<filename>.txt`, `<filename>.captions.json.gz` (raw playlists/WebVTT), `caption_receipts/<filename>.json`, and `captions_index.csv` | Custom; `--urls`, `--urls-file`, `--nthreads` (4) |
| `hearing-transcribe` | Required `--out-dir/{stem}.json` and `{stem}.gpo.txt`; `source/` contains retained HTML/Gemini attempts | Custom; `--event-id`, `--gpo-package`, `--video-id`, `--senate-url`, `--audio`, `--proxy`, `--gpo-path`, `--meetings` |
| `congress-fetch` | Explore-only TinyDB `committee-summaries.json`, chamber committee details; event URL discovery in memory. Full `events.json` requires the separate `process_events()` method | Global `--tinydb_dir` (shared data directory); `--chamber` (`house`), `--congress_number` (119) |
| `congress-analyze` | Explore-only stdout; reads committee/event/YouTube TinyDB files | Same global/explore flags; does not replace the production mirror |

`inventory.common.source_args` defines required `--meetings`, `--state-dir`,
`--output-dir`, optional `--seed-cache` (expanded path), `--offline`, and
`--as-of` (UTC today, ISO date). The source-reader and TinyDB flag families stay
separate. `congress_shared.globals.add_global_args` adds only `--tinydb_dir`.
The channels default is `congress_shared/youtube/youtube-accounts.csv`.
The key loader reads `--congress-api-key` through `parse_known_args`, then
`DATA_GOV_API_KEY`, then local key files; collectors load credentials at the CLI
edge. Commands using strict `parse_args` do not acquire new flags in this refactor.

## Weekly CI and publication

[update-data.yml](../.github/workflows/update-data.yml) has four jobs. Paths below
are relative to the checkout; `DATA_DIR` is `apps/committee_youtube/data`.

| Job | `needs` | Commands in order | Retained and derived paths |
| --- | --- | --- | --- |
| `youtube` | none | `youtube-fetch`, `youtube-analyze` | `pipeline-data/youtube`; `DATA_DIR/youtube_event_id_report.csv` and its site copy |
| `congress` | `youtube` | `gpo-fetch`, `congress-meetings`, `gpo-match` | `pipeline-data/gpo-evidence.jsonl.gz`, `pipeline-data/congress_meetings.jsonl.gz` and sidecars; GPO hearings, video matches and coverage CSVs in `DATA_DIR` |
| `meetings` | `congress` | `python -m pytest -q`, `house-meeting-records`, `senate-meeting-records`, `meeting-inventory` | `pipeline-data/meeting-inventory/{house,senate,inventory}.json.gz`; six source CSVs and four inventory CSVs in `DATA_DIR` |
| `committees` | `meetings` | `congress-committees` | `pipeline-data/congress_committees.jsonl.gz` |

Dependent jobs use `!cancelled()` so an earlier failure does not suppress all
later sources. Specific acquisition/save steps use `steps.*.outcome` to preserve
partial successes and failed-check receipts. There is no `continue-on-error`.
Derived-output commits still require success. Tests run before the House reader;
setup/test failures do not trigger its state-save step. YouTube commands belong
to `youtube-api`; neither explore command runs in the weekly workflow.

[publish-explorer.yml](../.github/workflows/publish-explorer.yml) runs after
`Update committee data` **completed**, including failed runs, and on configured
main-branch path pushes or manual dispatch. It shares the `update-data`
concurrency group. It records collection outcomes, restores persistent IDs,
exports retained inputs under `offline-python.py`, builds and verifies browser
data, then saves `pipeline-data/committee-explorer/{public,state,attempts.json}`.
Only that verified publication dispatches `deploy-pages.yml`. Collection success
alone is not a claim of successful publication.

`tests/test_congress_api_boundaries.py` freezes script names, checks production
imports, and checks the workflow's explore exclusion. This is a local/CI
regression gate, not evidence that a new workflow has run on GitHub.

## Offline behavior

See [meeting-state.md](youtube-coverage/meeting-state.md). `--offline` disables
acquisition, not file I/O, parsing, state persistence, or CSV joins.

| Command | Required saved results | Work still performed | Failure |
| --- | --- | --- | --- |
| House reader | Usable `house.json.gz` entry for every selected missing-record meeting, or usable seed XML/HTML | Optional seed import; print matching; rewrite deterministic state and three CSVs; old usable observations can remain | Missing or error-only selected entry raises `House source incomplete` after saving state; age alone does not force HTTP |
| Senate reader | Usable per-site listing/pages in `senate.json.gz`, or complete local seed pages for initial import | Seed parsing; native duplicate guards and retained matching; state/three CSV writes | Missing required listing or failed seed import raises; existing saved sites skip live discovery and refresh |
| Inventory | `inventory.json.gz` probe results for eligible unrecorded Senate days and parsed MODS/PDF witness sources as needed; seed cache can provide missing observations | Caption-index/receipt import, seed imports, CSV/YouTube joins, nominee extraction; rewrite inventory state and four CSVs | Missing required probe or witness source raises; missing input files also raise. Recent days (<7 days old) remain deferred. A saved empty witness list or negative probe is usable evidence |

The inventory orchestrator calls `inventory.acquisition` for day probes;
`completeness.build` calls it for witness sources. `get_witnesses`, `probe_day`,
and `probe_days` accept a defaulted `get=http.get_with_retry` collaborator.
The gateway receives `session=None` to retain its thread-local session behavior.
No CLI option or orchestrator `get` parameter is added. PDF/MODS parsing remains
in `witness_lists`; compatibility calls there delegate to acquisition.

## Parser, schema and capture versions

This is the complete set of declared parser/schema/capture version owners in
`src/congress_api`, plus the inline evidence/transport versions. Imported aliases
are not separate owners. The AST registry test catches new or changed constants.

| Owner | Version | What it governs / consumer |
| --- | --- | --- |
| `house.evidence.SCHEMA_VERSION` | `"1.1"` | House evidence; House reader refresh queue and House replay |
| `senate.records.PARSER_VERSION` | `5` | Parsed Senate pages; bounded maintenance and Senate replay |
| `gpo.fetch.PARSER_VERSION` | `"3"` | GPO CSV/evidence interpretation; fetch and cached replay |
| `inventory.witness_lists.PARSER_VERSION` | `2` | PDF/MODS witness observations; retained with names and bytes |
| `senate.captions.CAPTURE_VERSION` | `"3"` | Caption-capture completeness; stale receipts trigger recapture |
| `models.transcription.SCHEMA_VERSION` | `"1.0"` | Transcript JSON; exported through `transcribe.schema`, checked by transcript adapter |
| `senate.captions` receipt `schema_version` | `"1.0"` | Caption receipt layout, separate from capture algorithm |
| `http.response_metadata` `response_metadata_version` | `2` | Parsed response header/status fidelity |

Other source-model JSON and the GPO evidence store currently have no independent
schema-version constant. `TRANSCRIPT_JSON_SCHEMA` and Gemini `TURNS_SCHEMA` are
schema objects, not version counters. Do not invent a version from a class name.

For a parser upgrade: retain an immutable input snapshot; identify the owning
version and affected consumers; characterize old/new source interpretations;
run source-contract and adapter identity tests; bump only the appropriate owner;
replay retained bytes using that source's protection rules or schedule a bounded
refresh; compare receipt shapes, source fields, IDs, and output bytes. Do not
advance an acquisition time during replay. Breaking storage/identity changes
need an explicit migration and version decision, not an incidental counter bump.
`write_state` preserves sorted compact UTF-8 JSON and gzip `mtime=0`; changes to
that serialization require a state major-version migration.

## Adapter identity policy

Identity is layered. [ADR: adapter digest versioning](adr/adapter-digest-versioning.md)
records the compatibility decision.

* `adapters.common.digest` hashes UTF-8 JSON with sorted keys,
  `ensure_ascii=False`, and compact separators using SHA-256. Object key order
  does not change the hash; array order, spelling, nulls, absence and scalar types
  do. Source-model `source_dict()` preserves publisher keys and field presence.
* `AdapterContext.source` uses `provider|input_id|native_key|digest(payload)` for
  a **source observation**, not for every domain object's identity.
* Domain keys, such as `govinfo:{package}` and `{key}:published`, are passed to
  the application's `IdRegistry`. It persists random opaque UUIDs indexed by
  `[kind,key]`. Preserve the registry across rebuilds; rebuilding an empty
  registry is not identity-preserving.
* House document fallbacks use retained URL/source/owner keys, or `digest(group)`
  when no URL supplies a key. Existing-key aliases preserve unambiguous published
  identities and refuse to merge two already allocated IDs.
* `known_materials` from GPO `primary_rendition_index` reuses exact unambiguous
  primary publisher files across adapters. Mixed files, supplements and ambiguous
  versions do not establish whole-package identity. Keep both citations.
* Transcript versions use SHA-256 of **original file bytes**, separate from JSON
  normalization. Reformatting JSON can produce a new transcript version while
  retaining the semantic material key.

Changing digest encoding, payload normalization, key composition, ID persistence
or reuse rules is breaking if an unchanged source/domain record receives a new
identity. Even at package version 0.x, require an explicit migration: retain old
keys/registry, add unambiguous aliases where possible, compare old/new IDs and
publish a versioned migration receipt. A new input payload can legitimately add
a source observation; it must not silently replace unrelated material IDs.
Additive metadata and implementation cleanup are safe only when unchanged inputs
retain these identities. No digest algorithm or ID scheme changes in this refactor.

Required gates: `test_congress_api_boundaries.py` (digest/source keys),
`test_gpo_identity_reuse.py`, `test_house_source_fidelity.py` (alias reuse and
ambiguous-source negatives), and `test_explorer_*.py` (adapters, transcript bytes,
persistent registry and exporter). Compare retained IDs on changed inputs when
an adapter upgrade affects key formation; green digest tests alone do not prove reuse.

## Replay protection matrix

Each driver remains independent. The module CLI paths are stable:
`python -m congress_api.house.replay`, `python -m congress_api.senate.replay`,
`python -m congress_api.gpo.replay`. No shared replay loop or receipt schema.

| Driver | Admission / skip gates | Preserved values | Receipt and output |
| --- | --- | --- | --- |
| House | Current evidence skips; only absent/1.0 schema can upgrade. Require usable raw cache and exact `MATCH_FIELDS`: documents, witnesses, amendments, XML update, status, witness status | All saved fields except enriched `evidence` and added `replay`; especially checked/version/retrieved_at and live receipts | Explicit distinct `--state` / `--output`; sibling `house-replay.json`; per-event input paths/digests, matched fields, replay time and counts |
| Senate | Skip live markers (`retrieved_at`, `observation_check`, live `last_check`), current parser, missing HTML, absent title or changed text lines | Existing witnesses/document tuples, associations, check/acquisition times and prior labels; add new document URLs and structured metadata; possible-match annotations do not rematch | Distinct `--input` and `--output-dir/senate.json.gz`; three CSVs; `replay-report.json`; page `cache_replay` has digest, parser version and null acquisition time |
| GPO | Ignore unlisted packages; skip acquired MODS; parse failures recorded. Use `merge_cached_row`, retain acquired transcripts | CSV title, held_date, last_modified, hearing_dates, text_read, committee_code/name, event_id, serial; old scalar corrections win; URL metadata can grow | Explicit CSV/evidence/receipt paths; receipt includes input/output SHA, package changes, disagreements, unmatched caches and failures. Cached evidence does not invent retrieved_at |

Run `test_house_source_fidelity.py`, `test_senate_source_fidelity.py` and
`test_gpo_source_fidelity.py` for receipt fields and source-specific protection.
Compare each driver's own before/after receipt fields, not one generic schema.

## Filename migration and legacy scope

Phase 5's proposed `filenames/` package and temporary facades were superseded by
the user's later decision to migrate **entirely** to `packages/house-naming`.
`congress_api` has no filename parser or bill-code facade and does not depend on
that package. The independent `house-naming[corpus]` extra owns PyArrow and
Parquet inventory tooling; `house-naming[test]` supplies its regression dependencies.
See its [corpus documentation](../packages/house-naming/FILENAME_PATTERNS.md).
The `tests/test_filename_*.py` consumer gate remains part of validation.

Explore-only code lives in `congress_api.legacy`; old `fetch`, `analyze` and
`json_to_tinydb` imports/module commands remain compatibility aliases. Production
rejected-page retention belongs to `retention.rejected_pages`, outside the legacy
path. See [TinyDB decision](adr/tinydb-explore-sunset.md). Physical collector/parser
moves and a unified CLI remain deferred; this refactor does not add an HTTP
protocol, dependency container, or shared HTML scraper.
