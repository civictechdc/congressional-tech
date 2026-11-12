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
    assert report['link_rule'] == dict(missing=0, missing_keys=[], dangling=0, dangling_keys=[],
                                       published_and_retired=0, published_and_retired_keys=[],
                                       changed=0, changed_keys=[],
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


def test_a_key_that_reaches_two_files_passes_when_correction_names_both_sorted_bodies(tmp_path):
    pair = repointed(tmp_path, 'ABC', base=('a', 'b', 'c'), candidate=('', 'ab', 'ac'))
    multi = dict(correction('lookup_key', K('a').hex(), 'A', 'B'), candidate_body=sorted([body('B'), body('C')]))
    addr_multi = dict(correction('address', 'https://example.test/a', 'A', 'B'), candidate_body=sorted([body('B'), body('C')]))
    groups = [*REPOINTED_GROUPS,
              ('urls.parquet', 'keys with more rows', 'more documents answer the key', 1),
              ('sources.parquet', 'same-URL rows added', 'more documents list the address', 1)]
    report, causes = corrected_gate(tmp_path, pair, groups, [multi, addr_multi])
    assert report['reasons'] == []
    assert report['named_corrections']['lookup_key'] == dict(waived=1, keys=[K('a').hex()])
    assert report['named_corrections']['address'] == dict(waived=1, keys=['https://example.test/a'])
    notes = render_notes(causes, *pair)
    assert f'`{body("B")[:12]}`, `{body("C")[:12]}`' in notes
    # Naming a third body that the key does not reach refuses and reports all named bodies.
    extra = dict(multi, candidate_body=sorted([body('B'), body('C'), body('D')]))
    refused, _ = corrected_gate(tmp_path, pair, groups, [extra, addr_multi])
    assert f'link rule: 1 live lookup keys answer another file ({K("a").hex()})' in refused['reasons']
    assert (f'cause record: correction lookup_key {K("a").hex()} from {body("A")} to '
            f'{", ".join(sorted([body("B"), body("C"), body("D")]))} matches no finding of the link rule') in refused['reasons']


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


def test_a_waiver_in_force_never_quiets_a_vanished_key(tmp_path):
    """Reviewer (5950bb11): the six fused keys are named and let through while a seventh key vanishes.
    A waiver that works must not reach the vanish reason; the absoluteness test above only uses a
    correction that waives nothing, so it cannot see one leak."""
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, [*'ABCDEFG', 'H'])
    release_dir(candidate, ['ABCDEFG'], saved='G')
    report, _ = corrected_gate(tmp_path, (base, candidate), FUSED_GROUPS, FUSED_CORRECTIONS)
    assert report['named_corrections']['link_key']['waived'] == 6
    assert any(reason.startswith('link rule: 1 base link keys vanish') for reason in report['reasons'])


def test_a_key_that_also_reaches_a_row_with_no_saved_file_cannot_be_named(tmp_path):
    """Reviewer (5950bb11): K(a) now reaches B's row and a row that shows no file. No single file is
    shown on every row it reaches, so naming B must not let it through (candidate_bodies keeps the null)."""
    pair = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(pair[0], list('ABC'), **addresses(['a', 'b', 'c']))
    detail = pa.table({'link_key': pa.array([K(x) for x in 'ABC'], pa.binary(8)),
                       'saved_body': pa.array([K('A') + bytes(24), K('B') + bytes(24), None], pa.binary(32))})
    release_dir(pair[1], list('ABC'), detail=detail, **addresses(['', 'ab', 'ac']))
    report, _ = corrected_gate(tmp_path, pair, REPOINTED_GROUPS, [correction('lookup_key', K('a').hex(), 'A', 'B')])
    answer = next(a for a in report['link_rule']['lookup_changed_answers'] if a['key'] == K('a').hex())
    assert sorted(answer['candidate_bodies'], key=str) == sorted([body('B'), None], key=str)
    assert K('a').hex() not in report['named_corrections']['lookup_key']['keys']
    assert unmatched('lookup_key', K('a').hex(), 'A', 'B') in report['reasons']


def test_render_notes_calls_corrected_entries_corrections(tmp_path):
    """ct-dagf (2): the prose above the corrections table names them corrections."""
    report, causes = corrected_gate(tmp_path, fused(tmp_path), FUSED_GROUPS, FUSED_CORRECTIONS)
    assert report['reasons'] == []
    notes = render_notes(causes, tmp_path / 'base', tmp_path / 'candidate')
    assert '6 corrections (keys and addresses that now answer another file on purpose), each named in the reviewed cause record with both files (ct-4nax):' in notes


@pytest.mark.parametrize('disposition', ['explained', 'accepted_defect'])
def test_load_causes_refuses_a_group_entry_whose_ticket_has_no_file(tmp_path, disposition):
    """ct-dagf (5): group entries check ticket existence in .tickets just like corrections."""
    from congress_api.retention.provenance import file_pin
    from viewer_publication.release_gate import load_causes
    ev = tmp_path / 'ev.txt'
    ev.write_text('evidence\n')
    record = dict(
        version=1, base_release_id='a' * 64, candidate_release_id='b' * 64,
        groups=[dict(id='list.parquet|added rows|unexplained', count=1, disposition=disposition,
                     cause='test cause', tickets=['ct-zzzz'],
                     evidence=[dict(path=str(ev), **file_pin(ev))])])
    path = tmp_path / 'causes.json'
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='no file in .*: ct-zzzz'):
        load_causes(dict(path=str(path), **file_pin(path)))


def test_verdict_returns_named_corrections_without_mutating_report(tmp_path):
    """ct-dagf (6): verdict is pure on its input report."""
    from viewer_publication.release_comparison import compare
    from viewer_publication.release_gate import verdict
    pair = fused(tmp_path)
    causes = record_for(*ids(pair), tmp_path, groups=FUSED_GROUPS, corrections=FUSED_CORRECTIONS)
    report = compare(*pair)
    snapshot = json.loads(json.dumps(report, default=str))
    reasons, named = verdict(report, causes)
    assert reasons == []
    assert named['link_key']['waived'] == 6
    assert report == snapshot and 'named_corrections' not in report


def test_gate_refuses_a_candidate_key_both_published_and_retired(tmp_path):
    """ct-xyo9 (4), plant R3: a key in both candidate links and candidate retired_links refuses even with a record."""
    notice = [dict(link_key=K('N'), successor_key=None, last_release_id='b' * 64, last_filename='N.pdf')]
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['A'], retired=notice)
    release_dir(candidate, ['A', 'N'], retired=notice)
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        ('list.parquet', 'added rows', 'no surviving link key', 1),
        ('detail.parquet', 'added rows', 'no surviving link key', 1),
        ('links.parquet', 'added keys', 'no evidence given', 1)])
    with pytest.raises(ValueError, match='1 candidate link keys are both published and retired'):
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')


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
    ('candidate_body', [body('B'), body('C')], 'candidate_body of link_key'),
])
def test_load_causes_refuses_a_malformed_correction(tmp_path, field, value, message):
    entry = {k: v for k, v in dict(FUSED_CORRECTIONS[0], **{field: value}).items() if v is not MISSING}
    with pytest.raises(ValueError, match=message):
        record_for('a' * 64, 'b' * 64, tmp_path, corrections=[entry])


@pytest.mark.parametrize('bad_bodies, message', [
    ([], 'sorted list of at least two distinct'),
    ([body('B')], 'sorted list of at least two distinct'),
    ([body('C'), body('B')], 'sorted list of at least two distinct'),
    ([body('B'), body('B')], 'sorted list of at least two distinct'),
    ([body('B'), 'G' * 64], 'candidate_body of lookup_key'),
])
def test_load_causes_refuses_malformed_multi_body_lookup_correction(tmp_path, bad_bodies, message):
    entry = dict(correction('lookup_key', K('a').hex(), 'A', 'B'), candidate_body=bad_bodies)
    with pytest.raises(ValueError, match=message):
        record_for('a' * 64, 'b' * 64, tmp_path, corrections=[entry])


CORRECTIONS_SCHEMA = pa.schema([
    ('original_url', pa.string(), False),
    ('rejected_body', pa.binary(32), False),
    ('decision_id', pa.string(), False),
    ('decided_at', pa.timestamp('us', tz='UTC'), False),
    ('recovered_url', pa.string(), True),
    ('identity_note', pa.string(), True),
])
RECOVERIES_SCHEMA = pa.schema([
    ('list_row', pa.int32(), False),
    ('ordinal', pa.int32(), False),
    ('kind', pa.string(), False),
    ('body', pa.binary(32), False),
    ('suffix', pa.string(), False),
    ('bytes', pa.int64(), False),
    ('imported_at', pa.date32(), True),
    ('recovered_url', pa.string(), False),
    ('identity_note', pa.string(), True),
])


def _proven_pair(tmp_path, *, plant=None):
    url = 'https://www.example.test/hearings/March%2030/porter.pdf'
    url_link_key = sha256(('url:' + url).encode()).digest()[:8]
    lookup_form = 'example.test/hearings/March%2030/porter.pdf'
    lookup_k1 = sha256(('lookup:' + lookup_form).encode()).digest()[:8]
    lookup_k2 = sha256(('lookup-alias:serialization-v1:' + lookup_form).encode()).digest()[:8]
    unknown_link_key = K('U')

    wrong_body = bytes.fromhex(body('W'))
    right_body = bytes.fromhex(body('R'))
    other_body = bytes.fromhex(body('X'))

    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    base_links = [url_link_key, K('K')] + ([unknown_link_key] if plant == 'unknown_key' else [])
    base_rows = [0, 1] + ([0] if plant == 'unknown_key' else [])
    cand_links = [url_link_key, K('K')] + ([unknown_link_key] if plant == 'unknown_key' else [])
    cand_rows = [1, 1]

    release_dir(
        base, ['W', 'K'], saved='WK',
        links=pa.table({'link_key': pa.array(base_links, pa.binary(8)),
                        'list_row': pa.array(base_rows, pa.int32())}),
        urls=pa.table({'lookup_key': pa.array([lookup_k1, lookup_k2], pa.binary(8)),
                       'list_row': pa.array([0, 0], pa.int32())}),
        sources=pa.table({'list_row': pa.array([0, 1], pa.int32()),
                          'url': pa.array([url, 'https://www.example.test/keep.pdf'], pa.string()),
                          'member_path': pa.array([None, None], pa.string())}),
    )

    cand_saved = right_body
    note_prefix = body('R')[:16] if plant != 'note_body_prefix_mismatch' else '0' * 16
    rejected_rows = [dict(
        original_url=url,
        rejected_body=other_body if plant == 'wrong_live_body' else wrong_body,
        decision_id='dec-1',
        decided_at=datetime(2026, 11, 10, 13, 5, tzinfo=timezone.utc),
        recovered_url='http://mirror.example.test/wrong.pdf',
        identity_note=f"The copy holds a different document; this address's document is body {note_prefix}.",
    )]
    if plant == 'candidate_shows_another_rejected_copy':
        rejected_rows.append(dict(
            original_url=url,
            rejected_body=right_body,
            decision_id='dec-2',
            decided_at=datetime(2026, 11, 10, 13, 6, tzinfo=timezone.utc),
            recovered_url='http://mirror.example.test/also-wrong.pdf',
            identity_note=None,
        ))
    rec_rows = [] if plant == 'wrong_candidate_fused_not_recovery' else [dict(
        list_row=1, ordinal=0, kind='wayback', body=cand_saved, suffix='', bytes=128,
        imported_at=None, recovered_url='http://web.archive.org/porter.pdf', identity_note=None,
    )]

    release_dir(
        candidate, ['keep', 'porter'],
        detail=pa.table({'link_key': pa.array([K('K'), url_link_key], pa.binary(8)),
                         'saved_body': pa.array([bytes.fromhex(body('K')), cand_saved], pa.binary(32))}),
        links=pa.table({'link_key': pa.array([K('K'), url_link_key] + ([unknown_link_key] if plant == 'unknown_key' else []), pa.binary(8)),
                        'list_row': pa.array([0, 1] + ([1] if plant == 'unknown_key' else []), pa.int32())}),
        urls=pa.table({'lookup_key': pa.array([lookup_k1, lookup_k2], pa.binary(8)),
                       'list_row': pa.array([1, 1], pa.int32())}),
        sources=pa.table({'list_row': pa.array([0, 1], pa.int32()),
                          'url': pa.array(['https://www.example.test/keep.pdf', url], pa.string()),
                          'member_path': pa.array([None, None], pa.string())}),
        recoveries=pa.Table.from_pylist(rec_rows, schema=RECOVERIES_SCHEMA),
        corrections=pa.Table.from_pylist(rejected_rows, schema=CORRECTIONS_SCHEMA),
    )
    return (base, candidate), url, url_link_key.hex(), sorted([lookup_k1.hex(), lookup_k2.hex()])


PROVEN_GROUPS = [
    ('corrections.parquet', 'file added', 'file absent from the base release', 1),
    ('detail.parquet', 'changed link_key', 'value differs on matched key', 1),
    ('detail.parquet', 'changed saved_body', 'value differs on matched key', 1),
    MOVED_LINKS,
    ('list.parquet', 'changed filename', 'value differs on matched key', 2),
    ('recoveries.parquet', 'file added', 'file absent from the base release', 1),
    ('sources.parquet', 'changed bytes, no key or value difference found', 'unexplained', 0),
    ('urls.parquet', 'changed bytes, no key or value difference found', 'unexplained', 0),
]


def test_published_corrections_table_proves_changed_answers_without_hand_list(tmp_path):
    pair, url, link_hex, lookup_hexes = _proven_pair(tmp_path)
    # No hand `corrections` list in the cause record: candidate/corrections.parquet proves every changed answer!
    causes = record_for(*ids(pair), tmp_path, groups=PROVEN_GROUPS)
    report = require_release_gates(*pair, causes, report_path=tmp_path / 'r.json')
    assert report['reasons'] == []
    assert report['proven_corrections'] == dict(
        link_key=dict(proven=1, keys=[link_hex]),
        lookup_key=dict(proven=2, keys=lookup_hexes),
        address=dict(proven=1, keys=[url]),
    )
    notes = render_notes(causes, *pair)
    assert f'`{link_hex}`' in notes and 'dec-1' in notes


def test_proven_corrections_do_not_crowd_out_manual_or_unnamed_link_rule_findings(tmp_path):
    """P2-1 (ct-faan): link_rule samples unproven keys before proven ones so >= sample proven keys
    never hide an unnamed regression or prevent a manual named_correction from matching."""
    from viewer_publication.lookup_aliases import address_keys
    from viewer_publication.release_comparison import Diff, link_rule

    # Pick URLs whose link_key hexes sort alphabetically BEFORE manual/regressed link_keys ('fe...', 'ff...').
    urls = [f'https://www.house.gov/proven-{i}.pdf' for i in range(40)]
    proven_three = sorted(
        [(next(iter(address_keys(u)['link_key'])), u) for u in urls],
        key=lambda pair: pair[0],
    )[:3]
    manual_key = bytes.fromhex('fe' * 8)
    reg_key = bytes.fromhex('ff' * 8)
    assert proven_three[-1][0] < manual_key.hex() < reg_key.hex()

    def build_case(sub, *, include_reg):
        base, cand = sub / 'base', sub / 'cand'
        extra_keys = [manual_key] + ([reg_key] if include_reg else [])
        n_rows = 1 + len(proven_three) + len(extra_keys)
        base_link_keys = [K('K'), *[bytes.fromhex(kh) for kh, _ in proven_three], *extra_keys]
        base_bodies = [bytes.fromhex(body('K'))] + [sha256(f'old-{i}'.encode()).digest() for i in range(n_rows - 1)]
        cand_bodies = [bytes.fromhex(body('K'))] + [sha256(f'new-{i}'.encode()).digest() for i in range(n_rows - 1)]
        src_urls = ['https://www.example.test/keep.pdf', *[u for _, u in proven_three]] + [
            f'https://www.example.test/extra-{i}.pdf' for i in range(len(extra_keys))
        ]
        lookup_keys = [bytes.fromhex(sorted(address_keys(u)['lookup_key'])[0]) for u in src_urls]
        release_dir(
            base, [f'doc-{i}' for i in range(n_rows)],
            detail=pa.table({'link_key': pa.array(base_link_keys, pa.binary(8)),
                             'saved_body': pa.array(base_bodies, pa.binary(32))}),
            links=pa.table({'link_key': pa.array(base_link_keys, pa.binary(8)),
                            'list_row': pa.array(list(range(n_rows)), pa.int32())}),
            urls=pa.table({'lookup_key': pa.array(lookup_keys, pa.binary(8)),
                           'list_row': pa.array(list(range(n_rows)), pa.int32())}),
            sources=pa.table({'list_row': pa.array(list(range(n_rows)), pa.int32()),
                              'url': pa.array(src_urls, pa.string()),
                              'member_path': pa.array([None] * n_rows, pa.string())}),
        )
        rec_rows = [
            dict(list_row=1 + idx, ordinal=0, kind='wayback_exact_url', body=cand_bodies[1 + idx], suffix='', bytes=128,
                 imported_at=None, recovered_url=f'http://web.archive.org/{idx}.pdf', identity_note=None)
            for idx, (_, u) in enumerate(proven_three)
        ]
        corr_rows = [
            dict(original_url=u, rejected_body=base_bodies[1 + idx], decision_id=f'dec-{idx}',
                 decided_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
                 recovered_url=f'http://web.archive.org/bad-{idx}.pdf',
                 identity_note=f"The copy holds a different document; this address's document is body {cand_bodies[1 + idx].hex()[:12]}.")
            for idx, (_, u) in enumerate(proven_three)
        ]
        release_dir(
            cand, [f'doc-{i}' for i in range(n_rows)],
            detail=pa.table({'link_key': pa.array(base_link_keys, pa.binary(8)),
                             'saved_body': pa.array(cand_bodies, pa.binary(32))}),
            links=pa.table({'link_key': pa.array(base_link_keys, pa.binary(8)),
                            'list_row': pa.array(list(range(n_rows)), pa.int32())}),
            urls=pa.table({'lookup_key': pa.array(lookup_keys, pa.binary(8)),
                           'list_row': pa.array(list(range(n_rows)), pa.int32())}),
            sources=pa.table({'list_row': pa.array(list(range(n_rows)), pa.int32()),
                              'url': pa.array(src_urls, pa.string()),
                              'member_path': pa.array([None] * n_rows, pa.string())}),
            recoveries=pa.Table.from_pylist(rec_rows, schema=RECOVERIES_SCHEMA),
            corrections=pa.Table.from_pylist(corr_rows, schema=CORRECTIONS_SCHEMA),
        )
        return base, cand, base_bodies, cand_bodies, src_urls, lookup_keys

    # Case 1: 3 proven + 1 manual named_correction with sample=2 passes with 0 link-rule refusals!
    from viewer_publication.release_comparison import documents as diff_documents
    from viewer_publication.release_gate import named_corrections
    b1, c1, bb1, cb1, su1, lk1 = build_case(tmp_path / 'manual-ok', include_reg=False)
    d1 = Diff(b1, c1)
    d1.documents = diff_documents(d1)
    rule1 = link_rule(d1, sample=2)
    manual_corrs = [
        dict(kind='link_key', key=manual_key.hex(), live_body=bb1[4].hex(), candidate_body=cb1[4].hex(),
             decision='Reviewed manual fix', tickets=['ct-faan']),
        dict(kind='lookup_key', key=lk1[4].hex(), live_body=bb1[4].hex(), candidate_body=cb1[4].hex(),
             decision='Reviewed manual fix', tickets=['ct-faan']),
        dict(kind='address', key=su1[4], live_body=bb1[4].hex(), candidate_body=cb1[4].hex(),
             decision='Reviewed manual fix', tickets=['ct-faan']),
    ]
    waived1, _prov1, refused1, stale1 = named_corrections(rule1, manual_corrs)
    assert stale1 == []
    assert refused1 == {'link_key': [], 'lookup_key': [], 'address': []}
    assert waived1['link_key'] == [manual_key.hex()]

    # Case 2: 3 proven + 1 manual + 1 unnamed regression with sample=2 names the regressed key explicitly!
    b2, c2, bb2, cb2, su2, lk2 = build_case(tmp_path / 'reg-caught', include_reg=True)
    d2 = Diff(b2, c2)
    d2.documents = diff_documents(d2)
    rule2 = link_rule(d2, sample=2)
    _waived2, _prov2, refused2, stale2 = named_corrections(rule2, manual_corrs)
    assert stale2 == []
    assert refused2['link_key'] == [f'link rule: 1 live link keys answer another file ({reg_key.hex()})']


@pytest.mark.parametrize('plant', [
    'wrong_live_body',
    'wrong_candidate_fused_not_recovery',
    'candidate_shows_another_rejected_copy',
    'note_body_prefix_mismatch',
    'unknown_key',
])
def test_published_corrections_proof_refuses_planted_defects(tmp_path, plant):
    pair, _, _, _ = _proven_pair(tmp_path, plant=plant)
    extra_corr = 2 if plant == 'candidate_shows_another_rejected_copy' else 1
    groups = [
        (f, g, c, extra_corr if f == 'corrections.parquet' else n)
        for f, g, c, n in PROVEN_GROUPS
        if not (plant == 'wrong_candidate_fused_not_recovery' and f == 'recoveries.parquet')
    ]
    if plant == 'unknown_key':
        groups = [
            (f, g, c, -1 if f in ('detail.parquet', 'list.parquet') and g == 'merged rows' else n)
            for f, g, c, n in groups
        ]
    causes = record_for(*ids(pair), tmp_path, groups=groups)
    with pytest.raises(ValueError, match=r'link rule: .* answer another file'):
        require_release_gates(*pair, causes, report_path=tmp_path / 'r.json')


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
                      ('family', pa.string()), ('sniffed_format', pa.string()), ('mode', pa.string()),
                      ('complete', pa.bool_()), ('attempt', pa.int32()), ('outcome', pa.string()),
                      ('http_status', pa.int32()), ('fetch_outcome', pa.string()), ('fetch_http_status', pa.int32()),
                      ('retrieved_at', TS)])


def write_captures(rows, path):
    """The lake captures table's columns that the gate reads, with a fetch's usual defaults."""
    defaults = dict(capture_index=0, url=None, context_url=None, member_path=None, expansion=None, family='documents',
                    sniffed_format=None, fetch_outcome=None, fetch_http_status=None, retrieved_at=FETCHED)
    pq.write_table(pa.Table.from_pylist([{**defaults, **row} for row in rows], schema=CAPTURES), path)


def nightly(tmp_path, base_docs, candidate_docs, *, receipt=NEW_RECEIPT, raw_names_body=True, filenames=None,
            url=REQUEST, attempts=1, raw_url=REQUEST, capture_url=REQUEST, other_entity=False, nested=True, live_receipts=LIVE_RECEIPTS, failed_duplicate=None,
            base_tables=None, candidate_tables=None, also_held=None, cache_files=(), capture_lines=(), base_retired=None):
    """Releases plus a captures file and raw receipts; returns the gate's automatic callback.
    `capture_lines` are further capture rows, each a dict of its own columns."""
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
    release_dir(base, base_docs, retired=base_retired, **{**baseline, **(base_tables or {})})
    release_dir(candidate, candidate_docs, retired=[], **{**additions, **(candidate_tables or {})})
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
    # Cache files the pipeline captured: (file hash, receipt key), defaulting to pipeline-data YouTube cache paths.
    yt_default = lambda idx: f'https://github.com/civictechdc/congressional-tech/raw/pipeline-data/youtube/youtube_{idx:02d}.json'
    explicit_shas = {row.get('sha256') for row in capture_lines} | {item[0] for item in cache_files}
    if base_tables and 'channels' in base_tables and live_receipts:
        live_key = sorted(live_receipts)[0]
        for idx, ch in enumerate(base_tables['channels'].to_pylist()):
            if ch.get('record_sha') and ch['record_sha'] not in explicit_shas:
                capture_rows.append(dict(receipt_key=live_key, receipt_line=100 + idx, sha256=ch['record_sha'],
                                         requested_url=None, url=yt_default(idx), family='pipeline-data', mode='fetch',
                                         complete=True, attempt=0, outcome='stored', http_status=None))
    capture_rows += [dict(receipt_key=item[1], receipt_line=1 + idx, sha256=item[0], requested_url=None, url=yt_default(idx),
                          family='pipeline-data', mode='fetch', complete=True, attempt=0, outcome='stored', http_status=None,
                          **(item[2] if len(item) > 2 else {})) for idx, item in enumerate(cache_files)]
    capture_rows += [dict(dict(receipt_line=1, mode='fetch', complete=True, attempt=0, outcome='stored', http_status=200), **row)
                     for row in capture_lines]
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
    by_receipt = {}
    for row in capture_lines:
        if row['receipt_key'] not in raw:
            sha_hex = row['sha256'].hex() if row.get('sha256') else None
            by_receipt.setdefault(row['receipt_key'], {})[row.get('receipt_line', 1)] = json.dumps(dict(
                record={k: v for k, v in dict(mode=row.get('mode', 'fetch'), requested_url=row.get('requested_url'),
                                              outcome=row.get('outcome', 'stored')).items() if v is not None},
                captures=[dict(sha256=sha_hex)] if sha_hex else []))
    for key, by_line in by_receipt.items():
        raw[key] = gzip.compress(('\n'.join(by_line.get(i, '{}') for i in range(1, max(by_line) + 1)) + '\n').encode(), mtime=0)
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    def automatic(report):
        return automatic_causes(report, base, candidate, engine=engine, captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                                live_receipt_keys=live_receipts, read_receipt=raw.__getitem__, work=tmp_path / 'auto',
                                candidate_receipt_keys={*live_receipts, receipt, *(item[1] for item in cache_files),
                                                        *(row['receipt_key'] for row in capture_lines)})
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


# ct-uywf, ct-rhqw: a Congress.gov meeting record read again. Its witness keys hash the record body,
# so a new body re-keys both witnesses; the meeting's detail read, status sightings and the
# publisher's update stamp move, and an update may change anything the record states (owner,
# 2026-11-11: "Everything from Congress.gov publishes"). Expected groups are written by hand.
MEETING_URL = 'https://api.congress.gov/v3/committee-meeting/119/house/118340?format=json'
FIRST_READ = 'receipts/congress/meetings/2026-10-31/first.jsonl.gz'  # in the live release's receipt set
RELIST = 'receipts/congress/meetings/2026-11-08/relist.jsonl.gz'
OLD_RECORD, NEW_RECORD = sha256(b'meeting 118340, first read').digest(), sha256(b'meeting 118340, read again').digest()
READ = pa.struct([('source_url', pa.string()), ('retrieved_at', TS), ('receipt_key', pa.string()), ('receipt_line', pa.int32()),
                  ('capture_index', pa.int32()), ('body_sha256', pa.string()), ('meeting_parser_version', pa.string()),
                  ('proof_parser_version', pa.string())])
MEETINGS = pa.schema([
    ('event_id', pa.int64()), ('title', pa.string()), ('meeting_date', pa.date32()), ('publisher_status', pa.string()),
    ('subject_keys', pa.list_(pa.string())), ('document_references', pa.list_(pa.string())),
    ('videos', pa.list_(pa.struct([('name', pa.string()), ('url', pa.string()), ('video_key', pa.string())]))),
    ('house_xml_updated', pa.string()), ('congress_gov_updated', TS), ('outcome', pa.string()), ('outcome_basis', pa.string()),
    ('outcome_source_reference', pa.string()), ('rescheduled_to', pa.int64()), ('rescheduled_basis', pa.string()),
    ('sittings', pa.list_(pa.struct([('start', TS), ('end', TS), ('place', pa.string()), ('room', pa.string()), ('building', pa.string()),
                                     ('address', pa.string())]))),
    ('publisher_status_observations', pa.list_(pa.struct([('source', pa.string()), ('status', pa.string()),
                                                          ('meeting_date', pa.date32()), ('record_sha', pa.string()), ('observed_at', TS)]))),
    ('congress_gov_detail_observation', pa.struct([('state', pa.string()), ('coverage', pa.string()), ('successful_read', READ),
        ('latest_attempt', pa.struct([('evidence', READ), ('state', pa.string()), ('outcome', pa.string()), ('http_status', pa.int32())])),
        ('has_undated_attempt', pa.bool_())]))])
WITNESSES = pa.schema([('witness_key', pa.string()), ('occasion', pa.string()), ('source', pa.string()), ('record_sha', pa.binary()),
                       ('source_locator', pa.string()), ('context_key', pa.string()), ('name', pa.string()), ('organization', pa.string()),
                       ('panel', pa.string()), ('panel_order', pa.int16()), ('display_order', pa.int16()), ('superseded_by', pa.string())])
KEY_MAP = pa.schema([('old_key', pa.string()), ('witness_key', pa.string()), ('status', pa.string()), ('basis', pa.string()),
                     ('candidate_keys', pa.list_(pa.string())), ('occasion', pa.string()), ('source', pa.string())])
HEARD = datetime(2025, 6, 12).date()
PANEL = (('Ann Lee', 'GAO'), ('Bo Park', 'CBO'))


def meeting_read(record, receipt, at, *, keys, mapped, outcome='stored', updated=datetime(2026, 1, 2, tzinfo=timezone.utc),
                 statuses=(), documents=('hearing memo',), panel=PANEL, order=(1, 2), panels=None, title='Oversight hearing',
                 date=HEARD, status='Scheduled', videos=(), house_xml=None, held=('unknown', 'no_outcome_evidence', None),
                 rescheduled=(None, None), rooms=()):
    """The meeting, its witnesses (listed in `order`, each on its (panel, panel order), all on the
    first panel by default) and the key map, as one read of the record left them. `videos` are names;
    `held` is the meeting's (outcome, outcome basis, outcome source reference); `rooms` are (start, room)
    sittings."""
    panels = panels or [('Panel I', 1)] * len(keys)
    read = dict(source_url=MEETING_URL, retrieved_at=at, receipt_key=receipt, receipt_line=1, capture_index=0,
                body_sha256=record.hex(), meeting_parser_version='m1', proof_parser_version='p1')
    meeting = dict(event_id=118340, title=title, meeting_date=date, publisher_status=status, subject_keys=[],
                   document_references=list(documents),
                   videos=[dict(name=v, url=f'https://www.youtube.com/watch?v={v}', video_key=None) for v in videos],
                   house_xml_updated=house_xml, congress_gov_updated=updated, outcome=held[0], outcome_basis=held[1],
                   outcome_source_reference=held[2], rescheduled_to=rescheduled[0], rescheduled_basis=rescheduled[1],
                   sittings=[dict(start=start, end=None, place=None, room=room, building=None, address=None) for start, room in rooms],
                   publisher_status_observations=[dict(zip(('source', 'status', 'meeting_date', 'record_sha', 'observed_at'), s))
                                                  for s in statuses],
                   congress_gov_detail_observation=dict(state='successful', coverage='selected_release_inputs', successful_read=read,
                       latest_attempt=dict(evidence=read, state='successful', outcome=outcome, http_status=200), has_undated_attempt=False))
    witnesses = [dict(witness_key=key, occasion='meeting:118340', source='congress_gov', record_sha=record,
                      source_locator=f'congress_gov:witness[{place}]', context_key='congress/meetings', name=name,
                      organization=organization, panel=sitting, panel_order=rank, display_order=place, superseded_by=None)
                 for key, (name, organization), place, (sitting, rank) in zip(keys, panel, order, panels, strict=True)]
    key_map = [dict(old_key=old, witness_key=new, status='unambiguous', basis=basis, candidate_keys=[],
                    occasion='meeting:118340', source='congress_gov') for old, new, basis in mapped]
    return dict(meetings=pa.Table.from_pylist([meeting], schema=MEETINGS), witnesses=pa.Table.from_pylist(witnesses, schema=WITNESSES),
                witness_key_map=pa.Table.from_pylist(key_map, schema=KEY_MAP))


FIRST_SEEN = datetime(2026, 10, 31, tzinfo=timezone.utc)
SEEN_AGAIN = datetime(2026, 11, 8, 14, tzinfo=timezone.utc)
UPDATED_OLD, UPDATED_NEW = datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 11, 7, tzinfo=timezone.utc)
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
LIVE_STATUS = ('congress_gov', 'Scheduled', HEARD, OLD_RECORD.hex(), FIRST_SEEN)
NEW_MAP = [('k1', 'n1', 'content'), ('w1', 'n1', 'content'), ('w2', 'n2', 'content'), ('v1', 'n1', 'content')]
OTHER_BODY, SECOND_BODY = bytes.fromhex('ab' * 32), bytes.fromhex('d2' * 32)
MODS_OLD, MODS_NEW = bytes.fromhex('c1' * 32), bytes.fromhex('c2' * 32)
MODS_RECEIPT = 'receipts/govinfo/2026-11-10/mods.jsonl.gz'
UPDATE = 'a Congress.gov update of its meeting, read again with new bytes (ct-rhqw)'


def base_tables(**change):
    """The live release: meeting 118340 as first read, with witnesses w1 and w2 and one older key k1."""
    return meeting_read(OLD_RECORD, FIRST_READ, FIRST_SEEN, **{**dict(keys=('w1', 'w2'), mapped=[('k1', 'w1', 'occurrence')],
                                                                   statuses=[LIVE_STATUS]), **change})


def cand_tables(record=NEW_RECORD, receipt=RELIST, at=SEEN_AGAIN, **change):
    """The candidate after the relist read the record again from `receipt`: by default new bytes, the
    same two witnesses re-keyed to n1 and n2, a later update stamp, and the status seen in the new body.
    With `record=OLD_RECORD` the same bytes came back: keys, stamp and status stay, the status seen again."""
    new = record != OLD_RECORD
    default = dict(keys=('n1', 'n2') if new else ('w1', 'w2'), mapped=NEW_MAP if new else [('k1', 'w1', 'occurrence')],
                   outcome='stored' if new else 'unchanged', updated=UPDATED_NEW if new else UPDATED_OLD,
                   statuses=[LIVE_STATUS, ('congress_gov', 'Scheduled', HEARD, record.hex(), at)] if new else [LIVE_STATUS[:4] + (at,)])
    return meeting_read(record, receipt, at, **{**default, **change})


def capture_line(receipt, body, at, *, url=MEETING_URL, receipt_line=1, family='congress', **extra):
    return dict(receipt_key=receipt, receipt_line=receipt_line, capture_index=0, sha256=body, requested_url=url, family=family,
                retrieved_at=at, **extra)


def edit(tables, name, change):
    """`tables` with `change` applied to the rows of one of them."""
    rows = tables[name].to_pylist()
    change(rows)
    return {**tables, name: pa.Table.from_pylist(rows, schema=tables[name].schema)}


def other_witness(key, source, body, place, name, organization):
    return dict(witness_key=key, occasion='meeting:118340', source=source, record_sha=body, source_locator=f'{source}:witness[{place}]',
                context_key='ctx/' + source, name=name, organization=organization, panel='Panel I', panel_order=1,
                display_order=place, superseded_by=None)


def documents(keys):
    """One document whose list and detail rows name `keys` as its witnesses."""
    return dict(list=pa.table({'filename': ['A.pdf'], 'witness_keys': [list(keys)]}),
                detail=pa.table({'link_key': pa.array([K('A')], pa.binary(8)), 'saved_body': pa.array([K('A') + bytes(24)], pa.binary(32)),
                                 'witness_keys': [list(keys)]}))


def locators(*places):
    return lambda rows: [row.update(source_locator=f'congress_gov:witness[{place}]') for row, place in zip(rows, places)]


READ_AGAIN = 'a new read of the Congress.gov detail record: every other column equal on the meeting'
FIRST_STATED = 'a meeting Congress.gov states for the first time, read from its detail record (ct-rhqw)'


def gate_night(tmp_path, base, candidate, lines=None, cache_files=(), documents=(['A'], ['A'])):
    """Gates 1 and 2, unattended, on the two releases; returns (passed, report). By default the
    capture table holds the candidate's read (its body, address and time, in RELIST) and the live read."""
    if lines is None:
        read = candidate['meetings'].to_pylist()[0]['congress_gov_detail_observation']['successful_read']
        lines = [capture_line(read['receipt_key'], bytes.fromhex(read['body_sha256']), read['retrieved_at']),
                 capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]
    base_dir, candidate_dir, automatic = nightly(tmp_path, *documents, base_tables=base, candidate_tables=candidate,
                                                 live_receipts=LIVE_RECEIPTS | {FIRST_READ}, capture_lines=lines, cache_files=cache_files)
    try:
        return True, require_release_gates(base_dir, candidate_dir, None, report_path=tmp_path / 'r.json', automatic=automatic)
    except ValueError:
        return False, json.loads((tmp_path / 'r.json').read_text())


def groups_of(report):
    return {(name, g['group'], g['cause']): g['count'] for name, facts in report['files'].items() for g in facts['groups']}


def test_a_meeting_read_again_with_unchanged_witnesses_passes_unattended(tmp_path):
    passed, report = gate_night(tmp_path, base_tables(), cand_tables())
    assert passed and report['reasons'] == [] and report['automatic_reasons'] == [] and report['failing'] == []
    assert groups_of(report) == {
        ('witnesses.parquet', 'removed keys', f're-keyed: witness_key_map names the published successor; {UPDATE}'): -2,
        ('witnesses.parquet', 'added keys', f'successor of a re-keyed witness; {UPDATE}'): 2,
        ('witness_key_map.parquet', 'added keys', f'key retired from witnesses in this release; {UPDATE}'): 2,
        ('witness_key_map.parquet', 'added keys', f'a key no base witness carries; {UPDATE}'): 1,
        ('witness_key_map.parquet', 'changed basis', UPDATE): 1,
        ('meetings.parquet', 'changed congress_gov_detail_observation', UPDATE): 1,
        ('meetings.parquet', 'changed congress_gov_updated', UPDATE): 1,
        ('meetings.parquet', 'changed publisher_status_observations', UPDATE): 1}
    assert all(g.get('refetch_only') for facts in report['files'].values() for g in facts['groups'])
    trace = json.loads((tmp_path / 'auto/cited/citation-trace.json').read_text())
    assert trace['files'] == {NEW_RECORD.hex(): [RELIST]} and [r['receipt_key'] for r in trace['reads']] == [RELIST]


def test_a_byte_identical_read_again_passes_unattended(tmp_path):
    """Only the date stamps move: the same body read from a new receipt, its status seen again."""
    passed, report = gate_night(tmp_path, base_tables(), cand_tables(record=OLD_RECORD))
    assert passed and report['failing'] == []
    assert groups_of(report) == {('meetings.parquet', 'changed congress_gov_detail_observation', READ_AGAIN): 1,
                                 ('meetings.parquet', 'changed publisher_status_observations', READ_AGAIN): 1}
    assert json.loads((tmp_path / 'auto/cited/citation-trace.json').read_text())['files'] == {}
    assert not (tmp_path / 'meeting-updates.txt').exists()


UNRESOLVED = dict(old_key='w2', witness_key=None, status='unresolved', basis=None, candidate_keys=[], occasion='meeting:118340',
                  source='congress_gov')
NINE, TEN = datetime(2025, 6, 12, 14, tzinfo=timezone.utc), datetime(2025, 6, 19, 14, tzinfo=timezone.utc)


def report_lines(tmp_path):
    return (tmp_path / 'meeting-updates.txt').read_text().splitlines()


def test_a_congress_gov_update_publishes_and_the_morning_report_says_what_changed(tmp_path):
    """Owner, 2026-11-11 (ct-rhqw): a re-fetched meeting's title, date, status, sitting, witnesses,
    documents and videos all change; the night clears the release check, and the report names each change."""
    base = base_tables(documents=('hearing memo', 'agenda'), rooms=[(NINE, 'SD-366')])
    candidate = cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, ('Cy Diaz', 'EPA')), order=(1, 2, 3),
                            title='Oversight hearing, rescheduled', date=HEARD + timedelta(days=7), status='Postponed',
                            documents=('hearing memo', 'testimony'), videos=('v1', 'v1'), rooms=[(TEN, 'SD-406')],
                            statuses=[LIVE_STATUS, ('congress_gov', 'Postponed', HEARD + timedelta(days=7), NEW_RECORD.hex(), SEEN_AGAIN)])
    passed, report = gate_night(tmp_path, base, candidate)
    assert passed, report['reasons'] + report['automatic_reasons']
    assert report['files']['meetings.parquet']['congress_gov_updates'] == [118340]
    assert report_lines(tmp_path) == [
        'Cleared the release check: 1 Congress.gov meeting update (' + report['base_release'][:12] + ' to '
        + report['candidate_release'][:12] + ', ct-rhqw).', '',
        '118340 Oversight hearing, rescheduled (2025-06-19)',
        '  title: Oversight hearing -> Oversight hearing, rescheduled',
        '  date: 2025-06-12 -> 2025-06-19',
        '  status: Scheduled -> Postponed',
        '  witnesses added: Cy Diaz (EPA)',
        '  documents added: testimony',
        '  documents removed: agenda',
        '  videos added: v1; v1',
        '  sittings added: 2025-06-19 14:00Z SD-406',
        '  sittings removed: 2025-06-12 14:00Z SD-366']
    assert json.loads((tmp_path / 'meeting-updates.json').read_text())['line'] == (
        'Cleared the release check with 1 Congress.gov meeting update: 118340 (title, date, status, +1 witness, +1 document, '
        '-1 document, +2 videos, +1 sitting, -1 sitting)')


def test_a_stopped_night_says_so_and_names_the_lost_keys(tmp_path):
    """The record drops Bo Park and the map states his key unresolved: a lost key stops the night
    (owner, 2026-11-11), and the report says nothing was published and which key was lost."""
    candidate = edit(cand_tables(keys=('n1',), panel=PANEL[:1], order=(1,), mapped=NEW_MAP[:2]), 'witness_key_map',
                     lambda rows: rows.append(dict(UNRESOLVED)))
    passed, report = gate_night(tmp_path, base_tables(), candidate)
    assert not passed
    lines = report_lines(tmp_path)
    assert lines[0].startswith('STOPPED at the release check, nothing published') and lines[1].startswith('  comparison: no recorded cause')
    assert '  witness keys lost (no single successor): w2 (Bo Park (CBO)): unresolved' in lines
    summary = json.loads((tmp_path / 'meeting-updates.json').read_text())
    assert not summary['cleared'] and summary['line'].startswith('STOPPED at the release check, nothing published; 1 Congress.gov meeting update waited')


def test_the_report_shows_a_renamed_video(tmp_path):
    """Review R9: the same address under a new name is a change the report shows."""
    passed, _ = gate_night(tmp_path, base_tables(videos=('v1',)), edit(cand_tables(videos=('v1',)), 'meetings',
                                                                       lambda rows: rows[0]['videos'][0].update(name='v1 (renamed)')))
    assert passed and report_lines(tmp_path)[2:] == ['118340 Oversight hearing (2025-06-12)', '  videos added: v1 (renamed)', '  videos removed: v1']


def test_the_report_formats_real_sittings_without_none_or_doubled_rooms(tmp_path):
    """Real meetings populate `place` alongside `room` and `building` (meeting-records-resolved.sql),
    and a sitting may have no start time."""
    sitting = dict(start=None, end=None, place='366, Dirksen Senate Office Building',
                   room='366', building='Dirksen Senate Office Building', address=None)
    candidate = edit(cand_tables(), 'meetings', lambda rows: rows[0].update(sittings=[sitting]))
    passed, _ = gate_night(tmp_path, base_tables(), candidate)
    assert passed and report_lines(tmp_path)[2:] == [
        '118340 Oversight hearing (2025-06-12)',
        '  sittings added: 366, Dirksen Senate Office Building']


@pytest.mark.parametrize('case,expected_lost', [
    ('map_names_an_unpublished_successor', ['w2 (Bo Park (CBO)): successor gone not published']),
    ('two_old_keys_one_successor', [
        'k1 (historical): collides on n1',
        'w1 (Ann Lee (GAO)): collides on n1',
        'w2 (Bo Park (CBO)): collides on n1']),
    ('historical_key_names_an_unpublished_successor', ['k1 (historical): successor gone not published']),
    ('historical_key_successor_on_another_meeting', ['k1 (historical): successor bn9 not on meeting:118340']),
    ('successor_on_another_updated_meeting', ['w2 (Bo Park (CBO)): successor bn9 not on meeting:118340']),
])
def test_the_report_names_unambiguous_map_rows_that_still_lose_a_key(tmp_path, case, expected_lost):
    passed, _ = gate_night(tmp_path, *CASES[case][0]())
    assert not passed
    summary = json.loads((tmp_path / 'meeting-updates.json').read_text())
    entry = next(m for m in summary['meetings'] if m['event_id'] == 118340)
    assert entry['keys_lost'] == expected_lost


def first_stated():
    """The live release does not hold meeting 118340; the relist reads it with two witnesses and their
    free_context_key prior rows in witness_key_map (witness-key-priors.sql)."""
    return (edit(base_tables(keys=(), panel=(), order=(), mapped=[]), 'meetings', lambda rows: rows.clear()),
            cand_tables(mapped=[('f1', 'n1', 'occurrence'), ('f2', 'n2', 'occurrence')]))


def coverage(witnesses, documents=1, extra=()):
    rows = [dict(event_id=118340, aspect='witnesses', state='present', basis='appearance_records', count=witnesses, reason=None),
            dict(event_id=118340, aspect='documents', state='present', basis='list.meeting_keys', count=documents, reason=None), *extra]
    return pa.Table.from_pylist(rows, schema=pa.schema([('event_id', pa.int64()), ('aspect', pa.string()), ('state', pa.string()),
                                                        ('basis', pa.string()), ('count', pa.int32()), ('reason', pa.string())]))


def mods(reordered=False):
    """A MODS print of the meeting re-fetched with new bytes, its witnesses (and the order) otherwise equal."""
    old = [other_witness('m1', 'mods', MODS_OLD, 1, *PANEL[0]), other_witness('m2', 'mods', MODS_OLD, 2, *PANEL[1])]
    new = [other_witness('m3', 'mods', MODS_NEW, 2 if reordered else 1, *PANEL[0]),
           other_witness('m4', 'mods', MODS_NEW, 1 if reordered else 2, *PANEL[1])]
    mapped = [dict(old_key=o, witness_key=n, status='unambiguous', basis='content', candidate_keys=[], occasion='meeting:118340',
                   source='mods') for o, n in (('m1', 'm3'), ('m2', 'm4'))]
    candidate = edit(edit(base_tables(), 'witnesses', lambda rows: rows.extend(new)), 'witness_key_map', lambda rows: rows.extend(mapped))
    return (edit(base_tables(), 'witnesses', lambda rows: rows.extend(old)), candidate,
            [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN), capture_line(MODS_RECEIPT, MODS_NEW, SEEN_AGAIN, url='https://www.govinfo.gov/mods')])


def meeting_row(tables, event, read=True):
    """`tables` plus a copy of meeting 118340 as meeting `event`, with its own read (in RELIST, line 2), or with no detail read
    (Congress.gov only lists it)."""
    meeting = tables['meetings'].to_pylist()[0]
    observation = meeting['congress_gov_detail_observation']
    body = sha256(f'meeting {event}'.encode()).digest()
    reading = dict(observation['successful_read'], body_sha256=body.hex(), receipt_line=2,
                   source_url=MEETING_URL.replace('118340', str(event))) if read else None
    copy = dict(meeting, event_id=event, publisher_status_observations=[],
                congress_gov_detail_observation=dict(observation, state='successful' if read else 'unknown', successful_read=reading,
                                                     latest_attempt=dict(observation['latest_attempt'], evidence=reading)))
    return {**tables, 'meetings': pa.Table.from_pylist([meeting, copy], schema=tables['meetings'].schema)}, body


def listed_only_beside_an_update():
    """Review F1 (the 338820 shape): beside an update, Congress.gov lists meeting 338820 with no detail read."""
    candidate, _ = meeting_row(cand_tables(), 338820, read=False)
    return base_tables(), candidate


def nomination_named_by_the_update(subject):
    """An added nomination; the update names `subject` as the meeting's subject."""
    table = lambda ids: pa.Table.from_pylist([dict(nomination_id=i, description='to be Inspector General') for i in ids],
                                             schema=pa.schema([('nomination_id', pa.string()), ('description', pa.string())]))
    candidate = edit(cand_tables(), 'meetings', lambda rows: rows[0].update(subject_keys=[subject]))
    return ({**edit(base_tables(), 'meetings', lambda rows: rows[0].update(subject_keys=[])), 'nominations': table([])},
            {**candidate, 'nominations': table(['119-pn-1022-19'])})


def document_names(witness_keys, meeting_keys=()):
    """One document naming witness `witness_keys` and meetings `meeting_keys` in list and detail (review R4)."""
    return dict(list=pa.table({'filename': ['A.pdf'], 'witness_keys': [list(witness_keys)],
                               'meeting_keys': pa.array([list(meeting_keys)], pa.list_(pa.string()))}),
                detail=pa.table({'link_key': pa.array([K('A')], pa.binary(8)), 'saved_body': pa.array([K('A') + bytes(24)], pa.binary(32)),
                                 'witness_keys': [list(witness_keys)], 'meeting_keys': pa.array([list(meeting_keys)], pa.list_(pa.string()))}))


HOUSE_MEETING_XML = 'https://docs.house.gov/meetings/AS/AS00/20250612/118340/HHRG-119-AS00-20250612.xml'


def document_injects_subject_beside_update(*, first=False):
    """A newly captured single-meeting document ('N') carries measure_keys=['119-pn-1022-19'], which
    entity-meetings.sql copies into meeting 118340's subject_keys and entity-nominations.sql publishes."""
    nom_schema = pa.schema([('nomination_id', pa.string()), ('description', pa.string())])
    base_m, cand_m = first_stated() if first else (base_tables(), cand_tables())
    cand_m = edit(cand_m, 'meetings', lambda rows: rows[0].update(subject_keys=['119-pn-1022-19']))
    base_list = pa.table({'filename': ['A.pdf'], 'meeting_keys': pa.array([[]], pa.list_(pa.string())),
                          'measure_keys': pa.array([[]], pa.list_(pa.string()))})
    cand_list = pa.table({'filename': ['A.pdf', 'N.pdf'],
                          'meeting_keys': pa.array([[], ['118340']], pa.list_(pa.string())),
                          'measure_keys': pa.array([[], ['119-pn-1022-19']], pa.list_(pa.string()))})
    cand_detail = pa.table({'link_key': pa.array([K('A'), K('N')], pa.binary(8)),
                            'saved_body': pa.array([K('A') + bytes(24), K('N') + sha256(b'N').digest()[:24]], pa.binary(32))})
    base_url = pa.Table.from_pylist([] if first else [state(MEETING_URL, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, 28 * DAY, HEARD)],
                                    schema=URL_STATE)
    cand_url = pa.concat_tables([url_states(REQUEST, 1), pa.Table.from_pylist(
        [state(MEETING_URL, 1 if first else 2, SEEN_AGAIN, 200, 'stored', SEEN_AGAIN, 28 * DAY, HEARD)], schema=URL_STATE)])
    lines = [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN, family='congress/meetings'),
             capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN, family='congress/meetings')]
    return ({**base_m, 'list': base_list, 'url_state': base_url, 'nominations': pa.Table.from_pylist([], schema=nom_schema)},
            {**cand_m, 'list': cand_list, 'detail': cand_detail, 'url_state': cand_url,
             'nominations': pa.Table.from_pylist([dict(nomination_id='119-pn-1022-19', description='to be IG')], schema=nom_schema)},
            lines, (), (['A'], ['A', 'N']))


RECORDING_MATCHES = pa.schema([
    ('match_id', pa.string()), ('subject_kind', pa.string()), ('subject_id', pa.string()), ('event_id', pa.int64()),
    ('package_id', pa.string()), ('video_key', pa.string()), ('url', pa.string()), ('basis', pa.string()),
    ('decision', pa.string()), ('score', pa.int16()), ('recording_scope', pa.string()), ('status', pa.string()),
    ('note', pa.string()), ('source_ref', pa.string()),
    ('meeting_links', pa.list_(pa.struct([('event_id', pa.int64()), ('basis', pa.string()), ('scope', pa.string())])))])


def publisher_match(event_id, video_key, url, **override):
    key_input = json.dumps(['event', str(event_id), video_key or url or '', override.get('basis', 'publisher_link')]).encode()
    row = dict(match_id=sha256(key_input).hexdigest(), subject_kind='event', subject_id=str(event_id), event_id=event_id,
               package_id=None, video_key=video_key, url=url, basis='publisher_link', decision='linked', score=100,
               recording_scope='unknown', status='asserted', note=None, source_ref='meetings.videos',
               meeting_links=[dict(event_id=event_id, basis='direct_event', scope='event')])
    row.update(override)
    return row


RECORDINGS = pa.schema([
    ('video_key', pa.string()), ('event_ids', pa.list_(pa.int64())),
    ('tracks', pa.list_(pa.struct([('body', pa.binary(32)), ('suffix', pa.string()), ('format', pa.string()),
                                   ('language', pa.string()), ('production', pa.string())])))])


def publisher_video_matches_case(*, first=False, curated=False, non_updated_event=False, extra_track=False,
                                 bad_rec_event=False, html_page_recording=False, html_page_shared_event=False):
    v1_url, v2_url = 'https://www.youtube.com/watch?v=v1', 'https://www.youtube.com/watch?v=v2'
    vs_url = 'https://www.youtube.com/watch?v=vs'
    ev_url = 'https://www.congress.gov/event/119th-Congress/house-event/118340'
    track = [dict(body=OTHER_BODY, suffix='.vtt', format='vtt', language='en', production='auto')] if extra_track else []
    if first:
        base, cand = first_stated()
        cand = edit(cand, 'meetings', lambda r: r[0].update(videos=[dict(name='v2', url=v2_url, video_key='youtube:v2'),
                                                                    dict(name='ev', url=ev_url, video_key=None)]))
        return ({**base, 'recording_matches': pa.Table.from_pylist([], schema=RECORDING_MATCHES),
                 'recordings': pa.Table.from_pylist([], schema=RECORDINGS)},
                {**cand, 'recording_matches': pa.Table.from_pylist(
                    [publisher_match(118340, 'youtube:v2', v2_url), publisher_match(118340, None, ev_url)], schema=RECORDING_MATCHES),
                 'recordings': pa.Table.from_pylist([dict(video_key='youtube:v2', event_ids=[118340], tracks=track)], schema=RECORDINGS)})
    base = edit(base_tables(), 'meetings', lambda r: r[0].update(videos=[dict(name='v1', url=v1_url, video_key='youtube:v1')]))
    cand = edit(cand_tables(), 'meetings', lambda r: r[0].update(videos=[dict(name='v2', url=v2_url, video_key='youtube:v2'),
                                                                         dict(name='vs', url=vs_url, video_key='youtube:vs'),
                                                                         dict(name='ev', url=ev_url, video_key=None)]))
    base_rm = [publisher_match(118340, 'youtube:v1', v1_url), publisher_match(999999, 'youtube:vs', vs_url)]
    cand_rm = [publisher_match(118340, 'youtube:v2', v2_url), publisher_match(118340, 'youtube:vs', vs_url),
               publisher_match(999999, 'youtube:vs', vs_url), publisher_match(118340, None, ev_url)]
    base_rec = [dict(video_key='youtube:v1', event_ids=[118340], tracks=[]),
                dict(video_key='youtube:vs', event_ids=[999999], tracks=[])]
    vs_events = [118340, 338820, 999999] if bad_rec_event else [118340, 999999]
    cand_rec = [dict(video_key='youtube:v2', event_ids=[118340], tracks=track),
                dict(video_key='youtube:vs', event_ids=vs_events, tracks=[])]
    if html_page_recording:
        cand_rec.append(dict(video_key='youtube:html_page_only', event_ids=[118340], tracks=[]))
    if html_page_shared_event:
        cand = edit(cand, 'meetings', lambda r: r[0].update(videos=[dict(name='v2', url=v2_url, video_key='youtube:v2'),
                                                                    dict(name='ev', url=ev_url, video_key=None)]))
        cand_rm = [m for m in cand_rm if not (m['event_id'] == 118340 and m['video_key'] == 'youtube:vs')]
    if curated:
        cand_rm.append(publisher_match(118340, 'youtube:c1', None, basis='curated', decision='found', score=None,
                                       recording_scope='full', status='decided', source_ref='recording_decisions:rd-1'))
    if non_updated_event:
        base, _ = meeting_row(base, 338820, read=False)
        cand, _ = meeting_row(cand, 338820, read=False)
        cand = edit(cand, 'meetings', lambda r: r[1].update(videos=[dict(name='v9', url='https://www.senate.gov/isvp/?comm=csce&filename=csce111626', video_key='senate:csce111626')]))
        cand_rm.append(publisher_match(338820, 'senate:csce111626', 'https://www.senate.gov/isvp/?comm=csce&filename=csce111626'))
    return ({**base, 'recording_matches': pa.Table.from_pylist(base_rm, schema=RECORDING_MATCHES),
             'recordings': pa.Table.from_pylist(base_rec, schema=RECORDINGS)},
            {**cand, 'recording_matches': pa.Table.from_pylist(cand_rm, schema=RECORDING_MATCHES),
             'recordings': pa.Table.from_pylist(cand_rec, schema=RECORDINGS)})


def captioned_recording_linked_case():
    """An updated meeting links a held video that already had caption tracks in `base`:
    `recordings.event_ids`, `meetings.transcripts` (`source='captions'`) and `meeting_coverage` move."""
    tx_struct = pa.struct([('source', pa.string()), ('package_id', pa.string()), ('list_row', pa.int32()),
                           ('formats', pa.list_(pa.string())), ('video_key', pa.string()),
                           ('language', pa.string()), ('production', pa.string())])
    m_schema = MEETINGS.append(pa.field('transcripts', pa.list_(tx_struct)))
    v_url = 'https://www.youtube.com/watch?v=cap1'
    track = [dict(body=OTHER_BODY, suffix='.vtt', format='vtt', language='en', production='auto')]
    cov_schema = pa.schema([('event_id', pa.int64()), ('aspect', pa.string()), ('state', pa.string()),
                            ('basis', pa.string()), ('count', pa.int32()), ('reason', pa.string())])
    base, cand = base_tables(videos=()), cand_tables(videos=())
    bm = dict(base['meetings'].to_pylist()[0], transcripts=[])
    cm = dict(cand['meetings'].to_pylist()[0], videos=[dict(name='cap1', url=v_url, video_key='youtube:cap1')],
              transcripts=[dict(source='captions', package_id=None, list_row=None, formats=['vtt'],
                                video_key='youtube:cap1', language='en', production='auto')])
    base_cov = [
        dict(event_id=118340, aspect='witnesses', state='present', basis='appearance_records', count=2, reason=None),
        dict(event_id=118340, aspect='recording', state='unknown', basis='none', count=0, reason=None),
        dict(event_id=118340, aspect='captions', state='unknown', basis='videos.has_caption,recordings.tracks', count=0, reason='recording_link_pending'),
        dict(event_id=118340, aspect='transcript', state='not_stated', basis='meetings.transcripts', count=0, reason=None)]
    cand_cov = [
        dict(event_id=118340, aspect='witnesses', state='present', basis='appearance_records', count=2, reason=None),
        dict(event_id=118340, aspect='recording', state='present', basis='recording_matches', count=1, reason=None),
        dict(event_id=118340, aspect='captions', state='present', basis='videos.has_caption,recordings.tracks', count=1, reason=None),
        dict(event_id=118340, aspect='transcript', state='present', basis='meetings.transcripts', count=1, reason='captions')]
    return ({**base, 'meetings': pa.Table.from_pylist([bm], schema=m_schema),
             'recording_matches': pa.Table.from_pylist([publisher_match(999999, 'youtube:cap1', v_url)], schema=RECORDING_MATCHES),
             'recordings': pa.Table.from_pylist([dict(video_key='youtube:cap1', event_ids=[999999], tracks=track)], schema=RECORDINGS),
             'meeting_coverage': pa.Table.from_pylist(base_cov, schema=cov_schema)},
            {**cand, 'meetings': pa.Table.from_pylist([cm], schema=m_schema),
             'recording_matches': pa.Table.from_pylist([publisher_match(999999, 'youtube:cap1', v_url),
                                                        publisher_match(118340, 'youtube:cap1', v_url)], schema=RECORDING_MATCHES),
             'recordings': pa.Table.from_pylist([dict(video_key='youtube:cap1', event_ids=[118340, 999999], tracks=track)], schema=RECORDINGS),
             'meeting_coverage': pa.Table.from_pylist(cand_cov, schema=cov_schema)})


def related_bills_case(*, include_unrelated=False):
    rel_struct = pa.struct([('bill_id', pa.string()), ('title', pa.string()), ('relationship_types', pa.list_(pa.string()))])
    bill_schema = pa.schema([('bill_id', pa.string()), ('title', pa.string()), ('related_bills', pa.list_(rel_struct))])
    cand = edit(cand_tables(), 'meetings', lambda r: r[0].update(subject_keys=['119-s-5289']))
    cand_rows = [
        dict(bill_id='119-s-5289', title='Right to Worship Act',
             related_bills=[dict(bill_id='119-hr-1234', title='Companion Act', relationship_types=['Identical bill'])]),
        dict(bill_id='119-hr-1234', title='Companion Act', related_bills=[]),
        dict(bill_id='119-hr-5678', title='Related Act',
             related_bills=[dict(bill_id='119-s-5289', title='Right to Worship Act', relationship_types=['Related bill'])])]
    if include_unrelated:
        cand_rows.append(dict(bill_id='119-hr-9999', title='Unrelated Act', related_bills=[]))
    return ({**base_tables(), 'bills': pa.Table.from_pylist([], schema=bill_schema)},
            {**cand, 'bills': pa.Table.from_pylist(cand_rows, schema=bill_schema)})


def stated_event_video_resolved_case(*, non_updated=False):
    target = 338820 if non_updated else 118340
    key_input = json.dumps(['event', str(target), 'youtube:v9', 'video_states_event_id']).encode()
    mid = sha256(key_input).hexdigest()
    before = dict(match_id=mid, subject_kind='event', subject_id=str(target), event_id=None, package_id=None,
                  video_key='youtube:v9', url=None, basis='video_states_event_id', decision='linked', score=None,
                  recording_scope='unknown', status='claimed', note=f'stated event id {target} has no meeting',
                  source_ref='video_records:' + OTHER_BODY.hex(), meeting_links=[])
    after = dict(before, event_id=target, score=95, note=None,
                 meeting_links=[dict(event_id=target, basis='direct_event', scope='event')])
    if non_updated:
        base, _ = meeting_row(base_tables(), 338820, read=False)
        cand, _ = meeting_row(cand_tables(), 338820, read=False)
        return ({**base, 'recording_matches': pa.Table.from_pylist([before], schema=RECORDING_MATCHES)},
                {**cand, 'recording_matches': pa.Table.from_pylist([after], schema=RECORDING_MATCHES)})
    base, cand = first_stated()
    return ({**base, 'recording_matches': pa.Table.from_pylist([before], schema=RECORDING_MATCHES)},
            {**cand, 'recording_matches': pa.Table.from_pylist([after], schema=RECORDING_MATCHES)})


def coverage_moved_by_update_case(*, kind='all_valid'):
    cov_schema = pa.schema([('event_id', pa.int64()), ('aspect', pa.string()), ('state', pa.string()),
                            ('basis', pa.string()), ('count', pa.int32()), ('reason', pa.string())])
    base = base_tables(documents=(), videos=())
    base_cov = [
        dict(event_id=118340, aspect='witnesses', state='present', basis='appearance_records', count=2, reason=None),
        dict(event_id=118340, aspect='recording', state='unknown', basis='none', count=0, reason=None),
        dict(event_id=118340, aspect='captions', state='unknown', basis='videos.has_caption,recordings.tracks', count=0, reason='recording_link_pending'),
        dict(event_id=118340, aspect='transcript', state='not_stated', basis='meetings.transcripts', count=0, reason=None),
        dict(event_id=118340, aspect='documents', state='not_stated', basis='list.meeting_keys', count=0, reason=None)]
    if kind == 'present_transcript':
        cand = cand_tables(documents=(), videos=())
        cand_cov = [dict(r, state='present', count=1, reason='printed_hearing') if r['aspect'] == 'transcript' else dict(r) for r in base_cov]
    elif kind == 'confirmed_absent':
        cand = cand_tables(documents=(), videos=())
        cand_cov = [dict(r, state='confirmed_absent', basis='recording_decisions', reason=None) if r['aspect'] == 'recording'
                    else dict(r, state='not_stated', reason=None) if r['aspect'] == 'captions' else dict(r) for r in base_cov]
    else:
        cand = edit(cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3),
                                documents=('https://docs.house.gov/memo.pdf',)),
                    'meetings', lambda r: r[0].update(videos=[dict(name='v1', url='https://www.youtube.com/watch?v=v1', video_key='youtube:v1')]))
        cand_cov = [
            dict(event_id=118340, aspect='witnesses', state='present', basis='appearance_records', count=3, reason=None),
            dict(event_id=118340, aspect='recording', state='present', basis='recording_matches', count=1, reason=None),
            dict(event_id=118340, aspect='captions', state='unknown', basis='videos.has_caption,recordings.tracks', count=0, reason=None),
            dict(event_id=118340, aspect='transcript', state='unresolved', basis='meetings.transcripts', count=0, reason=None),
            dict(event_id=118340, aspect='documents', state='unresolved', basis='list.meeting_keys', count=0, reason='stated_documents_not_held')]
    return ({**base, 'meeting_coverage': pa.Table.from_pylist(base_cov, schema=cov_schema)},
            {**cand, 'meeting_coverage': pa.Table.from_pylist(cand_cov, schema=cov_schema)})


def rescheduled_url_state_case(*, kind='valid'):
    old_date, new_date = datetime(2026, 9, 25).date(), datetime(2026, 10, 25).date()
    doc_url = 'https://www.congress.gov/119/meeting/house/118340/documents/memo.pdf'
    other_url = 'https://www.govinfo.gov/unrelated-scheduled.pdf'
    base = base_tables(date=old_date, documents=(doc_url,), statuses=[('congress_gov', 'Scheduled', old_date, OLD_RECORD.hex(), FIRST_SEEN)])
    cand = cand_tables(date=new_date, documents=(doc_url,),
                       statuses=[('congress_gov', 'Scheduled', old_date, OLD_RECORD.hex(), FIRST_SEEN),
                                 ('congress_gov', 'Postponed', new_date, NEW_RECORD.hex(), SEEN_AGAIN)])
    base_rows = [state(MEETING_URL, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, 28 * DAY, old_date),
                 state(doc_url, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, 28 * DAY, old_date),
                 state(other_url, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, 28 * DAY, old_date)]
    meeting_cand_date = new_date + DAY if kind == 'wrong_date' else new_date
    doc_interval = 28 * DAY if kind == 'wrong_band' else 7 * DAY
    other_cand_date = new_date if kind == 'unrelated_url' else old_date
    cand_rows = [state(MEETING_URL, 2, SEEN_AGAIN, 200, 'stored', SEEN_AGAIN, 7 * DAY, meeting_cand_date),
                 state(doc_url, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, doc_interval, new_date),
                 state(other_url, 1, FIRST_SEEN, 200, 'stored', FIRST_SEEN, 28 * DAY, other_cand_date)]
    lines = [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN, family='congress/meetings'),
             capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN, family='congress/meetings'),
             capture_line(FIRST_READ, OTHER_BODY, FIRST_SEEN, url=doc_url, receipt_line=2, family='documents'),
             capture_line(FIRST_READ, SECOND_BODY, FIRST_SEEN, url=other_url, receipt_line=3, family='documents')]
    return ({**base, 'url_state': pa.Table.from_pylist(base_rows, schema=URL_STATE)},
            {**cand, 'url_state': pa.Table.from_pylist(cand_rows, schema=URL_STATE)}, lines)


def bill_named_by_the_update(*, on_other_meeting=False):
    bill_schema = pa.schema([('bill_id', pa.string()), ('title', pa.string())])
    bills = lambda ids: pa.Table.from_pylist([dict(bill_id=i, title='Right to Worship Act') for i in ids], schema=bill_schema)
    if on_other_meeting:
        base, _ = meeting_row(base_tables(), 999999, read=False)
        cand, _ = meeting_row(cand_tables(), 999999, read=False)
        cand = edit(cand, 'meetings', lambda r: r[1].update(subject_keys=['119-s-5289']))
        return {**base, 'bills': bills([])}, {**cand, 'bills': bills(['119-s-5289'])}
    cand = edit(cand_tables(), 'meetings', lambda r: r[0].update(subject_keys=['119-s-5289']))
    return {**base_tables(), 'bills': bills([])}, {**cand, 'bills': bills(['119-s-5289'])}


def rescheduled_twin_case(*, kind='update_points_to_twin'):
    if kind == 'update_points_to_twin':
        base, _ = meeting_row(base_tables(), 118341, read=False)
        twin = base['meetings'].to_pylist()[1]
        cand = cand_tables(status='Postponed', rescheduled=(118341, 'publisher_status'))
        return base, {**cand, 'meetings': pa.Table.from_pylist([*cand['meetings'].to_pylist(), twin], schema=MEETINGS)}
    if kind == 'unchanged_points_to_first_stated':
        old_m = base_tables(status='Postponed')['meetings'].to_pylist()[0]
        old_m.update(event_id=118300, publisher_status_observations=[])
        old_m['congress_gov_detail_observation'] = dict(old_m['congress_gov_detail_observation'], state='unknown',
                                                        successful_read=None, latest_attempt=dict(old_m['congress_gov_detail_observation']['latest_attempt'], evidence=None))
        base_f, cand_f = first_stated()
        base = {**base_f, 'meetings': pa.Table.from_pylist([old_m], schema=MEETINGS)}
        cand_rows = [*cand_f['meetings'].to_pylist(), dict(old_m, rescheduled_to=118340, rescheduled_basis='publisher_status')]
        return base, {**cand_f, 'meetings': pa.Table.from_pylist(cand_rows, schema=MEETINGS)}
    base, _ = meeting_row(base_tables(), 118300, read=False)
    base, _ = meeting_row(base, 118301, read=False)
    cand, _ = meeting_row(cand_tables(), 118300, read=False)
    cand, _ = meeting_row(cand, 118301, read=False)
    cand = edit(cand, 'meetings', lambda r: r[1].update(rescheduled_to=118301, rescheduled_basis='publisher_status'))
    return base, cand


def held_document_update_case(kind='date_title_meta_and_reorder'):
    """Held one-to-one documents whose meeting-derived metadata and list_row order move on an update."""
    comm_type = pa.list_(pa.struct([('system_code', pa.string()), ('role', pa.string())]))
    def with_meta(m_table, rows_meta):
        t = m_table
        t = t.append_column('chamber', pa.array([m['chamber'] for m in rows_meta], pa.string()))
        t = t.append_column('congress', pa.array([m['congress'] for m in rows_meta], pa.int16()))
        t = t.append_column('committees', pa.array([m['committees'] for m in rows_meta], comm_type))
        return t

    list_schema = pa.schema([
        ('filename', pa.string()), ('title', pa.string()), ('committee_keys', pa.list_(pa.string())),
        ('chambers', pa.list_(pa.string())), ('congress', pa.int16()), ('document_date', pa.date32()),
        ('meeting_keys', pa.list_(pa.string())), ('witness_keys', pa.list_(pa.string()))])
    detail_schema = pa.schema([
        ('link_key', pa.binary(8)), ('saved_body', pa.binary(32)), ('document_date_source', pa.string()),
        ('document_date_status', pa.string()), ('title_source', pa.string()),
        *list_schema])

    def doc_tables(rows):
        list_rows = [{f.name: r[f.name] for f in list_schema} for r in rows]
        detail_rows = [dict(link_key=K(r['key']), saved_body=K(r['key']) + bytes(24),
                            document_date_source=r['document_date_source'],
                            document_date_status=r['document_date_status'],
                            title_source=r.get('title_source',
                                               None if r['title'] is None
                                               else ('page_title' if kind == 'non_generic_title' else 'label_witness')),
                            **{f.name: r[f.name] for f in list_schema}) for r in rows]
        urls = pa.table({'lookup_key': pa.array([K(r['key'].lower()) for r in rows], pa.binary(8)),
                         'list_row': pa.array(list(range(len(rows))), pa.int32())})
        sources = pa.table({'list_row': pa.array(list(range(len(rows))), pa.int32()),
                            'url': pa.array([f"https://docs.house.gov/{r['key']}.pdf" for r in rows], pa.string()),
                            'member_path': pa.array([None] * len(rows), pa.string())})
        return dict(list=pa.Table.from_pylist(list_rows, schema=list_schema),
                    detail=pa.Table.from_pylist(detail_rows, schema=detail_schema),
                    urls=urls, sources=sources, url_state=url_states(REQUEST, 1).slice(0, 0))

    if kind in {'matched_meeting_links_witness_doc', 'wrong_title_source'}:
        base = base_tables()
        cand = cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3))
        base['meetings'] = with_meta(base['meetings'], [dict(chamber='house', congress=119,
                                                             committees=[dict(system_code='hsag00', role='primary')])])
        cand['meetings'] = with_meta(cand['meetings'], [dict(chamber='house', congress=119,
                                                             committees=[dict(system_code='hsag00', role='primary')])])
        b_doc = dict(key='A', filename='statement.pdf', title=None, title_source=None, committee_keys=[], chambers=[],
                     congress=None, document_date=None, document_date_source=None, document_date_status=None,
                     meeting_keys=[], witness_keys=[])
        c_doc = dict(key='A', filename='statement.pdf', title='Witness Statement - Cy Diaz',
                     title_source='override' if kind == 'wrong_title_source' else 'label_witness',
                     committee_keys=['hsag00'], chambers=['house'], congress=119, document_date=HEARD,
                     document_date_source='meeting', document_date_status='accepted', meeting_keys=['118340'],
                     witness_keys=['n3'])
        return {**base, **doc_tables([b_doc])}, {**cand, **doc_tables([c_doc])}

    moved_date = HEARD + timedelta(days=7)
    mid_date = HEARD + timedelta(days=3)
    base, _ = meeting_row(base_tables(), 999999, read=False)
    base = edit(base, 'meetings', lambda r: r[1].update(meeting_date=mid_date))
    untouched = base['meetings'].to_pylist()[1]
    cand = cand_tables(date=moved_date, panel=(('Anna Lee', 'GAO'), PANEL[1]),
                       mapped=[('k1', 'n1', 'locator'), ('w1', 'n1', 'locator'),
                               ('w2', 'n2', 'content'), ('v1', 'n1', 'locator')],
                       statuses=[LIVE_STATUS, ('congress_gov', 'Scheduled', moved_date, NEW_RECORD.hex(), SEEN_AGAIN)])
    cand = {**cand, 'meetings': pa.Table.from_pylist([*cand['meetings'].to_pylist(), untouched], schema=MEETINGS)}
    b_meta = [dict(chamber='house', congress=118, committees=[dict(system_code='hsag00', role='primary')]),
              dict(chamber='senate', congress=119, committees=[dict(system_code='ssfi00', role='primary')])]
    c_comms = ([dict(system_code='hsag00', role='primary')] if kind == 'unrelated_committee'
               else [dict(system_code='hsag00', role='primary'), dict(system_code='hsif00', role='subcommittee')])
    c_meta = [dict(chamber='joint', congress=119, committees=c_comms),
              dict(chamber='senate', congress=119, committees=[dict(system_code='ssfi00', role='primary')])]
    base['meetings'] = with_meta(base['meetings'], b_meta)
    cand['meetings'] = with_meta(cand['meetings'], c_meta)

    a_base = dict(key='A', filename='testimony.pdf',
                  title='Oversight Report - Ann Lee' if kind == 'non_generic_title' else 'Testimony - Ann Lee',
                  committee_keys=['hsag00'], chambers=['house'], congress=118, document_date=HEARD,
                  document_date_source='filename' if kind == 'filename_date' else 'meeting',
                  document_date_status='accepted', meeting_keys=['118340'], witness_keys=['w1'])
    a_cand = dict(key='A', filename='testimony.pdf',
                  title='Oversight Report - Anna Lee' if kind == 'non_generic_title' else 'Testimony - Anna Lee',
                  committee_keys=['hsag00', 'ssfi00'] if kind == 'unrelated_committee' else ['hsag00', 'hsif00'],
                  chambers=['joint'], congress=119, document_date=moved_date,
                  document_date_source='filename' if kind == 'filename_date' else 'meeting',
                  document_date_status='accepted', meeting_keys=['118340'], witness_keys=['n1'])
    b_row = dict(key='B', filename='testimony.pdf', title='Prepared Statement - Pat Roe',
                 committee_keys=['ssfi00'], chambers=['senate'], congress=119, document_date=mid_date,
                 document_date_source='meeting', document_date_status='accepted', meeting_keys=['999999'], witness_keys=[])
    if kind == 'title_only_reorder':
        base, _ = meeting_row(base_tables(panel=(('Zachary Lee', 'GAO'), PANEL[1])), 999999, read=False)
        untouched = base['meetings'].to_pylist()[1]
        cand = cand_tables(panel=(('Anna Lee', 'GAO'), PANEL[1]),
                           mapped=[('k1', 'n1', 'locator'), ('w1', 'n1', 'locator'),
                                   ('w2', 'n2', 'content'), ('v1', 'n1', 'locator')])
        cand = {**cand, 'meetings': pa.Table.from_pylist([*cand['meetings'].to_pylist(), untouched], schema=MEETINGS)}
        meta = [dict(chamber='house', congress=119, committees=[dict(system_code='hsag00', role='primary')]),
                dict(chamber='senate', congress=119, committees=[dict(system_code='ssfi00', role='primary')])]
        base['meetings'] = with_meta(base['meetings'], meta)
        cand['meetings'] = with_meta(cand['meetings'], meta)
        a_b = dict(key='A', filename='testimony.pdf', title='Testimony - Zachary Lee',
                   committee_keys=['hsag00'], chambers=['house'], congress=119, document_date=HEARD,
                   document_date_source='meeting', document_date_status='accepted', meeting_keys=['118340'], witness_keys=['w1'])
        a_c = dict(a_b, title='Testimony - Anna Lee', witness_keys=['n1'])
        b_same = dict(key='B', filename='testimony.pdf', title='Testimony - Mid Person',
                      committee_keys=['ssfi00'], chambers=['senate'], congress=119, document_date=HEARD,
                      document_date_source='meeting', document_date_status='accepted', meeting_keys=['999999'], witness_keys=[])
        return ({**base, **doc_tables([b_same, a_b])},
                {**cand, **doc_tables([a_c, b_same])},
                None, (), (['B', 'A'], ['A', 'B']))
    if kind == 'unexplained_swap':
        c_row = dict(b_row, key='C', document_date=HEARD + timedelta(days=20))
        a_early_b = dict(a_base, document_date=HEARD - timedelta(days=20))
        a_early_c = dict(a_cand, document_date=HEARD - timedelta(days=19))
        base = edit(base, 'meetings', lambda r: r[0].update(meeting_date=HEARD - timedelta(days=20)))
        cand = edit(cand, 'meetings', lambda r: r[0].update(meeting_date=HEARD - timedelta(days=19)))
        return ({**base, **doc_tables([a_early_b, b_row, c_row])},
                {**cand, **doc_tables([a_early_c, c_row, b_row])},
                None, (), (['A', 'B', 'C'], ['A', 'C', 'B']))
    return ({**base, **doc_tables([a_base, b_row])},
            {**cand, **doc_tables([b_row, a_cand])},
            None, (), (['A', 'B'], ['B', 'A']))


def mods_beside(tables, body, keys, mapped=()):
    """`tables` plus MODS witnesses `keys` on meeting 118340 from `body`, and MODS map rows `mapped` (old, new)."""
    out = edit(tables, 'witnesses', lambda rows: rows.extend(other_witness(k, 'mods', body, i + 1, *PANEL[i % 2]) for i, k in enumerate(keys)))
    return edit(out, 'witness_key_map', lambda rows: rows.extend(dict(old_key=o, witness_key=n, status='unambiguous', basis='content', candidate_keys=[],
                                                                     occasion='meeting:118340', source='mods') for o, n in mapped))


def second_meeting(tables, event, body, receipt, at, line, witnesses):
    """`tables` plus meeting `event` read from `body` at (`receipt`, `line`, `at`), with Congress.gov `witnesses` [(key, name, org)] (review R3b)."""
    meeting = tables['meetings'].to_pylist()[0]
    observation = meeting['congress_gov_detail_observation']
    reading = dict(observation['successful_read'], body_sha256=body.hex(), receipt_key=receipt, receipt_line=line, retrieved_at=at,
                   source_url=MEETING_URL.replace('118340', str(event)))
    copy = dict(meeting, event_id=event, publisher_status_observations=[],
                congress_gov_detail_observation=dict(observation, successful_read=reading, latest_attempt=dict(observation['latest_attempt'], evidence=reading)))
    rows = [dict(witness_key=k, occasion=f'meeting:{event}', source='congress_gov', record_sha=body, source_locator=f'congress_gov:witness[{i + 1}]',
                 context_key='congress/meetings', name=n, organization=o, panel='Panel I', panel_order=1, display_order=i + 1, superseded_by=None)
            for i, (k, n, o) in enumerate(witnesses)]
    return edit({**tables, 'meetings': pa.Table.from_pylist([meeting, copy], schema=tables['meetings'].schema)}, 'witnesses', lambda r: r.extend(rows))


def successor_on_another_updated_meeting(historical=False):
    """Review R3b: Bo Park's key w2 (or historical key k1) re-keyed onto meeting 118341, both meetings read again with new bytes."""
    old, new = bytes.fromhex('b1' * 32), bytes.fromhex('b2' * 32)
    base = second_meeting(base_tables(), 118341, old, FIRST_READ, FIRST_SEEN, 2, [('y1', 'Cy Diaz', 'EPA')])
    rekeyed = (dict(mapped=[('k1', 'bn9', 'content'), *NEW_MAP[1:], ('y1', 'y2', 'content')]) if historical
               else dict(keys=('n1',), panel=PANEL[:1], order=(1,), mapped=[('k1', 'n1', 'content'), ('w1', 'n1', 'content'),
                                                                            ('w2', 'bn9', 'content'), ('y1', 'y2', 'content')]))
    candidate = second_meeting(cand_tables(**rekeyed),
                               118341, new, RELIST, SEEN_AGAIN, 2, [('y2', 'Cy Diaz', 'EPA'), ('bn9', *PANEL[1])])
    other = MEETING_URL.replace('118340', '118341')
    return base, candidate, [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
                             capture_line(RELIST, new, SEEN_AGAIN, url=other, receipt_line=2), capture_line(FIRST_READ, old, FIRST_SEEN, url=other, receipt_line=2)]


# One case per clause of the re-fetch rule (release_comparison.updated_meetings, updated_witnesses,
# refetched_meetings, nominations; release_gate.cited_files_are_new), many from the 2026-11-11
# reviews (R1-R12: the ct-rhqw review). Each builds (base, candidate[, capture lines[, cache files[, documents]]])
# and names the outcome: True passes unattended; a string must appear among the gate's reasons. Under
# the owner's ct-rhqw decision a Congress.gov update publishes whatever its record changed; it stops
# on a lost key (a witness key the map does not resolve to one witness: until "no longer listed"
# lands), on anything another source or another meeting moved, and on any re-fetch the capture
# table does not prove.
PERSON_MAP = [('k1', 'n2', 'content'), ('w1', 'n2', 'content'), ('w2', 'n1', 'content'), ('v1', 'n2', 'content')]
REKEY_STOPS = 'witnesses.parquet|removed keys|re-keyed: witness_key_map names the published successor ('
UNRESOLVED_STOPS = 'witnesses.parquet|removed keys|witness_key_map states the key unresolved'
NOT_A_BODY = f'cited file {NEW_RECORD.hex()[:16]} is not a body in the capture table'
CY = ('Cy Diaz', 'EPA')
HOUSE_LIST = lambda organization: other_witness('x1', 'house_xml', OTHER_BODY, 9, 'Di Fox', organization)
HOUSE_SEEN, HOUSE_SEEN_AGAIN = ('house_xml', 'Scheduled', HEARD, 'e1' * 32, FIRST_SEEN), ('house_xml', 'Canceled', HEARD, 'e2' * 32, SEEN_AGAIN)
SEEN_IN_THE_NEW_BODY = ('congress_gov', 'Scheduled', HEARD, NEW_RECORD.hex(), SEEN_AGAIN)
DROPPED = lambda status, **row: edit(cand_tables(keys=('n1',), panel=PANEL[:1], order=(1,), mapped=NEW_MAP[:2]), 'witness_key_map',
                                     lambda rows: rows.append(dict(UNRESOLVED, status=status, **row)))
MODS_ELSEWHERE = dict(other_witness('m1', 'mods', MODS_OLD, 1, *PANEL[0]), occasion='meeting:777')
TO_MODS_ELSEWHERE = dict(old_key='q1', witness_key='m1', status='unambiguous', basis='content', candidate_keys=[], occasion='meeting:777', source='mods')
CASES = {
    # Pass: what a Congress.gov update may change (ct-rhqw), and the clean re-keys before it (ct-uywf).
    'map_follows_the_person_in_a_new_order': (lambda: (base_tables(), cand_tables(panel=(PANEL[1], PANEL[0]), mapped=PERSON_MAP)), True),
    'display_order_moved_locator_kept': (lambda: (base_tables(), edit(cand_tables(order=(2, 1)), 'witnesses', locators(1, 2))), True),
    'locator_moved_display_order_kept': (lambda: (base_tables(), edit(cand_tables(), 'witnesses', locators(2, 1))), True),
    'two_identical_rows_reordered': (lambda: (base_tables(panel=(PANEL[0], PANEL[0])), cand_tables(panel=(PANEL[0], PANEL[0]), order=(2, 1))), True),
    # D2: documents naming re-keyed witnesses (78 rows in each document file on 2026-11-10's pair).
    'documents_name_the_re_keyed_witnesses': (lambda: ({**base_tables(), **documents(('w1', 'w2'))},
                                                       {**cand_tables(), **documents(('n1', 'n2'))}), True),
    'a_document_names_a_new_witness': (lambda: ({**base_tables(), **documents(('w1',))},
                                                {**cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), **documents(('n1', 'n3'))}), True),
    'video_refresh_beside_a_re_key': (lambda: ({**base_tables(), **video_tables('fetch-1', 1)}, {**cand_tables(), **video_tables('fetch-2', 8)},
                                               None, [(cache_file('fetch-2'), CACHE_RECEIPT)]), True),
    # The map's locator tier pairs an edited given name at the same place (witness-key-map.sql).
    'name_edited_in_place': (lambda: (base_tables(), cand_tables(panel=(PANEL[0], ('Bob Park', 'CBO')),
                                                                 mapped=[('k1', 'n1', 'content'), ('w1', 'n1', 'content'), ('w2', 'n2', 'locator')])), True),
    'superseded_by_set_under_a_new_order': (lambda: (base_tables(), edit(cand_tables(order=(2, 1)), 'witnesses',
                                                                         lambda rows: rows[0].update(superseded_by='n2'))), True),
    'a_witness_added': (lambda: (base_tables(), cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3))), True),
    'two_old_bodies_one_new': (lambda: (edit(base_tables(), 'witnesses', lambda rows: rows[1].update(record_sha=OTHER_BODY)), cand_tables()), True),
    'title_date_status_documents_videos_and_sitting_changed': (lambda: (base_tables(), cand_tables(title='Renamed', date=HEARD + timedelta(days=1),
                                                                                                status='Canceled', documents=('agenda',), videos=('v9',),
                                                                                                rooms=[(TEN, 'SD-406')])), True),
    'status_postponed': (lambda: (base_tables(), cand_tables(statuses=[LIVE_STATUS, ('congress_gov', 'Postponed', HEARD, NEW_RECORD.hex(), SEEN_AGAIN)])), True),
    'postponed_and_moved_a_fortnight': (lambda: (base_tables(), cand_tables(status='Postponed', date=HEARD + timedelta(days=14),
                                                                            statuses=[LIVE_STATUS, ('congress_gov', 'Postponed', HEARD + timedelta(days=14),
                                                                                                    NEW_RECORD.hex(), SEEN_AGAIN)])), True),
    'live_status_dropped': (lambda: (base_tables(), cand_tables(statuses=[SEEN_IN_THE_NEW_BODY])), True),
    'latest_attempt_failed': (lambda: (base_tables(), edit(cand_tables(), 'meetings', lambda rows: rows[0]['congress_gov_detail_observation']['latest_attempt'].update(state='failed'))), True),
    'update_stamp_moved_back': (lambda: (base_tables(), cand_tables(updated=datetime(2025, 12, 1, tzinfo=timezone.utc))), True),
    'canceled_by_the_publisher': (lambda: (base_tables(), cand_tables(status='Canceled', held=('canceled', 'publisher_cancellation', NEW_RECORD.hex()))), True),
    'uncanceled_by_the_publisher': (lambda: (
        base_tables(status='Canceled', held=('canceled', 'publisher_cancellation', OLD_RECORD.hex()),
                    statuses=[('congress_gov', 'Canceled', HEARD, OLD_RECORD.hex(), FIRST_SEEN)]),
        cand_tables(status='Scheduled', held=('unknown', 'no_outcome_evidence', None),
                    statuses=[('congress_gov', 'Canceled', HEARD, OLD_RECORD.hex(), FIRST_SEEN), SEEN_IN_THE_NEW_BODY])), True),
    'first_stated_meeting_with_its_witnesses': (first_stated, True),
    'witness_coverage_counts_a_new_witness': (lambda: ({**base_tables(), 'meeting_coverage': coverage(2)},
                                                      {**cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), 'meeting_coverage': coverage(3)}), True),
    'a_nomination_the_update_newly_names': (lambda: nomination_named_by_the_update('119-pn-1022-19'), True),
    'a_bill_the_update_newly_names': (bill_named_by_the_update, True),
    'related_bill_pulled_in_by_updated_meeting_subject': (related_bills_case, True),
    'publisher_video_matches_added_and_removed_on_an_update': (publisher_video_matches_case, True),
    'first_stated_meeting_with_publisher_video_matches': (lambda: publisher_video_matches_case(first=True), True),
    'updated_meeting_links_existing_captioned_recording': (captioned_recording_linked_case, True),
    'first_stated_meeting_resolves_video_states_event_id_match': (stated_event_video_resolved_case, True),
    'senate_page_witness_superseded_by_updated_congress_gov_witness': (lambda: (
        edit(base_tables(), 'witnesses', lambda r: r.append(other_witness('sp1', 'senate_page', OTHER_BODY, 1, *CY))),
        edit(cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), 'witnesses',
             lambda r: r.append(dict(other_witness('sp1', 'senate_page', OTHER_BODY, 1, *CY), superseded_by='n3')))), True),
    'recording_captions_transcript_and_documents_coverage_moved_by_an_update': (coverage_moved_by_update_case, True),
    'rescheduled_meeting_moves_recheck_dates_and_bands': (rescheduled_url_state_case, True),
    'postponed_update_points_to_later_twin': (rescheduled_twin_case, True),
    'unchanged_postponed_meeting_gains_first_stated_twin': (lambda: rescheduled_twin_case(kind='unchanged_points_to_first_stated'), True),
    'held_documents_follow_updated_meeting_date_title_meta_and_reorder': (held_document_update_case, True),
    'held_document_title_only_reorder_passes': (lambda: held_document_update_case(kind='title_only_reorder'), True),
    'matched_updated_meeting_links_held_witness_document': (lambda: held_document_update_case(kind='matched_meeting_links_witness_doc'), True),
    'house_xml_unchanged_recheck_beside_an_update': (lambda: (
        base_tables(), cand_tables(),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(FIRST_READ, OTHER_BODY, FIRST_SEEN, url=HOUSE_MEETING_XML, receipt_line=2), family='house/meeting-xml'),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN, url=HOUSE_MEETING_XML, receipt_line=2), family='house/meeting-xml', outcome='unchanged')]), True),
    'house_xml_for_another_meeting_captured_beside_an_update': (lambda: (
        base_tables(), cand_tables(),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN, url=HOUSE_MEETING_XML.replace('118340', '999999'), receipt_line=2), family='house/meeting-xml')]), True),
    'read_dated_a_minute_ago': (lambda: (base_tables(), cand_tables(at=(t := datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=1))),
                                         [capture_line(RELIST, NEW_RECORD, t), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), True),

    # Lost keys stop, whatever the record says (owner, 2026-11-11, until "no longer listed" lands).
    'a_link_key_lost': (lambda: (base_tables(), cand_tables(), None, (), (['A', 'B'], ['A'])), 'link rule: 1 base link keys vanish'),
    'a_witness_dropped_with_no_map_row': (lambda: (base_tables(), cand_tables(keys=('n1',), panel=PANEL[:1], order=(1,), mapped=NEW_MAP[:2])),
                                          'witnesses.parquet|removed keys|no evidence given'),
    'a_witness_dropped_the_map_states_unresolved': (lambda: (base_tables(), DROPPED('unresolved')), UNRESOLVED_STOPS),
    'a_witness_dropped_the_map_names_candidates': (lambda: (base_tables(), DROPPED('ambiguous', candidate_keys=['n1'])),
                                                   'witnesses.parquet|removed keys|witness_key_map states the key ambiguous'),
    # The map the model writes for an edit its tiers cannot pair (witness-key-map.sql: unresolved): reviews R8a, R8b.
    'organization_edited_the_map_states_unresolved': (lambda: (base_tables(), edit(cand_tables(panel=(PANEL[0], ('Bo Park', 'EPA')), mapped=NEW_MAP[:2]),
                                                                                   'witness_key_map', lambda rows: rows.append(dict(UNRESOLVED)))), UNRESOLVED_STOPS),
    'panel_moved_the_map_states_unresolved': (lambda: (base_tables(), edit(cand_tables(panels=[('Panel I', 1), ('Panel II', 2)], mapped=NEW_MAP[:2]),
                                                                           'witness_key_map', lambda rows: rows.append(dict(UNRESOLVED)))), UNRESOLVED_STOPS),
    'name_edited_under_a_new_order_the_map_states_unresolved': (lambda: (base_tables(), edit(cand_tables(order=(2, 1), panel=(PANEL[0], ('Bo Parks', 'CBO')),
                                                                                                         mapped=NEW_MAP[:2]),
                                                                                             'witness_key_map', lambda rows: rows.append(dict(UNRESOLVED)))), UNRESOLVED_STOPS),
    'record_drops_every_witness': (lambda: ({**base_tables(), **documents(('w1', 'w2'))},
                                            {**edit(cand_tables(keys=(), panel=(), order=(), mapped=[]), 'witness_key_map',
                                                    lambda rows: rows.extend(dict(UNRESOLVED, old_key=k) for k in ('k1', 'w1', 'w2'))), **documents(())}),
                                   UNRESOLVED_STOPS),
    'unresolved_row_for_a_key_never_listed': (lambda: (base_tables(), edit(cand_tables(), 'witness_key_map', lambda rows: rows.append(dict(UNRESOLVED, old_key='zz')))),
                                              'witness_key_map.parquet|added keys|a key no base witness carries (1) is not an addition'),
    'new_order_beside_a_dropped_witness': (lambda: (base_tables(keys=('w1', 'w2', 'w3'), panel=(*PANEL, CY), order=(1, 2, 3)),
                                                    cand_tables(order=(2, 1))), 'witnesses.parquet|removed keys|no evidence given'),
    'dropped_witness_key_sent_to_another': (lambda: (base_tables(keys=('w1', 'w2', 'w3'), panel=(*PANEL, CY), order=(1, 2, 3)),
                                                     cand_tables(order=(2, 1), mapped=NEW_MAP + [('w3', 'n1', 'content')])), 'collapses distinct base occurrences'),
    'two_old_keys_one_successor': (lambda: (base_tables(), cand_tables(mapped=[('k1', 'n1', 'content'), ('w1', 'n1', 'content'),
                                                                               ('w2', 'n1', 'content'), ('v1', 'n1', 'content')])), 'collapses distinct base occurrences'),
    'successor_collides_with_a_base_map_row': (lambda: (base_tables(), cand_tables(mapped=[('k1', 'n1', 'content'), ('w1', 'n2', 'content'),
                                                                                           ('w2', 'n1', 'content')])), 'collapses distinct base occurrences'),
    'map_names_an_unpublished_successor': (lambda: (base_tables(), cand_tables(mapped=NEW_MAP[:2] + [('w2', 'gone', 'content')])),
                                           'witnesses.parquet|removed keys|unexplained'),
    'historical_key_names_an_unpublished_successor': (lambda: (base_tables(), cand_tables(mapped=[('k1', 'gone', 'content'), *NEW_MAP[1:]])),
                                                      'witness_key_map.parquet|changed witness_key'),
    'historical_key_successor_on_another_meeting': (lambda: successor_on_another_updated_meeting(historical=True),
                                                    'witness_key_map.parquet|changed witness_key'),

    # Another source, another meeting, or a column another source moves: not this update.
    'house_list_witness_edited': (lambda: (edit(base_tables(), 'witnesses', lambda rows: rows.append(HOUSE_LIST('NSF'))),
                                           edit(cand_tables(), 'witnesses', lambda rows: rows.append(HOUSE_LIST('NIH')))), 'witnesses.parquet|changed organization'),
    'house_list_witness_added_on_an_update': (lambda: (base_tables(), edit(cand_tables(), 'witnesses',
                                                                            lambda rows: rows.append(other_witness('x1', 'house_xml', NEW_RECORD, 9, 'Di Fox', 'NSF')))),
                                              'witnesses.parquet|added keys|no evidence given'),
    # R1a, R1b: a House read beside the update may move what the House record leads; its sightings must stay.
    'house_read_moves_the_title_stamp_kept': (lambda: (base_tables(house_xml='2026-01-01', statuses=[LIVE_STATUS, HOUSE_SEEN]),
                                                       cand_tables(house_xml='2026-01-01', title='Renamed by the House',
                                                                   statuses=[LIVE_STATUS, SEEN_IN_THE_NEW_BODY, HOUSE_SEEN_AGAIN])), 'meetings.parquet|changed title'),
    'house_cancellation_stamp_kept': (lambda: (base_tables(house_xml='2026-01-01', statuses=[LIVE_STATUS, HOUSE_SEEN]),
                                               cand_tables(house_xml='2026-01-01', held=('canceled', 'publisher_cancellation', 'e2' * 32),
                                                           statuses=[LIVE_STATUS, SEEN_IN_THE_NEW_BODY, HOUSE_SEEN_AGAIN])), 'meetings.parquet|changed outcome'),
    'house_xml_stamp_moved_on_an_update': (lambda: (base_tables(), cand_tables(title='Renamed', house_xml='2026-11-08')), 'meetings.parquet|changed house_xml_updated'),
    'house_xml_null_status_captured_on_an_update': (lambda: (
        base_tables(), cand_tables(title='Renamed by House XML'),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN, url=HOUSE_MEETING_XML, receipt_line=2), family='house/meeting-xml')]),
        'new House XML body'),
    'house_xml_eventless_url_captured_on_an_update': (lambda: (
        base_tables(), cand_tables(title='Renamed by House XML'),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN,
                           url='https://docs.house.gov/meetings/AS/AS00/20250612/HHRG-119-AS00-20250612.xml', receipt_line=2),
              family='house/meeting-xml')]),
        'new House XML body'),
    'house_xml_numeric_filename_captured_on_an_update': (lambda: (
        base_tables(), cand_tables(title='Renamed by House XML'),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN,
                           url='https://docs.house.gov/meetings/AS/AS00/20250612/118340/20250612.xml', receipt_line=2),
              family='house/meeting-xml')]),
        'new House XML body'),
    'house_xml_sniffed_without_extension_captured_on_an_update': (lambda: (
        base_tables(), cand_tables(title='Renamed by House XML'),
        [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
         dict(capture_line(RELIST, OTHER_BODY, SEEN_AGAIN,
                           url='https://docs.house.gov/meetings/AS/AS00/20250612/118340/feed', receipt_line=2),
              family='documents', sniffed_format='xml')]),
        'new House XML body'),
    'first_stated_meeting_with_house_xml_stamp': (lambda: (first_stated()[0], cand_tables(mapped=[], house_xml='2026-11-08')),
                                                  'meetings.parquet|added keys|unexplained'),
    'first_stated_meeting_with_house_xml_status': (lambda: (first_stated()[0], cand_tables(mapped=[], statuses=[SEEN_IN_THE_NEW_BODY, HOUSE_SEEN_AGAIN])),
                                                   'meetings.parquet|added keys|unexplained'),
    'new_single_meeting_document_injects_a_nomination_on_an_update': (document_injects_subject_beside_update, 'meetings.parquet|changed subject_keys'),
    'new_first_stated_meeting_with_document_measure_keys': (lambda: document_injects_subject_beside_update(first=True), 'meetings.parquet|added keys|unexplained'),
    'held_by_a_transcript_on_an_update': (lambda: (base_tables(), cand_tables(held=('held', 'committee_transcript', '256383'))), 'meetings.parquet|changed outcome'),
    # C3: a live outcome from a transcript is not the publisher's to undo.
    'canceled_where_a_transcript_held_it': (lambda: (base_tables(held=('held', 'committee_transcript', '256383')),
                                                     cand_tables(status='Canceled', held=('canceled', 'publisher_cancellation', NEW_RECORD.hex()))),
                                            'meetings.parquet|changed outcome'),
    'mods_print_re_fetched': (lambda: mods(), 'witnesses.parquet|removed keys|re-keyed'),
    'mods_print_re_fetched_in_a_new_order': (lambda: mods(reordered=True), 'witnesses.parquet|changed display_order'),
    'surviving_key_mapped_to_a_duplicate': (lambda: (
        edit(base_tables(), 'witnesses', lambda rows: rows.append(other_witness('h1', 'house_xml', OTHER_BODY, 1, *PANEL[0]))),
        edit(cand_tables(mapped=NEW_MAP + [('h1', 'd1', 'content')]), 'witnesses', lambda rows: rows.extend([
            other_witness('h1', 'house_xml', OTHER_BODY, 1, *PANEL[0]), other_witness('d1', 'house_xml', NEW_RECORD, 1, *PANEL[0])]))),
        'witnesses.parquet|added keys|successor of a re-keyed witness (1) is not an addition'),
    'map_row_added_for_a_witness_the_night_left_alone': (lambda: (
        edit(base_tables(), 'witnesses', lambda rows: rows.append(other_witness('h1', 'house_xml', OTHER_BODY, 1, *PANEL[0]))),
        edit(edit(cand_tables(), 'witnesses', lambda rows: rows.append(other_witness('h1', 'house_xml', OTHER_BODY, 1, *PANEL[0]))),
             'witness_key_map', lambda rows: rows.append(dict(old_key='z9', witness_key='h1', status='unambiguous', basis='content',
                                                              candidate_keys=[], occasion='meeting:118340', source='house_xml')))),
        'witness_key_map.parquet|added keys|a key no base witness carries (1) is not an addition'),
    # W4: a live MODS witness mapped (by a row that claims Congress.gov) onto the update's new witness.
    'live_mods_witness_mapped_onto_the_update': (lambda: (
        edit(base_tables(), 'witnesses', lambda rows: rows.append(other_witness('m1', 'mods', MODS_OLD, 3, *CY))),
        edit(cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), 'witness_key_map', lambda rows: rows.append(
            dict(old_key='m1', witness_key='n3', status='unambiguous', basis='content', candidate_keys=[], occasion='meeting:118340', source='congress_gov')))),
        REKEY_STOPS),
    # R7b: a live MODS key of another meeting relabelled onto the update; R7c: the same row kept on its meeting.
    'live_mods_key_relabelled_onto_the_update': (lambda: (
        edit(edit(base_tables(), 'witnesses', lambda rows: rows.append(dict(MODS_ELSEWHERE))), 'witness_key_map', lambda rows: rows.append(dict(TO_MODS_ELSEWHERE))),
        edit(edit(cand_tables(), 'witnesses', lambda rows: rows.append(dict(MODS_ELSEWHERE))), 'witness_key_map',
             lambda rows: rows.append(dict(TO_MODS_ELSEWHERE, occasion='meeting:118340', source='congress_gov', basis='locator')))),
        'witness_key_map.parquet|changed'),
    'live_mods_key_unresolved_on_its_meeting': (lambda: (
        edit(edit(base_tables(), 'witnesses', lambda rows: rows.append(dict(MODS_ELSEWHERE))), 'witness_key_map', lambda rows: rows.append(dict(TO_MODS_ELSEWHERE))),
        edit(edit(cand_tables(), 'witnesses', lambda rows: rows.append(dict(MODS_ELSEWHERE))), 'witness_key_map',
             lambda rows: rows.append(dict(UNRESOLVED, old_key='q1', occasion='meeting:777', source='mods')))), 'witness_key_map.parquet|changed'),
    # K2: a Congress.gov key of a meeting the night did not read.
    'map_row_of_a_meeting_not_read': (lambda: (
        edit(base_tables(), 'witness_key_map', lambda rows: rows.append(dict(TO_MODS_ELSEWHERE, old_key='z1', witness_key='w1', basis='occurrence',
                                                                                occasion='meeting:118341', source='congress_gov'))),
        edit(cand_tables(), 'witness_key_map', lambda rows: rows.append(dict(TO_MODS_ELSEWHERE, old_key='z1', witness_key='n1', basis='content',
                                                                                 occasion='meeting:118341', source='congress_gov')))),
        'witness_key_map.parquet|changed basis'),
    # R3a, R3b: a removed witness's successor on a meeting not read, or on another updated meeting.
    'successor_on_a_meeting_not_read': (lambda: (base_tables(), edit(cand_tables(), 'witnesses', lambda rows: rows[1].update(occasion='meeting:118341'))),
                                        'is not an addition'),
    'successor_on_another_updated_meeting': (successor_on_another_updated_meeting, 'witnesses.parquet|changed occasion'),
    'a_meeting_not_read_again_renamed': (lambda: (base_tables(), meeting_read(OLD_RECORD, FIRST_READ, FIRST_SEEN, keys=('w1', 'w2'), mapped=[('k1', 'w1', 'occurrence')],
                                                                              statuses=[LIVE_STATUS], title='Renamed'), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                                         'meetings.parquet|changed title'),
    # R12: the read that would prove the update is a read of another meeting's record.
    'read_is_another_meetings_record': (lambda: (base_tables(), edit(cand_tables(title='Renamed'), 'meetings', lambda rows: [
        r.update(source_url=r['source_url'].replace('118340', '999999')) for r in (rows[0]['congress_gov_detail_observation']['successful_read'],
                                                                                 rows[0]['congress_gov_detail_observation']['latest_attempt']['evidence'])]),
                                                 [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN, url=MEETING_URL.replace('118340', '999999')),
                                                  capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), 'meetings.parquet|changed title'),
    # F1 (338820's shape), F2: a meeting Congress.gov only lists, and coverage of an aspect the update does not move.
    'listed_only_meeting_beside_an_update': (listed_only_beside_an_update, 'meetings.parquet|added keys|unexplained'),
    'coverage_row_added_to_an_updated_meeting': (lambda: ({**base_tables(), 'meeting_coverage': coverage(2)},
                                                          {**cand_tables(), 'meeting_coverage': coverage(2, extra=[dict(event_id=118340, aspect='captions', state='unknown',
                                                                                                                         basis='videos.has_caption', count=0, reason=None)])}),
                                                 'meeting_coverage.parquet|added keys|no evidence given'),
    'documents_coverage_moved_on_an_update': (lambda: ({**base_tables(), 'meeting_coverage': coverage(2)}, {**cand_tables(), 'meeting_coverage': coverage(2, documents=2)}),
                                              'meeting_coverage.parquet|changed count'),
    'a_nomination_no_update_names': (lambda: nomination_named_by_the_update('119-pn-9999-1'), 'nominations.parquet|added keys|no evidence given'),
    'a_bill_a_non_updated_meeting_names_beside_an_update': (lambda: bill_named_by_the_update(on_other_meeting=True), 'bills.parquet|added bills|new meeting subject'),
    'unrelated_bill_added_with_no_subject_or_neighbor_link': (lambda: related_bills_case(include_unrelated=True), 'bills.parquet|added bills|unexplained'),
    'curated_recording_match_added_on_an_update': (lambda: publisher_video_matches_case(curated=True), 'recording_matches.parquet|added keys|no evidence given'),
    'publisher_video_match_on_non_updated_meeting_beside_an_update': (lambda: publisher_video_matches_case(non_updated_event=True), 'recording_matches.parquet|added keys|no evidence given'),
    'added_recording_carries_new_caption_tracks_on_an_update': (lambda: publisher_video_matches_case(extra_track=True), 'recordings.parquet|added keys'),
    'recording_event_ids_gains_non_updated_meeting_beside_update': (lambda: publisher_video_matches_case(bad_rec_event=True), 'recordings.parquet|changed event_ids'),
    'html_page_recording_added_on_an_update': (lambda: publisher_video_matches_case(html_page_recording=True), 'recordings.parquet|added keys'),
    'html_page_event_added_to_shared_recording_on_an_update': (lambda: publisher_video_matches_case(html_page_shared_event=True), 'recordings.parquet|changed event_ids'),
    'uncanceled_to_held_without_evidence_on_an_update': (lambda: (
        base_tables(status='Canceled', held=('canceled', 'publisher_cancellation', OLD_RECORD.hex()),
                    statuses=[('congress_gov', 'Canceled', HEARD, OLD_RECORD.hex(), FIRST_SEEN)]),
        cand_tables(status='Scheduled', held=('held', 'no_outcome_evidence', None),
                    statuses=[('congress_gov', 'Canceled', HEARD, OLD_RECORD.hex(), FIRST_SEEN), SEEN_IN_THE_NEW_BODY])),
        'meetings.parquet|changed outcome'),
    'first_stated_map_claims_a_live_witness': (lambda: (
        edit(first_stated()[0], 'witnesses', lambda r: r.append(dict(MODS_ELSEWHERE))),
        edit(edit(first_stated()[1], 'witnesses', lambda r: r.append(dict(MODS_ELSEWHERE))), 'witness_key_map',
             lambda r: r.append(dict(old_key='m1', witness_key='n1', status='unambiguous', basis='content',
                                     candidate_keys=[], occasion='meeting:118340', source='congress_gov')))),
        'witness_key_map.parquet|added keys'),
    'senate_page_witness_organization_edited_with_superseded_by': (lambda: (
        edit(base_tables(), 'witnesses', lambda r: r.append(other_witness('sp1', 'senate_page', OTHER_BODY, 1, 'Cy Diaz', 'GAO'))),
        edit(cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), 'witnesses',
             lambda r: r.append(dict(other_witness('sp1', 'senate_page', OTHER_BODY, 1, 'Cy Diaz', 'EPA'), superseded_by='n3')))),
        'witnesses.parquet|changed organization'),
    'video_states_event_id_resolves_for_non_updated_meeting_beside_update': (
        lambda: stated_event_video_resolved_case(non_updated=True), 'recording_matches.parquet|changed'),
    'transcript_coverage_present_on_an_update': (lambda: coverage_moved_by_update_case(kind='present_transcript'), 'meeting_coverage.parquet|changed state'),
    'curated_confirmed_absent_coverage_on_an_update': (lambda: coverage_moved_by_update_case(kind='confirmed_absent'), 'meeting_coverage.parquet|changed state'),
    'rescheduled_meeting_linked_url_wrong_band': (lambda: rescheduled_url_state_case(kind='wrong_band'), 'next_attempt_at is not last_attempt plus the band'),
    'rescheduled_meeting_unrelated_url_recheck_date_moved': (lambda: rescheduled_url_state_case(kind='unrelated_url'), 'changed with no new line'),
    'rescheduled_meeting_url_recheck_date_not_the_new_date': (lambda: rescheduled_url_state_case(kind='wrong_date'), 'recheck_meeting_date changed on an address'),
    'unrelated_meeting_rescheduled_to_changed_beside_an_update': (lambda: rescheduled_twin_case(kind='unrelated_pair'), 'meetings.parquet|changed rescheduled_to'),
    'held_document_non_generic_title_edited_on_an_update': (lambda: held_document_update_case(kind='non_generic_title'), 'changed title'),
    'held_document_wrong_title_source_on_an_update': (lambda: held_document_update_case(kind='wrong_title_source'), 'changed title_source'),
    'held_document_filename_date_moved_on_an_update': (lambda: held_document_update_case(kind='filename_date'), 'changed document_date'),
    'held_document_gains_unrelated_committee_on_an_update': (lambda: held_document_update_case(kind='unrelated_committee'), 'changed committee_keys'),
    'held_document_unexplained_row_swap_on_unchanged_pair_beside_update': (
        lambda: held_document_update_case(kind='unexplained_swap'), 'changed bytes, no key or value difference found'),
    # R4: a first stated meeting that claims an existing document.
    'first_stated_meeting_claims_an_existing_document': (lambda: ({**first_stated()[0], **document_names((), ())}, {**first_stated()[1], **document_names((), ('118340',))}),
                                                         'changed meeting_keys'),
    'document_of_another_meeting_gains_updated_witness': (lambda: (
        {**base_tables(), **document_names((), ('999999',))},
        {**cand_tables(keys=('n1', 'n2', 'n3'), panel=(*PANEL, CY), order=(1, 2, 3)), **document_names(('n3',), ('999999',))}),
        'list.parquet|changed witness_keys|value differs on matched key'),
    # D1: a document key the map moves that no update moved (here a stale key the live document listed).
    'document_lists_a_key_no_update_moved': (lambda: ({**base_tables(), **documents(('v1', 'w2'))}, {**cand_tables(), **documents(('n1', 'n2'))}),
                                             'list.parquet|changed witness_keys|re-keyed through witness_key_map (1) is not an addition'),
    # D3: a document that gains a witness of another source; R2a, R2b: and beside a MODS re-key.
    'document_gains_a_witness_of_another_source': (lambda: ({**edit(base_tables(), 'witnesses', lambda rows: rows.append(HOUSE_LIST('NSF'))), **documents(('w1',))},
                                                           {**edit(cand_tables(), 'witnesses', lambda rows: rows.append(HOUSE_LIST('NSF'))), **documents(('n1', 'x1'))}),
                                                   'list.parquet|changed witness_keys|value differs on matched key'),
    'document_moved_by_a_re_key_and_a_mods_re_key': (lambda: ({**mods_beside(base_tables(), MODS_OLD, ('m1',)), **documents(('w1', 'm1'))},
                                                              {**mods_beside(cand_tables(), MODS_NEW, ('m3',), [('m1', 'm3')]), **documents(('n1', 'm3'))},
                                                              [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
                                                               capture_line(MODS_RECEIPT, MODS_NEW, SEEN_AGAIN, url='https://www.govinfo.gov/mods')]),
                                                     'is not an addition'),
    'witness_body_is_not_its_meetings_read': (lambda: (base_tables(), edit(cand_tables(), 'witnesses', lambda rows: [r.update(record_sha=SECOND_BODY) for r in rows]),
                                                       [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(RELIST, SECOND_BODY, SEEN_AGAIN, receipt_line=2),
                                                        capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                                              'witnesses.parquet|added keys|successor of a re-keyed witness (2) is not an addition'),
    'old_body_split_in_two': (lambda: (base_tables(), edit(cand_tables(), 'witnesses', lambda rows: rows[1].update(record_sha=SECOND_BODY)),
                                       [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(RELIST, SECOND_BODY, SEEN_AGAIN, receipt_line=2),
                                        capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                              'witnesses.parquet|added keys|successor of a re-keyed witness (1) is not an addition'),
    'new_body_already_cited_live': (lambda: (edit(base_tables(), 'witnesses', lambda rows: rows.append(other_witness('x1', 'house_xml', NEW_RECORD, 9, 'Di Fox', 'NSF'))),
                                             edit(cand_tables(), 'witnesses', lambda rows: rows.append(other_witness('x1', 'house_xml', NEW_RECORD, 9, 'Di Fox', 'NSF')))),
                                    REKEY_STOPS),
    'same_body_new_keys_in_a_new_order': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, keys=('n1', 'n2'), order=(2, 1), mapped=NEW_MAP[:3])),
                                          'witnesses.parquet|changed display_order'),
    'read_dated_before_the_live_read': (lambda: (base_tables(), cand_tables(at=datetime(2026, 10, 1, tzinfo=timezone.utc))),
                                        'meetings.parquet|changed congress_gov_detail_observation'),
    'read_dated_in_the_future': (lambda: (base_tables(), cand_tables(at=FUTURE)), 'meetings.parquet|changed congress_gov_detail_observation'),
    # A byte-identical read moves only bookkeeping (ct-uywf).
    'status_seen_again_with_no_read': (lambda: (base_tables(), meeting_read(OLD_RECORD, FIRST_READ, FIRST_SEEN, keys=('w1', 'w2'), mapped=[('k1', 'w1', 'occurrence')],
                                                                            statuses=[LIVE_STATUS[:4] + (SEEN_AGAIN,)]), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                                       'meetings.parquet|changed publisher_status_observations'),
    'update_stamp_moved_on_the_same_body': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, updated=UPDATED_NEW)), 'meetings.parquet|changed congress_gov_updated'),
    'title_changed_on_the_same_body': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, title='Renamed')), 'meetings.parquet|changed title'),
    'status_seen_again_in_the_future': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, statuses=[LIVE_STATUS[:4] + (FUTURE,)])),
                                        'meetings.parquet|changed publisher_status_observations'),
    'status_copied_with_an_earlier_date': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, statuses=[LIVE_STATUS, LIVE_STATUS[:4] + (datetime(2026, 10, 1, tzinfo=timezone.utc),)])),
                                           'meetings.parquet|changed publisher_status_observations'),

    # The capture table, which the candidate does not control.
    'new_body_made_up': (lambda: (base_tables(), cand_tables(), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), NOT_A_BODY),
    'new_body_made_up_beside_a_title_change': (lambda: (base_tables(), cand_tables(title='Renamed'), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), NOT_A_BODY),
    'first_stated_meeting_made_up': (lambda: (*first_stated(), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), NOT_A_BODY),
    'new_body_also_in_a_live_receipt': (lambda: (base_tables(), cand_tables(), [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
                                                                              capture_line(FIRST_READ, NEW_RECORD, SEEN_AGAIN, receipt_line=9)]),
                                        f'cited file {NEW_RECORD.hex()[:16]} was already read by the live release ({FIRST_READ})'),
    'meeting_body_also_in_a_live_receipt': (lambda: (base_tables(keys=(), panel=(), order=(), mapped=[]),
                                                     cand_tables(keys=(), panel=(), order=(), mapped=[], title='Renamed'),
                                                     [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN), capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN),
                                                      capture_line(FIRST_READ, NEW_RECORD, SEEN_AGAIN, receipt_line=9)]),
                                            f'cited file {NEW_RECORD.hex()[:16]} was already read by the live release ({FIRST_READ})'),
    'witness_body_uncaptured_beside_a_video_refresh': (lambda: ({**base_tables(), **video_tables('fetch-1', 1)}, {**cand_tables(), **video_tables('fetch-2', 8)},
                                                                [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)], [(cache_file('fetch-2'), CACHE_RECEIPT)]), NOT_A_BODY),
    'read_in_a_live_receipt': (lambda: (base_tables(), cand_tables(record=OLD_RECORD, receipt=UNDATED_LIVE_RECEIPT)),
                               f'read {UNDATED_LIVE_RECEIPT}:1:0 is in a receipt the live release read'),
    'read_line_absent': (lambda: (base_tables(), cand_tables(record=OLD_RECORD), [capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                         f'read {RELIST}:1:0 is not a line in the capture table'),
    'read_line_holds_another_body': (lambda: (base_tables(), cand_tables(record=OLD_RECORD), [capture_line(RELIST, OTHER_BODY, SEEN_AGAIN),
                                                                                          capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]),
                                     f'read {RELIST}:1:0 holds body {OTHER_BODY.hex()[:16]}'),
    'read_line_requests_another_address': (lambda: (base_tables(), cand_tables(), [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN, url=MEETING_URL.replace('118340', '999999')),
                                                                                capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), f'read {RELIST}:1:0 requested'),
    'read_line_fetched_at_another_time': (lambda: (base_tables(), cand_tables(), [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN - timedelta(days=1)),
                                                                               capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), f'read {RELIST}:1:0 is dated'),
    'read_line_fetched_one_microsecond_apart': (lambda: (base_tables(), cand_tables(), [capture_line(RELIST, NEW_RECORD, SEEN_AGAIN + timedelta(microseconds=1)),
                                                                                     capture_line(FIRST_READ, OLD_RECORD, FIRST_SEEN)]), f'read {RELIST}:1:0 is dated'),
    'latest_attempt_dated_apart_from_its_line': (lambda: (base_tables(), edit(cand_tables(), 'meetings', lambda rows: rows[0]['congress_gov_detail_observation']
                                                                              ['latest_attempt']['evidence'].update(retrieved_at=SEEN_AGAIN + timedelta(minutes=1)))),
                                                 f'read {RELIST}:1:0 is dated'),
}


@pytest.mark.parametrize('case', sorted(CASES))
def test_a_meeting_read_again_unattended(tmp_path, case):
    build, expected = CASES[case]
    passed, report = gate_night(tmp_path, *build())
    said = '\n'.join(report['reasons'] + report.get('automatic_reasons', []))
    if expected is True:
        assert passed, said
    else:
        assert not passed and expected in said, said


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


def test_generic_doc_title_regex_matches_title_rules_registry():
    from viewer_publication.release_comparison import GENERIC_DOC_TITLE_RE
    rules_path = Path(__file__).resolve().parents[3] / 'model/registries/title-rules.json'
    label_patterns = [r['pattern'] for r in json.loads(rules_path.read_text()) if r['kind'] == 'label']
    assert label_patterns == [GENERIC_DOC_TITLE_RE]


def test_cache_refresh_refuses_non_youtube_cache_body_and_swapped_channel_caches(tmp_path):
    """ct-xyo9 (1), plants S_OTHERBODY and S_SWAPNEW: a newly cited video cache hash must come from a
    pipeline-data YouTube cache capture at the same channel cache path as the channel's live hash."""
    # S_OTHERBODY: new hash captured as a committee HTML document rather than pipeline-data youtube_NN.json.
    sub1 = tmp_path / 'other-body'
    base, candidate, automatic = nightly(
        sub1, ['A'], ['A'], base_tables=video_tables('fetch-1', 1), candidate_tables=video_tables('fetch-2', 8),
        capture_lines=[
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], sha256=cache_file('fetch-1'), family='pipeline-data',
                 requested_url='https://github.com/civictechdc/congressional-tech/raw/pipeline-data/youtube/youtube_00.json'),
            dict(receipt_key=CACHE_RECEIPT, sha256=cache_file('fetch-2'), family='documents',
                 requested_url='https://docs.house.gov/committee/page.html'),
        ])
    with pytest.raises(ValueError):
        require_release_gates(base, candidate, None, report_path=sub1 / 'r.json', automatic=automatic)
    r1 = json.loads((sub1 / 'r.json').read_text())
    assert any('has no pipeline-data YouTube cache capture' in msg for msg in r1['automatic_reasons'])

    # S_SWAPNEW: two channels swap their new pipeline-data cache files (youtube_00.json vs youtube_01.json).
    sub2 = tmp_path / 'swap-new'
    old0, old1 = cache_file('ch0-old'), cache_file('ch1-old')
    new0, new1 = cache_file('ch0-new'), cache_file('ch1-new')
    two_ch = lambda s0, s1, day: dict(
        channels=pa.table({'handle': ['@c0', '@c1'], 'title': ['C0', 'C1'], 'record_sha': pa.array([s0, s1], pa.binary())}),
        videos=pa.table({'video_key': ['youtube:v0', 'youtube:v1'], 'handle': ['@c0', '@c1'], 'title': ['V0', 'V1'],
                         'details_checked_at': pa.array([datetime(2026, 11, day, tzinfo=timezone.utc)] * 2, TS),
                         'record_sha': pa.array([s0, s1], pa.binary())}))
    yt_url = lambda idx: f'https://github.com/civictechdc/congressional-tech/raw/pipeline-data/youtube/youtube_{idx:02d}.json'
    base2, cand2, auto2 = nightly(
        sub2, ['A'], ['A'], base_tables=two_ch(old0, old1, 1),
        candidate_tables=two_ch(new1, new0, 8),  # swapped!
        capture_lines=[
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], sha256=old0, family='pipeline-data', requested_url=yt_url(0)),
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], receipt_line=2, sha256=old1, family='pipeline-data', requested_url=yt_url(1)),
            dict(receipt_key=CACHE_RECEIPT, sha256=new0, family='pipeline-data', requested_url=yt_url(0)),
            dict(receipt_key=CACHE_RECEIPT, receipt_line=2, sha256=new1, family='pipeline-data', requested_url=yt_url(1)),
        ])
    with pytest.raises(ValueError):
        require_release_gates(base2, cand2, None, report_path=sub2 / 'r.json', automatic=auto2)
    r2 = json.loads((sub2 / 'r.json').read_text())
    assert any('is not from the same channel cache path' in msg for msg in r2['automatic_reasons'])

    # Cross-domain S_OTHERBODY: @c0 refreshes cleanly while @c1 cites a live witness body hash.
    sub3 = tmp_path / 'cross-domain-live-body'
    witness_sha = cache_file('live-witness-xml')
    witness_tbl = pa.table({'witness_key': ['w1'], 'event_id': pa.array([1001], pa.int64()),
                            'name': ['Jane Roe'], 'record_sha': pa.array([witness_sha], pa.binary())})
    base3_tables = {**two_ch(old0, old1, 1), 'witnesses': witness_tbl}
    cand3_tables = {**two_ch(new0, witness_sha, 8), 'witnesses': witness_tbl}
    base3, cand3, auto3 = nightly(
        sub3, ['A'], ['A'], base_tables=base3_tables, candidate_tables=cand3_tables,
        capture_lines=[
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], sha256=old0, family='pipeline-data', requested_url=yt_url(0)),
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], receipt_line=2, sha256=old1, family='pipeline-data', requested_url=yt_url(1)),
            dict(receipt_key=sorted(LIVE_RECEIPTS)[0], receipt_line=3, sha256=witness_sha, family='house/witness-xml',
                 requested_url='https://docs.house.gov/meetings/IF/IF00/20261101/1001/HHRG-119-IF00-Wstate-RoeJ-20261101.xml'),
            dict(receipt_key=CACHE_RECEIPT, sha256=new0, family='pipeline-data', requested_url=yt_url(0)),
        ])
    with pytest.raises(ValueError):
        require_release_gates(base3, cand3, None, report_path=sub3 / 'r.json', automatic=auto3)
    r3 = json.loads((sub3 / 'r.json').read_text())
    assert any('was already read by the live release' in msg for msg in r3['automatic_reasons'])
    assert any('has no pipeline-data YouTube cache capture' in msg for msg in r3['automatic_reasons'])

    # Symmetric cross-domain reuse: new_citations still surfaces a witness newly citing a live YouTube cache hash.
    from viewer_publication.release_comparison import new_citations
    cand4_witnesses = pa.table({'witness_key': ['w1'], 'event_id': pa.array([1001], pa.int64()),
                                'name': ['Jane Roe'], 'record_sha': pa.array([old0], pa.binary())})
    sub4_base, sub4_cand = tmp_path / 'sym-base', tmp_path / 'sym-cand'
    sub4_base.mkdir()
    sub4_cand.mkdir()
    for name, tbl in {**two_ch(old0, old1, 1), 'witnesses': witness_tbl}.items():
        pq.write_table(tbl, sub4_base / f'{name}.parquet')
    for name, tbl in {**two_ch(new0, new1, 8), 'witnesses': cand4_witnesses}.items():
        pq.write_table(tbl, sub4_cand / f'{name}.parquet')
    assert old0.hex() in new_citations(sub4_base, sub4_cand)


def test_refetch_only_groups_refuse_when_both_automatic_and_cause_record_are_absent(tmp_path):
    """ct-xyo9 (1), plant S_ABSENT: turning automatic_causes off with no cause record cannot pass made-up citations."""
    base, candidate, _ = refreshed(tmp_path, captured=())
    with pytest.raises(ValueError, match='requires automatic capture verification or a cause record'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'absent.json', automatic=None)
    # A reviewed publish with a bound cause record (a person) passes without automatic_causes.
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[])
    assert require_release_gates(base, candidate, causes, report_path=tmp_path / 'reviewed.json', automatic=None)['reasons'] == []


@pytest.mark.parametrize('attr,cap_val,expected', [
    ('AUTOMATIC_LINK_KEYS_PER_DOCUMENT_CAP', 1, '2 link keys on one added document, more than the 1 one added document may carry'),
    ('AUTOMATIC_ADDED_LINK_KEYS_CAP', 1, '2 added link keys, more than the 1 one unattended night may add'),
    ('AUTOMATIC_ADDRESSES_PER_DOCUMENT_CAP', 1, '2 source rows on one added document, more than the 1 one added document may carry'),
    ('AUTOMATIC_ADDED_ADDRESSES_CAP', 1, '2 added source rows, more than the 1 one unattended night may add'),
])
def test_added_link_key_and_address_caps_refuse_before_any_engine_job(tmp_path, monkeypatch, attr, cap_val, expected):
    """ct-xyo9 (3), plants C1 and C250: per-document and nightly total caps on added link keys, source rows
    and lookup rows stop oversized additions before starting any engine job."""
    from viewer_publication import release_gate
    from viewer_publication.release_comparison import compare
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['A'], **addresses(['a']))
    release_dir(candidate, ['A', 'MN'], **addresses(['a', 'mn']))  # 1 added doc with 2 link keys, 2 sources, 2 urls
    report = compare(base, candidate)
    monkeypatch.setattr(release_gate, attr, cap_val)
    entries, reasons = release_gate.automatic_causes(
        report, base, candidate, engine=None, captures=None, live_receipt_keys=LIVE_RECEIPTS,
        read_receipt=lambda _: (_ for _ in ()).throw(AssertionError('engine or receipt read must not run')),
        work=tmp_path / 'auto')
    assert entries == []
    assert any(expected in r for r in reasons), reasons


def test_new_no_meeting_recordings_from_new_page_receipts_pass_unattended(tmp_path):
    """ct-zdj8: unattended night passes when added no-meeting recordings trace via recording_video_links.parquet to new receipts."""
    page_body = sha256(b'committee-event-page').digest()
    page_receipt = 'receipts/house/pages/2026-11-12/new-page.jsonl.gz'
    base_rec = pa.Table.from_pylist([dict(video_key='youtube:old', event_ids=[], tracks=[])], schema=RECORDINGS)
    cand_rec = pa.Table.from_pylist([
        dict(video_key='youtube:old', event_ids=[], tracks=[]),
        dict(video_key='youtube:anchor1', event_ids=[], tracks=[]),
        dict(video_key='youtube:embed1', event_ids=[], tracks=[]),
    ], schema=RECORDINGS)
    ev_dir = tmp_path / 'evidence'
    ev_dir.mkdir()
    pq.write_table(
        pa.Table.from_pylist([
            dict(page_body=page_body.hex(), extracted_key='youtube:anchor1'),
            dict(page_body=page_body.hex(), extracted_key='youtube:embed1'),
        ], schema=pa.schema([('page_body', pa.string()), ('extracted_key', pa.string())])),
        ev_dir / 'recording_video_links.parquet',
    )
    base, candidate, automatic_base = nightly(
        tmp_path, ['A'], ['A', 'N'],
        base_tables=dict(recordings=base_rec),
        candidate_tables=dict(
            recordings=cand_rec,
            url_state=pa.concat_tables([url_states(REQUEST, 1), url_states('https://agriculture.house.gov/event/1', 1)]),
        ),
        capture_lines=[dict(receipt_key=page_receipt, sha256=page_body, requested_url='https://agriculture.house.gov/event/1')],
    )
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes
    import gzip, os
    # Wrap automatic_causes with evidence_dir pointing to kept evidence.
    report_out = require_release_gates(
        base, candidate, None, report_path=tmp_path / 'r.json',
        automatic=lambda rep: automatic_causes(
            rep, base, candidate,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
            live_receipt_keys=LIVE_RECEIPTS,
            read_receipt=lambda k: (
                gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url='https://agriculture.house.gov/event/1', outcome='stored'),
                                               captures=[dict(sha256=page_body.hex())])) + '\n').encode(), mtime=0)
                if k == page_receipt else
                gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST, outcome='stored',
                                                           http_status=200, retrieved_at=FETCHED.isoformat()),
                                               captures=[dict(sha256=(K('N') + sha256(b'N').digest()[:24]).hex())])) + '\n' +
                               json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[])) + '\n').encode(), mtime=0)
            ),
            work=tmp_path / 'auto2',
            candidate_receipt_keys={*LIVE_RECEIPTS, NEW_RECEIPT, page_receipt},
            evidence_dir=ev_dir,
        ),
    )
    assert report_out['reasons'] == []
    by_file = {e['id'].split('|')[0]: e['tickets'] for e in report_out['automatic_causes']}
    assert by_file['recordings.parquet'] == ['ct-zdj8']
    trace = json.loads((tmp_path / 'auto2/automatic-trace.json').read_text())
    assert trace['recording_pages'] == [page_body.hex()[:16]]

    # P2-4 (ct-zdj8): when evidence_base and evidence_candidate are passed (as in nightly_publish.py),
    # compare classifies the group as 'empty event_ids; capture newly real'; automatic_causes must accept it too.
    ev_base = tmp_path / 'evidence-base'
    ev_base.mkdir()
    pq.write_table(
        pa.Table.from_pylist([dict(
            receipt_key=page_receipt, receipt_line=1, capture_index=0, member_path=None, sha256=page_body,
            mode='fetch', complete=True, outcome='stored', http_status=200,
            url='https://agriculture.house.gov/event/1',
            requested_url='https://agriculture.house.gov/event/1',
            context_url='https://agriculture.house.gov/event/1', is_real_file=False,
        )], schema=pa.schema([
            ('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('capture_index', pa.int32()),
            ('member_path', pa.string()), ('sha256', pa.binary()), ('mode', pa.string()), ('complete', pa.bool_()),
            ('outcome', pa.string()), ('http_status', pa.int32()), ('url', pa.string()),
            ('requested_url', pa.string()), ('context_url', pa.string()), ('is_real_file', pa.bool_()),
        ])),
        ev_base / 'capture_evidence.parquet',
    )
    pq.write_table(
        pa.Table.from_pylist([dict(
            receipt_key=page_receipt, receipt_line=1, capture_index=0, member_path=None, sha256=page_body,
            mode='fetch', complete=True, outcome='stored', http_status=200,
            url='https://agriculture.house.gov/event/1',
            requested_url='https://agriculture.house.gov/event/1',
            context_url='https://agriculture.house.gov/event/1', is_real_file=True,
        )], schema=pq.read_schema(ev_base / 'capture_evidence.parquet')),
        ev_dir / 'capture_evidence.parquet',
    )
    report_with_ev = require_release_gates(
        base, candidate, None, report_path=tmp_path / 'r-ev.json',
        evidence_base=ev_base / 'capture_evidence.parquet', evidence_candidate=ev_dir / 'capture_evidence.parquet',
        automatic=lambda rep: automatic_causes(
            rep, base, candidate,
            engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
            live_receipt_keys=LIVE_RECEIPTS,
            read_receipt=lambda k: (
                gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url='https://agriculture.house.gov/event/1', outcome='stored'),
                                               captures=[dict(sha256=page_body.hex())])) + '\n').encode(), mtime=0)
                if k == page_receipt else
                gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST, outcome='stored',
                                                           http_status=200, retrieved_at=FETCHED.isoformat()),
                                               captures=[dict(sha256=(K('N') + sha256(b'N').digest()[:24]).hex())])) + '\n' +
                               json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[])) + '\n').encode(), mtime=0)
            ),
            work=tmp_path / 'auto-ev',
            candidate_receipt_keys={*LIVE_RECEIPTS, NEW_RECEIPT, page_receipt},
            evidence_dir=ev_dir,
        ),
    )
    assert report_with_ev['reasons'] == []
    rec_groups = report_with_ev['files']['recordings.parquet']['groups']
    assert any(g['group'] == 'added keys' and g['cause'] == 'empty event_ids; capture newly real' for g in rec_groups)
    trace_ev = json.loads((tmp_path / 'auto-ev/automatic-trace.json').read_text())
    assert trace_ev['recording_pages'] == [page_body.hex()[:16]]


@pytest.mark.parametrize('mode,expected_reason', [
    ('unlinked', 'have no linking page in kept evidence'),
    ('live_receipt', 'is already in the live release'),
    ('missing_raw_body', 'does not name body'),
])
def test_new_no_meeting_recordings_refuse_when_unlinked_or_not_from_new_raw_receipt(tmp_path, mode, expected_reason):
    """ct-zdj8: untraced or live-receipt or raw-mismatched no-meeting recordings refuse unattended."""
    import gzip, os
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes

    page_body = sha256(b'committee-event-page-bad').digest()
    page_receipt = sorted(LIVE_RECEIPTS)[0] if mode == 'live_receipt' else 'receipts/house/pages/2026-11-12/bad-page.jsonl.gz'
    base_rec = pa.Table.from_pylist([dict(video_key='youtube:old', event_ids=[], tracks=[])], schema=RECORDINGS)
    cand_rec = pa.Table.from_pylist([
        dict(video_key='youtube:old', event_ids=[], tracks=[]),
        dict(video_key='youtube:new1', event_ids=[], tracks=[]),
    ], schema=RECORDINGS)
    ev_dir = tmp_path / 'evidence'
    ev_dir.mkdir()
    rvl_rows = [] if mode == 'unlinked' else [dict(page_body=page_body.hex(), extracted_key='youtube:new1')]
    pq.write_table(
        pa.Table.from_pylist(rvl_rows, schema=pa.schema([('page_body', pa.string()), ('extracted_key', pa.string())])),
        ev_dir / 'recording_video_links.parquet',
    )
    extra_state = [url_states('https://agriculture.house.gov/event/2', 1)] if mode != 'live_receipt' else []
    base, candidate, _ = nightly(
        tmp_path, ['A'], ['A', 'N'],
        base_tables=dict(recordings=base_rec),
        candidate_tables=dict(
            recordings=cand_rec,
            url_state=pa.concat_tables([url_states(REQUEST, 1), *extra_state]),
        ),
        capture_lines=[dict(receipt_key=page_receipt, sha256=page_body, requested_url='https://agriculture.house.gov/event/2')],
    )
    raw_sha = '0' * 64 if mode == 'missing_raw_body' else page_body.hex()
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(
            base, candidate, None, report_path=tmp_path / 'r.json',
            automatic=lambda rep: automatic_causes(
                rep, base, candidate,
                engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                live_receipt_keys=LIVE_RECEIPTS,
                read_receipt=lambda k: (
                    gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url='https://agriculture.house.gov/event/2', outcome='stored'),
                                                   captures=[dict(sha256=raw_sha)])) + '\n').encode(), mtime=0)
                    if k == page_receipt else
                    gzip.compress((json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST, outcome='stored',
                                                               http_status=200, retrieved_at=FETCHED.isoformat()),
                                                   captures=[dict(sha256=(K('N') + sha256(b'N').digest()[:24]).hex())])) + '\n' +
                                   json.dumps(dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[])) + '\n').encode(), mtime=0)
                ),
                work=tmp_path / 'auto-bad',
                candidate_receipt_keys={*LIVE_RECEIPTS, NEW_RECEIPT, page_receipt},
                evidence_dir=ev_dir,
            ),
        )
    report = json.loads((tmp_path / 'r.json').read_text())
    assert any(expected_reason in r for r in report['automatic_reasons']), report['automatic_reasons']
