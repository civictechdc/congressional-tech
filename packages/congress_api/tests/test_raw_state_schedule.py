"""State route summaries preserve queue policy without visiting unrelated rows."""
from datetime import datetime, timezone

import pyarrow as pa
import pytest

from congress_api.retention.raw_archive import STATE_SCHEMA, NON_DOWNLOAD_OUTCOMES
from native_memory_helpers import memory_raw_storage
from testing_fakes import SelectorStore, response

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def seed(rows, *, max_rows=4):
    store = SelectorStore()
    owner = memory_raw_storage(store, max_state_rows=max_rows)
    selected = owner.publish(owner.prepare(owner.snapshot(), operation='seed',
        states=pa.Table.from_pylist(rows, schema=STATE_SCHEMA), qualify_readings=True,
        filename_version=dict(selector_sha256=None, selected_ref=None)))
    owner.native.reads.clear()
    return store, owner, selected


def eligible(row, outcomes, now):
    return (row['outcome'] in outcomes and (now is None or not row.get('next_attempt_at')
            or datetime.fromisoformat(row['next_attempt_at']) <= now))


def priority(row):
    return row['outcome'] == 'retained', row.get('checked_at') or '', row['url']


@pytest.mark.parametrize('outcomes,now', [
    ({'pending'}, NOW), ({'retry_later', 'request_failed'}, NOW),
    ({'http_error'}, None), ({'saved', 'retained'}, None),
    ({'pending', 'retained', 'request_failed', 'retry_later', 'http_error'}, NOW),
])
def test_selected_schedule_matches_old_sort_due_and_outcome_filters(outcomes, now):
    rows = [dict(url=f'https://example.gov/{i}.pdf', outcome=outcome,
        checked_at='' if i % 3 else f'2026-10-{i+1:02d}T00:00:00+00:00',
        next_attempt_at=due) for i, (outcome, due) in enumerate([
            ('saved', None), ('retained', None), ('pending', None),
            ('retry_later', '2026-10-21T00:00:00+00:00'),
            ('request_failed', '2026-10-19T23:00:00-01:00'),
            ('pending', '2026-10-20T00:00:01+00:00'),
            ('http_error', None), ('request_failed', None), ('pending', None)])]
    store, owner, selected = seed(rows)
    expected = sorted((row for row in rows if eligible(row, outcomes, now)), key=priority)
    actual = list(selected.state_candidates(outcomes=outcomes, now=now))
    assert [row['url'] for row in actual] == [row['url'] for row in expected]
    assert all(set(row) == set(STATE_SCHEMA.names) for row in actual)


def test_unchanged_saved_history_and_future_queue_have_no_payload_reads():
    rows = [dict(url=f'https://example.gov/{i}.pdf', outcome='saved') for i in range(100)]
    rows += [dict(url='https://example.gov/future.pdf', outcome='pending', next_attempt_at='2027-01-01T00:00:00Z')]
    store, owner, selected = seed(rows)
    assert list(selected.state_candidates(outcomes={'pending', 'retained'}, now=NOW)) == []
    assert owner.native.reads == []


def test_small_queue_only_reads_leaves_containing_selected_outcomes():
    costs = []
    for count in (10, 1000):
        rows = [dict(url=f'https://example.gov/old-{i}.pdf', outcome='saved') for i in range(count)]
        rows += [dict(url=f'https://example.gov/pending-{i}.pdf', outcome='pending') for i in range(3)]
        store, owner, selected = seed(rows)
        actual = list(selected.state_candidates(outcomes={'pending'}, now=NOW))
        assert len(actual) == 3
        costs.append(len(owner.native.reads))
        assert len(owner.native.reads) <= 3
    assert max(costs) <= 3


def test_targeted_and_invalid_admission_queries_preserve_exact_rows():
    rows = [dict(url='https://example.gov/good.pdf', outcome='pending'),
            dict(url='https://a.internal/no.pdf', outcome='pending'),
            dict(url='https://b.internal/old.pdf', outcome='repaired_url'),
            dict(url='https://example.gov/fail.pdf', outcome='request_failed')]
    store, owner, selected = seed(rows)
    invalid = list(selected.state_candidates(outcomes={'pending', 'repaired_url'}, invalid_only=True))
    assert [row['url'] for row in invalid] == ['https://a.internal/no.pdf', 'https://b.internal/old.pdf']
    actual = list(selected.state_candidates(outcomes={'pending'}, urls={'https://example.gov/good.pdf'}))
    assert [row['url'] for row in actual] == ['https://example.gov/good.pdf']


def test_native_capture_nochange_never_iterates_state_history():
    from congress_api.retention.raw_archive import Archive
    from congress_api.acquisition.raw_sync import run_sync
    rows = [dict(url=f'https://example.gov/old-{i}.pdf', outcome='saved') for i in range(1000)]
    store, owner, selected = seed(rows)
    archive = Archive(store, 'nochange-scheduler', storage=owner)
    archive.state.values = lambda: pytest.fail('Unbounded state iteration')
    owner.native.reads.clear()
    owner.native.writes.clear()
    store.writes.clear()
    result = run_sync(archive, (), fetch=lambda url: pytest.fail('Unexpected acquisition'))
    assert result['attempted'] == result['remaining'] == 0
    assert result['known_urls'] == 1000
    assert owner.native.reads == []
    assert owner.native.writes == store.writes == []


def test_attempt_budget_keeps_old_priority_and_resumes_untouched_tail():
    from congress_api.retention.raw_archive import Archive
    from congress_api.acquisition.raw_sync import run_sync
    rows = [dict(url=f'https://example.gov/queued-{i}.pdf', outcome='pending', attempts=0, links_scanned=False) for i in range(20)]
    store, owner, selected = seed(rows)
    archive = Archive(store, 'bounded-admission', storage=owner)
    archive.state.values = lambda: pytest.fail('Unbounded state iteration')
    seen = []
    def fetch(url):
        seen.append(url)
        return response(url, b'%PDF-1.7\ninvalid\n%%EOF')
    run_sync(archive, (), fetch=fetch, limit=2, workers=1)
    ordered = sorted(row['url'] for row in rows)
    assert seen == ordered[:2]
    resumed = Archive(store, 'bounded-next', storage=owner)
    resumed.state.values = lambda: pytest.fail('Unbounded state iteration on resume')
    run_sync(resumed, (), fetch=fetch, limit=2, workers=1)
    assert seen == ordered[:4]


@pytest.mark.parametrize('initial_only,retry_outcomes,reinspect,retry_now', [
    (True, (), False, False), (False, ('request_failed',), False, False),
    (False, ('request_failed',), False, True), (False, (), True, False),
    (False, (), False, False),
])
def test_archive_queue_modes_match_full_reference(initial_only, retry_outcomes, reinspect, retry_now):
    from congress_api.retention.raw_archive import Archive
    rows = [dict(url=f'https://example.gov/{i}.pdf', outcome=outcome,
        checked_at=f'2026-10-{10-i:02d}', body_key=f'bodies/{i}.gz', next_attempt_at=due)
        for i, (outcome, due) in enumerate([('saved', None), ('retained', None), ('pending', None),
            ('request_failed', None), ('request_failed', '2026-12-01T00:00:00Z'), ('excluded_media', None)])]
    store, owner, selected = seed(rows)
    archive = Archive(store, 'queue-mode', storage=owner)
    archive.state.values = lambda: pytest.fail('Unbounded mode scan')
    urls = {row['url'] for row in rows}
    actual, refused = archive.capture_queue(now=NOW, limit=100, urls=urls, retry_outcomes=retry_outcomes,
        initial_only=initial_only, reinspect_retained=reinspect, retry_now=retry_now)
    expected = sorted((row for row in rows if
        (True if reinspect else row['outcome'] in retry_outcomes if retry_outcomes else
            row['outcome'] == 'pending' if initial_only else row['outcome'] not in NON_DOWNLOAD_OUTCOMES)
        and (reinspect or retry_now or not row.get('next_attempt_at') or datetime.fromisoformat(row['next_attempt_at']) <= NOW)), key=priority)
    assert not refused
    assert [row['url'] for row in actual] == [row['url'] for row in expected]


def test_schedule_preserves_null_state_fields_and_refuses_false_leaf_summary():
    rows = [dict(url=None, outcome=None), dict(url='https://example.gov/pending.pdf', outcome='pending')]
    store, owner, selected = seed(rows, max_rows=4)
    assert selected.states().to_pylist()[0]['url'] is None
    root = selected.manifest['state']['root']
    page = owner.state_routes.objects.read(root)
    page['value']['schedule']['str:pending']['count'] += 1
    # The immutable metadata can be self-consistent while lying about a native
    # leaf. Exact selected payload validation still refuses before admission.
    false = owner.state_routes.objects.put(page)
    selected.manifest['state']['root'] = false
    with pytest.raises(ValueError, match='native state rows differ'):
        list(selected.state_candidates(outcomes={'pending'}, now=NOW))


def test_admission_policy_change_requires_explicit_summary_qualification(monkeypatch):
    from congress_api.retention import raw_storage
    store, owner, selected = seed([dict(url='https://example.gov/a.pdf', outcome='pending')])
    monkeypatch.setattr(raw_storage, 'schedule_basis', lambda: dict(version=1, admission_sha256='changed-policy'))
    with pytest.raises(ValueError, match='basis changed'):
        memory_raw_storage(store, max_state_rows=4).snapshot()
