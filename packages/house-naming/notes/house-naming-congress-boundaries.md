# Congress wording and ambiguous numbered titles

Decision: preserve explicit Congress wording while preventing joined title digits
from becoming a falsely certain bill number.

Observed: `BILLS-118HR2534116thCongressih.pdf` currently yields measure number
2534116. Its retained Congress.gov record names H.R. 2534 from the 116th Congress.
The filename alone lacks the separator needed to select that split. All 160
filenames containing Congress were inventoried. The wider ordinal scan also
found ordinary titles beginning `the`, `Stephen` and `Third`; those are controls,
not ordinal boundaries.

Hypothesis: one shared field-boundary check can reject the ambiguous numbered
interpretation in strict validation and preserve the same raw digits under an
explicitly uncertain lexical field. The existing descriptive-draft fallback can
retain the complete title without introducing a new catalog kind. It must not
derive the externally supplied bill number or historical Congress from this
filename. The existing free-text reference reader already avoids ordinal tails.

Also extend literal Congress wording to the observed `for the`/`of the` joined
forms, non-ordinal numbers followed by a separator, and trailing local digits.
Keep primary Congress distinct, preserve ordinal warnings, and protect witness
identifiers, larger numeric runs, percent escapes and Congressional topic words.

Arms: accepted `planning-wording`, historical native/strict `drafts-final`, and
the candidate. Hold the 333,368 inputs fixed. Inspect the original retained
meeting record and test the actual failure plus ordinary-title controls.

Gate: this corrects one known strict-parser result, so unconditional strict
equivalence is the wrong gate. Retain an exact before/after expectation for that
one source filename and its reason. The comparison must reject any unlisted
strict change or stale/unused correction. Preserve all other complete outputs
except reviewed new Congress fields. On the corrected name, require identical
literal spans and bytes, removal of the false primary measure number, an explicit
ambiguity diagnostic, and the unchanged raw title in the descriptive fallback.
Run focused and regression tests, full comparison, typed-adapter checks, native
omission audit and corpus checks. Preserve failed trials.

Reuse existing harnesses; no downloads or dependencies. Each full run has a
30-minute limit. These are development cases, not unseen accuracy evidence.

The shared Congress rule's description will say "Congress reference" rather than
"ordinal Congress reference" now that a separated non-ordinal form is supported.
Permit only that description change on existing Congress observations; retain
their complete fields and other output unchanged. This is reported separately
from newly extracted fields.

The follow-up reference scan found the same defect in a secondary reference:
`BILLS-115HR5759ih-HR575921stCentAct.pdf` assigns the final digits to H.R. 575921.
Apply the same uncertainty rule to `measure-reference` fields, including retained
suppressed candidates, while preserving the unambiguous primary H.R. 5759.
This extends the shared boundary check to its other consumer, without selecting
any particular split or changing the strict record for that filename.
