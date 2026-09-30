# Amendment source forms: results

Accepted run: `.cache/filename-engine-comparison-20260929/amendment-source-forms/`.
Previous accepted extractor: `remarks-wording/`.

**204 filenames gain 552 fields.** The extractor retains numbered references
before hanging pdf suffixes and complete compound amendment identifiers, with
their literal local V-number components. All 333,368 strict results remain
unchanged. Every one of the 915 unique prior fields on changed inputs retains
its original metadata; no prior field is removed.

| Source family | Filenames | Additional fields |
| --- | ---: | ---: |
| Hanging pdf after an amendment identifier | 156 | 312 |
| Local identifiers such as `1v1` and `1v2` | 48 | 240 |

| Filename | Previous output | Additional metadata |
| --- | --- | --- |
| `alsobrooks-s163-amendment-1pdf` | Native: Senate bill 163. House: bill, name/number assumption and hanging suffix. | Marker `amendment`, identifier `1`. Existing bill, assumption and suffix fields remain. |
| `02-10-21_rep._velazquez_amendment_1v2.pdf` | Native: extension and date. House: those plus remaining name text. | Marker `amendment`, whole identifier `1v2`, local number `1`, marker `v`, printed revision number `2`. |
| `09-21-22_meuser_amendment_1v2_tally_sheet.pdf` | Extension, date and remaining text. | The same compound fields; the original name text, including `tally_sheet`, stays available. |

These fields do not establish a floor amendment number, GovInfo bill-text
version, identity, or verified revision history. The whole source identifier
remains available alongside its V-shaped components. Other letter/digit forms
remain unsplit; constructed tests cover `1a2` and leading zeros. Existing
references and protected witness/sponsor identifiers do not gain duplicates.

The source discovery contained 313 apparent number candidates. The other
**109 candidates overlap dates or opaque IDs** and remain excluded. Examples
include the UUID after `S.1542_Managers_Substitute_Amendment_` and the short date
in `hr-31-managers-amendment-052219`. The full comparison found exactly the 204
intended additions, with no further active source-form matches.

**1,912 tests pass**, including 28 new cases. Before implementation, 14 new
positive tests failed and 14 controls passed; both logs are retained. Generated
JSON, ECMAScript and whitespace checks pass. All 2,571,066 observed source spans
validate. The omission audit finds no unexplained native omissions, and the
all-field reviewer reports no losses or changed metadata. Native code, prior
guide rules, code meanings and strict schemas remain unchanged; source hashes
match the comparison snapshot.

The accepted directory contains source snapshots, complete outputs, every
changed field, before/after source examples, validation logs, the reused
preservation checker and a hash-verified manifest. The discovery retains URLs
from Senate HELP and the House meeting documents, including the paired Velazquez
`1v1`/`1v2` filenames. No document download was needed.

The broader residual audit identified 967 filenames containing `SENR`, all with
retained source URLs on `www.energy.senate.gov`. Their repeated committee,
subcommittee and meeting wording is the next substantial source family to
investigate. It has not yet been implemented. Reused development-corpus evidence
does not prove complete semantic coverage. Changes remain local and uncommitted,
and application consumers remain unchanged.
