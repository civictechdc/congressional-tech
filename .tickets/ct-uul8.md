---
id: ct-uul8
status: closed
deps: []
links: [ct-dx22]
created: 2026-11-10T13:36:28Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, meetings]
---
# Printed hearings attached to the wrong meeting or to none: 3 on a Senate business meeting, 8 with no meeting

Found 2026-11-10 while reading the 343 name clashes (.cache/archive-release/investigations/name-clash-review-20261110/README.md, 'Off topic but found'). Three GovInfo printed hearings are attached to a Senate business meeting instead of the hearing they print (documents 130655, 138297, 138459), and eight printed hearings have no meeting at all (listed there). Not verified beyond the reader's note.

## Acceptance Criteria

Each of the eleven is attached to its hearing, or the reason it cannot be is recorded; the rule that attached the three is named.


## Notes

**2026-11-10T20:39:29Z**

2026-11-10 unchanged in release 77673bfb8fcf; this release did not touch it. Followed by link key from 619db5f9e08e: rows 130655 (CHRG-117shrg45945.pdf), 138297 (CHRG-119shrg58674.pdf) and 138459 (CHRG-119shrg60657.pdf) are now rows 100076, 103985 and 104069, still on meetings 329124, 336584 and 337025.

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: unchanged in 77673bfb8fcf (rows 100076, 103985, 104069 still on Senate business meetings 329124, 336584, 337025, per the 2026-11-10 note); no commit names ct-uul8.

**2026-11-12T06:20:00Z**

Resolved all 11 printed hearings row by row:

1. **Three prints on Senate `Meeting`-typed sittings (valid attachments; rule named):**
   - `CHRG-117shrg45945` (row `100076`) -> `329124` (`2021-04-22`, Senate Agriculture): Congress.gov's Senate Daily Digest records one combined sitting (`"Business meeting to consider ...; to be immediately followed by a hearing to examine the nomination of Jewel Hairston Bronaugh..."`) under `event_id = 329124`, tags its `meeting_type` as `'Meeting'`, and lists `transcript_jackets = [45945]` (while `mods.xml` also states `<eventId>329124</eventId>`). No separate hearing `event_id` exists in `meetings.parquet`. Attached by `meeting-transcript-links.sql` (`meeting_jackets` + `meeting_mods_links`) vetted by `package-meeting-links.sql` (`print_meeting_agreement` title overlap).
   - `CHRG-119shrg58674` (row `103985`) -> `336584` (`2025-02-05`, Senate Agriculture): combined sitting (`"Business meeting to consider subcommittee assignments; to be immediately followed by a hearing to examine perspectives from the field..."`) under single `event_id = 336584` with `transcript_jackets = [58674]`; same rule (`meeting-transcript-links.sql` + `package-meeting-links.sql`).
   - `CHRG-119shrg60657` (row `104069`) -> `337025` (`2025-06-03`, Senate Agriculture): combined sitting (`"Business meeting to consider the nominations of...; to be immediately followed by a hearing to examine the nominations of Michael Boren..."`) under single `event_id = 337025` with `transcript_jackets = [60657]` and `<eventId>337025</eventId>`; same rule.

2. **Two Senate legislative prints fixed and attached (`senate_page` witness corroboration in `print-meeting-agreement.sql`):**
   - `CHRG-119shrg60080` (row `104027`, `<eventId>336769</eventId>`, `2025-04-01`, `S. 222` Whole Milk for Healthy Kids Act) -> attaches to `336769`.
   - `CHRG-119shrg60341` (row `104046`, `<eventId>336927</eventId>`, `2025-05-06`, `S. 1462` Fix Our Forests Act) -> attaches to `336927`.
   - Root cause & fix: Congress.gov lists no witnesses for Senate hearings, so `print-meeting-agreement.sql` previously fell through to `titled`, where GPO's short legislative titles missed the long statutory Daily Digest descriptions (`1/6` and `4/10` shared words `< 50%`). Extracted `senate-page-candidates.sql` + `senate_page_prelim_links` so resolved `senate_page` witness rosters corroborate Senate prints in `print-meeting-agreement.sql` (attaching 21 Senate prints across the corpus while keeping all 7 wrong `<eventId>` collisions, such as `CHRG-117shrg52109` on `330128`, rejected).

3. **Two House Ways & Means prints lacking any raw publisher link (recorded under `ct-dx22`):**
   - `CHRG-118hhrg54811` (row `101624`, held `2023-05-17`, meeting `115971`) and `CHRG-118hhrg57012` (row `102139`, held `2024-05-10`, meeting `117293`): Congress.gov carries `transcript_jackets = []` on `115971` and `117293`, GPO omitted `<eventId>` (`named_meetings = []`) in both `mods.xml` files, and the `waysandmeans.house.gov/wp-content/uploads/...` PDF captures have no fetched committee hearing page (`listed_on = None`). Under `ct-dx22` (*every link is one a publisher states*), the model does not invent unstated package-to-meeting links.

4. **Four out-of-Washington Senate field hearings absent from `meetings.parquet` (recorded):**
   - `CHRG-117shrg45206` (row `100022`, `2021-07-19`, Senate Rules in Atlanta, GA), `CHRG-117shrg46334` (row `100109`, `2021-09-08`, Senate Aging in Charleston, SC), `CHRG-117shrg47456` (row `100249`, `2022-04-12`, Senate Aging in Phoenix, AZ), and `CHRG-117shrg47982` (row `100312`, `2022-07-01`, Senate Aging in Fayetteville, GA): Congress.gov's Senate `committee-meeting` feed derives from the Congressional Record Daily Digest, which omits recess/field hearings outside Washington, so none of the four has a canonical meeting row to attach to.
