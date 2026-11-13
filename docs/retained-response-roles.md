# Inspect retained response roles

`congress_api.cli.response_roles` observes one local retained HTML or XML body.
It records original identity, a versioned role and the source fields that support
the observation. It does not change captures, accepted readings or acquisition
state. OCR remains paused and publisher refetch remains deferred.

```sh
.venv/bin/python -m congress_api.cli.response_roles retained.xml --format xml
.venv/bin/python -m congress_api.cli.response_roles retained.html --format html
```

The command accepts at most 1 MiB and uses spicy-docs' maintained markup readers
with bounded event/depth limits and original-byte positions. Large feeds use
their dedicated structured reader. The role policy is independent of historical
parser completion: a completed text extraction can still contain an error page.
HTML title/heading evidence has separate limits of 512 fields and 65,536
accumulated text characters. Ancestor closure ends descendant fields; exceeding either
evidence limit leaves the source unassessed instead of emitting a partial role.

The initial policy recognizes two complete root-level storage error structures
(`NoSuchKey` and `AccessDenied`) and narrow combinations of publisher titles,
headings and explanations for observed HTML error/wait families. A quoted phrase
alone is insufficient. Storage-error children must use the unnamespaced response
vocabulary, and non-whitespace mixed text under the root keeps it unassessed.
It distinguishes Senate maintenance from missing content.
The Atom root is a source-role observation, not proof that all entries were read.
Zero bytes are an empty response, not a qualified empty document. Unsupported,
over-bound, malformed, undecodable and unmatched inputs remain `unassessed`.

Each JSON output retains `body_sha256`, `policy_version`, `role`, `reason` and
`evidence`. Evidence includes title/heading or XML-child fields and byte starts.
Use the original file and retained HTTP/capture history to decide what happened;
these observations do not prove current publisher availability or permanent
document absence. A no-match does not certify substantive content.

## Bounded acceptance and remaining work

Evidence lives under the main checkout's durable directory:
`.cache/archive-release/ocr-recovery-20261113/repairs/response-roles-offline-20261113/`.
`inputs.json` identifies ten originals; `S301.json` adds an encoded edge-refusal
case. Actual CLI outputs distinguish errors from a maintenance response.
`data-review.md` names the directly read raw/intermediary/output chains and their
limits. A separate reviewer read two complete originals and actual outputs, then
rejected a deliberately wrong document role in
`independent-data-review-pdf-agent.md`. Mechanical tests are separate evidence.

`deferred-source-proposal.json` reconciles the existing eight landing-target
traces: six selected copies are excluded; one unattempted target and one HTTP410
target remain unresolved. Other damaged-source candidates remain explicitly
unreconciled. This file is a retained-history proposal, not a dispatcher or a
complete source inventory. Do not infer a new request authorization from it.

The broader `ct-en4n` criteria remain open: actual normal documents quoting
errors, justified-empty sources, manifests, portfolios, whole-hearing fallbacks,
selected-versus-unselected effects and the full zero-page failure cohort need
source qualification. `ct-z4w5` remains deferred until the user resumes refetching.

## Retained selection qualification

The sibling `selection-offline-20261113/` directory freezes a private 14-body,
281-page GPO pilot. Native planning/export selected eight corrected actual keys
and carried six exact unchanged readings at their original versions. Both
consumers reported zero pending work; six newer unselected attempts remained
available for qualification. A markup-only policy move enqueued zero PDFs;
missing or wrong-digest selections refused before producing accepted work.

`data-review.md` records direct PDF/native/diagnostic/final-row observations for
S055 and S150 bullets, the S017 tail, and the C015 carry-forward control. The
visible C015 signature remains absent from native text: unchanged carry-forward
is not complete form qualification. Root independently reviewed S055.
`direct-review-artifact-hashes.json` identifies the exact reviewed artifacts.
No production selection manifest or published body text was changed. Historical
exposure, composed-WARC qualification and publication/readback remain `ct-kfsd`
work; no broad re-OCR is required by this bounded selection evidence.
