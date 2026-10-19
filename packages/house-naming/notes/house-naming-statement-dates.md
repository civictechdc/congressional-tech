# Statement abbreviations and incomplete printed dates

Decision: extract recurring statement abbreviations and yearless named dates
without guessing missing source text or changing strict naming records.

Hypothesis: the existing named-date recognition can support day/month forms with
no year and preserve three-digit year spellings with an explicit warning.
Literal, bounded Stmt/STMNT/SMNT labels and uppercase terminal STMNT/SMNT after a
leading named date can expose useful wording without assigning an official
document code. Unrelated word endings and protected identifiers must stay intact.

Arms: frozen native/strict results in drafts-final, previous House extraction in
named-date-remainders, and this deliberately bundled candidate. The reused
333,368-name inventory is development evidence, not an unseen accuracy sample.

Cases: 132 inventory names containing stmt/stmnt/smnt and 70 discovery matches
for day/month wording (including already recognized dates and UUID controls).
Raw discovery rows are retained in statement-date-inventory.json. Actual examples
include 05JUN2019GraySMNT, 02JUN2020.GAO.STMNT, BEGICH stmt, Updated 13 APR,
and 16DEC202BATEMANSTMNT. Constructed controls cover word endings, malformed
year widths, leap dates, whole identifiers, structured witness slots, long inputs,
and multiple dates. Source labels do not independently verify document contents.

Hold constant: native parser, official guide definitions, strict records, corpus,
and existing comparison/audit harness. No downloads or person-name vocabulary.
Run focused tests before one full comparison and audit, each bounded to 30 minutes.

Accept only if strict results and existing code meanings remain unchanged, every
raw field span remains exact, yearless dates gain no inferred year, malformed
years receive no calendar candidate, and every removed/changed prior field has a
reviewed explanation. Review all changed outputs, including fallback interactions.
Retain failures and source hashes. Lossless preservation and fallback coverage do
not establish complete semantic parsing.

Fixture correction before the corpus run: two initial negative controls assumed
16DEC2 and 16 DEC 2 had no possible date. The existing month-first rule can read
DEC2/DEC 2 as December 2. Preserve that alternative; the new behavior must not
discard the final digit to invent a yearless 16DEC date. The corrected assertions
explicitly preserve the old alternative. The initial failure is retained in
statement-date-focused-initial.log.

Full-corpus correction: reject statement-dates-first. Its month-first boundary
removed 18 prior month/day candidates when unsupported following digits might be
time, a duplicated upload suffix, or a date range. Preserve those candidates with
their unspecified-year note. A new yearless candidate also read %20Feb in one
literal Content-Disposition string as 20 Feb; exclude percent-prefixed byte
fragments without URL decoding. Add raw regressions for these cases. A constructed
compound-label control also requires one Opening STMNT label rather than adding
a redundant contained STMNT suffix. All initial-run outputs and source snapshots
remain retained. The next full run must satisfy the original field-retention
criteria and these stronger controls.
