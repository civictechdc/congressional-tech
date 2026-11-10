# Release notes

Latest: [November 10, 2026 — archive 619db5f9e08e](2026-11-10-619db5f9e08e.md).

Previous: [November 8, 2026 — archive 630164505301](2026-11-08-630164505301.md).

Each published archive release that changes keys or values against the live release gets
a note here, named `<YYYY-MM-DD>-<release id, first 12>.md`. The publisher's gates write
the source for each note:

- the accepted cause record, `model/jobs/release-causes/<base12>-<candidate12>.json`, which
  lists every difference from the previous release with its cause, count and tickets
  (gate 1); and
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
  names each key with its live and candidate file; like a vanished key, no cause record
  overrides it. If a column the rule reads is missing from either release it refuses too: a
  check that could not run is not a pass. It cannot tell whether an alternate or recovery
  recorded on a row is truly the same document (ct-u9y4). So a key whose live file is now
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
  are reported as their own comparison groups. It cannot tell which file of a wrongly
  joined live document an address named.

## Nightly publication (ct-ud0b)

The daily publish (`model/jobs/publish.json`, `automatic_causes: true`) can explain a
difference without a person only when every difference is a new row traced to receipts the
live release did not read, or `url_state` bookkeeping those receipts imply (below). A new row is a new document, or a source
or lookup row on one. Each new document's body is joined to `captures`, and each receipt
line is read from raw. The receipt key must be outside the live release's receipt set (the
key list its input record names, `inputs/receipts/<sha256>.json.gz`), and the line must name
the body. The key's date does not matter (ct-gc99): the daily reads a backlog oldest first,
so its receipts are new to the release without being newer than it. Every capture line of a
new document must qualify, so a body the live release also read is not new. Any other changed or
removed value, a split or merge, a new key or address on a document the live release has, a
recovered document (its key is a link, not a body), or a row that cannot be traced still
needs a reviewed cause record. So does a night that adds more than 250 documents
(`AUTOMATIC_ADDITION_CAP`): the proof shows where an added document came from, never that
its title, date or meeting are right, so a large batch waits for a person.

A capture night always changes `url_state` (attempt counts and times on fetched addresses, newly
queued links). Since ct-9j3z each changed, added or removed row must be exactly what the lines
of the candidate's receipts outside the live set imply, folded by the model's own
`url_state_lines` over the capture table, each line in raw with its own `requested_url` equal to
the address (a line without one refuses): attempts grow by the new lines; the newest new line,
when later than the live one (a tie refuses), sets the latest attempt, and `next_attempt_at` is
its time plus the band of the published `recheck_meeting_date`, which must equal the live value
where the live release had scheduled the address; `last_good_at` is the later of the live value
and the newest new line the model's own good-fetch steps call good. A newly queued link's pages
(`linked_from`) must each come only from new receipts, traced like a new document's body. A row
that changed with no new line (a meeting link that moved), a meeting date that moved on a
scheduled address, a removed address or any other column change still needs a record. An added
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

## Video cache refresh (ct-syp1)

`videos.record_sha` and `channels.record_sha` are the hash of the cache file a row was read
from, `videos.details_checked_at` is when it was fetched, and a `recording_matches.source_ref`
of the form `video_records:<hash>` cites the same file. The file embeds fetch times, so the
weekly refresh rewrites all of them with no content change. The comparison sets such a row
apart as `verified`, so it needs no cause entry:

- a channel: every other column equal, its old file went to one new file that came from that
  old file only, over all channels, and the live release cites the new hash nowhere;
- a video: every column but those two equal, the row cites its own channel's file in both
  releases, that channel passed the check above, and the check time is equal, or later than
  the live value and not later than the moment of comparison;
- a match: every column but `source_ref` equal, and the citation is that video's
  `record_sha` in each release.

Everything else in these tables still needs a reviewed cause: a changed title, duration,
description or any other column, an added or removed row, and the citation change on a row
that changed anything else.

That check compares the candidate with the live release and reads no file, so it shows only
that the candidate is consistent with itself: a made-up hash applied to every row of one old
file would pass it. The nightly, which has no person, therefore also looks up every file hash
the candidate cites for the first time in the capture table: it must be a captured body, and
every receipt holding it must be absent from the live release's receipt set. A reviewed
publish has the comparison and the reviewer. Neither can see whether the file holds the
published values.
