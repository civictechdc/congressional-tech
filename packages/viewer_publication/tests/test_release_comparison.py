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
    'witnesses': [('witness_key', S), ('occasion', S), ('name', S), ('organization', S)], 'recordings': [('video_key', S), ('event_ids', pa.list_(pa.int64()))],
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
            'sources': [s if isinstance(s, dict) else dict(zip(('list_row', 'url', 'member_path'), s)) for s in sources], **tables}
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


def test_shifted_list_rows_with_identical_keys_need_a_recorded_cause(tmp_path):
    """No key or value differs, but bytes did: the comparison says so instead of passing."""
    prev = release(tmp_path / 'prev', documents=['A', 'B', 'C'], sources=[(0, 'a', None), (1, 'b', None), (2, 'c', None)])
    live = release(tmp_path / 'live', documents=['C', 'A', 'B'], sources=[(0, 'c', None), (1, 'a', None), (2, 'b', None)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert result['files']['links.parquet']['digest_identical'] is False
    nothing = {('changed bytes, no key or value difference found', 'unexplained'): 0}
    for name in ('list', 'links', 'sources'):
        assert counts(result, name) == nothing
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
    # Every group is verified, yet the removed key M has no redirect or removal notice:
    # the link rule alone refuses (gate 2).
    assert code == 1 and result['failing'] == []
    assert result['link_rule']['missing_keys'] == [key('M').hex()] and result['link_rule']['dangling'] == 0
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
    prev = release(tmp_path / 'prev', documents=['A'], witnesses=[{'witness_key': 'w1', 'occasion': 'o', 'name': 'a'}])
    live = release(tmp_path / 'live', documents=['A'], witnesses=[{'witness_key': 'w2', 'occasion': 'o', 'name': 'b'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert {g['file'] for g in result['failing']} == {'witnesses.parquet'}


def test_witness_value_rewritten_on_a_matched_key_is_a_group(tmp_path):
    """red-h probe 1: an organization rewritten under the same witness_key passed before."""
    row = lambda org: [{'witness_key': 'w1', 'occasion': 'o', 'name': 'Ann', 'organization': org}]
    code, result = run(tmp_path, release(tmp_path / 'prev', documents=['A'], witnesses=row('GAO')),
                       release(tmp_path / 'live', documents=['A'], witnesses=row('Totally Wrong Org')))
    assert code == 1
    assert counts(result, 'witnesses') == {('changed organization', 'value differs on matched key'): 1}


REKEY_SCHEMAS = {**SCHEMAS, 'list': [('filename', S), ('witness_keys', pa.list_(S))],
                 'witnesses': [('witness_key', S), ('occasion', S), ('record_sha', S), ('name', S), ('organization', S), ('superseded_by', S)],
                 'witness_key_map': [('old_key', S), ('witness_key', S), ('status', S), ('basis', S), ('candidate_keys', pa.list_(S))]}


def rekey_release(directory, witnesses, keys, mapped):
    """One document listing `keys`; witnesses are (key, record, name, organization, superseded_by)."""
    return release(directory, documents=['A'], schemas=REKEY_SCHEMAS,
                   list=[{'filename': 'A', 'witness_keys': keys}],
                   witnesses=[dict(zip(('witness_key', 'record_sha', 'name', 'organization', 'superseded_by'), w), occasion='meeting:1')
                              for w in witnesses],
                   witness_key_map=[dict(zip(('old_key', 'witness_key', 'status', 'basis'), m),
                                         candidate_keys=list(m[4]) if len(m) > 4 else []) for m in mapped])


def test_witnesses_re_keyed_through_the_published_map_are_explained(tmp_path):
    """ct-kb4w: a re-fetched body re-keys its witnesses; only what the map does not carry needs a cause."""
    prev = rekey_release(tmp_path / 'prev', [('w1', 'r0', 'Ann', 'GAO', None), ('w2', 'r0', 'Ann', 'GAO', 'w1'),
                                             ('w3', 'r0', 'Bob', 'CBO', None), ('w4', 'r0', 'Cy', None, None)],
                         ['w1', 'w3'], [('o1', 'w1', 'unambiguous', 'content')])
    live = rekey_release(tmp_path / 'live', [('n1', 'r1', 'Ann', 'GAO', None), ('n2', 'r1', 'Ann', 'GAO', 'n1'),
                                             ('n3', 'r1', 'Bob', 'Budget Office', None), ('n5', 'r1', 'Dee', None, None)],
                         ['n1', 'n3'], [('o1', 'n1', 'unambiguous', 'content'), ('w1', 'n1', 'unambiguous', 'content'),
                                        ('w2', 'n2', 'unambiguous', 'content'), ('w3', 'n3', 'unambiguous', 'locator'),
                                        ('w4', None, 'unresolved', None)])
    code, result = run(tmp_path, prev, live)
    assert counts(result, 'witnesses') == {
        ('removed keys', 're-keyed: witness_key_map names the published successor'): -3,
        ('removed keys', 'witness_key_map states the key unresolved'): -1,
        ('added keys', 'successor of a re-keyed witness'): 3,
        ('added keys', 'no evidence given'): 1,
        ('changed organization', 'value differs on matched key'): 1,  # the re-keyed pair is compared too
    }
    assert counts(result, 'list') == {('changed witness_keys', 're-keyed through witness_key_map'): 1}
    assert counts(result, 'witness_key_map') == {('added keys', 'key retired from witnesses in this release'): 4}
    assert code == 1 and {(g['file'], g['group']) for g in result['failing']} == {
        ('witnesses.parquet', 'removed keys'), ('witnesses.parquet', 'added keys'), ('witnesses.parquet', 'changed organization')}


@pytest.mark.parametrize('surviving_key', ['w1', 'n1'])
def test_a_map_that_collapses_distinct_base_occurrences_is_not_explained(tmp_path, surviving_key):
    previous = rekey_release(tmp_path / 'prev', [('w1', 'r0', 'Ann', 'GAO', None), ('w2', 'r0', 'Ann', 'GAO', None)],
                             ['w1', 'w2'], [('earlier', 'w1', 'unambiguous', 'content')])
    mappings = [(key, surviving_key, 'unambiguous', 'content')
                for key in ('earlier', 'w1', 'w2') if key != surviving_key]
    current = rekey_release(tmp_path / 'live', [(surviving_key, 'r1', 'Ann', 'GAO', None)],
                            [surviving_key], mappings)
    code, report = run(tmp_path, previous, current)
    assert code == 1
    assert counts(report, 'witnesses')[('removed keys', 'witness_key_map collapses distinct base occurrences')] == (
        -1 if surviving_key == 'w1' else -2)
    assert counts(report, 'list') == {('changed witness_keys', 'value differs on matched key'): 1}


def test_a_map_that_names_the_wrong_successor_is_not_explained(tmp_path):
    """The planted case: an unambiguous row whose successor is not published, and a key the map dropped."""
    prev = rekey_release(tmp_path / 'prev', [('w1', 'r0', 'Ann', 'GAO', None), ('w2', 'r0', 'Bob', None, None)], ['w1'],
                         [('o1', 'w1', 'unambiguous', 'content'), ('o2', 'w2', 'unambiguous', 'content')])
    live = rekey_release(tmp_path / 'live', [('n1', 'r1', 'Ann', 'GAO', None), ('n2', 'r1', 'Bob', None, None)], ['n2'],
                         [('w1', 'gone', 'unambiguous', 'content'), ('o2', 'n2', 'unambiguous', 'content'),
                          ('w2', 'n2', 'unambiguous', 'content')])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'witnesses')[('removed keys', 'unexplained')] == -1
    assert counts(result, 'list')[('changed witness_keys', 'value differs on matched key')] == 1  # w1 listed, n2 now
    assert counts(result, 'witness_key_map') == {('removed keys', 'no longer resolves'): -1,
                                                 ('added keys', 'key retired from witnesses in this release'): 2}


def test_source_address_moved_to_another_document_is_a_group(tmp_path):
    """red-h probe 2: the same address now on document B, at equal multiplicity."""
    prev = release(tmp_path / 'prev', documents=['A', 'B'], sources=[(0, 'https://x/a', None), (1, 'https://x/b', None)])
    live = release(tmp_path / 'live', documents=['A', 'B'], sources=[(1, 'https://x/a', None), (1, 'https://x/b', None)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert ('documents changed for a shared key', 'the key now answers other documents') in counts(result, 'sources')


def test_lookup_key_repointed_to_another_document_is_a_group(tmp_path):
    """red-h probe 3: a URL lookup key now answers the other document."""
    url = lambda row: [{'lookup_key': key('u'), 'list_row': row}]
    code, result = run(tmp_path, release(tmp_path / 'prev', documents=['A', 'B'], urls=url(0)),
                       release(tmp_path / 'live', documents=['A', 'B'], urls=url(1)))
    assert code == 1
    assert counts(result, 'urls') == {('documents changed for a shared key', 'the key now answers other documents'): 1}


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
    assert counts(result, 'meetings') == {('changed subject_keys', 'value differs on matched key'): 1}


def test_swapped_subject_key_is_a_value_group(tmp_path):
    """ct-d3tk: release_diff exited 0 on a swapped key; the comparison now refuses it."""
    prev = release(tmp_path / 'prev', documents=['A'], meetings=[{'event_id': 1, 'subject_keys': ['hr1']}])
    live = release(tmp_path / 'live', documents=['A'], meetings=[{'event_id': 1, 'subject_keys': ['hr2']}])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'meetings') == {('changed subject_keys', 'value differs on matched key'): 1}
    assert result['files']['meetings.parquet']['check']['ok']  # a value group is outside the row sum


COMMITTEES = [('system_code', S), ('name', S), ('chamber', S)]


def test_changed_file_without_handler_fails(tmp_path):
    """committees has no special handler: its registry key compares values at equal row counts."""
    schemas = {**SCHEMAS, 'committees': COMMITTEES}
    prev = release(tmp_path / 'prev', documents=['A'], schemas=schemas,
                   committees=[{'system_code': 'hsag00', 'name': 'Agriculture', 'chamber': 'House'}])
    live = release(tmp_path / 'live', documents=['A'], schemas=schemas,
                   committees=[{'system_code': 'hsag00', 'name': 'Agriculture!', 'chamber': 'House'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1 and result['files']['committees.parquet']['delta'] == 0
    assert counts(result, 'committees') == {('changed name', 'value differs on matched key'): 1}


def test_changed_file_with_no_comparison_at_all_is_refused(tmp_path):
    schemas = {**SCHEMAS, 'mystery': [('x', S)]}
    prev = release(tmp_path / 'prev', documents=['A'], schemas=schemas, mystery=[{'x': 'a'}])
    live = release(tmp_path / 'live', documents=['A'], schemas=schemas, mystery=[{'x': 'b'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'mystery') == {('changed file without a comparison', 'unexplained'): 0}


def test_added_and_removed_files_are_groups(tmp_path):
    prev = release(tmp_path / 'prev', documents=['A'], schemas={**SCHEMAS, 'committees': COMMITTEES},
                   committees=[{'system_code': 'a', 'name': 'n', 'chamber': 'c'}])
    live = release(tmp_path / 'live', documents=['A'], schemas={**SCHEMAS, 'url_variants': [('canonical_url', S), ('variant_url', S)]},
                   url_variants=[{'canonical_url': 'a', 'variant_url': 'b'}, {'canonical_url': 'c', 'variant_url': 'd'}])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'committees') == {('file removed', 'file absent from the candidate release'): -1}
    assert counts(result, 'url_variants') == {('file added', 'file absent from the base release'): 2}


SOURCES_FULL = [('list_row', I), ('url', S), ('member_path', S), ('is_saved', pa.bool_()), ('first_seen', pa.date32())]


def test_sources_value_change_on_matched_address_is_a_group(tmp_path):
    from datetime import date
    schemas = {**SCHEMAS, 'sources': SOURCES_FULL}
    row = lambda saved: {'list_row': 0, 'url': 'u', 'member_path': None, 'is_saved': saved, 'first_seen': date(2026, 1, 1)}
    prev = release(tmp_path / 'prev', documents=['A'], schemas=schemas, sources=[row(True)])
    live = release(tmp_path / 'live', documents=['A'], schemas=schemas, sources=[row(False)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'sources') == {('changed is_saved', 'value differs on matched key'): 1}


def test_recovery_value_change_is_a_group(tmp_path):
    schemas = {**SCHEMAS, 'recoveries': [('list_row', I), ('body', B), ('recovered_url', S), ('kind', S), ('bytes', pa.int64())]}
    row = lambda size: {'list_row': 0, 'body': b'b' * 32, 'recovered_url': 'r', 'kind': 'recovered_document', 'bytes': size}
    prev = release(tmp_path / 'prev', documents=['A'], schemas=schemas, recoveries=[row(10)])
    live = release(tmp_path / 'live', documents=['A'], schemas=schemas, recoveries=[row(11)])
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'recoveries') == {('changed bytes', 'value differs on matched key'): 1}


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


SITTING_OLD = pa.struct([('start', pa.string()), ('place', S)])
SITTING_NEW = pa.struct([('start', pa.string()), ('place', S), ('room', S)])


def test_a_changed_shared_subfield_surfaces_beside_an_added_subfield(tmp_path):
    """meetings.sittings gained room: the whole struct differs on every row, but a real change
    to an existing subfield (start) must still be its own group, and room an addition."""
    old = {**SCHEMAS, 'meetings': [('event_id', pa.int64()), ('subject_keys', pa.list_(S)), ('sittings', pa.list_(SITTING_OLD))]}
    new = {**SCHEMAS, 'meetings': [('event_id', pa.int64()), ('subject_keys', pa.list_(S)), ('sittings', pa.list_(SITTING_NEW)),
                                   ('not_held', pa.bool_())]}
    rows = lambda start, room=None, **extra: [dict(event_id=1, subject_keys=[], sittings=[dict(start='09:00', place='Rayburn', **({'room': room} if room else {}))], **extra),
                                               dict(event_id=2, subject_keys=[], sittings=[dict(start=start, place='Dirksen', **({'room': room} if room else {}))], **extra)]
    prev = release(tmp_path / 'prev', documents=['A'], schemas=old, meetings=rows('10:00'))
    live = release(tmp_path / 'live', documents=['A'], schemas=new, meetings=rows('14:00', room='2123', not_held=False))
    code, result = run(tmp_path, prev, live)
    assert code == 1
    assert counts(result, 'meetings') == {
        ('changed sittings[].start', 'value differs on matched key'): 1,
        ('added subfield sittings[].room', 'subfield new in the candidate, set on matched rows'): 2}
    assert result['cannot_see'] == ['meetings.not_held: new in the candidate; no base values to compare']


def test_null_urls_removed_from_the_candidate_are_not_reported_as_persisting(tmp_path):
    """Base has 2 NULL source URLs and the candidate none: the NULL url group is -2, and no
    'also present in the previous release' defect may appear (causes agent, 72 on 448651e7)."""
    prev = release(tmp_path / 'prev', documents=['A'], sources=[(0, None, None), (0, None, None), (0, 'a', None)])
    live = release(tmp_path / 'live', documents=['A'], sources=[(0, 'a', None)])
    _, result = run(tmp_path, prev, live)
    groups = counts(result, 'sources')
    assert groups[('NULL url', 'defect: a published source address must not be null')] == -2
    assert not any('also present' in name for name, _ in groups)


# ct-syp1: the weekly video cache refresh rewrites every citation of a cache file.
TS = pa.timestamp('us', tz='UTC')
VIDEO_SCHEMAS = dict(SCHEMAS, channels=[('handle', S), ('title', S), ('record_sha', B)],
                     videos=[('video_key', S), ('handle', S), ('title', S), ('duration_seconds', I),
                             ('details_checked_at', TS), ('record_sha', B)],
                     recording_matches=[('match_id', S), ('video_key', S), ('basis', S), ('source_ref', S)])
# Written out, not imported: a reworded cause changes every recorded group id.
CHURN = 'only the file citation moved: every content column equal on the row'
CITED = "citation follows the video's record_sha: every other column equal on the row"
PLAIN = 'value differs on matched key'


def file_hash(name):
    return sha256(name.encode()).digest()


def cited(name):
    return 'video_records:' + file_hash(name).hex()


def video_release(directory, files, checked, *, change=None, schemas=VIDEO_SCHEMAS):
    """Two cache files (`files` names this fetch of each) holding channels @a and @b, and @c; `api`
    is a video read from an API record, which no refresh rewrites. `change(tables)` plants a value."""
    from datetime import datetime, timezone
    first, second = files
    at = datetime(2026, 11, checked, tzinfo=timezone.utc)
    video = lambda key, handle, source: dict(video_key=key, handle=handle, title=key, duration_seconds=60,
                                             details_checked_at=at, record_sha=file_hash(source))
    tables = dict(
        channels=[dict(handle=h, title=h, record_sha=file_hash(f)) for h, f in (('@a', first), ('@b', first), ('@c', second))],
        videos=[video('a1', '@a', first), video('a2', '@a', first), video('b1', '@b', first), video('c1', '@c', second),
                dict(video('api', '@a', 'api-record'), details_checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc))],
        recording_matches=[dict(match_id='m1', video_key='a1', basis='video_states_event_id', source_ref=cited(first)),
                           dict(match_id='m2', video_key='c1', basis='video_states_event_id', source_ref=cited(second)),
                           dict(match_id='m3', video_key=None, basis='curated', source_ref='recording_decisions:d1')])
    if change:
        change(tables)
    return release(directory, documents=['A'], schemas=schemas, **tables)


def refresh(tmp_path, change=None, *, files=('new-1', 'new-2'), checked=8, schemas=VIDEO_SCHEMAS):
    prev = video_release(tmp_path / 'prev', ('old-1', 'old-2'), 1)
    live = video_release(tmp_path / 'live', files, checked, change=change, schemas=schemas)
    _, result = run(tmp_path, prev, live)
    return result


def test_a_cache_refresh_that_changes_no_content_is_proven_without_a_record(tmp_path):
    result = refresh(tmp_path)
    assert counts(result, 'channels') == {('changed record_sha', CHURN): 3}
    assert counts(result, 'videos') == {('changed record_sha', CHURN): 4, ('changed details_checked_at', CHURN): 4}
    assert counts(result, 'recording_matches') == {('changed source_ref', CITED): 2}
    assert result['ok'] and result['failing'] == []


def row(tables, name, key):
    return next(r for r in tables[name] if key in r.values())


def plant(name, key, **values):
    return lambda tables: row(tables, name, key).update(values)


@pytest.mark.parametrize('change,table,expected', [
    # A changed title or duration is its own group, and the row's citation is not proven either.
    (plant('videos', 'a1', title='A new title'), 'videos',
     {('changed record_sha', CHURN): 3, ('changed details_checked_at', CHURN): 3, ('changed record_sha', PLAIN): 1,
      ('changed details_checked_at', PLAIN): 1, ('changed title', PLAIN): 1}),
    (plant('videos', 'c1', duration_seconds=61), 'videos',
     {('changed record_sha', CHURN): 3, ('changed details_checked_at', CHURN): 3, ('changed record_sha', PLAIN): 1,
      ('changed details_checked_at', PLAIN): 1, ('changed duration_seconds', PLAIN): 1}),
    # One row cites a hash that is not its channel's file.
    (plant('videos', 'a2', record_sha=file_hash('not-a-file')), 'videos',
     {('changed record_sha', CHURN): 3, ('changed details_checked_at', CHURN): 3, ('changed record_sha', PLAIN): 1,
      ('changed details_checked_at', PLAIN): 1}),
    # The check time went backwards or was emptied: an older file was read, not a newer one.
    (plant('videos', 'b1', details_checked_at=None), 'videos',
     {('changed record_sha', CHURN): 3, ('changed details_checked_at', CHURN): 3, ('changed record_sha', PLAIN): 1,
      ('changed details_checked_at', PLAIN): 1}),
    # An API-sourced row that now cites a cache file changed its source, not its file.
    (plant('videos', 'api', record_sha=file_hash('new-1')), 'videos',
     {('changed record_sha', CHURN): 4, ('changed details_checked_at', CHURN): 4, ('changed record_sha', PLAIN): 1}),
    # A changed channel proves nothing for itself or for the videos that cite its file through it.
    (plant('channels', '@a', title='Renamed'), 'channels', {('changed record_sha', CHURN): 2, ('changed record_sha', PLAIN): 1, ('changed title', PLAIN): 1}),
    (plant('channels', '@a', title='Renamed'), 'videos',
     {('changed record_sha', CHURN): 2, ('changed details_checked_at', CHURN): 2, ('changed record_sha', PLAIN): 2,
      ('changed details_checked_at', PLAIN): 2}),
    # A match re-pointed at another video, citing another video's file, or citing another decision.
    (plant('recording_matches', 'm1', video_key='a2'), 'recording_matches',
     {('changed source_ref', CITED): 1, ('changed source_ref', PLAIN): 1, ('changed video_key', PLAIN): 1}),
    (plant('recording_matches', 'm1', source_ref=cited('new-2')), 'recording_matches',
     {('changed source_ref', CITED): 1, ('changed source_ref', PLAIN): 1}),
    (plant('recording_matches', 'm3', source_ref='recording_decisions:d2'), 'recording_matches',
     {('changed source_ref', CITED): 2, ('changed source_ref', PLAIN): 1}),
    # Added and removed rows are never part of the proof.
    (lambda tables: tables['videos'].append(dict(tables['videos'][0], video_key='a3')), 'videos',
     {('changed record_sha', CHURN): 4, ('changed details_checked_at', CHURN): 4, ('added keys', 'no evidence given'): 1}),
    (lambda tables: tables['recording_matches'].pop(0), 'recording_matches',
     {('changed source_ref', CITED): 1, ('removed keys', 'no evidence given'): -1}),
])
def test_a_planted_change_beside_a_cache_refresh_is_not_proven(tmp_path, change, table, expected):
    result = refresh(tmp_path, change)
    assert counts(result, table) == expected
    assert not result['ok'] and {g['file'] for g in result['failing']} >= {f'{table}.parquet'}


def test_an_earlier_check_time_is_not_a_refresh(tmp_path):
    result = refresh(tmp_path, checked=1, change=lambda tables: [v.update(details_checked_at=v['details_checked_at'].replace(month=10))
                                                                  for v in tables['videos'] if v['video_key'] != 'api'])
    assert counts(result, 'videos') == {('changed record_sha', PLAIN): 4, ('changed details_checked_at', PLAIN): 4}


def test_two_cache_files_folded_into_one_hash_prove_nothing(tmp_path):
    result = refresh(tmp_path, files=('new-1', 'new-1'))
    assert counts(result, 'channels') == {('changed record_sha', PLAIN): 3}
    assert counts(result, 'videos') == {('changed record_sha', PLAIN): 4, ('changed details_checked_at', PLAIN): 4}
    # A match's citation is judged against its own video's hash only; the video rows carry the finding.
    assert counts(result, 'recording_matches') == {('changed source_ref', CITED): 2}


# The independent review's cases (investigations/gate-rules-20261110/review/REVIEW.md).
@pytest.mark.parametrize('files', [
    ('old-2', 'old-1'),  # P4e: two files swapped
    ('old-2', 'new-2'),  # P4d: one file's rows now cite another channel's old file
])
def test_a_citation_the_live_release_already_holds_is_not_a_refresh(tmp_path, files):
    result = refresh(tmp_path, files=files)
    moved = 1 if files[1] == 'new-2' else 0  # channel @c and its video still went to a hash nobody cited
    assert counts(result, 'channels') == {k: v for k, v in {('changed record_sha', CHURN): moved, ('changed record_sha', PLAIN): 3 - moved}.items() if v}
    assert counts(result, 'videos') == {k: v for k, v in {
        ('changed record_sha', CHURN): moved, ('changed details_checked_at', CHURN): moved,
        ('changed record_sha', PLAIN): 4 - moved, ('changed details_checked_at', PLAIN): 4 - moved}.items() if v}


def test_a_check_time_in_the_future_is_not_a_refresh(tmp_path):
    """P6/E4: every check date set to 2099. A check is a past event; the gate's clock bounds it."""
    result = refresh(tmp_path, change=lambda tables: [v.update(details_checked_at=v['details_checked_at'].replace(year=2099))
                                                      for v in tables['videos'] if v['video_key'] != 'api'])
    assert counts(result, 'videos') == {('changed record_sha', PLAIN): 4, ('changed details_checked_at', PLAIN): 4}
    assert counts(result, 'channels') == {('changed record_sha', CHURN): 3}


def test_the_check_time_bound_is_the_moment_of_comparison(tmp_path):
    from datetime import datetime, timezone
    prev = video_release(tmp_path / 'prev', ('old-1', 'old-2'), 1)
    live = video_release(tmp_path / 'live', ('new-1', 'new-2'), 8)
    proven = lambda now: {g['group'] for g in release_diff.compare(prev, live, now=now)['files']['videos.parquet']['groups'] if g['status'] == 'verified'}
    assert proven(datetime(2026, 11, 8, tzinfo=timezone.utc)) == {'changed record_sha', 'changed details_checked_at'}
    assert proven(datetime(2026, 11, 7, 23, 59, tzinfo=timezone.utc)) == set()


def test_a_column_with_no_partner_stops_the_cache_refresh_proof(tmp_path):
    wider = dict(VIDEO_SCHEMAS, videos=[*VIDEO_SCHEMAS['videos'], ('transcript', S)])
    result = refresh(tmp_path, schemas=wider)
    assert counts(result, 'videos') == {('changed record_sha', PLAIN): 4, ('changed details_checked_at', PLAIN): 4}
    assert 'videos.transcript: new in the candidate; no base values to compare' in result['cannot_see']


# ct-4qld: a live link key must reach a row that serves the live file or the file the key names.
LINK_SCHEMAS = dict(SCHEMAS, detail=[('saved_body', B), ('alternates', pa.list_(pa.struct([('body', B)])))],
                    recoveries=[('list_row', I), ('body', B), ('recovered_url', S), ('kind', S)])


def body(letter):
    """The file whose body key is `key(letter)`: a link key is the first 8 bytes of its body's SHA-256."""
    return key(letter) + b'\0' * 24


def served(directory, rows, recoveries=()):
    """Each row is (link-key letters, saved body letter, alternate letters); a recovery is (row, body letter)."""
    return release(directory, documents=[r[0] for r in rows], schemas=LINK_SCHEMAS,
                   detail=[{'saved_body': body(r[1]), 'alternates': [{'body': body(a)} for a in (r[2] if len(r) > 2 else '')]} for r in rows],
                   recoveries=[{'list_row': row, 'body': body(letter), 'recovered_url': f'https://example.test/{letter}', 'kind': 'recovered_document'}
                               for row, letter in recoveries])


def changed(tmp_path, prev, live):
    _, result = run(tmp_path, prev, live)
    assert result['link_rule']['changed'] == len(result['link_rule']['changed_keys']) == len(result['link_rule']['changed_answers'])
    assert result['link_rule']['ok'] == (not result['link_rule']['changed']) and result['link_rule']['missing'] == 0
    return [bytes.fromhex(k).decode()[0] for k in result['link_rule']['changed_keys']]


def test_fused_documents_whose_keys_answer_the_surviving_file_are_named(tmp_path):
    """a70ebc3d1466: seven PDFs joined through one listing page H; six can no longer be opened."""
    prev = served(tmp_path / 'prev', [(letter, letter) for letter in 'ABCDEFG'])
    live = served(tmp_path / 'live', [('ABCDEFGH', 'G', 'H')])
    assert changed(tmp_path, prev, live) == list('ABCDEF')
    answer = json.loads((tmp_path / 'out.json').read_text())['link_rule']['changed_answers'][0]
    assert answer == {'key': key('A').hex(), 'live_row': 0, 'live_file': 'A', 'live_body': body('A').hex(),
                      'candidate_row': 0, 'candidate_file': 'ABCDEFGH', 'candidate_body': body('G').hex()}


@pytest.mark.parametrize('prev,live', [
    # The same saved file, on a row that moved.
    (dict(rows=[('A', 'A'), ('B', 'B')]), dict(rows=[('B', 'B'), ('A', 'A')])),
    # Another format became the saved file; the live file is its recorded alternate.
    (dict(rows=[('A', 'A')]), dict(rows=[('AP', 'P', 'A')])),
    # cae8e4ea34ec603a: a link key U names no body. Its live file stays on the row as a recovery
    # while a newly fetched body becomes the saved one.
    (dict(rows=[('U', 'X')], recoveries=[(0, 'X'), (0, 'Y')]), dict(rows=[('UY', 'Y')], recoveries=[(0, 'X'), (0, 'Y')])),
    # A wrong join split: B now reaches the file it names instead of A's.
    (dict(rows=[('AB', 'A', 'B')]), dict(rows=[('A', 'A'), ('B', 'B')])),
    # After a split the key's own file is an alternate of its new row.
    (dict(rows=[('ABC', 'A', 'BC')]), dict(rows=[('A', 'A'), ('BC', 'B', 'C')])),
])
def test_a_live_key_that_still_reaches_its_file_passes(tmp_path, prev, live):
    assert changed(tmp_path, served(tmp_path / 'prev', **prev), served(tmp_path / 'live', **live)) == []


@pytest.mark.parametrize('prev,live,named', [
    # A link key re-pointed at a document that does not hold the live file.
    (dict(rows=[('U', 'X'), ('Y', 'Y')]), dict(rows=[('X', 'X'), ('UY', 'Y')]), ['U']),
    # The live file is recorded, but as another row's recovery.
    (dict(rows=[('U', 'X'), ('Y', 'Y')]), dict(rows=[('UY', 'Y'), ('Z', 'Z')], recoveries=[(1, 'X')]), ['U']),
    # The key's own file is served, but by another row than the one the key reaches.
    (dict(rows=[('A', 'A'), ('B', 'B')]), dict(rows=[('AB', 'B'), ('C', 'C', 'A')]), ['A']),
    # The saved file was replaced by different bytes and the live file is nowhere on the row.
    (dict(rows=[('U', 'X')]), dict(rows=[('U', 'Y')]), ['U']),
])
def test_a_live_key_that_reaches_another_file_is_named(tmp_path, prev, live, named):
    assert changed(tmp_path, served(tmp_path / 'prev', **prev), served(tmp_path / 'live', **live)) == named


def test_a_release_without_saved_bodies_says_the_answer_check_did_not_run(tmp_path):
    bare = dict(SCHEMAS, detail=[('link_key', B)])
    prev = release(tmp_path / 'prev', documents=['A', 'B'], schemas=bare, detail=[{'link_key': key('A')}, {'link_key': key('B')}])
    live = release(tmp_path / 'live', documents=['AB'], schemas=bare, detail=[{'link_key': key('A')}])
    _, result = run(tmp_path, prev, live)
    assert result['link_rule']['changed'] == 0
    assert result['cannot_see'] == ['link rule: a release has no detail.saved_body, so no live key was checked for answering another file']


# ct-wscb: a live lookup key or address must reach a row serving the live file or one of the
# live document's own files. Each test row is (link-key letters, saved letter, alternates,
# address letters): address "a" is URL `u/a`, lookup key `key('a')`; "a/m" is member m of `u/a`.
def addressed(directory, rows, recoveries=()):
    sources, urls = [], []
    for index, row in enumerate(rows):
        for address in (row[3] if len(row) > 3 else '').split():
            url, _, member = address.partition('/')
            sources.append({'list_row': index, 'url': f'u/{url}', 'member_path': member or None})
            urls.append({'lookup_key': key(url), 'list_row': index})
    return release(directory, documents=[r[0] for r in rows], schemas=LINK_SCHEMAS, sources=sources, urls=urls,
                   detail=[{'saved_body': body(r[1]), 'alternates': [{'body': body(a)} for a in r[2]]} for r in rows],
                   recoveries=[{'list_row': row, 'body': body(letter), 'recovered_url': f'https://example.test/{letter}', 'kind': 'recovered_document'}
                               for row, letter in recoveries])


def addresses_changed(tmp_path, prev, live):
    _, result = run(tmp_path, addressed(tmp_path / 'prev', **prev), addressed(tmp_path / 'live', **live))
    rule = result['link_rule']
    assert rule['ok'] == (not rule['missing'] and not rule['changed'] and not rule['lookup_changed'] and not rule['address_changed'])
    assert rule['lookup_changed'] == len(rule['lookup_changed_keys']) and rule['address_changed'] == len(rule['address_changed_keys'])
    return [bytes.fromhex(k).decode()[0] for k in rule['lookup_changed_keys']], rule['address_changed_keys']


def test_fused_documents_whose_addresses_answer_the_surviving_file_are_named(tmp_path):
    """a70ebc3d1466: each of six fused PDFs keeps its addresses and lookup keys, on a row that serves another file."""
    prev = dict(rows=[(letter, letter, '', letter.lower()) for letter in 'ABCDEFG'])
    live = dict(rows=[('ABCDEFGH', 'G', 'H', 'a b c d e f g')])
    assert addresses_changed(tmp_path, prev, live) == (list('abcdef'), [f'u/{a}' for a in 'abcdef'])
    answer = json.loads((tmp_path / 'out.json').read_text())['link_rule']['address_changed_answers'][0]
    assert answer == {'key': 'u/a', 'live_row': 0, 'live_file': 'A', 'live_body': body('A').hex(),
                      'candidate_rows': [0], 'candidate_files': ['ABCDEFGH']}
    # The comparison's own shared-key groups see nothing: the merge leaves every key on "the same" document.
    result = json.loads((tmp_path / 'out.json').read_text())
    assert not any(g['group'] == 'documents changed for a shared key' for f in result['files'].values() for g in f['groups'])


@pytest.mark.parametrize('prev,live', [
    # The same file, on a row that moved.
    (dict(rows=[('A', 'A', '', 'a'), ('B', 'B', '', 'b')]), dict(rows=[('B', 'B', '', 'b'), ('A', 'A', '', 'a')])),
    # The live file became an alternate of its row, or stays as its recovery.
    (dict(rows=[('A', 'A', '', 'a')]), dict(rows=[('AP', 'P', 'A', 'a')])),
    (dict(rows=[('U', 'X', '', 'a')], recoveries=[(0, 'X')]), dict(rows=[('UY', 'Y', '', 'a')], recoveries=[(0, 'X')])),
    # An address holds two editions: a new one beside the live one.
    (dict(rows=[('A', 'A', '', 'a')]), dict(rows=[('A', 'A', '', 'a'), ('N', 'N', '', 'a')])),
    # A wrong join split: the address of B, which the live row showed as A, reaches B's own row.
    (dict(rows=[('AB', 'A', '', 'a b')]), dict(rows=[('A', 'A', '', 'a'), ('B', 'B', '', 'b')])),
    # An archive member keeps its file.
    (dict(rows=[('A', 'A', '', 'z/m.htm'), ('B', 'B', '', 'z/n.htm')]), dict(rows=[('B', 'B', '', 'z/n.htm'), ('A', 'A', '', 'z/m.htm')])),
    # A key or address the candidate no longer publishes is the comparison's group, not this rule's.
    (dict(rows=[('A', 'A', '', 'a b')]), dict(rows=[('A', 'A', '', 'a')])),
    # A document the candidate removed: its address now shows only a newer edition. The removed
    # row and its retired key are reported elsewhere; the address is not a second finding.
    (dict(rows=[('A', 'A', '', 'a')]), dict(rows=[('N', 'N', '', 'a')])),
])
def test_a_live_address_that_still_reaches_its_file_passes(tmp_path, prev, live):
    assert addresses_changed(tmp_path, prev, live) == ([], [])


@pytest.mark.parametrize('prev,live,lookups,addresses', [
    # An address re-pointed at a document that holds none of the live document's files.
    (dict(rows=[('A', 'A', '', 'a'), ('B', 'B', '', 'b')]), dict(rows=[('A', 'A', ''), ('B', 'B', '', 'a b')]), ['a'], ['u/a']),
    # The live file is recorded, but on a row the address does not reach.
    (dict(rows=[('A', 'A', '', 'a'), ('B', 'B', '', 'b')]), dict(rows=[('A', 'A', ''), ('B', 'B', '', 'a b'), ('C', 'C', 'A')]), ['a'], ['u/a']),
    # After a split the address lands on a file that was never the live document's.
    (dict(rows=[('AB', 'A', '', 'a b'), ('C', 'C', '', 'c')]), dict(rows=[('A', 'A', '', 'a'), ('B', 'B', ''), ('C', 'C', '', 'b c')]), ['b'], ['u/b']),
    # Two archive members swapped between documents: each is named with its member.
    (dict(rows=[('A', 'A', '', 'z/m.htm'), ('B', 'B', '', 'z/n.htm')]), dict(rows=[('A', 'A', '', 'z/n.htm'), ('B', 'B', '', 'z/m.htm')]),
     [], ['u/z member m.htm', 'u/z member n.htm']),
])
def test_a_live_address_that_reaches_another_file_is_named(tmp_path, prev, live, lookups, addresses):
    assert addresses_changed(tmp_path, prev, live) == (lookups, addresses)
