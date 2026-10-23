"""Persist receipt context ownership without rereading unrelated interpretations."""
from contextlib import closing

import pytest

from testing_fakes import MemoryNative
from testing_fakes import MemoryStore
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention.source_observations import SourceObservationTrace, SourceObservationStorage, dependency_id, observation_id


def item(key, kind, value, access='read'):
    return dict(receipt_key=key, receipt_line=1, kind=kind, value=value, access=access)


def test_old_new_event_closure_keeps_ambiguous_and_unresolved_consumers(tmp_path):
    native, store = MemoryNative(), MemoryStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='observations', max_rows=4, max_bytes=4096)
    with closing(WorkingCatalog(tmp_path / 'adopt.sqlite')) as work:
        trace = SourceObservationTrace(work)
        trace(item('page', 'event', '7'))
        trace(item('meeting-119', 'event', '7', 'write'))
        trace(item('meeting-118', 'event', '7', 'write'))
        trace(item('unresolved-page', 'event', '8'))
        trace(item('unrelated', 'event', '99'))
        old = owner.prepare(None, trace)
    with closing(WorkingCatalog(tmp_path / 'changed.sqlite')) as work:
        trace = SourceObservationTrace(work)
        # Complete deletion of this parent's contribution, and a previously
        # unknown event arrives. Both old and new edges must be followed.
        trace.register('meeting-118', 1)
        trace(item('new-meeting', 'event', '8', 'write'))
        changed = owner.prepare(old, trace)
    with closing(WorkingCatalog(tmp_path / 'closure.sqlite')) as work:
        affected = set(owner.affected(old, changed,
            [observation_id('meeting-118', 1), observation_id('new-meeting', 1)], working=work))
    assert affected == {observation_id(key, 1) for key in [
        'meeting-118', 'meeting-119', 'page', 'unresolved-page', 'new-meeting']}
    # A fresh owner reads retained old membership independently of latest state.
    fresh = SourceObservationStorage(native=native, store=store, namespace='observations', max_rows=4, max_bytes=4096)
    with closing(WorkingCatalog(tmp_path / 'old-closure.sqlite')) as work:
        old_affected = set(fresh.affected(old, old, [observation_id('meeting-118', 1)], working=work))
    assert old_affected == {observation_id(key, 1) for key in ['meeting-118', 'meeting-119', 'page']}


def test_many_small_receipt_owners_share_one_native_membership_partition(tmp_path):
    native, store = MemoryNative(), MemoryStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='coalesced-observations',
                                     max_rows=8192, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'trace.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for number in range(1000):
            trace(item(f'page-{number}', 'event', str(number)))
        root = owner.prepare(None, trace)
    assert len(native.calls) == 1
    assert len(native.tables[native.calls[0]]) == 2000
    with closing(WorkingCatalog(tmp_path / 'one.sqlite')) as work:
        assert list(owner.affected(root, root, [observation_id('page-99', 1)], working=work)) == [observation_id('page-99', 1)]


@pytest.mark.parametrize('absent', ['before', 'after'])
@pytest.mark.parametrize('trigger', ['observation', 'dependency'])
def test_one_sided_closure_reuses_exact_native_membership(tmp_path, absent, trigger):
    native, store = MemoryNative(), MemoryStore()
    options = dict(native=native, store=store, namespace='one-sided-observations',
                   max_rows=8192, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'trace.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for number in range(4):
            trace(item(f'page-{number}', 'event', str(number)))
            trace(item(f'meeting-{number}', 'event', str(number), 'write'))
        root = SourceObservationStorage(**options).prepare(None, trace)
    assert len(native.calls) == 1
    # A fresh owner must load the selected leaf once; an absent old/new graph
    # contributes no edges and must not evict that exact immutable read.
    owner = SourceObservationStorage(**options)
    native.reads.clear()
    before, after = (None, root) if absent == 'before' else (root, None)
    observations = [observation_id('meeting-1', 1)] if trigger == 'observation' else []
    dependencies = [dependency_id('event', '1')] if trigger == 'dependency' else []
    with closing(WorkingCatalog(tmp_path / 'affected.sqlite')) as work:
        affected = list(owner.affected(before, after, observations, working=work,
                                       changed_dependencies=dependencies))
    assert affected == sorted(observation_id(key, 1) for key in ['page-1', 'meeting-1'])
    assert native.reads == native.calls


def test_absent_graphs_keep_explicit_observations_without_native_reads(tmp_path):
    native, store = MemoryNative(), MemoryStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='empty-observations',
                                     max_rows=8192, max_bytes=1 << 20)
    observation = observation_id('deleted', 1)
    with closing(WorkingCatalog(tmp_path / 'empty.sqlite')) as work:
        assert list(owner.affected(None, None, [observation], working=work,
                                   changed_dependencies=[dependency_id('event', '7')])) == [observation]
    assert native.reads == []


def test_retained_receipt_xml_replay_persists_inherited_event_dependency_without_classification(tmp_path, monkeypatch):
    from test_raw_rebuild import retain
    from congress_api.retention import document_index as index
    from congress_api.retention.raw_archive import CAPTURES_KEY, decode_table
    from congress_api.retention.document_evidence import read_retained_body
    store, native = MemoryStore(), MemoryNative()
    retain(store, dict(eventId=7, congress=119, chamber='House', committees=[dict(systemCode='hsii00')]),
           family='congress/meetings', source_file='meeting.json')
    retain(store, {}, family='house/witness-xml', source_file='witness.xml', url='https://docs.house.gov/7.xml',
        body=b'<witness-list meeting-id="HMKP7"><panel><witness><firstname>Jane</firstname><lastname>Doe</lastname><witness-documents><witness-document type="WS"><files><file doc-url="https://example.gov/paper.pdf" doc-type="PDF"/></files></witness-document></witness-documents></witness></panel></witness-list>')
    captures = decode_table(store.read(CAPTURES_KEY))
    monkeypatch.setattr(index, 'extract', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Document interpretation repeated')))
    owner = SourceObservationStorage(native=native, store=store, namespace='retained-replay', max_rows=64, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'replay.sqlite')) as work:
        trace = SourceObservationTrace(work)
        rows = list(trace.replay(captures, store.read,
            lambda key: read_retained_body(None, key, read_compressed=store.read)).values())
        paper = next(row for row in rows if row['source_url'] == 'https://example.gov/paper.pdf')
        assert paper['source_committee_code'] == ['hsii00']
        observations = list(trace.observations())
        root = owner.prepare(None, trace)
    meeting_capture = next(row for row in captures.to_pylist() if row['family'] == 'congress/meetings')
    meeting_id = observation_id(meeting_capture['receipt_key'], meeting_capture['receipt_line'])
    with closing(WorkingCatalog(tmp_path / 'event-closure.sqlite')) as work:
        assert set(owner.affected(root, root, [meeting_id], working=work)) == set(observations)




def test_actual_native_observation_membership_survives_fresh_owner(tmp_path, native):
    store = MemoryStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='actual-observations', max_rows=8, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'native-trace.sqlite')) as work:
        trace = SourceObservationTrace(work)
        trace(item('page', 'event', '7'))
        trace(item('meeting', 'event', '7', 'write'))
        root = owner.prepare(None, trace)
    fresh = SourceObservationStorage(native=native, store=store, namespace='actual-observations', max_rows=8, max_bytes=1 << 20)
    with closing(WorkingCatalog(tmp_path / 'native-closure.sqlite')) as work:
        assert set(fresh.affected(root, root, [observation_id('meeting', 1)], working=work)) == {
            observation_id('meeting', 1), observation_id('page', 1)}


def test_changed_reader_does_not_replay_unrelated_readers_of_the_same_event(tmp_path):
    native, store = MemoryNative(), MemoryStore()
    owner = SourceObservationStorage(native=native, store=store, namespace='directed-observations', max_rows=4, max_bytes=4096)
    with closing(WorkingCatalog(tmp_path / 'readers.sqlite')) as work:
        trace = SourceObservationTrace(work)
        for number in range(1000):
            trace(item(f'page-{number}', 'event', '7'))
        trace(item('meeting', 'event', '7', 'write'))
        root = owner.prepare(None, trace)
    native.reads.clear()
    with closing(WorkingCatalog(tmp_path / 'reader-change.sqlite')) as work:
        affected = list(owner.affected(root, root, [observation_id('page-1', 1)], working=work))
    assert affected == sorted([observation_id('page-1', 1), observation_id('meeting', 1)])
    assert sum(len(native.tables[key]) for key in native.reads) < 100


def test_metadata_only_deduplicated_parent_context_keeps_all_source_owners(tmp_path):
    import pyarrow as pa
    from congress_api.retention import document_index as index
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    from congress_api.retention.source_inputs import collect_source_inputs
    with closing(WorkingCatalog(tmp_path / 'late-source-owners.sqlite')) as work:
        trace = SourceObservationTrace(work)
        context = index.DocumentSources(working=work, observe=trace)
        link = dict(url='https://example.gov/paper.pdf', parent_url='https://example.gov/page', label='Publisher label')
        for key in ('original-parent', 'copied-parent'):
            context.add_link(link, index.context_values(source_receipt_key=key, source_receipt_line=1))
        sources = work.mapping('sources')
        collect_source_inputs(sources, context, pa.Table.from_pylist([], schema=CAPTURE_SCHEMA),
                              lambda key: None, working=work, source_observer=trace)
        row, = list(sources.values())
        identity = index.source_identity(row)
        owners = {value[0] for value in work.connection.execute(
            'SELECT observation FROM observation_source_owners WHERE source=?', (identity,))}
        assert owners == {observation_id('original-parent', 1), observation_id('copied-parent', 1)}
        # Display evidence remains deduplicated, while contribution ownership
        # retains both actual receipts rather than fabricating paired locators.
        assert len(row['source_occurrences']) == 1


def test_placeholder_fact_merge_moves_every_exact_source_owner(tmp_path):
    import pyarrow as pa
    from congress_api.retention import document_index as index
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    from congress_api.retention.source_inputs import collect_source_inputs, add_source
    with closing(WorkingCatalog(tmp_path / 'merged-source-owners.sqlite')) as work:
        trace = SourceObservationTrace(work)
        sources = work.mapping('sources')
        placeholder = add_source(sources, None, 'paper.pdf', 'https://example.gov/paper.pdf', media_type=['application/pdf'])
        captured = add_source(sources, 'saved-body', 'paper.pdf', 'https://example.gov/paper.pdf', http_status=['200'])
        trace.source(placeholder, index.context_values(source_receipt_key='metadata', source_receipt_line=1))
        trace.source(captured, index.context_values(source_receipt_key='capture', source_receipt_line=2))
        collect_source_inputs(sources, index.DocumentSources(working=work, observe=trace),
            pa.Table.from_pylist([], schema=CAPTURE_SCHEMA), lambda key: None,
            working=work, source_observer=trace)
        row, = list(sources.values())
        assert row['body_key'] == 'saved-body' and row['media_type'] == ['application/pdf']
        owners = {value[0] for value in work.connection.execute(
            'SELECT observation FROM observation_source_owners WHERE source=?', (index.source_identity(row),))}
        assert owners == {observation_id('metadata', 1), observation_id('capture', 2)}


def test_observation_storage_attaches_reads_and_remaps_provenance_receipts_without_source_rewrite(tmp_path, native):
    store = MemoryStore()
    owner = SourceObservationStorage(
        native=native, store=store, namespace='receipt-observations', max_rows=32, max_bytes=1 << 20
    )
    with closing(WorkingCatalog(tmp_path / 'adopt.sqlite')) as work:
        trace = SourceObservationTrace(work)
        trace(item('page', 'event', '7'))
        trace(item('page', 'source', 'src-initial-1', 'write'))
        trace(item('meeting-119', 'event', '7', 'write'))
        trace(item('meeting-118', 'event', '7', 'write'))
        root1 = owner.prepare(None, trace)

    _, leaf1 = owner.members.routes.lookup(root1, observation_id('page', 1))
    source_pin_before = leaf1['release']['dataset']['groups']['source']
    # Initial prepare() automatically attached 'source:src-initial-1' from the trace's source write edge!
    initial_entries = owner.read_receipts(root1)
    assert [(e['locator'], e['evidence']) for e in initial_entries] == [
        (observation_id('page', 1), 'source:src-initial-1')
    ]

    # Attach ordered duplicate receipts and an explicit None null receipt
    root2 = owner.attach_receipts(
        root1,
        [
            (observation_id('page', 1), 'provenance:pass-1'),
            (observation_id('page', 1), 'provenance:pass-2'),
            (observation_id('meeting-119', 1), None),
            (observation_id('meeting-118', 1), 'provenance:to-be-deleted'),
        ],
        operation='attach-obs-receipts-1',
    )
    _, leaf2 = owner.members.routes.lookup(root2, observation_id('page', 1))
    assert leaf2['release']['dataset']['groups']['source'] == source_pin_before

    # Fresh owner reads back exact receipts bound to source and evidence versions
    fresh = SourceObservationStorage(
        native=native, store=store, namespace='receipt-observations', max_rows=32, max_bytes=1 << 20
    )
    entries = fresh.read_receipts(root2)
    by_loc = {}
    for entry in entries:
        assert entry['source_version'] == source_pin_before
        assert entry['evidence_version'] == leaf2['release']['dataset']['evidence']
        by_loc.setdefault(entry['locator'], []).append(entry['evidence'])
    assert by_loc == {
        observation_id('page', 1): ['provenance:pass-1', 'provenance:pass-2'],
        observation_id('meeting-119', 1): [None],
        observation_id('meeting-118', 1): ['provenance:to-be-deleted'],
    }

    # Delete meeting-118 and add a new observation; prepare() remaps surviving receipts by locator
    with closing(WorkingCatalog(tmp_path / 'update.sqlite')) as work:
        trace = SourceObservationTrace(work)
        trace.register('meeting-118', 1)
        trace(item('aaa-first', 'event', '7', 'write'))
        root3 = owner.prepare(root2, trace)

    remapped_entries = fresh.read_receipts(root3)
    remapped_by_loc = {}
    for entry in remapped_entries:
        remapped_by_loc.setdefault(entry['locator'], []).append(entry['evidence'])
    assert remapped_by_loc == {
        observation_id('page', 1): ['provenance:pass-1', 'provenance:pass-2'],
        observation_id('meeting-119', 1): [None],
    }
    # Affected closure still works identically over leaves with attached receipts
    with closing(WorkingCatalog(tmp_path / 'closure.sqlite')) as work:
        affected = set(fresh.affected(root2, root3, [observation_id('meeting-118', 1)], working=work))
    assert observation_id('page', 1) in affected and observation_id('meeting-119', 1) in affected
