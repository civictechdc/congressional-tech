# Release notes

Latest: [November 7, 2026 — Congress Explorer 0.6.2 / 5d24699ad9fa](2026-11-07-5d24699ad9fa.md).

Previous: [November 5, 2026 — e145d24c389e](2026-11-05-e145d24c389e.md).

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
traced to receipts newer than the live release. A new row is a new document, or a source
or lookup row on one. Each new document's body is joined to `captures`, and each receipt
line is read from raw. The receipt key must be outside the live release's receipt set and
dated after the newest of them, and the line must name the body. Any changed or removed
value, a split or merge, or a row that cannot be traced still needs a reviewed cause record.

What it cannot see: a bug that adds only wrong rows from genuinely new receipts. A
code change that alters how new rows are built is invisible too, when no existing row
changes. Gates 2-5 still run on every nightly candidate.
