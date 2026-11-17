"""ct-pz32: a night only new receipts can explain needs no cause record, inside its tripwires."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.data_only_night import (COLUMN_LOSS_FLOOR, DATA_ONLY_CAUSE, FILE_ROWS, GROUP_FLOOR, GROUP_ROWS,
                                                REMOVED_ROWS, column_values, data_only_causes, unattended_causes)

PROFILE = dict(parser_versions={'html_metadata': 'c226'}, file_hashes={'model/sql/list.sql': 'a' * 64, 'model/sql/detail.sql': 'b' * 64})
INPUTS = dict(profile=PROFILE, entity_digests={'members': 'm' * 64}, provenance=[dict(key='provenance/reviews/r.jsonl', etag='"1"')],
              unprofiled_inputs=dict(producer_versions={'captures': 'c' * 64}, job_pins={'model_spec': 's' * 64, 'daily': 'd' * 64}))
LIVE_KEYS = ['receipts/documents/2026-11-16/a.jsonl.gz', 'receipts/house/pages/2026-11-16/b.jsonl.gz']
NEW_KEY = 'receipts/documents/2026-11-17/c.jsonl.gz'
REAL = Path(__file__).parent / 'fixtures/data-only-night'
ROWS = {'list.parquet': 400_000, 'detail.parquet': 300_000, 'url_state.parquet': 1_200_000, 'recoveries.parquet': 12_000,
        'channels.parquet': 100}


def group(file, name, count, cause='value differs on matched key', status='unverified', **extra):
    if name.startswith('changed ') and cause == 'value differs on matched key':
        extra.setdefault('value', True)  # as release_comparison.value_group marks a changed column
    return dict(file=file, group=name, cause=cause, count=count, status=status, **extra)


def report(*groups, link_ok=True):
    return dict(link_rule=dict(ok=link_ok), failing=[g for g in groups if g['status'] != 'verified'],
                files={name: dict(rows=dict(base=rows, candidate=rows), groups=[{k: v for k, v in g.items() if k != 'file'}
                                                                                 for g in groups if g['file'] == name])
                       for name, rows in ROWS.items()})


def live(keys=LIVE_KEYS, **changes):
    return dict(release_id='1' * 64, key='viewer-publications/releases/1/inputs/x.json', record=dict(INPUTS, **changes),
                receipt_keys=list(keys))


@pytest.fixture
def releases(tmp_path):
    """Two releases whose one file has a full column and a sparse one, written by the caller."""
    def write(name, titles, notes):
        (tmp_path / name).mkdir()
        pq.write_table(pa.table({'title': titles, 'note': pa.array(notes, pa.string()),
                                 'tags': pa.array([[t] if t else [] for t in titles], pa.list_(pa.string()))}),
                       tmp_path / name / 'list.parquet')
        return tmp_path / name
    return write


@pytest.fixture
def decide(releases):
    base = releases('base', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    same = releases('same', ['t'] * 1000, ['n'] * 200 + [None] * 800)
    def run(value, *, record=INPUTS, records=None, keys=(*LIVE_KEYS, NEW_KEY), candidate_dir=same):
        return data_only_causes(value, candidate_record=record, live_records=[live()] if records is None else records,
                                candidate_receipt_keys=list(keys), base_dir=base, candidate_dir=candidate_dir)
    return run


def test_every_group_of_a_night_built_from_the_live_inputs_is_attributed_without_a_record(decide):
    value = report(group('list.parquet', 'changed title', 1097), group('list.parquet', 'added rows', 478, 'no surviving link key'),
                   group('url_state.parquet', 'removed URLs', -680, 'unexplained', 'unexplained'),
                   group('recoveries.parquet', 'changed bytes, no key or value difference found', 0, 'unexplained', 'unexplained', flag=True))
    entries, reasons, facts = decide(value)
    assert reasons == []
    assert [(e['id'], e['count']) for e in entries] == [
        ('list.parquet|changed title|value differs on matched key', 1097), ('list.parquet|added rows|no surviving link key', 478),
        ('url_state.parquet|removed URLs|unexplained', -680),
        ('recoveries.parquet|changed bytes, no key or value difference found|unexplained', 0)]
    assert all(e['cause'] == DATA_ONLY_CAUSE and e['disposition'] == 'explained' and e['automatic'] and e['tickets'] == ['ct-pz32']
               for e in entries)
    assert (facts['live_receipts'], facts['new_receipt_keys'], facts['groups'], facts['columns_compared']) == (2, [NEW_KEY], 4, 3)
    from congress_api.lake.versions import version_digest
    assert facts['profile_sha256'] == version_digest(packages={}, files={}, values=PROFILE)


@pytest.mark.parametrize('change,names', [
    (dict(profile=dict(PROFILE, file_hashes=dict(PROFILE['file_hashes'], **{'model/sql/list.sql': 'c' * 64}))),
     'profile.file_hashes.model/sql/list.sql'),
    (dict(profile=dict(PROFILE, parser_versions={'html_metadata': 'next'})), 'profile.parser_versions.html_metadata'),
    (dict(entity_digests={'members': 'n' * 64}), 'entity_digests.members'),
    (dict(provenance=[dict(key='provenance/reviews/r.jsonl', etag='"2"')]), 'provenance'),
    (dict(unprofiled_inputs=dict(INPUTS['unprofiled_inputs'], producer_versions={'captures': 'e' * 64})),
     'unprofiled_inputs.producer_versions.captures'),
    (dict(unprofiled_inputs=dict(INPUTS['unprofiled_inputs'], job_pins={'model_spec': 's' * 64, 'daily': 'f' * 64})),
     'unprofiled_inputs.job_pins.daily'),
])
def test_a_changed_definition_pin_decision_or_producer_is_not_a_data_only_night(decide, change, names):
    entries, reasons, _ = decide(report(group('list.parquet', 'changed title', 3)), record=dict(INPUTS, **change))
    assert entries == [] and reasons == [f'data-only night: the candidate differs from the live release in {names}']
    # Every refusal found is named, not only the first: here also a night over its cap.
    assert len(decide(report(group('list.parquet', 'changed title', 9000)), record=dict(INPUTS, **change))[1]) == 2


def test_an_input_neither_side_names_cannot_be_called_equal(decide):
    value = report(group('list.parquet', 'changed title', 3))
    old = live(); del old['record']['unprofiled_inputs']
    assert decide(value, records=[old])[1] == ['data-only night: the live release keeps no unprofiled_inputs to compare with']
    bare = {k: v for k, v in INPUTS.items() if k != 'unprofiled_inputs'}
    assert decide(value, record=bare, records=[old])[1] == ['data-only night: the candidate names no unprofiled_inputs']


def test_any_kept_input_of_the_live_release_with_the_same_inputs_serves_and_every_kept_receipt_counts_as_live(decide):
    older = live(keys=['receipts/documents/2026-11-15/z.jsonl.gz'], entity_digests={'members': 'o' * 64})
    value = report(group('list.parquet', 'added rows', 2, 'no surviving link key'))
    # The older input's receipt is live too: a candidate without it dropped a receipt.
    assert 'absent from the candidate' in decide(value, records=[older, live()])[1][0]
    for records in ([older, live()], [live(), older]):
        entries, reasons, facts = decide(value, records=records, keys=[*LIVE_KEYS, 'receipts/documents/2026-11-15/z.jsonl.gz', NEW_KEY])
        assert reasons == [] and len(entries) == 1 and facts['live_receipts'] == 3 and facts['new_receipt_keys'] == [NEW_KEY]
    # A refusal compares with the nearest kept input, wherever it sorts.
    off = dict(INPUTS, entity_digests={'members': 'p' * 64})
    assert [decide(value, record=off, records=records)[1][0] for records in ([older, live()], [live(), older])] == [
        'data-only night: the candidate differs from the live release in entity_digests.members'] * 2


def test_receipts_must_only_grow_and_something_new_must_have_been_read(decide):
    value = report(group('list.parquet', 'changed title', 3))
    assert decide(value, keys=[LIVE_KEYS[0], NEW_KEY])[1] == [
        f"data-only night: 1 receipts the live release read are absent from the candidate (first ['{LIVE_KEYS[1]}'])"]
    assert decide(value, keys=LIVE_KEYS)[1] == [
        'data-only night: the candidate read no receipt the live release did not, so nothing explains a difference']
    # Even with nothing failing: a difference-free night is the traced proof's, and no receipt is no explanation.
    assert decide(report(), keys=LIVE_KEYS)[1]
    assert decide(value, records=[live(keys=[])])[1] == ['data-only night: the live release has no receipt set to compare with']
    assert decide(report(group('list.parquet', 'changed title', 3), link_ok=False))[1] == ['data-only night: the link rule failed']


@pytest.mark.parametrize('planted', [
    group('list.parquet', 'manifest digest disagrees with file', 0, 'unexplained', 'unexplained', flag=True),
    group('detail.parquet', 'column page_metadata removed', 0, 'schema'),
    group('list.parquet', 'NULL url', 500, 'defect: a published source address must not be null', 'defect'),
    group('channels.parquet', 'file added', 40, 'file absent from the base release'),
    group('list.parquet', 'added bills', 21, 'unexplained', 'unexplained'),
    group('list.parquet', 'live file now an alternate', 3, 'a person decides which file a link opens (ct-4qld)'),
    group('list.parquet', 'removed rows', -1, 'no surviving link key'),
    group('list.parquet', 'added rows', 3, 'no surviving link key', flag=True),
])
def test_only_the_shapes_a_capture_night_makes_are_explained_and_the_rest_wait_for_a_person(decide, planted):
    entries, reasons, _ = decide(report(group('list.parquet', 'changed title', 5, value=True), planted))
    assert entries == [] and len(reasons) == 1 and 'is not a difference new receipts alone explain' in reasons[0]
    assert planted['group'] in reasons[0]


@pytest.mark.parametrize('file,name,count,status,passes', [
    ('list.parquet', 'added rows', GROUP_ROWS, 'unverified', True), ('list.parquet', 'added rows', GROUP_ROWS + 1, 'unverified', False),  # 2% is 8,000: the row cap binds
    ('recoveries.parquet', 'added keys', 240, 'unverified', True), ('recoveries.parquet', 'added keys', 241, 'unverified', False),      # 2% of 12,000
    ('channels.parquet', 'added keys', GROUP_FLOOR, 'unverified', True), ('channels.parquet', 'added keys', GROUP_FLOOR + 1, 'unverified', False),
    # A verified group is proven to be what it says, not to be small.
    ('list.parquet', 'removed rows', -REMOVED_ROWS, 'verified', True), ('list.parquet', 'removed rows', -REMOVED_ROWS - 1, 'verified', False),
    ('url_state.parquet', 'removed URLs', -3000, 'verified', True), ('url_state.parquet', 'removed URLs', -40_000, 'verified', False),  # 0.25% of the queue
    ('list.parquet', 'added keys', GROUP_ROWS + 1, 'verified', False),
])
def test_tripwires_use_each_files_own_rows_and_stop_more_than_a_capture_night_moves(decide, file, name, count, status, passes):
    changed = group('list.parquet', 'changed title', 5, value=True)
    entries, reasons, _ = decide(report(changed, group(file, name, count, 'fixture', status)))
    assert bool(entries) == passes and bool(reasons) != passes


def test_the_real_capture_night_passes_every_group_check_and_the_real_wipe_stops_on_them_alone(decide):
    night = json.loads((REAL / 'capture-night-20261117-c998ffa0766f.json').read_text())
    entries, reasons, facts = decide(night)
    assert reasons == [] and len(entries) == len(night['failing']) == 42 and facts['groups'] == 42
    assert {e['id']: e['count'] for e in entries} == {f"{g['file']}|{g['group']}|{g['cause']}": g['count'] for g in night['failing']}
    wipe = json.loads((REAL / 'html-metadata-wipe-20261116-08c465599d7b.json').read_text())
    entries, reasons, _ = decide(wipe)
    assert entries == [] and len(reasons) >= 18
    assert any('detail.parquet|changed page_metadata|value differs on matched key (12587)' in reason for reason in reasons)


def test_many_groups_each_under_its_cap_still_stop_at_the_files_total(decide):
    columns = [group('detail.parquet', f'changed c{i}', 4000, value=True) for i in range(3)]
    entries, reasons, _ = decide(report(*columns))
    assert entries == [] and reasons == [
        f'data-only night: detail.parquet moves 12000 rows across its groups, more than the {FILE_ROWS} one unattended night may']
    assert decide(report(*columns[:2]))[1] == []


def test_a_column_that_empties_stops_the_night_at_any_share_of_its_file(decide, releases):
    value = report(group('list.parquet', 'changed note', 200))                    # 0.05% of the file: no row cap sees it
    wiped = releases('wiped', ['t'] * 1000, [None] * 1000)
    assert decide(value, candidate_dir=wiped)[1] == [
        'data-only night: list.parquet:note lost 200 of its 200 values, more than the 5% one unattended night may']
    emptied = releases('emptied', ['t'] * 800 + [''] * 200, ['n'] * 200 + [None] * 800)   # 200 lists go empty
    assert decide(value, candidate_dir=emptied)[1] == [
        'data-only night: list.parquet:tags.list.element lost 200 of its 1000 values, more than the 5% one unattended night may']
    thinned = releases('thinned', ['t'] * 1000, ['n'] * (200 - COLUMN_LOSS_FLOOR) + [None] * (800 + COLUMN_LOSS_FLOOR))
    assert decide(value, candidate_dir=thinned)[1] == []
    assert column_values(wiped)['list.parquet', 'note'] == 0 and column_values(wiped)['list.parquet', 'title'] == 1000


def test_the_fetch_queue_is_bounded_by_its_row_caps_not_by_the_column_tripwire(decide, tmp_path):
    """A fetched address leaves the queue with its whole linked_from list (run 44065807228)."""
    def queue(name, linked):
        (tmp_path / name).mkdir()
        for file in ('url_state.parquet', 'list.parquet'):
            pq.write_table(pa.table({'linked_from': pa.array(linked, pa.list_(pa.string()))}), tmp_path / name / file)
        return tmp_path / name
    full, worked = queue('full', [['p'] * 10] * 100), queue('worked', [['p'] * 10] * 40 + [[]] * 60)
    value = report(group('url_state.parquet', 'changed linked_from', 60))
    run = lambda files: data_only_causes(value, candidate_record=INPUTS, live_records=[live()],
                                         candidate_receipt_keys=[*LIVE_KEYS, NEW_KEY], base_dir=full, candidate_dir=files)
    # The same loss in a content file stops the night; in the queue it does not.
    assert run(worked)[1] == ['data-only night: list.parquet:linked_from.list.element lost 600 of its 1000 values, more than the 5% one unattended night may']
    (worked / 'list.parquet').write_bytes((full / 'list.parquet').read_bytes())
    entries, reasons, facts = run(worked)
    assert reasons == [] and len(entries) == 1 and facts['columns_compared'] == 1


def test_the_traced_proof_decides_every_night_it_can_read_and_data_only_only_the_rest():
    addition = report(group('list.parquet', 'added rows', 3, 'no surviving link key'))
    forbidden = lambda value: pytest.fail('data-only must not decide a night the traced proof can read')
    assert unattended_causes(addition, traced=lambda value: (['traced'], []), data_only=forbidden) == (['traced'], [], None)
    # A proof that ran and refused is final: over its cap, a contradiction in raw, a re-fetch it cannot verify.
    assert unattended_causes(addition, traced=lambda value: ([], ['already in the live release']), data_only=forbidden) == (
        [], ['already in the live release'], None)
    assert unattended_causes(report(), traced=lambda value: ([], ['re-fetch not verified']), data_only=forbidden) == (
        [], ['re-fetch not verified'], None)
    mixed = report(group('list.parquet', 'added rows', 3, 'no surviving link key'), group('list.parquet', 'changed title', 2, value=True))
    assert unattended_causes(mixed, traced=forbidden, data_only=lambda value: (['e'], [], {'f': 1})) == (['e'], [], {'f': 1})
    # The deciding reason leads; the traced proof ran no check, and one line says so.
    assert unattended_causes(mixed, traced=forbidden, data_only=lambda value: ([], ['definition differs'], {})) == (
        [], ['definition differs', 'automatic causes: 1 differences are not additions the traced proof reads, so it ran no check'], None)
    # A verified group the traced proof cannot read is a difference too, with nothing failing.
    quiet = report(group('url_state.parquet', 'removed URLs', -40_000, 'never attempted', 'verified'))
    assert quiet['failing'] == [] and unattended_causes(quiet, traced=forbidden, data_only=lambda value: ([], ['over the cap'], {}))[1][0] == 'over the cap'
