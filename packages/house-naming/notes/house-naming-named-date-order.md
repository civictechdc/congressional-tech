# Complete named dates before contained candidates

Decision: correct extraction of complete named-date shapes such as 5APR22 and
22JUN21, which currently lose their day/year split to an earlier month-first
candidate. The native parser retains both candidates; the House extractor should
prefer the complete shape and retain the contained alternative as suppressed.

Hypothesis: combining the two existing named-date rules at their current search
priority and considering longer shapes first fixes the loss without new regexes,
assumed centuries or changed primary naming records. Preserve invalid complete
date shapes with their calendar warning; do not replace them with a valid inner
month/day fragment. Preserve higher-priority identifier protection.

Compare saved native/strict outputs in drafts-final, the prior House extractor in
local-families-reviewed and the candidate. Hold all source definitions, regexes,
the 333,368-name corpus and native code fixed. Reuse calendar validation between
field construction and tests. Cases include actual 5APR22, 7Mar23 and 22JUN21,
both date orders, four-digit years, leap/invalid dates, independent multiple
dates, identifier-embedded dates and long invalid input. The initial raw outputs
are retained in named-date-overlap-before.json at the cache root.

Accept if complete day/month/year components are available, original alternatives
remain inspectable, strict results and code meanings are unchanged, and every
changed or removed old field has a verified named-date/protection explanation.
Correcting an old fragment's interpretation may replace its day field with a
year field; raw spelling must remain. Review all changed outputs. Focused tests
precede one full comparison and omission audit, each bounded to 30 minutes.
Retain failures and source hashes; reused cases are development evidence, not
an unseen accuracy benchmark. No downloads.

Raw-review correction: the first complete-corpus candidate preserved both dates
but reordered independent dates by length, including the actual Coast Guard
1MAR24 / Final_28FEB24 filename. Two stronger ordering assertions fail on that
candidate. Retain it as rejected in named-date-order. Use source-position order
with longest-match tie breaking: containing complete dates start before or with
their fragments, while independent dates retain printed order. The reviewed run
must pass both new assertions as well as the original criteria.

Field-loss audit correction: the source-ordered candidate correctly removes
numeric-prefix assumptions but also leaves eight fallback names and three
refined subjects without their extracted remainder. Retain that candidate as
rejected in named-date-reviewed. A selected leading named date must hand the
remaining text to the existing name/subject fallback, including other already
recognized leading named-date forms. Preserve the source date and its warning,
suffix cleanup and ZIP exclusion. Inspect every resulting remainder change.

Fallback-control correction: the first remainder candidate used only the final
assumed-name rule. Three constructed controls show it loses a trailing identifier,
a leading identifier, or a trailing date after the named-date prefix. Retain it
as rejected in named-date-final. Reuse the entire existing fallback implementation
for the remainder and ordinary root fallback instead of maintaining two policies.
