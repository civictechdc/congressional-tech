# Filename family comparison — 2026-09-29

Decision: Extend the current parser with reusable rules for the remaining BILLS
filename families, while preserving its existing interpretations and uncertainty.

Hypothesis: Missing family rules and overly strict mandatory fields explain most
of the 850 incomplete inner layouts. Family rules with optional slots should add
useful literal fields to at least 70% (595) without changing existing captures.
An alternative explanation is insufficient information in the filenames: apparent
coverage would then rise only by placing everything in an opaque descriptor.
Missing bill numbers cannot be recovered by either approach and must remain absent.

Arms: A is the current parser, frozen in
`output/filename-regex/family-experiment-20260929/filenames.py`. B adds a deliberate
bundle of family rules for appropriations, amendments, placeholders, print/local
identifiers and alternate title/version placement. Evaluate the bundle as a whole;
do not attribute its effect to a single change. Existing rules run first; new rules
apply only when no existing inner legislative layout matches.

Cases: All 850 retained gaps plus the full 275,654-name inventory for regression
checks. The gap population was previously inspected and is development data, not
an independent benchmark. Before implementation, author field expectations from
literal examples and constructed adversarial controls. Manually inspect the new
captures, including all unusual shapes, after the rules run. No PDF/XML content
labels or missing identities will be inferred.

Held constant: Exact input spellings, optional retained legislator reference,
tokenization, date handling and existing rules. One deterministic replay per arm;
no model calls, sampling temperature, network requests or downloads. Stop after
at most three candidate iterations and one final corpus audit, or 30 minutes.
Keep every candidate's source and comparison results, including failures.

Decision rule: Adopt locally within the user's requested continuation only if
at least 595 formerly incomplete names gain a family match and at least one
nonempty useful field beyond the old captures. An opaque subject/descriptor,
suffix or remainder alone does not count. Require exact reconstruction, exact
field spans, zero removed/changed old captures, zero competing full layouts,
passing declared field/negative controls and no observed unjustified semantic
claims in raw review. If the gate fails, report that failure and retain the
experiment; a narrower change requires a separately stated decision.

Limits: Source labels describe filename syntax, not verified document contents.
This experiment cannot establish behavior for unseen future naming conventions.
Local adoption is not a commit, push or deployment. The existing full-layout
metric is not a complete semantic-interpretation metric.

## Candidate findings before the final iteration

Trial 1 failed: overlapping families mislabeled AP00 as a sponsor and JES as
J + ES. Its 741 apparent useful gains include false interpretations and cannot
support adoption. Trial 2 removes those errors but still has one HRES/HR+ES
collision. It matches 841 layouts but adds useful fields to only 490 names,
below the unchanged 595 threshold. In 351 appropriations names, the recovered
fields already existed through search rules.

The final candidate adds an explicit bill-type capture to the appropriations
subject slot when that slot contains an exact published type. This recovers the
previously untyped HR/HRes prefix without treating arbitrary subjects as bills.
It also protects whole measure types before a separated title (HRES cannot
backtrack into HR + ES) and distinguishes explicit TextofHR wording from local
IDs. Additional assertions retain these observed failures as regression cases.
The original decision criteria remain unchanged. There will be no fourth
candidate to chase the remaining unmatched strings.

## Explicit bound revision after raw review

The third candidate passes the mechanical gate and full-inventory comparison,
but manual review finds seven placeholder names where a greedy optional letter
consumes the P in PIH and falsely labels IH. Therefore its semantic gate fails.
The original three-candidate/one-audit limit is retained above; revise it here
to permit one corrective pass and repeat validation solely for version-boundary
preservation. This is not an expansion to recover the nine residual names.
Coverage thresholds and all other acceptance criteria remain unchanged. Add
actual failing inputs and constructed PIH/PIS/RIH prefix controls, including
the analogous optional-letter boundary in local identifiers.
