"""Gates 1 and 2 at publish: every difference needs its recorded cause; no link key may vanish."""
from datetime import datetime, timezone
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


def release_dir(root, documents, retired=None, **extra_tables):
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
LIVE_RECEIPTS = {'receipts/documents/2026-11-01/live.jsonl.gz'}
NEW_RECEIPT = 'receipts/documents/2026-11-03/nightly.jsonl.gz'
REQUEST = 'https://www.govinfo.gov/content/pkg/CHRG-119hhrg12345/pdf/CHRG-119hhrg12345.pdf'
FETCHED = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)


def url_states(url, attempts):
    ts = pa.timestamp('us', tz='UTC')
    return pa.table({
        'requested_url': pa.array([url], pa.string()),
        'attempts': pa.array([attempts], pa.int32()),
        'last_attempt': pa.array([FETCHED if attempts else None], ts),
        'last_status': pa.array([200 if attempts else None], pa.int16()),
        'last_outcome': pa.array(['stored' if attempts else None], pa.string()),
        'last_good_at': pa.array([FETCHED if attempts else None], ts),
        'next_attempt_at': pa.array([None], ts),
    })


def nightly(tmp_path, base_docs, candidate_docs, *, receipt=NEW_RECEIPT, raw_names_body=True, filenames=None,
            url=REQUEST, attempts=1, raw_url=REQUEST, capture_url=REQUEST, other_entity=False, nested=True):
    """Releases plus a captures file and raw receipts; returns the gate's automatic callback."""
    import gzip
    import os
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    states = url_states(url, attempts)
    baseline = dict(url_state=states.slice(0, 0))
    additions = dict(url_state=states)
    if other_entity:
        additions['meetings'] = pa.table({'event_id': [119123]})
        baseline['meetings'] = additions['meetings'].slice(0, 0)
    release_dir(base, base_docs, **baseline)
    release_dir(candidate, candidate_docs, retired=[], **additions)
    if filenames:
        pq.write_table(pa.table({'filename': filenames}), candidate / 'list.parquet')
        manifest = json.loads((candidate / 'manifest.json').read_text())
        data = (candidate / 'list.parquet').read_bytes()
        entry = next(f for f in manifest['files'] if f['name'] == 'list.parquet')
        entry.update(sha256=sha256(data).hexdigest(), md5=md5(data).hexdigest(), size=len(data))
        manifest['release_id'] = release_identity(1, manifest['files'])
        (candidate / 'manifest.json').write_text(json.dumps(manifest))
    new = [k for keys in candidate_docs for k in keys if not any(k in b for b in base_docs)]
    bodies = {k: K(k) + sha256(k.encode()).digest()[:24] for k in new}
    pq.write_table(pa.table({'receipt_key': [receipt] * len(bodies), 'receipt_line': pa.array([1] * len(bodies), pa.int32()),
                             'sha256': pa.array(list(bodies.values()), pa.binary(32)),
                             'requested_url': pa.array([capture_url] * len(bodies), pa.string())}), tmp_path / 'captures.parquet')
    sha = next(iter(bodies.values())).hex() if raw_names_body else '0' * 64
    line = dict(record=dict(mode='fetch', outcome='stored', requested_url=raw_url, url=raw_url,
                            http_status=200, retrieved_at=FETCHED.isoformat(), content=dict(sha256=sha)),
                captures=[dict(pointer=['content', 'body'], sha256=sha,
                               body_key=f'bodies/sha256/{sha[:2]}/{sha}.gz', bytes=4721, media_type='application/pdf')])
    if not nested:
        line.update(line.pop('record'))
    unrelated = dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[])
    raw = {receipt: gzip.compress(('\n'.join(map(json.dumps, (line, unrelated))) + '\n').encode(), mtime=0)}
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    def automatic(report):
        return automatic_causes(report, base, candidate, engine=engine, captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                                live_receipt_keys=LIVE_RECEIPTS, read_receipt=raw.__getitem__, work=tmp_path / 'auto')
    return base, candidate, automatic


@pytest.mark.parametrize('nested', [True, False])
def test_additions_from_new_receipts_pass_unattended(tmp_path, nested):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], nested=nested)
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and {e['tickets'][0] for e in report['automatic_causes']} == {'ct-ud0b'}
    assert {e['id'].split('|')[1] for e in report['automatic_causes']} >= {'added rows', 'added keys', 'added URLs'}
    trace = json.loads((tmp_path / 'auto/automatic-trace.json').read_text())
    assert trace['url_attempts'] == {REQUEST: [[NEW_RECEIPT, 1]]}


@pytest.mark.parametrize('receipt,rule', [
    (sorted(LIVE_RECEIPTS)[0], 'is already in the live release'),
    ('receipts/documents/2026-10-30/older.jsonl.gz', 'is not dated after the live release'),
    ('receipts/documents/undated/assemble.jsonl.gz', 'is not dated after the live release'),
    ('receipts/documents/2026-11-31/bad-date.jsonl.gz', 'is not dated after the live release'),
])
def test_an_added_row_from_an_old_receipt_refuses(tmp_path, receipt, rule):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], receipt=receipt)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert any(rule in reason for reason in json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'])


def test_a_raw_line_that_does_not_name_the_body_refuses(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], raw_names_body=False)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert any('does not name body' in r for r in json.loads((tmp_path / 'r.json').read_text())['automatic_reasons'])


def test_a_changed_value_refuses_even_beside_new_rows(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], filenames=['A-renamed.pdf', 'N.pdf'])
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
