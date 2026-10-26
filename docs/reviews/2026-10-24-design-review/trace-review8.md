# Review 8 (trace lens): docs/engine-first-data-model.md @ 33c2cba0

Lens: end-to-end trace (raw → lake → model → release), key definitions, PK/current-record rules, invariants, cross-references, duplication, readability.

Evidence sources: the document text; `docs/engine-first-architecture.md` (only to resolve cited sections); parser code under `packages/`; the 2026-10-02 index snapshot (`captures`, `documents`); receipts under `.cache/docspec-catalog/r2-immutable/receipts/` (field names and counts only); spicy-regs `publication.v2.json` and the nine pinned tables it names (fetched with UA `congressional-tech-review/1.0`, ≤4 req/s). Scripts: `r8t_*.py` in this directory. Python ran only as the ct-viewer-publish venv with `-I`.

## 1. Score

**58 / 100.** Confidence: medium-high (every data or code claim below was run; the readability judgements are mine).

The document is dense but almost fully traceable: for nearly every release column I could follow a chain back to a lake column, a parser and a raw source, and the body-key identities (`source_id`, `document_id`, `link_key`) are defined once with deterministic formulas. The score is held down by things a trace exposes rather than a read: the same key spelled in two formats on the two sides of a join (`witness_key` fsb(8) vs `witness_keys` List<dict>), a join column (`chamber`) with no vocabulary whose real inputs disagree in case, a nomination key whose part is zero-padded on one side only, a single-valued `vote_id` for nominations that is ambiguous for 72% of real rows, a recovery capture row whose "source URL" is the recovered copy's address (not the original link) so §7.4 creates two source files per recovery-only document, an order-of-evaluation loop between §7.4 clause 3 and §7.8, invariant 16 contradicted by a legitimate review merge, House witnesses living in a body the "current record" rule can never select, and a §7.8 rule that refuses the build on 6,519 of today's 12,106 import lines. A stray code fence at line 784 also renders all of §8 (Release Files) as a code block, which defeats the "act on one section" goal for the section readers need most.

## 2. Findings (most severe first)

### F1 — major — §7.11 / §8.1 / §10.16: `witness_key` is binary in `witnesses.parquet` and a string in `list.parquet`
- Lines 759–760: `witness_key := first 8 bytes of the SHA-256 …` (bytes). Line 814: `witness_key fsb(8)`. Line 826: `witness_keys … List<dict>` (§4: `dict` is a string). Line 918: "every `witness_keys` entry is in `witnesses`" joins the two.
- Compare `version_keys` (line 639–641), which says "the hex of the first 8 bytes". `witness_key` does not say hex.
- Verified: text. The join is unimplementable as written without an unstated conversion.
- Fix: rewrite line 759–760 as `witness_key := the hex of the first 8 bytes of …` and line 814 as `witness_key dict`, or make `witness_keys` `List<fsb(8)>`; one representation, named once.

### F2 — major — §6.5 / §7.5 / §7.11 / §8.1: `chamber` is a join key and a hash input with no vocabulary, and the real inputs disagree
- `chamber` is `string —` (line 362) with no values. It is half of `meeting_keys` ('chamber:event_id', line 673), half of `occasion` and therefore inside every `witness_key` (lines 756–760), the `(chamber, event_id)` join from witnesses to meetings (line 888), and `committees.chamber dict` (line 815).
- `file_meetings` takes chamber from URLs (`congress.gov/<congress>/meeting/<chamber>/`, line 664); the index shows these as lowercase (`119/house/118618`). `meeting_records` takes it from the Congress.gov JSON, which the old catalog recorded as `House`/`Senate`/`NoChamber` (`documents.parquet` `source_chamber`: House 238,323, Senate 15,694, NoChamber 471). spicy-regs `committees.chamber` is `House`/`Senate`/`Joint`; `committee_assignments.chamber` and `roll_call_votes.chamber` are `house`/`senate`; `member_terms.term_type` is `rep`/`sen`. `packages/committee_meeting/src/committee_meeting/common.py:15` declares `Chamber = Literal["house","senate","joint","unknown"]`.
- Verified: data (index, spicy-regs tables) and code.
- Consequence: `meeting_refs` from URLs will not join `meeting_records` from JSON; `witness_key` moves if anyone later normalizes case.
- Fix: in §3 define **chamber** as one of `house`, `senate`, `joint`, and in §6.5 say the producers MUST write it; in §7.11 say the spicy-regs `chamber` and `term_type` are mapped to that set before any join.

### F3 — major — §6.5 / §7.11 / §8.1: nomination key `{congress}-pn-{number}[-{part}]` is undefined on padding, and the inputs differ
- Line 372 and 780 build the key from spicy-regs `nominations.number` and `part_number`; line 348 says `roll_call_votes.documents` holds "a nomination's `PN{number}[-{part}]`".
- spicy-regs: `nominations.part_number` is zero-padded (`'02'`, `'18'`) while its own `citation` is `PN730-2`; `roll_call_votes.documents` is `list<struct<congress int64, name, number, short_title, title, type>>` with `type='PN'`, `name='PN129-10'`, `number='129-10'` (not a string column), and `congress` is null on 1,681 of 9,079 entries.
- Verified: data (`r8t_spicy_vals.py`).
- Fix: rewrite line 372/780 as `{congress}-pn-{int(number)}[-{int(part)}]` (integers, no leading zeros), rewrite line 348 to describe `documents` as the struct list it is and name the fields the join reads (`type = 'PN'`, `number`, and the vote's own `congress` when the struct's is null).

### F4 — major — §7.11 / §8.1: `nominations.vote_id` is single-valued but 1,552 of 2,155 nominations with Senate votes have more than one
- Line 781: "the Senate vote whose documents name it"; line 819: `vote_id string nullable`.
- spicy-regs roll_call_votes: 2,155 distinct (congress, PN) pairs appear in Senate vote documents; 1,552 appear on ≥2 votes (cloture + confirmation is the normal case).
- Verified: data.
- Fix: replace `vote_id` with `floor_votes List<Struct<…>>` as `bills.parquet` already does (line 818), ordered by `(vote_day, vote_id)`.

### F5 — major — §7.4 / §3 / §7.8: a recovery capture row's "source URL" is the recovered copy's address, so a recovery-only document gets two source files
- §3 (line 67): source URL is "a top-level capture row's final `url`; for a recovery's **bodiless** source file, its original link". §7.4 (line 567) builds source files from "the distinct (body, effective filename, source URL) triples in captures" with nothing excluding `mode = retained_import` rows, and rules 1 and 7 of the effective filename (lines 569, 575) only make sense for such rows. §7.8 (line 723) then adds "a bodiless source file for its original link" when the recovery needs its own document.
- Receipts: on 11,950 of 12,106 `retained_import` lines `url == acquisition.recovered_url`; on 11,296 `url != recovery_evidence.original_url`. So the bodied recovery source file sits at the wayback/recovered URL, its `copy_urls` never hold the original link, and the same recovery also gets the bodiless row: two `filenames` rows and two `filename_readings` work-list pairs per recovery-only document, one of them an unlisted orphan.
- Verified: data (receipts) + text.
- Fix: rewrite line 567 as "the distinct triples over `mode = fetch` rows; plus one bodiless row per URL that never yielded a body; plus one bodiless row per distinct recovery original link, with the decision's `recovered_filename`", and delete rule 7 (`retained_name`) or move it to the bodiless row. Then §3's source-URL definition needs no recovery clause.

### F6 — major — §7.8: "a row with neither [category nor decision kind] MUST fail the build" refuses the build on today's receipts
- Line 722. Receipts: 6,519 of 12,106 import lines carry no `prior_access_category`; 138 carry no original URL in either shape (`recovery_evidence.original_url` on 7,820, `acquisition.original_url` on 6,381), so no decision can match them by exact `original_url` (line 718).
- Verified: data (`r8t_receipts2.py`).
- Consequence: the first publish cannot run until ~6,500 provenance decisions exist, or the rule changes.
- Fix: rewrite line 722: "A row with no category takes its decision's kind, else `recovered_document`; a row whose category the registry does not list fails the build; the model reports rows with no category and no decision." Also list `acquisition.original_url` beside `recovery_evidence.original_url` in §5.2 (line 163) since the ingest mapping must read both.

### F7 — major — §6.7 / §7.11: House witnesses are in a separate `witness-list` body, which "from its current record" can never select
- Line 761–763: witnesses "for a meeting, from its current record (§6.5)". The current record is a `committee-meeting` body (line 377).
- Code: `packages/congress_api/src/congress_api/models/house.py` has `HouseMeetingXML` (tag `committee-meeting`, meeting documents only) and a separate `HouseWitnessListXML` (tag `witness-list`, panels and witnesses, its own `meeting-id`). The index has a `house/witness-xml` family (14,471 rows) beside `house/meeting-xml` (21,239); sample URL `…/105543/HHRG-115-VR09-WList-20170214.xml`.
- Verified: code + data.
- Fix: in §6.7 say House appearances come from the `witness-list` body of the same meeting folder and in §7.11 select "the latest good-fetched `witness-list` body for `(chamber, event_id)`" by the same order as §6.5, not the current record. Also §6 line 214: `appearance_records` from a `witness-list` body has no `meeting_records` rows to ride on, so it needs its own completion rule (see F10).

### F8 — major — §6.2 / §6.7 / §7.11: `group_path` is a join key produced by two parsers with no shared formula
- `readings.links.group_path` (line 293): "the indexed path of the nearest grouping ancestor". `appearance_records.document_group_paths` (line 405): "the `group_path`s of the document groups the source assigns to this witness". `witness_keys` (lines 764–766) joins them by equality.
- No code in `packages/` computes a `group_path` (grep: zero hits), so nothing fixes the format; the old catalog's `source_document_group` values are names (`witnessDocuments`, `meeting-document`), not paths.
- Verified: code (absence) + text.
- Fix: define the path once in §6.2 (element names with 0-based sibling indexes from the root, e.g. `/committee-meeting/panel[0]/witness[2]/witness-documents`) and in §6.7 say the appearance parser writes "the §6.2 path of each `witness-documents` element", or drop the path and have `appearance_records` carry the document hrefs so the join is on `url_key`.

### F9 — major — §7.4 / §7.5 / §7.8: order of evaluation is circular for the recovery bodiless row
- §7.4 clause 3 (line 567): "plus one bodiless row per recovery that **needs a document of its own (§7.8)**" is step 1 of the order (line 645). Whether it needs one is decided by attachment, step 4 (line 648), which needs `listed` (line 609), step 3.
- Verified: text.
- Fix: as in F5, create the bodiless row for every distinct recovery original link unconditionally in step 1; it is harmless when the recovery attaches elsewhere (its singleton component is unlisted).

### F10 — major — §6 / §6.5 / §6.7 / §10.4: the meeting and appearance producers' work lists are undefined
- Invariant 4 (line 900) requires every pinned version's work list to be empty, but §6.5 names its inputs by publisher ("the Congress.gov meeting JSON and its XML fallback … and the House meeting XML", line 377), not by a computable predicate over `captures`/`readings` (family? URL registry? `xml_root`?). Completion rows (line 210) say "for a response that yields no records" without saying which responses the producer must read; if it is every json/xml body, the "tens of thousands of rows" (line 378) becomes hundreds of thousands of completion rows (125k MODS alone). `appearance_records` from MODS (line 387) and from `witness-list` (F7) have no `meeting_records` rows to share a commit with (line 214).
- Verified: text + data (family counts).
- Fix: in §6.5 add "**Work list:** good-fetched bodies whose `url` matches the meeting-source registry [new row in §7.1's table] with no row at the pinned version"; in §6 line 214 say appearance rows are written in the same commit as the body's reading (xml/json) and that reading is the completion marker.

### F11 — major — §10.16 vs §7.5/§7.9: a legitimate review merge violates "every `version_keys` entry appears on at least two `list` rows"
- `version_keys` (639–641) is one key per edition-ambiguous endpoint holding one of the document's real bodies. Invariant 14 (line 913) permits a review edge to join two different-fingerprint bodies at one endpoint; after that merge, the endpoint's key appears on one row and invariant 16 (line 918) fails the release.
- Verified: text.
- Fix: rewrite the clause in line 918 to "every `version_keys` entry appears on at least two `list` rows, or on one row that a review edge merged", or compute `version_keys` only over endpoints whose real bodies lie in ≥2 listed documents.

### F12 — major — line 784: stray code fence renders §7.11's bullets, all of §8 and the §9 diagram as one code block
- 13 fences in the file (odd). Line 784 opens a block that nothing closes until line 879; a `` ```mermaid `` line cannot close a fence in CommonMark, so lines 785–878 are one literal block in any renderer.
- Verified: text (`/usr/bin/grep -n '^```'`).
- Fix: delete lines 784–785.

### F13 — minor — §6.5 / §7.11: `transcript_jackets list<int>` loses a leading zero that one real package has
- Line 373 types jackets as int; line 753 rebuilds `CHRG-{congress}{h|s}hrg{jacket}`. The index holds `CHRG-118shrg049104057` (1 of 34,576 distinct CHRG packages); jackets are 5, 7, 8 or 9 digits. `packages/congress_api/src/congress_api/models/congress.py:112` already types `jacketNumber: int`, so the code shares the defect.
- Verified: data + code.
- Fix: `transcript_jackets list<string>`, "the jacket digits as the source writes them".

### F14 — minor — §6.4 / §7.11: the `bill_vote_references → roll_call_votes` join is unstated and the listed columns cannot do it
- Line 348 lists `roll_call_votes` columns without `congress`, `session`, `roll_number`; line 778–779 says votes a bill's actions name join "once each" with no key. In the data `vote_id = congress||'-'||chamber||'-'||session||'-'||roll_number` on 30,702/30,702 rows and all 19,766 reference rows join that way.
- Verified: data.
- Fix: at line 349 add "joined on `vote_id = '{congress}-{chamber}-{session}-{roll_number}'`".

### F15 — minor — §6.5 / §7.11: the current-record and witness-precedence rules rank sources the tables do not record
- Line 379 "a House meeting XML record before a Congress.gov one"; line 762 "House meeting XML, then Congress.gov JSON, then MODS". Neither `meeting_records` (358–375) nor `appearance_records` (389–405) has a source column, and `parser_version` alone does not separate the two XML sources.
- Verified: text.
- Fix: add `source dict` (`house_xml`, `congress_json`, `congress_xml`, `mods`) to both tables and order on it.

### F16 — minor — §7.5 / §7.11: "A House meeting ID drops its four-letter prefix (HHRG, HMKP, HMTG)" names an input that does not exist
- Line 669–670. The House XML `meeting-id` attribute (models/house.py:35, 63) and the old catalog's 15,707 distinct `source_meeting_id` values are all digits (0 with a letter prefix). The four-letter codes are `meeting-type` and filename prefixes (`matching/house.py:36`).
- Verified: code + data.
- Fix: delete the sentence, or if it describes a MODS field, name that field.

### F17 — minor — §7.6 / §7.11 / §8.1: three different things are called `members`
- `members` = `(document_id, source_id)` (line 697); `members :=` the spicy-regs member rows (line 772); `members.parquet` = Congress members (line 816). Also "its members' filename readings" (line 681) means §7.6.
- Fix: rename §7.6 to `document_members`.

### F18 — minor — §8.1: `list.filename` and `detail.review_note`/`review_decided_at` have no derivation line
- `filename` orders `list` (line 795) and is its first column (line 826) but §7.5's column list (line 693) never names it; the only hint is line 577 "the document shows the saved file's name" — undefined for a recovery-only document whose saved file is a recovery row. `review_note`/`review_decided_at` (827) are implied by line 732 but not derived from the `hide` record's `note`/`decided_at`.
- Fix: in §7.5's derivation block add `filename := the saved file's effective filename` and `review_note, review_decided_at := the applying hide record's note and decided_at`.

### F19 — minor — §7.5 / §9: `committee_key` is derived and diagrammed but never published, and its input is unspecified
- Line 674 derives `committee_key` "for each committee code" without saying whose codes (saved file's, or the union over members as line 681 does for `measure_keys`). `list` carries only `committee_name` (826); the ER diagram (872) and the §9 prose both route committees by `committee_key`/`system_code`, which no release column holds, so the site cannot reach `committees.parquet` from a document.
- Fix: say "the union over its members' filename readings", and publish `committee_keys List<dict>` beside `committee_name`, or drop the diagram edge.

### F20 — minor — §6 vs §6.5: completion rows require every non-PK column nullable, but the table marks only some
- Line 212 "every non-PK column of that table is nullable"; lines 364–368 mark `congress int`, `title string`, `meeting_date date`, `meeting_type string` as not nullable while `session`, `status` are.
- Fix: mark them nullable in the table.

### F21 — minor — §7.5 vs §7.9: `document_kind` ignores `kind_override`
- `title` (636) includes the override; `document_kind` (682–684) does not, though line 733 says overrides replace the displayed kind.
- Fix: prefix line 682 with "the applying `kind_override`, else".

### F22 — minor — §7.11 / §8.1: `videos.has_captions` names no column to join on
- Lines 769–771 say captions are found "under the player's filename" or "named by the video ID" but no lake column carries a caption body's player filename or video ID.
- Fix: name the join: the caption source file's `filename_readings` field (which) or a capture `url` pattern in a registry.

### F23 — minor — §7.3 / §6.5: the Congress.gov "XML fallback" would be classified `document`
- `api_row := format = 'json' and …` (525); an XML response from the same API endpoint takes the `source_record`/`listing`/`document` path. No `format=xml` API URL exists in the 10-02 index (0 of 822 api.congress.gov URLs), so harmless today.
- Fix: `api_row := format in ('json','xml') and c.url matches the API-endpoint registry`.

### F24 — minor — §8.1: type mismatches against the inputs
- `rosters.rank int16` (817): spicy-regs `rank` is a string, numeric on 2,523 of 2,973 rows. `members.terms.chamber dict` from `term_type` `rep`/`sen` with no mapping; `members.name` from `name_first`/`name_last` with no join rule; `detail.govinfo_package_id string` (827) not marked nullable though line 678–680 can yield none; `recoveries.identity_note string` not nullable though it comes from a decision that may be absent; `sittings.place` (813) from `room, building, address` with no concatenation rule; `facts` "dates as YYYY-MM-DD" (827) without naming which fold fields are dates.
- Verified: data for `rank` and `term_type`.
- Fix: state each cast or mapping once where the column is derived.

### F25 — minor — §6.4: `congress_bills.subjects` is read but no release column uses it
- Line 346 vs `bills.parquet` (818). Either publish it or drop it from the read set (line 352 says a change in read columns fails the publish, so reading unused columns adds a failure mode for nothing).

### F26 — nit — cross-references and wording
- Line 73: "fingerprint candidate … (§7.3)" — §7.3 does not define it; §6.2 uses it. Point to §6.2 or define it there.
- Line 885: "`sha256` for readings, committee and meeting records" — there are no committee records in the lake.
- Line 828 "a document's ID … stay in the lake" contradicts line 412 "relations exist only inside the job"; `document_id` is persisted nowhere.
- Line 809 "measured with F0" is unexplained in this document.
- Line 578/739: `is_saved` is "the saved file's address" but a saved archive-member source file may have several paths; say "each of its addresses" or "its first by `(url, member_path)`".
- 16 of 422,011 `congress_bills.bill_id` do not match `^\d+-[a-z]+-\d+$` (e.g. type `cen_doc_h`); `measure_keys` will never name them, fine, but line 346's "keyed `{congress}-{type}-{number}`" is not quite total.

## 3. Checked and found sound

- Every ARCHITECTURE citation (§2, §3, §7.1, §8, §8.2, §8.6, §9.1, §10.3.1, §10.3.7) resolves to a section with the cited content (headings listed; §7.1 and §8.2 read).
- All internal § cross-references except line 73 point where they say.
- `source_id`, `document_id`, `link_key` (body and URL), `version_keys`, `url_key`: each defined exactly once, deterministic, with explicit null handling; `copy_urls`, `same_body`, `same_text`, `same_rendition` have deterministic node definitions; `saved-file order`, `recovery order`, `list` order, `sources.ordinal`, `url_state` winner, `reviews` latest-record all end in a total tiebreak.
- Invariants 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20 follow from the derivations as written (14 checked by chasing same_text/same_rendition transitivity: equal-fingerprint chains cannot meet a different fingerprint, and `edition_bodies` blocks rendition groups).
- The `congress.gov/<congress>/meeting/<chamber>/<eventId>/` pattern is real (28,424 distinct index URLs, e.g. `www.congress.gov/117/meeting/house/112782/documents/…`); `docs.house.gov/meetings/<C>/<SC>/<date>/<eventId>/` is real (88,500).
- §5.2's "123 older import lines say `publisher_requested` true": exactly 123 in the local receipts.
- §7.3 placeholder threshold: k=100 selects 13 bodies on the 10-02 snapshot (doc: 18 on 10-19), widest 86,455 URLs (doc: 87,161); same shape, older snapshot.
- Reference inputs: all nine tables exist in `publication.v2.json`; every column §6.4 names exists in the pinned files; `congress_bills.bill_id` is `{congress}-{type}-{number}` lowercase (421,995/422,011), min congress 6; `committee_assignments` is the 119th only; `nominations` is the 119th only (2,287 rows); `members` 12,770 rows from 1789-03-04; `committees.history` carries `officialName`/`startDate`/`endDate`; `hsag03` and `hlig00` exist as system codes; House votes from the 101st, Senate from the 108th, as line 348 says.
- `url_state`/queue/credential rules (§7.2, §7.7, inv 12) are mutually consistent; `hide` semantics (§7.9, inv 15, manifest facet counts) are consistent.

## 4. Could not check, and why

- Counts tied to the 2026-10-19 snapshot (line counts, 34,196 GovInfo ZIPs, 1,683,430 source files, 3,690/11,792 recovery bodies): the local index is 2026-10-02 and has no GovInfo ZIP family at all (0 URLs matching `/zip` or `.zip`), so the ZIP rendition claims in §7.2/§7.5 are unverifiable here. My recovery-body overlap count (151,378 of 222,849 `retained-file` sha256s also on a 2xx fetched row) uses the index's broader `retained-file` kind, not the doc's "capture row of a `retained_import` line", so it cannot confirm or refute 3,690/11,792.
- Provenance records (`recoveries`, `url_variants`, `reviews`, `verification`): not in the local cache, so invariants 2 and 3 (verification records for every older body, cleaned-receipt records) and the F6 count of decisions are unchecked.
- Registries (file shapes, error words, publisher kinds, committee codes, …) do not exist yet, so `real_files`' `file_shaped` behavior on GovInfo `.htm` members and the `source-record roots` treatment of House `committee-meeting` XML (which otherwise takes role `document` and becomes a listed document) are unverifiable; I note the latter as a risk, not a finding.
- The engine's own semantics (DataFusion `IS NOT DISTINCT FROM`, ConnectedComponents determinism) were taken as given.
- Blind spots of my checks: URL-pattern counts use my regexes, which encode the doc's shapes; the receipts scan skipped list-valued top-level records (the `assemble-*` files); spicy-regs checks are one generation (the current one) and one direction (doc columns ⊂ table columns), so an extra column the doc should read would not show.
