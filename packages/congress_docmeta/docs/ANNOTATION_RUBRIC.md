# Hydrogen-High Gold Expansion Rubric (`DocMetaV4Causal` — V6.2 / V6.3 / V6.4)

You own **one document shard** (`shard_XX`) split into **compact zero-truncation reader packets**:
- **Shards `32..37` (`100` docs/shard, `doc_idx` `0..99`, `5 × 20` docs/batch `< 38 KB` — V6.5 rare-kind and unseen-layout gap-fill):**
  - `.cache/archive-release/docmeta-v65-raretypes-20261118/packets_2000/shard_XX_b1.md` (`docs 0..19`) .. `shard_XX_b5.md` (`docs 80..99`)
  - `SEED` includes `"gap_target_hint"` explaining why the candidate was sampled (a cluster sibling, a keyword match, or an unseen layout cluster). It is a hint, often wrong: **always judge strictly from the actual document text** (and run `inspect` whenever `chars > 1400` or tail/middle details matter).

Each packet is `< 38 KB`, so **one `read_file` call reads an entire batch cleanly with zero truncation**.

## Absolute Ground-Truth Rules
1. **NO BULK REGEX / AUTO-LABELING SCRIPTS:** You MUST personally read and judge every document in your shard as `gemini-4-hydrogen-high`. Never write a Python script to synthesize labels heuristically.
2. **NO GIT REPO EDITS:** Do NOT modify any git repository files and NEVER embed hidden home/agent scratch directory paths anywhere. Write temporary batch JSON files to `.cache/archive-release/docmeta-v65-raretypes-20261118/_scratch_label_XX/v65_shard_XX_bK.json`.
3. **INSPECT FULL 9,000-CHAR WINDOW WHENEVER NEEDED:** Packet lines show up to ~1,400 chars (`head + ...[TAIL]... + tail`). Whenever a document's `primary_kind`, actors/signers, dates, committees/subcommittees, citations, or disclosure details depend on middle/tail text (`chars > 1400` or ambiguous), inspect the full 9,000-char `head_tail_window` in one call:
   ```bash
   .venv/bin/python \
     .cache/archive-release/docmeta-v65-raretypes-20261118/scripts/apply_batch_labels.py \
     inspect --shard XX --docs 3 7 14
   ```
4. **APPLY EACH BATCH & FIX ANY VALIDATION ERRORS IMMEDIATELY:**
   Write a JSON array of batch objects (`[{"doc_idx": 0, ...}, ...]`) to `.cache/archive-release/docmeta-v65-raretypes-20261118/_scratch_label_XX/v65_shard_XX_bK.json` and run:
   ```bash
   .venv/bin/python \
     .cache/archive-release/docmeta-v65-raretypes-20261118/scripts/apply_batch_labels.py \
     apply --shard XX --reviewer v65-carbon-XX --in .cache/archive-release/docmeta-v65-raretypes-20261118/_scratch_label_XX/v65_shard_XX_bK.json
   ```
   - `apply_batch_labels.py` automatically inherits deterministic `refs`, `short_titles`, and `fiscal_years` from `det_seed` when you omit those keys (or set `"@seed"`), canonicalizes key order at all 3 levels, builds the full `9,000`-char `build_prompt_v4` user message, and runs `gold_gate_v6_2` (`validate_docmeta_v4` + `strict_validate_v4` + zero-leakage check). If you spot extra/corrected `refs`, `short_titles`, or `fiscal_years` in the text (or `[]` when `det_seed` is noisy), pass the explicit array!
5. **FINAL SHARD VERIFICATION (`remaining_count == 0`):**
   Once all 5 batches apply cleanly (`remaining_count == 0`), run:
   ```bash
   .venv/bin/python -m congress_docmeta.gold_v65.gold_gate_v6_2 \
     check .cache/archive-release/docmeta-v65-raretypes-20261118/outputs_2000/gold_shard_XX.jsonl
   ```
   (`gold_gate_v6_2.py` automatically checks Shards `32..37` against all 3,077 rows of the V6.4 gold.)
   There is no swarm board for this run: do not post anywhere and do not call `swarm_wait`. Your final answer is the report.

## V6.5 House Conventions (owner decisions 2026-11-18; they override any softer wording below)
**Governing rule: the source text is the source of truth.** A label records what the document text states. The filename, the upload slot, where the file came from, the `known` hint, rosters and your own memory are signal only: they may help you find the answer in the text, and they never supply a value the text does not state. When the text does not state something, leave it out.

**Interpret, do not invent** (owner, 2026-11-18: "just because it's not perfect in the text doesn't mean the model shouldn't interpret things. That's the point, but it shouldn't be hallucinating"). Reading a document means drawing the conclusions its words support: what kind of document it is, who is the witness and who the chair, which date is the hearing's, what a damaged or abbreviated passage says, a title pieced together from the heading. Those are correct labels even when the text never says them outright. The error is a value with no basis in the text at all, one that could only have come from the filename, the hint, a roster or memory. The test for any value: can you point to the words in this document that led to it? If yes, it stays. If no, it goes.

**"Stated" means evident from the document's own words to a careful reader** (owner, 2026-11-18). It includes what the text makes plain without saying it outright: "Location: 106 Dirksen Senate Office Building", a roll sheet with a "Representative" column, "Rep. Allen", "Senator Booker presiding", a standalone "SENATE" or "HOUSE OF REPRESENTATIVES" header, or a committee that exists in only one chamber all state the chamber. It does not include anything that needs a calculation or an outside lookup: a Congress worked out from a printed date is not stated, and neither is anything taken from the filename, the `known` hint or a roster. Read through scanning damage the way a person would ("117h Congress", "ONE HUNDRED FIFTHTEENTH CONGRESS", a signature scanned as "Bill Cassicdog" are stated). Do not be fooled by look-alikes: "the White House", a state "House" or "Senate", a site navigation menu, or a Congress mentioned in passing (a bill "introduced in the 112th Congress") say nothing about this document.

Each was settled against the whole gold, not a sample. Where a document is two things, the first is `primary_kind` and the second goes in `secondary_kinds`.

**People**
- **Write a name as the text shows it.** If the text gives only a surname ("Chairman Roe", "Mr. CRAMER", "Mrs. KIGGANS of Virginia"), the name is the surname. Never supply a first or middle name from memory; a roster rule adds them later. A person who is not named in the text is not listed.
- **Roll-call and attendance grids are never a source of people.** On `committee_vote` and `attendance_quorum_sheet`, do not list the chair, the ranking member or anyone else read off the grid. List an amendment's offeror or a bill's sponsor when the text names them outside the grid.
- **Letters: the role is the function, not the office.** Lead signer `sender`, co-signers `signatory`, addressees and cc `recipient`. A chair who signs a letter is `sender`, not `chair`.
- List a person only in a role the rubric defines; not people mentioned in passing.

**Kinds**
- **JCT "Description of H.R. ..." pamphlets and one-page substitute descriptions (JCX-NN-YY):** `section_by_section`; add `revenue_or_cost_estimate` to `secondary_kinds` when it carries a revenue table or score. `chamber` is the chamber of the committee the text says is marking up (House for Ways and Means, Senate for Finance); `committees` lists that committee and the Joint Committee on Taxation; `issuer_org` is the Joint Committee on Taxation. When the text names no marking-up committee, list none.
- **Statements for the record:** decide from the text. Testimony presented to the committee ("Testimony of ...", "Statement of ... before the Committee", an address to the chair as a witness) is `witness_statement`. A statement the text says was submitted for the record by someone who did not appear is `public_comment_or_submission`. The filename's slot does not decide it.
- **Rules Committee Prints of bill text** ("TEXT OF H.R. ... [Showing the text of ...]"): `bill_or_draft`, whatever the file format. `comparative_print` is only for prints that show changes against a base document.
- **Treaty paperwork:** presidential transmittals, resolutions of advice and consent, and Senate Executive Reports on a treaty are all `treaty_document` (an Executive Report also gets `committee_report` in `secondary_kinds`).
- **House Rules "special rule" paperwork** (the text shows an H. RES. with a House Report number, providing for consideration of a bill): `committee_report`, with `committee_resolution` in `secondary_kinds`.
- **One-page meeting or markup agenda sheet** (date, time, bullet agenda): `markup_notice`.
- **"Announces Committee Action on H.R. ..." releases** (what a markup decided): `meeting_results`, with `press_release_or_fact_sheet` in `secondary_kinds`.
- **Committee web pages carrying a member's hearing remarks:** as the page presents itself. A page the committee marks "Press Release" or headlines with a quote is `press_release_or_fact_sheet`, with `member_opening_statement` in `secondary_kinds`. A page titled "Opening Remarks" or "Opening Statement" is `member_opening_statement`, with `press_release_or_fact_sheet` in `secondary_kinds` when it sits in a news section.
- **Letters asking someone to testify,** including "Dear Colleague" Member Day letters: `witness_invitation`.
- **Legal records entered as exhibits** (subpoena, court filing, deposition record, regulatory application): `legal_or_investigative_filing`, with `investigative_exhibit` in `secondary_kinds`. Emails, charts and internal memos entered as exhibits are `investigative_exhibit`.
- **GSA and VA lease or prospectus resolutions:** `gsa_prospectus_or_property`, with `committee_resolution` in `secondary_kinds`.
- **Scraped single-event committee pages,** including ones updated with vote results: `event_web_page`.
- **Biographies and CVs:** `witness_biography` is the kind for any biography or CV of a person, whether or not the text mentions a hearing. The kind describes the document, not the occasion.
- **Hearing transcripts list their witnesses:** every witness the transcript's own witness list or contents page names is a person in the label (name as the text shows it, title and organisation as given, role `witness`).
- **Committee amendments:** "AMENDMENT TO H.R. ... OFFERED BY MR. X OF STATE" is the House committee form and makes the House evident; the Senate form ("IN THE SENATE OF THE UNITED STATES", "AMENDMENT NO.", "Calendar No.") makes the Senate evident.
- **Damaged or garbled text is still read:** shifted-letter or badly scanned text is interpreted like any other ("RepXblican MeeWing" is "Republican Meeting"); the label records what the document actually says. When the text layer is too damaged to be sure, check the source PDF before labeling, and never fill the gap from the filename or the hint.
- **Single chart, graph, map, photo or infographic sheet** whose only text is a caption or source line: `status: "usable", primary_kind: "error_or_non_document"`. `slides_or_visual` is for a multi-slide deck.
- **Pages with no document content** (download-redirect "please wait" pages, a sheet holding only a video link, empty bodies): `status: "stub_or_blank"`.

**Fields**
- **`correspondence_flow` only on the letter kinds** (`oversight_letter`, `external_submission_letter`, `nomination_or_support_letter`, `witness_invitation`, `qfr_request`, `qfr_response`, `public_comment_or_submission`). Never on statements, memos, notices or exhibits.
- **Dates:** a date goes in exactly one place. When a document tied to a hearing, markup or meeting prints a single date (the date under the hearing title of a witness statement, "Date: 12/7/22" on a vote sheet, the date on a transcript cover or notice), that is the `event_date`, and `doc_date` is left out. `doc_date` is only for a date the text marks as the document's own: a letter's date line, a press release dateline, "Adopted:", "Dated:", "Submitted:", or a second, distinct date. A stated date is never dropped from both fields.
- **`refs`:** only references whose identifying numbers appear in the text shown. Do not inherit `det_seed` refs that the window does not contain.
- **Subcommittee names:** the roster spelling ("and", not "&"; no leading "the").
- When you are unsure between two kinds, pick one, and add the doc to an `unsure` list in your final answer with both kinds and one phrase of why.
---

## Shards `26..29` Special Guidance: `V4_GOLD` Verification & `BodyTextSSOT` Upgrade
Each document in Shards `26..29` is a legacy `train_v4_all360.jsonl` gold example now re-hydrated against the **9,000-character `BodyTextSSOT` `head_tail_window`** (`p1..p2` + last-page tail) and includes `V4_GOLD: {...}` in both the packet and `det_seed["v4_gold"]`:
1. **Do NOT blindly copy `V4_GOLD`:** Inspect the newly hydrated `BodyTextSSOT` text (and run `inspect --shard XX --docs ...` whenever `chars > 1400` or `V4_GOLD` may miss tail content).
2. **Keep accurate `V4_GOLD` fields, and actively upgrade:**
   - **Newly visible tail content:** letter `signatory` / `sender` personas, `signatory_count`, closing `doc_date` / `due_date`, GPO colophon `sudoc:` / `hrg:` / `rept:` refs, and multi-page rosters or disclosures that were truncated in V4's old p1-2 slice;
   - **CMS-cleaned HTML / WARC bodies:** strip any leftover nav pollution from `verbatim_title` / `composed_title`, verify `congress` & `doc_date` from actual prose rather than scraped chrome, and canonicalize committee names (e.g., `"Committee on the Judiciary"` -> `"Senate Committee on the Judiciary"` or `"House Committee on the Judiciary"` when chamber is known);
   - **Strict V6.3 caps & hygiene:** ensure `gist` is `4..22` words (`<= 22` words hard cap!), `composed_title` is `8..109` chars, no honorifics (`Rep.`, `Sen.`, `Hon.`, `Dr.`) in `personas[].name`, and pass explicit `refs` / `short_titles` / `fiscal_years` arrays (merging accurate `V4_GOLD` + `SEED` + newly visible citations, or `[]` if none apply).

---

## Exact `DocMetaV4Causal` Schema & Domain Rules

### Critical Domain Distinctions
- **TEXT OVER FILENAME SLUG / SEED:** Judge `primary_kind`, `congress`, `committees`, `subcommittees`, and `doc_date` from the **document text**, NOT filename slugs or noisy upstream metadata (e.g., `Wstate-` containing Q&A post-hearing responses is `qfr_response`; `QFR001`/`TTF-` cover letters are `qfr_request`/`witness_invitation`/`external_submission_letter`; upstream `SEED.cong` typos like `12`, `14`, `120`, `122` must be corrected to the true Congress `1..119` from the document date/masthead, or omitted if genuinely non-congressional/undated; early historical docs like `79th Congress` (`1945–1946`) or `104th Congress` (`1995–1996`) ARE valid when confirmed by text!).
- **CHARTER/MEMO vs NOTICE vs WEB vs TRANSCRIPT:**
  - Committee staff background/hearing memos, hearing charters, markup memos -> `hearing_memo_or_charter`
  - Formal event time/place announcements -> `hearing_notice` or `markup_notice`
  - Scraped HTML single-event pages -> `event_web_page` (or `status: "index_or_listing"` if pure multi-event nav/listing page)
  - Verbatim Q&A / stenographic / GPO hearing books -> `hearing_transcript`
- **MEMBER vs WITNESS:**
  - Chair/member opening remarks at their committee -> `member_opening_statement` (`role: "chair"` / `"ranking_member"` / `"author_or_speaker"`, `entity_type: "member"`)
  - Floor remarks / Congressional Record extensions -> `member_or_floor_statement`
  - A Member of Congress testifying as a witness before a committee -> `witness_statement` (`role: "witness"`, `entity_type: "member"`)
- **AMENDMENTS vs VOTES vs RESULTS vs REPORTS:**
  - ALL amendments (floor, Senate, ANS, committee, report amendments) -> `committee_amendment`
  - Roll-call tally sheets -> `committee_vote` (summarize tally in `action_summary`; NEVER list roll-call voter grids in `personas`)
  - Post-markup summary of bills/amendments ordered reported -> `meeting_results`
  - Formal numbered/committee report -> `committee_report`
- **COMMITTEES & SUBCOMMITTEES (Canonical English Strings, NEVER `hsxx00` Codes!):**
  - Convert seed codes like `hsif14` / `ssju00` / `jocp00` / `spia00` using document text + congressional knowledge into full canonical English names:
    - `committees`: e.g. `["House Committee on Energy and Commerce"]`, `["Senate Committee on the Judiciary"]`, `["Senate Select Committee on Intelligence"]`, `["Joint Committee on Printing"]`, `["House Committee on Ethics"]` / `["House Committee on Standards of Official Conduct"]` (era-appropriate or canonical full name)
    - `subcommittees`: e.g. `["Subcommittee on Health"]`, `["Subcommittee on Courts, Intellectual Property, and the Internet"]`
  - Do NOT attribute a host committee onto external reports (`agency_or_gao_crs_report`, `external_report_or_whitepaper`, `news_clip_or_article`) unless the document itself addresses or names that committee!

### Non-Usable `status` Triage & `error_or_non_document` Rules
Carefully distinguish genuine non-usable artifacts from usable exhibits:
- **Hard-Error / Unusable Triage Statuses (`error_reason` REQUIRED; omit ALL other fields!):**
  When `status` is one of these 3 values, emit **ONLY** `{"status": ..., "text_quality": ..., "error_reason": "..."}`:
  1. **`error_or_block`**: HTTP 403/404/500 error responses, WAF/Cloudflare/security challenge pages, `"object-storage-no-such-key"` / `"house-meeting-not-found"` / `"Exception: forbidden"` / `"Page Not Found"` HTML responses (even when saved under a `.pdf` filename!). Set `text_quality: "native"` and a concise factual `error_reason` (e.g. `"HTTP 403 forbidden error response page"`, `"House committee 404 file-not-found HTML response"`).
  2. **`stub_or_blank`**: Empty `[EMPTY_BODY]` extractions (`0` chars), streaming media playlist stubs (`.wvx`/`.asx`), Adobe PDF portfolio viewer placeholders (`"For the best experience, open this PDF portfolio in Acrobat X..."`), or 1-line placeholder stubs with zero document content. Set `error_reason` (e.g. `"Empty document body with no extractable text"`, `"Windows Media ASX/WVX stream redirect stub"`).
  3. **`ocr_unreadable`**: Completely garbled OCR gibberish or un-OCR'd scan/image-only PDFs with `[EMPTY_BODY]` / GPO-footer-only blank scans where prose cannot be read (`text_quality: "garbled"`). Set `error_reason` (e.g. `"Unreadable garbled OCR scan"`, `"Image-only scan with no extractable prose text"`).
- **Structural Wrapper / Listing Non-Usable Statuses (NO `error_reason`; extract real masthead metadata if present; `composed_title`/`gist`/`topics` optional):**
  4. **`catalog_xml`**: Machine-readable GPO/GovInfo/House XML metadata files (`MODS`, `PREMIS`, bill-status/committee-schedule catalog XML dumps where raw XML/catalog tags are the artifact rather than prose). Set `status: "catalog_xml"`, `text_quality: "native"`, plus any real `chamber`/`congress`/`committees`/`doc_date`/`refs` clearly stated.
  5. **`index_or_listing`**: Multi-event HTML directory/navigation/calendar index pages (`"Upcoming Hearings"`, `"All Hearings"`, search hit lists, committee press-release index pages) that list multiple separate items rather than a single event/document. Set `status: "index_or_listing"`, `text_quality: "native"`, plus `chamber`/`congress`/`committees` if clear.
  6. **`govinfo_wrapper`**: GPO/GovInfo package wrapper stubs (`"[TEXT NOT AVAILABLE]"`, `"[TEXT NOT AVAILABLE REF TO PDF]"`, Congress.gov empty viewer shells with no bill/hearing body). Set `status: "govinfo_wrapper"`, `text_quality: "native"`, plus visible masthead metadata (`verbatim_title`, `chamber`, `congress`, `committees`, `doc_date`, `refs`).
  7. **`cover_or_toc`**: Standalone GPO hearing/report cover sheets or standalone Table of Contents pages (`"CONTENTS"`, THOMAS report TOC pages) lacking the underlying document body. Set `status: "cover_or_toc"` + visible masthead fields.
- **Usable Exhibits vs `error_or_non_document`:**
  - Redacted/internal emails, chat logs, org charts, subpoenas, court filings, and news clips entered into the record are `status: "usable"` (`investigative_exhibit`, `legal_or_investigative_filing`, or `news_clip_or_article`), **NEVER** `error_or_block`.
  - Use `status: "usable", primary_kind: "error_or_non_document"` ONLY when a file has readable caption/label/metadata text (so it is not a blank/WAF error) yet represents a non-document artifact (e.g., standalone photo collage, placard/poster photo sheet, or non-document media artifact).

### Canonical Citation Prefixes (`refs` — `<= 25` items)
Use exact schema-blessed prefixes whenever formal identifiers appear in the text:
- **Legislation, Law & Regulation:** `bill:H.R. 1234`, `bill:S. 567`, `amdt:S. Amdt. 12`, `law:P.L. 117-58`, `usc:42 U.S.C. 1395`, `cfr:40 CFR 60`, `fr:88 FR 12345`, `eo:E.O. 14028`, `rule:House Rule XI`, `docket:EPA-HQ-OAR-2021-0317`
- **Nominations & Treaties:**
  - `nom:PN...` — Presidential Nomination numbers on `nominee_questionnaire_apq`, nomination hearings, and support letters (e.g., `nom:PN1234`, `nom:PN87-118`)
  - `treaty:Treaty Doc. 117-1` / `treaty:Senate Executive E, 95-2` — Senate Treaty Documents & Executive treaties
- **Congressional & Legislative Branch Publications:**
  - `rept:H. Rept. 118-100`, `rept:S. Rept. 117-45` — numbered committee/conference reports
  - `hrg:S. Hrg. 117-210`, `hrg:Serial No. 118-12` — GPO hearing serials
  - `sudoc:Y 4....` — Superintendent of Documents classification numbers on GPO imprints/covers/depository stamps (e.g., `sudoc:Y 4.J 89/2:S.HRG.117-210`, `sudoc:Y 4.EN 2/3:118-15`, `sudoc:Y 4.AP 9/1:T 71/2002/PT. 2`; collapse internal linebreaks into single spaces and repair obvious single-char OCR noise like `&/1` -> `9/1` only when unambiguous, or keep clean printed call string)
  - `cbo:...` — Congressional Budget Office cost estimates/publications (e.g., `cbo:H.R. 2670 Cost Estimate`, `cbo:Pub. No. 58912`)
  - `jct:JCX-...` / `jct:JCS-...` — Joint Committee on Taxation publications (e.g., `jct:JCX-14-23`)
  - `crs:R...` / `crs:RL...` / `crs:IF...` / `crs:LSB...` / `crs:RS...` — Congressional Research Service report codes (e.g., `crs:R47500`, `crs:IF12345`, `crs:RL33614`)
  - `gao:GAO-...` — GAO reports/testimonies (e.g., `gao:GAO-23-106123`)
- **Executive, Legal, Property & Oversight Identifiers:**
  - `olc:...` — DOJ Office of Legal Counsel opinions/memos (e.g., `olc:45 Op. O.L.C. 1`, `olc:OLC Opinion 2021-05-10`)
  - `gsa:...` — GSA Public Buildings Service prospectus numbers (e.g., `gsa:PCA-0001-WA24`, `gsa:PDS-02024`)
  - `grant:...` — Federal grant / cooperative agreement / award numbers in TTF disclosures or oversight docs (e.g., `grant:DE-SC0012345`, `grant:NIH R01-AI123456`)
  - `advisory:...` — Formal committee press/hearing advisory or alert numbers (e.g., `advisory:Advisory No. 118-09`)
  - `exhibit:Exhibit 1`, `gpo:52-891`, `id:...`

### Exact Allowed Enums (`apply_batch_labels.py` enforces 100% match)
- **`status`** (required):
  `usable` | `cover_or_toc` | `govinfo_wrapper` | `index_or_listing` | `catalog_xml` | `stub_or_blank` | `error_or_block` | `ocr_unreadable`
- **`text_quality`** (required):
  `native` | `clean_ocr` | `noisy_ocr` | `garbled`
- **`chamber`**:
  `house` | `senate` | `joint` | `commission` | `executive_or_external`
- **`congress`**: integer `1..130` (odd-year Jan 1–2 noon rule: e.g. `1945–1946` is `79`, `1995–1996` is `104`, `1997–1998` is `105`, `1999–2000` is `106`, `2001–2002` is `107`, `2003–2004` is `108`, `2005–2006` is `109`, `2007–2008` is `110`, `2009–2010` is `111`).
- **`event_type`**:
  `hearing` | `field_hearing` | `nomination_hearing` | `markup` | `business_meeting` | `roundtable_or_briefing` | `floor_or_other`
- **`venue_kind`**:
  `capitol_room` | `field_site` | `virtual` | `hybrid`
- **`dates`**: `doc_date` (`YYYY-MM-DD` or `YYYY-MM`), `event_date` (`YYYY-MM-DD`), `due_date` (`YYYY-MM-DD`), `date_spans` (`<=8` verbatim date substrings from text).
- **`primary_kind`** (`47` enums; required when `status == "usable"`):
  `hearing_transcript` | `witness_statement` | `member_opening_statement` | `member_or_floor_statement` | `truth_in_testimony_disclosure` | `witness_biography` | `witness_list` | `member_roster` | `attendance_quorum_sheet` | `qfr_request` | `qfr_response` | `nominee_questionnaire_apq` | `hearing_notice` | `markup_notice` | `hearing_memo_or_charter` | `meeting_results` | `committee_vote` | `bill_or_draft` | `committee_amendment` | `comparative_print` | `section_by_section` | `committee_report` | `explanatory_statement` | `committee_resolution` | `committee_rules` | `oversight_plan` | `budget_views_and_estimates` | `revenue_or_cost_estimate` | `treaty_document` | `agency_or_gao_crs_report` | `external_report_or_whitepaper` | `oversight_letter` | `witness_invitation` | `nomination_or_support_letter` | `external_submission_letter` | `public_comment_or_submission` | `investigative_exhibit` | `legal_or_investigative_filing` | `news_clip_or_article` | `press_release_or_fact_sheet` | `legislative_schedule_or_calendar` | `gsa_prospectus_or_property` | `slides_or_visual` | `event_web_page` | `multi_doc_packet` | `error_or_non_document` | `other`
- **`personas`** (`<=26` active actors in reading order ONLY; the limit was 10 until 2026-11-18, raised so a transcript's whole witness list fits — never roll-call grids or passive letterhead rosters):
  - Required per persona: `name` (clean full name without honorifics/degrees), `role`, `entity_type`
  - Optional per persona: `creds`, `title`, `org` (full institution string), `sub_org`, `secondary_orgs` (`[]`), `on_behalf_of`, `party_state` (e.g. `R-UT`, `D-CA`), `panel` (string, e.g. `"Panel I"`), `work_addr`, `official_contact`, `prior_roles` (`[]<=8`), `education` (`[]<=5`), `redacted_personal_pii` (`true` only — set when private home address, personal email, or personal phone on a TTF/questionnaire/letter is redacted or withheld!)
  - **`role` (`16` enums)**:
    `witness` | `author_or_speaker` | `chair` | `ranking_member` | `presiding` | `questioner` | `sponsor` | `cosponsor` | `amendment_offeror` | `nominee` | `introducer` | `sender` | `recipient` | `signatory` | `staff` | `party_or_investigator`
  - **`entity_type` (`7` enums)**:
    `member` | `gov_official` | `military_officer` | `judicial_or_exec_nominee` | `non_gov_person` | `staff` | `organization`
- **`correspondence_flow`** (`9` enums):
  `committee_to_witness` | `witness_to_committee` | `congress_to_agency` | `agency_to_congress` | `member_to_committee` | `committee_to_member` | `external_to_committee` | `foreign_gov_to_congress` | `internal_exhibit_chain`
  - **`foreign_gov_to_congress` formatting example:** Letters addressed to U.S. Congressional Committees, Commissions (e.g., Tom Lantos Human Rights Commission, Helsinki Commission), Chairs, or Members from foreign embassies, ambassadors, foreign ministries, or foreign parliamentarians -> set `primary_kind: "external_submission_letter"` (or `"oversight_letter"` when responding to an inquiry), `correspondence_flow: "foreign_gov_to_congress"`, `issuer_org` to the foreign embassy/ministry (e.g., `"Embassy of the Republic of Haiti"`, `"Republic of the Marshall Islands Ministry of Foreign Affairs and Trade"`), sender persona with `role: "sender"`, `entity_type: "gov_official"` (or `"organization"` if unsigned embassy note), and congressional addressee(s) with `role: "recipient"`, `entity_type: "member"`.
- **`disclosure`** (ONLY on `truth_in_testimony_disclosure` or conflict/financial disclosure forms):
  `capacity` (`self` | `organization` | `government`), `gov_witness` (`bool`), `represented_orgs` (`[]`), `fiduciary_orgs` (`[]`), `unrepresented_parent_or_sub` (`bool`), `has_federal_grants` (`bool`), `federal_grants` (`[]`), `has_foreign_payments` (`bool`), `foreign_payments` (`[]`).
- **Required Synthesis Tail on Every `usable` Document**:
  - `composed_title`: Clean, informative `< 110`-char (`8..109` chars) title synthesized from extracted entities/subject.
  - `gist`: `4..22` words (`<= 22` words hard cap!) factual summary grounded strictly in document numbers/claims.
  - `topics`: `3..6` (`1..6` hard cap) normalized policy/subject strings.
