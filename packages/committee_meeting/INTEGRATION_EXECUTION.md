# Congress API integration: execution receipt

Implemented and validated locally on 2026-09-27 in
`/Users/mikewolfd/Work/congressional-tech-production`, on
`codex/committee-explorer`, preserving the existing model and Explorer work.
The first adapter/export validation used source baseline `98db974`; the final
production integration adds bounded browser queries, persistent issue history,
automated publication and real Explorer views. Merge, first hosted execution and
public readback are release steps; this receipt does not claim they have run.
No new source acquisition was needed for these local checks.

The source packages now adapt their retained records into `committee_meeting`.
The application owns stable IDs, assembly, conflict/issue history and publication.
The model remains independent of acquisition. The current transcript body schema
and original bytes remain separate from the metadata model.

## Implemented boundary

- `congress_api/adapters/` imports complete native meetings, House/Senate source
  state, GPO packages, explained print matches, existing video decisions, manual
  recording associations, inventory observations, recovered witnesses and
  structured transcript bodies. `youtube_api/adapters.py` imports cached video
  metadata. None acquires new source content.
- `apps/committee_youtube/src/committee_explorer/` allocates persisted opaque IDs,
  retains disagreements and issue evidence, validates graph references and JSON
  evidence selectors, and exports immutable files before changing `CURRENT.json`.
  A failed export preserves the preceding publication. Documented resolutions
  retain original issue evidence; omitted sources do not silently close issues.
- The complete Catalog remains an offline export. The browser distribution
  excludes it and the old all-meetings index. Per-kind, per-Congress query pages,
  inverse relationship indexes and record/source locators support all six views.
  Gzip JSON is declared by manifest media type and stored with an opaque `.data`
  suffix so static servers cannot transparently decompress its hashed bytes.
  Parquet can supply the same records through a different decoder/source.
- The frontend generates domain types from the model schema and injects its data
  source. The publication reader pins the manifest and verifies hashes, sizes
  and counts. Real Explorer views use the query reader; the existing video-ID
  dashboard remains available through its separately injected report source.

## Producer corrections

House parsed results retain all XML file formats, metadata, active/removed rows,
source order, panels and witness ownership. New checks retain real request
receipts and distinguish seed import from retrieval. Failed checks keep previous
usable results. Parser upgrades join the bounded maintenance queue.

Legacy House action rows also map locally: 19,985 source rows produce 13,178
amendments, 6,746 votes and 241 en-bloc groups. The 61 repeated metadata/file rows
share an action and keep all row citations. The 356 fileless rows retain their
metadata. Existing exact-URL materials are reused; 35 additional explicit URLs
are retained. Incomplete bill numbers remain unresolved.

Senate listing/page requests now retain exact URLs, statuses and real UTC
attempt times. Seed imports have separate import times. Failed refreshes retain
both the last successful observation and the latest failure. PDF responses stop
before HTML parsing. One retained Intelligence Committee PDF had already become
garbled page text; its original payload remains with an explicit unverified
format issue, rather than being silently discarded.

Senate caption acquisition distinguishes a confirmed 404 from exhausted requests,
invalid playlists, empty responses and missing segments. A failed acquisition
cannot become an indexed `none` result. Successful independent work is saved
before a run reports failure. New sidecar receipts describe the exact live
WebVTT scope; they do not establish embedded archive-caption availability.

The existing print matcher returns optional per-association decisions without
changing its selection rules. Video decisions retain their aggregate scores and
methods as evidence, not probabilities. Shared or multiple-date GPO packages do
not distribute recordings across meetings. An inferred package association stays
inferred in its recording link and downstream caption coverage.

Transcript imports preserve contextual participants without creating attendance,
global people or an actual meeting start. The scheduled-time producer note gets
its own issue. The owner deserializer checks structure/version but is not a full
JSON Schema validator; every imported representation states that limitation.

## Initial retained-data validation

The complete retained native/source/cache input was extracted locally from
`origin/pipeline-data` commit `acc8108dca3239fe275c708b5372a5a44a108eb4`.
Current committed GPO/video/manual/recovered tables and six existing transcript
examples are separately pinned by their exact bytes. The raw-state revision is
not incorrectly assigned to those separate files. Export time is never called a
source check time.

Inputs include all 18,139 native meetings, including 96 canceled and 323
postponed entries; 5,741 House states; 4,925 Senate pages across 21 sites; 34,559
GPO package rows and 34,559 retained recording decisions; all 52 YouTube cache
files; all 11,163 inventory observations; all 18,495 recovered witness rows; the
manual recording table; and all six structured bodies in
`docs/youtube-coverage/research/data/transcribe_compare/`.
The 18,495 recovered rows contain 18,479 distinct rows. Exact repeated appearance
descriptions can share an appearance while retaining each source observation;
different descriptions stay separate. Equal names do not create global people.

`coverage.json` publishes input reconciliation, source observation counts, current
record counts and explicit coverage rules. Recording, transcript, document,
witness and caption states are exclusive within their own meeting denominator:
observed, reported, curated, derived, inferred, error, blocked, scoped not-found,
not-applicable, unknown and unchecked. Positive evidence takes precedence for
this inventory; every failed or conflicting check remains inspectable in detail.
An availability numerator includes inferred evidence only with that state shown
separately. Partial recording links are evidence of some material, not complete
meeting coverage. Current, historical and all-retained issues have separate
counts and overlap with coverage states.

The denominator is retained provider entries in all statuses, not a claim about
distinct hearings held or expected publications. Unknown and unchecked canceled,
closed or future entries do not become publication failures. The older inventory
has a narrower selection and different caption inference rules, so its counts
are compatibility measures rather than interchangeable Explorer metrics.

## Initial archive artifacts

`CURRENT.json` contains `schema_version`, `publication_id`, `manifest_path`,
`manifest_sha256` and `media_type`. Manifest partition counts for Catalog count
`records` only; source counts remain separate.

- `catalog.json`: `committee_meeting.Catalog`, role `download`.
- `indexes/meetings.json`: `{schema_version, rows}`.
- `indexes/locations.json`: `<kind>/<id>` key format, `sha256-prefix-2` bucket
  algorithm, bucket paths, chunk byte budget and oversized single records.
- `indexes/locations/<prefix>.json`: `{schema_version, locations}` mapping each
  record/source key to its detail/source partition.
- `details/*.json` and `sources/*.json`: `{schema_version, records}` or
  `{schema_version, sources}`, respectively.
- `coverage.json`: evidence-state counts, rules and input reconciliation.
- `inputs/print-decisions.json`: exact retained decisions from the existing
  matcher, as a hashed export input.

Each descriptor specifies schema/version, media type, SHA-256, byte size and
record count. Detail/source chunks target 2 MiB. One indivisible source record
can exceed the target and is listed explicitly. The meeting index and raw print
explanations are separately measured artifacts, not claimed to fit that budget.

The first complete retained pass published
`82dd9a9347f0084e884944fb` at `.cache/committee-explorer/full-public/CURRENT.json`:
2,022,057 domain records and 221,141 sources in 249.88 seconds. Peak resident
memory was 14,824,144,896 bytes; peak footprint 17,628,132,528 bytes; no swaps.
Catalog was 1,721,264,624 bytes. The largest detail chunk was 2,097,151 bytes.
One source chunk was 24,453,323 bytes because of the retained garbled PDF.
This pass preceded the final manual-association/body additions and inference
propagation correction; its counts are not the final publication counts.

The verified final publication is **`c71a7a56ae823fb802a09779`** at
[the local current pointer](../../.cache/committee-explorer/full-public-verified/CURRENT.json).
It contains **2,022,160 domain records and 221,170 source observations**, including
23 manual recording associations and six retained transcript bodies. Runtime was
237.98 seconds, maximum resident memory 14,378,926,080 bytes, peak footprint
17,667,028,120 bytes, with no swaps. The complete Catalog is 1,725,805,252 bytes.
There are 665 detail chunks; the largest is 2,097,151 bytes. Source chunks have
one explicitly listed 24,453,323-byte exception; raw print-decision input is a
separate 24,971,419-byte artifact.

Independent [full reconciliation](../../.cache/committee-explorer/full-reconciliation.json)
verified every one of the 1,075 partition hashes, byte sizes and row counts,
every locator, and the exact native identity population. Exact retained payload
sets match all eleven providers. The check compares distinct payload values
within each pinned input; repeated identical values do not imply dropped source
observations. Separate provider counts and locator checks cover all 221,170
source observations. Every one of the first pass's 2,022,057 domain IDs survives.

This check found that the initial CSV reader had stripped embedded newlines in
25 video-match notes. The reader now preserves quoted multiline fields, with a
regression test. The corrected publication replaces those 25 immutable source
observations and retains every domain ID. The intermediate candidate
`0bf26e726bff3e3d4482b2cb` is superseded; its successful consumer check alone was
insufficient to prove native-field preservation.

The [verified consumer receipt](../../.cache/committee-explorer/verified-reader-receipt.json)
records 18,139 indexed meetings, a retrieved meeting and its cited source, and
five coverage metrics. It made nine requests totaling **15,452,677 bytes** and
requested no Catalog. Every requested artifact passed the manifest's hash, size,
count and schema checks. The meeting index is 9,573,387 bytes.

Final meeting evidence states illustrate the distinction between availability
and inference. Recording evidence is reported for 7,902 meetings, curated for
34, derived for four and inferred for 4,846; 5,353 remain unchecked. Caption
evidence is reported for 1,899 and inferred for 72; 8,757 are unknown and 7,411
unchecked. Each aspect totals 18,139. No live observation state is fabricated.
All underlying assessments and overlapping issues remain in the detail records.

[The full export log](../../.cache/committee-explorer/full-export-verified.log)
and [independent verifier](../../.cache/committee-explorer/verify_full.py) retain
run evidence beside the ignored generated artifacts. The exact reproduction
arguments are the README export command with the pinned local full-inputs paths,
`--as-of 2026-09-27T18:00:00+00:00`, the raw-state revision above, all six
`--transcript` paths, the preserved `full-state` ID directory, and a fresh local
output directory. Artifact and input digests provide the exact byte identities.

## Validation and remaining work

The complete offline compatibility replay ran House → Senate → inventory against
copies of all retained state, with socket and DNS access blocked. All three
commands passed and all ten output CSVs were byte-identical and keyed-row-identical
to committed `98db9745ee3283742da36fb0b6ba301c65c3d043`. No network attempt occurred.
The old reports still contain 17,606 inventory rows and 18,495 recovered witness
rows. Original inputs and tracked data were unchanged. Timings were 3.4 seconds
for House, 57.5 for Senate and 5.8 for inventory.

Detailed compatibility evidence is in
[the local report](../../.cache/committee-explorer/compatibility/output/README.md)
and [comparison JSON](../../.cache/committee-explorer/compatibility/output/comparison.json).
The runner and stage log are beside them. These prove retained-data replay,
not today's live upstream layouts or availability.

Both previously tracked package `uv.lock` files were stale before this work.
They now include current local/transitive dependencies. No existing package
version changed; `uv lock --check` passes for both. CI install lines include the
local model package; the existing meetings test job also installs the exporter
app required by its new tests. The new publication workflow runs after the complete collection workflow settles; local validation does not claim its first hosted execution.

The initial adapter milestone passed **187 tests plus 31 subtests**. These include
model structure, adapter identity/provenance, raw field retention, issue history,
failure atomicity, exclusive coverage, source failure receipts, caption failures
and locator resolution. The exact CI editable install command passes a pip
dry-run; whitespace checks pass.

The initial frontend milestone passed 14 Node tests, generated-type drift checking and Astro checking.
The site build produces 27 pages. The existing dashboard still shows its retained
65,074 total / 8,037 event-ID / 57,037 missing-ID counts. Prototype checks cover
keyboard drilldowns/Back and a 390-pixel viewport. These UI checks use the
prototype fixtures and legacy report; they do not claim deployment of the new
full-data Explorer views.

The first complete archive was consumed through the partition reader in nine
requests and 15,444,648 bytes, without requesting its Catalog. The final reader
check is recorded separately with the final publication above.

| Plan phase | Local outcome | Remaining boundary |
|---|---|---|
| 1: prepare model/dependencies | Implemented against the production source baseline; drafts preserved. | Hosted PR checks and release execution remain separately observable. |
| 2: offline assembly | Bounded cases and complete retained population pass graph/selector/artifact checks. | Source acquisition remains independent. |
| 3: owner evidence | House/Senate receipts, House rich retention, caption failures and print explanations implemented and tested offline. | Missing historical receipts cannot be reconstructed from export time; new live checks have not run. |
| 4: reconcile | Complete retained input, stable IDs, exact source payload preservation and ten legacy report comparisons checked. | No claim of complete upstream collection or globally deduplicated proceedings/people. |
| 5: publish | Immutable releases, digest checks, issue checkpoints and pipeline-data publication/deploy workflows implemented. | First hosted publication, deployment and public readback must be recorded after merge. |
| 6: consumers | Real views use typed injected query/related readers; compressed bounded artifacts avoid the full Catalog and old index. | Legacy reports retain their different selection semantics. Public adoption is verified at deployment, not inferred from local checks. |

Specific limits remain visible:

- All retained source families are represented, but this is not all congressional
  material upstream. No missing historical bytes, receipts or original parser
  context are fabricated. Legacy flattened House rows cannot recover every
  alternate URL or ownership fact; some older raw research cache files exist
  separately and have not been promoted into these pinned pipeline inputs.
- Only retained metadata says a link exists. URL reachability, complete recording
  coverage, captured text and searchable text are distinct checks. Legacy negative
  caption flags are unknown, not proven absence. Senate date-cutoff caption
  inference is not silently promoted into a verified track.
- Old source schemas do not preserve all raw GPO MODS, exact original check times,
  authoritative YouTube channel IDs or individual video-match explanations.
  Transcript validation remains the owner's structural deserializer, with an
  explicit limitation rather than a full-schema validation claim.
- A person's appearance is source-scoped unless there is explicit identity
  evidence. Same-name witnesses, independent document listings and ambiguous
  meeting associations remain unresolved; no generic title/name merge hides them.
- The old 9,573,387-byte meeting index and 1.7 GB Catalog are excluded from
  the browser distribution. The first production package is 441,062,032 bytes;
  latest-Congress meeting query pages total 503,027 compressed bytes. Query pages
  are at most 59,580 compressed bytes in this run. The retained damaged PDF
  source remains an explicit 8,671,541-byte compressed exception; source bytes
  are not silently dropped to meet a transfer budget. Parquet remains optional.
- Full assembly still keeps the current graph in memory, but validates records
  individually instead of duplicating the graph. Old issues and their evidence
  load lazily from SQLite; the complete previous Catalog is never loaded.
  The first optimized production export used 10,835,804,160 peak resident bytes
  and took 382.44 seconds. The restored-state repeat used 10,466,000,896 peak resident bytes
  and took 489.63 seconds. This is a local macOS measurement, not a hosted-run claim.
- The public site has not loaded these artifacts, and no source-qualified live
  refresh or public readback is claimed. Those are concrete release/collection
  steps, separate from the completed local integration and replay.

## Production publication and storage

The automated input set contains every retained pipeline family above, but does
not import the six research transcript examples. Its first production build
contains **2,022,124 domain records and 221,164 source observations**: exactly
36 fewer domain records and six fewer source observations than the earlier
research-inclusive validation. All 18,139 native meetings remain. Body imports
remain supported through explicit `--transcript` arguments.

`publish-explorer.yml` runs after the entire collection workflow completes, also
on relevant main-branch changes and manual dispatch. It shares the collection
concurrency group, checks out settled retained inputs, blocks network access
during export, and records available collection-job results separately from
per-source evidence. A failed collection can therefore publish previous usable
records alongside its failed job receipt. A job receipt is never presented as a
successful check of every individual URL.

The exporter writes complete local files and persists stable IDs plus issue
history. The browser packager includes all domain/source chunks and bounded query,
locator and relationship indexes, excludes the complete Catalog and legacy
index, verifies compressed bytes, and rejects a package above 900 million bytes.
The Pages build verifies the pinned publication again and rejects total site
output above one billion bytes before deployment. Missing or corrupt data fails
before replacing the public site. Pages receives exact code and data commit IDs;
the old mid-collection deployment trigger has been removed.

Persistent IDs and issue closure belong on `pipeline-data`, together with the
browser distribution and collection-attempt receipts. They never enter code
history. SQLite retains only issues and their typed evidence dependencies, with
a small page cache and disk traversal queue. Each successful checkpoint replaces
prior SQLite releases only after its new publication/state pointer is saved.
The initial history is 435 MiB; the ID file is about 425 MiB. Checked tar/gzip
storage splits the combined checkpoint into 50 MiB chunks (nine files, about
421 MiB total). A full restore reproduced every ID, publication and SQLite byte.
Nonempty state without its manifest and corrupt chunks fail rather than silently
reset public identities. The existing single-snapshot pipeline branch policy
prevents weekly state history accumulating in Git.

The complete Catalog currently remains a local/runner artifact and is not
advertised as a hosted download. Filtered browser exports remain available.
PR validation has an independent no-secrets workflow with network-disabled
Python tests, browser-reader tests, generated-type drift checks, Astro checking
and a site build. This checks application code without starting collection.

The final backend suite passes **213 tests plus 31 subtests**, with
socket and DNS access blocked. The first compressed full-publication browser
check retrieved the latest Congress's 2,767 meetings and filtered coverage in
15 requests / 1,397,858 bytes, without requesting the Catalog or compatibility
index. Its transcript chart showed 433 non-inferred, 718 inferred and 1,616
unchecked meetings; selecting the inferred segment returned exactly 718 rows.
The witness view returned 9,749 source-scoped appearances. Browser navigation and
Back were exercised against these real retained records. Final repeated-build qualification follows.

## Final production qualification

The restored-checkpoint repeat produced publication
`b460a42dee7f7196f89e0b29`, with the same **2,022,124 domain records / 221,164
source observations / 18,139 meetings**. It completed in **489.63 seconds**
(8 minutes 10 seconds), with **10,466,000,896 bytes peak resident memory**
(9.75 GiB) and 14,177,528,584 bytes peak macOS memory footprint. It reads the
435 MiB issue checkpoint lazily and never loads the old Catalog. These measured
resident requirements fit the public repository's 16 GB standard Linux runner
with headroom; the first hosted run remains a separately observed release gate.
Source-independent exporter tests use blocked sockets and DNS.

The final browser publication is **`f749bcda356626b44851e3cc`**, at
[the local pointer](../../.cache/committee-explorer/production-browser-final/CURRENT.json).
It contains **454,402,946 bytes across 2,423 artifacts**, including the supported
material date/committee indexes and readable missing-committee labels. No full
Catalog or compatibility meeting index ships. Real browser readback verified:

- 2,767 latest-Congress meetings and 18,139 meetings across all Congresses;
- 718 inferred transcript rows from the corresponding coverage segment;
- 25,362 dated material rows for the latest Congress;
- meeting/source/related-record retrieval with all requested artifact hashes,
  sizes and counts checked;
- latest meeting query plus coverage in **15 requests / 1,431,494 bytes**, without
  a Catalog or old-index request.

The receipt is [production-reader-receipt.json](../../.cache/committee-explorer/production-reader-receipt.json).
The UI also passed real appearance, material/version/PDF, issue, Back-navigation
and 390-pixel viewport checks. It now builds 28 pages. The PR validation workflow
passed its Python, browser, type-generation and Astro checks; its hosted build
is tracked in the PR rather than inferred from the local build.

The independent complete first-production audit passed **2,320 partition
hashes/sizes, 2,243,288 typed record/locator identities, all graph constraints,
all retained source payloads, 18,139 native meeting identities and 2,316,860
inverse relationships**. It found no missing/duplicate edges. Prior IDs differed
only by the documented research transcript example closure. The audit used
578,158,592 bytes peak resident memory and took 466.66 seconds. See
[production-full-independent-reconciliation.json](../../.cache/committee-explorer/production-full-independent-reconciliation.json).
The final repeat receives focused input/ID/history/query checks instead of
repeating that identical complete source/graph audit.

Quality indexes all retained issues, including unresolved issues absent from
current inputs. Those rows explicitly carry `selection: retained_history`.
They preserve original detection, subject and evidence rather than implying a
new observation. The complete repeat has zero historical-only issues because
its input population is unchanged; a targeted omission regression proves the
history row remains searchable when the current source disappears.

Committee reader failures now save their raw-state receipt before the failed
job ends. The save step runs only after the House reader actually starts, on
success or failure and while the job is not canceled. Setup/test failures do
not publish a snapshot; derived CSV commits still require job success. Thus the
next Explorer publication sees the failed per-source check and its last usable
record, in addition to the separate coarse failed-job receipt.
