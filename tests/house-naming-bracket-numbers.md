# Preserve trailing bracketed numeric components

Decision: expose numbers in terminal `(digits)` and `[digits]` components
without inventing a copy count, revision, report part or document sequence.

Observed: 150 retained names have this surface shape. Several established
layouts leave it inside `suffix`; other names retain the entire string as a
fallback assumption. `MAUREEN RIORDAN Resume (62621).pdf` already has a plausible
short-date reading, which must keep precedence. `ABC Testimony (00303050).pdf`
contains an invalid compact date candidate and must retain every leading zero.

Hypothesis: one terminal-bracket rule, using the existing `local_number_token`,
can expose unclaimed numeric components after date and concrete-ID recognition.
Read before implementation from the accepted `title-years-final` outputs and
record all expected additions and excluded owned spans. Do not reinterpret
assigned witness names, amendment identifiers, valid dates or query strings.
The new rule adds fields without deleting prior observations or assumptions.

Arms: current extraction versus one catalog rule. Keep settings, inventory,
native/strict historical baseline and the existing exact Congress-boundary
correction fixed. Compare every one of the 333,368 outputs; remove only the
recorded new observations when testing preservation. Require exact spans,
leading-zero preservation, typed/engine equivalence, passing regression and
mechanical checks, and no new native field losses. Investigate unplanned changes.

Inspect retained source associations for hearing publications, testimony and
witness-list examples. No downloads or content classification. Test matched and
mismatched brackets, dates, concrete slots, chained extensions, query suffixes
and plain trailing numbers. Bound each full run to 30 minutes. Keep failed runs
and their evidence. These reused filenames are development data; recognizing
this syntax does not prove the role of the printed number.

Pre-edit discovery predicts 149 added numeric fields across 149 filenames.
The sole excluded candidate is the existing `62621` short-date reading. Retained
source observations confirm exact URL and link-title spellings for a Senate
hearing publication, Boyd's testimony, and a witness list. None supplies the
meaning of the bracketed number, so the implementation leaves that role unknown.
