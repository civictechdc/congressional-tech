# Close reviewed native differences without hiding new losses

Decision: distinguish the 19 previously reviewed native-field refinements from
unreviewed omissions, using exact cases and independently retained source text.

Observed: five `KOOO395` amendment names replace an old opaque suffix with raw
sponsor-shaped text, amendment marker and amendment number. Seven `ispdf` names
separate the recognized `is` version from hanging `pdf`, moving an empty suffix
boundary. The generic omission auditor still reports these as `needs_review`.

Hypothesis: an explicit, bounded set of reviewed native/current observations
can account for these cases without changing either parser or the native oracle.
Require the exact filename, original rule and complete old field, plus every
reviewed replacement observation. A missing field, changed meaning, different
filename or newly omitted field must remain unreviewed. No broad regex waivers.

Inspect retained source associations before writing the acceptance data. Compare
the entire 333,368-name native/House audit before and after this accounting
change. Require exactly 19 reclassifications across the 12 reviewed filenames;
every other omission and all fallback comparisons must remain unchanged.
Require the current extraction outputs themselves to remain byte-equivalent
after decompression. Exercise mutation controls that remove replacement data or
change its meaning, filename or original field. Run the regression suite and
source/hash checks. Keep failed trials. Bound each full run to 30 minutes; use
saved inputs and no new downloads.

This addresses audit accuracy, not semantic completion. Truncated source names
and ambiguous titles do not become fully understood because these native
differences are accounted for.

Design refinement before implementation: avoid a permanent filename exception
list. These cases have three mechanically checkable differences: an uncoded
opaque suffix covered by specific replacement fields, an uncoded version split
into a catalog-backed version and hanging `pdf`, and an empty suffix whose
boundary moves before that same hanging `pdf`. Add those narrow accounting
categories with regression controls rather than accepting arbitrary changes to
named files. No coded value or candidate may be waived; broad descriptions and
fallback names cannot count as specific replacement fields. The whole-corpus
acceptance condition remains exactly the same 19 reviewed reclassifications,
with no change to any other row or either parser.

Source review reads 17 retained inventory entries, all five original House XML
entries (which themselves spell `KOOO395`), and all seven saved Senate redirect
receipts (which end in canonical `...is.pdf` filenames). This supports keeping
the malformed sponsor token literal and the printed `is`/`pdf` split. It does
not establish a valid corrected Bioguide ID or actual current bill status.
