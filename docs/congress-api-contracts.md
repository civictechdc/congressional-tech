# Congress API compatibility and maintenance

The acquisition tools retain publisher inputs; source parsers interpret bytes;
`adapters/` translate source models into `committee_meeting`. The exporter owns
persistent IDs and publication. These boundaries and the interfaces below are
preserved by the refactor. See [source verification](../packages/congress_api/SOURCE_MODELS.md#verification-and-limits)
for the source-value and original-byte fidelity checks.

Shared file readers and capture writers live in `retention/`; collection and
transcript workflows call them, and the explorer owns its publication inputs. Transcript normalization accepts `TranscriptInput(data, name, uri)`;
it validates supplied bytes with `models.transcription.Transcript` and never
opens the URI. The exporter uses the same bytes for the input snapshot and the
transcript representation. Invalid bodies still retain their digest, location
and validation issue. Inventory matching accepts `(committee_code, video_row)`
pairs; `read_youtube_videos` reads the generated channel caches separately.

## Meeting interpretation and matching

`matching/meetings.py` owns meeting type, access and hearing eligibility for inventory,
House/Senate collection, adapters and Parquet conversion. Explicit publisher types
take precedence over title inference. Generic meetings stay generic, and a briefing
does not establish closed access. Both ordinary and field hearings can have witnesses.
The returned source field preserves the distinction between reported and inferred values.

`meeting_completeness.csv` uses these types in `kind` and includes `access`:
`open`, `closed`, `partly_closed`, or `unknown`. Its retained `closed` column is `yes`
only for a fully closed meeting; blank does not mean open. Native source fields
and the inventory's raw `type` column remain unchanged.

| Rule | Owner and intentional limits |
| --- | --- |
| Inventory population | `matching.meetings.in_inventory_scope`; the exporter uses the same population for print matching. Senate's explicit Indian Affairs/Drug Caucus exceptions remain in its collector. |
| Print associations and same-day title sharing | `matching.prints`; inventory and explorer use the same matcher. Print and recording sharing use the same grouping rule without merging meeting IDs. |
| Generic recording matches | `matching.recordings`; shared meeting classification feeds recording compatibility groups. Business meetings can match markup uploads; field hearings can match hearing uploads. Recaps and reactions cannot establish this weak match. Upload-title keywords never relabel the meeting. |
| Possible rescheduling | `matching.recordings.reschedule_candidate`; closed/partly closed sessions and recurring briefings/depositions are excluded. This is a matching restriction, not an access determination. |
| GPO hearing ↔ video verdicts | `matching.gpo_decisions`; `matching.gpo_videos` only scores candidates. Overrides, locks, clip divert, greedy assignment and status rows are decided here. `cli.gpo_match` loads files and writes the CSV. |
| Senate page associations | `matching.senate_pages.associate_pages` returns `events` and `match_details` (`senate.records.match_pages`, then exact `senate.records.match_identifiers`). Acquisition checkpoints that result on each site's `workflow` map, keyed by page URL. Weighted titles stay in `match_pages`; exact proof stays in `matching.senate`. Adapters consume the retained decisions. |

Publisher page-heading labels still require their source-specific layout and a
matching dated sitting. Reported status remains distinct from a title-based
`not_held` or possible-rescheduling indication. Neither missing recordings nor a
past date proves that a meeting occurred.

The two print rules that depend on meeting type (`markup_print_day` and
`unique_committee_day`) now emit rule version `2` and the classification field used.
New Senate page associations record matcher version `2`; retained unversioned
associations keep their prior version `1`. These changes do not require refetching
source files or changing source-parser versions.

## Commands and artifacts

These ten production console script names are stable. Default data paths are relative
to `packages/congress_shared/src/congress_shared/data/`, not the working directory.
Paths marked required have no default. CLI `--help` is safe without credentials.

| Command | Primary artifacts and paths | Invocation family |
| --- | --- | --- |
| `congress-meetings` | `congress_meetings.jsonl.gz`: meeting JSONL (XML recoveries include `_source_xml`); sibling `.pending.json` retry state and `.gz.rejected.json` rejected listing pages | Custom; `--output-path`, `--nthreads` (5) |
| `congress-committees` | Required `--output-path`: gzip JSONL Congress-specific lists plus full committee details/history with separate capture times; adjacent `.rejected.json` when listing/detail validation fails | Custom; required `--meetings-path`, optional `--gpo-path` |
| `gpo-fetch` | `gpo_hearings.csv`; optional `--evidence-path`: gzip JSONL of retained MODS/HTML and acquisition receipts | Custom; `--output-path`, `--chambers` (`hsj`), `--min-congress`, `--full-relist`, `--nthreads` (4), `--refresh-limit` (100) |
| `gpo-match` | `gpo_hearing_videos.csv`; default coverage file beside it, named `gpo_hearing_video_coverage.csv` | Global `--tinydb_dir`; `--gpo-path`, `--meetings`, `--channels-csv-path`, `--overrides`, `--no-overrides`, `--output-path`, `--coverage-path` |
| `house-meeting-records` | Required `--state-dir/house.json.gz`; `--output-dir/{house_documents_found,house_witnesses_found,house_amendments_found}.csv` | Source flags; required `--gpo-path`; `--refresh-limit` (400), `--limit`, `--zyte`, `--threads` |
| `senate-meeting-records` | `--state-dir/senate.json.gz`; `--output-dir/{senate_hearing_pages_found,senate_witnesses_found,senate_documents_found}.csv` | Source flags; `--refresh-limit` (450), repeatable `--site`, `--since`, `--limit` |
| `meeting-inventory` | `--state-dir/inventory.json.gz`; `--output-dir/{hearing_text_sources,meetings_without_records,meeting_completeness,meeting_witnesses}.csv` | Source flags; required `--gpo-path`, `--videos-path`, `--tinydb_dir`, `--recordings`; optional `--channels-csv-path`, `--youtube-caption-index`, `--senate-caption-index` |
| `gpo-transcripts` | Required `--out-dir/<package>.txt`, with original HTML observation in `source/<package>.json`, including short rejected text | Custom; `--gpo-path`, `--congress`, `--committee`, `--chamber`, `--package-ids`, `--nthreads` (4) |
| `senate-captions` | Required `--out-dir/<filename>.txt`, `<filename>.captions.json.gz` (raw playlists/WebVTT), `caption_receipts/<filename>.json`, and `captions_index.csv` | Custom; `--urls`, `--urls-file`, `--nthreads` (4) |
| `hearing-transcribe` | Required `--out-dir/{stem}.json` and `{stem}.gpo.txt`; `source/` contains retained HTML/Gemini attempts | Custom; `--event-id`, `--gpo-package`, `--video-id`, `--senate-url`, `--audio`, `--proxy`, `--gpo-path`, `--meetings` |

`cli.common.source_args` defines required `--meetings`, `--state-dir`,
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

`tests/test_congress_api_boundaries.py` freezes script names, checks source purity
and the workflow's explore exclusion. `tests/test_congress_api_imports.py` enforces
the allowed folder imports declared in `pyproject.toml`, including relative and
nested imports. This is a local/CI
regression gate, not evidence that a new workflow has run on GitHub.

## Offline behavior

See [meeting-state.md](youtube-coverage/meeting-state.md). `--offline` disables
acquisition, not file I/O, parsing, state persistence, or CSV joins.

| Command | Required saved results | Work still performed | Failure |
| --- | --- | --- | --- |
| House reader | Usable `house.json.gz` entry for every selected missing-record meeting, or usable seed XML/HTML | Optional seed import; print matching; rewrite deterministic state and three CSVs; old usable observations can remain | Missing or error-only selected entry raises `House source incomplete` after saving state; age alone does not force HTTP |
| Senate reader | Usable per-site listing/pages in `senate.json.gz`, or complete local seed pages for initial import | Seed parsing; native duplicate guards and retained matching; state/three CSV writes | Missing required listing or failed seed import raises; existing saved sites skip live discovery and refresh |
| Inventory | `inventory.json.gz` probe results for eligible unrecorded Senate days and parsed MODS/PDF witness sources as needed; seed cache can provide missing observations | Caption-index/receipt import, seed imports, CSV/YouTube joins, nominee extraction; rewrite inventory state and four CSVs | Missing required probe or witness source raises; missing input files also raise. Recent days (<7 days old) remain deferred. A saved empty witness list or negative probe is usable evidence |

The inventory application (`cli.inventory`) calls `acquisition.gaps` for day
probes and witness collection. `matching.completeness.witness_sources` selects
inputs; `matching.completeness.build` consumes collected MODS/PDF observations.
Neither matching step reads files or calls acquisition. The acquisition helpers
retain their injectable `get=http.get_with_retry` dependency and thread-local
session behavior. PDF/MODS parsing belongs to `parsers.witness_pdf`; old forwarding
wrappers were removed. Partial acquisition state is still saved on failure.

## Parser, schema and capture versions

This is the complete set of declared parser/schema/capture version owners in
`src/congress_api`, plus the inline evidence/transport versions. Imported aliases
are not separate owners. The AST registry test catches new or changed constants.

| Owner | Version | What it governs / consumer |
| --- | --- | --- |
| `parsers.house_evidence.SCHEMA_VERSION` | `"1.1"` | House evidence; House reader refresh queue and House replay |
| `parsers.senate.PARSER_VERSION` | `10` | Parsed Senate pages; skips empty headings, preserves joint-participant card ownership, and distinguishes explicit amendments within Legislation; bounded maintenance and Senate replay |
| `parsers.gpo_hearings.PARSER_VERSION` | `"3"` | GPO CSV/evidence interpretation; fetch and cached replay |
| `parsers.witness_pdf.PARSER_VERSION` | `2` | PDF/MODS witness observations; retained with names and bytes |
| `transcripts.senate.CAPTURE_VERSION` | `"3"` | Caption-capture completeness; stale receipts trigger recapture |
| `models.transcription.SCHEMA_VERSION` | `"1.0"` | Transcript JSON; exported through `transcripts.render`, checked by transcript adapter |
| `transcripts.senate` receipt `schema_version` | `"1.0"` | Caption receipt layout, separate from capture algorithm |
| `transport.http.response_metadata` `response_metadata_version` | `2` | Parsed response header/status fidelity |

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
`python -m congress_api.replay.house`, `python -m congress_api.replay.senate`,
`python -m congress_api.replay.gpo`. No shared replay loop or receipt schema.

| Driver | Admission / skip gates | Preserved values | Receipt and output |
| --- | --- | --- | --- |
| House | Current evidence skips; only absent/1.0 schema can upgrade. Require usable raw cache and exact `MATCH_FIELDS`: documents, witnesses, amendments, XML update, status, witness status | All saved fields except enriched `evidence` and added `replay`; especially checked/version/retrieved_at and live receipts | Explicit distinct `--state` / `--output`; sibling `house-replay.json`; per-event input paths/digests, matched fields, replay time and counts |
| Senate | Skip live markers (`retrieved_at` on the page, `observation_check`, live `last_check` on that page's `workflow` record; an old file that still has those checks on the page is lifted before this test), current parser, missing HTML, absent title or changed text lines | Existing witnesses, document URLs/labels, associations and check/acquisition times; an explicit section or primary witness-file button may refine `other`; add new document URLs and structured metadata; possible-match annotations do not rematch | Distinct `--input` and `--output-dir/senate.json.gz`; three CSVs; `replay-report.json`; `workflow[url].cache_replay` has digest, parser version and null acquisition time |
| GPO | Ignore unlisted packages; skip acquired MODS; parse failures recorded. Use `merge_cached_row`, retain acquired transcripts | CSV title, held_date, last_modified, hearing_dates, text_read, committee_code/name, event_id, serial; old scalar corrections win; URL metadata can grow | Explicit CSV/evidence/receipt paths; receipt includes input/output SHA, package changes, disagreements, unmatched caches and failures. Cached evidence does not invent retrieved_at |

Run `test_house_source_fidelity.py`, `test_senate_source_fidelity.py` and
`test_gpo_source_fidelity.py` for receipt fields and source-specific protection.
Compare each driver's own before/after receipt fields, not one generic schema.

Document-index refresh also reinterprets Senate link sections from the exact
retained page digest. `source_link_heading` preserves the publisher's words;
`publisher_section_heading` distinguishes an explicit “Transcripts” section
from filename/link-word inference. `parsers.document_cover` recognizes numbered
GPO hearings, stenographic transcripts, opening statements, explicit testimony,
paper-hearing questions, and official bill/substitute covers from native text.
GPO covers must be on page one; a blank first page permits checking page two for
proceedings. `content_document_kind`, `content_citation`, `content_congress`, and
`content_amendment_type` retain supported meanings separately from filename
fields. This check does not use OCR or classify attachments from a generic
“Related Files” heading. Missing or unrecognized evidence leaves the kind empty.

Witness-card ownership no longer requires its label to parse as one individual.
The typed occurrence retains the raw `witness_card`; `source_participant_label`
exposes its name in the catalog. A paired label does not establish coauthorship
or create individual witness records. Literal URL dot segments are normalized
for matching and grouping, while original source URLs and anchors stay intact.
Content classification never confirms a candidate source association.
The member-card section remains distinct even when it uses the witness-card
layout. PDF extraction accepts public files that open with an empty password;
files requiring a password abstain. A source-metadata refresh preserves native
publisher observations already retained in the table when the current readers
do not reproduce them, including House XML document type codes and receipt
locations. It still replaces parser-inferred classifications.
For the same original page and link, explicit publisher types and sections
take precedence over older inventory/link-word guesses when selecting a kind.
Both observations remain visible; distinct parents are never collapsed by this
precedence rule.

Bold testimony labels within a paragraph also describe that paragraph's links,
including Indian Affairs testimony links labeled only with bill numbers.
Independent successful Senate HTML captures contribute their own page digest,
receipt, anchor, and witness context even when an older saved page has no digest.
They remain separate observations; they do not replace the older capture or
invent a meeting association.

A retained Senate Judiciary nomination-page link with explicit support wording
adds the `nomination-support` family. An otherwise unclassified document also
gets that kind with `document_kind_source=source_context`; known letters,
statements and other forms keep their specific kind. The page and label must
belong to the same retained anchor. Legislative references and unconfirmed link
associations do not qualify. Refreshes recompute this classification from the
retained context rather than caching it as filename meaning.
An explicit “Letter of Support” link label supplies the more specific
`letter-of-support` kind with `document_kind_source=source_link_label`.

## Filename migration and legacy scope

Phase 5's proposed `filenames/` package and temporary facades were superseded by
the user's later decision to migrate **entirely** to `packages/house-naming`.
`congress_api` has no filename parser or bill-code facade and does not depend on
that package. The independent `house-naming[corpus]` extra owns PyArrow and
Parquet inventory tooling; `house-naming[test]` supplies its regression dependencies.
See its [corpus documentation](../packages/house-naming/FILENAME_PATTERNS.md).
The `tests/test_filename_*.py` consumer gate remains part of validation.

The user approved retiring the unused Congress exploration tools after preserving
their remaining acquisition capabilities. `congress-fetch`, `congress-analyze`,
`congress_api.legacy`, the old `api`, `fetch`, `analyze`, `xml_to_dict` and
`json_to_tinydb` imports are removed. Use `congress-meetings` and
`congress-committees`; see the [removal audit](legacy-congress-removal.md).
Production rejected-page retention remains in `retention.rejected_pages`.
YouTube collectors and TinyDB caches remain active. Physical collector/parser
moves and a unified CLI remain deferred.
