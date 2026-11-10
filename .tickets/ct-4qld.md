---
id: ct-4qld
status: in_progress
deps: []
links: []
created: 2026-11-10T03:26:29Z
type: bug
priority: 1
assignee: mikewolfd
tags: [gate, release, links]
---
# Release gate link rule passes when a live link key answers a different file

Release build 2026-11-10 (candidate a70ebc3d1466 against live 630164505301): six House Financial Services PDFs (live rows 256823, 256827, 256829, 256831, 256836, 278162) were fused into candidate row 331783 and appear nowhere in the candidate. Their 7 link keys, 14 lookup keys and 13 addresses still answer, but with a different file (live key 28f7a541731b530b, 143,581 bytes, now opens hhrg-119-ba00-20260902-sd002.pdf, 186,557 bytes). None is in retired_links. The gate's link rule reported missing 0, dangling 0, ok: it checks only that every live key still exists. Reviewers found it, not the gate. Evidence: .cache/archive-release/release-20261110/causes/review-DE/REVIEW.md, .cache/archive-release/release-20261110/causes/review-capture-address/.

## Acceptance Criteria

The link rule refuses when a live link key answers a body that is not the live body, a recorded alternate of it, or a retired successor, and names the keys. A test plants the seven-way fusion and the gate refuses it. The rule's count on live-against-candidate for this release is recorded here.


## Notes

**2026-11-10T06:48:19Z**

2026-11-10 branch claude/ct-gate-rules: the link rule has a third finding, changed, beside missing and dangling (release_comparison.changed_answers). A link key that the live release and the candidate both publish must reach a candidate row that serves either the live file (the live row's saved body) or the file the key names (a body whose SHA-256 begins with the key, data model 8.2). A row serves its saved body, its alternates and its recoveries. Passing: the same saved file; the live file kept on the row as an alternate or recovery; a key that reaches its own file after a wrong join is split. A retired key stays the ledger's business. Any other key refuses the publish, is named in the refusal, and is listed in the report with its live and candidate row, file and body. Like a vanished key, no cause record overrides it; no exception path was added, because the link rule's design has none. If release detail has no saved_body the report says the check did not run. Cost: two hash anti-joins over the key pairs the comparison already builds (441,164 keys, 394,230 served bodies); the whole comparison still takes 3.4 s.

Count for this release, live 630164505301 (investigations/gate-rules-20261110/4qld-real-data.md):
- dead candidate a70ebc3d1466: 6 keys named, exactly 28f7a541731b530b, f209387c5948760f, e0560d54500bf13e, 45027a7365cdc1f1, 7b63de014d2cd6a2, d5f411b954a0c3bf, each answering hhrg-119-ba00-20260902-sd002.pdf on row 331783. Nothing else: of 441,164 live keys 441,143 keep their saved file, 13 keep it as an alternate, 1 as a recovery, 1 reaches its own file. (The ticket's seventh key is the surviving PDF's own.)
- published 619db5f9e08e: 0 named. 441,157 keep their saved file, 6 reach their own file after the ct-h3jb splits, 1 keeps the live file as a recovery.
A plain-Python classification of every live key names the same keys as the gate on both candidates. Two keys re-pointed in a copy of the published candidate (a body key, and cae8e4ea34ec603a) are each named.

cae8e4ea34ec603a (Bowman Testimony.pdf) is not a refusal under this rule: the live file (14c4ae4df7b0, 2012) is still served on the row as its recovery, and the body now shown (75e859b7ff42, 2018) was already a recorded recovery of that row in the live release. The rule reads what the release records; that the two are different documents is ct-u9y4. The change is still caught where the record can accept it by name: detail.parquet changed saved_body (1) and changed saved_bytes (1), which last night's record carries as accepted_defect ct-u9y4.

Cannot see: whether an alternate or recovery recorded on a row is truly the same document; lookup keys and addresses that answer another file (the ticket counts 14 and 13 on the dead candidate; the comparison's documents-changed groups size them but name none). Remains open: a key with no file to name (a recovery link key or a ZIP key) that is correctly moved to another document would be refused with no hand path; none exists in either candidate.
