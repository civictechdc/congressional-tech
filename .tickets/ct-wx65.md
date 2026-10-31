---
id: ct-wx65
status: open
deps: []
links: [ct-h1nd, ct-m94a]
created: 2026-10-31T00:05:22Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [house-naming, parser, correctness, chaos-test]
---
# Preserve bill numbers when filename dates overlap explicit references

Current house_naming Engine.extract and congress_api.lake.filenames.read_filename misread these filenames:
- hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf -> fabricated date 2199-05-23.
- hearing_memo_--_leg_hrg_on_hr_2167_06.23.16.pdf -> fabricated date 2167-06-23.

The selected release contains these dates at list_row 329136 and 329171 with document_date_source=filename. The parser consumes the bill number plus the adjacent month/day, suppresses the explicit bill reference, and then suppresses the actual short-date token for overlap. This is distinct from preserving a literal future year printed in a filename.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owner: packages/house-naming/src/house_naming/extraction.py and existing reference-reservation tests. At :1168-1171 the reference guard accepts a separated date beginning at the reference number; candidate ordering at :1123-1127 favors the resulting full-year candidate. Existing protected spans then suppress the following date.

Narrow the existing reference/date precedence rule so an explicit bill number retains its span when followed by a separate date. Reuse current parsing and span reservation; preserve cases where reference-like attachment wording legitimately precedes a complete date. Keep short-year precision and never infer a century. Recovering a bill type/number does not establish a complete measure_key: the producer also requires a known Congress. Preserve the reference without inventing that missing context.

Prove the repair on compact retained examples before scheduling regeneration. current_version hashes the parser and producer packages, and existing filename readings are reused only for the same catalog_version. A version change may therefore require reparsing all selected filename inputs; selective recomputation of only the two affected cases is not an established capability. Measure the required work and reuse retained inputs. Do not label old readings as outputs of the new parser or reacquire unrelated raw sources. Coordinate version handling with ct-h1nd and date/publication changes with ct-m94a and ct-gi01 to avoid duplicate regeneration. Keep this repair scoped to token ownership.

## Acceptance Criteria

- The exact 2167 and 2199 filenames retain their explicit bill type/number and intact 06.23.16 or 05.23.17 date token; neither produces a fabricated full date from the bill number.
- Preserve the unspecified century of short-year dates. A recovered reference yields a complete measure_key only when Congress is established by supported input evidence; unknown Congress remains unknown.
- Add controls varying only the bill number to 1234 and only the following date to a full-year spelling. Preserve literal future-date handling and genuine dates in "Burman Statement - Attachment 3-27-19 SENR Cmte WP Subcmte Hrg.pdf", "Cecere Testimony Attachment 9-22-22.pdf", "Attachment 06.12.2019.pdf" and "Hershman_APQ s_10-29-19.pdf".
- Run the maintained parser and producer adapter APIs plus focused existing tests; prove the original cases fail before the repair and pass afterward. Verify resulting document dates through a compact native publication fixture and the actual MCP client before broader regeneration.
- Verify parser-version invalidation and record the selected filename input count, expected recomputation scope and resource budget. Document whether existing version rules require all selected filenames to be reparsed; do not assume selective reuse or replay unrelated raw-source acquisition.
- Record exact input/version pins. Distinguish a local parser fix from corrected immutable publication and actual consumer readback; record remaining delivery work explicitly.
