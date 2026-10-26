# Review 8, reader lens: `docs/engine-first-data-model.md` @ 33c2cba0

Reviewer: independent, unanchored (I read no earlier reviews). Scope: whether the release files (§8) serve a reader, end to end, and whether they are honest and cheap. I also read [[ARCHITECTURE]] §4, §10.1, §11 and §16.

## 1. Score

**62 / 100** (confidence: medium-high on the findings, medium on the number).

What works: the document-first core is strong. `link_key` keeps public links stable across regrouping, and `date_kind`, `document_date_source`, `removed_on`, recovery kinds and the "removed by review" state are labeled honestly. The list/detail/ranged split fits a phone. Witnesses are keyed rather than matched, and `meetings`, `bills`, `members` and `rosters` reuse spicy-regs keys.

What costs points: one of the six entity journeys (committees) cannot join, because `list` carries committee *names* and the other files carry *system codes*, and the names collide across chambers and subcommittees. A reader cannot see document titles until each detail row is fetched. Several hearing-page links (transcript, Senate witnesses' testimony, captions) end in a flag or a package ID instead of a document. Two release columns state more than the publisher did: `witness_keys` treats "listed in the printed hearing" as "submitted", and `nominations.vote_id` gives one vote where the data has several. Separately, a CommonMark parser renders all of §8 and the §9 key diagram as one code block.

## 2. Journeys

N = about 0.65M list rows. Every "scan" below is a linear pass over a decoded `list` column in the worker: O(N), a few ms, and no request. Detail reads cost one page per leaf (§11.1), up to 64 KB each.

| # | Question | Files and columns | Lookups and cost | Verdict |
|---|---|---|---|---|
| J1 | Every document about bill 119-hr-6028 | `list.measure_keys` scan; `bills.parquet` (whole) by `bill_id` | 1 scan; bills loaded once | **Partial.** Only documents whose filename encodes the measure: 40,859 of 358,528 documents (11%) on the 2026-10-02 catalog. Other documents arrive only through J2's hearing hop. Each result shows its filename only (F3). |
| J2 | …then its hearings, cost and votes | `meetings.subject_keys` scan; `bills.cbo_estimates`, `bills.floor_votes`; `vote_id` out to spicy-regs for positions | meetings whole (2–4 MB, once per session); then one `list.meeting_keys` scan per hearing, O(H·N) | **Works.** `floor_votes` mixes votes on the bill with votes its actions only name (`bill_vote_references`) and does not say which is which (F11). |
| J3 | Open a hearing: witnesses and what each submitted | `meetings` row; `witnesses` (whole) filtered by `(chamber, event_id)`; `list.witness_keys` scan per witness; `detail` for each document's title | W scans (or one inverted pass); **K detail reads for K documents** just to show titles | **Partial.** House: works (XML document groups). Senate: no witness→document path at all (F5). MODS witnesses get every document in the package as "submitted" (F4). |
| J4 | …its transcript | `meetings.transcript_packages` → ? | No release index from a package ID to a list row. The reader must scan `detail.govinfo_package_id`, a ranged file read page by page, or guess from `list.meeting_keys` plus kind | **Broken link** (F6). |
| J5 | …its recording and captions | `meetings.videos{url, video_key, has_captions}` | none | **Partial.** The recording link works. `has_captions = true` promises captions the release does not publish, because captions are role `caption` and never listed (F9). |
| J6 | A member's committees, hearings and documents | `members` (whole) by `bioguide_id`; `rosters` by `bioguide_id`; `committees` by `system_code`; `meetings.committees` scan; `witnesses.bioguide_id`; `list.bioguide_ids` scan | All small or whole files | **Partial.** Committees exist for current seats only (stated in §7.11). Hearings can only be inferred from the member's committees; the files have no attendance, and that is correct. Documents come only from filename-encoded IDs: 38,864 of 358,528 (11%). |
| J7 | A committee's hearings and documents | `committees`; `meetings.committees[].system_code`; **`list.committee_name`** | Hearings: works. Documents: must match by *name* | **Broken** (F1). The names are not unique, and `list` carries no `system_code`. |
| J8 | A witness across hearings and documents | `witnesses.name` text scan; `bioguide_id` for member witnesses | Whole file | **Not answerable by key**, and the document says so honestly (§7.11, witness table "comes later"). A name search over `witnesses.parquet` is the only route; `name_key` is not published, so the reader re-derives it. |
| J9 | A nomination's hearing and outcome | `nominations` by `nomination_id`; `meetings.subject_keys` scan; `vote_id` | small | **Partial.** The `nomination_id` spelling is unspecified (F7). `vote_id` picks one of several votes (F8). Outcome comes from `latest_action_text`, which is fine. Only the 119th Congress exists. There is no `list` key for nomination documents. |
| J10 | A document's other versions | `list.version_keys` scan; order by `list.first_captured` | 1 scan | **Works** for same-address editions. Versions at other addresses (bill text ih/rh/eh) connect only through `measure_keys`. |
| J11 | Where a document was published and who listed it | `detail.src_start/src_len` → `sources` rows (`url`, `listed_on`, `link_text`, `doc_type`, `posted`) | 1 detail read and 1 ranged read | **Works well.** |
| J12 | A document whose original link is gone | Paste URL → `sha256('url:'‖url)[0:8]` → `links` (lookup) | 1–2 range reads | **Works only if** that exact string was a recovery's original link. Any other dead URL (the usual case: "this congress.gov link 404s; do you have it?") has no index (F2). |
| J13 | Search "Judiciary hearing on AI" | `list` only: `filename` and facets | 1 scan | **Weak.** Titles are not searchable. Committee facet merges House and Senate Judiciary (F1, F3). There is no chamber facet (F12). |
| J14 | Open a document and its saved file | `links` → `list_row` → `detail` (`saved_body`, `saved_suffix`, `saved_media_type`, `alternates`) | 1 lookup, 1 detail read, 1 body GET | **Works.** |

## 3. Findings (most severe first)

### F1. Blocker: §7.5 (`committee_key`/`committee_name`, l.674–677), §8.1 `list` (l.826), §9 (l.872, l.888). Documents join committees by a name that is not unique.

**Problem.** `list.committee_name` is the only committee column on a document. Every other file (`meetings.committees`, `rosters`, `committees`) keys on `system_code`. §9's ER diagram claims `SPICY_COMMITTEE ||--o{ DOCUMENT : "committee_key"`, but no release file carries `committee_key`. [[ARCHITECTURE]] §11.6 promises that "a committee's page joins its roster, hearings and documents by system code"; that join cannot be made for documents.

**Evidence** (pinned spicy-regs `committees.parquet`, generation 5f031073…, 817 rows):
- `name` is shared by 2 or more system codes for 47 names. "Oversight and Investigations Subcommittee" alone covers 12 codes across both chambers (hsvr08, hsii15, hlig09, hsif02, sseg06, …), and Appropriations, Judiciary and Armed Services carry identical `name` in both chambers.
- `history.officialName` is null on every entry for 287 of 589 subcommittees, so the "else its current name" fallback is the colliding `name`. Even the official names collide: "Committee on Commerce" (sscm00, hsif00), "Subcommittee on Energy" (hssy10, sseg01, hsif03), and 55 official names in all.

A facet on "Judiciary Committee" therefore merges both chambers, and a subcommittee page finds 12 committees' documents.

**What this could not see:** the filename codes' real distribution against these collisions, because I had no `filename_readings` at the current catalog.

**Fix (gives readers a committee page and a correct facet).** Rewrite the `list` bullet at l.826 so `list` carries `committee_keys` List<dict> (system codes, every value), replacing `committee_name`. Facet labels come from `committees.parquet`: its `names` by date for display, qualified by chamber and parent for subcommittees. Rewrite the §7.5 `committee_name` line as a display rule on `committees.names`, not a stored column. Fix §9's diagram edge to name the release column.

### F2. Major: §8.2 (l.831–835), §8.1 `links` (l.810). A dead link resolves only when it was a recovery.

**Problem.** Body keys need the file's bytes; link URL keys exist only for recovery originals. A reader holding a publisher URL that now 404s, which is the archive's main use case, has no lookup. The only file that holds URLs is `sources`, which is ranged by `list_row`. Scanning its `url` column means downloading most of an *est.* 10 MB file. (`url_state` holds requested URLs but maps to no document.)

**Fix (gives every reader "paste a link, get the document").** Rewrite the "Link URL keys" bullet to cover every distinct source URL of a listed document's real files, plus each recovery's original link, keyed by the same exact-string `sha256('url:'‖url)[0:8]`. Rewrite invariant 19 (l.919) to let a URL key resolve to several rows, shown as versions, because one address can serve several editions. *Est.* about 1.7M keys × 12 B is about 20 MB in the lookup profile, still 1–2 range reads per lookup through the column index.

### F3. Major: §8.1 `list` (l.826). No title in `list`.

**Problem.** Search runs over `list`, which has `filename` and no `title`. Every result row, hearing page, bill page and member page shows filenames until each row's `detail` page is fetched: K documents cost K range reads, each pulling a page of up to 1,024 titles. Filenames are often not distinctive:
- `index.cfm` names 342 documents in the 2026-10-02 catalog, and `summary` 288.
- `BILLS-119-1-M000312-Amdt-1.pdf` names 105 different amendments.
- 12,445 filenames are bare numbers.

The principle "carry what a reader acts on" (§8, l.15) puts title in `list`: it is the main thing a reader scans.

**What this could not see:** how many listed documents will have a non-null `title` (readings are not in the snapshot). 22,629 documents in the old catalog had a page title.

**Fix (gives searchable, scannable results).** Move `title` from `detail` to `list` (string, nullable, `DELTA_BYTE_ARRAY`), and rewrite the `list` size estimate (l.808) after measuring it in F0.

### F4. Major: §7.11 `witness_keys` (l.764–768); [[ARCHITECTURE]] §11.6. "Listed in the printed hearing" is published as "submitted".

**Problem.** `witness_keys` mixes two different facts:
- a House XML document group: the publisher states that this witness submitted this file;
- a MODS appearance whose `package_id` equals the document's `govinfo_package_id`: the witness is *named in* the printed hearing.

Under the second rule, every witness of a printed hearing is attached to every file of that package. The hearing page then "lists its witnesses with the documents each submitted" and shows the whole transcript as submitted by each witness. The release cannot tell the two bases apart.

**Fix (gives readers attribution they can trust).** Rewrite the `witness_keys` derivation to use only publisher document groups. Show the MODS witness list on the transcript document through `witnesses.package_id` (already present), so the transcript page says "witnesses in this printed hearing" and no witness is credited with authoring it.

### F5. Major: §6.7 Sources (l.408), §6.5 (l.377). Senate witnesses' testimony is unreachable.

**Problem.** Congress.gov lists no Senate witnesses, and Senate committee pages are excluded because they carry no meeting ID. Senate witnesses therefore come only from MODS, which exists for printed hearings, months to years later. No Senate witness ever reaches a testimony file.

**Evidence:** the old catalog attributed 12,663 documents to witnesses by name from publisher pages, almost all Senate (judiciary.senate.gov 2,800, foreign 964, banking 960, commerce 863, …). 12,486 senate.gov documents have testimony- or statement-shaped filenames.

**Fix (gives Senate hearings the same "who said what").** Rewrite §6.7's sources to add Senate committee hearing pages. Their occasion is the page (`'page:' || hex(sha256(url_key(page))[0:8])`), and their `document_group_paths` come from the page's witness blocks. Rewrite `occasion` (l.756) to include it. This is still keyed, not matched: a later step may tie a page occasion to a meeting.

### F6. Major: §8.1 `meetings` (l.813), `detail` (l.827). A transcript package cannot be opened.

**Problem.** `meetings.transcript_packages` holds package IDs, and only `detail.govinfo_package_id` holds the same ID. `detail` is ranged and sorted by filename, so finding the transcript means reading the column page by page across the file. The data needed to make this one hop already exists (the model computes `transcripts` from listed documents).

The same fact is also spelled four ways: `gpo_package_id`, `govinfo_package_id`, `package_id` and `transcript_packages`.

**Fix (gives "Read the transcript" as one click).** Rewrite the `meetings` columns so `transcripts` is List<Struct<package_id string, list_row int32>>, filled from §7.11's `transcripts`. Use one name, `package_id`, in `filename_readings`, `detail`, `witnesses` and `meetings`.

### F7. Major: §6.5 `subject_keys` (l.372), §8.1 `nominations` (l.819), §9 (l.888). The nomination key is unspecified.

**Problem.** `subject_keys` writes `{congress}-pn-{number}[-{part}]`, but `nominations.nomination_id` has no stated format. The pinned source spells parts two ways: `part_number` is `'02'` while `citation` is `PN730-2`. Votes name nominations as `PN129-10`, with the congress in a separate field.

**Fix (gives a nomination link that joins).** Rewrite the `nominations` column as `nomination_id` = `{congress}-pn-{number}[-{part}]`, with number and part as unpadded integers. State it once in §6.5, and have §7.11 derive it from `congress`, `number` and `int(part_number)`.

### F8. Major: §7.11 `nominations` (l.780–781), §8.1 (l.819). One `vote_id` where the Senate cast several.

**Problem.** "The Senate vote whose documents name it" is not unique. In the pinned `roll_call_votes`, 1,433 PN citations are named by 2 votes and 120 by 3–9 (motion to proceed, cloture, then the nomination). The writer must pick one, and the page then calls a cloture vote the confirmation vote. Meanwhile 1,640 of 2,287 nominations' `latest_action_text` says confirmed, but only 594 are named by any roll call (voice votes and unanimous consent).

**Fix (gives the full, labeled vote history).** Rewrite the column as `votes` List<Struct<vote_id, question, result, yea, nay, date>>, mirroring `bills.floor_votes`, ordered by date. The outcome stays `latest_action_text`.

### F9. Minor: §8.1 `meetings.videos.has_captions` (l.813), §7.11 `videos`. A promise the release does not keep.

**Problem.** Captions are role `caption`, never listed, and absent from the release. A reader told "captions available" has nowhere to go.

**Fix.** Either drop `has_captions` from `meetings`, or publish captions as listed documents keyed by `video_key` so the flag becomes a link. Rewrite the column to match whichever is chosen.

### F10. Major (spec integrity): §7.11–§9 (l.784–879). All of §8 renders as a code block.

**Problem.** Line 782 closes a fence and line 784 opens a stray empty one. Line 849's "```mermaid" cannot close it, because a closing fence takes no info string. A CommonMark parser (markdown-it, checked) yields one fence spanning lines 784–879 and no headings until l.891. §7.11's bullets, §8 (the release contract), §8.2, §8.3 and §9's heading and diagram all render as preformatted text, and the TOC anchors for §8 and §9 do not resolve.

**Fix.** Delete line 784.

### F11. Minor: §7.11 `bills` (l.776–779), §8.1 `bills.floor_votes`. Two bases of vote are merged.

**Problem.** Votes on the bill and votes its actions name (for example, a vote on the rule) appear in one list.

**Fix.** Add `basis` dict (`vote_record` | `bill_action`) to the struct, so the bill page can say "vote on this bill" or "vote named in its actions".

### F12. Minor: §8.1 `list` (l.826). No chamber facet.

**Problem.** House versus Senate is the commonest first filter, and once names collide (F1) it cannot be derived from `committee_name`.

**Fix.** Add `chamber` List<dict> to `list`, from `committee_keys` and `meeting_keys`.

### F13. Minor: §6.4 (l.340–350). The pinned reference data holds publisher-stated links the model ignores.

**Problem.** spicy-regs already publishes the following, and none of it is read:
- `nominations.hearings_json`: a nomination's printed hearing, by S.Hrg. jacket, on 224 of 2,287 rows;
- `nominations.committees_json`;
- `bill_committees`: bill → committees of referral, 286,721 rows;
- `committee_reports` (bill → report).

**Fix (exploration goes further at no matching cost).** Rewrite §6.4's table to read `nominations.hearings_json` (nomination → transcript package, then to a document through F6) and `bill_committees` (bills on a committee page). Do not add new joins of your own.

### F14. Minor: §8.1 `url_state.parquet`, `capture_scope.json` (l.820–821). Operational files are in the reader's release.

**Problem.** These carry the capture schedule and queue (*est.* 10 MB, re-uploaded with every changed release), which no reader acts on. That contradicts l.15 and §8 l.791.

**Fix.** Rewrite §8's first sentence and the table: publish them under `viewer-publications/capture/<release_id>/`, named by the pointer but outside the reader manifest's `files[]`, so the reader contract and the release ID cover reader files only.

### F15. Nit: §8.1 `sources`/`recoveries` `list_row` (l.811–812) and `detail.src_*`/`rec_*` (l.827). One fact stored twice.

**Problem.** Ranges locate rows, and `list_row` in the target file repeats them. The duplication is cheap, but invariant 18 then has two encodings to keep in agreement.

**Fix.** Drop `list_row` from `sources` and `recoveries`, and keep the ranges.

### F16. Nit: §8.1 `meetings`/`witnesses` and `list.meeting_keys`. Two encodings of the meeting key.

**Problem.** `list.meeting_keys` is `'chamber:event_id'` while `meetings` and `witnesses` use two columns, and the chamber vocabulary is never fixed (spicy-regs uses `house`, `senate`, `nochamber`).

**Fix.** State the chamber values once in §6.5, and give `meetings` a `meeting_key` dict column in the same string form.

### F17. Nit: §8.1 `detail` (l.809). The size is not estimated.

**Problem.** The size is given as "well under the earlier 55–70 MB … measured with F0", which is not an estimate. Phone startup does not depend on it, but the shard rule (`detail MAY be split`) does.

**Fix.** Give a number from a column-by-column estimate.

### Cost and heap

- **Heap.** `list` at 0.65M rows: `filename` averages 33 bytes (snapshot), giving *est.* 40–60 MB of JS strings plus about 10 MB of offsets and codes for 8 list columns. That is acceptable against a phone budget. Adding `title` (F3) adds *est.* 30–50 MB of decoded strings; keep it as a UTF-8 byte buffer with offsets rather than JS strings.
- **Key lookups.** Each is a linear scan of one list column, O(N) per lookup. A hearing page with W witnesses or H related hearings should build one inverted map per session (O(N) once) instead of O(W·N) repeated scans. Today's text is silent on this; [[ARCHITECTURE]] §11.1 is the place to say it.
- **Requests.**

  | Page | Requests |
  |---|---|
  | Document page | 1 links lookup + 1 detail read + 1 sources range + 1 body |
  | Hearing page | meetings and witnesses (whole, once per session) + K detail reads for titles (F3) |
  | Bill page | bills (whole, once per session) + scans |

## 4. What I could not check, and why

- **Release sizes and the phone heap.** No release has been built under this spec. Sizes and heap are estimates from the 2026-10-02 catalog (358,528 documents, an older grouping), not from 0.65M listed documents.
- **The data model's own lake tables** (`readings`, `filename_readings`, `meeting_records`, `appearance_records`). None exist locally, so I could not count:
  - meetings with `transcript_jackets`;
  - House XML `document_group_paths` coverage;
  - MODS witness counts;
  - how many documents get any `witness_keys`.
- **Real filename committee codes against the collisions in F1.** I verified the collisions in spicy-regs' names, not which codes the filename parser emits. The old catalog has `committee_code` on 194,686 of 358,528 documents, so the facet is used heavily.
- **Senate attribution in F5.** I relied on the old catalog's `source_witness_name`, which is an older, inferred attribution. I did not inspect Senate hearing-page HTML to confirm that per-witness grouping exists.
- **spicy-regs tables.** I read the generations named in `publication.v2.json` on 2026-10-26 (committees, committee_assignments, nominations, roll_call_votes, committee_meetings, hearing_transcripts). Later generations may differ.
- **The site.** The current site is a filename viewer, not this spec's reader, so I checked it for search behavior only: it searches filenames.
- **Rendering on other parsers.** I checked F10 with markdown-it (CommonMark) only; GitHub's renderer follows the same fence rule.
