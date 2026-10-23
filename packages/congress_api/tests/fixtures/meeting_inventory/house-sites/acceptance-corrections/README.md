# Frozen House acceptance regressions

These 47 gzip files contain exact retained HTML bytes. `manifest.json` records
each original page URL, decompressed SHA-256, compressed SHA-256, raw source-tag
ranges, reviewer finding references, and parent judgments. Gzip timestamps are
zero. No fixture was rewritten to simplify its markup.

The confirmed set covers 113 distinct page-target pairs on 42 pages:

- 46 usable omitted targets must remain exact source-designated references.
- 49 document targets must retain their references without their confirmed wrong
  kinds. The frozen audit permits broad `other`; a more specific kind is separate
  enrichment.
- Eight repository, registration, or related-coverage targets must remain page
  links rather than documents. Two also have confirmed kind contradictions.
- Ten malformed-host or site-root-fragment references must retain literal hrefs,
  labels, source document roles, and uncertainty in metadata. They must not become
  repaired or bare-root downloadable URLs.

The category counts are 56 omissions, 51 kind contradictions, and eight false
promotions. Their sum is 115 because of the two overlapping categories. The
independently verified union is 113, not 115.

Five additional pages supply ten unresolved controls: bill landing links, an
unlabeled image, a malformed scheme, an href containing escaped HTML, four stale
non-anchor spans, and a Testimony/Bio filename conflict. Their passing guards
verify preservation and avoid unsupported inference. They do not establish that
these sources are clean or resolve their ambiguity. In particular, the filename
conflict has no required document kind.

All source and adjudication pins are relative to the frozen audit directory
named in the manifest. The test suite uses only the checked-in gzip files and
manifest; that external audit directory is not required to run it. Redirect
labels remain labels, and no test fetches a destination or assumes its contents.
