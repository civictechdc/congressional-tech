# Structured slots before generic token searches

Decision: recover already-supported source roles that broad layout selection or
late refinement currently hides. Keep the original literal spelling and no
identity repair. KOOO395 is a malformed sponsor-shaped token, not K000395.

Hypothesis: refining explicit legislative payload slots before generic searches
will expose five missed sponsor slots and prevent numeric identifiers from being
misread as dates or other generic references. Reuse the existing unverified
sponsor and legislative-payload-search rules; do not invent new ID meanings or
remove the broader enclosing fields. Already selected source matches should not
be duplicated.

Arms: unchanged native outputs in drafts-final and House outputs in
semantic-fidelity-verified versus the revised House extractor. Use all 333,368
retained basenames, all seven actual KOOO395 cases, source-guide malformed
sponsor examples, and controls for valid Bioguide-shaped IDs, appropriations,
en bloc identifiers, revisions, dates and plain non-legislative names.

Hold source catalog meanings, strict parse/render behavior, native code and
inventory fixed. No network. Freeze source hashes and save complete changed
outputs. Bound each full corpus comparison to 30 minutes. Reused corpus cases
are development evidence, not a held-out accuracy estimate.

Acceptance: exact raw spans, no silent source rewriting, unchanged strict
results, all previous useful fields and meanings retained or directly explained,
new sponsor slots not labeled as verified Bioguide IDs, and numeric source roles
protected from generic date interpretation. Audit every change family and any
new native omission. Record remaining gaps rather than equating coverage with
complete interpretation.

Residual follow-up after the first run: expose recognized measure types and
explicit placeholders when a legislative subject is only HR, HR__, HResXX or
the corresponding other known measure codes. Require the whole subject slot;
ordinary titles and local abbreviations do not become bills. Extend the existing
amendment-ID refinement to simple numeric IDs so 15-U15 keeps amendment 15 and
update 15 separately. Preserve the enclosing source field and all existing
amendment-tree letter/digit behavior. Review the whole-corpus difference before
accepting these additions.

Nine actual targets print HR____AmericanPrivacyRightsActdiscussiondraft. Treat
the explicit underscores as a number placeholder and retain the following title
text separately, only inside the recognized legislative subject. Do not split
unseparated title-like words such as HResource or invent a number from a title.

Regex review: replace adjacent optional digit-consuming groups with an optional
letter-and-digit group. This preserves the amendment-ID language and captures
while preventing repeated partitions of long numeric strings before an invalid
character. Keep a bounded subprocess regression using a 12,000-digit invalid
token, preserve the pre-adjustment run, and qualify the final source separately.

Direct review rejects the broad numeric-ID refinement: 13,398 additions merely
repeat an already complete amendment_token. Four compound local IDs also gained
a potentially misleading numeric prefix (for example 1068_01_xml). Restrict the
new numeric refinement to an explicit positive terminal U update. Preserve
existing amendment-tree and en bloc rules. Check the four actual compound cases
as negative controls and verify that plain numeric IDs gain no duplicate field.
The structured-slots-final and structured-slots-verified candidates remain
retained, but neither is the accepted result. Qualify the corrected implementation
in structured-slots-reviewed.
