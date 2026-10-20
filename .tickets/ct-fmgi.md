---
id: ct-fmgi
status: closed
deps: [ct-3lz2]
links: []
created: 2026-10-20T16:52:15Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, analysis, views]
---
# Fix adjacent span coalescing, default decision resolution, and pending/date views in analysis

Four defects in analysis/ affect view accuracy and run selection:
1. analysis/views.py:97 (_merge_spans) checks if next_start <= end: instead of if next_start < end:. Because span end is exclusive ([start, end)), two adjacent non-overlapping spans [0, 8) and [8, 16) are falsely merged into [0, 16), and when version is None the fallback surface length does not match end - start.
2. analysis/views.py:39-46, 111 (politician_articles / _ReleaseScope) sets self.roots = {} when decision_result is None, ignoring the release's own pinned news.identity_decisions table and emitting duplicate rows for merged entities. Also, _survivor (line 29) can loop infinitely or raise KeyError if called on unvalidated items with cyclic or missing superseded_by links.
3. analysis/views.py:163-175 (coverage_daily) only checks version['publication'] via item.current_version_id, placing all versionless items (such as Media Cloud items that carry reported_publication on their discovery records) into the undated bucket.
4. analysis/selection.py:24-36 (select_runs) marks failed, not_modified, and metadata_only captures as perpetually pending for 'extract', marks metadata_only versions as pending for clustering when untouched, and only discovers candidate inputs of kind 'capture' or 'version' (ignoring 'entity' and 'release').

## Design

1. In _merge_spans, change next_start <= end to next_start < end so only overlapping or identical spans merge, and reconstruct surface accurately when overlapping spans extend end.
2. In _ReleaseScope.__init__, when decision_result is None, automatically compute apply_decisions(self.records) so pinned identity_decisions are always honored by politician_articles and coverage_daily. Guard _survivor with a visited set and safe lookup.
3. In coverage_daily, when an item has no current_version_id (or its current version has precision == 'unknown'), fall back to an unambiguous known reported_publication from the item's discoveries in the release.
4. In select_runs, exclude captures with status != 'succeeded' or access == 'metadata_only' from default 'extract' pending candidates, and support 'entity' and 'release' input kinds.

## Acceptance Criteria

- Adjacent spans [0, 8) and [8, 16) remain two separate spans in _merge_spans, while overlapping spans [0, 8) and [4, 12) merge into [0, 12) with matching surface text.
- Calling politician_articles(release_read) without passing decision_result resolves same_as merges from release_read['tables']['news.identity_decisions'].
- coverage_daily buckets versionless Media Cloud items by their discovery reported_publication date when present and unambiguous.
- Failed, not_modified, and metadata_only captures are not reported as pending extraction inputs in select_runs.


## Notes

**2026-10-20T17:30:52Z**

Adjacent spans stay separate while overlaps merge with the correct surface; _ReleaseScope applies pinned identity decisions by default and guards supersede cycles; coverage_daily falls back to unambiguous discovery dates for versionless/unknown-precision items; select_runs excludes ineligible pending captures/versions. Analysis suites: 29 passed.
