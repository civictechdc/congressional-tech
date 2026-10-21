"""Viewer aliases require one explicit target and one usable retained body."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.filename_aliases import catalog_aliases

BODY = 'bodies/sha256/aa/' + 'a' * 64 + '.gz'
OTHER = 'bodies/sha256/bb/' + 'b' * 64 + '.gz'
URL = 'https://www.congress.gov/118/bills/hr1/BILLS-118hr1ih.pdf'


def derive(tmp_path, rows, accepted=()):
    # Keep optional source fields present even when absent in the first row.
    keys = set().union(*(r.keys() for r in rows))
    rows = [{k: r.get(k) for k in keys} for r in rows]
    path = tmp_path / 'sources.parquet'
    pq.write_table(pa.Table.from_pylist(rows), path)
    result = catalog_aliases(path, accepted)
    assert pq.read_table(path).to_pylist() == rows
    return result


def target(**extra):
    return dict(source_url=URL, body_key=BODY, media_type=['application/pdf'], **extra)


def test_recorded_target_links_without_changing_original(tmp_path):
    result = derive(tmp_path, [dict(source_url='../hr1.pdf', source_resolved_url=[URL]), target()])
    assert len(result) == 1
    assert result[0] == dict(original_url='../hr1.pdf', recovered_url=URL, body_key=BODY,
                            kind='pdf', recovery_status='recovered', recovery_basis='resolved_source_url')


@pytest.mark.parametrize('failure', [dict(http_status=['404']), dict(response_body_complete=['false']),
    dict(record_role=['error-response']), dict(source_record_type=['error-page']), dict(capture_outcome=['timeout']),
    dict(media_type=['video/mp4']), dict(body_key=None)])
def test_unusable_targets_do_not_get_links(tmp_path, failure):
    row = {**target(), **failure}
    assert derive(tmp_path, [dict(source_url='../hr1.pdf', source_resolved_url=[URL]), row]) == []


@pytest.mark.parametrize('alternate', [URL.replace('hr1', 'hr2'), 'javascript:alert(1)', '../unresolved.pdf'])
def test_conflicting_or_invalid_recorded_targets_are_not_guessed(tmp_path, alternate):
    assert derive(tmp_path, [dict(source_url='../hr1.pdf', source_resolved_url=[URL]),
        dict(source_url='../hr1.pdf', source_resolved_url=[alternate]), target()]) == []


def test_multiple_bodies_and_already_saved_original_are_not_replaced(tmp_path):
    alias = dict(source_url='../hr1.pdf', source_resolved_url=[URL])
    assert derive(tmp_path, [alias, target(), {**target(), 'body_key':OTHER}]) == []
    assert derive(tmp_path, [{**alias, 'body_key':OTHER}, target()]) == []


@pytest.mark.parametrize('original', ['ttps://www.congress.gov/118/bills/hr1/BILLS-118hr1ih.pdf',
    'mailto:' + URL, 'chrome-extension://efaidnbmnnnibpcajpcglclefindmkaj/' + URL])
def test_known_wrappers_require_exact_saved_target(tmp_path, original):
    assert derive(tmp_path, [dict(source_url=original), target()])[0]['recovered_url'] == URL
    assert derive(tmp_path, [dict(source_url=original), {**target(), 'source_url':URL+'x'}]) == []


def test_lis_wrapper(tmp_path):
    url = 'https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf'
    original = 'https://www.lis.gov/cgi-lis/t2GPO/' + url
    assert derive(tmp_path, [dict(source_url=original), {**target(), 'source_url':url}])[0]['recovered_url'] == url


def test_accepted_original_precedence_and_accepted_target(tmp_path):
    alias = dict(source_url='../hr1.pdf', source_resolved_url=[URL])
    accepted = dict(original_url=URL, recovered_url=URL, body_key=BODY, kind='pdf', recovery_status='recovered')
    assert derive(tmp_path, [alias, dict(source_url=URL)], [accepted])[0]['body_key'] == BODY
    assert derive(tmp_path, [alias, target()], [{**accepted, 'original_url':'../hr1.pdf'}]) == []
    assert derive(tmp_path, [alias, dict(source_url=URL)], [{**accepted, 'kind':'video'}]) == []


def test_legacy_and_unsafe_values_are_unchanged(tmp_path):
    assert derive(tmp_path, [target(), dict(source_url='javascript:'+URL),
        dict(source_url='mailto:https://user@www.congress.gov/a.pdf'),
        dict(source_url='mailto:'+URL+'\n')]) == []


@pytest.mark.parametrize('invalid', [None, '../hr1.pdf', 'javascript:invalid'])
def test_invalid_and_self_resolution_values_remain_conflict_evidence(tmp_path, invalid):
    assert derive(tmp_path, [dict(source_url='../hr1.pdf', source_resolved_url=[URL, invalid]), target()]) == []


def test_null_only_resolution_cannot_create_a_non_url_alias(tmp_path):
    assert derive(tmp_path, [dict(source_url='../hr1.pdf', source_resolved_url=[None]),
                             {**target(), 'source_url': None}]) == []
