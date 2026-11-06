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

The bounded read verified 1,885 House XML body digests, 13,248,385 decoded bytes.
After independent review, 7,913 selected House locators have qualified positional
correspondence; twenty occurrences in four bodies remain explicitly unqualified.
The ledger refuses raw positional attribution when removal, panel order, explicit
IDs or unsupported shapes could change the meaning of a native locator. It does
not reproduce the producer's filtering and sorting rules. This corrects the
initial measurement's assumption that all 7,933 native positions were raw positions.
Qualified role, organization and representation checks found zero differences.
The reverse raw-locator inventory excludes unqualified bodies; its zero differences
do not qualify the twenty omitted bindings.

The supplemental detailed House name check now qualifies 7,913 selected-source
correspondences and six retained-original correspondences, leaving twenty under
review. All nineteen oath occurrence bindings remain qualified. Thin CSV and
non-House name correspondence remain unadjudicated.

The 14,805 other source-scoped native occurrences remain explicitly unread in
this audit. Missing local bodies would be labeled separately; the ledger makes
zero upstream-unavailability claims. It neither repeats Senate extraction nor
acquires sources.

Document checks compare source-listed URLs with visible documents annotated with
each witness key, and flag annotated document rows without an own-source URL.
They retain source document types and distinguish shared document rows from
distinct source links. There are **9,699 input records with exact-link flags** and
**4,832 source occurrences with document rows needing review**. These are leads,
not confirmed omissions or wrong associations: aliases, shared editions, source
status and other supporting evidence still need interpretation. `ct-x78c` owns
that review. No broad link or parser repair is claimed here.

Two House residuals are now specific:

- All twelve unmatched House input records concern six witnesses at `100876`.
  Digest-verified source `ba982aafcdb8d02568e8b44f46bfdabd6e99226a2e61fd4c909612404821e55a`
  lists seven witnesses with empty removal dates. The selected one-witness body
  exactly matches the repeated-documents test fixture. Original receipt lines 1-2
  of `assemble-20260930.jsonl.gz` trace it to local `manual-source-review` model
  outputs, not a later publisher fetch. The first causal failure is source
  admission: derived review evidence competed as roster authority. Root owns the
  bounded eligibility/input repair and ct-m104 its final output qualification.
  Preserve raw history and normal newer-list replacement; do not union rosters,
  infer attendance or reacquire these already retained sources.
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
biographies share one candidate document row. Independently accepted source
provenance confirms the shared biography body correctly carries both role keys;
each statement carries its own. Final readers must preserve those role sets
without inferring ownership from the selected filename or requiring a fourth body.

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
`ledger-720c-locator-fix/`, `locator-fix-coverage-reconciliation.json`,
`house-name-correspondence-locator-fix.jsonl`, `SOURCE-ADMISSION-HANDOFF.md` and
`reader-handoff.json` provide the corrected result. The original `ledger-720c-final/`
and its readback remain historical evidence, superseded for raw positional
attribution. Focused logs, the corrected measurement watchdog and independent
review are under the shared `merge-prune-20261106T180951Z/reviews/ct-x78c/` directory.

Eighteen focused checks passed through the project runner, explicitly a partial
production-offline result. They cover conservation, input/asset identity changes,
wrong roles, raw-role disagreement, historical status, ambiguous representation,
repeated claims, unread/unusable evidence and document associations in both
directions, plus removed-before-active, reordered-panel and ID-locator controls.
The four-skill independent reviewer identified the original locator defect; the
follow-up refuses unproved attribution instead of attaching another person's facts.
Doctor's workspace-evidence warnings remain in the log; no byte-hashed parser,
reading version, runtime pin or model file changed.
