# Release notes

Latest: [November 12, 2026 — archive ede659a056c0](2026-11-12-ede659a056c0.md).

Previous: [November 12, 2026 — archive 21fc049940bb](2026-11-12-21fc049940bb.md).

Each published archive release that changes keys or values against the live release gets
a note here, named `<YYYY-MM-DD>-<release id, first 12>.md`. The publisher's gates write
the source for each note:

- the accepted cause record, `model/jobs/release-causes/<base12>-<candidate12>.json`, which
  lists every difference from the previous release with its cause, count and tickets
  (gate 1), and every link the release corrects on purpose (below); and
- the release's `retired_links.parquet`, which counts the link keys that now redirect or
  show a removal notice (gate 2).

Render a note with:

```
.venv/bin/python -m viewer_publication.release_gate notes \
  --causes model/jobs/release-causes/<base12>-<candidate12>.json --base <base release dir> --candidate <candidate dir>
```

Notes are not part of the immutable release. Their counts exist only after the build, and
putting them in the release would force a second model run.

## Standing notices

- **Identifiers (ct-ktfe, owner decision 2026-11-02).** Witness IDs changed in release
  448651e7 (2026-11-01). `witness_key` values and `?witness=` links from c94bfedc and earlier
  no longer resolve. Release e145d24c389e adds mappings for historical occurrence-v2
  keys, including all 35,899 keys removed from e4538f00. Unambiguous keys redirect;
  ambiguous and unresolved mappings retain those states. This does not establish
  support for the earlier identifier scheme.
- **Links (ct-tk10).** From the first gated release onward, link keys that earlier releases
  published never vanish. A key redirects to the current document that holds its old
  document's primary key or one of its other keys. Failing that, it redirects to the single
  document at one of its old addresses that has the same text. Any other key shows "This
  document is no longer in the archive", with the filename and release it was last published
  in. Where other editions sit at the same address, the notice lists them; it never swaps one
  in. The first gated release also covers the 7,266 keys that c94bfedc published and 448651e7
  dropped. Measured against 448651e7, 7,134 of them redirect and 132 show a notice. 69 of
  those notices list the address's current editions: their bodies were read in full, 68 have
  different text (66 of the old bodies have none) and 1 has the same text but is a PDF the
  model does not fingerprint. 61 are ZIP-member keys lost to the D1 archive-member defect,
  to be rechecked on the rebuilt candidate.
- **Links answer the same file (ct-4qld).** A link key that the live release and the
  candidate both publish must reach a row that serves either the live file (the live row's
  saved body) or the file the key names (a body whose SHA-256 begins with the key). A row
  serves its saved body, its alternates and its recoveries. So a key may follow its file to
  another row, keep its file as an alternate or recovery while another body is shown first,
  or reach its own file when a wrong join is split. Anything else refuses the publish and
  names each key with its live and candidate file, unless the reviewed cause record names it
  as a correction (ct-4nax, owner decision 2026-11-10). A `corrections` entry is `{kind, key,
  live_body, candidate_body, decision, tickets}`: kind `link_key`, `lookup_key` or `address`,
  the key as the report prints it, both files' SHA-256, what was corrected and by which
  permanent record, and tickets that exist. A key passes only when an entry matches its kind,
  key and both bodies; an unnamed key, a key beyond the report's sample of 100 and an entry
  that matches nothing all refuse. The report lists the keys let through (`named_corrections`)
  and the release note lists each entry. The gate checks that the record names exactly what
  changed, not that the new file is the right document: that is the record's claim (ct-faan
  would prove it from the published rejection records). A vanished key, a successor that is
  not a published key, a key both published and retired (`published_and_retired`) and a check
  that could not run (a column the rule reads is missing
  from either release) refuse whatever the record says. The rule cannot tell whether an
  alternate or recovery recorded on a row is truly the same document (ct-u9y4). So a key whose live file is now
  only an alternate of a row that shows another body passes the rule but is listed
  (`link_rule.demoted_keys`) and counted in the group `links.parquet | live file now an
  alternate`, which needs a recorded cause: a correct rendition join and a wrong one look the
  same to the gate.
- **Lookups and addresses answer the same file (ct-wscb).** The same holds for every lookup
  key (`urls.parquet`) and address (`sources.parquet`) of a live document the candidate
  still holds. Neither names a body, so the test is: at least one row it reaches serves the
  live row's saved body or a body one of the live row's own link keys names. An address may
  hold several editions, and after a wrong join is split it may reach any of the live
  document's own files. A key or address the candidate dropped, and a document it removed,
  are reported as their own comparison groups. A correction for one names the file
  every row it reaches now shows (or, when it reaches rows showing distinct files, the sorted
  list of every such file's SHA-256). It cannot tell which file of a wrongly joined live document
  an address named (published `sources` and `urls` carry no body hash); `documents changed
  for a shared key` counts every address of a split row regardless of which sibling half it
  reaches, while `split rows` sends the split to a reviewed publish.

## Nightly publication (ct-ud0b)

The daily publish (`model/jobs/publish.json`, `automatic_causes: true`) can explain a
difference without a person only when every difference is a new row traced to receipts the
live release did not read, `url_state` bookkeeping those receipts imply, or a row a re-fetch
moved (both below). A new row is a new document, or a source
or lookup row on one. Each new document's body is joined to `captures`, and each receipt
line is read from raw. The receipt key must be outside the live release's receipt set (the
key list its input record names, `inputs/receipts/<sha256>.json.gz`), and the line must name
the body. The key's date does not matter (ct-gc99): the daily reads a backlog oldest first,
so its receipts are new to the release without being newer than it. Every capture line of a
new document must qualify, so a body the live release also read is not new. Any other changed or
removed value, a split or merge, a new key or address on a document the live release has, a
recovered document (its key is a link, not a body), or a row that cannot be traced still
needs a reviewed cause record. So does a night that adds more than 250 documents
(`AUTOMATIC_ADDITION_CAP`), more than 10 link keys on one added document or 500 across the
night (`AUTOMATIC_LINK_KEYS_PER_DOCUMENT_CAP`, `AUTOMATIC_ADDED_LINK_KEYS_CAP`), or more
than 50 source or lookup rows on one added document or 1,000 across the night
(`AUTOMATIC_ADDRESSES_PER_DOCUMENT_CAP`, `AUTOMATIC_ADDED_ADDRESSES_CAP`): the proof shows
where an added document came from, never that its title, date or meeting are right, so a
large batch or fan-out waits for a person.

A capture night always changes `url_state` (attempt counts and times on fetched addresses, newly
queued links). Since ct-9j3z each changed, added or removed row must be exactly what the lines
of the candidate's receipts outside the live set imply, folded by the model's own
`url_state_lines` over the capture table, each line in raw with its own `requested_url` equal to
the address (a line without one refuses): attempts grow by the new lines; the newest new line,
when later than the live one (a tie refuses), sets the latest attempt, and `next_attempt_at` is
its time plus the band of the published `recheck_meeting_date`, which must equal the live value
where the live release had scheduled the address unless a Congress.gov meeting update moved that
meeting's date (`_mark_moved_meeting_dates`, ct-rhqw), in which case `recheck_meeting_date`
equals the updated effective date and a row with no later new line moves `next_attempt_at` to the
live `last_attempt` plus its band under that date (checked over `held_receipts` in `capture_job`);
`last_good_at` is the later of the live value
and the newest new line the model's own good-fetch steps call good. A newly queued link's pages
(`linked_from`) must each come only from new receipts, traced like a new document's body. Any
other row that changed with no new line (a meeting link that moved), an unverified meeting date
move on a scheduled address, a removed address or any other column change still needs a record. An added
attempted address no longer has to have supplied a new document: a failed or repeated fetch is
still a fetch. Cannot see: a wrong meeting date on an address scheduled for the first time, or
whether a page really links its queued address; those are the model's. So one unattended night
may schedule at most 2,000 addresses for the first time with a meeting date
(`AUTOMATIC_FIRST_SCHEDULE_CAP`, beside the document cap): the scheduled capture is budgeted at
2,000 requests a night (`ARCHIVE_CAPTURE_REQUEST_BUDGET`, 2,000 on 2026-11-10), so an ordinary
night cannot make more first fetches, dated or not, and a catch-up or a hand run with a larger
budget gets a person. On 2026-11-10's pair at least 663 first schedules carried a date, 630 of
them among the 1,132 first fetches of the one 2026-11-08 capture day. The two numbers are
coupled by hand: raising the capture budget means looking at this cap again. A line's time,
status and outcome are the capture table's (raw is read for the request URL and bodies only); an
added row's other columns, such as `capture_disposition`, are not checked; a receipt that
replays an older line under a new key counts as one more attempt.

What it cannot see: a bug that adds only wrong rows from genuinely new receipts. A
code change that alters how new rows are built is invisible too, when no existing row
changes. Gates 2-5 still run on every nightly candidate.

## Re-fetched sources (ct-syp1, ct-uywf, ct-rhqw)

A source read again moves the rows that cite it. The comparison sets such a row apart as a
`verified` group flagged `refetch_only`, so it needs no cause entry. A video cache refresh and a
byte-identical meeting read may move only their citations, and a row that changed anything else
qualifies for nothing; a Congress.gov meeting update may move whatever its record states (below).
Every other verified group still stops an unattended night.

**Video cache refresh (ct-syp1).** `videos.record_sha` and `channels.record_sha` are the hash
of the cache file a row was read from, `videos.details_checked_at` is when it was fetched, and a
`recording_matches.source_ref` of the form `video_records:<hash>` cites the same file. The file
embeds fetch times, so the weekly refresh rewrites all of them with no content change:

- a channel: every other column equal, its old file went to one new file that came from that
  old file only, over all channels, the live release cites the new hash nowhere, and in
  `captures` both files are `pipeline-data` YouTube cache JSON captures at the same
  `youtube/youtube_NN.json` cache path (ct-xyo9);
- a video: every column but those two equal, the row cites its own channel's file in both
  releases, that channel passed the check above, and the check time is equal, or later than
  the live value and not later than the moment of comparison;
- a match: every column but `source_ref` equal, and the citation is that video's
  `record_sha` in each release.

Because the weekly refresh rewrites all 52 cache files at once (119/119 channels and 99.6% of
videos), no sub-100% row-count cap applies to citation-only rows; without `automatic_causes`,
any `refetch_only` group requires a reviewed cause record. Everything else in these tables
still needs a reviewed cause: a changed title, duration,
description or any other column, an added or removed row, and the citation change on a row
that changed anything else.

**Congress.gov meeting updates (ct-uywf, ct-rhqw).** Owner decision 2026-11-11, "Everything from
Congress.gov publishes": a Congress.gov meeting update publishes without a person, with a morning
report; only lost links or keys stop the night. A meeting is updated when the candidate's
successful detail read for that `event_id` names a body the live release cites nowhere (no witness,
no meeting read), in another receipt than its live read, later than it and not later than the
comparison, with non-Congress.gov status sightings and `house_xml_updated` unchanged; or when
Congress.gov states the meeting for the first time and its detail read names such a body with no
non-Congress.gov sightings, `house_xml_updated`, `transcripts` or single-meeting document
`measure_keys`. On it, set apart as verified groups flagged `refetch_only`:

- the explicit `UPDATE_COLUMNS` the record states (title, date, status and its sightings, sittings,
  committees, `subject_keys` when untouched by non-caption transcript changes or single-meeting
  document `measure_keys`, documents, videos, the update stamp, the detail read itself) and a first
  stated meeting's row. Never `house_xml_updated`, and `transcripts` only when a matched updated
  meeting's `videos` link or unlink an already-held recording with unchanged non-empty caption
  `tracks` (never GovInfo or committee transcripts); the outcome columns where the candidate cites
  the new read's body and the live outcome was publisher-based (a cancellation, or no evidence), or
  where an un-canceled update returns from `publisher_cancellation` to `unknown` /
  `no_outcome_evidence` with non-caption transcripts unchanged (since a print or transcript basis
  is another source and its reference is a release-local row that shifts with unrelated documents);
  and `rescheduled_to` / `rescheduled_basis` (`publisher_status` or `recording_on_later_twin`)
  between updated meetings (with unchanged transcripts) and unchanged or byte-identical re-fetched
  twins;
- its Congress.gov witnesses: new ones (re-key successors or not) whose body is the meeting's new
  read, so the proven read is the one that moved them; live ones removed with a non-colliding
  `unambiguous` map row naming a published same-meeting Congress.gov successor; every value changed
  on a pair of them on that meeting (names, organizations, panels, order); and `superseded_by` on a
  lower-priority same-meeting witness (`senate_page`, `mods`) newly superseded by one of them. This
  witness half is interim: carried witness keys (ct-46f3, the first slice of the witness-identity
  epic ct-woj3) end the re-keys;
- the `unambiguous` key-map rows resolving through `witness_rekey` to one of an updated or first
  stated meeting's Congress.gov witnesses (added where `old_key` belonged to that meeting's live
  Congress.gov witnesses or is absent from base witnesses as a `free_context_key` prior, or with a
  changed value on that meeting); held documents (`list.parquet`, `detail.parquet`) whose
  `witness_keys` gained or lost only witnesses of that document's own updated meetings, whose
  `meeting_keys` linked an unlinked held document to a matched updated meeting via a newly added
  witness, or whose meeting-derived `document_date` (with `document_date_source` /
  `document_date_status`), `congress`, `chambers`, `committee_keys` or generic witness-statement
  `title` moved solely from its linked meetings' updates (together with any resulting `list_row`
  permutation across `list`, `detail`, `links`, `urls`, `sources` and `recoveries` whose untouched
  rows keep relative order); added `nominations` and `bills` newly introduced in
  `new_update_subjects` (plus 1-hop `related_bills` neighbors of newly introduced bills);
  `publisher_link` rows of `recording_matches` matching `meetings.videos` (plus `claimed`
  `video_states_event_id` rows resolving `event_id`, `score`, `note` and `meeting_links` when a
  held video's `stated_event_ids` matches a first stated meeting) and the corresponding
  `meetings.videos` rows and `event_ids` changes of `recordings`; `meeting_coverage` (every coverage
  row of a first stated meeting, and on a matched updated meeting its `witnesses` aspect with
  unchanged non-caption transcripts, `recording` and `captions` when moved by `meetings.videos`
  without non-`publisher_link` match or caption/track changes, zero-count `transcript` jacket status
  with unchanged non-caption transcripts, and zero-count `documents` status); and `url_state`
  rescheduled `recheck_meeting_date` and recomputed `next_attempt_at` bands on URLs linked via
  `sources`, `meetings.document_references` or House meeting URL patterns.

Still stopping: anything the link rule refuses (a lost or changed link or lookup key, a removed
meeting); a removed witness key with no map row, an `ambiguous` or `unresolved` map row (lost keys
until dropped witnesses are kept as "no longer listed"), a map row whose successor is not published,
not on that meeting or not Congress.gov, or that turns `ambiguous` or `unresolved`, a map that
collapses distinct base occurrences; a first stated meeting claiming an existing unlinked base
document, a non-generic held document title edit, or a rescheduled non-document `url_state` address
linked only through `publisher_links` / `capture_source_contexts`; any row of another source (MODS,
House XML, Senate pages, aside from `superseded_by` pointing to an updated Congress.gov witness) or of a meeting not
updated (aside from an unchanged twin's `rescheduled_to` / `rescheduled_basis` to or from an updated
meeting); a column another source moves (GovInfo or committee `transcripts`, `house_xml_updated`, or
`subject_keys` carrying a single-meeting document's `measure_keys` or a non-caption transcript
change); a meeting Congress.gov only lists (no detail read); and any read or body the capture table
does not prove, or a new House meeting XML body in `captures` accompanying an updated meeting
(below). A byte-identical read moves only bookkeeping, which passes when every other column (or
`rescheduled_to` / `rescheduled_basis` to or from an updated meeting) is equal:

- `congress_gov_detail_observation`: only the locators of its two reads (time, receipt, line,
  capture index, body), each later than the live read, not later than the comparison and in
  another receipt; the successful read must move; the latest attempt's outcome may only go
  between `stored` and `unchanged`;
- `congress_gov_updated`: later, and only where the read names another body;
- `publisher_status_observations`: every live entry kept; a new entry only a live one seen again
  later.

The gate writes `meeting-updates.txt` (per meeting: title, date and status as they were and are,
witnesses, documents, videos and sittings added and removed, lost witness keys, any other column
that moved; marked stopped with its reasons when the gates refuse) and `meeting-updates.json`
beside `release-gate.json`; the nightly keeps both with the run's evidence and puts the report's
one line in `summary.json` (`meeting_updates`). Replayed on 2026-11-10's pairs, the rule sets
apart 23 updated meetings (2 first stated) and 8 byte-identical reads on 619db5f9e08e to
77673bfb8fcf, including the 4 new witnesses of meeting 119590, 25 added `nominations`, 8 added
`publisher_link` `recording_matches` and 4 added `recordings` (leaving 2 matches and 1 recording on
listed-only meeting 338820) and `meeting_coverage` (10 first-stated rows plus 2 basis, 3 count, 2
reason and 7 state changes on updated meetings; 54 blocking groups), and 31 updated meetings (13
first stated) and 9 byte-identical reads on 630164505301 to 619db5f9e08e, including 22 reordered
witnesses, 104+99 added `witness_key_map` rows (including 5 `free_context_key` priors), 10 added
`nominations`, 1 added bill (`119-s-5289`), 18 added `publisher_link` `recording_matches`, 9 added
`recordings` and `meeting_coverage` (65 first-stated rows plus 4 zero-count `transcript` state
changes; 73 blocking groups, with full-struct transcript comparison flagging 23 `transcripts`
changes); what still stops on those pairs is other sources (transcripts, transcript-based outcomes,
newly captured documents and recordings, the MODS reader change) and one meeting only listed.

These checks compare the candidate with the live release and read no file, so they show only
that the candidate is consistent with itself: a made-up hash applied to every row of one old
file would pass them. The nightly, which has no person, therefore also looks up every body the
candidate cites for the first time (cache files, witness records, meeting detail bodies) in the
capture table: it must be a captured body, and every receipt holding it must be absent from the
live release's receipt set. Every detail read a meeting names for the first time must be a
capture line at that receipt, line and index, outside the live receipt set, requesting the
read's address, holding its body (a byte-identical re-fetch names an old body in a new line) and
fetched at the read's own time, which the comparison requires later than the live read; and when
any Congress.gov meeting update is present, no new receipt in the capture table may hold a new
House meeting XML body accompanying an updated meeting (catching a null-status, unchanged-stamp
House XML read, which leaves no trace in `meetings.parquet` yet leads title, date and videos). A
reviewed publish has the comparison and the reviewer. Cannot see: whether the body holds the
published values; a Senate committee page fetched on the same night without moving status
sightings; or a multi-meeting document's `measure_keys` already present in base documents entering
an updated meeting's `subject_keys` on the same night.

A cause record drafted against the comparison before these rules (2026-11-11) no longer matches
after them: the exempt rows leave their groups, so a recorded count is too large and an entry for
a group that is now verified is stale. On 619db5f9e08e to 77673bfb8fcf, for example, the meetings'
`changed congress_gov_detail_observation` group falls from 32 rows to 3 and the
`witness_key_map | changed basis` entry has no group left. Redraft such a record from a fresh
report.
