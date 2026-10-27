# S1 page evidence and extractor comparison

The page reader now preserves literal link order, repeats, relative bases, XML labels/dates, embedded JSON links and separate embedded markup groups. It uses entity-safe XML parsing, records owned MODS event IDs and dates, and produces main-content fingerprints with locked Trafilatura 2.0.0. The focused binding checks pass: **89 tests**, including 15 new page contracts and existing import, link-resolution and GovInfo fidelity checks.

S1 remains **partly done**. The extractor comparison favors this binding on available data; full paired-page qualification, sniff formats, semantic SQL, registry seeds and real-slice checks remain open. No release or lake write was run.

## Measured scope

DataFusion discovered 2,709 candidate paired endpoints and 2,723 stratified page rows from the pinned local capture index and older readings. These are candidates, using older format/status evidence; the raw mapping and S1 roles still need to narrow them to qualifying real pages. DataFusion produced a unique work list of 6,470 bodies. It also joined 412,529 local file identities from 29 cache directories, without reading those bodies or changing the cache. Only **3,425 requested bodies** were located, leaving 3,045 unavailable locally. No network body acquisition was attempted.

Each available body was read through a content-addressed reader and checked against its SHA-256. The arms ran in alternating order per page, using the same bytes; completed results were reused when 16 additional local copies were found. Text was NFKC-normalized, whitespace-collapsed and compared in full by DataFusion. Empty results never counted as equality. The versions were Trafilatura 2.0.0, readability-lxml 0.9 and lxml 6.0.2.

| Observed result | Trafilatura | readability-lxml |
|---|---:|---:|
| Nonempty extractions | 3,424 | 3,291 |
| Empty extractions | 1 | 134 |
| Unavailable candidate bodies | 3,045 | 3,045 |
| Candidate endpoints with equal, nonempty texts | 1,622 | 1,562 |
| Total measured extraction time | 26.090 s | 20.004 s |
| Median per available page | 7.056 ms | 4.492 ms |

These Mac timings describe the extraction calls, not the Linux runner, a complete backfill or all 2,709 endpoint groups. The original 6,470-body pass took 54.14 seconds overall and 206,077,952 bytes maximum RSS; the additional-copy pass also recomputed corrected markup facts and is not a second independent timing trial. Missing inputs prevent claiming a full-population winner.

The inspected sample included 12 Commerce executive-session differences and 16 short extraction rows. Trafilatura retained substantive agendas/nominees where readability returned empty text; the short-page check also exposed readability outputs that retained job titles while losing names. This supports the current binding but is sampled content review, not the required several-hundred-file labeled sample. Neither algorithm guarantees perfect boilerplate removal; Trafilatura sometimes retains stable sharing labels. The reader applies no custom main-content fallback.

## Corrections and remaining qualification

The first markup-facts draft failed on HTML comments and prefixed social tags. Fixtures preceded both fixes. The corrected facts pass completed all 3,425 available pages without a parser failure. Its source pin and per-body results remain in scratch; the current reader additionally has the tested date and embedded-group rules. A subsequent scratch guard incorrectly refused approved cache symlinks and produced no accepted facts; that attempt was retained and replaced, not counted as missing-body evidence.

DM §6.2 now gives embedded JSON markup groups a script/key-path prefix, preventing separate strings from sharing a publisher group. Its date rule pins a parser's timezone package as part of the parser version; the model continues to use the engine's timezone database. The reader uses locked pytz 2026.5 rather than host timezone files.

Scratch evidence: `cx_s1_population_broad_*`, `cx_s1_local_body_inventory_summary.json`, `cx_s1_source_pins.json`, `cx_s1_extractor_versions.json`, `cx_s1_extraction_rows.jsonl`, `cx_s1_extraction_retry_v2.jsonl`, `cx_s1_retry_analysis_fixed_*`, `cx_s1_summary_report.json`, and `cx_s1_page_binding_checks.log`. The protocol was committed before measuring either arm (`47d6c5e6`). Keep the full S1 checkpoint open until missing slices and the remaining fixtures/rules are qualified. The maintained candidates are documented by [Trafilatura](https://pypi.org/project/trafilatura/) and [readability-lxml](https://pypi.org/project/readability-lxml/).
