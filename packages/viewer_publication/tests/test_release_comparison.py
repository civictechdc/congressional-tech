"""Row accounting across releases, on tiny releases whose answers are worked out by hand."""
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).parents[3]
from viewer_publication import release_comparison as release_diff

S, I, B = pa.string(), pa.int32(), pa.binary()
SCHEMAS = {
    'list': [('filename', S)], 'detail': [('saved_body', B)],
    'links': [('link_key', B), ('list_row', I)], 'urls': [('lookup_key', B), ('list_row', I)],
    'sources': [('list_row', I), ('url', S), ('member_path', S)],
    'recoveries': [('body', B), ('recovered_url', S), ('kind', S)],
    'meetings': [('event_id', pa.int64()), ('subject_keys', pa.list_(S))],
    'witnesses': [('occasion', S), ('name', S)], 'recordings': [('video_key', S), ('event_ids', pa.list_(pa.int64()))],
    'bills': [('bill_id', S)], 'url_state': [('requested_url', S), ('attempts', I)],
}
SCOPE = {'version': 1, 'entries': [{'family': 'x', 'patterns': [], 'exclusions': ['/oembed/']}]}


def key(letter):
    return (letter * 8).encode()


def release(directory, *, documents, sources=(), schemas=SCHEMAS, **tables):
    """`documents` lists each row's link-key letters; list and links follow from it."""
    directory.mkdir()
    data = {'list': [{'filename': keys} for keys in documents],
            'detail': [{'saved_body': None} for _ in documents],
            'links': [{'link_key': key(k), 'list_row': i} for i, keys in enumerate(documents) for k in keys],
            'sources': [dict(zip(('list_row', 'url', 'member_path'), s)) for s in sources], **tables}
    files = []
    for name, fields in schemas.items():
        rows = data.get(name, [])
        path = directory / f'{name}.parquet'
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), path)
        files.append({'name': path.name, 'rows': len(rows), 'sha256': sha256(path.read_bytes()).hexdigest()})
    (directory / 'capture_scope.json').write_text(json.dumps(SCOPE))
    (directory / 'manifest.json').write_text(json.dumps({'release_id': directory.name, 'files': files}))
    return directory


def run(tmp_path, prev, live, *extra):
    output = tmp_path / 'out.json'
    code = release_diff.main(['--base', str(prev), '--candidate', str(live), '--output', str(output), *extra])
    return code, json.loads(output.read_text())


def counts(result, name):
    return {(g['group'], g['cause']): g['count'] for g in result['files'][f'{name}.parquet']['groups']}


def evidence(path, rows):
    """Each row is (key letter, real, member path); the triple comes from its position."""
    table = [{'receipt_key': 'r', 'receipt_line': i, 'capture_index': 0, 'member_path': member, 'url': address, 'requested_url': None, 'context_url': address,
              'sha256': key(letter) + b'\0' * 24, 'is_real_file': real} for i, (letter, real, member, address) in enumerate(r + (None,) * (4 - len(r)) for r in rows)]
    fields = [('receipt_key', S), ('receipt_line', I), ('capture_index', I), ('member_path', S), ('sha256', B),
              ('is_real_file', pa.bool_()), ('url', S), ('requested_url', S), ('context_url', S)]
    pq.write_table(pa.Table.from_pylist(table, schema=pa.schema(fields)), path)
    return str(path)


@pytest.fixture
def pair(tmp_path):
    """Prev row 0 splits, rows 1 and 2 merge, row 3 goes, row 4 stays; live row 4 is new."""
    prev = release(tmp_path / 'prev', documents=['AB', 'C', 'D', 'E', 'F'],
                   sources=[(0, 'u0', None), (0, 'u0', 'm.htm'), (1, 'u1', None), (2, 'u2', None), (3, 'u3', None), (4, 'u4', None)])
    live = release(tmp_path / 'live', documents=['A', 'B', 'CD', 'F', 'G'],
                   sources=[(0, 'u0', None), (1, 'u0', None), (2, 'u1', None), (2, 'u2', None), (3, 'u4', None), (4, None, None)])
    return prev, live


def test_split_merge_removal_and_addition_are_sized_but_fail_unverified(tmp_path, pair):
    code, result = run(tmp_path, *pair)
    assert code == 1 and not result['ok']
    assert all(f['check']['ok'] for f in result['files'].values())
    assert {'unverified', 'defect'} == {g['status'] for g in result['failing']}
    assert counts(result, 'list') == {
        ('split rows', 'previous row had a member source'): 1,
        ('merged rows', 'previous rows now share one document'): -1,
        ('removed rows', 'no surviving link key'): -1,
        ('added rows', 'no surviving link key'): 1,
    }
    assert result['files']['list.parquet']['delta'] == 0
    assert counts(result, 'links') == {('removed keys', 'no evidence given'): -1, ('added keys', 'no evidence given'): 1}


def test_null_source_urls_match_with_null_safe_comparison(tmp_path, pair):
    _, result = run(tmp_path, *pair)
    groups = {g[0]: n for g, n in counts(result, 'sources').items()}
    # Member u0/m.htm gone, NULL added, u3 gone, u0 listed twice instead of once: -1 +1 -1 +1 = 0.
    assert groups == {'member rows removed': -1, 'NULL url': 1, 'URLs gone': -1, 'same-URL rows added': 1}
    assert result['files']['sources.parquet']['null_url_rows'] == {'base': 0, 'candidate': 1}
    # A NULL url present on both sides is no change at all.
    a = release(tmp_path / 'a', documents=['A'], sources=[(0, None, None)])
    b = release(tmp_path / 'b', documents=['A'], sources=[(0, None, None), (0, 'new', None)])
    _, same = run(tmp_path, a, b)
    assert counts(same, 'sources') == {('new URLs', 'no previous row has this address'): 1,
                                       ('1 NULL urls also present in the previous release', 'a published source address must not be null'): 0}


def test_shifted_list_rows_with_identical_keys_report_no_change(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'B', 'C'], sources=[(0, 'a', None), (1, 'b', None), (2, 'c', None)])
    live = release(tmp_path / 'live', documents=['C', 'A', 'B'], sources=[(0, 'c', None), (1, 'a', None), (2, 'b', None)])
    code, result = run(tmp_path, prev, live)
    assert code == 0, result['failing']
    assert result['files']['links.parquet']['digest_identical'] is False
    for name in ('list', 'links', 'sources'):
        assert counts(result, name) == {}
    assert result['files']['list.parquet']['one_to_one_rows'] == 3


def test_row_no_rule_explains_exits_one_and_is_named(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], bills=[{'bill_id': 'hr1'}, {'bill_id': 'hr2'}])
    live = release(tmp_path / 'live', documents=['A'], bills=[{'bill_id': 'hr1'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1 and not result['ok']
    assert counts(result, 'bills') == {('removed bills', 'unexplained'): -1}


def test_manifest_that_disagrees_with_the_file_fails(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'])
    live = release(tmp_path / 'live', documents=['A', 'B'])
    manifest = json.loads((live / 'manifest.json').read_text())
    next(f for f in manifest['files'] if f['name'] == 'urls.parquet')['rows'] = 5
    (live / 'manifest.json').write_text(json.dumps(manifest))
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert result['files']['urls.parquet']['delta'] == 5


def test_url_state_removal_needs_a_scope_exclusion(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], url_state=[
        {'requested_url': 'https://x/oembed/1', 'attempts': 0}, {'requested_url': 'https://x/kept', 'attempts': 1}])
    live = release(tmp_path / 'live', documents=['A'], url_state=[
        {'requested_url': 'https://x/kept', 'attempts': 1}, {'requested_url': 'https://x/new', 'attempts': 0}])
    code, result = run(tmp_path, prev, live)
    assert code == 1  # the queued URL's source page was not traced
    assert [g['group'] for g in result['failing']] == ['added URLs']
    assert counts(result, 'url_state') == {('removed URLs', 'never attempted and matches a live capture scope exclusion'): -1,
                                           ('added URLs', 'queued link with no attempts yet'): 1}


def test_evidence_ties_removed_and_added_keys_to_eligibility_flips(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'])
    live = release(tmp_path / 'live', documents=['A', 'N'])
    before = evidence(tmp_path / 'before.parquet', [('A', True, None), ('M', True, 'm.htm'), ('N', False, None)])
    after = evidence(tmp_path / 'after.parquet', [('A', True, None), ('M', False, 'm.htm'), ('N', True, None)])
    code, result = run(tmp_path, prev, live, '--evidence-base', before, '--evidence-candidate', after,
                       '--removed-keys', str(tmp_path / 'removed.csv.gz'))
    assert code == 0
    assert counts(result, 'links') == {('removed keys', 'member-only body no longer real'): -1,
                                       ('added keys', 'newly eligible body'): 1}
    assert counts(result, 'list') == {('removed rows', 'member-only body no longer real'): -1,
                                      ('added rows', 'newly eligible body'): 1}
    assert result['removed_keys_written'] == 1
    assert (tmp_path / 'removed.csv.gz').read_bytes()[4:8] == b'\0\0\0\0'  # mtime=0 keeps the file reproducible


def test_removed_key_without_a_flip_is_unexplained(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'])
    live = release(tmp_path / 'live', documents=['A'])
    same = evidence(tmp_path / 'same.parquet', [('A', True, None), ('M', True, None)])
    code, result = run(tmp_path, prev, live, '--evidence-base', same, '--evidence-candidate', same)
    assert code == 1
    assert counts(result, 'links') == {('removed keys', 'unexplained'): -1}


def test_all_link_keys_replaced_cannot_pass(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'B'])
    live = release(tmp_path / 'live', documents=['C', 'D'])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert {('links.parquet', 'no evidence given'), ('list.parquet', 'no surviving link key')} <= {
        (g['file'], g['cause']) for g in result['failing']}


def test_all_witnesses_replaced_cannot_pass(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], witnesses=[{'occasion': 'o', 'name': 'a'}])
    live = release(tmp_path / 'live', documents=['A'], witnesses=[{'occasion': 'o', 'name': 'b'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert {g['file'] for g in result['failing']} == {'witnesses.parquet'}


def test_all_source_urls_null_cannot_pass(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], sources=[(0, 'a', None)])
    live = release(tmp_path / 'live', documents=['A'], sources=[(0, None, None)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert ('NULL url', 'defect') in {(g['group'], g['status']) for g in result['failing']}


def test_recordings_need_a_readable_event_ids_column(tmp_path):
    bare = {**SCHEMAS, 'recordings': [('video_key', S)]}
    prev = release(tmp_path / 'prev', documents=['A'], recordings=[{'video_key': 'youtube:a'}], schemas=bare)
    live = release(tmp_path / 'live', documents=['A'], recordings=[{'video_key': 'youtube:a'}, {'video_key': 'youtube:b'}], schemas=bare)
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert ('event_ids column missing', 'unexplained') in {(g['group'], g['status']) for g in result['failing']}


def test_recording_is_verified_only_when_a_new_capture_names_it(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'])
    rows = [{'video_key': 'youtube:vid', 'event_ids': []}, {'video_key': 'youtube:other', 'event_ids': [7]}]
    live = release(tmp_path / 'live', documents=['A', 'N'], recordings=rows)
    before = evidence(tmp_path / 'a.parquet', [('A', True, None), ('M', True, 'm'), ('N', False, None, 'https://y/watch?v=vid')])
    after = evidence(tmp_path / 'b.parquet', [('A', True, None), ('M', False, 'm'), ('N', True, None, 'https://y/watch?v=vid')])
    code, result = run(tmp_path, prev, live, '--evidence-base', before, '--evidence-candidate', after)
    assert code == 1
    assert counts(result, 'recordings') == {('added keys', 'empty event_ids; capture newly real'): 1,
                                            ('added keys', 'with event_ids; source not traced'): 1}
    assert [g['status'] for g in result['failing']] == ['unverified']


def failing(result):
    return {(g['file'], g['status']) for g in result['failing']}


def test_null_urls_persisting_across_releases_still_fail(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], sources=[(0, None, None)])
    live = release(tmp_path / 'live', documents=['A'], sources=[(0, None, None), (0, None, None)][:1] + [(0, 'x', None)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert ('sources.parquet', 'defect') in failing(result)
    assert any('NULL urls also present' in g['group'] for g in result['failing'])
    same = release(tmp_path / 'same', documents=['A'], sources=[(0, None, None)])
    code, result = run(tmp_path, prev, same)  # identical sources digest: the check must still run
    assert code == 1 and ('sources.parquet', 'defect') in failing(result)


def test_wiped_subject_keys_raise_a_group_with_no_row_change(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], meetings=[{'event_id': 1, 'subject_keys': ['hr1']}])
    live = release(tmp_path / 'live', documents=['A'], meetings=[{'event_id': 1, 'subject_keys': []}])
    code, result = run(tmp_path, prev, live)
    assert code == 1 and failing(result) == {('meetings.parquet', 'unverified')}


def test_false_manifest_digest_raises_a_group(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'])
    live = release(tmp_path / 'live', documents=['A'])
    manifest = json.loads((live / 'manifest.json').read_text())
    next(f for f in manifest['files'] if f['name'] == 'bills.parquet')['sha256'] = '0' * 64
    (live / 'manifest.json').write_text(json.dumps(manifest))
    code, result = run(tmp_path, prev, live)
    assert code == 1 and failing(result) == {('bills.parquet', 'unexplained')}


def test_removed_url_with_attempts_is_not_verified_by_a_matching_exclusion(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], url_state=[{'requested_url': 'https://x/oembed/1', 'attempts': 9}])
    live = release(tmp_path / 'live', documents=['A'])
    code, result = run(tmp_path, prev, live)
    assert code == 1 and failing(result) == {('url_state.parquet', 'unverified')}


def test_bill_already_a_previous_subject_is_not_a_new_subject(tmp_path):
    subject = [{'event_id': 1, 'subject_keys': ['hr1']}]
    prev = release(tmp_path / 'prev', documents=['A'], meetings=subject)
    live = release(tmp_path / 'live', documents=['A'], meetings=subject, bills=[{'bill_id': 'hr1'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1 and failing(result) == {('bills.parquet', 'unexplained')}


def test_removed_key_whose_body_is_still_real_is_unexplained(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'])
    live = release(tmp_path / 'live', documents=['A'])
    before = evidence(tmp_path / 'a.parquet', [('A', True, None), ('M', True, None), ('M', True, None)])
    after = evidence(tmp_path / 'b.parquet', [('A', True, None), ('M', False, None), ('M', True, None)])
    code, result = run(tmp_path, prev, live, '--evidence-base', before, '--evidence-candidate', after)
    assert code == 1
    assert counts(result, 'links') == {('removed keys', 'unexplained'): -1}


def test_recording_key_without_a_colon_does_not_match_every_flip(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'])
    live = release(tmp_path / 'live', documents=['A', 'N'], recordings=[{'video_key': 'nocolon', 'event_ids': []}])
    before = evidence(tmp_path / 'a.parquet', [('A', True, None), ('M', True, None), ('N', False, None, 'https://y/z')])
    after = evidence(tmp_path / 'b.parquet', [('A', True, None), ('M', False, None), ('N', True, None, 'https://y/z')])
    code, result = run(tmp_path, prev, live, '--evidence-base', before, '--evidence-candidate', after)
    assert code == 1 and ('recordings.parquet', 'unverified') in failing(result)


def test_member_row_needs_its_own_flip_not_an_equal_count(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A', 'M'], sources=[(0, 'u', 'real.htm')])
    live = release(tmp_path / 'live', documents=['A', 'M'])
    before = evidence(tmp_path / 'a.parquet', [('A', True, None), ('M', True, 'unrelated.htm')])
    after = evidence(tmp_path / 'b.parquet', [('A', True, None), ('M', False, 'unrelated.htm')])
    code, result = run(tmp_path, prev, live, '--evidence-base', before, '--evidence-candidate', after)
    assert code == 1 and ('sources.parquet', 'unverified') in failing(result)
