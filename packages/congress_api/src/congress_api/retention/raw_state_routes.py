"""Scheduling summaries on the existing immutable raw state routing pages.

Summaries select work; exact native leaves remain the only record owner. Each
changed leaf recomputes its summary and only its existing route ancestors change.
The minimum queue key is a lower bound, so due filtering never reorders admitted
work even when a future row has an earlier historical check time.
"""
from datetime import datetime, timezone
from hashlib import sha256
import heapq
from itertools import count
from pathlib import Path

from congress_api.parsers import archive_links, document_links
from congress_api.parsers.archive_links import allowed_url
from .immutable_metadata import MetadataObjects
from .partition_routing import RoutingPages


def schedule_basis():
    # A new URL admission rule cannot silently trust an old invalid-row summary.
    policy = b''.join(Path(module.__file__).read_bytes() for module in (archive_links, document_links))
    return dict(version=1, admission_sha256=sha256(policy).hexdigest())


def priority(row):
    return row['outcome'] == 'retained', row.get('checked_at') or '', row.get('url') or ''


def due_time(value, *, strict=True):
    if not value:
        return ''
    try:
        value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            raise ValueError('Scheduled state due time requires an explicit timezone')
    except (TypeError, ValueError):
        if strict:
            raise
        return ''
    return value.astimezone(timezone.utc).isoformat()


def invalid(row):
    return not isinstance(row.get('url'), str) or not allowed_url(row['url'])


def summarize(rows):
    result = {}
    for row in rows:
        outcome = 'null:' if row['outcome'] is None else 'str:' + row['outcome']
        key = list(priority(row))
        due = due_time(row.get('next_attempt_at'), strict=False)
        item = result.setdefault(outcome, dict(count=0, due=due, first=key, invalid_count=0, invalid_first=None))
        item['count'] += 1
        item['due'] = min(item['due'], due)
        item['first'] = min(item['first'], key)
        if invalid(row):
            item['invalid_count'] += 1
            item['invalid_first'] = min(item['invalid_first'] or key, key)
    return result


def combine(summaries):
    result = {}
    for summary in summaries:
        for outcome, row in summary.items():
            if outcome not in result:
                result[outcome] = dict(row)
                continue
            item = result[outcome]
            item['count'] += row['count']
            item['invalid_count'] += row['invalid_count']
            item['due'] = min(item['due'], row['due'])
            item['first'] = min(item['first'], row['first'])
            candidates = [key for key in (item['invalid_first'], row['invalid_first']) if key is not None]
            item['invalid_first'] = min(candidates) if candidates else None
    return result


class StateMetadata(MetadataObjects):
    """The routing writer retains verified summaries beside exact leaf pins."""
    @staticmethod
    def summary(page):
        if 'children' in page:
            return combine(reference['schedule'] for reference in page['children'].values())
        return page['value']['schedule']

    def put(self, page):
        summary = self.summary(page)
        return dict(super().put(dict(page, schedule=summary)), schedule=summary)

    def prepare_put(self, page):
        summary = self.summary(page)
        stored_page = dict(page, schedule=summary)
        ref, digest, key, raw = super().prepare_put(stored_page)
        return dict(ref, schedule=summary), digest, key, raw, stored_page

    def read(self, reference):
        page = super().read(reference)
        if page.get('schedule') != reference.get('schedule') or page['schedule'] != self.summary(page):
            raise ValueError('Raw state route scheduling summary differs')
        return page


class StateRoutes(RoutingPages):
    def __init__(self, store):
        self.objects = StateMetadata(store, 'raw-state-v1', max_cache_entries=32)
        self._parsed_cache = {}

    def candidates(self, snapshot, *, outcomes, now=None, urls=None, invalid_only=False):
        outcomes = frozenset(outcomes)
        summary_outcomes = {'null:' if value is None else 'str:' + value for value in outcomes}
        deadline = due_time(now.isoformat()) if now is not None else None

        def accepted(row):
            return (row['outcome'] in outcomes and (not invalid_only or invalid(row))
                    and (deadline is None or due_time(row.get('next_attempt_at')) <= deadline))

        if urls is not None:
            yield from sorted((row for row in snapshot.states_for(urls).values() if accepted(row)), key=priority)
            return

        def lower_bound(summary):
            keys = [item['invalid_first'] if invalid_only else item['first']
                    for outcome, item in summary.items() if outcome in summary_outcomes
                    and (item['invalid_count'] if invalid_only else item['count'])
                    and (deadline is None or item['due'] <= deadline)]
            return tuple(min(keys)) if keys else None

        root = snapshot.manifest['state']['root']
        if root is None:
            return
        # Verify the selected root bytes before trusting its pruning summary.
        self._read(root, '')
        first = lower_bound(root['schedule'])
        if first is None:
            return
        serial = count()
        queue = [(first, next(serial), 'page', ('', root))]
        while queue:
            _, _, kind, value = heapq.heappop(queue)
            if kind == 'row':
                yield value
                continue
            prefix, reference = value
            page = self._read(reference, prefix)
            if 'children' in page:
                for char, child in sorted(page['children'].items()):
                    bound = lower_bound(child['schedule'])
                    if bound is not None:
                        heapq.heappush(queue, (bound, next(serial), 'page', (prefix + char, child)))
            else:
                table = snapshot.owner._read_states(page['value'])
                rows = table.select(snapshot.owner.state_schema.names).to_pylist()
                if summarize(rows) != page['schedule']:
                    raise ValueError('Selected native state rows differ from scheduling summary')
                for row in rows:
                    if accepted(row):
                        heapq.heappush(queue, (priority(row), next(serial), 'row', row))
