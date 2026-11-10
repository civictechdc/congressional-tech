"""Gates 1 and 2 at publish: every difference needs its recorded cause; no link key may vanish."""
from datetime import datetime, timedelta, timezone
from hashlib import md5, sha256
from io import BytesIO
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.archive_format import release_identity
from viewer_publication.release_gate import (RETIRED, fetch_base, fetch_release, load_causes, render_notes,
                                             require_release_gates)

K = lambda letter: (letter * 8).encode()
SCOPE = {'version': 1, 'entries': []}


def release_dir(root, documents, retired=None, *, scope=SCOPE, saved=..., **extra_tables):
    """A real, internally consistent release: documents are rows of link-key letters.

    `saved` names each row's saved file by the letter of its body key (a link key is the first
    8 bytes of its body's SHA-256); by default each row saves the file its first key names, as
    every real release does. `saved=None` writes no saved_body column at all."""
    root.mkdir(parents=True)
    detail = {'link_key': pa.array([K(keys[0]) for keys in documents], pa.binary(8))}
    if saved is not None:
        letters = [keys[0] for keys in documents] if saved is ... else saved
        detail['saved_body'] = pa.array([K(letter) + bytes(24) for letter in letters], pa.binary(32))
    tables = {
        'list': pa.table({'filename': [f'{keys}.pdf' for keys in documents]}),
        'detail': pa.table(detail),
        'links': pa.table({'link_key': pa.array([K(k) for keys in documents for k in keys], pa.binary(8)),
                           'list_row': pa.array([i for i, keys in enumerate(documents) for _ in keys], pa.int32())}),
        'urls': pa.table({'lookup_key': pa.array([], pa.binary(8)), 'list_row': pa.array([], pa.int32())}),
        'sources': pa.table({'list_row': pa.array([], pa.int32()), 'url': pa.array([], pa.string()),
                             'member_path': pa.array([], pa.string())}),
    }
    tables.update(extra_tables)
    if retired is not None:
        tables['retired_links'] = pa.Table.from_pylist(retired, schema=RETIRED)
    files = []
    for name, table in tables.items():
        path = root / f'{name}.parquet'
        pq.write_table(table, path)
        data = path.read_bytes()
        files.append(dict(name=path.name, sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(),
                          size=len(data), rows=table.num_rows))
    data = json.dumps(scope).encode()
    (root / 'capture_scope.json').write_bytes(data)
    files.append(dict(name='capture_scope.json', sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(), size=len(data), rows=0))
    manifest = dict(schema_version=1, files=files, facet_counts=[], release_id=release_identity(1, files))
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return manifest


# The groups the pair fixture must produce, written by hand from its two releases: the
# helper never copies the comparison's own output into a passing record.
PAIR_GROUPS = [('detail.parquet', 'removed rows', 'no surviving link key', -1),
               ('links.parquet', 'removed keys', 'no evidence given', -1),
               ('list.parquet', 'removed rows', 'no surviving link key', -1),
               ('retired_links.parquet', 'file added', 'file absent from the base release', 1)]


def record_for(base_id, candidate_id, tmp_path, groups=PAIR_GROUPS, **override):
    evidence = tmp_path / 'evidence.txt'
    evidence.write_text('fixture: document B was removed on purpose; its key carries a removal notice')
    pin = dict(path=str(evidence), sha256=sha256(evidence.read_bytes()).hexdigest(), size=evidence.stat().st_size)
    entries = [dict(id=f'{f}|{g}|{c}', count=n, disposition='explained', cause='fixture: document B was removed on purpose',
                    tickets=['ct-tk10'], evidence=[pin]) for f, g, c, n in groups]
    value = dict(version=1, base_release_id=base_id, candidate_release_id=candidate_id, groups=entries,
                 notes=dict(identifiers=[dict(kind='witness_key', statement='Witness IDs changed.', decision='ct-ktfe 2026-11-02')]))
    value.update(override)
    path = tmp_path / 'causes.json'
    path.write_text(json.dumps(value))
    data = path.read_bytes()
    return load_causes(dict(path=str(path), sha256=sha256(data).hexdigest(), size=len(data)))


def ids(pair):
    return [json.loads((d / 'manifest.json').read_text())['release_id'] for d in pair]


@pytest.fixture
def pair(tmp_path):
    base = tmp_path / 'base'
    release_dir(base, ['A', 'B'])
    candidate = tmp_path / 'candidate'
    release_dir(candidate, ['A'], retired=[dict(link_key=K('B'), successor_key=None, last_release_id='b' * 64, last_filename='B.pdf')])
    return base, candidate


def gate(pair, tmp_path, causes):
    return require_release_gates(*pair, causes, report_path=tmp_path / 'report.json')


def test_refuses_without_cause_record(pair, tmp_path):
    with pytest.raises(ValueError, match='no recorded cause for list.parquet'):
        gate(pair, tmp_path, None)
    report = json.loads((tmp_path / 'report.json').read_text())  # the report is written before refusing
    assert report['link_rule']['missing'] == 0 and report['reasons']


def test_passes_with_exact_record(pair, tmp_path):
    with pytest.raises(ValueError):
        gate(pair, tmp_path, None)
    report = json.loads((tmp_path / 'report.json').read_text())
    assert gate(pair, tmp_path, record_for(*ids(pair), tmp_path))['reasons'] == []


def test_refuses_count_off_by_one(pair, tmp_path):
    with pytest.raises(ValueError):
        gate(pair, tmp_path, None)
    report = json.loads((tmp_path / 'report.json').read_text())
    causes = record_for(*ids(pair), tmp_path)
    causes['groups'][0]['count'] += 1
    with pytest.raises(ValueError, match='recorded count'):
        gate(pair, tmp_path, causes)


def test_refuses_stale_entry(pair, tmp_path):
    with pytest.raises(ValueError):
        gate(pair, tmp_path, None)
    causes = record_for(*ids(pair), tmp_path)
    causes['groups'].append(dict(id='bills.parquet|removed bills|unexplained', count=-1, disposition='explained', cause='x', tickets=[]))
    with pytest.raises(ValueError, match='stale entry'):
        gate(pair, tmp_path, causes)


def test_refuses_record_for_other_candidate(pair, tmp_path):
    with pytest.raises(ValueError):
        gate(pair, tmp_path, None)
    causes = record_for(*ids(pair), tmp_path, candidate_release_id='f' * 64)
    with pytest.raises(ValueError, match='bound to candidate ffffffffffff'):
        gate(pair, tmp_path, causes)


def test_accepted_defect_requires_ticket(tmp_path):
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(dict(version=1, base_release_id='a' * 64, candidate_release_id='b' * 64,
        groups=[dict(id='f|g|c', count=1, disposition='accepted_defect', cause='known', tickets=[])])))
    data = path.read_bytes()
    with pytest.raises(ValueError, match='accepted defect needs a ticket'):
        load_causes(dict(path=str(path), sha256=sha256(data).hexdigest(), size=len(data)))


def test_explained_cause_requires_evidence(tmp_path):
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(dict(version=1, base_release_id='a' * 64, candidate_release_id='b' * 64,
        groups=[dict(id='f|g|c', count=1, disposition='explained', cause='asserted, never read', tickets=['ct-tk10'])])))
    data = path.read_bytes()
    with pytest.raises(ValueError, match='explained cause needs pinned evidence'):
        load_causes(dict(path=str(path), sha256=sha256(data).hexdigest(), size=len(data)))


def test_changed_evidence_pin_refuses(tmp_path):
    evidence = tmp_path / 'evidence.txt'
    evidence.write_text('raw read')
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(dict(version=1, base_release_id='a' * 64, candidate_release_id='b' * 64,
        groups=[dict(id='f|g|c', count=1, disposition='explained', cause='read raw', tickets=[],
                     evidence=[dict(path=str(evidence), sha256=sha256(b'raw read').hexdigest(), size=8)])])))
    data = path.read_bytes()
    pin = dict(path=str(path), sha256=sha256(data).hexdigest(), size=len(data))
    load_causes(pin)
    evidence.write_text('raw reax')
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        load_causes(pin)


def test_link_rule_refuses_missing_base_key_even_with_record(tmp_path):
    base = tmp_path / 'base'
    release_dir(base, ['A', 'B'])
    candidate = tmp_path / 'candidate'
    release_dir(candidate, ['A'])  # B vanishes: no redirect, no removal notice
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json')
    groups = [g for g in PAIR_GROUPS if g[0] != 'retired_links.parquet']
    causes = record_for(*ids((base, candidate)), tmp_path, groups=groups)
    with pytest.raises(ValueError, match='link rule: 1 base link keys vanish'):
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')


# The same keys on other rows: the links file's bytes change and no key or value does.
MOVED_LINKS = ('links.parquet', 'changed bytes, no key or value difference found', 'unexplained', 0)


FUSED_GROUPS = [*((name, 'merged rows', 'previous rows now share one document', -6) for name in ('detail.parquet', 'list.parquet')),
                MOVED_LINKS]


def fused(tmp_path):
    """ct-4qld, a70ebc3d1466: seven PDFs become one row, and six keys open the seventh's file."""
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, list('ABCDEFG'), saved='ABCDEFG')
    release_dir(candidate, ['ABCDEFG'], saved='G')
    return base, candidate


def test_link_rule_refuses_fused_documents_even_with_record(tmp_path):
    base, candidate = fused(tmp_path)
    named = ', '.join(K(letter).hex() for letter in 'ABCDEF')
    with pytest.raises(ValueError, match=f'link rule: 6 live link keys answer another file \\({named}\\)'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json')
    # A reviewed record for every group of the comparison does not override it.
    causes = record_for(*ids((base, candidate)), tmp_path, groups=FUSED_GROUPS)
    with pytest.raises(ValueError) as refusal:
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['reasons'] == [f'link rule: 6 live link keys answer another file ({named})']
    assert report['reasons'][0] in str(refusal.value)
    assert [(a['live_file'], a['candidate_file']) for a in report['link_rule']['changed_answers']] == [
        (f'{letter}.pdf', 'ABCDEFG.pdf') for letter in 'ABCDEF']


def test_link_rule_fails_closed_without_saved_bodies_even_with_record(tmp_path):
    """Review of ct-4qld, plant L1: the fused candidate with its saved_body column dropped, and a
    record naming every group. A check that could not run is not a pass."""
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, list('ABCDEFG'))
    release_dir(candidate, ['ABCDEFG'], saved=None)
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        *((name, 'merged rows', 'previous rows now share one document', -6) for name in ('detail.parquet', 'list.parquet')),
        ('detail.parquet', 'column saved_body removed', 'unexplained', 0), MOVED_LINKS])
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['reasons'] == ['link rule: not checked: a release has no detail.saved_body, so no live key could be checked for answering another file']
    assert report['link_rule']['changed'] == 0 and not report['link_rule']['ok']


def test_a_live_file_that_became_an_alternate_needs_a_recorded_cause(tmp_path):
    """Review of ct-4qld: a page H fused into a PDF's row keeps its file, as an alternate. The rule
    does not refuse it (a right rendition join looks the same); a person must see it."""
    alternates = pa.list_(pa.struct([('body', pa.binary(32))]))
    detail = lambda saved, extra: pa.table({
        'link_key': pa.array([K(s) for s in saved], pa.binary(8)), 'saved_body': pa.array([K(s) + bytes(24) for s in saved], pa.binary(32)),
        'alternates': pa.array([[dict(body=K(a) + bytes(24)) for a in letters] for letters in extra], alternates)})
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['H', 'P'], detail=detail('HP', ['', '']))
    release_dir(candidate, ['PH'], detail=detail('P', ['H']))
    with pytest.raises(ValueError, match=r'no recorded cause for links.parquet\|live file now an alternate\|the key reaches a row whose saved file is another body \(1\)'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json')
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['link_rule']['ok'] and report['link_rule']['demoted_keys'] == [K('H').hex()]
    assert report['link_rule']['demoted_answers'][0]['candidate_file'] == 'PH.pdf'
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        *((name, 'merged rows', 'previous rows now share one document', -1) for name in ('detail.parquet', 'list.parquet')),
        ('links.parquet', 'live file now an alternate', 'the key reaches a row whose saved file is another body', 1), MOVED_LINKS])
    assert require_release_gates(base, candidate, causes, report_path=tmp_path / 'r2.json')['reasons'] == []


def test_link_rule_passes_documents_that_keep_their_files(tmp_path):
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['AB', 'C'], saved='AC')
    release_dir(candidate, ['C', 'A', 'B'], saved='CAB')  # B, wrongly joined to A, reaches its own file
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        *((name, 'split rows', 'previous row had no member source', 1) for name in ('detail.parquet', 'list.parquet')), MOVED_LINKS])
    report = require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    assert report['link_rule'] == dict(missing=0, missing_keys=[], dangling=0, dangling_keys=[], changed=0, changed_keys=[],
                                       changed_answers=[], lookup_changed=0, lookup_changed_keys=[], lookup_changed_answers=[],
                                       address_changed=0, address_changed_keys=[], address_changed_answers=[],
                                       demoted=0, demoted_keys=[], demoted_answers=[], unchecked=[], ok=True)


def addresses(rows):
    """sources and urls tables: row i is reached by each letter of rows[i], as URL `https://example.test/<letter>` and lookup key K(letter)."""
    pairs = [(i, letter) for i, letters in enumerate(rows) for letter in letters]
    return dict(urls=pa.table({'lookup_key': pa.array([K(letter) for _, letter in pairs], pa.binary(8)),
                               'list_row': pa.array([i for i, _ in pairs], pa.int32())}),
                sources=pa.table({'list_row': pa.array([i for i, _ in pairs], pa.int32()),
                                  'url': pa.array([f'https://example.test/{letter}' for _, letter in pairs], pa.string()),
                                  'member_path': pa.array([None] * len(pairs), pa.string())}))


def test_link_rule_refuses_a_repointed_address_even_with_record(tmp_path):
    """ct-wscb: every link key still opens its own file; one address and its lookup key now reach another document."""
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['A', 'B'], saved='AB', **addresses(['a', 'b']))
    release_dir(candidate, ['A', 'B'], saved='AB', **addresses(['', 'ab']))
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        (name, 'documents changed for a shared key', 'the key now answers other documents', 1) for name in ('sources.parquet', 'urls.parquet')])
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['reasons'] == [f'link rule: 1 live lookup keys answer another file ({K("a").hex()})',
                                 'link rule: 1 live addresses answer another file (https://example.test/a)']
    assert report['link_rule']['changed'] == 0 and not report['link_rule']['ok']
    assert report['link_rule']['address_changed_answers'] == [dict(
        key='https://example.test/a', live_row=0, live_file='A.pdf', live_body=body('A'),
        candidate_rows=[1], candidate_files=['B.pdf'], candidate_bodies=[body('B')])]


# ct-4nax (owner decision 2026-11-10, "Accept named corrections"): a changed answer passes only
# where the reviewed record names its kind, key and both bodies. Records are written by hand
# from the fixtures' letters, never copied from the comparison's output.
body = lambda letter: (K(letter) + bytes(24)).hex()


def correction(kind, key, live, now):
    return dict(kind=kind, key=key, live_body=body(live), candidate_body=body(now),
                decision=f'fixture: {live} was the wrong file; a permanent record rejects it', tickets=['ct-4nax'])


FUSED_CORRECTIONS = [correction('link_key', K(letter).hex(), letter, 'G') for letter in 'ABCDEF']


def corrected_gate(tmp_path, pair, groups, corrections, **override):
    """The gate's report for `pair` under a record naming `groups` exactly and `corrections`."""
    causes = record_for(*ids(pair), tmp_path, groups=groups, corrections=corrections, **override)
    try:
        require_release_gates(*pair, causes, report_path=tmp_path / 'r.json')
    except ValueError:
        pass
    return json.loads((tmp_path / 'r.json').read_text()), causes


def unmatched(kind, key, live, now):
    return f'cause record: correction {kind} {key} from {body(live)} to {body(now)} matches no finding of the link rule'


def test_named_corrections_let_exactly_the_named_changes_through(tmp_path):
    report, causes = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, FUSED_CORRECTIONS)
    assert report['reasons'] == []
    assert not report['link_rule']['ok']  # the comparison still reports what changed
    assert report['named_corrections'] == dict(link_key=dict(waived=6, keys=[K(letter).hex() for letter in 'ABCDEF']),
                                               lookup_key=dict(waived=0, keys=[]), address=dict(waived=0, keys=[]))
    notes = render_notes(causes, tmp_path / 'base', tmp_path / 'candidate')
    assert f'| link_key | `{K("A").hex()}` | `{body("A")[:12]}` | `{body("G")[:12]}` |' in notes


@pytest.mark.parametrize('side', ['live_body', 'candidate_body'])
def test_a_correction_with_one_wrong_body_refuses(tmp_path, side):
    wrong = [dict(c, **{side: body('Z')}) if c['key'] == K('C').hex() else c for c in FUSED_CORRECTIONS]
    report, _ = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, wrong)
    named = dict(live_body=('Z', 'G'), candidate_body=('C', 'Z'))[side]
    assert report['reasons'] == [f'link rule: 1 live link keys answer another file ({K("C").hex()})',
                                 unmatched('link_key', K('C').hex(), *named)]
    assert report['named_corrections']['link_key']['waived'] == 5


def test_an_unnamed_changed_key_beside_named_ones_refuses_and_is_named(tmp_path):
    report, _ = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, FUSED_CORRECTIONS[:-1])
    assert report['reasons'] == [f'link rule: 1 live link keys answer another file ({K("F").hex()})']


def test_a_correction_that_matches_no_finding_refuses_the_record(tmp_path):
    padded = [*FUSED_CORRECTIONS, correction('link_key', K('Z').hex(), 'Z', 'G')]
    report, _ = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, padded)
    assert report['reasons'] == [unmatched('link_key', K('Z').hex(), 'Z', 'G')]


def test_a_record_for_another_candidate_waives_nothing(tmp_path):
    report, _ = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, FUSED_CORRECTIONS, candidate_release_id='f' * 64)
    assert report['reasons'][0] == f'link rule: 6 live link keys answer another file ({", ".join(K(x).hex() for x in "ABCDEF")})'
    assert report['reasons'][1].startswith('cause record: bound to candidate ffffffffffff')
    assert report['named_corrections']['link_key'] == dict(waived=0, keys=[])


def test_keys_beyond_the_reports_sample_cannot_be_named(tmp_path, monkeypatch):
    from viewer_publication import release_comparison
    monkeypatch.setattr(release_comparison.link_rule, '__defaults__', (5,))  # the report lists 5 of the 6 keys
    report, _ = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, FUSED_CORRECTIONS)
    assert report['link_rule']['changed'] == 6 and len(report['link_rule']['changed_answers']) == 5
    assert report['reasons'] == ['link rule: 1 live link keys answer another file',
                                 "link rule: 1 live link keys that answer another file are beyond the report's sample, "
                                 'so no correction can name them', unmatched('link_key', K('F').hex(), 'F', 'G')]


REPOINTED_GROUPS = [(name, 'documents changed for a shared key', 'the key now answers other documents', 1)
                    for name in ('sources.parquet', 'urls.parquet')]


def repointed(tmp_path, documents='AB', base=('a', 'b'), candidate=('', 'ab')):
    """Lookup key K(a) and address https://example.test/a of document A now reach document B (ct-wscb)."""
    pair = tmp_path / 'base', tmp_path / 'candidate'
    for directory, rows in zip(pair, (base, candidate)):
        release_dir(directory, list(documents), **addresses(list(rows)))
    return pair


def test_named_lookup_key_and_address_corrections_pass(tmp_path):
    report, _ = corrected_gate(tmp_path, repointed(tmp_path), REPOINTED_GROUPS, [
        correction('lookup_key', K('a').hex(), 'A', 'B'), correction('address', 'https://example.test/a', 'A', 'B')])
    assert report['reasons'] == []
    assert report['named_corrections']['lookup_key'] == dict(waived=1, keys=[K('a').hex()])
    assert report['named_corrections']['address'] == dict(waived=1, keys=['https://example.test/a'])


def test_a_correction_of_one_kind_does_not_waive_another_kind_with_the_same_key(tmp_path):
    report, _ = corrected_gate(tmp_path, repointed(tmp_path), REPOINTED_GROUPS, [
        correction('link_key', K('a').hex(), 'A', 'B'), correction('address', 'https://example.test/a', 'A', 'B')])
    assert report['reasons'] == [f'link rule: 1 live lookup keys answer another file ({K("a").hex()})',
                                 unmatched('link_key', K('a').hex(), 'A', 'B')]


def test_a_key_answering_for_two_live_files_needs_a_correction_for_each(tmp_path):
    """K(a) and its address were on live rows A and B; the candidate sends both to C. Naming only A's change leaves B's."""
    pair = repointed(tmp_path, 'ABC', base=('a', 'ab', 'c'), candidate=('', 'b', 'ac'))
    report, _ = corrected_gate(tmp_path, pair, REPOINTED_GROUPS, [
        correction('lookup_key', K('a').hex(), 'A', 'C'),
        correction('address', 'https://example.test/a', 'A', 'C'), correction('address', 'https://example.test/a', 'B', 'C')])
    assert [(a['live_body'], a['candidate_bodies']) for a in report['link_rule']['lookup_changed_answers']] == [
        (body('A'), [body('C')]), (body('B'), [body('C')])]
    assert [r for r in report['reasons'] if not r.startswith('comparison:')] == [
        f'link rule: 1 live lookup keys answer another file ({K("a").hex()})']
    assert report['named_corrections']['address'] == dict(waived=1, keys=['https://example.test/a'])


def test_the_sample_lists_a_key_whole_so_its_unnamed_live_file_is_seen(tmp_path, monkeypatch):
    """A sample of one key still lists both of K(a)'s live rows; cut by rows, B's change would hide behind A's."""
    from viewer_publication import release_comparison
    monkeypatch.setattr(release_comparison.link_rule, '__defaults__', (1,))
    pair = repointed(tmp_path, 'ABC', base=('a', 'a', 'c'), candidate=('', '', 'ac'))
    report, _ = corrected_gate(tmp_path, pair, REPOINTED_GROUPS, [correction('lookup_key', K('a').hex(), 'A', 'C')])
    assert [a['live_body'] for a in report['link_rule']['lookup_changed_answers']] == [body('A'), body('B')]
    assert f'link rule: 1 live lookup keys answer another file ({K("a").hex()})' in report['reasons']


def test_a_key_that_reaches_two_files_cannot_be_named_by_one(tmp_path):
    pair = repointed(tmp_path, 'ABC', base=('a', 'b', 'c'), candidate=('', 'ab', 'ac'))
    report, _ = corrected_gate(tmp_path, pair, REPOINTED_GROUPS, [correction('lookup_key', K('a').hex(), 'A', 'B')])
    assert report['link_rule']['lookup_changed_answers'][0]['candidate_bodies'] == [body('B'), body('C')]
    assert f'link rule: 1 live lookup keys answer another file ({K("a").hex()})' in report['reasons']
    assert unmatched('lookup_key', K('a').hex(), 'A', 'B') in report['reasons']


@pytest.mark.parametrize('case', ['missing', 'dangling', 'unchecked'])
def test_no_correction_touches_a_vanished_key_a_dangling_successor_or_an_unchecked_rule(tmp_path, case):
    successor = dict(dangling=K('Z')).get(case)
    retired = None if case == 'missing' else [dict(link_key=K('B'), successor_key=successor, last_release_id='b' * 64, last_filename='B.pdf')]
    pair = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(pair[0], ['A', 'B'])
    release_dir(pair[1], ['A'], retired=retired, saved=None if case == 'unchecked' else ...)
    # The record names B's key as a correction from B's file to A's: no finding can match it.
    report, _ = corrected_gate(tmp_path, pair, PAIR_GROUPS, [correction('link_key', K('B').hex(), 'B', 'A')])
    expected = dict(missing='link rule: 1 base link keys vanish', dangling='link rule: 1 successors are not published keys',
                    unchecked='link rule: not checked: a release has no detail.saved_body')[case]
    assert report['reasons'][0].startswith(expected)
    assert unmatched('link_key', K('B').hex(), 'B', 'A') in report['reasons']


MISSING = object()


@pytest.mark.parametrize('field, value, message', [
    ('note', 'extra', 'exactly the fields'),
    ('decision', MISSING, 'exactly the fields'),
    ('kind', 'body_key', 'kind must be one of'),
    ('key', 'ABCDEF0123456789', 'printed as the report prints it'),
    ('key', K('A').hex()[:15], 'printed as the report prints it'),
    ('live_body', body('A')[:63], 'live_body of link_key'),
    ('candidate_body', 'G' * 64, 'candidate_body of link_key'),
    ('decision', ' ', 'needs its decision'),
    ('tickets', [], 'A correction needs a ticket'),
    ('tickets', ['CT-4NAX'], 'tickets must be ticket ids'),
    ('tickets', ['ct-4nax', 'ct-zzzz'], 'no file in .*: ct-zzzz'),
])
def test_load_causes_refuses_a_malformed_correction(tmp_path, field, value, message):
    entry = {k: v for k, v in dict(FUSED_CORRECTIONS[0], **{field: value}).items() if v is not MISSING}
    with pytest.raises(ValueError, match=message):
        record_for('a' * 64, 'b' * 64, tmp_path, corrections=[entry])


def test_load_causes_refuses_two_corrections_of_one_finding(tmp_path):
    first = FUSED_CORRECTIONS[0]
    with pytest.raises(ValueError, match='Duplicate correction'):
        record_for('a' * 64, 'b' * 64, tmp_path, corrections=[first, dict(first, candidate_body=body('F'))])


def test_dangling_successor_refuses(tmp_path):
    base = tmp_path / 'base'
    release_dir(base, ['A', 'B'])
    candidate = tmp_path / 'candidate'
    release_dir(candidate, ['A'], retired=[dict(link_key=K('B'), successor_key=K('Z'), last_release_id='b' * 64, last_filename='B.pdf')])
    with pytest.raises(ValueError, match='1 successors are not published keys'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json')


def test_no_live_release_passes_vacuously_and_says_so(pair, tmp_path):
    report = require_release_gates(None, pair[1], None, report_path=tmp_path / 'r.json')
    assert report['gates'].startswith('vacuous')


def test_fetch_release_refuses_wrong_identity_or_digest(pair, tmp_path):
    base, _ = pair
    manifest = json.loads((base / 'manifest.json').read_text())
    def reader(directory):
        return lambda name: BytesIO((directory / name).read_bytes())
    fetched = fetch_release(reader(base), manifest['release_id'], tmp_path / 'copy')
    assert fetched['release_id'] == manifest['release_id']
    assert (tmp_path / 'copy/links.parquet').read_bytes() == (base / 'links.parquet').read_bytes()
    with pytest.raises(ValueError, match='does not identify release'):
        fetch_release(reader(base), 'f' * 64, tmp_path / 'other')
    (base / 'links.parquet').write_bytes(b'tampered')
    with pytest.raises(ValueError):
        fetch_release(reader(base), manifest['release_id'], tmp_path / 'third')


def test_notes_render_witness_statement_and_link_counts(pair, tmp_path):
    with pytest.raises(ValueError):
        gate(pair, tmp_path, None)
    causes = record_for(*ids(pair), tmp_path)
    text = render_notes(causes, *pair)
    assert '- Witness IDs changed. (ct-ktfe 2026-11-02)' in text
    assert '0 link keys from earlier releases now redirect to their current document. 1 show a removal notice. 0 vanish.' in text
    assert '| `list.parquet` |' in text


def test_a_named_history_key_that_vanishes_refuses(tmp_path):
    """red-h probe 4: a key only an earlier release published must not vanish either."""
    history = tmp_path / 'history'
    release_dir(history, ['A', 'H'])
    base = tmp_path / 'base'
    release_dir(base, ['A'])
    candidate = tmp_path / 'candidate'
    release_dir(candidate, ['A'], retired=[])
    with pytest.raises(ValueError, match='1 base link keys vanish'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', history=[history])
    assert json.loads((tmp_path / 'r.json').read_text())['link_rule']['missing_keys'] == [K('H').hex()]


def reader(directory, calls):
    def read(name):
        calls.append(name)
        return BytesIO((directory / name).read_bytes())
    return read


def test_link_history_must_continue_the_pointer_chain_and_be_readable(tmp_path):
    releases = {}
    for name, docs in [('base', ['A']), ('previous', ['A', 'P']), ('older', ['A', 'O'])]:
        releases[name] = release_dir(tmp_path / name, docs)['release_id']
    by_id = {rid: tmp_path / name for name, rid in releases.items()}
    read = lambda rid: reader(by_id[rid], []) if rid in by_id else (lambda name: (_ for _ in ()).throw(FileNotFoundError(name)))
    with pytest.raises(ValueError, match='must start with the live pointer'):
        fetch_base(read, releases['base'], tmp_path / 'w1', [releases['older']], previous_release_id=releases['previous'])
    with pytest.raises(ValueError, match='is absent or unreadable'):
        fetch_base(read, releases['base'], tmp_path / 'w2', [releases['previous'], 'e' * 64], previous_release_id=releases['previous'])
    _, _, _, history = fetch_base(read, releases['base'], tmp_path / 'w3', [releases['previous'], releases['older']],
                                  previous_release_id=releases['previous'])
    assert [h.name for h in history] == [releases['previous'], releases['older']]


def test_fetch_release_keeps_files_it_already_holds(pair, tmp_path):
    base, _ = pair
    release_id = json.loads((base / 'manifest.json').read_text())['release_id']
    first, second = [], []
    fetch_release(reader(base, first), release_id, tmp_path / 'copy')
    fetch_release(reader(base, second), release_id, tmp_path / 'copy')
    assert len(first) > 1 and second == ['manifest.json']
    (tmp_path / 'copy/links.parquet').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='differs from its manifest entry'):
        fetch_release(reader(base, []), release_id, tmp_path / 'copy')


# ct-ud0b: nightly publication when every difference is a new row from new receipts.
UNDATED_LIVE_RECEIPT = 'receipts/documents/undated/live.jsonl.gz'
LIVE_RECEIPTS = {'receipts/documents/2026-11-01/live.jsonl.gz', UNDATED_LIVE_RECEIPT}
NEW_RECEIPT = 'receipts/documents/2026-11-03/nightly.jsonl.gz'
REQUEST = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345.pdf'
FETCHED = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)


TS = pa.timestamp('us', tz='UTC')
WEEK = timedelta(days=7)
URL_STATE = pa.schema([('requested_url', pa.string()), ('attempts', pa.int32()), ('last_attempt', TS),
                       ('last_status', pa.int16()), ('last_outcome', pa.string()), ('last_good_at', TS),
                       ('next_attempt_at', TS), ('recheck_meeting_date', pa.date32()), ('linked_from', pa.list_(pa.binary(8)))])


def url_states(url, attempts, pages=(K('P'),)):
    """One url_state row as a capture night writes it: a fetch at FETCHED with no meeting date (so
    the shortest band, a week), or a queued link with the pages behind it."""
    return pa.Table.from_pylist([dict(requested_url=url, attempts=attempts, last_attempt=FETCHED if attempts else None,
        last_status=200 if attempts else None, last_outcome='stored' if attempts else None,
        last_good_at=FETCHED if attempts else None, next_attempt_at=FETCHED + WEEK if attempts else None,
        recheck_meeting_date=None, linked_from=[] if attempts else list(pages))], schema=URL_STATE)


CAPTURES = pa.schema([('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('capture_index', pa.int32()),
                      ('sha256', pa.binary(32)), ('requested_url', pa.string()), ('url', pa.string()),
                      ('context_url', pa.string()), ('member_path', pa.string()), ('expansion', pa.string()),
                      ('family', pa.string()), ('mode', pa.string()),
                      ('complete', pa.bool_()), ('attempt', pa.int32()), ('outcome', pa.string()),
                      ('http_status', pa.int32()), ('fetch_outcome', pa.string()), ('fetch_http_status', pa.int32()),
                      ('retrieved_at', TS)])


def write_captures(rows, path):
    """The lake captures table's columns that the gate reads, with a fetch's usual defaults."""
    defaults = dict(capture_index=0, url=None, context_url=None, member_path=None, expansion=None, family='documents', fetch_outcome=None,
                    fetch_http_status=None, retrieved_at=FETCHED)
    pq.write_table(pa.Table.from_pylist([{**defaults, **row} for row in rows], schema=CAPTURES), path)


def nightly(tmp_path, base_docs, candidate_docs, *, receipt=NEW_RECEIPT, raw_names_body=True, filenames=None,
            url=REQUEST, attempts=1, raw_url=REQUEST, capture_url=REQUEST, other_entity=False, nested=True, live_receipts=LIVE_RECEIPTS, failed_duplicate=None,
            base_tables=None, candidate_tables=None, also_held=None, cache_files=(), base_retired=None):
    """Releases plus a captures file and raw receipts; returns the gate's automatic callback."""
    import gzip
    import os
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    states = url_states(url, attempts)
    failure_url = 'https://www.govinfo.gov/failed-copy.pdf'
    baseline = dict(url_state=states.slice(0, 0))
    additions = dict(url_state=pa.concat_tables([states, failed_duplicate]) if failed_duplicate is not None else states)
    if list(candidate_docs) == list(base_docs):
        additions['url_state'] = states.slice(0, 0)  # no new document, so no newly attempted address
    if other_entity:
        additions['meetings'] = pa.table({'event_id': [119123]})
        baseline['meetings'] = additions['meetings'].slice(0, 0)
    release_dir(base, base_docs, retired=base_retired, **baseline, **(base_tables or {}))
    release_dir(candidate, candidate_docs, retired=[], **additions, **(candidate_tables or {}))
    if filenames:
        pq.write_table(pa.table({'filename': filenames}), candidate / 'list.parquet')
        manifest = json.loads((candidate / 'manifest.json').read_text())
        data = (candidate / 'list.parquet').read_bytes()
        entry = next(f for f in manifest['files'] if f['name'] == 'list.parquet')
        entry.update(sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(), size=len(data))
        manifest['release_id'] = release_identity(1, manifest['files'])
        (candidate / 'manifest.json').write_text(json.dumps(manifest))
    held_keys = set(''.join(base_docs))
    new = [k for keys in candidate_docs if not held_keys.intersection(keys) for k in keys]
    bodies = {k: K(k) + sha256(k.encode()).digest()[:24] for k in new}
    capture_rows = [dict(receipt_key=receipt, receipt_line=1, sha256=body, requested_url=capture_url,
                         mode='fetch', complete=True, attempt=0, outcome='stored', http_status=200)
                    for body in bodies.values()]
    if failed_duplicate is not None:
        capture_rows.append(dict(capture_rows[0], receipt_line=2, requested_url=failure_url,
                                 outcome='failed', http_status=403))
    if also_held:
        # The same body was also captured by a receipt the live release read.
        capture_rows.append(dict(capture_rows[0], receipt_key=also_held, receipt_line=7))
    # Cache files the pipeline captured: (file hash, receipt key).
    capture_rows += [dict(receipt_key=key, receipt_line=1, sha256=file_sha, requested_url=None, mode='fetch', complete=True,
                          attempt=0, outcome='stored', http_status=200) for file_sha, key in cache_files]
    write_captures(capture_rows, tmp_path / 'captures.parquet')
    sha = next(iter(bodies.values()), b'').hex() if raw_names_body else '0' * 64
    line = dict(record=dict(mode='fetch', outcome='stored', requested_url=raw_url, url=raw_url,
                            http_status=200, retrieved_at=FETCHED.isoformat(), content=dict(sha256=sha)),
                captures=[dict(pointer=['content', 'body'], sha256=sha,
                               body_key=f'bodies/sha256/{sha[:2]}/{sha}.gz', bytes=4721, media_type='application/pdf')])
    if len(bodies)>1:
        line['notes'] = [b.hex() for b in list(bodies.values())[1:]]
    if not nested:
        line.update(line.pop('record'))
    unrelated = (dict(record=dict(mode='fetch', requested_url=failure_url, outcome='failed', http_status=403),
                      captures=line['captures']) if failed_duplicate is not None else
                 dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[]))
    raw = {receipt: gzip.compress(('\n'.join(map(json.dumps, (line, unrelated))) + '\n').encode(), mtime=0)}
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    def automatic(report):
        return automatic_causes(report, base, candidate, engine=engine, captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                                live_receipt_keys=live_receipts, read_receipt=raw.__getitem__, work=tmp_path / 'auto',
                                candidate_receipt_keys={*live_receipts, receipt, *(key for _, key in cache_files)})
    return base, candidate, automatic


@pytest.mark.parametrize('nested', [True, False])
def test_additions_from_new_receipts_pass_unattended(tmp_path, nested):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], nested=nested)
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == []
    assert {(e['id'].split('|')[0], e['tickets'][0]) for e in report['automatic_causes']} == {
        ('list.parquet', 'ct-ud0b'), ('detail.parquet', 'ct-ud0b'), ('links.parquet', 'ct-ud0b'), ('url_state.parquet', 'ct-9j3z')}
    trace = json.loads((tmp_path / 'auto/automatic-trace.json').read_text())
    assert trace['url_state']['groups']['added URLs: new attempts'] == [1, 1] and trace['url_state']['lines'] == 1
    assert (trace['live_receipts'], trace['new_receipts']) == (2, 1)


# ct-gc99: new means absent from the live release's receipt set, whatever the key's date. A
# backlog read oldest first is older than the live release's newest receipt and still new.
BACKLOG_RECEIPTS = ['receipts/documents/2026-10-30/older.jsonl.gz', 'receipts/documents/undated/assemble.jsonl.gz',
                    'receipts/documents/2026-11-31/bad-date.jsonl.gz']


@pytest.mark.parametrize('receipt', BACKLOG_RECEIPTS)
def test_additions_from_a_backlog_receipt_pass_unattended(tmp_path, receipt):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], receipt=receipt)
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and {e['id'].split('|')[1] for e in report['automatic_causes']} >= {'added rows', 'added keys', 'added URLs'}
    assert json.loads((tmp_path / 'auto/automatic-trace.json').read_text())['url_state']['groups']['added URLs: new attempts'] == [1, 1]


@pytest.mark.parametrize('receipt', [sorted(LIVE_RECEIPTS)[0], UNDATED_LIVE_RECEIPT])
def test_an_added_row_from_a_receipt_the_live_release_read_refuses(tmp_path, receipt):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], receipt=receipt)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert any('is already in the live release' in reason for reason in json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'])


@pytest.mark.parametrize('receipt', [NEW_RECEIPT, BACKLOG_RECEIPTS[0]])
def test_a_body_the_live_release_also_read_is_not_new(tmp_path, receipt):
    held = sorted(LIVE_RECEIPTS)[0]
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], receipt=receipt, also_held=held)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['automatic_reasons'] == [f'automatic causes: {held} is already in the live release'] and 'automatic_causes' not in report


def test_a_raw_line_that_does_not_name_the_body_refuses(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], raw_names_body=False)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert any('does not name body' in r for r in json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'])


@pytest.mark.parametrize('receipt', [NEW_RECEIPT, BACKLOG_RECEIPTS[0]])
def test_a_changed_value_refuses_even_beside_new_rows(tmp_path, receipt):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], filenames=['A-renamed.pdf', 'N.pdf'], receipt=receipt)
    with pytest.raises(ValueError, match='changed filename'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert any('is not an addition' in r for r in json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'])


def test_a_removed_row_refuses(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A', 'B'], ['A', 'N'])
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    assert any('is not an addition' in r or 'link rule' in r for r in report['automatic_reasons'])


@pytest.mark.parametrize('change', [
    {'raw_url': 'https://www.govinfo.gov/unrelated.pdf'},  # The requested URL occurs on another line.
    {'capture_url': 'https://www.govinfo.gov/unrelated.pdf'},
    {'attempts': 2},
    {'attempts': 0},
    {'attempts': None},
    {'other_entity': True},
])
def test_nightly_refuses_additions_without_the_exact_new_document_attempt(tmp_path, change):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], **change)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['automatic_reasons'] and 'automatic_causes' not in report


def test_automatic_policy_refuses_a_verified_scope_removal(tmp_path):
    from viewer_publication.release_gate import automatic_causes
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    scope = {'version': 1, 'entries': [{'exclusions': ['/oembed/']}]}
    queued = url_states('https://archive.example.test/oembed/1', 0)
    release_dir(base, ['A'], scope=scope, url_state=queued)
    release_dir(candidate, ['A'], scope=scope, url_state=queued.slice(0, 0))
    assert require_release_gates(base, candidate, None, report_path=tmp_path / 'reviewed.json')['reasons'] == []
    def automatic(report):
        return automatic_causes(report, base, candidate, engine=None, captures=None,
                                live_receipt_keys=(), read_receipt=None, work=tmp_path / 'auto')
    with pytest.raises(ValueError, match='removed URLs'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'nightly.json', automatic=automatic)
    report = json.loads((tmp_path / 'nightly.json').read_text())
    assert report['failing'] == [] and report['reasons'] == report['automatic_reasons']


def test_a_removed_document_that_comes_back_is_not_a_new_document(tmp_path):
    """Review of ct-gc99: the live release shows a removal notice for N; an old, never-read receipt
    brings N back. Its key is absent from the live links, and it is not new: a key published again
    leaves the ledger, and that group is not an addition. (This held before the review; the test pins it.)"""
    notice = [dict(link_key=K('N'), successor_key=None, last_release_id='b' * 64, last_filename='N.pdf')]
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], receipt=BACKLOG_RECEIPTS[0], base_retired=notice)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['link_rule']['ok'] and 'automatic_causes' not in report
    assert report['automatic_reasons'] == [
        'automatic causes: retired_links.parquet|removed keys|no evidence given (-1) is not an addition that can be traced']


def test_more_added_documents_than_one_unattended_night_may_add_refuses(tmp_path, monkeypatch):
    from viewer_publication import release_gate
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'])
    monkeypatch.setattr(release_gate, 'AUTOMATIC_ADDITION_CAP', 0)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'] == [
        'automatic causes: 1 added documents, more than the 0 one unattended night may add']
    monkeypatch.setattr(release_gate, 'AUTOMATIC_ADDITION_CAP', 1)
    assert require_release_gates(base, candidate, None, report_path=tmp_path / 'r2.json', automatic=automatic)['reasons'] == []
    monkeypatch.undo()
    assert 150 < release_gate.AUTOMATIC_ADDITION_CAP < 567  # passes the capture day measured, stops the backlog measured


def test_an_empty_live_receipt_set_refuses(tmp_path):
    # Nothing to be absent from: every receipt would count as new.
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], live_receipts=set())
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'] == [
        'automatic causes: the live release has no receipt set to compare with']


def test_a_second_document_hash_in_raw_notes_does_not_ride_an_eligible_attempt(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N', 'X'])
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    reasons = json.loads((tmp_path / 'r.json').read_text())['automatic_reasons']
    assert len(reasons) == 1 and 'does not name body' in reasons[0]


@pytest.mark.parametrize('recorded', ['as the failure it was', 'as a success'])
def test_an_added_address_whose_fetch_failed_is_bookkeeping_and_must_record_the_failure(tmp_path, recorded):
    """ct-9j3z replaces ct-ud0b's rule that an added attempted address must have supplied a new
    document (349 of 910 did on 2026-11-10): a failed fetch is still a fetch. Its row must be what
    its line says; one claiming the shared body's success refuses."""
    failed = 'https://www.govinfo.gov/failed-copy.pdf'
    failure = dict(last_status=403, last_outcome='failed', last_good_at=None) if recorded == 'as the failure it was' else {}
    row = {**url_states(failed, 1).to_pylist()[0], **failure}
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], failed_duplicate=pa.Table.from_pylist([row], schema=URL_STATE))
    if failure:
        assert require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)['reasons'] == []
        return
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'] == [
        f"automatic causes: url_state: 1 rows: last_attempt, last_status or last_outcome is not the newest new line (first ['{failed}'])"]


def test_an_added_link_key_on_an_existing_document_requires_review(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['AZ', 'N'], filenames=['A.pdf', 'N.pdf'])
    report_path = tmp_path / 'r.json'
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=report_path, automatic=automatic)
    report = json.loads(report_path.read_text())
    assert report['link_rule']['ok']
    assert report['automatic_reasons'] == ['automatic causes: 2 added link keys, 1 attached to new documents']


# ct-syp1: a video cache refresh rewrites every citation of the cache file and nothing else.
CACHE_RECEIPT = 'receipts/pipeline-data/2026-11-08/refresh.jsonl.gz'


def cache_file(fetch):
    return sha256(fetch.encode()).digest()


def video_tables(fetch, day, *, title='Hearing on oversight', year=2026):
    file_sha = cache_file(fetch)
    return dict(
        channels=pa.table({'handle': ['@committee'], 'title': ['Committee'], 'record_sha': pa.array([file_sha], pa.binary())}),
        videos=pa.table({'video_key': ['youtube:one'], 'handle': ['@committee'], 'title': [title],
                         'details_checked_at': pa.array([datetime(year, 11, day, tzinfo=timezone.utc)], pa.timestamp('us', tz='UTC')),
                         'record_sha': pa.array([file_sha], pa.binary())}),
        recording_matches=pa.table({'match_id': ['m1'], 'video_key': ['youtube:one'],
                                    'source_ref': ['video_records:' + file_sha.hex()]}))


def refreshed(tmp_path, *, documents=('A',), captured=(('fetch-2', CACHE_RECEIPT),), live_receipts=LIVE_RECEIPTS, **candidate):
    """The gate's unattended callback for a release whose cache file went from fetch-1 to fetch-2;
    `captured` lists the cache files the capture table holds, each with its receipt."""
    return nightly(tmp_path, ['A'], list(documents), base_tables=video_tables('fetch-1', 1),
                   candidate_tables=video_tables('fetch-2', 8, **candidate), live_receipts=live_receipts,
                   cache_files=[(cache_file(fetch), key) for fetch, key in captured])


def test_a_cache_refresh_alone_passes_unattended(tmp_path):
    base, candidate, automatic = refreshed(tmp_path)
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and report['automatic_reasons'] == [] and report['failing'] == []
    proven = {(name, g['group']): g['count'] for name, facts in report['files'].items() for g in facts['groups']}
    assert proven == {('channels.parquet', 'changed record_sha'): 1, ('videos.parquet', 'changed record_sha'): 1,
                      ('videos.parquet', 'changed details_checked_at'): 1, ('recording_matches.parquet', 'changed source_ref'): 1}
    assert json.loads((tmp_path / 'auto/cited/citation-trace.json').read_text())['files'] == {cache_file('fetch-2').hex(): [CACHE_RECEIPT]}


def test_a_cache_refresh_beside_new_documents_passes_unattended(tmp_path):
    base, candidate, automatic = refreshed(tmp_path, documents=('A', 'N'))
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and {e['id'].split('|')[0] for e in report['automatic_causes']} == {
        'list.parquet', 'detail.parquet', 'links.parquet', 'url_state.parquet'}


def test_a_changed_title_beside_a_cache_refresh_refuses_unattended(tmp_path):
    base, candidate, automatic = refreshed(tmp_path, title='Hearing on something else')
    with pytest.raises(ValueError, match=r'no recorded cause for videos.parquet\|changed title\|value differs on matched key \(1\)'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    # The changed row's own citation is not proven either; the channel's and the match's are.
    assert sorted(g['file'] + '|' + g['group'] for g in report['failing']) == [
        'videos.parquet|changed details_checked_at', 'videos.parquet|changed record_sha', 'videos.parquet|changed title']
    assert any('videos.parquet|changed title' in reason for reason in report['automatic_reasons'])


# The independent review's end-to-end cases (review/REVIEW.md, E1 and E4): a release that is
# consistent with itself is not thereby true.
@pytest.mark.parametrize('captured,live_receipts,reason', [
    # E1: the cited hash is made up; the capture table has no such body.
    ((), LIVE_RECEIPTS, f'automatic causes: cited file {cache_file("fetch-2").hex()[:16]} is not a body in the capture table'),
    # The file sits in a receipt the live release read: it could have been cited then.
    ((('fetch-2', sorted(LIVE_RECEIPTS)[0]),), LIVE_RECEIPTS,
     f'automatic causes: cited file {cache_file("fetch-2").hex()[:16]} was already read by the live release ({sorted(LIVE_RECEIPTS)[0]})'),
    # No live receipt set: nothing can be new to it.
    ((('fetch-2', CACHE_RECEIPT),), set(), 'automatic causes: the live release has no receipt set to compare with'),
])
def test_a_consistent_citation_no_new_receipt_delivered_refuses_unattended(tmp_path, captured, live_receipts, reason):
    base, candidate, automatic = refreshed(tmp_path, captured=captured, live_receipts=live_receipts)
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['failing'] == [] and report['reasons'] == report['automatic_reasons'] == [reason]


def test_a_check_date_in_the_future_refuses_unattended(tmp_path):
    """E4: every citation consistent and the check date set to 2099."""
    base, candidate, automatic = refreshed(tmp_path, year=2099)
    with pytest.raises(ValueError, match=r'no recorded cause for videos.parquet\|changed details_checked_at'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)


# ct-9j3z: a capture night's url_state bookkeeping, proven from the lines of receipts new to the
# release. Every expected value below is written by hand from the receipts and the recheck
# registry (documents and house/pages: 7 days under 31 days of age, 28 under 731, else 365).
DAY = timedelta(days=1)
T0 = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
LIVE = sorted(LIVE_RECEIPTS)[0]
F = 'https://docs.house.gov/meetings/AG/AG03/20261020/111/F.pdf'  # fetched before, fetched again
Q = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg1/pdf/CHRG-119hhrg1.pdf'  # queued, fetched for the first time
A = 'https://www.energy.senate.gov/a.pdf'  # first seen and fetched; the fetch failed
N = 'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=1'  # a page read for the first time
U = 'https://docs.house.gov/meetings/AG/AG03/20261105/222/U.pdf'  # newly queued, linked from N
V = 'https://www.govinfo.gov/v.pdf'  # queued in both; N links it too now
Z = 'https://www.govinfo.gov/z.pdf'  # untouched
BODY = {name: sha256(name.encode()).digest() for name in ('F', 'Q', 'N', 'P')}
PAGE = {name: BODY[name][:8] for name in BODY}  # a page key is its body's first 8 bytes


def state(url, attempts=0, at=None, status=None, outcome=None, good=None, interval=None, date=None, pages=()):
    return dict(requested_url=url, attempts=attempts, last_attempt=at, last_status=status, last_outcome=outcome,
                last_good_at=good, next_attempt_at=at + interval if interval else None, recheck_meeting_date=date,
                linked_from=list(pages))


def capture_night(tmp_path, *, base=None, candidate=None, drop=(), fetches=None, raw=None, live_columns=None,
                  extra_columns=None, receipt_set=...):
    """Releases, captures and raw receipts for one capture night, as the gate's automatic callback.

    `base`/`candidate` override rows by address; `drop` leaves addresses out of the candidate.
    `fetches` overrides capture lines by (receipt, line), None removing one; `raw` overrides fields
    of a raw line's record, None removing one. `receipt_set` is the candidate's receipt set (None:
    not given)."""
    import gzip
    import os
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes
    meeting = datetime(2026, 10, 20).date()
    live = {F: state(F, 1, T0, 200, 'stored', T0, 7 * DAY, meeting), Q: state(Q, pages=[PAGE['P']]),
            V: state(V, pages=[PAGE['P']]), Z: state(Z, 1, T0, 200, 'stored', T0, 7 * DAY)}
    night = {**live,
             # 14 days after its meeting: the 7-day band.
             F: state(F, 2, FETCHED, 200, 'unchanged', FETCHED, 7 * DAY, meeting),
             # A first schedule: 302 days after the meeting date the model found, the 28-day band.
             Q: state(Q, 1, FETCHED, 200, 'stored', FETCHED, 28 * DAY, datetime(2026, 1, 5).date()),
             # No meeting date: the shortest band.
             A: state(A, 1, FETCHED, 403, 'failed', None, 7 * DAY),
             N: state(N, 1, FETCHED, 200, 'stored', FETCHED, 7 * DAY),
             U: state(U, pages=[PAGE['N']]), V: state(V, pages=sorted([PAGE['N'], PAGE['P']]))}
    live.update(base or {})
    night.update(candidate or {})
    for url in drop:
        night.pop(url)
    tables = []
    for rows in (live, night):
        table = pa.Table.from_pylist(sorted(rows.values(), key=lambda r: r['requested_url']), schema=URL_STATE)
        for name, changed in (extra_columns or {}).items():  # the candidate's values; the live release's are 'eligible'
            values = changed if rows is night else {}
            table = table.append_column(name, pa.array([values.get(r, 'eligible') for r in table['requested_url'].to_pylist()]))
        tables.append(table)
    if live_columns is not None:
        tables[0] = tables[0].select(live_columns)
    release_dir(tmp_path / 'base', ['A'], url_state=tables[0])
    release_dir(tmp_path / 'candidate', ['A'], url_state=tables[1])
    lines = {(LIVE, 1): dict(requested_url=F, sha256=BODY['F'], retrieved_at=T0, outcome='stored'),
             (LIVE, 2): dict(requested_url='https://docs.house.gov/old-page', sha256=BODY['P'], retrieved_at=T0,
                             outcome='stored', family='house/pages'),
             (NEW_RECEIPT, 1): dict(requested_url=F, sha256=BODY['F'], outcome='unchanged'),
             (NEW_RECEIPT, 2): dict(requested_url=Q, sha256=BODY['Q'], outcome='stored'),
             (NEW_RECEIPT, 3): dict(requested_url=A, sha256=None, outcome='failed', http_status=403, complete=False),
             (NEW_RECEIPT, 4): dict(requested_url=N, sha256=BODY['N'], outcome='stored', family='house/pages')}
    lines.update(fetches or {})
    rows = [dict(dict(mode='fetch', complete=True, attempt=0, http_status=200), receipt_key=key, receipt_line=line, **row)
            for (key, line), row in sorted(lines.items()) if row is not None]
    write_captures(rows, tmp_path / 'captures.parquet')
    text = {}
    for row in rows:
        record = dict(mode='fetch', requested_url=row['requested_url'], outcome=row['outcome'])
        record.update((raw or {}).get((row['receipt_key'], row['receipt_line']), {}))
        body = [dict(sha256=row['sha256'].hex())] if row.get('sha256') else []
        text.setdefault(row['receipt_key'], {})[row['receipt_line']] = json.dumps(dict(
            record={k: v for k, v in record.items() if v is not None}, captures=body))
    blobs = {key: gzip.compress(('\n'.join(by_line.get(i, '{}') for i in range(1, max(by_line) + 1)) + '\n').encode(), mtime=0)
             for key, by_line in text.items()}
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])

    def automatic(report):
        return automatic_causes(report, tmp_path / 'base', tmp_path / 'candidate', engine=engine,
                                captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                                live_receipt_keys=LIVE_RECEIPTS, read_receipt=blobs.__getitem__, work=tmp_path / 'auto',
                                candidate_receipt_keys=LIVE_RECEIPTS | {NEW_RECEIPT} if receipt_set is ... else receipt_set)
    return tmp_path / 'base', tmp_path / 'candidate', automatic


def unattended(tmp_path, **night):
    base, candidate, automatic = capture_night(tmp_path, **night)
    try:
        report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    except ValueError:
        report = json.loads((tmp_path / 'r.json').read_text())
    return report


def test_a_capture_night_whose_url_state_the_new_receipts_imply_passes_unattended(tmp_path):
    report = unattended(tmp_path)
    assert report['reasons'] == [] and report['automatic_reasons'] == []
    entries = {e['id']: e for e in report['automatic_causes']}
    assert {(i, e['count']) for i, e in entries.items()} == {
        ('url_state.parquet|added URLs|new attempts', 2), ('url_state.parquet|added URLs|queued link with no attempts yet', 1),
        *((f'url_state.parquet|changed {column}|value differs on matched key', n) for column, n in (
            ('attempts', 2), ('last_attempt', 2), ('last_status', 1), ('last_outcome', 2), ('last_good_at', 2),
            ('next_attempt_at', 2), ('recheck_meeting_date', 1), ('linked_from', 2)))}
    assert {e['tickets'][0] for e in entries.values()} == {'ct-9j3z'}
    trace = json.loads((tmp_path / 'auto/automatic-trace.json').read_text())
    assert trace['url_state']['queued_link_pages'] == [PAGE['N'].hex()] and trace['url_state']['lines'] == 4
    assert trace['url_state']['groups']['changed attempts'] == [2, 2]
    # The live receipt's line for F is not counted again, and the old page P needs no trace.
    assert {(row['receipt_key'], row['receipt_line']) for row in trace['lines']} == {(NEW_RECEIPT, 4)}


LATER = 'receipts/documents/2026-11-04/later.jsonl.gz'


def test_a_line_in_a_receipt_the_candidate_did_not_read_is_not_counted(tmp_path):
    """The lake holds receipts newer than the candidate; only the candidate's own set counts."""
    report = unattended(tmp_path, fetches={(LATER, 1): dict(requested_url=F, sha256=BODY['F'], outcome='unchanged',
                                                         retrieved_at=FETCHED + DAY)})
    assert report['reasons'] == []


@pytest.mark.parametrize('plant,reason', [
    # A wrong band: 28 days where the published meeting date gives 7.
    (dict(candidate={F: state(F, 2, FETCHED, 200, 'unchanged', FETCHED, 28 * DAY, datetime(2026, 10, 20).date())}),
     'next_attempt_at is not last_attempt plus the band of its published meeting date'),
    # A consistent band on a changed meeting date: the live release had scheduled F.
    (dict(candidate={F: state(F, 2, FETCHED, 200, 'unchanged', FETCHED, 28 * DAY, datetime(2026, 1, 5).date())}),
     'recheck_meeting_date changed on an address the live release had scheduled'),
    (dict(candidate={F: state(F, 0)}), 'attempts are not the live count plus the new lines'),
    (dict(candidate={F: state(F, 2, FETCHED, 200, 'unchanged', None, 7 * DAY, datetime(2026, 10, 20).date())}),
     'last_good_at is not the later of the live value and the newest good new line'),
    (dict(candidate={A: state(A, 1, FETCHED, 403, 'failed', FETCHED, 7 * DAY)}), 'last_good_at is not the newest good new line'),
    (dict(candidate={A: state(A, 1, FETCHED, 200, 'stored', None, 7 * DAY)}),
     'last_attempt, last_status or last_outcome is not the newest new line'),
    # No receipt implies a change with no new line (the 10 rows of 2026-11-10 were this).
    (dict(candidate={Z: state(Z, 1, T0, 200, 'stored', T0, 365 * DAY)}), 'changed with no new line'),
    # A tie in time with the live value cannot be ordered without the receipt keys' order.
    (dict(base={F: state(F, 1, FETCHED, 200, 'stored', T0, 7 * DAY, datetime(2026, 10, 20).date())}),
     'the newest new line ties the live last_attempt'),
    (dict(candidate={U: state(U)}), 'a queued address names no linking page'),
    (dict(candidate={V: state(V, pages=[PAGE['N']])}), 'a page that linked a queued address is gone'),
    (dict(candidate={U: state(U, at=FETCHED, interval=7 * DAY, pages=[PAGE['N']])}), 'a queued address carries a schedule'),
])
def test_url_state_a_new_receipt_does_not_imply_refuses_unattended(tmp_path, plant, reason):
    report = unattended(tmp_path, **plant)
    assert report['reasons'] and 'automatic_causes' not in report
    assert any(f': {reason} (first' in r for r in report['automatic_reasons']), report['automatic_reasons']


@pytest.mark.parametrize('plant,reason', [
    # The page behind a newly queued link must come from new receipts only.
    (dict(candidate={U: state(U, pages=[PAGE['P']])}), f'automatic causes: {LIVE} is already in the live release'),
    (dict(candidate={U: state(U, pages=[K('X')])}), "automatic causes: 1 queued link page keys have no capture to trace (first ['5858585858585858'])"),
    (dict(raw={(NEW_RECEIPT, 2): dict(requested_url=Q + '?other')}),
     f'automatic causes: {NEW_RECEIPT}:2 requests {Q}?other in raw, not {Q}'),
    (dict(fetches={(NEW_RECEIPT, 5): dict(requested_url='https://www.govinfo.gov/w.pdf', outcome='failed', http_status=404)}),
     'automatic causes: url_state: 1 addresses with new lines have no changed or added row in the candidate'),
])
def test_url_state_rows_that_raw_or_the_capture_table_do_not_bear_out_refuse_unattended(tmp_path, plant, reason):
    report = unattended(tmp_path, **plant)
    assert report['reasons'] and 'automatic_causes' not in report
    assert reason in report['automatic_reasons'], report['automatic_reasons']


@pytest.mark.parametrize('plant,group', [
    (dict(extra_columns={'capture_disposition': {Z: 'excluded'}}), 'changed capture_disposition'),
    (dict(drop=[Z]), 'removed URLs'),
])
def test_url_state_groups_no_receipt_sets_refuse_unattended(tmp_path, plant, group):
    report = unattended(tmp_path, **plant)
    assert report['reasons'] and 'automatic_causes' not in report
    assert any(f'url_state.parquet|{group}|' in r and 'is not an addition' in r for r in report['automatic_reasons'])



# Review of ct-9j3z (investigations/next-release-review-20261110/gate/REVIEW.md): its constructed
# candidates W2b, W4, W4b, W9, W10, W10b, W12, W12b, W13 and W14, and plants for the checks
# no test pinned.
@pytest.mark.parametrize('plant,reason', [
    # W2b: the capture table puts Q's line on Z, its redirect target, which raw names only as `url`.
    (dict(fetches={(NEW_RECEIPT, 2): dict(requested_url=Z, sha256=BODY['Q'], outcome='stored')},
          raw={(NEW_RECEIPT, 2): dict(requested_url=Q, url=Z)},
          candidate={Q: state(Q, pages=[PAGE['P']]), Z: state(Z, 2, FETCHED, 200, 'stored', FETCHED, 7 * DAY)}),
     f'automatic causes: {NEW_RECEIPT}:2 requests {Q} in raw, not {Z}'),
    # An older receipt shape with no requested_url (the mapping falls back to `_url`): refused, not guessed.
    (dict(raw={(NEW_RECEIPT, 2): dict(requested_url=None, _url=Q)}),
     f'automatic causes: {NEW_RECEIPT}:2 names no requested_url in raw, so it cannot be matched to {Q}'),
])
def test_a_raw_line_must_request_the_address_its_capture_line_names(tmp_path, plant, reason):
    report = unattended(tmp_path, **plant)
    assert report['reasons'] and 'automatic_causes' not in report
    assert reason in report['automatic_reasons'], report['automatic_reasons']


@pytest.mark.parametrize('line', [
    dict(http_status=404),  # W12: stored, but a 404 is not a good fetch
    dict(http_status=200, complete=False),  # W12b: stored, but incomplete
])
def test_last_good_at_moves_only_to_a_line_the_model_calls_a_good_fetch(tmp_path, line):
    report = unattended(tmp_path, fetches={(NEW_RECEIPT, 3): dict(requested_url=A, sha256=BODY['Q'], outcome='stored', **line)},
                        candidate={A: state(A, 1, FETCHED, line['http_status'], 'stored', FETCHED, 7 * DAY)})
    assert report['reasons'] and 'automatic_causes' not in report
    assert any(': last_good_at is not the newest good new line (first' in r for r in report['automatic_reasons']), report['automatic_reasons']


WITHOUT_FACTS = [n for n in URL_STATE.names if n not in ('recheck_meeting_date', 'linked_from')]


BOTH_MISSING = 'automatic causes: url_state cannot be traced: the live release publishes no recheck_meeting_date, linked_from'


@pytest.mark.parametrize('night,reason', [
    (dict(live_columns=WITHOUT_FACTS), BOTH_MISSING),  # W10: the first night after the columns ship
    (dict(live_columns=WITHOUT_FACTS, fetches={(NEW_RECEIPT, 1): None},  # W10b: and no address read again
          candidate={F: state(F, 1, T0, 200, 'stored', T0, 7 * DAY, datetime(2026, 10, 20).date())}), BOTH_MISSING),
    (dict(live_columns=[n for n in URL_STATE.names if n != 'recheck_meeting_date']),
     'automatic causes: url_state cannot be traced: the live release publishes no recheck_meeting_date'),
])
def test_a_live_release_without_the_url_state_facts_refuses_with_one_reason(tmp_path, night, reason):
    """This pair runs once in production: the first candidate with the columns against a live
    release without them. It must refuse with a reason and write its report, never raise."""
    report = unattended(tmp_path, **night)
    assert 'automatic_causes' not in report and report['reasons']
    assert [r for r in report['automatic_reasons'] if 'url_state' in r] == [reason]


def test_more_first_schedules_with_a_meeting_date_than_one_unattended_night_may_add_refuses(tmp_path, monkeypatch):
    """W4 and W4b pass by design: a first schedule's meeting date has no live value to keep. So, like
    added documents, one unattended night may take at most so many; Q is the fixture's one."""
    from viewer_publication import release_gate
    monkeypatch.setattr(release_gate, 'AUTOMATIC_FIRST_SCHEDULE_CAP', 0)
    report = unattended(tmp_path)
    assert report['automatic_reasons'] == [
        'automatic causes: 1 first schedules with a meeting date, more than the 0 one unattended night may add']
    monkeypatch.setattr(release_gate, 'AUTOMATIC_FIRST_SCHEDULE_CAP', 1)
    assert unattended(tmp_path / 'within')['reasons'] == []
    monkeypatch.undo()
    # The cap itself: one above refuses, at the cap passes. 2,000 is the nightly capture budget.
    cap, what = release_gate.AUTOMATIC_FIRST_SCHEDULE_CAP, 'first schedules with a meeting date'
    assert cap == 2000
    assert release_gate.over_cap(cap + 1, what, cap) == [
        'automatic causes: 2001 first schedules with a meeting date, more than the 2000 one unattended night may add']
    assert release_gate.over_cap(cap, what, cap) == []


@pytest.mark.parametrize('plant', [
    dict(candidate={Q: state(Q, 1, FETCHED, 200, 'stored', FETCHED, 365 * DAY, datetime(2020, 1, 1).date())}),  # W4
    dict(candidate={A: state(A, 1, FETCHED, 403, 'failed', None, 365 * DAY, datetime(2020, 1, 1).date())}),  # W4b
])
def test_a_first_schedules_meeting_date_is_taken_as_published_within_the_cap(tmp_path, plant):
    """The stated limit, pinned: a made-up meeting date on a first schedule passes."""
    assert unattended(tmp_path, **plant)['reasons'] == []


def test_url_state_without_the_candidates_receipt_set_refuses(tmp_path):
    report = unattended(tmp_path, receipt_set=None)
    assert report['reasons'] and 'automatic_causes' not in report
    assert "automatic causes: url_state needs the candidate's receipt set" in report['automatic_reasons']


@pytest.mark.parametrize('plant,reason', [
    # W13: an added address whose band is wrong.
    (dict(candidate={A: state(A, 1, FETCHED, 403, 'failed', None, 28 * DAY)}),
     'next_attempt_at is not last_attempt plus the band of its published meeting date'),
    # A fetched-before address whose status is not its newest line's.
    (dict(candidate={F: state(F, 2, FETCHED, 500, 'unchanged', FETCHED, 7 * DAY, datetime(2026, 10, 20).date())}),
     'last_attempt, last_status or last_outcome is not the newest new line'),
    # W14: a first fetch whose last_attempt is not its line's time.
    (dict(candidate={Q: state(Q, 1, FETCHED + DAY, 200, 'stored', FETCHED, 28 * DAY, datetime(2026, 1, 5).date())}),
     'last_attempt, last_status or last_outcome is not the newest new line'),
    # W9: a backlog line older than the live one moves the latest attempt backward.
    (dict(fetches={(NEW_RECEIPT, 6): dict(requested_url=Z, sha256=None, retrieved_at=T0 - 3 * DAY, outcome='failed', http_status=500)},
          candidate={Z: state(Z, 2, T0 - 3 * DAY, 500, 'failed', T0, 7 * DAY)}),
     'the latest attempt moved without a later new line'),
    # A queued address (in both) with a new line of its own.
    (dict(fetches={(NEW_RECEIPT, 6): dict(requested_url=V, sha256=None, outcome='failed', http_status=404)}),
     'a queued address has new lines'),
    # A fetched address that names linking pages.
    (dict(candidate={F: state(F, 2, FETCHED, 200, 'unchanged', FETCHED, 7 * DAY, datetime(2026, 10, 20).date(), pages=[PAGE['N']])}),
     'an address with attempts names linking pages'),
    # A new line with no time.
    (dict(fetches={(NEW_RECEIPT, 3): dict(requested_url=A, sha256=None, outcome='failed', http_status=403, complete=False,
                                          retrieved_at=None)}),
     'the newest new line has no time'),
])
def test_url_state_checks_the_first_review_found_untested_refuse(tmp_path, plant, reason):
    report = unattended(tmp_path, **plant)
    assert report['reasons'] and 'automatic_causes' not in report
    assert any(f': {reason} (first' in r for r in report['automatic_reasons']), report['automatic_reasons']
