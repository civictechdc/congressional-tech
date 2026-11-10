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

## Nightly publication (ct-ud0b)

The daily publish (`model/jobs/publish.json`, `automatic_causes: true`) can explain a
difference without a person only when every difference is a new row and every new row is
traced to receipts the live release did not read. A new row is a new document, or a source
or lookup row on one. Each new document's body is joined to `captures`, and each receipt
line is read from raw. The receipt key must be outside the live release's receipt set (the
key list its input record names, `inputs/receipts/<sha256>.json.gz`), and the line must name
the body. The key's date does not matter (ct-gc99): the daily reads a backlog oldest first,
so its receipts are new to the release without being newer than it. Every capture line of a
new document must qualify, so a body the live release also read is not new. Any changed or
removed value, a split or merge, a new key or address on a document the live release has, a
recovered document (its key is a link, not a body), or a row that cannot be traced still
needs a reviewed cause record.

What it cannot see: a bug that adds only wrong rows from genuinely new receipts. A
code change that alters how new rows are built is invisible too, when no existing row
changes. Gates 2-5 still run on every nightly candidate.

## Video cache refresh (ct-syp1)

`videos.record_sha` and `channels.record_sha` are the hash of the cache file a row was read
from, `videos.details_checked_at` is when it was fetched, and a `recording_matches.source_ref`
of the form `video_records:<hash>` cites the same file. The file embeds fetch times, so the
weekly refresh rewrites all of them with no content change. The comparison proves such a row
itself and reports it `verified`, so it needs no cause entry on any publish, reviewed or
nightly:

- a channel: every other column equal, and its old file went to one new file that came from
  that old file only, over all channels;
- a video: every column but those two equal, the row cites its own channel's file in both
  releases, that channel passed the check above, and the check time is equal or later;
- a match: every column but `source_ref` equal, and the citation is that video's
  `record_sha` in each release.

Everything else in these tables still needs a reviewed cause: a changed title, duration,
description or any other column, an added or removed row, and the citation change on a row
that changed anything else. What it cannot see: whether the new hash is a real file's, or
whether that file holds the published values.
