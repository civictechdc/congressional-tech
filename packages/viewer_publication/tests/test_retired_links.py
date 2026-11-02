"""Gate 2 in the model: retired link keys redirect or show a removal notice (data model §8.2)."""
import json
import os
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive_job_fixture import real_model_spec
from docspec_client.client import NativeDatasets

K = lambda letter: (letter * 8).encode()
BASE, HISTORY = 'b' * 64, 'c' * 64


def fake_release(directory, release_id, rows, retired=None):
    """rows: [(filename, primary_key, [keys])]; only the files the ledger reads."""
    directory.mkdir(parents=True)
    pq.write_table(pa.table({'filename': [r[0] for r in rows]}), directory / 'list.parquet')
    pq.write_table(pa.table({'link_key': pa.array([r[1] for r in rows], pa.binary(8))}), directory / 'detail.parquet')
    links = [(key, i) for i, r in enumerate(rows) for key in r[2]]
    pq.write_table(pa.table({'link_key': pa.array([k for k, _ in links], pa.binary(8)),
                             'list_row': pa.array([i for _, i in links], pa.int32())}), directory / 'links.parquet')
    if retired is not None:
        from viewer_publication.release_gate import RETIRED
        pq.write_table(pa.Table.from_pylist(retired, schema=RETIRED), directory / 'retired_links.parquet')
    (directory / 'manifest.json').write_text(json.dumps({'release_id': release_id}))
    return directory


def build(tmp_path, spec, prior, retired, root=None):
    from viewer_publication.archive_model import ROOT, build_release
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        return build_release(**{name: spec[name]['path'] for name in ['captures', 'readings', 'filename_readings']},
            parser_versions=spec['parser_versions'], catalog_version=spec['catalog_version'], engine=engine,
            output=tmp_path / 'release', scratch=tmp_path / 'model', prior_links=prior, base_retired=retired, root=root or ROOT)


@pytest.fixture
def ledger(tmp_path):
    from viewer_publication.release_gate import prior_links
    spec, digest, _ = real_model_spec(tmp_path)
    live = bytes.fromhex(digest)[:8]  # the candidate's one document key
    base = fake_release(tmp_path / 'base', BASE, [
        ('gone.pdf', K('g'), [K('g')]),          # (a) body no longer real: removal notice
        ('two.pdf', live, [live, K('x')]),       # (b) the row loses key x; its primary key survives
    ], retired=[
        dict(link_key=K('r'), successor_key=K('x'), last_release_id='d' * 64, last_filename='r.pdf'),  # (c) re-resolve one hop
        dict(link_key=K('s'), successor_key=K('z'), last_release_id='d' * 64, last_filename='s.pdf'),  # (c) successor gone
        dict(link_key=live, successor_key=None, last_release_id='d' * 64, last_filename='back.pdf'),   # (d) published again
    ])
    history = fake_release(tmp_path / 'history', HISTORY, [('q.pdf', K('q'), [K('q'), live])])  # sibling-only successor
    prior, retired = prior_links(base, [history], tmp_path / 'ledger-inputs')
    return spec, live, prior, retired


def test_retired_keys_redirect_or_show_a_notice_and_none_vanish(tmp_path, ledger):
    spec, live, prior, retired = ledger
    manifest = build(tmp_path, spec, prior, retired)
    assert 'retired_links.parquet' in {f['name'] for f in manifest['files']}
    rows = {r['link_key']: r for r in pq.read_table(tmp_path / 'release/retired_links.parquet').to_pylist()}
    assert {k: (r['successor_key'], r['last_release_id'], r['last_filename']) for k, r in rows.items()} == {
        K('g'): (None, BASE, 'gone.pdf'),
        K('x'): (live, BASE, 'two.pdf'),
        K('q'): (live, HISTORY, 'q.pdf'),
        K('r'): (live, 'd' * 64, 'r.pdf'),
        K('s'): (None, 'd' * 64, 's.pdf'),
    }
    published = set(pq.read_table(tmp_path / 'release/links.parquet')['link_key'].to_pylist())
    assert live in published and not published & set(rows)


def test_a_dropped_re_resolution_refuses_before_the_manifest(tmp_path, ledger):
    """Injected defect: carried rows keep a successor that is no longer published."""
    from viewer_publication.archive_model_profile import ROOT, _definition_hashes
    spec, _, prior, retired = ledger
    broken = tmp_path / 'broken-root'
    for relative in _definition_hashes(ROOT):
        target = broken / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    sql = broken / 'model/sql/retired-links.sql'
    text = sql.read_text()
    assert 'coalesce(r.primary_key,f.successor_key) AS successor_key' in text
    sql.write_text(text.replace('coalesce(r.primary_key,f.successor_key) AS successor_key', 'b.successor_key', 1))
    with pytest.raises(ValueError, match='Release key invariant failed'):
        build(tmp_path, spec, prior, retired, root=broken)
    assert not (tmp_path / 'release/manifest.json').exists()
    reports = {q['name']: q['data'] for q in json.loads((tmp_path / 'model/result.json').read_text())['queries']}
    assert reports['relationship_invariants'][0]['missing_retired_successor'] == 2


def test_no_ledger_inputs_give_an_empty_ledger(tmp_path):
    spec, _, _ = real_model_spec(tmp_path)
    manifest = build(tmp_path, spec, None, None)
    entry = next(f for f in manifest['files'] if f['name'] == 'retired_links.parquet')
    assert entry['rows'] == 0


def test_ledger_history_is_required_exactly_when_the_base_has_no_ledger(tmp_path):
    from viewer_publication.release_gate import require_ledger_history
    bare = fake_release(tmp_path / 'bare', BASE, [('a', K('a'), [K('a')])])
    with pytest.raises(ValueError, match='must name link_history'):
        require_ledger_history(bare, [])
    require_ledger_history(bare, [HISTORY])
    kept = fake_release(tmp_path / 'kept', BASE, [('a', K('a'), [K('a')])], retired=[])
    require_ledger_history(kept, [])
    with pytest.raises(ValueError, match='link_history must be empty'):
        require_ledger_history(kept, [HISTORY])
