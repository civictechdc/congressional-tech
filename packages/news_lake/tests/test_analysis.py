"""Slice 6: baseline clusterer and C8 selection (pure record-level tests)."""
from uuid import NAMESPACE_URL, uuid5

from news_lake.analysis import cluster, select_runs
from news_lake.context import adapter_namespace
from news_lake.contract import check_corpus

RUN_NAMESPACE = adapter_namespace('test:analysis')
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-analysis-test:' + key))


def make_version(key, text=None, item_key=None):
    record = {
        'kind': 'version', 'id': _id('version:' + key), 'recorded_at': '2026-10-20T04:00:00Z',
        'item_id': _id('item:' + (item_key or key)), 'capture_id': _id('capture:' + key),
        'run_id': _id('run-extract:' + key), 'title': f'Title {key}',
        'publication': {'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'},
        'access': 'metadata_only',
    }
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        import hashlib

        record['text_hash'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return record


def shells_for(versions):
    """Minimal item/capture/run shells so a corpus check passes."""
    from news_lake.context import AdapterContext, build_run

    frozen = AdapterContext(clock=lambda: __import__('datetime').datetime(
        2026, 10, 20, 4, 0, 0, tzinfo=__import__('datetime').timezone.utc))
    records = []
    for version in versions:
        extract = build_run(RUN_NAMESPACE, frozen, processor='extract', processor_version='fixture-1',
                            config={'fixture': True}, inputs=[{'kind': 'capture', 'id': version['capture_id']}])
        extract['id'] = version['run_id']
        capture = {'kind': 'capture', 'id': version['capture_id'], 'recorded_at': '2026-10-20T04:00:00Z',
                   'provider': 'rss', 'request_url': f"https://example.com/{version['item_id']}",
                   'observed_at': '2026-10-20T04:00:00Z',
                   'access': 'redistributable' if 'text' in version else 'metadata_only',
                   'status': 'succeeded'}
        if 'text' in version:
            capture.update({'payload_uri': f"s3://fixture/{version['capture_id']}",
                            'payload_hash': 'a' * 64, 'media_type': 'text/html',
                            'rights_basis': 'Synthetic fixture.'})
        records.extend([
            capture,
            {'kind': 'item', 'id': version['item_id'], 'recorded_at': '2026-10-20T04:00:00Z',
             'canonical_url': f"https://example.com/{version['id']}", 'url_aliases': [],
             'content_type': 'news_article', 'first_seen_at': '2026-10-20T04:00:00Z'},
            extract,
        ])
    return records


# -- clusterer --------------------------------------------------------------------


def test_identical_text_across_outlets_is_one_story():
    a = make_version('a', text='The council passed the budget.')
    b = make_version('b', text='The council passed the budget.')
    c = make_version('c', text='A different story entirely.')
    result = cluster([a, b, c])
    assert len(result['stories']) == 2
    syndicated = next(s for s in result['stories'] if len(
        [m for m in result['story_members'] if m['story_id'] == s['id']]) == 2)
    assert {m['version_id'] for m in result['story_members'] if m['story_id'] == syndicated['id']} == {a['id'], b['id']}
    # Every member names the same run as its story (C7).
    run_ids = {m['run_id'] for m in result['story_members']} | {s['run_id'] for s in result['stories']}
    assert run_ids == {result['run']['id']}


def test_normalization_is_casefold_and_whitespace_collapse():
    loud = make_version('loud', text='The  COUNCIL passed\nthe budget.')
    quiet = make_version('quiet', text='the council passed the budget.')
    result = cluster([loud, quiet])
    assert len(result['stories']) == 1
    assert len(result['story_members']) == 2


def test_metadata_only_versions_cannot_be_grouped():
    with_text = make_version('t1', text='same text')
    without = make_version('t2')  # no text: nothing to compare
    result = cluster([with_text, without])
    assert len(result['stories']) == 1
    assert [m['version_id'] for m in result['story_members']] == [with_text['id']]
    check_corpus(shells_for([with_text, without]) + [with_text, without,
                                                     result['run'], *result['stories'], *result['story_members']])


def test_clustering_is_deterministic_and_replayable():
    from datetime import datetime, timezone

    from news_lake.context import AdapterContext

    frozen = AdapterContext(clock=lambda: datetime(2026, 10, 20, 4, 0, 0, tzinfo=timezone.utc))
    versions = [make_version('x', text='x text'), make_version('y', text='x text')]
    assert cluster(versions, context=frozen) == cluster(versions, context=frozen)


# -- selection (C8) -----------------------------------------------------------------


def run_record(key, *, processor='extract', version='v1', config, inputs, status='succeeded',
               finished_at='2026-10-20T04:00:00Z'):
    import hashlib
    import json

    return {
        'kind': 'run', 'id': _id('run:' + key), 'recorded_at': finished_at,
        'processor': processor, 'processor_version': version,
        'config_hash': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        'input_hash': hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        'inputs': inputs, 'mode': 'live', 'status': status,
        'started_at': '2026-10-20T03:00:00Z', 'finished_at': finished_at,
        **({} if status == 'succeeded' else {'reason': 'fixture failure'}),
    }


CAPTURE = _id('capture:c1')
PIN_A = ('extract', 'v1', None)  # filled below


def config_of(run):
    return {'processor': run['processor'], 'processor_version': run['processor_version'],
            'config_hash': run['config_hash']}


def test_changed_model_version_new_config_hash_wins():
    old = run_record('old', config={'model': 'A'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                     finished_at='2026-10-20T04:00:00Z')
    new = run_record('new', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                     finished_at='2026-10-20T05:00:00Z')
    result = select_runs([old, new], [config_of(new)])
    assert result['assignments'] == {('extract', 'capture', CAPTURE): new['id']}
    assert result['pending'] == []


def test_old_model_run_alone_leaves_the_input_pending():
    old = run_record('old', config={'model': 'A'}, inputs=[{'kind': 'capture', 'id': CAPTURE}])
    new_pin = {'processor': 'extract', 'processor_version': 'v1',
               'config_hash': 'f' * 64}  # no run exists for this triple
    result = select_runs([old], [new_pin])
    assert result['assignments'] == {}
    assert result['pending'] == [('extract', 'capture', CAPTURE)]


def test_zero_output_success_replaces_earlier_outputs():
    earlier = run_record('earlier', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                         finished_at='2026-10-20T05:00:00Z')
    later = run_record('later', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                       finished_at='2026-10-20T06:00:00Z')  # succeeded, produced no outputs
    version_of = {'kind': 'version', 'id': _id('version:old'), 'recorded_at': '2026-10-20T05:00:00Z',
                  'item_id': _id('item:x'), 'capture_id': CAPTURE, 'run_id': earlier['id'],
                  'title': 'T', 'publication': {'precision': 'unknown'}, 'access': 'metadata_only'}
    result = select_runs([earlier, later, version_of], [config_of(later)])
    assert result['assignments'][('extract', 'capture', CAPTURE)] == later['id']
    # The release believes the later run; the earlier version output is not its output.
    outputs = [r for r in [version_of] if r.get('run_id') == result['assignments'][('extract', 'capture', CAPTURE)]]
    assert outputs == []


def test_latest_by_finished_at_then_id():
    first = run_record('first', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                       finished_at='2026-10-20T05:00:00Z')
    second = run_record('second', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                        finished_at='2026-10-20T06:00:00Z')
    assert select_runs([first, second], [config_of(second)])['assignments'][
        ('extract', 'capture', CAPTURE)] == second['id']
    tie1 = run_record('tie1', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                      finished_at='2026-10-20T06:00:00Z')
    tie2 = run_record('tie2', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                      finished_at='2026-10-20T06:00:00Z')
    winner = max(tie1['id'], tie2['id'])
    assert select_runs([tie1, tie2], [config_of(tie2)])['assignments'][('extract', 'capture', CAPTURE)] == winner


def test_failed_runs_do_not_displace_and_stay_pending():
    good = run_record('good', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                      finished_at='2026-10-20T05:00:00Z')
    failed = run_record('failed', config={'model': 'B'}, inputs=[{'kind': 'capture', 'id': CAPTURE}],
                        status='failed', finished_at='2026-10-20T06:00:00Z')
    other_capture = _id('capture:c2')
    failed_only = run_record('failed-only', config={'model': 'B'},
                             inputs=[{'kind': 'capture', 'id': other_capture}],
                             status='failed', finished_at='2026-10-20T05:00:00Z')
    result = select_runs([good, failed, failed_only], [config_of(good)])
    assert result['assignments'] == {('extract', 'capture', CAPTURE): good['id']}
    assert result['pending'] == [('extract', 'capture', other_capture)]


def test_unprocessed_record_never_touched_by_any_run_is_pending():
    """C8: an input record in the corpus that no run of a pinned processor has
    touched is still visibly pending."""
    v1 = make_version('v1', text='first')
    v2 = make_version('v2', text='second')
    mentions_run = run_record('m1', processor='mentions', config={'model': 'B'},
                              inputs=[{'kind': 'version', 'id': v1['id']}])
    result = select_runs([v1, v2, mentions_run], [config_of(mentions_run)])
    assert result['assignments'] == {('mentions', 'version', v1['id']): mentions_run['id']}
    assert result['pending'] == [('mentions', 'version', v2['id'])]


def capture_record(key, *, status='succeeded', access='redistributable'):
    record = {'kind': 'capture', 'id': _id('capture:' + key), 'recorded_at': '2026-10-20T04:00:00Z',
              'provider': 'rss', 'request_url': f'https://example.com/{key}',
              'observed_at': '2026-10-20T04:00:00Z', 'access': access, 'status': status}
    if access != 'metadata_only':
        record.update({'payload_uri': f's3://fixture/{key}', 'payload_hash': 'a' * 64,
                       'media_type': 'text/html', 'rights_basis': 'Synthetic fixture.'})
    if status == 'failed':
        record['error_code'] = 'fixture_failure'
    return record


def test_ineligible_captures_are_not_pending_extraction():
    eligible = capture_record('eligible')
    failed = capture_record('failed', status='failed')
    not_modified = capture_record('not-modified', status='not_modified')
    metadata_only = capture_record('metadata-only', access='metadata_only')
    pin = {'processor': 'extract', 'processor_version': 'v1', 'config_hash': 'f' * 64}
    result = select_runs([eligible, failed, not_modified, metadata_only], [pin])
    assert result['assignments'] == {}
    assert result['pending'] == [('extract', 'capture', eligible['id'])]


def test_metadata_only_versions_are_not_pending_clustering():
    with_text = make_version('clusterable', text='A story with text.')
    without_text = make_version('metadata-only-version')  # no text: nothing to cluster
    for processor in ('cluster', 'cluster-identical-text', 'classify', 'classify-keywords'):
        pin = {'processor': processor, 'processor_version': 'v1', 'config_hash': 'f' * 64}
        result = select_runs([with_text, without_text], [pin])
        assert result['pending'] == [(processor, 'version', with_text['id'])]


def test_entity_and_release_input_kinds_are_discovered():
    entity = {'kind': 'entity', 'id': _id('entity:input')}
    release = {'kind': 'release', 'id': _id('release:input')}
    run = run_record('export', processor='export', config={'model': 'B'},
                     inputs=[{'kind': 'entity', 'id': entity['id']},
                             {'kind': 'release', 'id': release['id']}])
    result = select_runs([entity, release, run], [config_of(run)])
    assert result['assignments'] == {
        ('export', 'entity', entity['id']): run['id'],
        ('export', 'release', release['id']): run['id'],
    }
    assert result['pending'] == []
    unmatched = {'processor': 'export', 'processor_version': 'v1', 'config_hash': 'f' * 64}
    pending = select_runs([entity, release, run], [unmatched])
    assert pending['pending'] == [('export', 'entity', entity['id']),
                                  ('export', 'release', release['id'])]
