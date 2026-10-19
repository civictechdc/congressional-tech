# House filename metadata upgrade — 2026-09-29

Authorized scope: implement the seven recommendations from the full filename
comparison, with the PDF cross-check correction. Preserve `conference-numbered`
as a source-backed naming convention; use a neutral published-report record
when inferring metadata from an arbitrary filename. Keep original source text,
definitions, examples and input spellings.

Changes: two/four-digit fiscal years and structured appropriations descriptions;
publication suffix metadata; unnumbered amendment subjects; observed bill,
committee-print and vote layouts; HTML publication extensions; whole-slot
Bioguide syntax classification for witness identifiers.

Check against all 333,368 retained inputs in `implemented-final`. Preserve all
202,063 prior acceptances and their values, allowing documented kind migrations
when a source convention parses to a shared record. Keep raw description/suffix
fields alongside derived values. Check derived-field consistency on render,
canonical render/reparse, extension restrictions, calendar dates, ambiguity,
and counterexamples for bill/date/revision extraction from identifier slots.
Additional coverage is measured, not promised for every broad internal regex
match. No new downloads or source-content accuracy claims.
