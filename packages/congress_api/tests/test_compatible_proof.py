"""The proof CLI recomputes a pre-chosen local sample with the real producer and binds the entry."""
import gzip
import hashlib
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import compatible_proof, compatible_versions as cv, readings
from congress_api.retention.provenance import parquet_output, run_job
from docspec_client.client import NativeDatasets

PAGES = [b'<html><body><p>' + f'Evidence {i} '.encode() * 400 + b'</p><a href="r.pdf">PDF</a></body></html>' for i in range(3)]


def mirror(tmp_path):
    """Three html bodies, one stored gzip, and captures with the lake's primary key."""
    raw = tmp_path / 'raw'
    rows = []
    for i, body in enumerate(PAGES):
        digest = hashlib.sha256(body).hexdigest()
        suffix = '.gz' if i == 0 else ''
        path = raw / 'bodies/sha256' / digest[:2] / (digest + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body, mtime=0) if suffix else body)
        rows.append(dict(receipt_key='r', receipt_line=i + 1, capture_index=0, sha256=bytes.fromhex(digest), bytes=len(body),
            media_type='text/html', fidelity='exact-bytes', sniffed_format='html', sniff_version='x', intact=None,
            stored_suffix=suffix, stored_bytes=path.stat().st_size))
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('receipt_key', pa.string()), ('receipt_line', pa.int64()),
        ('capture_index', pa.int64()), ('sha256', pa.binary(32)), ('bytes', pa.int64()), ('media_type', pa.string()),
        ('fidelity', pa.string()), ('sniffed_format', pa.string()), ('sniff_version', pa.string()), ('intact', pa.bool_()),
        ('stored_suffix', pa.string()), ('stored_bytes', pa.int64())])), captures)
    return raw, captures


def test_a_full_page_proof_over_local_bodies_binds_its_entry(tmp_path, monkeypatch):
    import congress_api.parsers.archive_readings as reader
    monkeypatch.delattr(reader, 'HTML_REREAD_SQL', raising=False)  # a reader with no recompute set
    raw, captures = mirror(tmp_path)
    assert set(compatible_proof.local_bodies(raw)) == {hashlib.sha256(b).hexdigest() for b in PAGES}
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    local = compatible_proof.local_bodies(raw)
    (tmp_path / 'base-work').mkdir()
    _, staged = compatible_proof.recompute(bodies=sorted(local), local=local, captures=captures, raw_root=raw, engine=engine,
        work=tmp_path / 'base-work', decided_at='2026-11-02T00:00:00Z')
    # Independent of the base: the stored-gzip mirror body must sniff as html, not 'other'
    # (the base below is this same code's output, so it cannot see that convention).
    assert {r['format'] for r in pq.read_table(staged['readings']).to_pylist() if r['parser'] == 'sniff'} == {'html'}
    # The base is the producer's own output relabelled to an older html pin.
    base = tmp_path / 'base'
    run_job(base, engine, inputs=[dict(name='r', kind='parquet', path=str(staged['readings']))], steps=[], queries=[],
        outputs=[parquet_output(base, 'readings', "SELECT * EXCLUDE(parser_version),CASE WHEN parser='html' THEN 'old-html' ELSE parser_version END AS parser_version FROM r", readings.PK)])
    registry = tmp_path / 'registry.json'
    # A stale entry (its current pin superseded) must not block the proof that replaces it.
    stale = dict(parser='html', version='old-html', current='superseded', basis='whole', recompute_sql='none', reason='stale', proof={})
    registry.write_text(json.dumps(dict(version=2, entries=[stale])))
    monkeypatch.setattr(cv, 'REGISTRY', registry)
    compatible_proof.main(['--parser', 'html', '--old', 'old-html', '--base', str(base / 'readings.parquet'), '--captures', str(captures),
        '--raw-root', str(raw), '--work', str(tmp_path / 'proof'), '--write',
        '--engine-config', os.environ['DOCSPEC_JOB_CONFIG']])
    [entry] = json.loads(registry.read_text())['entries']
    assert entry['basis'] == 'predicate' and entry['current'] == readings.current_version('html')
    assert entry['proof']['scope'] == 'full' and entry['proof']['page_parse_max_bytes'] == readings.PAGE_PARSE_MAX_BYTES
    assert entry['proof']['rows'] == 3 and entry['proof']['strata'] == dict(completed=dict(population=3, local=3, sampled=3)) and entry['proof']['differences'] == entry['proof']['only_old'] == entry['proof']['only_new'] == 0
    assert cv.load_registry() == [entry]
    # A predicate entry compares every kept row: with one kept body not local, it refuses.
    import pytest
    next(path for path in (raw / 'bodies').rglob('*') if path.is_file()).unlink()
    with pytest.raises(ValueError, match='needs every kept body local'):
        compatible_proof.main(['--parser', 'html', '--old', 'old-html', '--base', str(base / 'readings.parquet'), '--captures', str(captures),
            '--raw-root', str(raw), '--work', str(tmp_path / 'missing'), '--write', '--engine-config', os.environ['DOCSPEC_JOB_CONFIG']])


def test_a_bundle_proof_states_strata_the_registry_accepts(tmp_path, monkeypatch):
    # Defect guarded: a full bundle proof without strata, refused by the registry's coverage rule.
    bodies = ['a' * 64, 'b' * 64]
    decisions = tmp_path / 'decisions.jsonl'
    decisions.write_text(''.join(json.dumps(dict(body_sha256=b, parser='readings', parser_version='b-old', reason=r)) + '\n'
                                 for b, r in zip(bodies, ['memory_limit', 'output_limit'])))
    stage = tmp_path / 'stage'
    (stage / 'parsed').mkdir(parents=True)
    (stage / 'parsed/unreadable.jsonl').write_text(decisions.read_text())
    monkeypatch.setattr(compatible_proof, 'local_bodies', lambda raw: {b: 'x' for b in bodies})
    monkeypatch.setattr(compatible_proof, 'recompute', lambda **kw: (None, dict(work_list=stage / 'work-list.parquet')))
    pins = cv.current_pins()
    proof = compatible_proof.prove_bundle(old='b-old', decisions=[decisions], captures=None, raw_root=tmp_path, engine=None,
        work=tmp_path, decided_at='2026-11-02T00:00:00Z', current=pins['readings'])
    entry = dict(parser='readings', version='b-old', current=pins['readings'], basis='bundle', recompute_sql=cv.WHOLE, reason='r', proof=proof)
    assert proof['strata'] == dict(memory_limit=dict(population=1, local=1, sampled=1), output_limit=dict(population=1, local=1, sampled=1))
    assert cv.validate_entries([entry], current=pins) == [entry]
