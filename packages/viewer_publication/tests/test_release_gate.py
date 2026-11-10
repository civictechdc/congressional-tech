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


def release_dir(root, documents, retired=None, *, scope=SCOPE, saved=None, **extra_tables):
    """A real, internally consistent release: documents are rows of link-key letters.

    `saved` names each row's saved file by the letter of its body key (a link key is the first
    8 bytes of its body's SHA-256); without it the release has no saved_body column."""
    root.mkdir(parents=True)
    detail = {'link_key': pa.array([K(keys[0]) for keys in documents], pa.binary(8))}
    if saved is not None:
        detail['saved_body'] = pa.array([K(letter) + bytes(24) for letter in saved], pa.binary(32))
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


def test_link_rule_refuses_fused_documents_even_with_record(tmp_path):
    """ct-4qld, a70ebc3d1466: seven PDFs become one row, and six keys open the seventh's file."""
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, list('ABCDEFG'), saved='ABCDEFG')
    release_dir(candidate, ['ABCDEFG'], saved='G')
    named = ', '.join(K(letter).hex() for letter in 'ABCDEF')
    with pytest.raises(ValueError, match=f'link rule: 6 live link keys answer another file \\({named}\\)'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json')
    # A reviewed record for every group of the comparison does not override it.
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        *((name, 'merged rows', 'previous rows now share one document', -6) for name in ('detail.parquet', 'list.parquet')), MOVED_LINKS])
    with pytest.raises(ValueError) as refusal:
        require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    report = json.loads((tmp_path / 'r.json').read_text())
    assert report['reasons'] == [f'link rule: 6 live link keys answer another file ({named})']
    assert report['reasons'][0] in str(refusal.value)
    assert [(a['live_file'], a['candidate_file']) for a in report['link_rule']['changed_answers']] == [
        (f'{letter}.pdf', 'ABCDEFG.pdf') for letter in 'ABCDEF']


def test_link_rule_passes_documents_that_keep_their_files(tmp_path):
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['AB', 'C'], saved='AC')
    release_dir(candidate, ['C', 'A', 'B'], saved='CAB')  # B, wrongly joined to A, reaches its own file
    causes = record_for(*ids((base, candidate)), tmp_path, groups=[
        *((name, 'split rows', 'previous row had no member source', 1) for name in ('detail.parquet', 'list.parquet')), MOVED_LINKS])
    report = require_release_gates(base, candidate, causes, report_path=tmp_path / 'r.json')
    assert report['link_rule'] == dict(missing=0, missing_keys=[], dangling=0, dangling_keys=[], changed=0, changed_keys=[],
                                       changed_answers=[], lookup_changed=0, lookup_changed_keys=[], lookup_changed_answers=[],
                                       address_changed=0, address_changed_keys=[], address_changed_answers=[], ok=True)


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
        key='https://example.test/a', live_row=0, live_file='A.pdf', live_body=(K('A') + bytes(24)).hex(),
        candidate_rows=[1], candidate_files=['B.pdf'])]


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
            url=REQUEST, attempts=1, raw_url=REQUEST, capture_url=REQUEST, other_entity=False, nested=True, live_receipts=LIVE_RECEIPTS, failed_duplicate=False,
            base_tables=None, candidate_tables=None, also_held=None):
    """Releases plus a captures file and raw receipts; returns the gate's automatic callback."""
    import gzip
    import os
    from docspec_client.client import NativeDatasets
    from viewer_publication.release_gate import automatic_causes
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    states = url_states(url, attempts)
    failure_url = 'https://www.govinfo.gov/failed-copy.pdf'
    baseline = dict(url_state=states.slice(0, 0))
    additions = dict(url_state=pa.concat_tables([states, url_states(failure_url, 1)]) if failed_duplicate else states)
    if other_entity:
        additions['meetings'] = pa.table({'event_id': [119123]})
        baseline['meetings'] = additions['meetings'].slice(0, 0)
    release_dir(base, base_docs, **baseline, **(base_tables or {}))
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
    if failed_duplicate:
        capture_rows.append(dict(capture_rows[0], receipt_line=2, requested_url=failure_url,
                                 outcome='failed', http_status=403))
    if also_held:
        # The same body was also captured by a receipt the live release read.
        capture_rows.append(dict(capture_rows[0], receipt_key=also_held, receipt_line=7))
    pq.write_table(pa.Table.from_pylist(capture_rows, schema=pa.schema([
        ('receipt_key', pa.string()), ('receipt_line', pa.int32()), ('sha256', pa.binary(32)),
        ('requested_url', pa.string()), ('mode', pa.string()), ('complete', pa.bool_()),
        ('attempt', pa.int32()), ('outcome', pa.string()), ('http_status', pa.int32()),
    ])), tmp_path / 'captures.parquet')
    sha = next(iter(bodies.values())).hex() if raw_names_body else '0' * 64
    line = dict(record=dict(mode='fetch', outcome='stored', requested_url=raw_url, url=raw_url,
                            http_status=200, retrieved_at=FETCHED.isoformat(), content=dict(sha256=sha)),
                captures=[dict(pointer=['content', 'body'], sha256=sha,
                               body_key=f'bodies/sha256/{sha[:2]}/{sha}.gz', bytes=4721, media_type='application/pdf')])
    if len(bodies)>1:
        line['notes'] = [b.hex() for b in list(bodies.values())[1:]]
    if not nested:
        line.update(line.pop('record'))
    unrelated = (dict(record=dict(mode='fetch', requested_url=failure_url, outcome='failed', http_status=403),
                      captures=line['captures']) if failed_duplicate else
                 dict(record=dict(mode='fetch', requested_url=REQUEST), captures=[]))
    raw = {receipt: gzip.compress(('\n'.join(map(json.dumps, (line, unrelated))) + '\n').encode(), mtime=0)}
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    def automatic(report):
        return automatic_causes(report, base, candidate, engine=engine, captures=dict(kind='parquet', path=str(tmp_path / 'captures.parquet')),
                                live_receipt_keys=live_receipts, read_receipt=raw.__getitem__, work=tmp_path / 'auto')
    return base, candidate, automatic


@pytest.mark.parametrize('nested', [True, False])
def test_additions_from_new_receipts_pass_unattended(tmp_path, nested):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], nested=nested)
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and {e['tickets'][0] for e in report['automatic_causes']} == {'ct-ud0b'}
    assert {e['id'].split('|')[1] for e in report['automatic_causes']} >= {'added rows', 'added keys', 'added URLs'}
    trace = json.loads((tmp_path / 'auto/automatic-trace.json').read_text())
    assert trace['url_attempts'] == {REQUEST: [[NEW_RECEIPT, 1]]}
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
    assert json.loads((tmp_path / 'auto/automatic-trace.json').read_text())['url_attempts'] == {REQUEST: [[receipt, 1]]}


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


def test_a_failed_response_sharing_the_new_documents_body_cannot_qualify_its_url(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], failed_duplicate=True)
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    reasons = json.loads((tmp_path / 'r.json').read_text())['automatic_reasons']
    assert len(reasons) == 1 and 'failed-copy.pdf has 1 attempts but 0 fresh raw lines' in reasons[0]


def test_an_added_link_key_on_an_existing_document_requires_review(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['AZ', 'N'], filenames=['A.pdf', 'N.pdf'])
    report_path = tmp_path / 'r.json'
    with pytest.raises(ValueError, match='no recorded cause'):
        require_release_gates(base, candidate, None, report_path=report_path, automatic=automatic)
    report = json.loads(report_path.read_text())
    assert report['link_rule']['ok']
    assert report['automatic_reasons'] == ['automatic causes: 2 added link keys, 1 attached to new documents']


# ct-syp1: a video cache refresh rewrites every citation of the cache file and nothing else.
def video_tables(fetch, day, *, title='Hearing on oversight'):
    file_sha = sha256(fetch.encode()).digest()
    return dict(
        channels=pa.table({'handle': ['@committee'], 'title': ['Committee'], 'record_sha': pa.array([file_sha], pa.binary())}),
        videos=pa.table({'video_key': ['youtube:one'], 'handle': ['@committee'], 'title': [title],
                         'details_checked_at': pa.array([datetime(2026, 11, day, tzinfo=timezone.utc)], pa.timestamp('us', tz='UTC')),
                         'record_sha': pa.array([file_sha], pa.binary())}),
        recording_matches=pa.table({'match_id': ['m1'], 'video_key': ['youtube:one'],
                                    'source_ref': ['video_records:' + file_sha.hex()]}))


def no_additions(base, candidate, tmp_path):
    from viewer_publication.release_gate import automatic_causes
    return lambda report: automatic_causes(report, base, candidate, engine=None, captures=None,
                                           live_receipt_keys=(), read_receipt=None, work=tmp_path / 'auto')


def test_a_cache_refresh_alone_passes_unattended(tmp_path):
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['A'], **video_tables('fetch-1', 1))
    release_dir(candidate, ['A'], **video_tables('fetch-2', 8))
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json',
                                   automatic=no_additions(base, candidate, tmp_path))
    assert report['reasons'] == [] and report['automatic_reasons'] == [] and report['failing'] == []
    proven = {(name, g['group']): g['count'] for name, facts in report['files'].items() for g in facts['groups']}
    assert proven == {('channels.parquet', 'changed record_sha'): 1, ('videos.parquet', 'changed record_sha'): 1,
                      ('videos.parquet', 'changed details_checked_at'): 1, ('recording_matches.parquet', 'changed source_ref'): 1}


def test_a_cache_refresh_beside_new_documents_passes_unattended(tmp_path):
    base, candidate, automatic = nightly(tmp_path, ['A'], ['A', 'N'], base_tables=video_tables('fetch-1', 1),
                                         candidate_tables=video_tables('fetch-2', 8))
    report = require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json', automatic=automatic)
    assert report['reasons'] == [] and {e['id'].split('|')[0] for e in report['automatic_causes']} == {
        'list.parquet', 'detail.parquet', 'links.parquet', 'url_state.parquet'}


def test_a_changed_title_beside_a_cache_refresh_refuses_unattended(tmp_path):
    base, candidate = tmp_path / 'base', tmp_path / 'candidate'
    release_dir(base, ['A'], **video_tables('fetch-1', 1))
    release_dir(candidate, ['A'], **video_tables('fetch-2', 8, title='Hearing on something else'))
    with pytest.raises(ValueError, match=r'no recorded cause for videos.parquet\|changed title\|value differs on matched key \(1\)'):
        require_release_gates(base, candidate, None, report_path=tmp_path / 'r.json',
                              automatic=no_additions(base, candidate, tmp_path))
    report = json.loads((tmp_path / 'r.json').read_text())
    # The changed row's own citation is not proven either; the channel's and the match's are.
    assert sorted(g['file'] + '|' + g['group'] for g in report['failing']) == [
        'videos.parquet|changed details_checked_at', 'videos.parquet|changed record_sha', 'videos.parquet|changed title']
    assert any('videos.parquet|changed title' in reason for reason in report['automatic_reasons'])
