# Committee Explorer review — 28 September 2026

## Browser-first findings

Reviewed the built site against the complete retained publication before reading
the implementation. Covered Meetings, Committees, Recordings & documents,
Witnesses, Coverage, Gaps & issues, and source details.

1. **P1 — Chart navigation changes the population.** Business meeting →
   Recordings → Month → January 2025 shows 15 meetings, but clicking it opens 78
   because the type filter is cleared.
2. **P2 — Committee navigation inherits an unusable date filter.** Starting from
   meetings after 1 October and switching to Committees returns zero committees.
3. **P2 — Browser Back loses chart settings.** Captions → Inferred (26) → Back
   returns to Transcripts instead of Captions.
4. **P2 — Original source link requires credentials.** The Congress.gov API URL
   for event 100240 returns HTTP 403, `API_KEY_MISSING`.
5. **P2 — Mobile coverage overflows.** At 390 px, opening Detailed evidence
   counts expands the document to 457 px.
6. **P2 — Conflict details omit the disagreement.** “Sources disagree about
   label” gives the field name and source IDs but neither competing value.
7. **P3 — Tables expose irrelevant fields.** Committees show Date unrecorded,
   a blank type and duplicate committee name; witnesses show a blank type;
   issues have an Issues column of their own.
8. **P3 — Related meetings are alphabetical.** A committee's recent meetings
   are mixed with older meetings. Material details also repeat a single meeting
   link in two places.
9. **P3 — Empty-page copy is misleading.** An out-of-range page says no records
   match even while the result count is 2,767. The recovery button works.

Working before fixes: combined search/Congress/chamber filters; Business meeting
type; search-result/detail Back and Forward; future recording suppression;
single Senate player; document formats and witness statements; independent
document/witness pagination; issue-status filter; disclosures; ordinary paging;
empty search recovery. Date-input automation required a native keyboard change
to trigger React; that was a test-control limitation, not an application defect.

## Design decisions

**Visual thesis:** retain the compact, restrained working surface and existing
charts; repair overflow and irrelevant columns rather than redesign the page.

**Content thesis:** every displayed fact or link should help identify a meeting,
find its material, understand a witness, or inspect a specific known issue.

**Interaction thesis:** filters and chart choices survive navigation and shared
URLs; a chart's destination must contain the population represented by its count.

## Implementation review and validation

The confirmed findings above are fixed. Source evidence now opens raw source data
inline on demand, with a public-source link, without navigating to another record.
Meeting/material tables pair date with status and Congress with type; enum labels
use sentence case. Witnesses and committees retain relevant columns. Follow-up inspection found two more
functional gaps: witness organization/position were absent from search columns,
and issues attached to file versions or checks did not lead to a visible record.
Those fields now participate in witness search; issues follow their explicit
owner to the document or meeting, with open counts recalculated there.

A final blind check exposed 7,502 false conflicts caused solely by two collector
placeholder labels. Collectors now leave an unknown edition label empty. The
retained-publication converter marks those exact legacy conflicts dismissed,
renames them as collector differences, and preserves the compared values and an
explicit correction explanation. Real source-label disagreements remain open.

### Function and data flow trace

| Entry | Processing | Result / invariant |
| --- | --- | --- |
| `export.py:export` | Saved inputs → existing validated records → `parquet.write_catalog` | No acquisition; stable IDs and history remain upstream |
| `parquet.py:write_tables` | Fold explicit file/version/meeting/witness references; keep source payloads | Six typed tables; actual file URLs and explicit ownership preserved |
| `parquet.py:migrate` | Verify retained JSON publication, read its records, write the same browser tables | First rollout reuses retained data without record reassembly |
| `browser.py:package` | Verify complete hashes; stage current release and enforce size budget | Parquet bytes remain unchanged |
| `data-source.js:openPublicationReader` | Verify pointer and manifest; select reader by media type | Components receive an injected `ExplorerReader` |
| `parquet-source.js:read` | Fetch column/row-group ranges, validate HTTP 206, lengths and row counts | No whole-catalog or source-payload download for browsing |
| `search` / `getCoverage` | Same date presentation and filter predicate | Chart counts and result populations agree |
| `getRelated` | Explicit meeting/witness/issue IDs; then physical-row reads | Shared files stay reachable across Congresses; independent pagination |
| `navigation.js:drillNavigation` | Preserve query scope, type and chart settings | January business-meeting count 15 opens exactly 15 records |
| `viewNavigation` | Carry only compatible filters | Committees cannot inherit an unusable date filter |
| `RecordDetail` | Public source URLs, direct file links, explicit issue values | No extra edition/representation navigation; unsafe URL schemes rejected |

Reviewed the changed publisher, adapters, readers, presentation, routing,
components, styles, dependency declarations and workflow files, together with
their model, query, state and test callers. The storage reader remains separate
from React; no database, server query engine or new matching system was added.

### Verification

- Offline Python suite: **228 passed, 31 subtests passed**.
- Frontend data/navigation suite: **29 passed**, including actual Snappy Parquet
  produced by Python and decoded by Hyparquet, cross-Congress files, organization
  search, chronological committee meetings, issue ownership, cancellation and
  rejected range responses.
- Generated model types match; Astro checks **36 files with zero errors,
  warnings or hints**; static build produces **28 pages**.
- Full retained-data comparison preserves IDs for 18,139 meetings, 1,205
  committees, 385,017 materials, 67,145 witness appearances and 239,116 issues.
  Material/meeting/witness associations are unchanged. The prior connection
  audit counts 300,380 material/meeting connections and 416,162 file-location entries (413,846 distinct URLs).
- Browser retests: all six workspaces, source/detail navigation, combined search,
  Congress/chamber/type/date/status filters, all five coverage measures,
  grouping, chart drill-downs, Back/Forward, reloadable URLs, reset, disclosures,
  pagination, invalid ranges, stale pages, and empty results.
- Full-archive meeting search returns **18,139**; 119th Congress organization
  search for Brookings returns **19 witness appearances**. The repaired committee
  transition returns **212 committees**. January 2025 business drill-down returns
  **15**, not 78. At 390 px, expanded coverage keeps document width at **390 px**.
- Both page-download JSON files were inspected on disk: one has the two filtered
  historical meetings; the other has the 25 visible default-page rows and the
  correct 2,767 total. The browser automation download event timed out even
  though the files downloaded correctly.
- Public GitHub Pages serving returned HTTP 206 and the exact requested four
  bytes for a retained data file, confirming the hosting prerequisite.

### Limits and verdict

**Merge after CI passes.** The reviewed issues have concrete fixes and regression
coverage. Deployment and public Parquet readback are checked after merge.

This review exercises each control family with representative records; it is not
an assertion that every external PDF or video URL is reachable. Congress.gov's
public event URL is used instead of its API-key endpoint; automated HTTP access
to the public site was blocked, so universal source reachability is not claimed.

The browser validates the manifest and range responses, not a whole-file hash
from partial bytes; complete hashes are checked before publication. The existing
normalized-model rebuild is still upstream. This merge does not implement
incremental updates of persistent intermediate tables.

Some retained issues concern committee identities or people that have no unique
meeting-specific browsing row. Their citations and compared values remain
available; the exporter does not invent a unique committee term or appearance.
The old JSON reader remains available for compatibility, while the deployed
simplified UI uses the converted Parquet publication.
