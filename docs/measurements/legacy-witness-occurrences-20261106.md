# Legacy witness occurrence accounting, November 6, 2026

All **36,301 frozen input records** now have a retained disposition, source leads
and an owner. This replaces the old event/name grouping as the accounting unit.
It does not establish complete migration or approve legacy retirement.

The measurement reads the three historical CSVs and the retained candidate
`720c495b66d1691ee270dadb45c752f1c47d997c9fbe561dbbd039be15786b2f`
from source `5d1a8779`. This is a private, older candidate, not a claim about
current main or deployed data. CSV hashes match the [frozen comparison](explorer-native-comparison-20261101.json).
The candidate witnesses, list and sources files match its manifest hashes.

## What is accounted for

Each input identity includes filename, CSV digest and logical record number.
The ledger preserves every original field. Candidate lookup uses the original
source and its event, package or page, then exact names and populated role,
organization, panel, representation and participation fields. Whitespace is the
only text normalization. Missing names and different roles remain unresolved.

| Candidate disposition | Input records | Meaning and next owner |
| --- | ---: | --- |
| Active field match | 28,650 | Candidate fields agree at the original source scope; `ct-x78c` accounts for migration and reader acceptance, with Senate source work at `ct-kthe`. |
| Historical field match | 2,711 | Matching row has a successor marker; `ct-x78c` must retain the role, evidence and historical-key outcome. |
| Original event binding absent or different | 2,350 | The matching occurrence is retained at another supported scope; `ct-x78c` and, for Senate sources, `ct-kthe`. |
| Source fields differ | 1,437 | Preserve both versions for interpretation; same owners. This is not a defect count. |
| No same-name source occurrence selected | 921 | No supported match was established; same owners. This does not mean unavailable source. |
| Ambiguous occurrence | 87 | More than one source occurrence fits the available legacy fields; same owners. |
| Repeated input claim needs review | 88 | Same-file records would use one candidate key; `ct-x78c` retains the ambiguity rather than declaring duplicates. |
| Title or witness-list document needs reading | 57 | No supported native source comparison; `ct-x78c`. |
| **Total** | **36,301** | Every original record and field was checked against the written ledger. |

The ledger has 21,159 distinct uniquely referenced candidate keys. That is an
occurrence-reference count, not a certified migration count. It makes **zero
proven-duplicate claims**. Cross-file references can share a native occurrence;
the original input records remain available. In particular, two identical thin
Jefferson Keel rows at `100520` cannot be collapsed: the detailed source separates
representation and statement links.

## Source and document evidence

The bounded read verified 1,885 House XML body digests, 13,248,385 decoded bytes,
and found all 7,933 selected House occurrence locators. Their role, organization,
representation and removal checks found zero differences. The ledger also writes
the reverse raw-locator inventory: zero raw House locators outside its selected
scope. Raw name correspondence remains unadjudicated across the population.

The 14,805 other source-scoped native occurrences remain explicitly unread in
this audit. Missing local bodies would be labeled separately; the ledger makes
zero upstream-unavailability claims. It neither repeats Senate extraction nor
acquires sources.

Document checks compare source-listed URLs with visible documents annotated with
each witness key, and flag annotated document rows without an own-source URL.
They retain source document types and distinguish shared document rows from
distinct source links. There are **9,715 input records with exact-link flags** and
**4,840 source occurrences with document rows needing review**. These are leads,
not confirmed omissions or wrong associations: aliases, shared editions, source
status and other supporting evidence still need interpretation. `ct-x78c` owns
that review. No broad link or parser repair is claimed here.

Two House residuals are now specific:

- All twelve unmatched House input records concern six witnesses at `100876`.
  Digest-verified source `ba982aafcdb8d02568e8b44f46bfdabd6e99226a2e61fd4c909612404821e55a`
  lists seven witnesses with empty removal dates. The selected House source lists
  one. The six older occurrences and links remain in retained raw evidence and
  legacy records. `ct-x78c` owns the selection/preservation decision; acquisition
  is unnecessary for this comparison.
- All nineteen House field differences contain `No, but took Oath`. Preserve that
  literal fact; a native boolean alone cannot represent the oath detail.
  `ct-x78c` owns its eventual disposition.

## Named candidate controls and release handoff

Credit merged `2b130952`, its 74 focused native checks, and the independent Allen
wrong-suppression and wrong-role controls. They were not recreated.

The retained candidate keeps both Allen keys (`db779668e63d56bb`,
`2a0208241fb6a49d`), both Keel keys (`7021b9cc93c3b30d`, `a10966305b2c9ab0`)
and Ayers at `100346` (`e0ca0e7375ff80be`) active. All four Allen source URLs and
all three Keel URLs appear on the associated candidate documents. The two Allen
biographies share one candidate document row. Final readers must validate that
shared-edition provenance before using filename-based exclusive-owner assertions.
The two Allen statements have distinct rows.

The release, site and MCP owners must exercise these keys, source links, the
Ayers receipt-path case, historical keys and testimony/statement controls on the
same final immutable release. Candidate table checks are not paired-reader or
live acceptance. Reuse this ledger only when its three candidate asset hashes
match; otherwise run this small comparison against the final candidate. No model
rebuild is needed for the ledger itself.

## Reproduction and evidence

`scripts/measure/legacy_witness_occurrences.py` accepts `--data`, `--release`,
`--mirror`, `--frozen-ledger` and a fresh `--output` directory. It has no network
path and writes records, occurrences, the reverse House inventory and summary.
Use the checkout's frozen environment and the repository watchdog.

Durable evidence is under the main checkout's
`.cache/archive-release/implementation/reviewed-non-news-20261106/ct-x78c/`:
`ledger-720c-final/`, `accounting-readback.json`, `house-residuals.json`,
`reader-handoff.json`, `focused-final.log` and `ledger-final.watchdog.json`.
The final measurement took 4.2 seconds and peaked at 0.505 GiB RSS.

Thirteen focused checks passed through the project runner, explicitly a partial
production-offline result. They cover conservation, input/asset identity changes,
wrong roles, raw-role disagreement, historical status, ambiguous representation,
repeated claims, unread/unusable evidence and document associations in both
directions. An independent reviewer confirmed the planted assertions and limits.
Doctor's workspace-evidence warnings remain in the log; no byte-hashed parser,
reading version, runtime pin or model file changed.
