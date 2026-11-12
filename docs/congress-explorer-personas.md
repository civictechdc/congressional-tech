# Congress Explorer MCP: personas, questions, and expected results

This document fuses three artifacts into one reference: the personas of people
who need a local Congress Explorer MCP server, the questions each would ask an
assistant wired to it, and a conceptual prediction of what each answer should
look like. It is grounded in the selected release `e4538f00…` (October 2026
snapshot) and in the server's documented behavior. Expected results are
back-of-envelope predictions, not measured outputs: magnitudes are soft
estimates; shapes are firm because they follow from the server's design.

## Grounding snapshot

| Data | Rows | Coverage |
|---|---|---|
| Documents (list/detail) | 355,608 | dense 1990s–2026; congress tags 104th–119th — the published 1901/2303 date endpoints and 12th-Congress start are misread artifacts (ct-m94a) |
| Meetings | 18,687 | 112th–119th, 2011–2026 |
| Witness appearances | 172,948 | 106th–119th, 2011–2026 |
| Bills | 52,279 | 106th–119th, 2007–2026 |
| Nominations | 747 | 119th only |
| Committees / members | 818 / 12,770 | back to 1789 |
| Rosters | 25,165 (2,973 in `e4538f00`) | 113th–119th |
| Recordings / videos / matches | 12,283 / 67,391 / 32,086 | committee channels |
| Recoveries | 12,618 | ~3.5% of documents |
| Tracked URLs | 1,198,586 | capture state |
| Retired links (lifetime) | 450 | removals are rare events |

## The pattern

Three clusters emerge across the personas:

- **Accountability** (journalist, fact-checker, opposition researcher) — powered
  by the archive's memory of churn and verified bodies.
- **Scholarship** (researcher, lawyer, librarian) — powered by immutability and
  honest absence (missing ≠ empty ≠ zero).
- **Production** (staffer, advocacy tracker, producer) — powered by recipes and
  dossiers that assemble in seconds what used to take a day of tab-hopping.

The builder persona constructs the tools the other nine use.

---

## 1. The investigative journalist

Tracks document churn on a committee: what was posted, then quietly removed;
which organizations kept supplying witnesses for a bill's hearings.
Deadline-driven; drafts with an assistant and verifies every claim against a
`reference` (`release_id` + `link_key`) so editors can re-check the exact
document.

1. **What documents did the committee publish and later remove this quarter?**
   (`removed_on`, hidden rows)
   *Expected:* tiny table, usually 0–3 rows per committee-quarter (only 450
   retirements ever); filename, title, `removed_on`, successor if any. Spikes
   cluster around party turnovers.
2. **Which organizations supplied more than one witness across the hearings on
   this bill?**
   *Expected:* grouped list, ~5–40 rows: org name, witness count (2–4 for the
   top), hearing count. Federal departments and one or two industry
   associations at the top; a long tail of singletons.
3. **Show every document whose only surviving copy is a recovery — what does
   each `identity_note` say it actually is?**
   *Expected:* tens to low hundreds depending on scope (12.6K of 355K docs ≈
   3.5%); notes mostly say "substitute/recovered, not verified original" — the
   tool refuses to claim it is the true copy.
4. **How many versions of this report exist, and which was the committee site
   actually serving?** (`document_editions`)
   *Expected:* 1–5 rows grouped by `version_keys`: usually a PDF+HTML sibling
   pair, occasionally a revised edition with a later date. Most documents have
   exactly one.
5. **Which documents on this topic vanished within 30 days of first capture?**
   *Expected:* rare, 0–5 rows; mostly captures replaced by a v2 pointing at a
   `successor_key`. A disappearance with no successor is the interesting row.
6. **What got posted in the three days surrounding that news event — by posted
   date, not document date?** (`date_kind`)
   *Expected:* a handful of rows where `first_captured` matches the window but
   `document_date` is often months older — backfilled archives, correctly
   flagged.
7. **Which hearings have zero surviving recordings, and does `meeting_coverage`
   say why?**
   *Expected:* a committee-level summary; a substantial minority — pre-YouTube
   hearings (2011–~2015), closed briefings — with reason codes, not silent
   zeros.
8. **Who testified on this bill in both chambers, in order of appearance?**
   *Expected:* 0–10 names, dominated by agency heads and Cabinet secretaries;
   each with paired House/Senate `event_id`s.
9. **Trace this document's URL history — status codes, attempts, last good
   date.** (`url_state`)
   *Expected:* one record per URL: attempts count, `last_status` (404/410),
   `last_good_at`. Churny committee URLs show dozens of attempts.
10. **Give me a citable reference for each removed document so my editor can
    independently verify.**
    *Expected:* a structured block per document: 64-hex `release_id` + 16-hex
    `link_key` + filename. Deterministic — re-running gives byte-identical
    output.

## 2. The fact-checker

"Did this nominee actually say that in 2019?" Pulls exact quotes with page
cites from bodies verified against recorded SHA-256 hashes, not paraphrases
from a blog. Relies on the no-OCR boundary: "no text found" is reported, never
guessed.

1. **Did this witness actually say "[quote]" — search the verified full text of
   every appearance.** (`section: "text"`)
   *Expected:* 1–3 matched snippets with page and character offsets, or an
   explicit "no match." Image-only PDFs: a clean "no extractable text" error —
   never a guess.
2. **Which page of the printed hearing does that statement appear on?**
   *Expected:* snippet JSON with `page` and surrounding text; one definitive
   answer.
3. **Was it spoken in the hearing or only submitted in writing?**
   (`witness_type`, `testified`)
   *Expected:* witness row with type/testified flags plus a separate `link_key`
   for any written statement — a distinction, not a yes/no.
4. **Has this official's exact wording on the topic changed between 2015 and
   2024?**
   *Expected:* side-by-side snippets from 2+ hearings with dates/pages; mutated
   phrasing of the same talking point rather than verbatim repeats.
5. **Does the archived PDF match what is on the committee's site today?**
   *Expected:* the archive's SHA-256 + suffix, then a live fetch compared — a
   binary hash match/mismatch. Occasional mismatches when committees re-post
   reformatted files.
6. **Is this "hearing date" the meeting date or the document date?**
   (`document_date_source`)
   *Expected:* one line: source ∈ {filename, content, meeting} + `date_kind`.
   Occasional filename/meeting disagreement, resolved explicitly.
7. **Did that dollar figure come from the CBO estimate or a member's opening
   statement?**
   *Expected:* two located snippets, one per document — the answer names which
   document each number lives in.
8. **Is the quote present in the PDF edition but absent from the HTML
   alternate?** (`alternates`)
   *Expected:* 1–3 format siblings; quote usually in both, occasionally
   PDF-only due to pagination artifacts.
9. **Confirm the full hearing title, chamber, Congress, and session for my
   correction notice.**
   *Expected:* canonical summary from the record — long, often ALL-CAPS House
   style — chamber, Congress, session, meeting date.
10. **This source is image-only — can the tool verify it at all?**
    *Expected:* an actionable error: "image-only PDF; no text extracted" — a
    reported failure, distinct from "not found."

## 3. The political science researcher

Longitudinal quantitative work: hearing counts by committee across Congresses,
witness appearance rates by organization, roll-call alignment. Lives in
`query_sql`. The immutable `release_id` is the methodological hook: a paper can
name the exact snapshot every number came from.

1. **Hearing counts by committee per Congress, 112th–119th — normalized by
   roster size.** (`committee_roster`)
   *Expected:* ~100–200 rows; busy committees (E&C, Appropriations, Judiciary,
   SASC) at 50–150/Congress, most others single digits. Normalized by roster
   (~30–60), top committees run 2–4 hearings/seat/Congress.
2. **Distribution of witness appearances by organization over time — which orgs
   dominate?**
   *Expected:* hundreds of orgs, steep head: federal departments, then industry
   coalitions and think tanks; an estimated 60–80% of orgs appear exactly once.
3. **Are bills with more subject-key hearings more likely to reach a floor
   vote?** (`meetings` → `bills.stage`)
   *Expected:* a 2×2 over ~52K bills: bills with ≥1 hearing enacted at perhaps
   3–10× the rate of zero-hearing bills — with selection bias as the finding,
   not causation.
4. **How does publication lag (`document_date` vs `first_captured`) vary across
   committees?**
   *Expected:* a distribution: median days-to-weeks, months-long tail from
   backfills; visible committee-house differences.
5. **What fraction of captured URLs eventually die, by year of first capture?**
   (`url_state.last_outcome`)
   *Measured (release e4538f00, 2026-11):* mortality does not rise with age —
   2012–13 cohorts stay ~99.5% alive. The one heavily dead group is a small
   legacy batch first seen 2016–17 (~6.5K URLs, under 1% of the corpus, ~90%
   dead — captured once and never successfully re-fetched). Overall ~3.5% of
   the 1.2M URL states are dead; outcomes stay coded, never guessed.
6. **What share of marked-up bills had a printed hearing first?**
   (`committee_records` → `list`)
   *Expected:* over ~20K committee records, a minority (20–40%).
7. **In the 119th, what is the lag from nomination referral to hearing?**
   *Expected:* right-skewed: median ~30–90 days, with a never-scheduled
   censored group the tool flags rather than averages over.
8. **Recording-coverage bias: which meeting types get archived to committee
   channels?** (`coverage_counts`)
   *Expected:* percentages by meeting type and Congress: near-total video for
   recent House oversight, sparse pre-~2016 and for closed sessions.
9. **Can I study witness gender over time here?**
   *Expected:* a refusal: no demographic field exists on witnesses. The correct
   output names the gap and suggests external joins (members have cross-IDs;
   witnesses do not).
10. **Pin every figure in my table to this `release_id` and emit the exact SQL
    as an appendix.**
    *Expected:* a generated appendix: each query, its row count, one
    `release_id` — and byte-identical re-runs because the selection is
    immutable.

## 4. The committee staffer

Needs a briefing book by Friday: who is on the dais, what each member has
asked at similar hearings, and every prior appearance of each witness with
their submitted documents. The "witness is an appearance, not a person"
distinction matters: the same name three times is three records.

1. **Build the dossier for Thursday's hearing: witnesses, their documents,
   recordings.** (`hearing_dossier`)
   *Expected:* one rich object: meeting metadata, 4–12 witnesses
   (name/position/org), their document `link_key`s, recording refs. One call.
2. **Has each witness testified before? Pull every prior transcript.**
   (`witness_transcripts`)
   *Expected:* 0–5 transcripts per witness; officials many, first-timers zero.
   Returns appearances — identity disambiguation stays with the staffer.
3. **What documents did each of them submit at their last appearance?**
   (`witness_documents`)
   *Expected:* 0–3 per witness, filenames like `statement-…-2023.pdf`; mostly
   written testimony only.
4. **Which of our subcommittee members also sit on committees hearing this
   bill?** (`rosters`)
   *Expected:* ~5–20 members × committee arrays; 2–3 assignments each is
   typical across the 113th–119th Congresses.
5. **What did the minority side ask this same witness last time?**
   *Expected:* snippets from questioning sections of the earlier transcript;
   thematic clusters (oversight letters, funding) rather than surprises.
6. **Summarize every hearing on this bill across both chambers.**
   (`bill_hearing_transcripts`)
   *Expected:* 1–6 rows; the classic shape is one House + one Senate companion
   hearing.
7. **Which related bills got hearings in prior Congresses and died — where?**
   (`related_bills`)
   *Expected:* several rows; most prior versions (70%+ by estimate) died in
   committee with zero hearings — the trail usually just stops.
8. **Does our 2019 field hearing have a recording, and is there a caption
   track?** (`recording_tracks`)
   *Expected:* a recording row with caption/transcript track URLs, or an
   explicit "none published"; older hearings lean audio-or-nothing.
9. **Current roster with ranks, titles, and party.** (`committee_roster`)
   *Expected:* 20–60 rows: name, party, title (Chair/Ranking/Member), rank.
10. **Find committee-stage records on this bill number from earlier
    Congresses.** (`committee_records.bill`)
    *Expected:* 0–15 rows (kind, sponsor, disposition); sparser the further
    back.

## 5. The opposition researcher

Building a nominee or incumbent file: nomination transcripts and votes, floor
amendments by sponsor, committee-stage records. Uses member cross-ID
relationships (FEC, GovTrack, OpenSecrets) as a bridge out to finance data —
while respecting that the tool deliberately stops at the bridge; the money
itself lives elsewhere.

1. **Every hearing transcript for nominee X, plus the committee's votes.**
   (`nomination_transcripts`, `nomination_votes`)
   *Expected:* 1–3 transcripts (nomination + confirmation), committee vote
   tally (favorable/unfavorable), floor vote totals — a compact dossier.
2. **All floor amendments sponsored by this member in the 119th.**
   *Expected:* 0–30 rows: amendment_id, purpose text, sponsor. Junior members
   near zero; chairs and leadership pile up. 119th-only boundary applies.
3. **This member's GovTrack, OpenSecrets, and FEC IDs so I can pull the money
   elsewhere.** (`cross_ids`)
   *Expected:* one member record: GovTrack ~always present, Wikidata usually,
   FEC possibly several IDs, older members sparse. IDs only — the money stays
   outside by design.
4. **Every document this member is tagged in — statements, letters,
   submissions.** (`bioguide_ids`)
   *Expected:* 0–100 rows, mostly hearing statements and
   entered-for-the-record items.
5. **Witnesses from organization Y across all committees: which bills were they
   supporting?**
   *Expected:* 5–50 appearances with the bill IDs each touched — an interest
   portfolio in one table.
6. **Give me the `vote_id`s for this bill's roll calls so I can pull member
   ballots from SpicyRegs.**
   *Expected:* per bill: `floor_votes[].vote_id` + totals. Pointers, not
   ballots — the documented handoff.
7. **Nominations heard in committee but never scheduled for floor action,
   119th.**
   *Expected:* dozens: mostly military and part-time board slots, each with a
   description string making the "why" legible.
8. **Did this nominee author any document that was later removed from a
   committee site?**
   *Expected:* almost always zero — which is what makes a single hit
   newsworthy.
9. **Is there any attendance record for this member's subcommittees?**
   *Expected:* a clean "no such data": coverage aspects track
   transcripts/recordings, not attendance. Rosters are the nearest thing.
10. **Everything this member said at hearings on this topic in prior
    Congresses.**
    *Expected:* a few dozen dated snippets for an active member; near-silence
    for a backbencher — itself a finding.

## 6. The legislative-history lawyer

Litigating statutory intent: hearing transcripts where a bill's language was
debated, CBO estimates, committee records from the amendment stage. Courts
still cite hearing records; needs the printed hearing's `package_id` to cite
the GovInfo original, not just the archive's copy.

1. **All hearings where this bill's key language was debated — include
   transcripts.** (text + `measure_keys`)
   *Expected:* 2–10 transcripts with phrase hits for contested provisions;
   0–1 for minor ones. Snippets, not paraphrases.
2. **Which committee reported the bill, and what do its markup records show?**
   (`committee_records`)
   *Expected:* a short factual answer: committee, date, kind — each line
   carrying a citation.
3. **Every CBO cost estimate across the bill's versions.** (`cbo_estimates`)
   *Expected:* 0–5 per bill: publication IDs, dates, cost language in text
   form, ordered by version.
4. **GovInfo `package_id`s for the printed hearings so I cite the official
   record.**
   *Expected:* one `CHRG-…`-style ID per printed hearing (or null, explained).
5. **Did the sponsor explain this provision's purpose at hearing?**
   (`sponsor_bioguide_id` → transcript)
   *Expected:* 1–3 passages from that hearing's text, tied to the sponsor's
   `bioguide_id`.
6. **Committee-stage amendments on this bill, 119th.**
   *Expected:* the bill's `amendments[]` with sponsors and descriptions —
   stamped 119th-only until the backfill lands.
7. **Prior-Congress versions of this bill and their hearing trails.**
   (`related_bills`)
   *Expected:* chains of 1–3 earlier-Congress attempts for persistent issues,
   each with its own (usually short) hearing trail. Bills begin 2007/106th.
8. **Full-text search the entire Congress's hearing bodies for this statutory
   term.**
   *Expected:* hundreds of hits for common words, a handful for distinctive
   phrases; capped at 200 rows with a `truncated` flag to respect.
9. **Nomination hearings that discussed this agency's authority.**
   *Expected:* 0–10 transcripts tied to that agency's nominees.
10. **Exact page cites for the three quotes going into the brief.**
    *Expected:* three ready-to-paste references: page + column context +
    document identity.

## 7. The advocacy-org policy tracker

A two-person shop with no data budget tracking a handful of bills through
committees. The `bill_hearing_transcripts` recipe is quietly the superpower —
it finds transcripts whose direct bill annotation is empty by walking meeting
subjects, catching hearings keyword alerts miss. Free, local, offline, no API
key.

1. **Pipeline status for our five bills: hearings, amendments, votes, CBO.**
   *Expected:* one dashboard row per bill: stage, latest action + date, hearing
   count, amendment count, vote totals, CBO list.
2. **Which hearings touched our bills without tagging them?**
   (`bill_hearing_transcripts`)
   *Expected:* a handful of extras (estimated 5–15% more) found via meeting
   subjects where document `measure_keys` is empty.
3. **Cosponsor counts for our bills as of this release.**
   *Expected:* one integer per bill per release — a snapshot, not a history.
   Trend = prepare two releases and diff; the tool says so rather than
   implying continuity.
4. **Scheduled hearings on our topic that have published nothing yet.**
   *Expected:* a short watchlist: future-dated meetings with zero coverage
   rows.
5. **Who testified against our bill, representing whom?**
   *Expected:* names + orgs from the bill's hearings; the tool supplies *who* —
   "against" stays a human inference from org identity.
6. **Which committees are demonstrably dead-ends for our issue?**
   *Expected:* a counts matrix: 2–4 receptive committees with 10–30 subject
   hearings, a long zero tail. Zeros are real zeros.
7. **Watch our issue's document set for removals and swaps.**
   *Expected:* usually an empty diff — removals are rare events (450 lifetime),
   so any hit matters.
8. **Our founder testified twice in 2023 — find both appearances and the
   videos.**
   *Expected:* two witness rows with `event_id`s, matched videos, caption
   tracks.
9. **Committee-stage activity on our bill this month.**
   (`committee_records`)
   *Expected:* 0–10 rows: markup/vote kinds with dates.
10. **Draft the one-page stakeholder update with inline citations.**
    *Expected:* assistant prose with inline `reference`s; every citation
    resolvable to a `link_key` that can be spot-checked.

## 8. The documentary producer

"Find me archival footage of that 2015 hearing, and the clip where the CEO gets
grilled." Works from recordings, videos, and committee channels; pulls caption
tracks to locate timestamps, and `meeting_coverage` to learn which hearings
have no surviving recording at all — before the edit bay discovers it.

1. **All surviving recordings for that hearing, with caption tracks.**
   (`recording_tracks`)
   *Expected:* 0–3 `video_key`s with WebVTT caption URLs and/or transcript
   PDFs.
2. **Which hearings on this topic have video, audio-only, or nothing?**
   (`meeting_coverage`)
   *Expected:* a coverage table: near-universal for recent House oversight,
   thinning going back and for closed sessions — with reasons.
3. **Find the timestamp where the CEO says "[phrase]" — search the caption
   track.**
   *Expected:* caption hits with `00:47:12`-style stamps; where only a PDF
   transcript exists, a page reference instead — clearly labeled which.
4. **Which committee channels posted this event, and what are the original
   URLs?** (`videos`, `channels`)
   *Expected:* 1–2 committee channels, original YouTube URLs intact for
   provenance.
5. **Videos posted by committee channels but never matched to a hearing.**
   (`channel_unmatched_videos`)
   *Expected:* per channel, potentially dozens: 67K videos vs 32K matches
   means a large unmatched pool — some unheard hearings, some studio fluff; the
   recipe hands over the shortlist, the producer curates.
6. **Duration and availability of every clip for the edit log.**
   *Expected:* durations (10 min–5 hrs), `available` flags — some gone from
   YouTube but archived — posted dates.
7. **Witness statements from that hearing to intercut with the footage.**
   (`witness_documents`)
   *Expected:* PDF list with names/titles — ready-made slates for intercuts.
8. **Every prior appearance of the whistleblower before 2020.**
   (`witness_transcripts`)
   *Expected:* 0–3 transcripts; often the one famous appearance is all there
   is.
9. **What exists for hearings before 2011?**
   *Measured:* meetings: empty. Documents: ~18K pre-2011 dated files, dense
   only from the 1990s (852 in the 1990s; the four pre-1990 rows are
   out-of-context content dates, not a paper-era corpus) — the 1901 endpoint
   was a misread artifact (ct-m94a). The boundary shapes the archive strategy.
10. **Provenance for licensing: the original posting URL and match basis for
    each recording.** (`recording_matches`)
    *Expected:* per recording: match basis (title/score/date), original URL,
    decision, status — enough to document where every second came from.

## 9. The government-documents librarian

Answers patron requests across two centuries of hearings. Cares about the
epistemology the tool enforces: missing table ≠ zero rows, alternates and
recovered substitutes flagged with `identity_note`, source URLs for every
claim. Points researchers at the bounded scope — a curated archive, not the
whole record.

1. **A patron's link is dead — do we hold an archived copy of that URL?**
   (`urls`)
   *Expected:* 0–1 hits against ~1.2M known URLs → a `list_row` → the archived
   document. Decent odds for anything a committee once posted.
2. **All formats and editions of this printed hearing.** (`alternates`,
   `document_editions`)
   *Expected:* 1–3 format siblings grouped by edition; most hearings have
   exactly one canonical PDF.
3. **Is this document genuinely absent, or does the table not exist for that
   era?**
   *Expected:* three distinct honest answers: "covered era, zero rows" / "table
   not published for that era" / "hidden row, exact reference required." The
   tool keeps them separate.
4. **The GovInfo package for this hearing, please.** (`package_id`)
   *Expected:* one ID string or an explained null (not all documents came from
   GovInfo).
5. **Verify the Congress and session from the document itself, not the
   catalog.** (`document_date_source`)
   *Expected:* parsed fields with source labels; mostly concordant, mismatches
   surfaced rather than silently reconciled.
6. **Are any of these recovered substitutes the true original?**
   (`identity_note`)
   *Expected:* most of the 12.6K recoveries explicitly labeled
   substitute/related — the note is the answer.
7. **What is actually here from before 1901?**
   *Expected:* documents: nothing before 1901. Committees/members: back to
   1789. A patron asking about the 1850s gets people and committees, but no
   hearing bodies.
8. **Find hearings by committee and date range only — no bill number.**
   *Expected:* paginated, capped at 100/page; filters collapse hundreds of
   results to a usable handful.
9. **Crosswalk this historical member to Wikidata for the patron's project.**
   (`cross_ids`)
   *Expected:* modern members: Wikidata Q-IDs mostly present; 19th-century
   members often blank — the gap is visible, not papered over.
10. **A stable citation for this record, including the release it came from.**
    *Expected:* `release_id` + `link_key` + filename: durable and re-resolvable
    in any future session on the same release.

## 10. The civic-tech builder

The meta-persona: a volunteer extending the site explorer, an external
dashboard, or QA-ing a new release. Uses `get_dataset_info` for schema
discovery and coverage gaps before writing code, and the MCP as a
conversational REPL over a candidate release before wiring it into anything.

1. **What tables, columns, and entity keys does this release publish?**
   (`table: "schema"`)
   *Expected:* complete per-table column lists (list: 19 cols, detail: 37 …),
   entity keys, views. Machine-readable ground truth.
2. **Which coverage gaps should my UI badge as "unavailable"?**
   (`coverage.gaps`)
   *Expected:* 4–6 named gap strings: rosters 113th–119th, amendments
   119th-only, nominations 119th-only, `url_variants` empty. Badge them, don't
   zero them.
3. **What do the published relationships say about joining witnesses to
   meetings?** (`relationship` selector)
   *Expected:* field-level mapping (`witnesses.event_id` →
   `meetings.event_id`), grain, one worked join example — generated from
   schema, not a hand-written wiki.
4. **Write and run "hearings per committee per month" — what does the SQL
   cost?** (`query_sql`)
   *Expected:* aggregates sub-second over 18K meetings; big unnest joins over
   the 1.2M-row `url_state` near the 10s deadline — and a timeout that is an
   error, not a hang.
5. **Which recipes are available that I could surface as one-click views?**
   (`recipe` selector)
   *Expected:* ~15 recipe IDs with required-tables and availability booleans.
6. **Row counts per table for my bundle-size budget.**
   *Expected:* the exact figures (355,608 / 172,948 / 52,279 / 12,770 …) plus
   per-shard rows for detail tables.
7. **What changed between the release I shipped and `e4538f00…`?**
   *Expected:* the MCP answers "one release only" — the documented workaround
   is two prepared data dirs diffed externally.
8. **Which rows are hidden, and does my site need to exclude them by default?**
   *Expected:* a small review-flagged fraction; UI filters by default. The
   asymmetry is deliberate — search hides them, exact reference + SQL still
   resolve them.
9. **Which upstream SpicyRegs tables could I join by ID?**
   (`upstream_relations`)
   *Expected:* 7 relations with parquet paths and generation hashes, join keys
   spelled out (`vote_id`, `amendment_id`, `(bill_id, bioguide_id)`).
10. **What error does a user see when a row busts the 128 KiB response cap?**
    *Expected:* an actionable error naming the oversized row and suggesting
    fewer columns or a slice — not a truncated mystery. Testing it is how the
    failure mode is learned to be honest.

## Confidence

Bet least on the magnitude estimates in journalist Q7, researcher Q3, Q6, and
producer Q5 (share-based guesses), and on anything involving human-motivation
ratios. Bet most on the shapes: every answer comes back as either bounded rows
with `reference`s, or a named refusal. Several of the best questions
(fact-checker Q10, researcher Q9, opposition Q6) are about the tool *refusing
to guess* — a feature wearing a boundary's clothes.
