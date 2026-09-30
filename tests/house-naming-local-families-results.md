# Recurring local legislative components: results

The accepted run is
`.cache/filename-engine-comparison-20260929/local-families-reviewed/`.
**303 filenames gain extracted fields**: 113 draft labels, 131 local numeric
components, 34 print identifiers and 26 descriptive prefixes before ANS/AINS.
Counts overlap. Overall, 821 outputs change; 518 only receive the clarified
committee-print rule description.

The full comparison covers **333,368 basenames**. Strict results remain
unchanged; all **2,557,801 field spans** match their source text. No previous
House field or field metadata was removed or changed, and no existing native
code meaning changed. **1,422 tests pass**, including 54 new tests. The native
omission audit has no unexplained omissions. Source guide definitions and strict
schemas remain unchanged; generated JSON and ECMAScript checks pass.

The raw review covers every new matching family:

- `CommitteePrint119-A` and `CommitteePrint2` retain print identifiers without
  supplying Congress or a bill number.
- `GrijalvaANS` separates descriptive prefix `Grijalva` from literal `ANS`.
  `GrijalvaANStoCommitteePrint` also exposes its target. No surname vocabulary,
  person identity or authorship is inferred. Ordinary Evans/EVANS words do not
  match the required case boundary.
- `CMT-AMD_01`, `D_AMDT_01` and nested filing identifiers expose local marker and
  numeric components. Leading zeros remain; these are not official amendment
  sequence numbers. Unknown local prefixes remain intact.
- `DiscussionDraft`, `SubcommitteeDraft` and the lowercase discussion-draft
  variant are literal wording, separate from official text-version codes.

A focused test rejected duplicate observations for bare ANS_02, already handled
by an existing whole-field rule. The corrected implementation omits the new
observation when all its fields already occur with identical metadata. The
failed and corrected focused runs are retained.

Full interpretation remains incomplete. Unexplained local codes stay literal.
Reviewing the earlier native omissions also revealed a substantive date issue:
the House month-first scan can claim `APR22` before reading the complete
`5APR22`, while the native parser retains both candidates. This needs a separate
ordering and calendar-validity experiment, not a new filename-specific regex.
Raw before-outputs are retained in `named-date-overlap-before.json` at the cache
root. The reused corpus remains development evidence, not an unseen accuracy
estimate. Work is local and uncommitted.
