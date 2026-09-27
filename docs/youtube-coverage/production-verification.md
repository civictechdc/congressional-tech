# Meeting inventory production verification

Verified locally on 2026-09-27 in `congressional-tech-production`, branch `claude/production-pipeline`, against baseline `a1705b6f26f91fa1b57c3e7fa36b27ac6fdc120a`. The real `../pipeline-data` and research caches were read only. The main checkout was read only for the explicitly supplied API credentials. No push, merge, tag, branch switch, SerpAPI search or transcription was performed.

## Result and ownership

The weekly pipeline now runs three additional commands, in this order after `gpo-match`:

| Command | Modules | Reads and writes |
|---|---|---|
| `house-meeting-records` | `congress_api.house.records`, `.repository` | Meeting export and GPO table → House documents, witnesses, amendments/votes; parsed `house.json.gz` state |
| `senate-meeting-records` | `congress_api.senate.records`, `.pages` | Meeting export and committee listings/pages → Senate pages, witnesses, documents; parsed `senate.json.gz` state |
| `meeting-inventory` | `congress_api.inventory.main`, `.text_sources`, `.prints`, `.completeness`, `.captions`, `.witness_lists` | Export, GPO tables, YouTube caches, curated recordings and reader CSVs → text index, no-records list, completeness and witnesses; `inventory.json.gz` state |

`congress_api.http` owns retries and host pacing; `.zyte` owns the optional Zyte client; `.xml` owns BOM-tolerant XML and MODS element access; `.witnesses` owns name parsing and person keys; `.committees` owns parent codes/aliases. The transcriber adapts those plain witness fields to its own `Person` model. GPO fetching and the inventory share `gpo.fetch.mods_witnesses`; existing `gpo.match` and `senate.isvp` helpers remain authoritative.

Deleted the five promoted research implementations: `hearing_text_sources.py`, `house_event_pages.py`, `senate_hearing_pages.py`, `meeting_completeness.py`, `zyte.py`. Moved their ten CSV outputs and the curated `meeting_recordings_found.csv` input to `apps/committee_youtube/data/`. Research-only scripts remain; their imports/default input paths now use the production owners where necessary. The House/Senate readers no longer consume the index, so no second indexing pass is needed.

## Equivalence

Inputs were the 18,139-record meeting export, the committed GPO CSVs, 67,244 cached YouTube videos, and read-only research caches for the initial parsed state. The production inventory contains the same 17,606 eligible meetings.

| Table | Research rows | Production rows | Comparison |
|---|---:|---:|---|
| `house_documents_found.csv` | 18,126 | 18,126 | Byte-identical |
| `house_witnesses_found.csv` | 7,939 | 7,939 | Byte-identical |
| `house_amendments_found.csv` | 19,985 | 19,985 | Byte-identical: 13,231 amendments, 6,754 votes |
| `senate_hearing_pages_found.csv` | 2,900 | 2,900 | Byte-identical |
| `senate_witnesses_found.csv` | 9,401 | 9,401 | Byte-identical |
| `senate_documents_found.csv` | 14,407 | 14,407 | Byte-identical |
| `meetings_without_records.csv` | 970 | 970 | Byte-identical |
| `hearing_text_sources.csv` | 17,606 | 17,606 | Same keys; 37 `text_source` cells changed |
| `meeting_completeness.csv` | 17,606 | 17,606 | Same keys; the same 37 caption cells plus four cells for event 112626 |
| `meeting_witnesses.csv` | 18,496 | 18,495 | One invalid row removed; every retained row identical |

All column names and ordering are unchanged. [The cell-by-cell comparison](production-equivalence.json) includes keys, values and output SHA-256 hashes. Every difference has one of these causes:

1. **Eight YouTube caption classifications:** three House meetings move from `video_no_captions` to `youtube_captions`; five Senate meetings move from `senate_captions` to `youtube_captions`, respecting the original source priority. Their cached API caption flags supply evidence absent from the manual caption index.
2. **29 Senate caption classifications:** recognized studio filenames since August 2023 move from `video_no_captions` to `senate_captions`. All 29 were checked live: 32 master playlists, including multiple recordings for some meetings, advertised subtitle tracks. Three additional `comm=xxxx` placeholders were excluded. [The measurements](production-verification.json) retain each event/filename result. Caption text was not downloaded.
3. **One PDF parsing correction:** event `112626` attaches a two-column member-day schedule. The old `pdftotext` reading order invented a witness `Van Drew` with position `Rep. Jackson-Lee` and organization `Rep. Escobar, Rep. Tenney, OPEN`. `pypdf` preserves the schedule rows; this yields no usable witness names. The witness count becomes zero, its source becomes empty, `witness_list_document` becomes `unparsed`, and the already-shared print is now correctly flagged. The invalid witness row is removed. A real one-page fixture covers this case. `unparsed` is the sole new column value; a text PDF is not mislabeled a scan.

Current text-source totals: GPO 11,459; committee transcript 610; YouTube captions 2,085; Senate captions 679; recording without confirmed text 1,751; no recording 1,022. The 970-row no-records list is unchanged after postponements and not-held records are excluded.

## Incremental behavior and cost

The commands retain parsed results and confirmed absences, never raw pages, XML, PDF or caption text. House state also retains XML `update-date` and Congress.gov `updateDate`; GPO witness lists use `last_modified`. A changed source marker triggers a fresh read. Unchanged meetings become due weekly through 30 days, every 28 days through two years, then annually; a newer House XML update restarts the faster schedule. Maintenance budgets are 400 House meetings and 450 Senate pages, with the oldest due checks selected across the corpus; new/changed records are additional. This is a bounded queue, not a guarantee that a synchronized backlog clears at its first due date.

Evidence for retaining older refreshes: among 6,155 House XML records, the median update lag was one day, the 90th percentile 188 days, the 95th percentile 330 days and the 99th percentile 728 days. There were 268 updates after one year, 62 after two years, and 19 XML update dates later than Congress.gov's marker. The seeded age groups imply mean maintenance demand of 364 House and 404 Senate checks per week, below the configured budgets.

The 30-day replay starts with **17,492 meetings**, then adds **114** (66 House, 47 Senate, one joint). It removes the recent records' parsed House results and 22 matched Senate pages before running the actual production refresh decisions against retained responses:

- 63 House meetings fetched: **125 replayed requests**.
- 16 Senate listings refreshed and 22 pages fetched: **92 replayed requests**.
- **217 total source requests**, zero external requests, **36.40 seconds** for the added batch; 88.56 seconds including setup and the older-input pass.
- Required House pacing alone would take at least **150 seconds**. Replay does not measure internet latency, retries or alternative-address failures.
- A separate live incremental run removed five House results, fetched their ten XML files and restored identical reader outputs in **13.25 seconds**.

A settled weekly replay made **zero source requests**. A real subsequent week still lists the Senate sites, handles new/changed inputs and spends the due maintenance budget. House requests remain 1.2 seconds apart, with a 60-second pause after 403. Zyte is optional for parallel backfills and unused by the weekly workflow. Confirmed archive answers are retained once per committee-day; a new day waits seven days before its initial probe. A request error is never saved as absence.

Caption evidence is deliberately compact: 4,376 YouTube observations and 1,374 unique Senate filenames, from 1,386 index rows whose duplicate keys retain the last observation as in the research. YouTube's cache has 3,146 true flags, 64,092 false flags and six unknowns. Among the caption probes, 2,433 false-flag videos had automatic captions and 1,649 had none. Duration does not distinguish them. Therefore, a false flag cannot remove known automatic captions or prove their absence. The 719 observed Senate WebVTT tracks and 655 unique negatives override the date rule.

## Tests, live checks and workflow

- **43 offline tests passed**, covering four real House XML fixtures, seven real Senate layouts, a real PDF, name parsing, addresses, matching, source priority, refresh scheduling, host pacing, failure handling and persisted archive absences. Fixtures total about 124 KB before whitespace trimming.
- **14 console scripts** passed `--help`; `as_run/web.py` imports successfully.
- **9/9 `gpo_parse_check.py` prints passed** after the refactor, spanning House/Senate/joint proceedings and multiple eras; retained speech ranges from 70% to 96% of source words.
- **House live:** five distinct meetings, **20 direct requests** across refresh and incremental checks; all 200. The required pacing code also has a deterministic 403/backoff test.
- **Senate live:** five committee sites, **47 requests**: Budget, Finance, Foreign Relations and Veterans' Affairs used three each; HSGAC used 35. All commands succeeded and the six reader CSVs remained unchanged.
- **Zyte:** **one** successful request. **Data APIs:** three successful calls total: YouTube video details, GovInfo collection listing and Congress.gov meeting detail. The collection listing returned zero new packages for the selected day.
- **Archive:** two committee-days checked live, one existing recording and one confirmed absence. Caption manifest checks used the Senate CDN, without visiting additional committee sites.

The workflow's eight commands ran locally in order against a copy of `pipeline-data`. Upstream Data API responses replayed a no-change week; accidental networking was forbidden. Thus this verifies the full command sequence and outputs, rather than claiming a full live API sweep. Separate bounded calls above check the actual services.

Two settled passes produced **byte-identical results for all 19 checked CSV/gzip files**, including all ten promoted tables and all three parsed-state files. The measured complete pass took **140.42 seconds**: YouTube fetch 0.99, analyze 42.15, GPO fetch 0.35, meetings 1.24, GPO match 57.19, House reader 2.18, Senate reader 32.68, inventory 3.64 seconds. The YouTube acquisition stage replayed 168 API responses.

The copied snapshot that `save-pipeline-data.sh` would stage is **52,781,646 bytes (50.34 MiB)**: the original inputs total 38,953,588 bytes, and new compact state adds **13,828,058 bytes (13.19 MiB)**. This replaces dependence on roughly 1.2 GB of research source caches. The three frozen bootstrap files supply that state on first CI use, then only `pipeline-data` is updated. No snapshot was pushed and neither publication script was executed.

The existing two workflow jobs remain. The Congress job installs the pytest extra, tests, bootstraps absent state, runs the three new steps, saves the existing snapshot and commits all ten derived tables with the existing helper. No new weekly secret is required. README and findings paths now point to the production commands and app data directory.

## Replay commands

Run from the worktree using its environment. `STATE` and `OUT` below must be disposable paths inside the worktree when rehearsing; the real sibling data checkout stays read only.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python tests/compare_meeting_inventory.py \
  --output-dir apps/committee_youtube/data --report .cache/equivalence.json
.venv/bin/python tests/replay_meeting_inventory.py \
  --seed-cache ~/hearing-text --state-dir "$STATE" \
  --meetings "$COPY/congress_meetings.jsonl.gz" \
  --gpo-path apps/committee_youtube/data/gpo_hearings.csv --output-dir "$OUT"
.venv/bin/python tests/replay_weekly_pipeline.py "$REHEARSAL"
```

`$REHEARSAL` contains `pipeline-data/` and `outputs/` copies; the first includes the bootstrap state. The app README gives the three standalone production commands, including a full backfill with empty state and an optional read-only research import.

## Limits and work left outside this branch

All requested local implementation, output migration and checks are complete. GitHub Actions has not run this branch, and no branch or snapshot has been published. A full uncached live backfill was not attempted because it would exceed the requested live bounds. The replay's timings and request counts are not a whole-corpus live benchmark.

Only five of 21 committee sites were checked live; all 21 were parsed and compared from retained source pages. Future site layout changes remain a maintenance risk. JEC running-text witnesses and newer Indian Affairs lists populated in a browser remain unread, as in the research. Unobserved automatic YouTube captions remain unknown until a manual caption run supplies evidence. The Senate date rule is supported by the observed transition and 29 live checks, but is still an availability inference for new filenames. Confirmed archive negatives deliberately do not retry, so a recording posted more than seven days late requires an explicit state refresh. No unsupported recording or witness matching rule was broadened.
