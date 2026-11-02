"""Gates 1 and 2 at publish: every difference needs its recorded cause; no link key may vanish."""
from hashlib import md5, sha256
from io import BytesIO
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.archive_format import release_identity
from viewer_publication.release_gate import (RETIRED, fetch_release, load_causes, render_notes,
                                             require_release_gates)

K = lambda letter: (letter * 8).encode()
SCOPE = {'version': 1, 'entries': []}


def release_dir(root, documents, retired=None):
    """A real, internally consistent release: documents are rows of link-key letters."""
    root.mkdir(parents=True)
    tables = {
        'list': pa.table({'filename': [f'{keys}.pdf' for keys in documents]}),
        'detail': pa.table({'link_key': pa.array([K(keys[0]) for keys in documents], pa.binary(8))}),
        'links': pa.table({'link_key': pa.array([K(k) for keys in documents for k in keys], pa.binary(8)),
                           'list_row': pa.array([i for i, keys in enumerate(documents) for _ in keys], pa.int32())}),
        'urls': pa.table({'lookup_key': pa.array([], pa.binary(8)), 'list_row': pa.array([], pa.int32())}),
        'sources': pa.table({'list_row': pa.array([], pa.int32()), 'url': pa.array([], pa.string()),
                             'member_path': pa.array([], pa.string())}),
    }
    if retired is not None:
        tables['retired_links'] = pa.Table.from_pylist(retired, schema=RETIRED)
    files = []
    for name, table in tables.items():
        path = root / f'{name}.parquet'
        pq.write_table(table, path)
        data = path.read_bytes()
        files.append(dict(name=path.name, sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(),
                          size=len(data), rows=table.num_rows))
    data = json.dumps(SCOPE).encode()
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
