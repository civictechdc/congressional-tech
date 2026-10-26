# Review 8 validation: keys, vocabularies, reference links

Spec: docs/engine-first-data-model.md @ 33c2cba0. Validator: independent; no reviewer scripts, downloads or numbers reused.

**Inputs I fetched or read myself**
- spicy-regs: `publication.v2.json`, fetched 2026-10-26, plus 10 tables (committees, committee_assignments, roll_call_votes, bill_vote_references, member_terms, nominations, congress_bills, bill_committees, committee_reports, committee_meetings). Every file's SHA-256 matches the index digest.
- Local index snapshot 2026-10-02: `documents` (358,528 rows) and `document-filenames` (468,943 rows).
- Raw Congress.gov meeting receipts: `docspec-catalog/r2-immutable/receipts/congress/meetings`, 199,156 lines, counted line by line and not deduplicated.
- One public House meeting XML file.
- Senate pages: 8 public hearing pages from 8 committees were tried, and all 8 returned 403. I used the repo's Senate fixtures and the index instead.
- Scripts and downloads: `validate-keys/scripts/v8k_*.py`, `validate-keys/dl/`.

## Verdict table

| ID | Verdict | Mine vs reviewer | Fix judgment |
|---|---|---|---|
| B2 | confirmed | Same spellings and counts (source_chamber House 238,323 / Senate 15,694 / NoChamber 471). Missed: API path `nochamber`; spicy `committee_meetings` uses `nochamber`; GovInfo uses h/s/j letters; House XML has no chamber at all. | Partly right. Better: key meetings on `event_id` alone (0 of 18,140 events use 2 chambers) and keep `chamber` as an attribute. |
| B3 | confirmed | Identical (part `'00'`/`'02'`, `PN730-2`, `129-10`, null congress on 1,681 of 9,079) | Right. The key equals spicy `citation`. |
| B4 | confirmed | 19,766/19,766 by string concatenation and by typed per-column join | Right. Also: 11,755 distinct (bill, vote) pairs, and only 48 rows add a vote the vote's own `bill_id` lacks. |
| C1 | confirmed | 47 names / 116 codes; 287 of 589; official-name collisions 54 vs 55 | Right: `committee_keys` replaces `committee_name`. All index system codes resolve. |
| C3 | partly | Claim "by name" is wrong: the parser ties links to witness *cards* in the DOM. 90.7% of Senate testimony sits under a card. 12,533 vs 12,663 attributed. | Direction right (Senate pages as appearance sources, page as occasion). |
| C5 | confirmed | 1,552 of 2,155 exact. In the 119th, the only Congress with nomination rows: 0 votes 1,693, 1 vote 9, 2 votes 526, 3+ votes 59. 1,047 confirmed with no roll call. | Right: a list of votes. |
| C9 | partly | `index.cfm` is in 342 documents' filenames but is the displayed name of only 96. The spec's `title` would be mostly null. | Incomplete: list a publisher label (46% coverage), not only `title`. |
| C12 | confirmed | hearings_json 224 of 2,287; committees_json 2,270; bill_committees 286,721; committee_reports only 196 | Right for the first three; committee_reports is too sparse to matter. |
| D3 (name) | partly | Strict overlaps: 6 unordered pairs (likely 12 counted as ordered pairs). Closed-day boundary ties: 196 in 134 codes. | The tie-break is right; also state half-open intervals. |
| D5 | confirmed | 1,606 of 1,839 exact; UTC date ≠ Eastern date on 174 history values and 2,001 vote-reference dates | Right (America/New_York). |
| E5 | confirmed | 16: 7 `cen_doc_h`, 8 `½`, 1 `LXXXV` | Right. Treat `bill_id` as opaque. |

## Details

### B2: chamber vocabularies, as raw counts

| Input | Spellings and counts |
|---|---|
| Congress.gov meeting `record.chamber` (199,156 lines) | House 146,799; Senate 50,301; NoChamber 1,828; null 228 |
| `_url` path segment | `house`, `senate`, `nochamber`, one-to-one with `record.chamber` |
| Web document URLs `congress.gov/<c>/meeting/<ch>/` | `house` only (1.86M URL occurrences; the index's `documents.source_url` gives 166,287 house) |
| House meeting XML (`docs.house.gov`) | No chamber element. The chamber is implied by the host. Committee codes are 4 characters (`PW12`). |
| GovInfo CHRG packages | Letters h 41,393; s 27,161; j 1,558 |
| spicy `committees` | House / Senate / Joint |
| spicy `bill_committees` | House / Senate / Joint / null 73,259 |
| spicy `congress_bills.origin_chamber` | House / Senate |
| spicy `committee_assignments`, `roll_call_votes`, `bill_vote_references`, `committee_reports` | house / senate |
| spicy `committee_meetings` | house / senate / nochamber |
| spicy `member_terms.term_type` | rep / sen |
| Code | `Literal["house","senate","joint","unknown"]`; adapters map NoChamber to joint |

**NoChamber is not always joint.** In NoChamber records, committee codes start with j on 1,814 entries, h on 14 and s on 14. Mapping NoChamber to "joint" invents a fact the publisher did not state.

**Fix.** In §6.5, §7.5 and §7.11, key a meeting by `event_id` alone. Event IDs come from one number space, which docs.house.gov and Congress.gov share: 18,140 distinct, none under two chambers. That makes `meeting_keys`, `occasion` and the witnesses→meetings join chamber-free. Keep `chamber` as an attribute in one vocabulary: `house|senate|joint`. Map each input once, in §6.4:
- Congress.gov `House|Senate` → lowercase; `NoChamber` → `joint` only for display, recorded as `nochamber` at its source.
- spicy capitalised columns → lowercase.
- `rep` → house, `sen` → senate.
- GovInfo h/s/j → house/senate/joint.

What this could not see: event-ID uniqueness is observed, not promised by the publisher. Invariant 16 should assert it.

### B3 / C5: nominations
- spicy `nominations`: 2,287 rows, all from the 119th Congress. `part_number` is `'00'` on 1,264 rows, otherwise zero-padded. `citation` = `'PN'||number||('-'||int(part) unless '00')` holds on 2,287 of 2,287.
- Congress.gov meeting `relatedItems.nominations[].part` is zero-padded (`'00'` 42,202 occurrences). So is spicy `committee_meetings.nomination_references_json`. This is the source of `subject_keys`, so the padding mismatch is real on both sides.
- Senate vote `documents`: 9,079 entries, 3,990 with `type='PN'`. All PN `number` values match `^\d+(-\d+)?$`, and `name` = `'PN'||number`. 103 PN entries have a null `congress`; none disagree with the vote's own congress. House votes carry no documents. No vote names a bare PN number when the nomination has parts.
- Votes per nomination, all Congresses (2,155 voted PNs): 1 vote 603, 2 votes 1,433, 3+ votes 119. Only 68 have no "On the Nomination" vote, and 2 have two of them.
- 119th Congress: 594 of 2,287 nominations have at least one vote. Questions: cloture 633, nomination 593, reconsider 48, decision of the chair 48, proceed 16.
- 1,640 nominations are confirmed: 593 with a roll call, 1,047 without. 1,048 of the 1,640 say "Voice Vote"; none say "unanimous consent" (the reader's wording is wrong here).
- 13 votes name 10 or more nominations en bloc.
- **Fix:** key = spicy `citation` form, `{congress}-pn-{number}[-{int(part)}]`, omitting `00`. Normalise the Congress.gov part with `int()`. Replace `nominations.vote_id` with `floor_votes List<Struct<vote_id, question, result, date, yea, nay>>`, mirroring `bills`. Outcome stays `latest_action_text`.

### C1: committees
- Raw `name`: 47 names over 116 codes. NFKC/casefold normalisation adds nothing.
- `(name, chamber)`: still 21 collisions.
- Official names: 54 collide raw and 54 normalised; the reader said 55.
- Any name, official or current: 99 normalised names shared, touching 181 of 817 codes.
- Index codes:
  - `source_committee_code` and `source_publisher_committee_code` are already system codes. All 255,300 and 22,640 values exist in spicy `committees`.
  - Filename `committee_code` is House 4-character. 190,591 of 194,821 resolve as `'hs'||lower`; 4,176 more resolve as `'hl'||lower` (IG00 → hlig00, as the registry says); 54 remain.
  - 279,639 of 358,528 documents carry at least one code. govinfo.gov is the main gap: 8,973 of 72,362.
- `committee_keys` on `list`, with names displayed from `committees.parquet`, lets a committee page scan for its documents. The fix is right.

### C3: Senate witnesses
- Congress.gov lists witnesses on 0 of 4,575 Senate events (House: 8,292 of 13,399). Senate pages are the only same-day source.
- `parsers/senate_page.py:1042-1128` finds per-witness DOM cards (`participant_card_identity`). It attaches each link to the card it sits in, by ancestor; a name match is used only to pair a card with the same page's witness list.
- On senate.gov, 14,624 documents are testimony-like by kind or filename:
  - 13,259 (90.7%) sit under a witness card (`source_participant_label`);
  - 11,818 (80.8%) also resolve a witness name.
  - By host: judiciary 98.6%, banking 100%, foreign 100%, hsgac 64.8%, indian 54.8%, jec 0%.
- The fix is right: Senate hearing pages as appearance sources, occasion = page URL key, groups = cards.
- Could not see: live pages (8 of 8 returned 403). The index is the project's own parser output, so it cannot reveal cards the parser misses. Fixtures show several layouts (vcard, capigacr card, ds-2col).

### C9: title
- The spec's `title` is an HTML reading. Only 39,301 of 358,528 documents are HTML.
- Publisher labels (Congress.gov document name, link text) cover 164,050 documents (46%), averaging 58 characters. That column is 1.73 MB zstd and about 17 MB of JS strings, or about 30 MB at 0.65M rows. Many labels are generic ("Testimony" 2,417).
- Filename floor: 1.87 MB and 20 MB.
- **Affordable.** Arrow keeps UTF-8 buffers, so the heap cost is close to the byte size until rows are rendered.
- **Fix:** `list.display_name` = title override, else reading title, else publisher link label, else null (the site falls back to `filename`).

### C12
- `nominations.hearings_json`: 224 rows with 228 entries, each with `jacketNumber` and `chamber` and no event ID. It joins to `CHRG-{c}shrg{jacket}`.
- `committees_json`: 2,270 rows with `systemCode`.
- `bill_committees`: 167,162 bills over the 108th–119th Congresses (96% of the 173,576 bills in those Congresses), 255 codes, all in `committees`.
- `committee_reports`: 196 rows.
- Unmentioned: spicy `committee_meetings` (6,098 meetings, 118th–119th) overlaps the spec's own meeting parse.

### D3 / D5
- All spicy history instants have the shape `YYYY-MM-DDTHH:MM:SSZ`.
- `startDate`: 1,606 of 1,839 fall at 04–05 UTC. `endDate`: 1,325 of 1,601.
- Converting to dates in America/New_York vs UTC changes 174 history values (for example `1977-02-04T04:59Z` = 23:59 EST on Feb 3).
- `bill_vote_references.date` matched to `roll_call_votes.vote_day`: the UTC date is wrong on 2,006 of 19,766, the Eastern date on 9.
- Overlaps in different `officialName` values within one code:
  - instant level: 6 pairs in 5 codes;
  - half-open Eastern days: 3 pairs;
  - closed days: 196 pairs in 134 codes, almost all boundary days.
- **Fix:** Eastern dates, half-open `[start, end)`, latest `startDate` first, then `officialName` bytewise. Under C1's fix this becomes a display rule on `committees.names`, not a stored pick.

### E5
16 non-matching IDs, all before the 43rd Congress. `bill_id` = `congress-lower(type)-number` holds on 422,011 of 422,011, so the spec should call the number opaque.

### Aside (outside my scope)
The fetched House XML has `meeting-id="HMTG110741"`, which contradicts A12's "0 of 15,707 prefixed". It needs re-checking.

## Reviewer accuracy (on findings validated here)

| Reviewer | Score | Basis |
|---|---|---|
| trace | 92 | B2, B3, B4, C5 and E5 numbers exact; the B2 fix bakes in NoChamber → joint. |
| data | 92 | B3 and B4 exact, fixes right. |
| reader | 80 | C1, C5 and C12 right. C3 mechanism ("by name") wrong. C5 says "unanimous consent" where it is 0. C9 fix incomplete. 55 vs 54 and 120 vs 119 off by one. |
| storage | 82 | D5 exact. D3's 12 is pair-counting dependent, and it missed the boundary-day ties. Fixes right. |

**Confidence:** high on spicy and receipt counts (digest-verified, raw counts); medium on C3 (live pages blocked, index uses the project's own parser); medium on C9 heap (V8 model approximated).
