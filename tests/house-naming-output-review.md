# Findings from every saved clustering report

Reviewed all 11 Markdown files under `output/` (480 lines), including the
committee/Congress experiment, its superseded first attempt and the PDF content
check. File hashes and current parser probes are retained in
`.cache/filename-engine-comparison-20260929/print-wording-output-review.json`.

The second experiment adds useful context evidence. It does not propose a
second, finer taxonomy: it scores agreement against 11 broad source categories.
The original report interprets 56 clusters as 21 candidate document families.

Those 11 scored categories are statements, disclosures, biographies, transcripts,
witness lists, questions for the record, votes, reports, legislative text,
amendments, and hearing records. The source mapping also retains a supporting
document category, but excludes that broad category from scoring. The benchmark
merges distinctions worth keeping in filename extraction: witness versus member
statements; committee versus conference reports; prints versus legislative text;
and rosters, covers, and contents pages versus hearing records. It cannot tell us
whether those finer categories were correctly identified.

| Approach | Agreement with source labels over 39,001 held-out cases |
| --- | --- |
| Global filename clustering | 77.84% |
| Chamber and parent committee | 79.65% |
| Adaptive subcommittee/Congress grouping | 84.39% |
| Committee-local vocabulary and word weights | 85.66% |

Use the corrected adaptive result, 84.39%, rather than the first attempt's
84.36%. The correction prevents descent through conflicting parent committees.
The local-vocabulary advantage over adaptive grouping is 1.27 percentage points,
below the experiment's declared two-point advancement threshold.

The previously unresolved subset is the clearest practical result: parent
committee grouping matched the source label for **38 of 57** held-out names,
compared with **10 of 57** globally. Adaptive grouping matched 37 and local
vocabulary matched 36. This supports using committee context to investigate
unknown names; it does not establish that the most elaborate approach is best.

## What to retain

- Keep the 21-family list as a review checklist. It distinguishes questionnaires,
  correspondence, rosters, cover pages, contents pages, notices, summaries and
  committee prints from broader testimony or legislative-text categories.
- Use committee and Congress context to investigate local patterns. Subcommittee
  and Congress splits need fallback to larger groups: 67.4% of the fully split
  groups contain fewer than 30 filenames.
- Read existing metadata before adding filename rules. Of 7,362 ambiguous or
  unclassified filenames, 402 already have native types; 316 have specific types.
  Source descriptions identify 733 Rules Committee Print mentions and 27
  explanatory statements. These are metadata observations, not verified contents.
- Preserve explicit companion links. The saved XML associates `DF_004_xml.pdf`
  with a named Rules Committee print and its CPRT XML. That association supplies
  information absent from the filename; `DF` has no established global meaning.
- Keep local abbreviations literal unless context establishes a meaning. The
  source description explains `ISO` in one committee's print, and the native type
  explains `tt_bates.pdf`. Neither establishes a universal filename rule.
- Check the context itself before relying on it. The raw review found 109
  filenames associated with opposite-chamber committee codes in GPO metadata.
  Preserve those source observations and conflicts; a unique subcommittee must
  not override conflicting parent committees. A joint publication associated
  with a House committee is not automatically a chamber error.
- Preserve conflicting claims. The content check found two disagreements favoring
  filename hints, three favoring metadata and one mixed document. It does not
  support treating either signal as automatic truth.

Current extraction preserves the saved representative signal from each of the
21 families, including the earlier notice and summary gaps. This is a sample
preservation check, not category-wide validation. No clustering rerun or new
production classifier is needed for these findings.

The latest check confirms the same complete 11-file inventory, unchanged report
hashes, and preservation of every saved representative field for all 21 families
in the current parser. That receipt is retained in
`.cache/filename-engine-comparison-20260929/output-review-current.json`.

## Complete Markdown inventory

Paths below are relative to `output/filename-clustering/`:

- `README.md`
- `RESTORED.md`
- `segmentation/README.md`
- `experiment-20260929/plan.md`
- `experiment-20260929/README.md`
- `experiment-20260929/raw-review.md`
- `experiment-20260929/content-check-plan.md`
- `experiment-20260929/content-check/README.md`
- `experiment-20260929/attempt-1/plan.md`
- `experiment-20260929/attempt-1/README.md`
- `experiment-20260929/attempt-1/raw-review.md`

The restoration report records reproduction from the retained transcript and
unchanged caches. Its timestamps and disk-space guard differ from the original
run; substantive reported counts match. The first-attempt source review is
identical to the corrected directory's retained diagnostic review.
