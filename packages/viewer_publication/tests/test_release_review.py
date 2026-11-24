"""Tests for Gate-1 human review summaries and bounded before/after row sampling."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import cause_record
from viewer_publication.release_gate import require_release_gates
from viewer_publication.release_review import render_review_summary, write_review_samples

ROOT = Path(__file__).parents[3]
NIGHT = ROOT / 'packages/viewer_publication/tests/fixtures/data-only-night/larger-capture-night-20261117-2ec7ae83a852.json'


def _write_table(directory: Path, name: str, rows: list[dict], schema: pa.Schema):
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), directory / name)


def test_write_review_samples_captures_large_removals_and_value_directions(tmp_path):
    base = tmp_path / 'base'
    cand = tmp_path / 'cand'
    bill_schema = pa.schema([
        ('bill_id', pa.string()),
        ('title', pa.string()),
        ('source_generation', pa.string()),
    ])
    rm_schema = pa.schema([('match_id', pa.string()), ('note', pa.string())])

    # Include 25 removals in recording_matches (> 20 inline cap) and 1 bill removal + 2 bill updates
    _write_table(base, 'bills.parquet', [
        {'bill_id': '117-hr-9248', 'title': 'Safe Access to Cash Act', 'source_generation': 'old'},
        {'bill_id': '119-hr-1', 'title': None, 'source_generation': 'old'},
        {'bill_id': '119-hr-2', 'title': 'Old Title', 'source_generation': 'old'},
    ], bill_schema)
    _write_table(cand, 'bills.parquet', [
        {'bill_id': '119-hr-1', 'title': 'Filled Title', 'source_generation': 'new'},
        {'bill_id': '119-hr-2', 'title': 'New Title', 'source_generation': 'new'},
        {'bill_id': '119-hr-3', 'title': 'Added Bill', 'source_generation': 'new'},
    ], bill_schema)

    _write_table(base, 'recording_matches.parquet', [
        {'match_id': f'm-{i:02d}', 'note': f'false match {i}'} for i in range(25)
    ], rm_schema)
    _write_table(cand, 'recording_matches.parquet', [], rm_schema)

    report = {
        'base_release': 'a' * 64,
        'candidate_release': 'b' * 64,
        'link_rule': {'ok': True},
        'files': {
            'bills.parquet': {
                'rows': {'base': 3, 'candidate': 3},
                'delta': 0,
                'groups': [
                    {'group': 'removed bills', 'cause': 'unexplained', 'count': -1, 'status': 'unexplained'},
                    {'group': 'added bills', 'cause': 'unexplained', 'count': 1, 'status': 'unexplained'},
                    {'group': 'changed title', 'cause': 'value differs on matched key', 'count': 2, 'status': 'unverified', 'value': True},
                    {'group': 'changed source_generation', 'cause': 'value differs on matched key', 'count': 2, 'status': 'unverified', 'value': True},
                ],
            },
            'recoveries.parquet': {
                'rows': {'base': 10, 'candidate': 10},
                'delta': 0,
                'groups': [
                    {'group': 'changed bytes, no key or value difference found', 'cause': 'unexplained', 'count': 0, 'status': 'unexplained', 'flag': True},
                ],
            },
            'recording_matches.parquet': {
                'rows': {'base': 25, 'candidate': 0},
                'delta': -25,
                'groups': [
                    {'group': 'removed keys', 'cause': 'no evidence given', 'count': -25, 'status': 'unverified'},
                ],
            },
        },
        'failing': [
            {'file': 'bills.parquet', 'group': 'removed bills', 'cause': 'unexplained', 'count': -1, 'status': 'unexplained'},
            {'file': 'bills.parquet', 'group': 'added bills', 'cause': 'unexplained', 'count': 1, 'status': 'unexplained'},
            {'file': 'bills.parquet', 'group': 'changed title', 'cause': 'value differs on matched key', 'count': 2, 'status': 'unverified', 'value': True},
            {'file': 'bills.parquet', 'group': 'changed source_generation', 'cause': 'value differs on matched key', 'count': 2, 'status': 'unverified', 'value': True},
            {'file': 'recoveries.parquet', 'group': 'changed bytes, no key or value difference found', 'cause': 'unexplained', 'count': 0, 'status': 'unexplained', 'flag': True},
            {'file': 'recording_matches.parquet', 'group': 'removed keys', 'cause': 'no evidence given', 'count': -25, 'status': 'unverified'},
        ],
    }

    samples = write_review_samples(report, base, cand, tmp_path / 'samples.json', max_per_group=5)
    assert (tmp_path / 'samples.json').exists()
    assert samples['tables']['bills.parquet']['removed'] == [
        {'bill_id': '117-hr-9248', 'title': 'Safe Access to Cash Act'}
    ]
    assert samples['tables']['bills.parquet']['added'] == [
        {'bill_id': '119-hr-3', 'title': 'Added Bill'}
    ]
    title_diff = samples['tables']['bills.parquet']['changed_columns']['title']
    assert title_diff['none_to_val'] == 1
    assert title_diff['val_to_none'] == 0
    assert title_diff['val_to_val'] == 1
    assert 'source_generation' not in samples['tables']['bills.parquet']['changed_columns']
    assert len(samples['tables']['recording_matches.parquet']['removed']) == 5
    assert samples['tables']['recording_matches.parquet']['removed'][0]['match_id'] == 'm-00'

    summary = render_review_summary(report, samples=samples)
    assert '## 1. Red Flags & Removals' in summary
    assert '117-hr-9248' in summary
    assert 'm-00' in summary
    assert '## 2. Content Changes to Spot-Check' in summary
    assert '1 filled, 0 cleared, 1 modified' in summary
    assert '## 3. Mechanical Pin Refreshes & Byte-Only Rewrites' in summary
    assert summary.index('117-hr-9248') < summary.index('<details>') < summary.index('recoveries.parquet')


def test_render_review_summary_works_on_stopped_night_fixture_and_cli(tmp_path):
    report = dict(json.loads(NIGHT.read_text()), link_rule={'ok': True})
    ev_dir = tmp_path / 'ev/candidate-1'
    ev_dir.mkdir(parents=True)
    (ev_dir / 'release-gate.json').write_text(json.dumps(report))
    out_md = tmp_path / 'nested/summary.md'
    assert cause_record.main(['summarize', '--evidence', str(tmp_path / 'ev'), '--out', str(out_md)]) == 0
    text = out_md.read_text()
    assert '## At a Glance' in text and '0 broken, changed, or demoted live links' in text

    # Pipes and newlines inside table cell values must never break GFM table columns.
    esc = render_review_summary(
        {
            'base_release': 'a' * 64,
            'candidate_release': 'b' * 64,
            'link_rule': {'ok': True},
            'files': {'bills.parquet': {'rows': {'base': 1, 'candidate': 1}, 'delta': 0, 'groups': [
                {'group': 'changed title', 'cause': 'val', 'count': 1, 'status': 'unverified', 'value': True},
            ]}},
            'failing': [{'file': 'bills.parquet', 'group': 'changed title', 'cause': 'line1\nwith | pipe', 'count': 1, 'status': 'unverified', 'value': True}],
        },
        samples={'tables': {'bills.parquet': {'changed_columns': {'title': {
            'none_to_val': 0, 'val_to_none': 0, 'val_to_val': 1,
            'samples': [{'key': 'k|1', 'before': 'a | b', 'after': 'c\nd|e'}],
        }}}}},
    )
    assert '\\|' in esc and 'c d\\|e' in esc


def test_require_release_gates_writes_summary_and_samples_on_stop(tmp_path, monkeypatch):
    from viewer_publication import release_gate

    monkeypatch.setattr(release_gate, 'write_meeting_updates', lambda *a, **kw: None)
    base = tmp_path / 'base'
    cand = tmp_path / 'cand'
    base.mkdir()
    cand.mkdir()
    (base / 'manifest.json').write_text(json.dumps({'release_id': 'a' * 64, 'files': []}))
    (cand / 'manifest.json').write_text(json.dumps({'release_id': 'b' * 64, 'files': []}))
    monkeypatch.setattr(
        'viewer_publication.release_comparison.compare',
        lambda *a, **kw: {
            'base_release': 'a' * 64,
            'candidate_release': 'b' * 64,
            'link_rule': {
                'ok': True,
                'missing': 0,
                'missing_keys': [],
                'dangling': 0,
                'dangling_keys': [],
                'published_and_retired': 0,
                'published_and_retired_keys': [],
                'unchecked': [],
                'changed': 0,
                'changed_answers': [],
                'lookup_changed': 0,
                'lookup_changed_answers': [],
                'address_changed': 0,
                'address_changed_answers': [],
                'proven_corrections': [],
            },
            'files': {'bills.parquet': {'rows': {'base': 1, 'candidate': 0}, 'delta': -1, 'groups': [
                {'group': 'removed bills', 'cause': 'unexplained', 'count': -1, 'status': 'unexplained'}
            ]}},
            'failing': [{'file': 'bills.parquet', 'group': 'removed bills', 'cause': 'unexplained', 'count': -1, 'status': 'unexplained'}],
        },
    )
    out = tmp_path / 'gate/release-gate.json'
    out.parent.mkdir()
    with pytest.raises(ValueError, match='Release gates refused'):
        require_release_gates(base, cand, None, report_path=out)
    assert (out.parent / 'release-gate-samples.json').exists()
    summary = (out.parent / 'release-gate-summary.md').read_text()
    assert 'removed bills' in summary and '-1' in summary
