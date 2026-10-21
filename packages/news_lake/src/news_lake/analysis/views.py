"""C9 owner: release-scoped derived views.

politician_articles(release_read, decision_result) — at most one row per
(resolved person-root entity, current item, release). When decision_result is
omitted, the release's own pinned identity decisions are applied. Item
supersede chains are followed to the survivor; the survivor's
current_version_id selects the text; mentions of any entity in the person's
root group are gathered from that release's selected runs only; version/run
ids and aboutness are retained; duplicate spans across aliases are unioned.

coverage_daily(release_read) — distinct items/outlets/stories per publication
date bucket, with unknown publication dates forming ONE undated group (never
a fake date). Items are bucketed by their CURRENT version's publication; a
versionless item, or one whose current version has unknown precision, falls
back to an unambiguous reported_publication on its discovery records.
Identical-text group ids are listed per bucket to keep syndicated text
visible: identical_text_group_ids MUST NOT be read or reported as
independent-reporting counts (C9). Both views record their source release id.
"""
from news_lake.analysis.cluster import text_group_key
from news_lake.analysis.selection import select_runs


def _flat_records(release_read):
    return [record for rows in release_read['tables'].values() for record in rows]


def _by_kind(records, kind):
    return {record['id']: record for record in records if record['kind'] == kind}


def _survivor(item, items_by_id):
    current = item
    visited = {current['id']}
    while 'superseded_by' in current:
        target = items_by_id.get(current['superseded_by'])
        if target is None or target['id'] in visited:
            break
        current = target
        visited.add(current['id'])
    return current


def _publication_date(publication):
    """The day a publication denotes, or None when it does not denote one."""
    if not publication:
        return None
    precision = publication.get('precision')
    if precision == 'day':
        return publication.get('date')
    if precision == 'instant':
        at = publication.get('at')
        return at[:10] if at else None
    return None


class _ReleaseScope:
    """Shared resolution: selections, survivors, current versions, mentions."""

    def __init__(self, release_read, decision_result=None):
        self.release = release_read['release']
        self.records = _flat_records(release_read)
        self.items = _by_kind(self.records, 'item')
        self.versions = _by_kind(self.records, 'version')
        self.entities = _by_kind(self.records, 'entity')
        self.runs = _by_kind(self.records, 'run')
        self.discoveries_by_item = {}
        for record in self.records:
            if record['kind'] == 'discovery':
                self.discoveries_by_item.setdefault(record['item_id'], []).append(record)
        if decision_result is None:
            # Default to the release's own pinned decisions so merged entities
            # resolve even when the caller does not replay identity separately.
            from news_lake.identity import apply_decisions

            decision_result = apply_decisions(self.records)
        self.roots = decision_result.get('roots', {})
        self.selection = select_runs(self.records, self.release['selections'])
        self._pinned = {selection['processor'] for selection in self.release['selections']}
        self.mentions_by_version = {}
        self.story_by_version = {}
        for record in self.records:
            kind = record['kind']
            if kind == 'mention' and self.is_selected(record):
                self.mentions_by_version.setdefault(record['version_id'], []).append(record)
            elif kind == 'story_member' and self.is_selected(record):
                self.story_by_version.setdefault(record['version_id'], record['story_id'])

    def root_of(self, entity_id):
        return self.roots.get(entity_id, entity_id)

    def discovery_date(self, item_id):
        """The unambiguous day reported by the item's discoveries, if any."""
        dates = {
            date for discovery in self.discoveries_by_item.get(item_id, ())
            if (date := _publication_date(discovery.get('reported_publication'))) is not None
        }
        return dates.pop() if len(dates) == 1 else None

    def is_selected(self, record):
        """True when the record's run is the selected run for its version."""
        run = self.runs.get(record['run_id'])
        if run is None or run['processor'] not in self._pinned:
            return False
        return self.selection['assignments'].get(
            (run['processor'], 'version', record['version_id'])) == record['run_id']

    def survivor_items(self):
        seen, survivors = set(), []
        for item in self.items.values():
            survivor = _survivor(item, self.items)
            if survivor['id'] not in seen:
                seen.add(survivor['id'])
                survivors.append(survivor)
        return survivors

    def selected_mentions(self, version_id):
        return list(self.mentions_by_version.get(version_id, ()))

    def selected_story(self, version_id):
        """The story of this version under its selected clustering run."""
        return self.story_by_version.get(version_id)


def _merge_spans(spans, version=None):
    """C9: union duplicate and overlapping spans across aliases per field."""
    grouped = {}
    for span in spans:
        grouped.setdefault(span['field'], []).append(
            (span['start'], span['end'], span['surface'])
        )
    merged = []
    for field, intervals in sorted(grouped.items()):
        intervals.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
        start, end, surface = intervals[0]
        for next_start, next_end, next_surface in intervals[1:]:
            if next_start < end:  # spans are [start, end): adjacency is disjoint
                end = max(end, next_end)
                if version is not None and isinstance(version.get(field), str):
                    surface = version[field][start:end]
                elif len(next_surface) > len(surface):
                    surface = next_surface
            else:
                merged.append({'field': field, 'surface': surface, 'start': start, 'end': end})
                start, end, surface = next_start, next_end, next_surface
        merged.append({'field': field, 'surface': surface, 'start': start, 'end': end})
    return merged


def politician_articles(release_read, decision_result=None, *, docspec_views=None, mode='full'):
    if docspec_views is not None:
        return docspec_views.politician_articles(release_read, mode=mode)
    scope = _ReleaseScope(release_read, decision_result)
    rows = {}
    for item in scope.survivor_items():
        version = scope.versions.get(item.get('current_version_id'))
        if version is None:
            continue
        for mention in scope.selected_mentions(version['id']):
            entity_id = mention.get('entity_id')
            if entity_id is None:  # ambiguous/unresolved mentions assert nothing
                continue
            root = scope.root_of(entity_id)
            root_entity = scope.entities.get(root)
            if root_entity is None or root_entity.get('entity_type') != 'person':
                continue
            row = rows.setdefault((root, item['id']), {
                'release_id': scope.release['id'],
                'person_root_id': root,
                'entity_ids': set(),
                'item_id': item['id'],
                'version_id': version['id'],
                'run_ids': set(),
                'aboutness': set(),
                'surfaces': set(),
                '_spans': [],
            })
            row['entity_ids'].add(entity_id)
            row['run_ids'].add(mention['run_id'])
            row['aboutness'].add(mention['aboutness'])
            row['surfaces'].add(mention['surface'])
            row['_spans'].extend(
                {'field': span['field'], 'surface': mention['surface'],
                 'start': span['start'], 'end': span['end']}
                for span in mention['occurrences']
            )
    result = []
    for row in rows.values():
        version = scope.versions.get(row['version_id'])
        result.append({
            'release_id': row['release_id'],
            'person_root_id': row['person_root_id'],
            'entity_ids': sorted(row['entity_ids']),
            'item_id': row['item_id'],
            'version_id': row['version_id'],
            'run_ids': sorted(row['run_ids']),
            'aboutness': sorted(row['aboutness']),
            'surfaces': sorted(row['surfaces']),
            'spans': _merge_spans(row['_spans'], version=version),
        })
    return sorted(result, key=lambda row: (row['person_root_id'], row['item_id']))


def coverage_daily(release_read, decision_result=None, *, docspec_views=None, mode='full'):
    if docspec_views is not None:
        return docspec_views.coverage_daily(release_read, mode=mode)
    scope = _ReleaseScope(release_read, decision_result)
    buckets = {}
    corpus_text_groups = {}
    for item in scope.survivor_items():
        version = scope.versions.get(item.get('current_version_id'))
        bucket_date = _publication_date(version.get('publication')) if version is not None else None
        if bucket_date is None:
            bucket_date = scope.discovery_date(item['id'])
        bucket = buckets.setdefault(bucket_date, {'items': set(), 'outlets': set(),
                                                  'stories': set(), 'text_groups': set()})
        bucket['items'].add(item['id'])
        if item.get('outlet_id') is not None:
            bucket['outlets'].add(item['outlet_id'])
        if version is not None:
            story = scope.selected_story(version['id'])
            if story is not None:
                bucket['stories'].add(story)
            if 'text' in version:
                key = text_group_key(version['text'])
                bucket['text_groups'].add(key)
                corpus_text_groups.setdefault(key, set()).add(item['id'])
    rows = []
    for bucket_date in sorted(buckets, key=lambda d: (d is None, d or '')):
        bucket = buckets[bucket_date]
        rows.append({
            'release_id': scope.release['id'],
            'date': bucket_date,
            'undated': bucket_date is None,
            'items': len(bucket['items']),
            'outlets': len(bucket['outlets']),
            'stories': len(bucket['stories']),
            # Identical-text groups are visibility for syndication (including
            # cross-day syndication across the release), NOT a count of
            # independent reporting (C9).
            'identical_text_group_ids': sorted(
                key for key in bucket['text_groups'] if len(corpus_text_groups[key]) > 1
            ),
        })
    return rows
