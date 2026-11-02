"""Compatible readings versions need a bound proof, select without duplicates, and raw duplicates are rejected first."""
import hashlib
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import compatible_proof, compatible_versions as cv
from congress_api.lake.readings import worker_limits
from congress_api.retention.provenance import run_job
from docspec_client.client import NativeDatasets
from native_test_helpers import lake_readings_table

PINS = dict(sniff='s2', html='h2', xml='x2', json='j2', readings='b2')
SHA = 'a' * 64
# A fixture recompute set, shaped like the reader's: a key set over {readings}.
NOT_HTML = "SELECT body_sha FROM {readings} WHERE format<>'html'"


@pytest.fixture
def reader_set(monkeypatch):
    """Stand in for the html reader's own recompute set (r1b-g defines the real one)."""
    import congress_api.parsers.archive_readings as reader
    monkeypatch.setattr(reader, 'HTML_REREAD_SQL', NOT_HTML, raising=False)


def proof(version, current, recompute='none', **more):
    return dict(dict(scope='sample', version=version, current=current, recompute_sha256=cv.recompute_sha256(recompute),
        old_input_sha256=SHA, new_input_sha256=SHA, rows=5, columns=3, differences=0, only_old=0, only_new=0,
        strata=dict(completed=dict(population=9, local=5, sampled=5)), lock_only=dict(recomputed=version)), **more)


def entry(parser='html', version='h1', basis='lock_only', recompute_sql='none', **more):
    value = dict(parser=parser, version=version, current=PINS.get(parser, 'x'), basis=basis, recompute_sql=recompute_sql,
                 reason='lock pin only', proof=proof(version, PINS.get(parser, 'x'), recompute_sql))
    return dict(value, **more)


def predicate(version='h1', recompute=NOT_HTML, **more):
    full = dict(scope='full', strata=dict(completed=dict(population=5, local=5, sampled=5)), lock_only=None)
    return entry(version=version, basis='predicate', recompute_sql=recompute,
                 proof=proof(version, 'h2', recompute, **{**full, **more}))


def static_bundle(**more):
    leaves = {p: p[0] + '1' for p in cv.LEAF_PARSERS}
    value = entry(parser='readings', version='b1', basis='bundle')
    value['proof'] = dict(scope='static', version='b1', current='b2', recompute_sha256=cv.recompute_sha256('none'), old_input_sha256=SHA,
        new_input_sha256=SHA, lock_only=dict(recomputed='b1'), leaf_versions=leaves, policy=worker_limits())
    value['proof'].update(more)
    return value


def leaf_entries():
    return [entry(parser=p, version=p[0] + '1', basis='lock_only' if p == 'sniff' else 'whole') for p in cv.LEAF_PARSERS]


@pytest.fixture
def engine():
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as value:
        yield value


def test_committed_registry_is_valid():
    assert cv.load_registry() == []


def test_valid_entries_are_accepted(reader_set):
    entries = [*[e for e in leaf_entries() if e['parser'] != 'html'], predicate(version='h0')]
    assert cv.validate_entries(entries, current=PINS) == entries


def test_a_static_bundle_over_whole_leaves_is_accepted():
    entries = [*leaf_entries(), static_bundle()]
    assert cv.validate_entries(entries, current=PINS) == entries


def bad_proof(**more):
    value = entry()
    value['proof'] = dict(value['proof'], **more)
    return value


# Each case is a check that, deleted, lets that entry through.
@pytest.mark.parametrize('bad,message', [
    (entry(proof=None), 'differential proof'),
    (bad_proof(rows=0), 'compared nothing'),
    (bad_proof(differences=1), 'found differences'),
    (bad_proof(only_new=1), 'found differences'),
    (bad_proof(only_old=1), 'found differences'),
    (entry(current='older'), 'superseded pin'),
    (entry(version='h2'), 'compatible with itself'),
    (entry(parser='filename_readings'), 'D3/D4 have no compatible versions'),
    (entry(parser='meeting_records.house_xml'), 'D3/D4 have no compatible versions'),
    (entry(basis='nope'), 'Unknown compatible version basis'),
    (entry(basis='bundle'), 'bundle basis'),
    (entry(parser='readings', basis='lock_only'), 'bundle basis'),
    (entry(recompute_sql=NOT_HTML), 'Only a predicate entry'),
    (dict(predicate(), parser='xml', current='x2'), 'names no recompute set'),
    (bad_proof(scope='full', lock_only=None), 'old tree to recompute'),
    (bad_proof(lock_only=dict(recomputed='h9')), 'old tree to recompute'),
    (bad_proof(scope='static'), 'basis scope'),
    (dict(entry(parser='xml', version='x1'), proof=dict(proof('x1', 'x2'), strata=None)), 'state its strata'),
    (dict(entry(parser='xml', version='x1'), proof=dict(proof('x1', 'x2'), rows=4)), 'add up to its rows'),
    (dict(entry(parser='xml', version='x1'), proof=dict(proof('x1', 'x2'), rows=5,
        strata=dict(completed=dict(population=9000, local=3000, sampled=5)))), 'too small in its completed'),
    (dict(entry(parser='xml', version='x1'), proof=dict(proof('x1', 'x2'), rows=6,
        strata=dict(completed=dict(population=9, local=5, sampled=5), error=dict(population=3, local=2, sampled=1)))), 'too small in its error'),
    (bad_proof(current='h3'), 'bound to other pins'),
    (bad_proof(version='h0'), 'bound to other pins'),
    (bad_proof(old_input_sha256=None), 'both inputs'),
])
def test_unproved_unbound_or_stale_entries_are_refused(bad, message):
    with pytest.raises(ValueError, match=message):
        cv.validate_entries([bad], current=PINS)


@pytest.mark.parametrize('bad,message', [
    (predicate(recompute="SELECT body_sha FROM {readings} WHERE false"), "must equal its reader's"),
    (predicate(scope='static'), 'basis scope'),
    (predicate(scope='sample'), 'basis scope'),
    (predicate(strata=dict(completed=dict(population=6, local=5, sampled=5))), 'every row the entry keeps'),
    (entry(), 'names a recompute set; a whole-version entry'),
    (entry(basis='whole'), 'names a recompute set; a whole-version entry'),
    (predicate(recompute_sha256=cv.recompute_sha256('other')), 'recompute set changed after'),
])
def test_a_parser_with_a_recompute_set_takes_only_full_predicate_entries(reader_set, bad, message):
    with pytest.raises(ValueError, match=message):
        cv.validate_entries([bad], current=PINS)


def test_duplicates_and_chains_are_refused():
    # A chain v1->v2->v3 needs an entry whose current is no longer live; that is refused.
    with pytest.raises(ValueError, match='Duplicate'):
        cv.validate_entries([entry(), entry()], current=PINS)
    # After a later move h2 becomes old too; an entry may not name another entry's current.
    with pytest.raises(ValueError, match='superseded pin'):
        cv.validate_entries([entry(version='h1'), entry(version='h2', current='h3', proof=proof('h2', 'h3'))], current=dict(PINS, html='h3'))
    # Several old versions to one current are separate, valid entries.
    both = [entry(version='h0', proof=proof('h0', 'h2')), entry(version='h1')]
    assert cv.validate_entries(both, current=PINS) == both


@pytest.mark.parametrize('more,message', [
    (dict(policy=dict(worker_limits(), memory_bytes=1)), 'worker policy'),
    (dict(leaf_versions=dict(sniff='s1')), 'old leaf pins'),
    (dict(leaf_versions={p: p[0] + '9' for p in cv.LEAF_PARSERS}), 'lock-only or whole entry for every old leaf'),
])
def test_a_static_bundle_needs_lock_only_leaves_and_the_same_policy(more, message):
    with pytest.raises(ValueError, match=message):
        cv.validate_entries([*leaf_entries(), static_bundle(**more)], current=PINS)


def test_a_static_bundle_is_refused_once_a_leaf_changed_semantics(reader_set):
    leaves = [e for e in leaf_entries() if e['parser'] != 'html'] + [predicate()]
    with pytest.raises(ValueError, match='lock-only or whole entry'):
        cv.validate_entries([*leaves, static_bundle()], current=PINS)


def test_a_registry_file_of_another_version_is_refused(tmp_path):
    path = tmp_path / 'registry.json'
    path.write_text(json.dumps(dict(version=1, entries=[])))
    with pytest.raises(ValueError, match='Invalid compatible version registry'):
        cv.load_registry(current=PINS, path=path)


def test_accepted_versions_exclude_predicate_entries(reader_set):
    rows = cv.accepted_version_rows([entry(), predicate(version='h0')], pins=PINS)
    assert dict(parser='html', version='h1') in rows and dict(parser='html', version='h0') not in rows
    assert {(r['parser'], r['version']) for r in rows} >= set(PINS.items())


def test_the_selection_is_never_materialized(reader_set):
    *sets, step = cv.selected_readings_steps([*leaf_entries(), predicate(version='h0')])
    assert step['name'] == 'selected_readings' and 'materialize' not in step
    assert [s['name'] for s in sets] == ['recompute_0'] and sets[0]['materialize']
    assert cv.selected_readings_steps([]) == [dict(name='selected_readings',
        sql='SELECT r.* FROM parser_versions v JOIN readings r ON r.parser=v.parser AND r.parser_version=v.version')]
    assert "'html'" not in cv.selected_readings_steps([entry()], parsers=('sniff',))[-1]['sql']


def write(tmp_path, name, rows):
    path = tmp_path / f'{name}.parquet'
    pq.write_table(lake_readings_table(rows), path)
    return path


def selected(tmp_path, engine, rows, entries):
    readings = write(tmp_path, 'readings', rows)
    pins = dict(cv.accepted_versions_input(tmp_path, [], pins=dict(html='h2')), name='parser_versions')
    result = run_job(tmp_path / 'select', engine, inputs=[dict(name='readings', kind='parquet', path=str(readings)), pins],
        steps=cv.selected_readings_steps(entries), outputs=[],
        queries=[dict(name='rows', sql='SELECT body_sha,parser_version FROM selected_readings ORDER BY body_sha')])
    return [(row['body_sha'], row['parser_version']) for row in result['rows']]


def reading(body, version, **more):
    return dict(dict(body_sha=body.encode() * 32, parser='html', parser_version=version, status='completed'), **more)


def test_current_row_wins_and_the_recompute_set_is_left_out(tmp_path, engine, reader_set):
    rows = [reading('a', 'h1', format='html'), reading('a', 'h2', format='html'),
            reading('b', 'h1', format='html'), reading('c', 'h1', format='xml'), reading('d', 'h0', format='html')]
    assert selected(tmp_path, engine, rows, [predicate()]) == [((b'a' * 32).hex(), 'h2'), ((b'b' * 32).hex(), 'h1')]


def test_preflight_rejects_an_injected_duplicate_primary_key(tmp_path, engine):
    good = tmp_path / 'good.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha='a', parser='html', parser_version='v'), dict(body_sha='a', parser='xml', parser_version='v')]), good)
    assert compatible_proof.preflight(engine=engine, work=tmp_path / 'ok', inputs=dict(readings=good)) == dict(readings=0)
    bad = tmp_path / 'bad.parquet'
    pq.write_table(pa.Table.from_pylist([dict(body_sha='a', parser='html', parser_version='v')] * 2), bad)
    with pytest.raises(ValueError, match='duplicated before selection'):
        compatible_proof.preflight(engine=engine, work=tmp_path / 'dup', inputs=dict(readings=bad))


def prove(tmp_path, engine, old, new, work, **more):
    return compatible_proof.prove_unchanged(engine=engine, work=tmp_path / work, old=write(tmp_path, work + '-old', old),
        new=write(tmp_path, work + '-new', new), parser='html', version='h1', current='h2', **more)


BASE = [reading(c, 'h1', format=f, title='t' + c) for c, f in zip('abcde', ['html', 'html', 'xml', 'html', 'xml'])]
SAME = [dict(row, parser_version='h2') for row in BASE]


def test_the_differential_reads_every_column_both_ways_in_the_real_schema(tmp_path, engine):
    result, differing = prove(tmp_path, engine, BASE, SAME, 'same')
    assert result['rows'] == 5 and result['columns'] == 17 and result['differences'] == result['only_old'] == result['only_new'] == 0
    changed = [dict(SAME[0], title='other'), *SAME[1:]]
    assert prove(tmp_path, engine, BASE, changed, 'changed')[1] == {'title': 1}
    assert prove(tmp_path, engine, BASE, SAME[:4], 'lost')[0]['only_old'] == 1
    # A new key with no old row is an addition, not a row the entry keeps.
    assert prove(tmp_path, engine, BASE, [*SAME, reading('f', 'h2', format='html')], 'extra')[0]['only_new'] == 0


def test_rows_in_the_recompute_set_are_not_counted_as_new(tmp_path, engine):
    # Defect guarded: an unfiltered new side counts every row outside the predicate (the 18,251).
    result, _ = prove(tmp_path, engine, BASE, SAME, 'pred', recompute_sql=NOT_HTML)
    assert result == dict(result, rows=3, only_new=0, only_old=0, differences=0)


def test_a_re_read_that_fills_a_field_passes_and_a_change_outside_the_set_fails(tmp_path, engine):
    # Recompute set: rows with no fingerprint (the html re-read rule's shape).
    unset = "SELECT body_sha FROM {readings} WHERE fingerprint IS NULL"
    old = [reading('a', 'h1', format='html', fingerprint=b'f' * 32), reading('b', 'h1', format='html')]
    # b's re-read fills its fingerprint, leaving the set: an intended change, not compared.
    filled = [reading('a', 'h2', format='html', fingerprint=b'f' * 32), reading('b', 'h2', format='html', fingerprint=b'g' * 32)]
    result, differing = prove(tmp_path, engine, old, filled, 'filled', recompute_sql=unset)
    assert result == dict(result, rows=1, differences=0, only_old=0, only_new=0) and differing == {}
    # a is outside the set and its value changes: a difference (defect: K from the new side).
    changed = [dict(filled[0], title='other'), filled[1]]
    assert prove(tmp_path, engine, old, changed, 'changed-out', recompute_sql=unset)[1] == {'title': 1}
    # a outside the set vanishes: only_old.
    assert prove(tmp_path, engine, old, filled[1:], 'vanished', recompute_sql=unset)[0]['only_old'] == 1
    # a joins the set on the new side (fingerprint lost): still compared, so counted.
    lost = [dict(filled[0], fingerprint=None), filled[1]]
    assert prove(tmp_path, engine, old, lost, 'lost', recompute_sql=unset)[1] == {'fingerprint': 1}


def test_a_predicate_sample_compares_only_sampled_keys_outside_the_recompute_set(tmp_path, engine):
    keys = tmp_path / 'pkeys.parquet'
    pq.write_table(pa.table(dict(body_sha=pa.array([b'a' * 32, b'c' * 32], pa.binary(32)))), keys)
    result, _ = prove(tmp_path, engine, BASE, [SAME[0]], 'psample', sample_keys=keys, recompute_sql=NOT_HTML)
    assert result['rows'] == 1 and result['only_old'] == 0 and result['only_new'] == 0


def test_a_sample_compares_only_its_keys(tmp_path, engine):
    # Defect guarded: without the K restriction the three unsampled old rows count as only_old.
    keys = tmp_path / 'keys.parquet'
    pq.write_table(pa.table(dict(body_sha=pa.array([b'a' * 32, b'c' * 32], pa.binary(32)))), keys)
    result, _ = prove(tmp_path, engine, BASE, [SAME[0], SAME[2]], 'sample', sample_keys=keys)
    assert result['rows'] == 2 and result['only_old'] == 0 and result['only_new'] == 0


def test_two_old_versions_select_one_body_once(tmp_path, engine):
    # Defect guarded: each old version's branch selecting the same body, a duplicate key.
    rows = [reading('a', 'h0', format='html'), reading('a', 'h1', format='html'), reading('b', 'h1', format='html')]
    both = [entry(version='h0', basis='whole', proof=proof('h0', 'h2')), entry(version='h1', basis='whole')]
    assert selected(tmp_path, engine, rows, both) == [((b'a' * 32).hex(), 'h0'), ((b'b' * 32).hex(), 'h1')]
