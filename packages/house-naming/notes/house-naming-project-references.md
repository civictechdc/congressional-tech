# GSA-style project references

Decision: expose structured reference components currently hidden in descriptive
text, using the observed `PDC-0002-WA21` family.

Hypothesis: one shared literal pattern can retain the three code segments and
the trailing two digits across House and Senate filenames. The middle identifier
must remain whole even when its digits resemble a date. Codes must not acquire
guessed locations, a century, event dates or a resolved project identity.

Arms: accepted `resolution-references`, frozen native/strict `drafts-final`, and
the candidate rule. Use the same 333,368-name inventory and existing harnesses.

Observed before implementation: a bounded scan finds 77 names. Saved House XML
for meeting 111077 identifies several as GSA resolutions and retains their
codes in filename metadata. `POK-00460072-OK20` corresponds to a source description
containing `POK-0046/0072-OK20`; do not reconstruct the missing slash from the
filename. `PIL-0303-FY21` and `POH-0192-FY20` already expose literal FY fields;
keep those observations alongside the larger reference.

Cases: review all selected names and varied raw source examples; include joined
bill versions, alphanumeric middle segments, leading zeros, protected witness
slots, percent escapes, longer incomplete codes, and calendar-plausible middle
identifiers. Require actual date text outside a reference to remain usable.

Gate: every changed corpus name must be in discovery. Every previous complete
output must remain exact after removing only reviewed additions. All new fields
must match exact source spans, with no inferred code meanings. Focused controls,
full comparison, adapter, omission audit, corpus checks and existing tests must
pass. Save failed trials. No downloads or new dependencies; each full run has a
30-minute bound. This is reused development evidence, not unseen accuracy.
