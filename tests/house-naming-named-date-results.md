# Complete named dates and their remaining text: results

The accepted run is
`.cache/filename-engine-comparison-20260929/named-date-remainders/`.
The extractor now keeps complete named dates, preserves the printed order of
independent dates, and passes the text after a leading named date through the
same fallback used for ordinary names and identifiers.

## Verified changes

The full comparison covers **333,368 basenames**. Strict results remain unchanged
for every input; all **2,557,981 extracted field spans** match the source.
**1,457 tests pass**, including 35 new tests. Existing native code meanings and
source guide definitions are unchanged. Generated JSON and ECMAScript checks
pass, and the comparison source hashes match the current implementation.

- **55 complete date occurrences in 47 filenames** replace contained month-first
  fragments. `5APR22` now exposes day `5`, month `APR`, and year `22`, instead of
  interpreting `APR22` as April 22. No century or meeting-date role is inferred.
- **158 filenames gain or refine a name/subject remainder** after a leading
  named date: 151 name assumptions and seven explicit document subjects. For
  example, `02JUN2020.FDAJNT.STMNT.pdf` exposes `FDAJNT.STMNT` separately from the
  date. These counts overlap with the date corrections.
- **194 filenames have field changes**. Three additional outputs only change
  the ordering of retained observations or alternatives.

Every field removal was reviewed. The 110 old date/day fields remain in the
suppressed fragment observations with identical metadata. Eleven numeric-prefix
assumptions become the day component of the full date. Twenty-two old name or
subject fields lose only the date prefix and its separators; their remaining
text stays extracted. The native omission audit has no unexplained omissions.

## What the comparisons rejected

The first candidate sorted all named dates by length. It restored complete
shapes but reversed independent dates in the actual `1MAR24 (Final_28FEB24)`
Coast Guard filename. The accepted ordering uses source position, with longer
matches first only when they start together.

The next candidate corrected date ordering but lost eight fallback names and
three refined subjects when the old numeric-prefix interpretation disappeared.
The remainder handoff fixes this, including older complete named-date forms.

A shortened name-only handoff then failed three constructed controls involving
an additional identifier or trailing date. The accepted implementation reuses
the entire existing fallback. `April22-Smith-42` retains name `Smith` and generic
identifier `42`; `5APR22-Smith-2024-02-29` retains the trailing date separately.
All rejected runs, failures and source snapshots remain in the comparison cache.

Invalid complete shapes such as `32APR22` retain their calendar warning rather
than becoming a valid inner date. Short years stay unspecified, independent
dates keep their order, and identifier protection and ZIP-name exclusion remain
in force. Every real filename with field changes was reviewed against its raw
text; synthetic controls are identified separately from corpus evidence.

This is reused development evidence, not a general accuracy percentage. Full
filename interpretation remains incomplete. Recurring statement abbreviations,
yearless day/month wording and revision labels in descriptive fields still
deserve review. Native corpus consumers are unchanged. Work remains local and
uncommitted.
