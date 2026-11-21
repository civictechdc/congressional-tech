# DocMeta gold data contract (docmeta-gold-contract/2, 2026-11-18)

**Bottom line.** One command, `gold_contract.py check`, validates training and test labels the same way before
anything trains or scores on them. It runs 81 rules in three layers (label, text, dataset). Any `error` failure exits 1,
and the trainer and scorer must then refuse the data; `warn` rules are reported only. Version 2 encodes the owner's
governing rule: **the source text is the source of truth.** Every fact a label records (Congress, chamber, committees,
dates, titles, organisations, places, programs, people and their organisation, title and address, refs) must be
stated in the training text; the filename, upload slot, `known` hint, rosters and memory never supply a value. All
labels live in one file, `../ssot/docmeta_gold_v6_5.jsonl`, sealed by `../ssot/MANIFEST.json`; values taken out of the
labels are kept beside them in each SSOT row's `signal` list.

Why version 2: the governing rule (P01 to P17; T01 to T03 now read the training text only; T04 replaces L24), the
D06 split into re-posts (error) and template siblings (warn), D15 (nothing inferred silently dropped), T05 (a Congress
named only in passing), and the text-decided T15, T18a/b, T22 and T23. The rule-list hash changed, so every SSOT must
be resealed.

## Files

| File | What it is |
|---|---|
| `docmeta_gold_conventions.schema.json` | JSON Schema 2020-12 overlay on `docmeta_v4_causal.schema.json`: the conventions decidable from the label alone. Each `$defs` key is a rule id, with `x-severity`, `$comment` (the rubric sentence) and `x-blind`. |
| `gold_contract.py` | `check`, `rules`, `build-ssot`, `seal`, `verify-manifest`, `export`, `summary`. Rules are data: `SHAPE_RULES`, `TEXT_RULES`, `FACT_RULES` (from `FACT_FIELDS`), `KIND_TEMPLATES`, `DATASET_RULES` and the overlay's `$defs`. |
| `baseline_raw_report.json`, `baseline_raw/` | Check of the labels as written: old gold 3,077 + gap-fill train 418 + gap-fill test 182. `failing/<rule>.tsv` lists failing link keys with the reason. The report's `provenance` section is the stated-in-text table. |
| `normalized_report.json`, `normalized/` | Check of the normaliser's `gold_v6_5n_*` files with `--signal gold_v6_5n_signal.jsonl` (inputs and sha256 in the report). |
| `../ssot/` | The single source of truth, `MANIFEST.json`, `ssot_report.json`, `check/failing/`. Not sealed this round (see Normalised data). |

Working notes, blind-read packets and the queue scan: `fast-gemma4/artifacts/gap_swarm_20261118/C2_contract/`.

## How to run (always with the congressional-tech venv Python)

```
PY=.venv/bin/python
C="-m congress_docmeta.gold_v65.gold_contract"
$PY $C check --input OLD.jsonl=auto_v64 --input GAP_TRAIN.jsonl=train --input GAP_TEST.jsonl=test_gapfill \
       [--input EXCLUDED.jsonl=excluded] [--signal gold_v6_5n_signal.jsonl] --out-dir OUT --json OUT/report.json
$PY $C rules                                       # the rule table below, from the code
$PY $C build-ssot                                  # SSOT from the normaliser's files + signal + val48/docs8, then seal
$PY $C seal                                        # after any SSOT edit: re-check, rewrite MANIFEST.json
$PY $C verify-manifest [--exports DIR]             # exit 1 unless the SSOT (and exports) match a PASSING manifest
$PY $C export --out-dir DIR [--compare-dir ../lookups_and_gold]
$PY $C summary                                     # rows per split by kind; per split by format, Congress, committee
```

How inputs are read:
- `=auto_v64` splits the old gold by `heldout_v6_4_183_link_keys.json`; a file with no `=SPLIT` takes each row's `split`.
- Rows in `excluded` (and the blind splits under `--warn-only-split`) are always reported and never block.
- The training text is the text `parse_gold_rows` builds: the production queue row through the runner's own
  `_build_precomputed_context_from_queue_row` (`p12_raw_text`, else `p12_clean_text`), else the row's own prompt.
- **DocMeta code.** DocMeta moved from the legacy inference package (`congress_docmeta`, trainer helpers in
  `congress_docmeta.gold`) into `packages/congress_docmeta` on `main`, with `personas` raised to 26
  (`congress_docmeta.schema_v4.MAX_PERSONAS`, `docmeta_v4_causal.schema.json` personas `maxItems` 26). The commit, branch,
  and people limit read are recorded in every report and in `MANIFEST.json` (`docmeta`). No contract rule restates the
  people limit: the shape validators (L00), the compact round trip (L01) and the gold gate read it from the schema.
- One check of 3,677 rows takes about 50 s on the CPU, 2.6 GB peak RSS (measured); the queue read is a DuckDB
  semi-join capped at 4 GB.

## Rule of use

1. Labels change only by editing `ssot/docmeta_gold_v6_5.jsonl` through a script that ends with `gold_contract.py
   seal`. Seal reruns `check` and rewrites `MANIFEST.json` (SSOT sha256; rows per split and kind; contract version,
   rule-list hash and contract code hash; input hashes, the signal sidecar included; the check result).
2. Training and scoring read only the files `export` writes, and only after `verify-manifest --exports DIR` exits 0.
   `export` strips the SSOT fields (`split`, `excluded_reason`, `source_batch`, `label_sha256`, `seen_template`,
   `signal`), so exports are row-for-row the normaliser's files.
3. A new or changed rule changes the rule-list hash, so every SSOT must be resealed. Say why in the same change.
4. **Blind sets stay warn-only.** `blind_val48` and `blind_docs8` are checked and reported, never blocking, and their
   labels are not changed here. They feed the model a `known` string in the order congress, chambers, cmt, date,
   which production never sends (production: congress, cmt, chambers, date; D07). Their scores therefore measure a
   prompt production does not use: decide on the queue-path sets (`heldout_v6_4`, `test_gapfill`).

5. **Waivers for rows a person has read and ruled on**: `adjudications.jsonl` beside this file, one JSON object per
   line with `link_key_hex`, `rule`, `verdict` (`label_stands`), `quote` (the document's words that justify the label),
   `ruled_by`, `ruled_at`. `check` reports a waived failure under the rule's `waived` list and never counts it as
   blocking; a ruling whose quote is not in the row's training text is refused and the failure still blocks; malformed
   lines are reported. `seal` records the file's sha256 and the number of rulings and waivers in `MANIFEST.json`, so
   editing the file needs a reseal. For genuine judgment calls only: a rule that is wrong in general is fixed, not
   waived. The file starts empty.
6. **Expected held-out exclusions** are reported, not blocking: the two `[EMPTY_BODY]` placeholders the normaliser
   drops (`46c1a6df1a2bcb4e`, `ae06868f6de3d647`) and the duplicate error page `85afe0532f6c8e0b`, which every `check`
   (not only the SSOT build) now treats as excluded with its reason, so D05 and D06a pass. The report lists them
   under `expected_exclusions`.

SSOT row format: the gold row format, plus `split` (`train`, `heldout_v6_4`, `test_gapfill`, `blind_val48`,
`blind_docs8`, `excluded`), `excluded_reason`, `source_batch`, `label_sha256`, `seen_template` (test rows whose nearest
training sibling is a template or edition, D06b) and `signal` (the normaliser's sidecar entries for the row: field,
value, source, rule, kept_as, persona). The held-out error page `85afe0532f6c8e0b` (identical to training row
`a3002f39e37a6384`) goes to `excluded` at build time with its reason (`SSOT_EXCLUSIONS`).

## The governing rule: how "stated in the text" is decided

Each fact is classified by where it occurs, first hit wins; only `text` passes (`unchecked` is not judged):
`text` (the training text) / `window` (only the reviewer's own prompt text) / `known` (only the hint) / `filename` /
`derived` (only follows from something stated: a Congress from a year; a chamber from a committee that exists in one
chamber; for committees, the committee named but the chamber in the label's name not stated) / `none` / `unchecked`
(chamber `executive_or_external`, which names no chamber; facts of a text mostly in a non-Latin script, whose labels
translate it). Judgment fields (`status`, kinds, `text_quality`, roles, `gist`, `topics`, `composed_title`,
`event_type`, `correspondence_flow`) are conclusions about the text and are not checked.

**Interpret, do not invent: how the contract tells them apart.** An error rule in the text layer fails a value only
when the contract finds no basis for it in the document's words. A value a careful reader would conclude from the
text passes. That covers facts read through scan damage ("117h Congress", "Cassicdog", "4:14.ll", "Raybum"), informal
or abbreviated names (acronyms either way: "EPW", "HSGAC", an organisation's distinctive words), a chamber made evident
by a building, a member's title or a roll column, and a title pieced together from the document's own heading and
bill list. The basis must be **this document's words**: a value found only in the filename, the `known` hint, a
roster, or worked out from a date fails. The rules where the contract cannot tell interpretation from invention
reliably are `warn`: the phrase fields, partly composed titles (P09b), passing mentions (T05) and unreadable text
(T07). What it cannot tell: a reader's inference that needs domain knowledge the words only hint at ("Chairman Rubio"
implying the Senate; the House "Offered by Mr. X of State" amendment form); a value whose words occur in the text
but about something else (a "Ways and Means" mention in a biography, guarded only by requiring the word
"committee" beside it); and font-cipher or non-Latin text, whose facts are not judged at all (T07 lists them).

**"Stated" means evident from the document's own words to a careful reader** (owner, 2026-11-18, rubric governing
paragraph): it includes what the text makes plain without saying it outright, and excludes anything that needs a
calculation or an outside lookup. How each match is made (folded text: lower case, accents, ligatures and
zero-width characters removed):
- **Congress**: an ordinal ("118th Congress", "118th Cong.", congress.gov's "118th-congress", "116th United States
  Congress", scan damage "117h", "117\"", "115t", "1i2th", "114*h"), the number in words ("One Hundred Eighteenth
  Congress"; words misread within two edits: "ONE HUNDRED FIFTHTEENTH CONGRESS"), or a printed designator of the
  document (Serial No./Rept./Hrg./Doc./Print 118-NN, "S. HR9. 106-344", GovInfo ids BILLS-/CHRG-/CRPT-/HHRG-118). A
  year never states it (a calculation); a public-law number says when a law passed, not when this document was made;
  "congressional" never matches.
- **Chamber** (evident to a careful reader): "House of Representatives", "United States Senate", "U.S. House/Senate";
  a committee name carrying the chamber ("House Committee on", "Senate Finance Committee", "H. Comm. on") **or a
  committee or subcommittee that exists in one chamber only** (production's committee table and the roster's
  subcommittee table; the committee word must sit beside the name, so "Foreign Affairs magazine" does not count; usual
  acronyms EPW, SFRC, SSCI, SASC, HSGAC, HASC, HFAC, HPSCI); a House or Senate office building or room code in a
  location line (Rayburn, Longworth, Cannon, "2123 RHOB", HVC-210; Dirksen, Hart, Russell, "SD-366"); the committee's
  own site (x.house.gov, x.senate.gov); a standalone "SENATE" / "HOUSE OF REPRESENTATIVES" header line; "Rep.",
  "Representative", "Congressman", "Senator" before a member's name in the head, or before "... presiding"; a roll
  sheet with a Representative or Senator column; "S. Hrg.", "H./S. Rept.", "Congressional Record—House", report and
  treaty mastheads ("To the Senate of the United States", "the Senate advises and consents"); prose about this
  proceeding ("the full Senate", "reported ... to the House", "the House floor"). Committee amendments: "AMENDMENT TO H.R. ... OFFERED BY MR. X OF
  STATE" makes the House evident; "IN THE SENATE OF THE UNITED STATES", "AMENDMENT NO." or "Calendar No." (not Union or
  House Calendar) the Senate. Also: "Senators who are members of this committee", "JUDICIARY (SENATE)", a scanned
  "Dirksen Senate Ofice Building" or "Houxe of Representatiues", a two-word one-chamber subcommittee in the heading
  ("Workforce Protections Subcommittee"), and a witness thanking the senator who invited them. `joint`: a joint committee, or a
  text that states both chambers. Look-alikes refused: "the White House", a state legislature ("Georgia State
  Senate", a state "Senate Bill 12"), a career line ("after 28 years in the United States Senate", a staff or intern
  post), a member who employs the witness ("chief of staff to Senator X"), a bill merely cited.
- **Committees**: the core name (production's own committee table, so any era name of the same committee counts),
  as "Committee on X" or "X Committee" (one-word cores need "committee" or "subcommittee" within three words), all
  core words close together (OCR tolerant), or the chamber's short form ("Senate Commerce Committee"). A chamber
  written into the label's name must itself be evident (chamber rule; a one-chamber committee makes its own chamber
  evident, so "House Committee on Ways and Means" is stated by "Committee on Ways and Means").
- **Subcommittees**: the same, with "subcommittee"; an Appropriations "and Related Agencies" tail is optional; the
  short form "Financial Services Subcommittee" counts.
- **Dates**: any written format: "March 20, 2017", "Mar. 20th, 2017", "20 March 2017", "the 20th day of March, 2017",
  inside a range ("March 19-20, 2017"), "3/20/2017", "03.20.17", "3\20\17", "2017-03-20", "20170320", one OCR-misread
  letter of the month or digit of the year when the rest is exact, or "March 20" with the year elsewhere in the text.
  YYYY-MM: "March 2017" or any date in that month. YYYY: the year.
- **Phrases** (titles, organisations, places, programs, person title and organisation): the content words close
  together (span 2 x length + 4 positions), allowing one missing word in six (one in four for titles), with '&'/'and',
  U.S./United States, state names and codes, plurals and common abbreviations folded, OCR one-edit and run-in forms
  ("titleoversight", "Global Foundries"), spaced-letter OCR ("K U R T"); or the value's acronym (GAO, DOD, USAID, a
  parenthetical "(SNAP)"), the text spelling out the value's acronym (AASHTO), or an organisation's distinctive words
  ("Heritage" for The Heritage Foundation; Department, Office, Agency, Bureau stay required). Values are split on ';',
  '|' (and ',' for names and places, ':' and dashes for titles); every part must be stated. "Nominee to be" is the
  reviewer's role wording and is not required.
- **Addresses and contacts**: emails as written, phone numbers by their last ten digits, the rest as a phrase.
- **Event titles** (P09 error / P09b warn): stated when the words sit together (one missing in four for OCR), when
  all the words are in the text (a title assembled from the text's own heading and bill list), or when a form field
  cut the title mid-word ("Examining Local Needs in Di"). A failing title with at least 60% of its words in the text
  is a partly composed title (P09b, warn); fewer is P09 (error).
- **Names** (T01, T02): every token, read through scan damage the way a person would (one edit for 5+ letters; or
  the same first letter, length within three and similarity 0.7: "Cassicdog" is Cassidy, "Thonspion" is Thompson,
  "Alsobrodkos" is Alsobrooks). **T06**: a name written as an initial and a surname ("E. Cummings") needs that
  initial beside the surname in the text. **Refs** (T03): as in version 1; the filename grounds nothing.
- **Dates in one place** (T04, rubric "Dates"): a doc_date equal to event_date passes only when the text marks the
  date as the document's own: after "Dated", "Adopted", "Approved", "Submitted", "Issued", "Released", "Revised",
  "As of" (with or without "on"; "Date:" is not a mark, it heads the event date on vote sheets and forms); within 120
  characters after a release header; on a release page (press-release or share-bar cues in the head) in the head or
  after a Washington dateline; a letter's date line (a salutation within 400 characters after it); a JCX number
  beside it; a date line of its own only for documents not tied to an event. An event-tied document (event_type,
  event_title or an event kind) whose only printed date sits in doc_date with no event_date also fails. **D16**: a
  date the text states and the original label carried stays in doc_date or event_date.
- **Party, state and venue** (T08, T09, T09b; an independent 40-document review found these invented): a person's
  `party_state` needs its party and state in the text within 120 characters of the person's surname ("(R-GA)",
  "R-Ga.", "Republican of Georgia"); a `venue` needs every room number it carries in the text and at least one of its
  place words; a `venue_kind` beside a failing venue restates it and fails too.
- **Readability** (T07, warn): rows mostly in a non-Latin script, or whose first 9,000 characters are under 50%
  word-shaped (font cipher, garbled scans) are listed for a person to read. Owner, 2026-11-18: garbled or non-English
  text is interpreted, not skipped ("interpretation is not hallucination"), so every rule judges these rows; where the
  label stands after a person read the document, the ruling goes in `adjudications.jsonl`, and on these rows (only) the
  ruling may quote the reader's reason, since the matchers cannot read the words.
- **Biographies**: `witness_biography` is the kind for any biography or CV, with or without a hearing; no rule flags a
  biography's kind for lacking one (T04 treats a biography's single printed date as the event date only when the
  label ties it to an event).
- **Transcripts list their witnesses** (T24, error): every person `transcript_witness_additions.jsonl` lists for a
  transcript is in its label as a witness, matched by surname; the rule reports "not run" until that file exists.

**Masthead versus mention (T05, warn).** "Stated in the text" must mean the document's own value. For Congress the
contract tells them apart by place and context: a mention is passing when it sits inside site navigation (a
schedule or archive menu, or three or more different Congresses within 200 characters), inside a link, after
"introduced/passed/enacted/during ... the", or past the first 1,500 characters; a document number (Serial No.,
H. Rept., BILLS-118) outside a link is own. T05 warns when a label's Congress occurs only in passing. What it cannot
tell: a masthead that belongs to an attached older document (an old letterhead counts as own, which it is for that
letter, not for the hearing it was filed under); a header past 1,500 characters of site chrome; a quoted title
inside the head. Dates and chambers are not judged by T05: a document's own date or chamber also sits late in the text
("Adopted: April 10, 2019", report footers, contact blocks), so position cannot separate them from mentions (read:
of 8 T05 hits on dates and chambers, most were the document's own values).

**Verification of the matchers.** Failing values were read blind (the readers saw the training text and the value,
never the verdict, with passing values mixed in as controls) by Haiku readers in three rounds: round 1, 20 per field
over all fields; round 2, 20 fresh values per field after fixes; round 3, 20 fresh values for the core fields after
further fixes. Every disagreement was checked against the text by me: reader quotes were verified to exist (one
reader quote was fabricated: "Ranking Member Dan Lipinski" is not in that document). A field whose matcher stayed
under 95% correct is `warn`, so no error rule demands removing a stated fact.

## Rule table (output of `gold_contract.py rules`)

| id | layer | severity | checks | cannot see |
|---|---|---|---|---|
| L00_shape | label | error | validate_docmeta_v4 / strict_validate_v4 pass and the label equals canonicalize_docmeta_v4(label). | Values that are in-domain but wrong. |
| L01_compact_roundtrip | label | error | encode_v4_to_compact_v6 -> expand_compact_json_str_to_v4 returns the label unchanged, less refs and fiscal_years, which the wire omits by design (post_pass_v6 adds them). | Whether the compact form is what production decodes (only that the round trip is lossless). |
| L02_title_gist_caps | label | error | The gold gate's caps on composed_title and gist (usable labels). | Whether title and gist are grounded. |
| L10_nonusable_no_kind | label | error | A status other than usable carries no primary_kind and no secondary_kinds. | Whether the status itself is right. |
| L11_usable_has_kind_and_tail | label | error | A usable label has primary_kind, composed_title, gist and topics. | Whether the kind, title, gist and topics are right. |
| L12_error_status_triage_only | label | error | error_or_block, stub_or_blank and ocr_unreadable carry exactly status, text_quality and error_reason. | Whether the triage status is right. |
| L13_error_reason_only_on_error_status | label | error | error_reason appears only with the three triage statuses. | Whether the status is right. |
| L14_secondary_not_primary | label | error | secondary_kinds has no repeats and never repeats primary_kind. | Whether a secondary kind is right. |
| L20_grid_kinds_no_chair_or_ranking | label | error | committee_vote and attendance_quorum_sheet list no person with role chair or ranking_member. | Grid people under other roles (L21); a chair named outside the grid as offeror or sponsor is allowed under that role only. |
| L21_grid_kinds_only_offeror_or_sponsor | label | warn | On committee_vote and attendance_quorum_sheet every listed person is an amendment_offeror, sponsor or cosponsor. | Whether a listed offeror or sponsor was read off the grid. |
| L22_letters_functional_roles | label | error | On the five kinds that are letters by form (oversight, external submission, nomination or support, witness invitation, QFR request) no person has an office role (chair, ranking_member, presiding). qfr_response and public_comment_or_submission may (coordinator decision 2026-11-18). | Whether sender, signatory and recipient are assigned right; letters labeled with a non-letter kind; office roles on qfr_response and public_comment_or_submission (allowed by decision). |
| L23_correspondence_flow_letters_only | label | error | correspondence_flow appears only when primary_kind is one of the seven letter kinds. | Whether the flow value is right; read strictly on primary_kind, so packets and filings whose secondary kind is a letter fail. |
| L25_date_formats | label | error | doc_date is YYYY-MM-DD, YYYY-MM or YYYY (YYYY reported by L25b); event_date and due_date are YYYY-MM-DD (valid month and day numbers). | Whether the date is the right one. |
| L25b_year_only_doc_date | label | warn | doc_date is not year-only (warn: allowed when the text gives only a year). | Whether the text gives more than a year. |
| L26_ref_prefixes | label | error | Every ref starts with one of the rubric's prefixes followed by a non-empty value. | Whether the ref value is right or shown (T03 checks its numbers against the text). |
| L27_subcommittee_roster_spelling | label | error | No subcommittee name contains '&' or starts with 'the '. | Oxford-comma and other spelling variants (D13); whether the name is the roster name. |
| L28_committee_names_not_codes | label | error | No committee or subcommittee is a bare system code such as hsif14. | Codes of other shapes. |
| L29_person_name_no_honorific | label | error | No person name starts with an honorific or office title. | Honorifics or titles after the first word. |
| L30_disclosure_only_on_disclosures | label | warn | disclosure appears only on truth_in_testimony_disclosure (warn: the rubric also allows other disclosure forms). | Other disclosure forms the rubric allows, hence warn. |
| L31_jct_description_fields | label | error | A section_by_section label issued by or filed under JCT has issuer_org Joint Committee on Taxation; when it lists Ways and Means the chamber is house, when it lists Finance the chamber is senate. | JCT descriptions labeled with another kind (T10 reports those); a marking-up committee written another way (Committee on Ways and Means without the chamber); whether the committee is the one marking up. |
| T01_name_tokens_in_text | text | error | Every token of every person's name (first, middle, suffix) occurs as a word in the training text (one OCR edit allowed on 5+ letter tokens; adjacent words run together count). The filename does not ground a name. | Text cut by the trainer's token cap; a token found elsewhere in the text (common first names, single initials) or one edit from another word passes; organizations are P15's. |
| T02_person_named_in_text | text | error | At least one token of two or more letters of each person's name occurs in the training text (not the filename); the failure names where the name does occur. | OCR damage beyond one edit (Sco,, for Scott) looks absent; a surname that occurs for another reason passes. |
| T03_ref_numbers_in_text | text | error | Every identifying digit group (2+ digits; an act's year excluded; usc: section and fr: page only; date-form ids skipped) of every ref occurs in the training text, whitespace removed (not the filename). | Refs with no 2-digit group (names, Roman-numeral rules); a group found inside another number or in an unrelated place passes; refs are not trained (the wire omits them), so this guards scoring only. |
| T04_date_in_one_place | text | error | A doc_date equal to event_date passes only when the text marks that date as the document's own (after a dating word incl. Adopted:/Submitted:; within 120 characters after a release header; on a release page in the head or after a Washington dateline; a letter's date line with a salutation after it; a date line of its own away from event words; beside a JCX number). A doc_date with no event_date fails when the document is event-tied (event_type, event_title or an event kind), prints exactly one full date, and does not mark it as its own. | Own-date marks in other words; event ties the label does not record; documents whose single printed date is a print stamp. |
| T06_initial_beside_surname | text | error | A person named as one initial and a surname has that initial as one of the two words before the surname somewhere in the text (the surname matched exactly or one edit away). | Initials after the surname; surnames the text lacks (T02 reports those). |
| T08_party_state_basis | text | error | Every person's party_state has its party and state in the text within 120 characters of the person's surname ("(R-GA)", "R-Ga.", "[R-GA-1]", "Republican of Georgia", "Georgia (R)"); a state-only value needs the state there. Anywhere in the text when the surname is not found. | Party and state written apart from the name by more than 120 characters (a roster table); a state abbreviation that is also a word. |
| T09_venue_basis | text | error | The venue's room numbers (2+ digit groups) all occur in the text, whitespace removed, and at least one of its place words (building, city, 'virtual'; OCR and scan damage tolerated) does. | A room number printed in another form ('Rm. 2-123'); a venue whose words are all generic. |
| T09b_venue_kind_basis | text | error | A label with venue_kind is on a text that gives a place or mode for the event: a room or room code (Room 2123, SD-366, HVC-210, 2123 RHOB), a House or Senate office building or the Capitol, a 'Location:' or 'held at/in' line, 'virtual', 'remote', 'Webex', 'Zoom', 'online', 'videoconference', or 'field hearing'. | Whether the kind matches the place (a virtual cue beside a capitol_room kind passes); places written without these words. |
| T24_transcript_witnesses_listed | text | error | Every person `transcript_witness_additions.jsonl` (a dedicated, quote-verified pass over the transcripts) lists for a transcript is in that transcript's label with role witness, matched by surname. Not run while the file is missing. | Witnesses the pass did not find; two witnesses sharing a surname. |
| T07_readable_text | text | warn | The text is not mostly non-Latin, and at least 50% of the first 9,000 characters' words (3+ letters) are word-shaped (lower, Capitalized or UPPER case, a vowel, no five-consonant run). | Readable text in another alphabet (counted unreadable here and listed as non-Latin); garble that happens to be word-shaped. |
| T05_value_only_in_passing_mention | text | warn | The label's congress is named only in passing, never as the document's own. A mention is passing when it sits inside site navigation (a schedule or archive menu, or three or more different Congresses within 200 characters), inside a link, after 'introduced/passed/enacted/during ... the', or past the first 1500 characters; a document number (Serial No., H. Rept., S. Hrg., BILLS-118) outside a link is own. | A masthead that belongs to an attached older document (its letterhead counts as own, which it is for that document); a header past 1,500 characters of site chrome; a quoted title inside the first 1,500 characters; dates and chambers (position cannot tell their mastheads from mentions: 'Adopted:' lines, footers). |
| P01_congress_stated | text | error | Every congress value is stated in the training text: ordinal ('118th Congress', '118th Cong.', '118th-congress'; scan damage '117h', '1i2th'), words ('One Hundred Eighteenth Congress'; misread words within two edits: 'FIFTHTEENTH'), or a printed designator of the document (Serial No./Rept./Hrg./Doc./Print 118-NN, 'S. HR9. 106-344', BILLS-/CHRG-/CRPT-/HHRG-118). A year never states it; a public-law number does not. The failure names where the value does occur (window, known, filename, derived, none). | Whether the stated Congress is the document's (a text naming two Congresses passes either); public law numbers are left out on purpose. |
| P02_chamber_stated | text | error | Every chamber value is stated in the training text: evident to a careful reader (owner 2026-11-18): 'House of Representatives' / 'United States Senate' / 'U.S. House\|Senate'; a committee name carrying the chamber or existing in one chamber only (Ways and Means, Finance); a House or Senate office building or room code (Rayburn, 2123 RHOB, SD-366); the committee's site (x.house.gov); a standalone SENATE header; 'Rep.'/'Senator' before a member's name in the head or 'presiding'; a Representative or Senator roll column; 'the full Senate', 'reported ... to the House'; S. Hrg., H./S. Rept. Look-alikes refused: the White House, a state legislature or state bill, a career line, a member who employs the witness. joint: a joint committee or both chambers; commission: 'Commission'. executive_or_external names no chamber and is not checked. The failure names where the value does occur (window, known, filename, derived, none). | A member title or office building that is a look-alike in other words; a chamber stated only past the head by a member title. |
| P03_committees_stated | text | error | Every committees value is stated in the training text: the core name (production's committee table, any era name of the same committee) as 'Committee on X' / 'X Committee' (one-word cores need 'committee' within three words), its words close together; a chamber in the label's name must itself be stated (chamber rule). The failure names where the value does occur (window, known, filename, derived, none). | Acronyms (HELP, HSGAC) and short forms ('Senate Commerce Committee') fail; a name stated in another role (a cited committee) passes. |
| P04_subcommittees_stated | text | error | Every subcommittees value is stated in the training text: the core name with 'subcommittee' within three words for one-word cores ('Subcommittee on Health', 'Health Subcommittee'), else all words close together. The failure names where the value does occur (window, known, filename, derived, none). | Whether the stated subcommittee is the document's; renamed subcommittees. |
| P05_doc_date_stated | text | error | Every doc date value is stated in the training text: any written format: 'March 20, 2017', 'Mar. 20th, 2017', '20 March 2017', '20th day of March, 2017', inside a range ('March 19-20, 2017'), '3/20/2017', '03.20.17', '2017-03-20', '20170320', or 'March 20' with the year written elsewhere; YYYY-MM by 'March 2017' or any date in that month; YYYY by the year. The failure names where the value does occur (window, known, filename, derived, none). | Whether the stated date is the document's (see T04 for echoes of the event date). |
| P06_event_date_stated | text | error | Every event date value is stated in the training text: any written format: 'March 20, 2017', 'Mar. 20th, 2017', '20 March 2017', '20th day of March, 2017', inside a range ('March 19-20, 2017'), '3/20/2017', '03.20.17', '2017-03-20', '20170320', or 'March 20' with the year written elsewhere; YYYY-MM by 'March 2017' or any date in that month; YYYY by the year. The failure names where the value does occur (window, known, filename, derived, none). | Whether the stated date is the document's (see T04 for echoes of the event date). |
| P07_due_date_stated | text | error | Every due date value is stated in the training text: any written format: 'March 20, 2017', 'Mar. 20th, 2017', '20 March 2017', '20th day of March, 2017', inside a range ('March 19-20, 2017'), '3/20/2017', '03.20.17', '2017-03-20', '20170320', or 'March 20' with the year written elsewhere; YYYY-MM by 'March 2017' or any date in that month; YYYY by the year. The failure names where the value does occur (window, known, filename, derived, none). | Whether the stated date is the document's (see T04 for echoes of the event date). |
| P08_date_spans_verbatim | text | warn | Every date spans value is stated in the training text: the span itself, case and whitespace ignored (spans are verbatim by definition). The failure names where the value does occur (window, known, filename, derived, none). | OCR spacing inside digits. |
| P09_event_title_stated | text | error | Every event title value is stated in the training text: its content words (case, punctuation, '&'/'and', U.S./US, state names and common abbreviations folded) close together in the text; one word in six may be missing (OCR). The failure names where the value does occur (window, known, filename, derived, none). | A title stated in pieces far apart; paraphrases close to the text pass. |
| P09b_event_title_partly_composed | text | warn | An event title that fails P09's stated test but has at least 60% of its words in the text (a title partly composed by the reviewer). | Whether the missing words are paraphrase or OCR damage. |
| P10_verbatim_title_stated | text | warn | Every verbatim title value is stated in the training text: its content words (case, punctuation, '&'/'and', U.S./US, state names and common abbreviations folded) close together in the text; one word in six may be missing (OCR). The failure names where the value does occur (window, known, filename, derived, none). | A title stated in pieces far apart; paraphrases close to the text pass. |
| P11_issuer_org_stated | text | warn | Every issuer org value is stated in the training text: as event_title, or the name's acronym (GAO, DOD, HHS, a parenthetical '(SNAP)') as an upper-case word; committee names by the committee rule. The failure names where the value does occur (window, known, filename, derived, none). | An organization named only by a short form other than its initials (the VA, the Fed). |
| P12_orgs_mentioned_stated | text | warn | Every orgs mentioned value is stated in the training text: as event_title, or the name's acronym (GAO, DOD, HHS, a parenthetical '(SNAP)') as an upper-case word; committee names by the committee rule. The failure names where the value does occur (window, known, filename, derived, none). | An organization named only by a short form other than its initials (the VA, the Fed). |
| P13_places_stated | text | warn | Every places value is stated in the training text: its content words (case, punctuation, '&'/'and', U.S./US, state names and common abbreviations folded) close together in the text; one word in six may be missing (OCR). The failure names where the value does occur (window, known, filename, derived, none). | A title stated in pieces far apart; paraphrases close to the text pass. |
| P14_programs_stated | text | warn | Every programs value is stated in the training text: as event_title, or the name's acronym (GAO, DOD, HHS, a parenthetical '(SNAP)') as an upper-case word; committee names by the committee rule. The failure names where the value does occur (window, known, filename, derived, none). | An organization named only by a short form other than its initials (the VA, the Fed). |
| P15_person_org_stated | text | warn | Every person org value is stated in the training text: as event_title, or the name's acronym (GAO, DOD, HHS, a parenthetical '(SNAP)') as an upper-case word; committee names by the committee rule. The failure names where the value does occur (window, known, filename, derived, none). | An organization named only by a short form other than its initials (the VA, the Fed). |
| P16_person_title_stated | text | warn | Every person title value is stated in the training text: its content words (case, punctuation, '&'/'and', U.S./US, state names and common abbreviations folded) close together in the text; one word in six may be missing (OCR). The failure names where the value does occur (window, known, filename, derived, none). | A title stated in pieces far apart; paraphrases close to the text pass. |
| P17_person_address_stated | text | warn | Every person address value is stated in the training text: work_addr as a phrase; official_contact: emails as written, phone numbers by their last ten digits. The failure names where the value does occur (window, known, filename, derived, none). | Addresses split across letterhead lines far apart. |
| T10_jct_description | text | error | Text/filename pattern -> kind section_by_section | JCT descriptions whose title is not within the first 300 characters; non-JCT descriptions. |
| T11_jct_description_revenue | text | warn | Text/filename pattern (rows labeled section_by_section) -> secondary revenue_or_cost_estimate | Scores stated in other words; tables cut from the training text; descriptions still mis-kinded (T10 reports those first). |
| T12_rules_committee_print_text | text | error | Text/filename pattern -> kind bill_or_draft | Prints of amendment text (left out on purpose); prints whose heading the extraction moved. |
| T13_treaty_transmittal_or_resolution | text | error | Text/filename pattern -> kind treaty_document | Transmittals without the standard heading; hearing transcripts on treaties are excluded on purpose. |
| T14_treaty_executive_report | text | error | Text/filename pattern -> kind treaty_document + secondary committee_report | Executive reports whose accompany line is outside the first 1,500 characters. |
| T15_special_rule_report | text | error | Text/filename pattern -> kind committee_report + secondary committee_resolution | Special rules whose report number or 'providing for consideration' falls past 3,000 characters; resolutions printed without the report number (the rubric's test needs it). |
| T16_agenda_sheet | text | warn | Text/filename pattern -> kind markup_notice | Agenda sheets longer than 1,500 characters, not PDF, or without the word agenda near the top; hearing agendas (not covered); scraped event pages (event_web_page by rule). |
| T17_announces_committee_action | text | error | Text/filename pattern -> kind meeting_results + secondary press_release_or_fact_sheet | The same release under other wording. |
| T18a_release_page_with_remarks | text | warn | Text/filename pattern -> kind press_release_or_fact_sheet + secondary member_opening_statement | Pages that headline with a quote instead of a 'Press Release' mark (not detected); scraped pages whose mark sits past 1,500 characters of site chrome. |
| T18b_opening_remarks_page | text | warn | Text/filename pattern -> kind member_opening_statement | Titles past 250 characters of site chrome; whether the page sits in a news section (the secondary press_release_or_fact_sheet is not checked). |
| T19_witness_invitation_letter | text | error | Text/filename pattern -> kind witness_invitation | Invitations worded otherwise; an invitation quoted inside another document. |
| T20_gsa_va_lease_resolution | text | error | Text/filename pattern -> kind gsa_prospectus_or_property + secondary committee_resolution | Resolutions whose resolving clause is past 2,500 characters. |
| T21_placeholder_page | text | error | Text/filename pattern -> status stub_or_blank | Placeholders over 300 characters (site chrome around a redirect); other video hosts; [EMPTY_BODY] rows (D10 refuses them outright). |
| T22_sfr_submitted_not_testimony | text | warn | Text/filename pattern (rows labeled witness_statement) -> kind public_comment_or_submission | Whether the author appeared (the text rarely says 'did not appear'; for-the-record wording without any testimony wording stands in for it), hence warn. |
| T23_testimony_presented | text | warn | Text/filename pattern (rows labeled public_comment_or_submission) -> kind witness_statement | Submissions that quote testimony wording; testimony worded otherwise. Warn: the text-only reading has not been checked against a blind read. |
| D01_row_format | dataset | error | The gold gate's row-format checks other than leakage and label shape. | Whether provenance values are true. |
| D02_link_key_unique | dataset | error | Every link key is present and appears once across all inputs. | The same document under two link keys (see D04). |
| D03_one_valid_split | dataset | error | split is one of train, heldout_v6_4, test_gapfill, blind_val48, blind_docs8, excluded; excluded rows carry excluded_reason. | Whether the split is the right one. |
| D04_same_doc_across_splits | dataset | error | No saved_body_hex or doc_key is shared by a training row and a test row. | Re-posts with different bytes (see D06). |
| D05_heldout_183 | dataset | error | Each of the 183 keys is in heldout_v6_4 or excluded with a reason; no other row is in heldout_v6_4. | Whether a held-out label was changed (by design it may be). |
| D06a_test_repost_of_train | dataset | error | No test row is a re-post of a training row: containment >= 0.9 of the smaller doc's word 5-shingles, symmetric containment >= 0.95 and digit-token Jaccard >= 0.9 (pairs in between: REVIEWED_NEAR_DUPLICATES, else counted as re-posts). | Texts under 20 shingles; re-posts windowed differently (under 0.9 containment, e.g. L3's slide deck at 0.72); the class thresholds rest on 13 read pairs. |
| D06b_test_template_sibling_of_train | dataset | warn | Test rows at containment >= 0.9 with a training row whose numbers differ (same form, other content: vote sheets, lease resolutions, rules for another Congress). | Siblings under 0.9 containment (L3 found more at 0.8 to 0.9); whether the differing content is what is scored. |
| D07_known_key_order | dataset | error | The known JSON the trainer sends (and, for blind sets, the one the scorer's record sets send) has keys in production order. | Whether the known values are right. |
| D08_known_serialization | dataset | warn | The known JSON uses the production serialization (compact separators), as the queue's known_json does. | Rows in the queue (they take the queue's known by construction). |
| D09_blind_set_overlap | dataset | error | No non-blind row matches a blind doc by the gold gate's keys or the trainer's load_blind_keys (rows the trainer would drop silently). | Blind docs re-posted with different text heads. |
| D10_no_think_or_empty_body | dataset | error | No prompt or training text contains <\|think\|> or [EMPTY_BODY]. | Other template tokens. |
| D11_test_row_in_queue | dataset | warn | Every test row (except blind sets, which carry their own text) has a production queue row. | Nothing about label quality. |
| D12_label_sha256 | dataset | error | label_sha256 (when present) equals sha256 of messages[-1].content. | Rows without the field. |
| D13_subcommittee_majority_spelling | dataset | warn | Every subcommittee uses the dataset's majority spelling of that name ('&'/'and', 'the', commas and case folded together). | Whether the majority spelling is the roster spelling; names spelled one way only. |
| D14_seen_template_flag | dataset | error | On SSOT test rows, seen_template is set exactly on the rows D06b reports. | Rows outside the SSOT format (no label_sha256). |
| D16_stated_date_not_lost | dataset | error | For every exported training and test row that may carry dates, each doc_date or event_date of the reviewer's original label that the training text writes in full is still in doc_date or event_date (or a more specific date within it is). | Dates the original label did not carry; a stated date moved to due_date. |
| D15_removed_values_in_signal | dataset | error | For every exported training and test row, each fact of the reviewer's original label that the exported label no longer has (respellings excluded) and that the training text does not state has a sidecar entry with the same field and value (the SSOT row's `signal`, else the --signal file). | Values the normaliser changed rather than removed where the new spelling has other words; whether a sidecar entry's recorded source is right; facts of people removed whole (covered by the name's entry). |

## Changed and new rules: raw failing counts and verified share

Raw failing = rows failing on the labels as written (3,677 rows; `baseline_raw_report.json`). Verified = failing values
a blind reader and I judged truly not stated (or truly wrong), over values read; "fresh" means read after the last
fix that touched the field.

| Rule | Layer | Sev | Raw failing rows | Verified true by reading | Note |
|---|---|---|---:|---|---|
| P01 Congress stated | text | error | 2,346 | 20/20 | owner examples pass ("117h", "FIFTHTEENTH", "S. HR9. 106-344", "112** congress"); a public-law number or a year never counts |
| P02 chamber stated (owner: evident to a careful reader) | text | error | 552 (959 before the owner decision) | round 4: 18/20 adjudicated (misses "the EPW Committee", a House-only subcommittee; fixed); round 5 fresh: 20/20 adjudicated; the rows the committee-word guard added: 8/8 look-alikes ("Foreign Affairs magazine") | 3 normalised-residue misses fixed ("favorably to the House", "sub-committee", "Department of State Senate") |
| P03 committees stated | text | error | 842 (1,103 before) | fresh 17/19 (round 3; readers ignored the chamber condition: 19/19 adjudicated); rounds 1-2: 34/39 | a one-chamber committee states its chamber; committee acronyms (E&C, HSGAC) count |
| P04 subcommittees stated | text | error | 408 | 20/20 | short forms added after the normalised read |
| P05 doc_date stated | text | error | 539 | 20/20 | |
| P06 event_date stated | text | error | 525 | 52/58 fresh over three rounds (90%); all 6 misses OCR-damaged dates ("3,3,11", "4\|19/23", "Mune 4", "3013"), each now matched | OCR forms added; in-sample 58/58 |
| P07 due_date stated | text | error | 2 | 2/2 | |
| P08 date_spans verbatim | text | warn | 79 | 24/36 (67%) | readers counted reformatted dates; OCR damage |
| P09 event_title not stated (error) / P09b partly composed (warn) | text | error / warn | 119 / 80 (239 before) | 35/37 (95%) on the old rule; titles assembled from the text's words, read through scan damage, or cut by a form field pass | error only under 60% of the title's words in the text |
| P10 verbatim_title | text | warn | 57 | 17/35 | OCR headings, composed titles |
| P11 issuer_org | text | warn | 22 | 14/25 | acronyms not formed from initials (OHCHR, the Fed) |
| P12 orgs_mentioned | text | warn | 160 | 18/36 | same, plus EXIM, CMS, "VA" |
| P13 places | text | warn | 43 | 18/35 | non-Latin texts (now unchecked), OCR |
| P14 programs | text | warn | 16 | 6/22 | TALF, WIC; labels adding words ("B-21 Raider") are true fails |
| P15 person_org | text | warn | 153 | 27/36 | |
| P16 person_title | text | warn | 151 | 23/35 | "Nominee to be" wording, OCR, font-cipher text |
| P17 person_address | text | warn | 28 | 16/31 | spaced-letter and OCR addresses |
| T01 name tokens in text | text | error | 479 (516 before scan-damage reading) | 22/22 (version 1) | "Cassicdog", "Thonspion", "Alsobrodkos", "Nukheee", "gee1", "Kena" (Rena) pass |
| T02 person named in text | text | error | 32 | fresh 8/9; rounds 1-2: 36/40 after discarding one fabricated reader quote | font-cipher texts are now unchecked |
| T03 ref numbers in text | text | error | 87 (19 in version 1) | 20/20 | the filename no longer grounds a ref |
| T04 date in one place (rubric Dates bullet; replaces L24 and the first T04) | text | error | 1,633 | round 4: 20/20; round 5 fresh: 9/10, the miss "Approved on March 17, 2021" fixed; controls showed "Date: 11/20/2024" on vote sheets passing wrongly (the rubric names it the event date), fixed. The three rows the coordinator named pass | 842 on the first T04; the rise is the date-under-a-hearing-title rule |
| T06 initial beside surname (new) | text | error | 0 (a normaliser artifact: raw labels carry full names) | by construction on "E. Cummings", "C. Burgess" | |
| T07 readable text (new) | text | warn | 12 | read 14 at the old threshold: 2 vote-sheet surname grids, now excluded | font cipher, garbled scans, non-Latin; their facts are unchecked by every rule |
| T24 transcripts list their witnesses (new) | text | error | 143 (raw labels; the file arrived 14:11) | quote-verified input | dedicated quote-verified pass over 324 transcripts |
| T08 party_state has a basis near the name (new) | text | error | 656 | 20/20 failing, 3/3 passing controls | "R-GA" on "Rep. Buddy Carter" with no party or state in the text |
| T09 venue has a basis (new) / T09b venue_kind needs a place or mode in the text (new) | text | error | 323 / 260 | T09: 20/20 failing, 3/3 controls; T09b read 6 on the normalised run: all venue labels such as "Rayburn House Office Building" on texts that name no place | T09's place words exclude House and Senate |
| T05 Congress only in a passing mention | text | warn | 58 | read 8: the Congress hits are navigation menus; date and chamber parts were wrong and were removed | |
| T15 special rule report (rubric wording: H. RES. with a House Report number) | text | error | 1 | 1/1 | a first widening matched 11 floor schedules; narrowed to a document that opens with the H. RES. |
| T18a release page with member remarks / T18b "Opening Remarks" page | text | warn | 14 / 1 | not read | the rubric's "as the page presents itself"; quote headlines not detected |
| T22 for-the-record, no testimony wording / T23 testimony wording, no for-the-record | text | warn | 20 / 2 | not read | text decides, never the filing slot (rubric) |
| L22 functional roles on the five letter kinds | label | error | 43 | 8/8 (version 1) | qfr_response and public_comment_or_submission may carry office roles |
| L24 event document has doc_date | label | removed | | | replaced by T04 |
| L25 / L25b date formats; year-only doc_date | label | error / warn | 0 / 2 | 2/2 | year-only allowed when the text gives only a year |
| L31 JCT description fields | label | error | 7 | | committees are only those the text names (P03); chamber follows W&M / Finance |
| D06a re-post / D06b template sibling | dataset | error / warn | 6 / 6 | 12/12 by definition | `build-ssot` sets `seen_template` on D06b rows |
| D15 removed values are in the signal | dataset | error | 0 (labels unchanged) | | |
| D16 stated date not lost (new) | dataset | error | 0 (labels unchanged) | normalised 13:14: 4 hits were my fuzzy-year form ("2011" read as "2012"); D16 now uses exact written dates: 0 | the coordinator counted 68 on the 12:14 run; exact definition here gave 17 there |

Blind-read evidence: `C2_contract/haiku*/reader_*/answers.tsv`, keys and scoring in `C2_contract/scratch/`.

## Baseline: where each label fact occurs (labels as written; `baseline_raw_report.json`, `provenance`)

Rough first count for comparison (old gold): Congress 25% in text, 61% only in known, 14% neither; committees 77 / 22 / 1; doc_date 78 / 19 / 2; event_date 75 / 23 / 1.

**All rows outside excluded**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 3404 | 31.0% |  | 54.8% | 0.1% | 13.3% | 0.7% |  |
| chamber | 3547 | 81.1% |  | 14.2% | 0.1% |  | 1.2% | 3.4% |
| committees | 3517 | 75.9% |  | 19.2% | 0.1% | 2.3% | 2.4% |  |
| subcommittees | 1852 | 77.6% |  | 14.8% | 0.1% |  | 7.5% |  |
| doc_date | 2948 | 81.8% |  | 17.4% | 0.2% |  | 0.6% |  |
| event_date | 2458 | 78.8% |  | 20.5% | 0.3% |  | 0.3% |  |
| due_date | 110 | 98.2% |  |  |  |  | 1.8% |  |
| date_spans | 3871 | 97.8% |  |  | 0.4% |  | 1.8% |  |
| event_title | 1669 | 88.0% |  |  | 0.1% |  | 12.0% |  |
| verbatim_title | 2058 | 98.7% |  |  | 0.1% |  | 1.1% |  |
| issuer_org | 438 | 93.2% |  |  | 0.2% |  | 6.6% |  |
| orgs_mentioned | 5118 | 96.2% |  |  | 0.0% |  | 3.8% |  |
| places | 1996 | 95.8% |  |  | 0.2% |  | 4.0% |  |
| programs | 935 | 98.2% |  |  |  |  | 1.8% |  |
| person_org | 3833 | 95.5% |  |  | 0.3% |  | 4.3% |  |
| person_title | 4314 | 96.1% |  |  | 0.1% |  | 3.8% |  |
| person_address | 1171 | 97.6% |  |  |  |  | 2.4% |  |
| person_name | 6495 | 99.4% |  |  | 0.3% |  | 0.3% |  |
| refs | 4085 | 97.6% |  |  | 1.8% |  | 0.6% |  |

**Split heldout_v6_4 (core fields)**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 170 | 30.6% |  | 58.8% |  | 10.6% |  |  |
| chamber | 175 | 77.1% |  | 17.7% | 0.6% |  | 2.3% | 2.3% |
| committees | 171 | 70.8% |  | 23.4% |  | 2.3% | 3.5% |  |
| subcommittees | 99 | 67.7% |  | 24.2% |  |  | 8.1% |  |
| doc_date | 138 | 79.7% |  | 17.4% |  |  | 2.9% |  |
| event_date | 123 | 72.4% |  | 26.0% |  |  | 1.6% |  |
| event_title | 82 | 76.8% |  |  |  |  | 23.2% |  |
| person_name | 317 | 99.4% |  |  |  |  | 0.6% |  |

**Split test_gapfill (core fields)**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 164 | 39.6% |  | 39.0% |  | 17.7% | 3.7% |  |
| chamber | 178 | 84.3% |  | 1.1% | 0.6% |  | 3.4% | 10.7% |
| committees | 183 | 86.9% |  | 5.5% | 0.5% | 0.5% | 6.6% |  |
| subcommittees | 71 | 94.4% |  |  | 1.4% |  | 4.2% |  |
| doc_date | 125 | 92.8% |  | 5.6% | 0.8% |  | 0.8% |  |
| event_date | 112 | 84.8% |  | 13.4% | 0.9% |  | 0.9% |  |
| event_title | 68 | 100.0% |  |  |  |  |  |  |
| person_name | 363 | 99.2% |  |  | 0.6% |  | 0.3% |  |

**Split train (core fields)**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 3070 | 30.6% |  | 55.4% | 0.2% | 13.2% | 0.6% |  |
| chamber | 3194 | 81.1% |  | 14.7% | 0.1% |  | 1.1% | 3.0% |
| committees | 3163 | 75.6% |  | 19.8% | 0.0% | 2.4% | 2.1% |  |
| subcommittees | 1682 | 77.5% |  | 14.9% |  |  | 7.6% |  |
| doc_date | 2685 | 81.4% |  | 17.9% | 0.2% |  | 0.5% |  |
| event_date | 2223 | 78.9% |  | 20.6% | 0.3% |  | 0.2% |  |
| event_title | 1519 | 88.0% |  |  | 0.1% |  | 11.9% |  |
| person_name | 5815 | 99.4% |  |  | 0.3% |  | 0.2% |  |

**Kind witness_statement**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 699 | 4.1% |  | 80.1% | 0.1% | 15.3% | 0.3% |  |
| chamber | 701 | 95.3% |  | 3.4% |  |  | 1.3% |  |
| committees | 735 | 90.1% |  | 7.2% |  | 0.5% | 2.2% |  |
| doc_date | 672 | 93.6% |  | 6.2% |  |  | 0.1% |  |
| event_date | 661 | 93.0% |  | 6.8% |  |  | 0.2% |  |

**Kind witness_biography**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 473 | 0.4% |  | 98.7% | 0.6% | 0.2% |  |  |
| chamber | 501 | 23.0% |  | 76.8% |  |  | 0.2% |  |
| committees | 481 | 9.1% |  | 78.0% |  | 11.9% | 1.0% |  |
| doc_date | 365 | 17.5% |  | 82.2% | 0.3% |  |  |  |
| event_date | 267 | 1.9% |  | 97.0% | 1.1% |  |  |  |

**Kind hearing_transcript**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 323 | 83.0% |  | 6.2% |  | 10.2% | 0.6% |  |
| chamber | 323 | 98.5% |  | 0.3% |  |  | 1.2% |  |
| committees | 344 | 98.8% |  | 0.9% |  |  | 0.3% |  |
| doc_date | 266 | 98.5% |  | 1.5% |  |  |  |  |
| event_date | 315 | 99.0% |  | 0.6% | 0.3% |  |  |  |

**Kind event_web_page**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 154 | 8.4% |  | 53.2% |  | 37.7% | 0.6% |  |
| chamber | 156 | 94.2% |  | 1.3% |  |  | 4.5% |  |
| committees | 157 | 62.4% |  | 31.2% |  |  | 6.4% |  |
| doc_date | 107 | 94.4% |  | 5.6% |  |  |  |  |
| event_date | 153 | 98.7% |  | 1.3% |  |  |  |  |

**Kind bill_or_draft**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 124 | 91.9% |  | 7.3% |  | 0.8% |  |  |
| chamber | 124 | 98.4% |  |  |  |  | 1.6% |  |
| committees | 139 | 88.5% |  | 7.2% |  |  | 4.3% |  |
| doc_date | 103 | 83.5% |  | 14.6% |  |  | 1.9% |  |
| event_date | 8 |  |  | 100.0% |  |  |  |  |

**Kind committee_vote**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 109 | 72.5% |  | 20.2% |  | 4.6% | 2.8% |  |
| chamber | 109 | 91.7% |  | 7.3% |  |  | 0.9% |  |
| committees | 108 | 88.0% |  | 6.5% |  | 3.7% | 1.9% |  |
| doc_date | 105 | 74.3% |  | 20.0% | 3.8% |  | 1.9% |  |
| event_date | 97 | 73.2% |  | 21.6% | 3.1% |  | 2.1% |  |

**Kind hearing_notice**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 103 | 13.6% |  | 59.2% |  | 27.2% |  |  |
| chamber | 103 | 98.1% |  |  |  |  | 1.9% |  |
| committees | 110 | 92.7% |  | 3.6% |  |  | 3.6% |  |
| doc_date | 100 | 98.0% |  |  |  |  | 2.0% |  |
| event_date | 102 | 97.1% |  | 1.0% |  |  | 2.0% |  |

**Kind committee_amendment**

| field | values | text | window | known | filename | derived | none | unchecked |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| congress | 90 | 37.8% |  | 47.8% |  | 11.1% | 3.3% |  |
| chamber | 96 | 99.0% |  | 1.0% |  |  |  |  |
| committees | 72 | 36.1% |  | 62.5% |  |  | 1.4% |  |
| doc_date | 41 | 46.3% |  | 48.8% | 2.4% |  | 2.4% |  |
| event_date | 27 | 3.7% |  | 92.6% |  |  | 3.7% |  |

## Text versus metadata: is the text the better source? (coordinator request, 2026-11-18)

Scan of all 258,440 queue rows (`C2_contract/scratch/c2_queue_scan.py`; first 6,000 characters of the training text;
metadata = `known_json` congress / chambers / date, falling back to `rel_congress` / `rel_chamber`, and `rel_event_date`
for the event date). "Own" Congress = `congress_mentions(...)` own mentions (the T05 test). A date "agrees" when the
metadata date is among the full dates printed in the head. Disagreeing keys: `C2_contract/queue_scan/disagree_*.tsv`;
per-row categories: `queue_scan/rows.tsv`; tables: `queue_scan/tables.json`.
The scan ran before the owner's "evident" chamber decision (it uses the narrower chamber forms of that time),
so its chamber columns undercount what the contract now accepts; Congress and date columns are unaffected.

| Field | Scope | Rows | Text states one | Metadata has one | Both, agree | Both, disagree (share of both) | Text only | Metadata only | Neither |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Congress, any mention | queue | 258,440 | 49,854 | 201,071 | 39,245 | 3,682 (8.6%) | 6,927 | 158,144 | 50,442 |
| Congress, own mention | queue | 258,440 | 44,019 | 201,071 | 37,495 | 1,258 (3.2%) | 5,266 | 162,318 | 52,103 |
| chamber | queue | 258,440 | 166,157 | 207,941 | 133,293 | 2,205 (1.6%) | 30,659 | 72,443 | 19,840 |
| metadata date (`known.date`) | queue | 258,440 | 199,260 | 194,449 | 106,355 | 42,407 (28.5%) | 50,498 | 45,687 | 13,493 |
| event date (`rel_event_date`) | queue | 258,440 | 199,260 | 176,153 | 91,180 | 41,085 (31.1%) | 66,995 | 43,888 | 15,292 |
| Congress, own mention | labeled rows in queue | 3,387 | 825 | 2,725 | 692 | 30 (4.2%) | 103 | 2,003 | 559 |
| chamber | labeled rows in queue | 3,387 | 2,278 | 2,831 | 1,894 | 74 (3.8%) | 310 | 863 | 246 |
| metadata date | labeled rows in queue | 3,387 | 2,551 | 2,498 | 1,338 | 507 (27.5%) | 706 | 653 | 183 |
| event date | labeled rows in queue | 3,387 | 2,551 | 2,153 | 1,045 | 479 (31.4%) | 1,027 | 629 | 207 |

Reading the disagreements: 40 per field were sampled from the first scan and classified by Haiku readers (shown the
metadata value and the values found; I checked 16 of their calls against the text, and their quotes are often
paraphrased, so treat the split as approximate). Counted over the samples that are still disagreements after the
matcher fixes:

| Field | Read | Still disagree | Metadata wrong | Text value not the document's own | Real conflict (related but different things) |
|---|---:|---:|---:|---:|---:|
| Congress (own) | 40 | 27 | 4 | 23 | 0 |
| chamber | 40 | 28 | 4 | 24 | 0 |
| metadata date | 40 | 40 | 22 | 11 | 7 |
| event date | 40 | 40 | 9 | 13 | 18 |

What this says: for Congress and chamber the remaining disagreements are mostly the trap. Navigation menus, cited
bills, career histories in biographies ("after 28 years in the United States Senate") and references to the other
chamber's action ("the Senate-passed bill") name a value that is not the document's own, and the own-mention test
still misses most of them (23 of 27). Real metadata errors there are rare (4 of 27). For dates the text is often the
better source: the metadata date is wrong for 22 of 40 (a letter dated May 4, 2019 under a June 7 metadata date; a
PTAB decision entered October 21, 2020 under a 2022 hearing). For the event date, 18 of 40 are documents whose own date
is not the hearing they were filed under (a bill introduced months earlier; testimony dated two days before). So
"text is truth" holds for a document's own date, while the hearing date is a fact about the filing, which the text
often does not state.

**Repeated metadata dates.** 372 `known.date` values each carry more than 200 queue rows (108,999 rows in all; most are
real hearing days with many attachments, and 84% to 97% of their rows that print a date in the first 1,500 characters
print that year). One is not: **`2011-10-31`, 1,073 rows**. Of those, 130 print a full date in the head; 3 of the 130
(2.3%) are in 2011, and the printed years are mostly 2007 (75), 2008 (15) and 2005 (8). Over any printed date, 1.8% are
in 2011. It is a bulk import date, not a document date. Full list with shares: `queue_scan/tables.json`,
`repeated_metadata_dates`.

## Normalised data and the sealed SSOT (normaliser run of 15:22:55; sealed 2026-11-18)

`check` on the normaliser's four files with the signal sidecar and `adjudications.jsonl`: **0 blocking errors**;
28 failures waived by 29 person-made rulings (13 seeded from the coordinator's reading of the two shifted-letter
advisories, 16 added by the coordinator; one, `bad802e5854b7dce` P07, no longer fails because P07 now reads "July
23d"). No ruling was refused (a quote broken at a line end, "sub- mit", is rejoined before matching).

`build-ssot`, `seal`, `export --compare-dir ../lookups_and_gold` and `verify-manifest --exports ../ssot/export` all
passed: the SSOT `../ssot/docmeta_gold_v6_5.jsonl` (sha256 `33f978210cbeb8f25960fb66c96090b8139d2e4f2321e64dd7f8e53b56ce9b3f`,
3,733 rows: train 3,268, heldout_v6_4 180, test_gapfill 179, blind_val48 48, blind_docs8 8, excluded 50) is sealed
by `MANIFEST.json` with the contract version, rule-list hash `fed94611...`, contract hash `36687efb...`, the
adjudications file's hash and counts, and the DocMeta branch `docmeta-people-limit-26` at commit `965be3de` (people
limit 26). The exports equal the normaliser's files row for row (the duplicate held-out error page moved to
`excluded`, as declared). 30 training labels carry more than 10 people (at most 26); none in the test splits.

Blind sets stay warn-only: their unnormalised labels fail several error rules (reported in `ssot_report.json`), and
they feed the model a `known` order production never sends.

The 2011-10-31 metadata date (1,073 queue rows) is a source-data defect outside this contract; no metadata value
reaches a label.

## Production rule locks that set a kind from something other than the text (report only; nothing changed)

From `llm_queue_v6_2.parquet` (`locked_primary_kind`, `grammar_lock_source`, `lock_id`; 100,274 locked rows of 258,440).
Gold columns: labeled rows (normalised, outside excluded) carrying that lock, and how many labels agree with it.

| Lock source | Decides from | Queue rows | Gold rows (label agrees) |
|---|---|---:|---|
| `provenance_link_anchor` | the link anchor text on the committee page (10 lock ids: QFR responses 870, support letters 504, transcripts 322, biographies 299, exhibits 183, meeting results 148, ...) | 2,505 | 63 (62) |
| `govinfo_crpt_pkg_lock` | the GovInfo package collection (CRPT -> committee_report) | 2,007 | 0 |
| `govinfo_chrg_pkg_lock` | the package collection (CHRG -> hearing_transcript) | 890 | 42 (38) |
| `govinfo_bills_pkg_lock` | the package collection (BILLS -> bill_or_draft); its sample row is a vote sheet ("042315_Vote_Sheet_Final_Passage_HR_1890.pdf") | 500 | 0 |
| `saved_name_sha_override` | a hand table keyed by body hash, built from saved filenames (36 lock ids) | 36 | 3 (3) |
| `cover_lock_v6` | the text, but the filename slot and roster can veto it: `witness_statement_formal_cover_v6` is skipped for `-SD` slots without "testimony" and for `-MState-`; `stmt_member_opening_cover_v6` is skipped for `-Wstate-`/`-SD` slots and when the roster lists a witness but no member | 30,411 + 2,270 of 37,725 | 137 (136) |
| `nominee_opening_override_v6` | text, with the filename's `-MState-`/non-statement slug as a veto | 3 | 0 |
| `tier1_text`, `tier1_hydrated_v6_1`, `tier1_ssot_v6_2` | text grammar (not audited line by line here) | 56,351 + 179 + 78 | 246 (244) |

Non-text in full: 5,938 queue rows (link anchors 2,505; package collections 3,397; saved-name hashes 36). Text locks
with a filename or roster veto: 32,684 rows.

## Decisions taken (owner and coordinator, 2026-11-18 afternoon) and what is still open

Decided and encoded:
- **"Stated" means evident from the document's own words to a careful reader**, excluding calculation and outside
  lookup (rubric governing paragraph). P02/P03 chamber evidence, P01 scan damage, T01/T02 scan damage, P09 titles.
- **A committee or subcommittee that exists in one chamber states the chamber**, and its canonical name with the
  chamber is correct (P02, P03).
- **A public-law number does not carry the document's Congress** (P01).
- **Prose about this proceeding ("the full Senate") and the committee's own site count** for the chamber (P02).
- **Titles assembled from the text's own words, or cut by a form field, pass**; the remaining composed titles are
  warn (P09/P09b).
- **One printed date goes in one place** (rubric Dates bullet; T04 replaced) and **no stated date is lost** (D16).
- **Initial plus surname without that initial in the text is an error** (T06).
- **Mostly non-Latin texts stay unchecked**, warn-only; **font-cipher or unreadable text is measured and listed**,
  not relabeled (T07).
- **Phrase fields stay warn**, no alias list.
- **Statements for the record** are decided from the text; where the text does not say whether the author appeared,
  the reviewer's label stands (T22/T23 warn).
- **The `2011-10-31` metadata date** (1,073 queue rows) is a source-data defect outside this contract; it never
  reaches a label because no metadata value does.

- **Committee amendment forms** make the chamber evident (House "Offered by Mr. X of State"; Senate "In the Senate of
  the United States", "Amendment No.", "Calendar No.").
- **Biographies** are `witness_biography` whether or not a hearing is mentioned.
- **Garbled or non-English text is read, not skipped**; T07 lists such rows and person-made rulings waive failures.

Still open:
1. **Member titles past the head.** "Rep." or "Senator" before a member's name counts in the first 1,500 characters
   or before "presiding"; later in the text it is not taken as the document's chamber.
2. **The Congress in passing (T05, warn).** P01 still passes a Congress the text names only in passing; the rubric now
   says such mentions "say nothing about this document". Making P01 require an own mention would need a better
   masthead test than T05's (it missed 23 of 27 passing mentions in the queue sample).
