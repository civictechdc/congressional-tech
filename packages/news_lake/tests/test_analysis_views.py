"""Slice 6 (C9): release-scoped views — politician_articles and coverage_daily.

Expectations come from the packet, not the implementation: one row per
(resolved person-root, current item, release); supersede chains count at the
survivor; only the release's selected runs contribute mentions; duplicate
spans across aliases union; unknown publication dates form one undated group;
identical-text groups stay visible as syndication, never as independent
reporting counts.
"""
import hashlib
from uuid import NAMESPACE_URL, uuid5

from news_lake.analysis import coverage_daily, politician_articles
from news_lake.analysis.views import _merge_spans
from news_lake.contract import check_corpus
from news_lake.contract.records import CONTENT_TABLES, KIND_TABLES, validate_shape
from news_lake.identity import apply_decisions

AT = '2026-10-20T04:00:00Z'
_id = lambda key: str(uuid5(NAMESPACE_URL, 'news-lake-views-test:' + key))


def _hash(name):
    return hashlib.sha256(name.encode()).hexdigest()


def _entity(key, name, entity_type='person', aliases=(), identifiers=()):
    return {'kind': 'entity', 'id': _id('entity:' + key), 'recorded_at': AT,
            'entity_type': entity_type, 'name': name, 'aliases': list(aliases),
            'identifiers': list(identifiers)}


P1 = _entity('p1', 'Alex Doe', identifiers=[{'scheme': 'fixture', 'value': 'p1'}])
# A distinct scheme, so merging P1B into P1 corroborates identity instead of
# colliding authoritative ids (C6).
P1B = _entity('p1b', 'Alex Doe', aliases=[{'value': 'A. Doe', 'language': 'en'}],
              identifiers=[{'scheme': 'fixture-alias', 'value': 'p1b'}])
P2 = _entity('p2', 'Robin Roe', identifiers=[{'scheme': 'fixture', 'value': 'p2'}])
ORG = _entity('org', 'Example Party', entity_type='organization',
              identifiers=[{'scheme': 'fixture', 'value': 'org'}])
MERGE_P1B_INTO_P1 = {
    'kind': 'identity_decision', 'id': _id('decision:merge'), 'recorded_at': AT,
    'action': 'same_as', 'left_id': P1B['id'], 'right_id': P1['id'],
    'decided_by': 'fixture:reviewer', 'reason': 'Fixture merge of the alias entity.',
}

OUTLET_A = {'kind': 'outlet', 'id': _id('outlet:a'), 'recorded_at': AT, 'name': 'Example News',
            'domains': ['a.example']}
OUTLET_B = {'kind': 'outlet', 'id': _id('outlet:b'), 'recorded_at': AT, 'name': 'Other News',
            'domains': ['b.example']}


def _capture(key):
    return {'kind': 'capture', 'id': _id('capture:' + key), 'recorded_at': AT, 'provider': 'rss',
            'request_url': f'https://a.example/{key}', 'observed_at': AT, 'http_status': 200,
            'access': 'redistributable', 'payload_uri': f's3://fixture/{key}',
            'payload_hash': _hash('capture:' + key), 'media_type': 'text/html',
            'rights_basis': 'Synthetic fixture.', 'status': 'succeeded'}


def _discovery(key, *, item_key=None, reported_publication=None):
    item_key = item_key or key
    record = {'kind': 'discovery', 'id': _id('discovery:' + key), 'recorded_at': AT,
              'capture_id': _id('capture:' + item_key), 'item_id': _id('item:' + item_key),
              'provider': 'mediacloud', 'url': f'https://a.example/{key}', 'observed_at': AT,
              'mode': 'live'}
    if reported_publication is not None:
        record['reported_publication'] = reported_publication
    return record


def _extract_run(key, capture_id):
    return {'kind': 'run', 'id': _id('run-extract:' + key), 'recorded_at': AT, 'processor': 'extract',
            'processor_version': 'fixture-1', 'config_hash': _hash('extract:' + key),
            'input_hash': _hash('extract-inputs:' + key),
            'inputs': [{'kind': 'capture', 'id': capture_id}], 'mode': 'live', 'status': 'succeeded',
            'started_at': AT, 'finished_at': AT}


def _item(key, *, outlet=OUTLET_A, version_key=None, superseded_by=None):
    record = {'kind': 'item', 'id': _id('item:' + key), 'recorded_at': AT, 'outlet_id': outlet['id'],
              'canonical_url': f"https://{outlet['domains'][0]}/{key}", 'url_aliases': [],
              'content_type': 'news_article', 'first_seen_at': AT}
    if version_key is not None:
        record['current_version_id'] = _id('version:' + version_key)
    if superseded_by is not None:
        record['superseded_by'] = _id('item:' + superseded_by)
    return record


def _version(key, *, title, publication, text=None):
    record = {'kind': 'version', 'id': _id('version:' + key), 'recorded_at': AT,
              'item_id': _id('item:' + key), 'capture_id': _id('capture:' + key),
              'run_id': _id('run-extract:' + key), 'title': title, 'publication': publication,
              'access': 'metadata_only'}
    if text is not None:
        record['access'] = 'restricted'
        record['rights_basis'] = 'Synthetic fixture.'
        record['text'] = text
        record['text_hash'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    return record


def _run(key, *, processor, config, inputs, finished_at):
    return {'kind': 'run', 'id': _id('run:' + key), 'recorded_at': finished_at, 'processor': processor,
            'processor_version': 'fixture-1', 'config_hash': _hash(processor + ':' + config),
            'input_hash': _hash(processor + '-inputs:' + key),
            'inputs': [{'kind': 'version', 'id': identifier} for identifier in inputs],
            'mode': 'reprocess', 'status': 'succeeded', 'started_at': AT, 'finished_at': finished_at}


def _mention(key, *, version_key, surface, resolution, occurrences, entity_key=None, aboutness='primary'):
    record = {'kind': 'mention', 'id': _id('mention:' + key), 'recorded_at': AT,
              'version_id': _id('version:' + version_key), 'run_id': _id('run:link2'),
              'surface': surface, 'resolution': resolution, 'aboutness': aboutness,
              'occurrences': occurrences}
    if entity_key is not None:
        record['entity_id'] = _id('entity:' + entity_key)
    return record


def _story(key, run_key):
    return {'kind': 'story', 'id': _id('story:' + key), 'recorded_at': AT, 'run_id': _id('run:' + run_key)}


def _member(story_key, version_key, run_key):
    return {'kind': 'story_member', 'id': _id('member:' + story_key + ':' + version_key),
            'recorded_at': AT, 'story_id': _id('story:' + story_key),
            'version_id': _id('version:' + version_key), 'run_id': _id('run:' + run_key)}


# -- the scenario ---------------------------------------------------------------------

V1 = _version('v1', title='Alex Doe speaks at the council',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
              text='Council member Alex Doe and Alex Doe spoke.')
V2 = _version('v2', title='Council roundup',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'},
              text='Council member Alex Doe and Alex Doe spoke.')  # identical text: syndication
V3 = _version('v3', title='Who is Alex Doe?', publication={'precision': 'unknown'})
V5 = _version('v5', title='Robin Roe resigns',
              publication={'precision': 'instant', 'at': '2026-10-19T18:30:00Z', 'basis': 'publisher'},
              text='Robin Roe resigned Monday.')
V6 = _version('v6', title='Example Party announces platform',
              publication={'precision': 'day', 'date': '2026-10-18', 'basis': 'publisher'})

I1 = _item('v1', version_key='v1')
I2 = _item('v2', outlet=OUTLET_B, version_key='v2')
I3 = _item('v3', version_key='v3')
I4 = _item('v4')  # superseded duplicate of the Robin Roe appearance
I5 = _item('v5', version_key='v5')
I6 = _item('v6', version_key='v6')
I4['superseded_by'] = I5['id']

LINKED = [_id('version:' + key) for key in ('v1', 'v3', 'v5', 'v6')]
RUN_LINK_OLD = _run('link1', processor='mentions', config='model-A', inputs=[_id('version:v1')],
                    finished_at='2026-10-20T05:00:00Z')
RUN_LINK = _run('link2', processor='mentions', config='model-B', inputs=LINKED,
                finished_at='2026-10-20T06:00:00Z')
RUN_CLUSTER = _run('cluster1', processor='cluster', config='identical-text',
                   inputs=[_id('version:' + key) for key in ('v1', 'v2', 'v5')],
                   finished_at='2026-10-20T06:30:00Z')
STORY_SYNDICATION = _story('syndication', 'cluster1')
STORY_ROE = _story('roe', 'cluster1')

M_OLD = _mention('old', version_key='v1', surface='Alex Doe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 8}], entity_key='p1')
M1 = _mention('m1', version_key='v1', surface='Alex Doe', resolution='resolved',
              occurrences=[{'field': 'title', 'start': 0, 'end': 8},
                           {'field': 'text', 'start': 15, 'end': 23}], entity_key='p1')
M2 = _mention('m2', version_key='v1', surface='Alex Doe', resolution='resolved',
              occurrences=[{'field': 'title', 'start': 0, 'end': 8},
                           {'field': 'text', 'start': 28, 'end': 36}], entity_key='p1b')
M_AMBIGUOUS = _mention('amb', version_key='v3', surface='Alex Doe', resolution='ambiguous',
                       occurrences=[{'field': 'title', 'start': 7, 'end': 15}], aboutness='unknown')
M_ROE = _mention('roe', version_key='v5', surface='Robin Roe', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 9},
                              {'field': 'text', 'start': 0, 'end': 9}], entity_key='p2')
M_ORG = _mention('org', version_key='v6', surface='Example Party', resolution='resolved',
                 occurrences=[{'field': 'title', 'start': 0, 'end': 13}], entity_key='org')
# The old run's mention carries its own run id (not the selected one).
M_OLD['run_id'] = RUN_LINK_OLD['id']

SHELLS = []
for key in ('v1', 'v2', 'v3', 'v5', 'v6'):
    SHELLS.extend([_capture(key), _extract_run(key, _id('capture:' + key))])

CORPUS = [
    OUTLET_A, OUTLET_B, I1, I2, I3, I4, I5, I6, V1, V2, V3, V5, V6,
    P1, P1B, P2, ORG, MERGE_P1B_INTO_P1,
    RUN_LINK_OLD, RUN_LINK, RUN_CLUSTER,
    STORY_SYNDICATION, STORY_ROE,
    _member('syndication', 'v1', 'cluster1'), _member('syndication', 'v2', 'cluster1'),
    _member('roe', 'v5', 'cluster1'),
    M_OLD, M1, M2, M_AMBIGUOUS, M_ROE, M_ORG,
    *SHELLS,
]

SELECTIONS = [
    {'processor': 'mentions', 'processor_version': 'fixture-1', 'config_hash': RUN_LINK['config_hash']},
    {'processor': 'cluster', 'processor_version': 'fixture-1', 'config_hash': RUN_CLUSTER['config_hash']},
]


def release_read_of(records, selections):
    """Build the read_release shape directly; storage tests cover its fidelity."""
    tables = {}
    for record in records:
        tables.setdefault(KIND_TABLES[record['kind']], []).append(record)
    release = {'kind': 'release', 'id': _id('release:views'), 'recorded_at': AT,
               'contract_version': '0.1.0',
               'snapshots': [{'table': table, 'table_uuid': _id('uuid:' + table)}
                             for table in CONTENT_TABLES],
               'selections': list(selections), 'checkpoints': []}
    validate_shape(release)
    return {'release': release, 'tables': tables}


def test_fixture_scenario_is_a_valid_corpus():
    check_corpus(CORPUS)


# -- politician_articles --------------------------------------------------------------


def _rows():
    return politician_articles(release_read_of(CORPUS, SELECTIONS), apply_decisions(CORPUS))


def _row_for(rows, person):
    return next(row for row in rows if row['person_root_id'] == person['id'])


def test_one_row_per_person_root_item_and_release():
    rows = _rows()
    keys = [(row['person_root_id'], row['item_id']) for row in rows]
    # Merged P1B into P1: one row for the root, not two. The superseded item
    # counts at its survivor (I5, never I4); ambiguous/org mentions assert
    # nothing; I2 carries no mention; every row names the release.
    assert sorted(keys) == sorted([(P1['id'], I1['id']), (P2['id'], I5['id'])])
    assert all(row['release_id'] == _id('release:views') for row in rows)


def test_row_keeps_version_run_aboutness_and_unioned_spans():
    doe = _row_for(_rows(), P1)
    assert doe['version_id'] == V1['id']  # current_version_id selects the text
    assert doe['entity_ids'] == sorted([P1['id'], P1B['id']])  # both aliases' entities
    assert doe['run_ids'] == [RUN_LINK['id']]  # the selected linking run only
    assert doe['aboutness'] == ['primary']
    # C9: duplicate spans across aliases union — the title span appears in both
    # M1 and M2 and collapses; the two disjoint text spans stay separate.
    assert doe['spans'] == [
        {'field': 'text', 'surface': 'Alex Doe', 'start': 15, 'end': 23},
        {'field': 'text', 'surface': 'Alex Doe', 'start': 28, 'end': 36},
        {'field': 'title', 'surface': 'Alex Doe', 'start': 0, 'end': 8},
    ]
    roe = _row_for(_rows(), P2)
    assert roe['version_id'] == V5['id'] and roe['item_id'] == I5['id']
    assert roe['spans'] == [{'field': 'text', 'surface': 'Robin Roe', 'start': 0, 'end': 9},
                            {'field': 'title', 'surface': 'Robin Roe', 'start': 0, 'end': 9}]


def test_mentions_of_unselected_runs_do_not_count():
    doe = _row_for(_rows(), P1)
    assert M_OLD['run_id'] not in doe['run_ids']
    # Pin a mentions triple no run matches: no mention of this release is
    # selected, so the person has no row at all — unprocessed inputs stay
    # visibly pending rather than silently falling back to an older run (C8).
    runless = [dict(selection, config_hash='f' * 64)
               if selection['processor'] == 'mentions' else selection for selection in SELECTIONS]
    rows_unprocessed = politician_articles(release_read_of(CORPUS, runless), apply_decisions(CORPUS))
    assert (P1['id'], I1['id']) not in [(row['person_root_id'], row['item_id'])
                                        for row in rows_unprocessed]


def test_release_pinned_decisions_apply_by_default():
    """Without an explicit decision_result, the release's own pinned
    news.identity_decisions table resolves same_as merges."""
    assert politician_articles(release_read_of(CORPUS, SELECTIONS)) == _rows()


def test_explicit_decision_result_overrides_release_decisions():
    rows = politician_articles(release_read_of(CORPUS, SELECTIONS), {'roots': {}})
    keys = [(row['person_root_id'], row['item_id']) for row in rows]
    assert sorted(keys) == sorted([(P1['id'], I1['id']), (P1B['id'], I1['id']), (P2['id'], I5['id'])])


# -- span merging ---------------------------------------------------------------------


def test_adjacent_spans_stay_separate():
    """Span ends are exclusive: [0, 8) and [8, 16) are disjoint."""
    version = {'title': 'ABCDEFGHIJKLMNOP'}
    spans = [
        {'field': 'title', 'surface': 'ABCDEFGH', 'start': 0, 'end': 8},
        {'field': 'title', 'surface': 'IJKLMNOP', 'start': 8, 'end': 16},
    ]
    assert _merge_spans(spans, version=version) == [
        {'field': 'title', 'surface': 'ABCDEFGH', 'start': 0, 'end': 8},
        {'field': 'title', 'surface': 'IJKLMNOP', 'start': 8, 'end': 16},
    ]


def test_overlapping_spans_merge_with_the_merged_surface():
    version = {'title': 'ABCDEFGHIJKLMNOP'}
    spans = [
        {'field': 'title', 'surface': 'ABCDEFGH', 'start': 0, 'end': 8},
        {'field': 'title', 'surface': 'EFGHIJKL', 'start': 4, 'end': 12},
    ]
    assert _merge_spans(spans, version=version) == [
        {'field': 'title', 'surface': 'ABCDEFGHIJKL', 'start': 0, 'end': 12},
    ]


def test_overlapping_spans_without_text_keep_a_contributing_surface():
    spans = [
        {'field': 'title', 'surface': 'ABC', 'start': 0, 'end': 3},
        {'field': 'title', 'surface': 'BCDE', 'start': 1, 'end': 5},
    ]
    assert _merge_spans(spans, version=None) == [
        {'field': 'title', 'surface': 'BCDE', 'start': 0, 'end': 5},
    ]


# -- coverage_daily -------------------------------------------------------------------


def test_coverage_counts_distinct_items_outlets_and_stories():
    rows = coverage_daily(release_read_of(CORPUS, SELECTIONS), apply_decisions(CORPUS))
    by_date = {row['date']: row for row in rows}
    # Day bucket 2026-10-18: I1, I2 (identical text, two outlets), I6.
    day = by_date['2026-10-18']
    assert (day['items'], day['outlets'], day['stories']) == (3, 2, 1)
    assert day['undated'] is False and day['release_id'] == _id('release:views')
    # Instant bucket: the UTC date of the instant, survivor item only (I4 not
    # counted separately), one story.
    instant = by_date['2026-10-19']
    assert (instant['items'], instant['outlets'], instant['stories']) == (1, 1, 1)


def test_unknown_dates_form_one_undated_group_never_a_fake_date():
    rows = coverage_daily(release_read_of(CORPUS, SELECTIONS), apply_decisions(CORPUS))
    undated = [row for row in rows if row['undated']]
    assert len(undated) == 1
    assert undated[0]['date'] is None
    assert undated[0]['items'] == 1  # I3
    assert all(row['date'] is None or len(row['date']) == 10 for row in rows)


def test_identical_text_groups_are_syndication_visibility_not_independence():
    rows = coverage_daily(release_read_of(CORPUS, SELECTIONS), apply_decisions(CORPUS))
    day = next(row for row in rows if row['date'] == '2026-10-18')
    # Two items share one normalized text: the group is listed, the story count
    # stays one story, and the row reports items (2 syndicated + 1 other).
    assert len(day['identical_text_group_ids']) == 1
    assert day['stories'] == 1
    assert day['items'] == 3
    # A bucket with no duplicated text lists no groups.
    instant = next(row for row in rows if row['date'] == '2026-10-19')
    assert instant['identical_text_group_ids'] == []


def test_cross_day_syndication_stays_visible_in_both_date_buckets():
    import copy

    corpus = copy.deepcopy(CORPUS)
    v2 = next(r for r in corpus if r['id'] == V2['id'])
    v2['publication'] = {'precision': 'day', 'date': '2026-10-19', 'basis': 'publisher'}
    rows = coverage_daily(release_read_of(corpus, SELECTIONS), apply_decisions(corpus))
    by_date = {row['date']: row for row in rows}
    assert len(by_date['2026-10-18']['identical_text_group_ids']) == 1
    assert (
        by_date['2026-10-18']['identical_text_group_ids']
        == by_date['2026-10-19']['identical_text_group_ids']
    )


def test_versionless_item_uses_unambiguous_discovery_date():
    item = _item('mc')  # no current_version_id: Media Cloud style
    corpus = [OUTLET_A, item, _capture('mc'), _discovery(
        'mc', reported_publication={'precision': 'day', 'date': '2026-10-17', 'basis': 'provider'})]
    check_corpus(corpus)
    rows = coverage_daily(release_read_of(corpus, []))
    assert [(row['date'], row['undated'], row['items']) for row in rows] == [
        ('2026-10-17', False, 1),
    ]


def test_unknown_version_precision_falls_back_to_discovery_date():
    item = _item('mc', version_key='mc')
    version = _version('mc', title='Provider story', publication={'precision': 'unknown'})
    corpus = [OUTLET_A, item, _capture('mc'), _extract_run('mc', _id('capture:mc')), version,
              _discovery('mc', reported_publication={
                  'precision': 'instant', 'at': '2026-10-17T23:30:00Z', 'basis': 'provider'})]
    check_corpus(corpus)
    rows = coverage_daily(release_read_of(corpus, []))
    assert [(row['date'], row['undated'], row['items']) for row in rows] == [
        ('2026-10-17', False, 1),
    ]


def test_conflicting_discovery_dates_stay_undated():
    item = _item('mc')
    corpus = [
        OUTLET_A, item, _capture('mc'),
        _discovery('mc-a', item_key='mc', reported_publication={
            'precision': 'day', 'date': '2026-10-17', 'basis': 'provider'}),
        _discovery('mc-b', item_key='mc', reported_publication={
            'precision': 'day', 'date': '2026-10-16', 'basis': 'provider'}),
        _discovery('mc-c', item_key='mc', reported_publication={'precision': 'unknown'}),
    ]
    check_corpus(corpus)
    rows = coverage_daily(release_read_of(corpus, []))
    assert [(row['date'], row['undated'], row['items']) for row in rows] == [(None, True, 1)]


def test_release_scope_indexes_mentions_and_stories_without_rescanning():
    from news_lake.analysis.views import _ReleaseScope

    scope = _ReleaseScope(release_read_of(CORPUS, SELECTIONS))
    # Clearing records after __init__ proves selected_mentions / selected_story
    # use the O(1) pre-indexed maps rather than rescanning self.records per item.
    scope.records = None
    assert len(scope.selected_mentions(V1['id'])) == 2
    assert scope.selected_story(V1['id']) == STORY_SYNDICATION['id']
