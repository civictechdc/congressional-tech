---
id: ct-h1nd
status: closed
deps: []
links: [ct-30fp, ct-kw9b, ct-vpo2, ct-pocg, ct-yymr, ct-wx65, ct-jinw, ct-77zb, cef-nkzp, ct-d0o0, ct-sh4j, cefr-7sar, ct-kac4]
created: 2026-10-30T18:34:40Z
type: task
priority: 1
assignee: mikewolfd
tags: [lake, dry, parsers, house-naming, phase-2, etl-workflow]
---
# Source-scoped lake parser versioning and House XML / meeting_records bill extraction

`meeting_records.py` and `appearance_records.py` currently compute a single monolithic `current_version()` digest across all sources (`congress_gov` + `house_xml` for meetings; `mods` + `congress_gov` + `house_xml` + `senate_page` for appearances). Consequently, any edit to a single source parser (such as `house_xml` bill extraction or `senate_page` HTML rules) invalidates all 110,930 `meeting_records` rows or all 62,782 `appearance_records` rows across unrelated sources. Additionally, House `<committee-meeting>` XML parsing missed agenda bill keys embedded in `<file doc-url="...">` filenames and `<meeting-title>`, lacked `spicy-docs` `BILL_NUMBER_PATTERN` false-positive guards, and discarded `congress_gov` `subject_keys` when `house_xml` had any `subject_keys`.

Note: Shared incremental lake producer primitives (`lake/_record_producer.py`), `archive_model_profile.py` hashing, and single-pass `ModsScope.access_ids` (`models/gpo.py`, `parsers/gpo.py`) have already landed on `main` (`3f6548e6`).

## Design

Owners: `packages/congress_api/src/congress_api/lake/_record_producer.py`, `meeting_records.py`, `appearance_records.py`, `model/sql/meeting-records-resolved.sql`, `model/sql/entity-rosters.sql`, `packages/viewer_publication/src/viewer_publication/archive_model.py`, and `packages/viewer_publication/src/viewer_publication/archive_model_profile.py`.

1. **Source-scoped `current_version(source)` for selective recomputation (`etl-workflow` §4):**
   - Parameterize `current_version(source: str | None = None)` (and add `current_versions(*, root=ROOT) -> dict[str, str]`) in `meeting_records.py` and `appearance_records.py`, following the pattern in `lake/readings.py`:
     - `meeting_records`:
       - `'congress_gov'`: hashes `_record_producer.py`, `models/congress.py`, `parsers/congress.py`, `parsers/media.py`, `parsers/senate_player.py`, `meeting-records.schema.json`.
       - `'house_xml'`: hashes `_record_producer.py`, `parsers/house_xml.py`, `parsers/house_documents.py`, `meeting-records.schema.json`, `values={"prefixes": list(HOUSE_MEETING_PREFIXES)}`, and `packages={"house-naming": "house-naming"}`.
     - `appearance_records`:
       - `'mods'`: hashes `_record_producer.py`, `models/gpo.py`, `parsers/gpo.py`, `parsers/xml.py`, `parsers/witness_names.py`, `appearance-records.schema.json`.
       - `'congress_gov'`: hashes `_record_producer.py`, `models/congress.py`, `parsers/congress.py`, `appearance-records.schema.json`.
       - `'house_xml'`: hashes `_record_producer.py`, `parsers/house_xml.py`, `parsers/house_documents.py`, `parsers/text.py`, `appearance-records.schema.json`, `values={"prefixes": list(HOUSE_MEETING_PREFIXES)}`.
       - `'senate_page'`: hashes `_record_producer.py`, `parsers/senate_page.py`, `parsers/text.py`, `appearance-records.schema.json`.
   - Update `stage_record_table` and `filter_unprocessed_inputs` in `lake/_record_producer.py` and `completeness_checks` in `viewer_publication/archive_model_profile.py` to accept `version: str | Mapping[str, str]` and anti-join each candidate row `c` against `existing e` and `unreadable u` using the `parser_version` for `c.source`.
2. **Wire `house_naming.Engine().extract()` into `meeting_records.py` (`_extract_bill_keys_from_doc_url`) across all active `<meeting-document>` elements (including `type="SD"`):**
   - Resolve Congress from `house-naming` metadata (`congress`, `print_congress`, `generic_identifier`), URL path/date tokens (`/gpoxmlc{c}/`, `/billsthisweek/YYYYMMDD/`, `/meetings/.../YYYYMMDD/`), or the enclosing meeting's `congress` (refusing only when a file's stated Congress disagrees with the meeting's Congress).
   - Map legacy THOMAS `gpoxmlc{congress}/{type}{num}_{stage}.xml` prefixes where `hr` denotes `hres` (e.g., `hr99_rh.xml` -> `113-hres-99`) and `h` denotes `hr`.
3. **Unconditional `<legis-num>`, `<description>`, and `<meeting-title>` bill extraction with prose Congress/Act-year guard:**
   - Scan `<legis-num>` and `<description>` across all active `<meeting-document>` elements (removing the `if doc_type == "SD": continue` skip so House Rules Committee resolutions like `H. Res. 440` and `H. Res. 99` are captured) AND scan the meeting's own title (`<meeting-title>` / `title`) by default (recovers 1,006 meetings out of 18,687 in live `meetings.parquet`).
   - Add a prose Congress/Act-year guard (`_extract_prose_bill_keys(text, congress)`) so prose mentions that explicitly qualify a bill with a different Congress (e.g., *"H.R. 2 (114th Congress)"*) or prior-year Act citation are not stamped with the enclosing meeting's Congress.
4. **Harden `_HOUSE_BILL_RE`:**
   - Align with `spicy-docs` `BILL_NUMBER_PATTERN` guards AND require the trailing period on single-letter Senate bills (`S\.`) plus apostrophe lookbehind (`(?<![A-Za-z.\x27\u2018\u2019])`) so possessives like `"GAO's 2013"` or `"Navy’s 30"` never match as Senate bills (eliminates all 46 possessive false positives measured across 18,687 meeting titles while retaining all 3,693 real `S.` matches).
5. **Union `house_xml` and `congress_gov` `subject_keys` in SQL:**
   - In `model/sql/meeting-records-resolved.sql`, replace the `CASE WHEN house IS NOT NULL ... ELSE congress_gov` branch in `subject_rows` with a `UNION ALL` of both `house_xml` and `congress_gov` `subject_keys` so `subjects_agg` (`ORDER BY subject_key`) produces their deduplicated sorted union.
6. **Include `congress` in `rosters.parquet` unique sort key (supporting `L2-R4`):**
   - Update `packages/viewer_publication/src/viewer_publication/archive_model.py:653` from `['system_code', 'rank', 'bioguide_id']` to `['congress', 'system_code', 'rank', 'bioguide_id']` (matching `release-schema.json`) and add `AND congress IS NOT NULL` to `model/sql/entity-rosters.sql` so multi-Congress committee rosters from `spicy-regs` do not fail the unique-key sort invariant.

## Acceptance Criteria

- Editing `house_xml` logic in `meeting_records.py` changes `current_version("house_xml")` while leaving `current_version("congress_gov")` unchanged, and `stage_record_table` / `completeness_checks` only invalidate `house_xml` rows.
- Editing `senate_page` logic in `appearance_records.py` changes `current_version("senate_page")` while leaving `current_version("mods")`, `current_version("congress_gov")`, and `current_version("house_xml")` unchanged.
- House `<committee-meeting>` XML extracts bill keys from `<file doc-url="...">` (including `BILLS-118HR3522ih-FIRESHEDSAct.pdf`, `BILLS%20-115HR2810-RCP115-23.pdf`, `113-HR933-ExState.pdf`, Rules Committee resolutions under `type="SD"` like `BILLS-115hres440rh.pdf`, and legacy THOMAS `gpoxmlc113/hr99_rh.xml` -> `113-hres-99`), `<legis-num>`, `<description>`, and `<meeting-title>`, while skipping prose mentions explicitly attributed to a different Congress.
- `_HOUSE_BILL_RE` accepts dotted/undotted House bills (`H.R. 1234`, `HR 3210`) and dotted Senate bills (`S. 744`) while rejecting `U.S.`, `R.S. 2477`, `W.S. 11-6-302`, `S 2(N)`, year headings, and possessives (`"GAO's 2013"`, `"Navy’s 30"`).
- `model/sql/meeting-records-resolved.sql` takes the deduplicated sorted union of `house_xml` and `congress_gov` `subject_keys`.
- `rosters.parquet` sorts and checks uniqueness on `['congress', 'system_code', 'rank', 'bioguide_id']`.
- All unit and model entity tests pass on `main`.

## Notes

**2026-10-30T19:25:30Z**

Do NOT close this ticket based on commit `3f6548e6` alone: `3f6548e6` landed only the initial `lake/_record_producer.py` extraction, `ModsScope.access_ids`, and v1 `_extract_bill_keys_from_doc_url`. It is still missing:
1. Source-scoped `current_version(source)` / `current_versions()` in `meeting_records.py`, `appearance_records.py`, `_record_producer.py`, and `archive_model_profile.py` (`etl-workflow` selective recomputation).
2. Unconditional scanning of `<meeting-document type="SD">` (`meeting_records.py:615` still skips `SD`), percent-decoded URLs (`unquote`), Congress fallback from `print_congress` / `generic_identifier` / URL dates, and legacy THOMAS `gpoxmlc` URL mapping (`hr` -> `hres`, `h` -> `hr`).
3. Scanning `<meeting-title>` / `title` (1,006 meetings) with a prose-Congress guard.
4. Hardening `_HOUSE_BILL_RE` with `S\.` + `(?<![A-Za-z.\x27\u2018\u2019])` (eliminating 46 `'s 2013` possessive false positives).
5. `UNION ALL` of `house_xml` and `congress_gov` `subject_keys` in `model/sql/meeting-records-resolved.sql`.
6. Including `congress` in `rosters.parquet`'s unique sort key (`['congress', 'system_code', 'rank', 'bioguide_id']`) in `archive_model.py:653` and `model/sql/entity-rosters.sql`.


**2026-10-30T21:20:20Z**

Coordinate source-scoped version generation with reopened ct-yymr (preserve selections in daily handoff) and ct-kw9b (filter selected source/version and expected-candidate admission). ct-30fp changes appearance record identity to include source and keeps parsing context-free; its explicit collection states distinguish empty, absent and failed/unrecognized extraction. Preserve the documented subject_keys union policy separately from replacement-list semantics.

**2026-11-01T04:25:21Z**

Verified and tested:
- Witness appearance extraction decoupled from meeting-record production into congress_api.lake.appearance_records (HOUSE_MEETING_PREFIXES, build_appearance_record_row, current_version, current_versions, stage).
- Meeting-record production extracted into congress_api.lake.meeting_records (build_meeting_record_row, current_version, current_versions, stage) with Public Law parenthesized bill citation guard (_PRE_CONGRESS_RE).
- Verified with uv run pytest packages/congress_api/tests/test_phase2_meeting_appearance_lake.py packages/congress_api/tests/test_daily_producers.py.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 239cc54c):
- Verdict: PASS-WITH-CAVEATS (6/7 ACs met, 1 partial; 151/151 tests pass).
- Remaining work before closure:
  1. [Priority 2] In `packages/congress_api/src/congress_api/lake/meeting_records.py:515-521`, update `_HOUSE_BILL_RE` so compact dotted Senate bills (`S.140`, `S.744` without whitespace after `S.`) match alongside `S. 744` while still rejecting `U.S.`, `R.S. 2477`, `W.S. 11-6-302`, `S 2(N)`, and possessives (`"GAO's 2013"`).
  2. [Priority 2] In `packages/congress_api/src/congress_api/lake/meeting_records.py:533-536,581-585`, narrow `_ACT_YEAR_RE` so bills whose titles amend an earlier Act (e.g. `"H.R. 2215, To amend the Help America Vote Act of 2002"`) are not suppressed when the `"Act of YYYY"` phrase follows `"to amend"` / `"amending"` / `"under"` rather than naming the bill itself.
  3. [Priority 2] Include `SITTING_STRUCT`, `COMMITTEE_STRUCT`, and `VIDEO_STRUCT` in `meeting_records._SOURCE_SYMBOLS` (`meeting_records.py:131-164`) so Arrow struct changes automatically invalidate per-source `current_version`.
  4. Refresh `model/jobs/publish-model.json` and `model/jobs/publish.json` after the above edits and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 2 Engineer (b009d889, 100% confidence) across Round 1 & Round 2:
  1. Added `SITTING_STRUCT`, `COMMITTEE_STRUCT`, and `VIDEO_STRUCT` to `_SOURCE_SYMBOLS` in `meeting_records.py:131-170`.
  2. Updated `_HOUSE_BILL_RE` (`meeting_records.py:521-527`) to match compact dotted Senate bills (`S.140`, `S.744`) while preserving `U.S. 2023` / `R.S. 2477` exclusions.
  3. Hardened `_ACT_YEAR_RE` (`meeting_records.py:539-546,582`) with leading punctuation `r"^\s*[,:;.\-–—()\x27\"\u2018\u2019\u201c\u201d\s]*"` and per-token negative lookahead so amendatory `"To amend the ... Act of YYYY"` titles retain their bill keys while prior-Congress short-title appositives are suppressed.
  4. Synced `meeting_records.current_versions()` (`{"congress_gov": "7c4881d1...", "house_xml": "87a7014c..."}`) and `appearance_records.current_versions()` in `model/jobs/publish-model.json` and `model/jobs/publish.json`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (98%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (99%).
