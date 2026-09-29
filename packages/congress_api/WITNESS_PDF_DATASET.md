# Paired House witness XML and PDF inventory

Counted directly from retained files on 2026-09-28. No documents were downloaded to produce these counts.

**Follow-up capture:** the later parallel download retained **381 of the 383
missing attachments**. We now have **834 candidate PDFs across 821 of the 823
meetings**. The table below remains the initial inventory so its counts and
original manifest are reproducible. Current paths and hashes are in
`.cache/raw-source-backfill-20260928/witness-pdfs/manifest.json`.

Events `102719` and `114210` still return HTML error pages from both listed
sources. All 834 retained PDF hashes were verified. Two newly inspected files
that the publisher labels as witness lists actually contain organizational
statements; these are candidate pairs, not a certified matching-roster dataset.

| Population | Meetings |
| --- | ---: |
| Retained House witness-list XML with at least one named, active witness | 3,386 |
| Those meetings with any PDF in meeting documents | 2,356 |
| Those meetings with an identified witness-list PDF | **823** |
| Those meetings with both witness XML and the PDF already saved locally | **453** |
| Identified pairs needing at least one PDF downloaded | 370 |

The 823 meetings identify **836 distinct PDF attachment filenames**. Of those, **453 PDFs are already cached**, one per ready meeting. There are 3,388 retained witness XML files; two have no named active witnesses. The local witness-PDF folder has 463 files, of which 461 start with a PDF signature; non-PDF bodies are excluded.

## Selection and joins

Inputs:

- `/Users/mikewolfd/hearing-text/docs_house_xml/wlist/*.xml`
- `/Users/mikewolfd/hearing-text/docs_house_xml/meeting/*.xml`
- `.cache/raw-output-audit-20260928/snapshot/congress_meetings.jsonl.gz`
- `/Users/mikewolfd/hearing-text/witness_lists/`

A candidate must have a named, active witness in its House XML and an active meeting-document PDF identified by at least one of:

1. Native `HW` document code or explicit Witness List document-type label.
2. A Witness List description/title, including Agenda and Witness List.
3. The publisher's `-WList-` filename component.

Native types identify 322 of the 823 meetings; descriptions identify 621. These overlap. Adding native types finds 13 meetings that a title/filename-only search misses. Older witness-list PDFs commonly have broad `SD` (Support Document) codes, so `HW` alone is insufficient.

Documents are joined by House event ID and exact attachment filename. This recognizes the known Congress.gov/docs.house.gov mirror paths within the same event without joining unrelated documents by similar titles. The manifest retains both source URLs, native type, source selector, labels, XML fields, local paths and SHA-256 values. Removed witnesses/documents are excluded from the current comparison population, not erased from raw files. No parse failures occurred during this count.

## Coverage by Congress

| Congress | Linked candidate meetings | Both files local |
| --- | ---: | ---: |
| 113 | 291 | 281 |
| 114 | 161 | 146 |
| 115 | 32 | 0 |
| 116 | 118 | 2 |
| 117 | 161 | 16 |
| 118 | 25 | 8 |
| 119 | 35 | 0 |
| **Total** | **823** | **453** |

**427 of the 453 cached pairs come from Congresses 113–114.** The ready set is useful for an immediate experiment but is not balanced across time or committee layouts.

These are candidate reference pairs, not certified identical editions. PDF updates, withdrawn witnesses, panel subsets, abbreviated names and affiliation wording can differ from the latest XML. Separate those source disagreements from extraction mistakes. The eight visually reviewed PDFs provide stronger ground truth for the current extractor comparison; the larger set can support a later reviewed benchmark.

## Reproduction

- Script: `.cache/source-models/witness-pdf-pairs/count_pairs.py`
- Per-meeting manifest: `.cache/source-models/witness-pdf-pairs/manifest.json`
- Counts: `.cache/source-models/witness-pdf-pairs/summary.json`

Run `.venv/bin/python .cache/source-models/witness-pdf-pairs/count_pairs.py` from the repository root. All reads are local. The manifest retains the actual XML witness fields rather than using CSV summaries as the reference.
