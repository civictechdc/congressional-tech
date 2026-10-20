---
id: ct-07eg
status: closed
deps: [ct-r33r, ct-1h4g]
links: []
created: 2026-10-20T16:52:20Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, storage, performance]
---
# Eliminate O(N^2) full-lake scans in publish_release, read_release, and find_release

storage/releases.py:58-67, 105, 135-170 and storage/coordinator.py:243-260 perform full-warehouse scans and re-validations on every operation:
1. find_release (releases.py:135-139) calls lake.read_all('news.releases') and scans in Python instead of pushing down an Iceberg EqualTo('id', release_id) filter.
2. publish_release (releases.py:105) loads all 12 tables in their entirety via _pinned_records() and runs full jsonschema validate_shape() and SHA-256 text hashing on every historical record on every hourly cycle (O(N^2 * M) total cost across N cycles).
3. read_release (releases.py:155-170) eagerly materializes all 12 tables into Python dicts with no option to select specific tables.
4. abandon_cycle (coordinator.py:243-260) scans and deserializes all 12 tables even for tables whose snapshot_id did not change during the failed cycle.

## Design

1. Use PyIceberg EqualTo('id', release_id) row filter in find_release.
2. In abandon_cycle, skip any content table whose current_snapshot().snapshot_id already matches the baseline release's pinned snapshot_id.
3. Allow read_release to accept an optional tables subset while defaulting to all 12 tables for backward compatibility.
4. Optimize corpus validation during publish_release so unchanged snapshots already validated in the prior available release do not re-run expensive per-record JSON Schema shape validation and SHA-256 text hashing while preserving full cross-record C7 integrity checks.

## Acceptance Criteria

- find_release uses an Iceberg row filter on id rather than reading all releases.
- abandon_cycle touches only tables whose current snapshot differs from the baseline release snapshot.
- Publishing a new cycle on top of an existing release validates the corpus without re-running JSON Schema validation and SHA-256 text hashing on untouched records from prior validated snapshots, while still catching all cross-record C7 violations.


## Notes

**2026-10-20T17:30:52Z**

find_release uses EqualTo('id'); read_release supports validated table subsets; publish_release skips per-record shape/hash work for snapshots already validated while cross-record C7 always runs; abandon_cycle skips snapshot-identical tables. Release tests cover the filter path, subsets, validation-cache call counts, and journaled snapshot reuse.
