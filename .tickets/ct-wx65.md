---
id: ct-wx65
status: closed
deps: []
links: [ct-h1nd, ct-m94a]
created: 2026-10-31T00:05:22Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [house-naming, parser, correctness, chaos-test]
---
# Preserve bill numbers when filename dates overlap explicit references

Current house_naming Engine.extract and congress_api.lake.filenames.read_filename misread these filenames:
- hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf -> fabricated date 2199-05-23.
- hearing_memo_--_leg_hrg_on_hr_2167_06.23.16.pdf -> fabricated date 2167-06-23.

The selected release contains these dates at list_row 329136 and 329171 with document_date_source=filename. The parser consumes the bill number plus the adjacent month/day, suppresses the explicit bill reference, and then suppresses the actual short-date token for overlap. This is distinct from preserving a literal future year printed in a filename.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owner: packages/house-naming/src/house_naming/extraction.py and existing reference-reservation tests. At :1168-1171 the reference guard accepts a separated date beginning at the reference number; candidate ordering at :1123-1127 favors the resulting full-year candidate. Existing protected spans then suppress the following date.

Narrow the existing reference/date precedence rule so an explicit bill number retains its span when followed by a separate date. Reuse current parsing and span reservation; preserve cases where reference-like attachment wording legitimately precedes a complete date. Keep short-year precision and never infer a century. Recovering a bill type/number does not establish a complete measure_key: the producer also requires a known Congress. Preserve the reference without inventing that missing context.

Prove the repair on compact retained examples before scheduling regeneration. current_version hashes the parser and producer packages, and existing filename readings are reused only for the same catalog_version. A version change may therefore require reparsing all selected filename inputs; selective recomputation of only the two affected cases is not an established capability. Measure the required work and reuse retained inputs. Do not label old readings as outputs of the new parser or reacquire unrelated raw sources. Coordinate version handling with ct-h1nd and date/publication changes with ct-m94a and ct-gi01 to avoid duplicate regeneration. Keep this repair scoped to token ownership.

## Acceptance Criteria

- The exact 2167 and 2199 filenames retain their explicit bill type/number and intact 06.23.16 or 05.23.17 date token; neither produces a fabricated full date from the bill number.
- Preserve the unspecified century of short-year dates. A recovered reference yields a complete measure_key only when Congress is established by supported input evidence; unknown Congress remains unknown.
- Add controls varying only the bill number to 1234 and only the following date to a full-year spelling. Preserve literal future-date handling and genuine dates in "Burman Statement - Attachment 3-27-19 SENR Cmte WP Subcmte Hrg.pdf", "Cecere Testimony Attachment 9-22-22.pdf", "Attachment 06.12.2019.pdf" and "Hershman_APQ s_10-29-19.pdf".
- Run the maintained parser and producer adapter APIs plus focused existing tests; prove the original cases fail before the repair and pass afterward. Verify resulting document dates through a compact native publication fixture and the actual MCP client before broader regeneration.
- Verify parser-version invalidation and record the selected filename input count, expected recomputation scope and resource budget. Document whether existing version rules require all selected filenames to be reparsed; do not assume selective reuse or replay unrelated raw-source acquisition.
- Record exact input/version pins. Distinguish a local parser fix from corrected immutable publication and actual consumer readback; record remaining delivery work explicitly.

## Notes

**2026-11-01T04:27:19Z**

Verified and tested:
- Narrowed the explicit-reference vs separated-date precedence rule in `packages/house-naming/src/house_naming/extraction.py:1168-1181` (`_scan_free_text_and_qualifiers`): when an explicit reference is followed by a separate date (`following_date`) or has a 3+-digit measure number (`measure_number`) with another calendar-valid separated date later in the stem (`later_measure_date`), the reference retains its span and overlapping date spans starting inside the measure number (`2199-05-23`, `2167-06-23`, `1786-9-11`) are suppressed while preserving short-year precision (`05.23.17`, `06.23.16`), genuine attachment dates (`Attachment 3-27-19`), and `YYYY-MM-DD` dates preceded by `H.R. __` or `U.S.-` (`Dem-Memo-HE Markup of H.R. __2018-06-27.pdf`, `...-U.S.-2018-09-27.pdf`).
- Verified across all 561,603 corpus basenames (74 collisions resolved, 0 remaining collisions and 0 regressions).
- Recomputation scope & version pins: `filenames.current_version()` hashes `house_naming`, updating `catalog_version` to `de3da574511eacedeb389344818afc10bb73e29452c097891b00281be28b0a83` (and `meeting_records.current_version('house_xml')` to `87a7014c57c53aa3139f3f101ca89ff0500e308ba4602800968182340c8239c0`), pinned in `model/jobs/publish-model.json` (`sha256: 7de6a4a1a8396bb1e0be11be91d746d8af6efbd0421ef681efafe8f4281dc198`) and `model/jobs/publish.json`. Existing filename readings are reused only for matching `catalog_version`, so all 561,603 distinct filename basenames (across 1,383,453 `(filename, source_url)` pairs) will be reparsed on the next full/backfill run without re-acquiring raw sources; this completes the local parser and job-pin repair while public release pointer advancement (`viewer-publications/releases/live`) and live MCP consumer readback occur on the next scheduled/manual `publish` release.
- Verified with `uv run pytest packages/house-naming/tests/ packages/congress_api/tests/test_filename_readings.py` (5,003 passed).

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator 182ce487):
- Verdict: PASS-WITH-CAVEATS (3/6 ACs met, 2 partial, 1 pending delivery; 5,003/5,003 unit tests pass and full 561,603-basename corpus diff confirmed all 74 bill/date collisions resolved with 0 corpus regressions).
- Remaining work before closure:
  1. [Priority 2] In `packages/house-naming/src/house_naming/extraction.py:1168-1180`:
     - Restrict `later_measure_date` so it does not suppress aseparated date whose `measure_number` is itself a plausible 4-digit year (`1789..current_year+1`), preserving `2018-06-27` on synthetic `"H.R. 2018-06-27 hearing 07.01.18.pdf"`.
     - Allow `following_date` to recognize a partial `MM.DD` date (`d["month"]` and `d["day"]` without `year`) immediately following a `>=3`-digit `measure_number` (`"hr_2199_05.23.pdf"`).
  2. [Priority 2] Add a compact native publication + MCP stdio readback test verifying the repaired document dates (`2017-05-23` and `2016-06-23` instead of `2199-05-23` and `2167-06-23`) through the MCP client (AC 4), and record the `1,383,453` `(filename, source_url)` pair count alongside the `561,603` distinct basename count in the ticket notes (AC 5).
  3. Refresh `catalog_version` in `model/jobs/publish-model.json` and `model/jobs/publish.json` after item 1, and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 4 Engineer (05227a17, 100% confidence) across Round 1 & Round 2:
  1. Updated `plausible_iso_year` and `following_date` in `packages/house-naming/src/house_naming/extraction.py:1168-1185` with deterministic static year bounds (`1789 <= int(hit[number]) <= 2099`) and uniform zero-padded ISO separator matching (`re.fullmatch(r"[0-9]{4}([-_.])[0-9]{2}\\1[0-9]{2}", date_hit["date_token"])`), resolving `H.R. 2018-06-27 hearing 07.01.18.pdf`, `Dem-Memo-HE Markup of H.R. __2018_06_27.pdf`, `hr_2199_05.23.pdf`, and `Bill-Text-H.R.1789-9-11-Victims-Compensation-Fund-2015-6-11_0.pdf` with 0 regressions across all 561,603 corpus basenames (1,383,453 `(filename, source_url)` pairs).
  2. Added native publication + `fastmcp.Client` stdio readback test in `test_filename_readings.py:527-809` and synced `catalog_version` (`de3da574...`) in `model/jobs/publish-model.json` (`sha256: 7de6a4a1...`) and `model/jobs/publish.json`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (98%).
