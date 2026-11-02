# Release notes

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
  no longer resolve. No old-to-new mapping is published.
- **Links (ct-tk10).** From the first gated release onward, link keys that earlier releases
  published never vanish. A key redirects to the current document that holds its old
  document's primary key or one of its other keys. Failing that, it redirects to the single
  current document listed at one of the old document's exact source addresses. Every other
  key shows "This document is no longer in the archive", with the filename and release it
  was last published in. The first gated release also covers the 7,266 keys that c94bfedc
  published and 448651e7 dropped. Measured against 448651e7 itself, 7,203 of them redirect
  and 63 show a notice: 61 ZIP-member keys lost to the D1 archive-member defect, to be
  rechecked on the rebuilt candidate, plus a 500-error ZIP whose address three documents
  share, and one article that no current document lists.
