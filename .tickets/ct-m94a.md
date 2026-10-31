---
id: ct-m94a
status: open
deps: []
links: [ct-wx65, ct-gi01, ct-m104]
created: 2026-10-31T00:05:23Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, dates, coverage, chaos-test]
---
# Qualify filename-derived document dates and publication coverage

The retained release advertises document coverage through 2303-05-04 with gaps=[]. A bounded audit found 11 document dates after 2100. For FDA PAHPA testimony May 4 2303 HELP1.pdf (list_row 161961), the parser correctly preserves the literal year and marks its role unknown, but the producer promotes the single candidate into filename_date and publication treats it as a coverage bound.

This is a qualification-policy gap distinct from the bill-number/date overlap bug. Current model documentation explicitly promotes a single date candidate and prefers filename dates, so correcting the behavior requires an explicit model-policy change. The historical date of this document has not been adjudicated; changing 2303 to 2023 would be a guess.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owners: congress_api/lake/filenames/_typed, model/sql/source-annotations-filename.sql, source-annotations-final.sql and document-normalized.sql; viewer_publication/archive_format.py; shared schema/documentation and site/MCP consumers.

Define an explicit, reproducible policy for accepted, unresolved and suspect document dates, using existing provenance and uncertainty fields where possible. Preserve literal filename evidence and useful candidates. Calendar validity alone does not establish a date's role. Document how supported source context, conflicting assertions, missing values and short-year precision affect selection and classification. Never silently clamp years, repair digits or infer centuries.

Publish the accepted date span with dated/undated/suspect counts and enough qualification detail to account for unresolved candidates without double counting. Define the counting units and categories. Expose date source and uncertainty; label an observed span as such, because its endpoints cannot establish completeness or the absence of gaps. Keep completeness claims separate and evidence-based.

Calculate these summaries in the existing publication aggregation and keep site/MCP consumers faithful to the shared release; do not add repeated MCP scans or a separate date calculator. Prove the policy on fixed small inputs before regeneration. Coordinate with ct-wx65 and ct-m104, assess actual parser-version invalidation, and reuse retained inputs. Do not assume that only affected filenames can be recomputed; combine required date-generation work where practical.

## Acceptance Criteria

- Document and implement the date-selection and classification policy, including candidate role, conflicting evidence, missing values, short-year precision and any precedence change. Update the existing model/schema reference coherently.
- Preserve the literal May 4 2303 observation. It must not become an unqualified historical coverage claim or be silently rewritten to a guessed date. State its classification and the evidence or rule supporting it.
- Test a qualified content/event date, an unknown-role filename candidate, a suspect candidate, conflicting dates, an undated document and a short year. Published accepted bounds and dated/undated/suspect counts, with unresolved-candidate accounting, must agree with independent expectations on fixed inputs.
- A date span or empty gaps list must not imply complete historical coverage without supporting completeness evidence. Document the meaning of bounds, counts and gap metadata, including unavailable or unknown evidence.
- Compute qualification summaries in the existing publication path. Verify date source, uncertainty and summary discovery through actual stdio MCP against the compact native fixture and through the site where exposed; label local candidate versus selected/deployed release evidence separately.
- Keep parser-overlap errors distinct from literal but unqualified observations. After fixture verification, record required regeneration scope and resource budget under the actual version rules; reuse retained inputs, preserve raw evidence and record exact input/definition/release pins.
