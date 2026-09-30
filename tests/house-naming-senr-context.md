# SENR filename context

Decision: extract the repeated committee/subcommittee/meeting portion of SENR
filenames, preserving the source tokens and context-dependent meanings.

Hypothesis: one family-specific grammar can recover committee, optional
subcommittee, nominations or field-hearing qualifiers, and meeting wording from
967 filenames without reinterpreting witness IDs, dates or bill references.
The raw inventory has 63 distinct tails, all from `www.energy.senate.gov`.
Two committee mentions in one filename must remain separate occurrences.

Source check: retained PDFs were read with pypdf after checking their body hashes.
The 118th Congress subcommittee assignment and Bissell testimony first pages were
also rendered and inspected. The assignment lists Energy; National Parks; Public
Lands, Forests, and Mining; and Water and Power. Aaronson, Caldwell, Bissell and
Baker source headers corroborate the W&P, NP, ENR and PLFM filename slots.
Participant List corroborates a Roundtable. ENR means Energy only in the
subcommittee slot within this family; do not resolve it globally. These are
source-family meanings, not new official House guide codes or committee IDs.

Arms: frozen native/strict results in `drafts-final`, accepted extraction in
`amendment-source-forms`, and the SENR supplement. Hold all existing guide rules,
code meanings, strict outputs and the 333,368-input corpus constant.

Intervention: append a late source-context rule that retains `committee_token`,
committee/subcommittee markers, `subcommittee_token`, `nomination_wording`,
`field_location_token`, `field_marker` and `meeting_wording` when printed.
Assign readable labels to source-supported abbreviations, retaining raw spelling
and no canonical committee identifier. Preserve Cmtr/Submte spellings. Require
an explicit subcommittee marker or following meeting wording before assigning a
subcommittee slot. The short Hr spelling is supported only at the stem end;
it must not consume a House bill reference. Recognize bare SENR independently
when no more specific context follows. No missing date, Congress, location,
meeting occurrence or access status is inferred.

Cases: all 967 source names, whole/subcommittee hearings, Business Meetings,
Roundtables, nominations, MT/WV Field Hrg, explicit Energy, missing Cmte/Subcmte,
hyphenated tails with UUIDs, repeated committee mentions and the malformed
Content-Disposition-derived basename. Include constructed embedded-word,
percent-encoded, witness-ID, unknown-subcommittee and HR-number controls.

Preserve existing overlapping labels such as Business Meeting or Nominations:
they do not block the added committee context. Concrete IDs and dates still do.
Use the existing late supplement pass; do not add a schema, external lookup or
new parser module. Existing broad name/subject text remains inspectable.

Decision rule: validate every field span and new meaning against source context,
retain all previous fields and metadata, preserve every strict result, keep all
old guide definitions/rules unchanged, and pass focused/full tests plus the
full comparison, omission and preservation audits. Reuse the 30-minute-bounded
harness, preserve unsuccessful runs, and label the reused corpus as development
evidence. The family does not establish complete semantic coverage of all names.
