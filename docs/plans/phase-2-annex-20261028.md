# Congressional Document Archive: Phase-2 Annex

**Note, 2026-10-28.** What phase 2 adds: hearings, witnesses, recordings and the spicy-regs entities. Its rules were moved here unchanged from [[DATA-MODEL]] (§1–3, formerly DM §6.4, §6.5, §6.7, §7.11 and the entity rows of §8.1) and [[IMPLEMENTATION-PLAN]] (§4), so phase 1 can be built without reading them. §1–3 are normative as [[DATA-MODEL]] §2 says, from phase 2 on.

## 1. Lake and Reference Inputs

### 1.1 Reference Inputs

Committees, members, terms, current rosters, bills, CBO estimates, floor votes and nominations come from spicy-regs, which owns their raw records and provenance. They are not lake tables: each publish pins each family's current immutable generation as spicy-regs' index `data.spicygov.ai/publication.v2.json` names it (the older `publication.json` names pruned generations), and the model reads the files that index lists for each table, `generations/<family>/<digest>/<table>.parquet`.

| spicy-regs table | Columns the model reads | Gives |
|---|---|---|
| `committees` | `system_code`, `chamber`, `name`, `committee_type`, `parent_system_code`, `history` (official names with start and end dates), `website_url`, `is_current` | Every committee and subcommittee of every Congress, named for any date |
| `members` | `bioguide_id`, `name_first`, `name_last`, `lis_id`, `fec_ids`, `opensecrets_id`, `govtrack_id`, `icpsr_id`, `wikidata_id` | Every member since 1789, with identifiers in other datasets |
| `member_terms` | `bioguide_id`, `term_type`, `term_state`, `term_district`, `term_party`, `term_start`, `term_end` | Every term |
| `committee_assignments` | `congress`, `system_code`, `bioguide_id`, `position`, `rank`, `party` | Current-Congress seats from the House Clerk's and the Senate's files |
| `congress_bills` | `bill_id`, `title`, `short_title`, `sponsor_bioguide_id`, `introduced_date`, `latest_action_date`, `latest_action_text`, `stage`, `policy_area` | 422,011 measures from the 6th Congress, keyed by `bill_id`, an opaque string: `{congress}-{type}-{number}` with the type lowercase, as `measure_keys` writes it |
| `bill_committees` | `bill_id`, `system_code` | The committees each bill was referred to: 286,721 rows over 167,162 bills of the 108th–119th Congresses |
| `amendments` | `amendment_id`, `purpose`, `sponsor_bioguide_id`, `latest_action_date`, `latest_action_text`, `amended_bill_id`, `amended_amendment_id` (all strings) | Amendments to a bill or to another amendment; the 119th Congress only until spicy-regs backfills |
| `bill_committee_activities` | `bill_id`, `system_code`, `activity_name`, `activity_date` (a UTC instant), `occurrence` | What each committee did on a bill and when (referred, hearings, markup, reported), as BILLSTATUS lists it; filling Congress by Congress |
| `cbo_cost_estimates` | `bill_id`, `publication_id`, `pub_date`, `description` | CBO cost estimates from the 108th Congress, 913–1,666 a Congress |
| `roll_call_votes` | `vote_id`, `chamber`, `vote_day`, `question`, `result`, `yea`, `nay`, `bill_id`, `documents` | Floor roll-call votes, House from the 101st Congress and Senate from the 108th, keyed `{congress}-{chamber}-{session}-{roll_number}`; a Senate vote's `documents` entry with `type = 'PN'` names a nomination by `number` `{number}[-{part}]`, in the vote's own Congress when the entry's is null |
| `bill_vote_references` | `bill_id`, `congress`, `chamber`, `session`, `roll_number` | Floor votes a bill's actions name, joined to `roll_call_votes` by building that `vote_id` (19,766 of 19,766) |
| `nominations` | `citation`, `congress`, `description`, `organization`, `received_date`, `latest_action_date`, `latest_action_text`, `committees_json` (referral system codes), `hearings_json` (printed hearings by jacket) | Nominations; the 119th Congress only until spicy-regs backfills |

A change in these columns fails the model at its next publish rather than reading wrong values; the model SQL moves with the generation. Spicy-regs keeps each family's last three generations and every generation a consumer pins; the archive pins those of every release it keeps ([[ARCHITECTURE]] §10.3.7).

### 1.2 `meeting_records`

One row per input and parser version: a Congress.gov meeting record, inline in a receipt line or a response body, or a House `committee-meeting` XML record, with the meetings it gives in `meetings`.

| Column | Type | Notes |
|---|---|---|
| `record_sha` | fixed[32] | The body's SHA-256, or an inline record's `record_sha` ([[DATA-MODEL]] §6.1). |
| `parser_version` | string | — |
| `status`, `error_type` | string | [[DATA-MODEL]] §6. |
| `source` | string | `congress_gov` or `house_xml`. |
| `meetings` | list<struct> | One element per meeting the input gives, usually one; empty when it gives none. Fields below. |

Each `meetings` element:

| Field | Type | Notes |
|---|---|---|
| `event_id` | long | The meeting key ([[DATA-MODEL]] §3). A House XML `meeting-id` drops its four-letter prefix (HHRG, HMKP, HMTG). |
| `chamber` | string, nullable | [[DATA-MODEL]] §3. |
| `congress` | int, nullable | — |
| `session` | int, nullable | The Congress's session. |
| `updated` | timestamptz, nullable | Congress.gov's `updateDate`. |
| `title` | string, nullable | — |
| `meeting_date` | date, nullable | — |
| `meeting_type` | string, nullable | Hearing, markup, meeting, … |
| `status` | string, nullable | As the source states it: scheduled, postponed, cancelled, rescheduled, … |
| `sittings` | list<struct<start timestamptz, end timestamptz, room string, building string, address string>> | Each sitting with its place; most meetings have one. |
| `committees` | list<struct<system_code string, role string>> | Congress.gov system codes; `role` is host, joint or the source's own word. |
| `subject_keys` | list<string> | What the meeting covers: bills as `measure_keys` writes them, nominations as `nomination_id` (§2, from a zero-padded `part`), treaties `{congress}-treaty-{number}`. |
| `transcript_jackets` | list<long> | GPO jacket numbers of the printed hearing, from `hearingTranscript[].jacketNumber` (§2). |
| `videos` | list<struct<name string, url string, video_key string>> | Recording links the source gives. `video_key` is `youtube:{id}` for a YouTube watch link and `senate:{filename}` for a senate.gov player link, else null; the recordings are not captured. |

- **Sources:** Congress.gov meeting records for both chambers (18,140 meetings, about 11 identical inline copies each, which `record_sha` collapses) and House `committee-meeting` XML. Senate committee pages carry no meeting ID; they give documents and appearances (§1.3).
- **Work list:** good-fetched bodies and inline records whose URL matches the meeting-source registry ([[DATA-MODEL]] §7.1) with no row at the pinned version. Inline records are read once from the four `congress/meetings` receipt files (77 MB, 199,156 lines) by their `captures` pointers, and `record_sha` is computed then.
- **PK:** `(record_sha, parser_version)`; tens of thousands of rows. The model unnests `meetings`.
- **Current records:** per `(event_id, source)`, the latest by `(updated desc nulls last, latest good fetch's retrieved_at desc nulls last, record_sha)`. Each field of a meeting comes from its current `house_xml` record when that states it, else its current `congress_gov` record.

### 1.3 `appearance_records`

One row per input and parser version, with the witnesses it lists in `appearances`. An appearance is keyed, not matched: the model gives it a `witness_key` (§2), which a later witness table keys on.

| Column | Type | Notes |
|---|---|---|
| `record_sha` | fixed[32] | The body's SHA-256, or an inline record's ([[DATA-MODEL]] §6.1). |
| `parser_version` | string | — |
| `status`, `error_type` | string | [[DATA-MODEL]] §6. |
| `source` | string | `house_xml`, `congress_gov`, `senate_page` or `mods`. |
| `appearances` | list<struct> | One element per witness, in source order; an input's entries sharing a `name_key` keep the first, so `witness_key` (§2) is unique per occasion. Empty when it lists none. Fields below. |

Each `appearances` element:

| Field | Type | Notes |
|---|---|---|
| `event_id` | long, nullable | The meeting, for a House witness list or a Congress.gov record. |
| `package_id` | string, nullable | The GovInfo package, for a MODS record. |
| `page_url` | string, nullable | The hearing page's source URL, for a Senate page. |
| `name_key` | string | The recorded name, NFKC, casefolded, punctuation dropped, whitespace collapsed. It survives re-parsing and reordering; two spellings give two keys. With no recorded name, `#` and the entry's 1-based position in the source's list, so unnamed witnesses stay apart. |
| `name` | string, nullable | As recorded. |
| `honorific`, `given`, `middle`, `family`, `suffix` | string, nullable | When the source splits the name (House XML). |
| `position`, `organization`, `on_behalf_of`, `location` | string, nullable | As recorded. |
| `panel` | string, nullable | The panel's label. |
| `panel_order`, `display_order` | int, nullable | Source order. |
| `witness_type` | string, nullable | As recorded. |
| `testified` | boolean, nullable | Whether the source marks the witness as having testified. |
| `bioguide_id` | string, nullable | Given by the source for a member witness; never inferred. |
| `document_urls` | list<string> | The witness's own document links, resolved against the source's URL as [[DATA-MODEL]] §7.2 resolves links: a House witness list's `witness-document` entries, a Senate page card's links. Empty for Congress.gov and MODS. |

- **Sources:**
  - House `witness-list` XML, beside the meeting's `committee-meeting` record: split names, panels, witness documents and member bioguide IDs;
  - Congress.gov meeting records: name, position and organization; they list no Senate witnesses (0 of 4,575 Senate events);
  - Senate committee hearing pages, whose layout puts each witness's links inside that witness's card: 90.7% of senate.gov testimony files;
  - GovInfo MODS records already in raw, which list a printed hearing's witnesses for both chambers, at granule level too.
- **Work list:** good-fetched witness lists, Congress.gov records and MODS records, and Senate hearing pages, matching the meeting-source registry ([[DATA-MODEL]] §7.1), with no row at the pinned version.
- **PK:** `(record_sha, parser_version)`; one input lists one meeting, page or package. The model unnests `appearances`.

## 2. Hearings, Witnesses and Reference Entities

Hearings, witnesses, members, committees, bills and nominations are the entities a reader explores beside documents: a hearing's transcript, recording and witnesses and what each submitted, a member's committees and hearings, a bill's committees, cost and votes, a nomination's hearings and votes. Every relationship is one a publisher states; none is matched by name.

```
transcripts    := per meeting, each listed document whose package_id parses as
                  CHRG-{c}{h|s|j}hrg{digits} with {c} the meeting's congress, int({digits})
                  one of its transcript_jackets, and the letter its chamber's when it has
                  one; as (package_id, list_row). Jackets are matched as integers, never
                  formatted: 49104057 is CHRG-118shrg049104057
occasion       := 'meeting:{event_id}' for a House witness list or Congress.gov record;
                  for a MODS appearance, the meeting whose transcripts hold its package
                  when exactly one does, else 'package:{package_id}'; for a Senate page,
                  'page:' and the hex of the first 8 bytes of sha256(url_key(page_url))
witness_key    := the lowercase hex of the first 8 bytes of the SHA-256 of the compact
                  JSON ["witness", occasion, name_key]
witnesses      := per occasion, the appearances of its highest-precedence source that
                  lists any (House witness list, then Congress.gov, then MODS; a page is
                  its own occasion), each source's latest record for the occasion in the
                  order of §1.2
witness_keys   := per document, the witness_key of every appearance one of whose
                  document_urls matches one of its document members (DATA-MODEL §7.2
                  matching); a printed hearing's witnesses are the transcript's, through
                  its package_id, never documents they submitted
members        := per bioguide_id, the pinned members row, named "{name_first}
                  {name_last}", and its member_terms, latest first, term_type mapped
                  (DATA-MODEL §3)
rosters        := the pinned committee_assignments, rank as an integer when it is one:
                  current-Congress seats only, because spicy-regs keeps no roster history
committees     := the pinned committees, each with its official names from history as
                  half-open date intervals (DATA-MODEL §4), latest start first, then name
                  bytewise; a label for a date is the first name whose interval holds it,
                  else the current name
bills          := the pinned congress_bills row of every bill_id a listed document's
                  measure_keys or a meeting's subject_keys names, with its committees of
                  referral (bill_committees), its CBO estimates, and its floor votes once
                  each: votes whose bill_id is it (basis vote_record), then votes its
                  actions name (bill_vote_references, basis bill_action); its amendments,
                  by amended_bill_id or through amended_amendment_id to the bill the
                  chain reaches; and its committee activities, dated by DATA-MODEL §4
recordings     := per video_key a meeting's videos names, the caption, subtitle and
                  playlist bodies whose URLs the recording-source registry ties to it,
                  one per (format, language, production), from its latest good fetch;
                  a streamed track's segment files are not tracks
nomination_id  := '{congress}-pn-{number}', plus '-{int(part)}' unless the part is 0:
                  spicy-regs' citation form (PN730-2 is 119-pn-730-2)
nominations    := per nomination_id a meeting's subject_keys names, the pinned row whose
                  citation gives it, its referral committees, the packages its printed
                  hearings' jackets name (as transcripts parse them), and every Senate vote
                  whose documents name it, by (vote_day, vote_id)
```

- No witness is matched across occasions or sources beyond the current records and the transcript link; the witness table that matches them comes later and keys on `witness_key`.
- A name or role a later reading supplies, such as a structured transcript from captions, subtitles or `pdf_text`, is an attribute of the appearance and never part of `witness_key`, so links survive it.
- The model reports appearances whose `name_key` differs only by a title or initial within one occasion, as input for that table, and Senate page cards with no links.

## 3. Entity Release Files

These files join [[DATA-MODEL]] §8.1's table, with its shared writer settings and profiles.

| File | Columns | Order | Writer settings | Size |
|---|---|---|---|---|
| `witnesses.parquet` | `witness_key` string, `occasion` dict, `event_id` int64 nullable, `package_id` string nullable, `page_url` string nullable, `name` string nullable, `position`, `organization`, `on_behalf_of`, `location`, `panel` (strings, nullable), `panel_order`, `display_order` int16 nullable, `witness_type` dict nullable, `testified` bool nullable, `bioguide_id` dict nullable | `(occasion, panel_order, display_order, witness_key)` | Whole | *est.* a few MB |
| `recordings.parquet` | `video_key` string, `event_ids` List<int64>, `tracks` List<Struct<body fsb(32), suffix dict, format dict, language dict nullable, production dict nullable>> | `video_key` | Whole | *est.*, measured with S2 |
| `committees.parquet` | `system_code` string, `name` string, `chamber` dict, `committee_type` dict nullable, `parent_system_code` dict nullable, `names` List<Struct<name string, start date32, end date32>>, `website` string nullable, `is_current` bool nullable | `system_code` | Whole | Under 1 MB |
| `members.parquet` | `bioguide_id` string, `name` string, `terms` List<Struct<chamber dict, state dict, district int16, party dict, start date32, end date32>>, latest first, `cross_ids` Struct<lis, opensecrets, govtrack, icpsr, wikidata string; fec List<string>> | `bioguide_id` | Whole | *est.* about 2 MB |
| `rosters.parquet` | `congress` int16, `system_code` dict, `bioguide_id` dict, `title` dict nullable, `rank` int16 nullable, `party` dict nullable | `(system_code, rank, bioguide_id)` | Whole | Under 1 MB |
| `bills.parquet` | `bill_id` string, `title` string nullable, `short_title` string nullable, `sponsor_bioguide_id` dict nullable, `introduced`, `latest_action_date` date32 nullable, `latest_action_text` string nullable, `stage` dict nullable, `policy_area` dict nullable, `committees` List<dict> (system codes), `cbo_estimates` List<Struct<publication_id string, date date32, description string>>, `floor_votes` List<Struct<vote_id string, basis dict, chamber dict, date date32, question string, result string, yea int16, nay int16>>, `amendments` List<Struct<amendment_id string, purpose string, sponsor_bioguide_id dict, latest_action_date date32, latest_action_text string>>, `committee_activities` List<Struct<system_code dict, activity dict, date date32>> | `bill_id` | Whole | *est.* a few MB |
| `nominations.parquet` | `nomination_id` string, `description` string, `organization` string nullable, `received` date32 nullable, `latest_action_date` date32 nullable, `latest_action_text` string nullable (the outcome, such as a voice vote), `committees` List<dict>, `transcripts` List<string> (package IDs), `floor_votes` List<Struct<vote_id string, date date32, question string, result string, yea int16, nay int16>> (cloture, then confirmation, as cast) | `nomination_id` | Whole | Under 1 MB |

## 4. Plan Items

### 4.1 Phase-2 Exit Checklist

Phase 2 is done when, beyond [[IMPLEMENTATION-PLAN]] §6.6's phase-1 checklist:
- every older gzip PDF has a recorded `.pdf` copy (B13), and the full re-hash has run (B10);
- the committee explorer reads meeting and witness records from the lake (F3);
- spicy-regs' retention plan keeps every generation a kept release pins (F4);
- the weekly meeting job is gone, after B14's first run;
- C3's export is byte-identical across threads, batch sizes and a forced spill, so the profile no longer pins the runner class.

### 4.2 Uncertainties

As in [[IMPLEMENTATION-PLAN]] §8, each row closes only with its measurement.

| Uncertainty | Settled by | Decides |
|---|---|---|
| Roster history: spicy-regs keeps the current Congress only | A spicy-regs change publishing its captured rosters as dated history | Rosters show current seats until then |
| How often one printed hearing covers several meetings, leaving its MODS witnesses on the package | **Settled by D4 full-corpus measurement:** among **10,723** `CHRG-*` packages linked to meetings in `meetings.parquet`, **6,917 (64.5%)** link to **1 meeting** (`meeting:{event_id}`) and **3,806 (35.5%)** link to **>1 meetings** (`package:{package_id}`); across all **34,559** parsed `CHRG-*` MODS records (**107,272** deduplicated appearances), **6,882** packages (**22,501** witnesses) resolve to 1 meeting, **3,796** packages (**12,162** witnesses) resolve to 2–15 meetings, and **23,881** packages (**72,609** witnesses, mostly pre-113th Congress) have 0 meeting records | Keep `'package:{package_id}'` when `count(event_id) != 1`; no per-day rule needed in Phase 2 |
| Senate card coverage by committee site (judiciary 98.6%, hsgac 64.8%, indian 54.8%, jec 0%) | **Settled by D4 full-corpus measurement** across **6,685** candidate `senate_page` captures (**5,030** non-empty pages, **17,687** witnesses, **16,496** card links) and **8,946** listed Senate testimony documents: **5,638 / 8,946 (63.0%)** match strictly under current `url_key`; stripping ColdFusion `[?&]download=1` suffixes on `banking`, `finance`, `appropriations`, `aging`, `budget` and `veterans` raises coverage to **8,096 / 8,946 (90.5%)** | Normalize `[?&]download=1` on ColdFusion `/download/` URLs; second page layouts only needed for `environment`, `intelligence` and `jec` |
| Event IDs never name two chambers (observed on 18,140, not promised by the publishers) | Invariant 15 at every publish (**0** multi-chamber `event_id`s across all **18,140** Congress.gov + **6,164** House XML `meeting_records`, **18,225** resolved meetings) | The meeting key, if one ever does |
| Nominations before the 119th Congress | spicy-stack ss-vhi2's backfill | How far back nomination pages reach |
| How often one witness gets two keys at one meeting (spelling, titles, initials) | **Settled by D4 full-corpus measurement:** intra-record duplicate `name_key`s occur in **0.64%** of `mods` records (**220 / 34,559**, **534** rows dropped), **0.61%** of `congress_gov` records (**110 / 18,140**, **478** rows dropped), and **0.44%** of `house_xml` records (**15 / 3,398**, **23** rows dropped), leaving **0** duplicate `(occasion, witness_key)` rows in `witnesses.parquet` (**109,572** rows across **28,392** occasions); **138 / 28,392 (0.49%)** occasions (**152** pairs) have distinct `name_key`s sharing surname + first initial (49 honorific/title pairs, plus middle-initial and suffix variants) | `deduplicate_appearances` + `ROW_NUMBER() OVER (PARTITION BY occasion, name_key)` guarantees unique `(occasion, witness_key)`; later witness entity table matches honorific/initial pairs |

#### 4.2.1 D4 Measurement Details

1. **Multi-meeting MODS packages (`meeting_records` = 24,304 rows; `appearance_records` = 62,782 rows including 34,559 `mods` rows):**
   - **Meeting count distribution across the 10,723 linked `CHRG-*` packages in `meetings.parquet`:** `1 meeting: 6,917 (64.5%)`, `2: 2,696 (25.1%)`, `3: 750 (7.0%)`, `4: 199 (1.9%)`, `5: 52`, `6: 48`, `7: 14`, `8: 19`, `9: 8`, `10: 5`, `11: 3`, `12: 1`, `13: 5`, `14: 5`, `15: 1` (total `>1 meetings`: **3,806 / 10,723 = 35.5%**).
   - **Examples of multi-meeting packages:** `CHRG-112hhrg64725` (`event_id`s `103896, 103897`), `CHRG-112hhrg72254` (`100083, 100180`), `CHRG-113hhrg78631` (`100222, 100223, 100225`), `CHRG-113hhrg79435` (`100220, 100221, 101129`).
   - **MODS witness assignment across all 34,559 parsed `CHRG-*` packages (22,498 with `>=1` witness; 107,272 deduplicated appearances):**
     - `1 meeting` (`occasion = 'meeting:{event_id}'`): **6,882** packages (**4,798** with witnesses, **22,501** appearances; **3,053** overridden by higher-precedence `house_xml` or `congress_gov`, **1,745** winning in `witnesses.parquet` with **6,213** witnesses).
     - `>1 meetings` (`occasion = 'package:{package_id}'`): **3,796** packages (**2,256** with witnesses, **12,162** appearances: `2 meetings: 2,690 pkgs / 9,255 witnesses`, `3 meetings: 747 pkgs / 2,397 witnesses`, `4 meetings: 199 pkgs / 417 witnesses`, `5–15 meetings: 160 pkgs / 93 witnesses`).
     - `0 meetings` (`occasion = 'package:{package_id}'`): **23,881** packages (**15,444** with witnesses, **72,609** appearances).

2. **Senate card coverage by committee site (6,685 candidate pages, 5,030 with cards, 8,946 listed Senate testimony documents):**

| Committee site | Candidate pages | Non-empty pages | Witnesses | Listed testimony docs | Strict `url_key` match | Match stripping `[?&]download=1` |
|---|---:|---:|---:|---:|---:|---:|
| `judiciary.senate.gov` | 645 | 602 | 2,424 | 2,265 | 2,235 (**98.7%**) | 2,235 (**98.7%**) |
| `commerce.senate.gov` | 482 | 463 | 1,688 | 1,039 | 1,014 (**97.6%**) | 1,014 (**97.6%**) |
| `banking.senate.gov` | 460 | 440 | 1,354 | 892 | 0 (**0.0%**) | 860 (**96.4%**) |
| `finance.senate.gov` | 405 | 350 | 1,210 | 826 | 0 (**0.0%**) | 804 (**97.3%**) |
| `appropriations.senate.gov` | 538 | 369 | 1,735 | 632 | 0 (**0.0%**) | 451 (**71.4%**) |
| `epw.senate.gov` | 365 | 258 | 936 | 626 | 533 (**85.1%**) | 533 (**85.1%**) |
| `hsgac.senate.gov` | 599 | 458 | 1,458 | 499 | 327 (**65.5%**) | 327 (**65.5%**) |
| `energy.senate.gov` | 360 | 269 | 957 | 460 | 388 (**84.3%**) | 388 (**84.3%**) |
| `foreign.senate.gov` | 540 | 382 | 1,019 | 347 | 308 (**88.8%**) | 308 (**88.8%**) |
| `indian.senate.gov` | 249 | 184 | 825 | 316 | 174 (**55.1%**) | 174 (**55.1%**) |
| `help.senate.gov` | 249 | 217 | 784 | 265 | 250 (**94.3%**) | 250 (**94.3%**) |
| `aging.senate.gov` | 150 | 132 | 476 | 242 | 0 (**0.0%**) | 242 (**100.0%**) |
| `armed-services.senate.gov` | 296 | 218 | 661 | 169 | 166 (**98.2%**) | 166 (**98.2%**) |
| `agriculture.senate.gov` | 177 | 138 | 548 | 123 | 102 (**82.9%**) | 102 (**82.9%**) |
| `sbc.senate.gov` | 145 | 101 | 375 | 85 | 69 (**81.2%**) | 69 (**81.2%**) |
| `budget.senate.gov` | 191 | 153 | 523 | 81 | 0 (**0.0%**) | 79 (**97.5%**) |
| `intelligence.senate.gov` | 436 | 133 | 298 | 49 | 25 (**51.0%**) | 25 (**51.0%**) |
| `environment.senate.gov` | 192 | 48 | 139 | 20 | 3 (**15.0%**) | 3 (**15.0%**) |
| `veterans.senate.gov` | 127 | 115 | 266 | 9 | 0 (**0.0%**) | 8 (**88.9%**) |
| `jec.senate.gov` | 56 | 0 | 0 | 1 | 0 (**0.0%**) | 0 (**0.0%**) |
| **Total (all Senate hosts)** | **6,685** | **5,030** | **17,687** | **8,946** | **5,638 (63.0%)** | **8,096 (90.5%)** |

3. **Duplicate witness keys per occasion:**
   - **Before deduplication (within a single source record):** `mods` has **220 / 34,559 (0.64%)** records with repeated `name_key`s (**107,806** raw -> **107,272** deduplicated, **534** dropped, e.g., multi-panel or multi-day appearances in `CHRG-117shrg46099`); `congress_gov` has **110 / 18,140 (0.61%)** records (**35,964** raw -> **35,486** deduplicated, **478** dropped); `house_xml` has **15 / 3,398 (0.44%)** records (**15,112** raw -> **15,089** deduplicated, **23** dropped).
   - **After deduplication (`appearance-records-resolved.sql` / `witnesses.parquet`):** **0** duplicate `(occasion, witness_key)` rows across all **109,572** resolved witnesses (**28,392** occasions).
   - **Near-collision variants within one occasion:** **652 / 28,392 (2.30%)** occasions (**945** pairs) contain distinct `name_key`s sharing a last token; **138 / 28,392 (0.49%)** occasions (**152** pairs) share both surname and first initial (**49** honorific/title prefix differences such as `dr`/`mr`/`hon`, plus middle-initial and `jr`/`sr`/`ii`/`iii` suffix variants).

### 4.3 MCP Coverage

The MCP coverage tasks (`docs/youtube-coverage/congressional-explorer-mcp-data-coverage-tasks.md`, a proposal): its producer fixes (tasks 1–10) may land on today's exporter so the MCP gains them before the switch, as work the switch deletes; the target covers each, and the switch checks it does:

| Task | Covered by |
|---|---|
| 1 identifiers, 9 coverage | [[DATA-MODEL]] §8–9: native keys, `schema.json`, the manifest's producer and coverage |
| 2–3 participants, ownership | D4 and §2, unnamed witnesses kept apart |
| 4 legislative items | `subject_keys`; spicy-regs amendments and committee activities; markup votes parked ([[IMPLEMENTATION-PLAN]] §7) |
| 5 committee history | spicy-regs `committees`; its other fields are spicy-regs' to add |
| 6 sittings, versions | `sittings`, editions, `version_keys`, alternates |
| 7 file and text catalog | `recordings`; recoveries and reviews in the same release |
| 8 reference data | Not covered: archive routes, session dates and chamber control, channel mappings |
| 10 replay and rebuild | The switch: everything rebuilt from raw, parity by cause |
| 11–15 the two MCP servers | Their own plan, reading release manifests; full research tables are decided then |

## References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
