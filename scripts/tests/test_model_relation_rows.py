"""model_relation_rows counts archive-model and model-scratch builds with verified metadata and input pins."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

PATH = Path(__file__).resolve().parents[1] / 'measure/model_relation_rows.py'
SPEC = importlib.util.spec_from_file_location('model_relation_rows_contract', PATH)
mrr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mrr)


def _pin(real_path: Path, recorded_path: Path | None = None) -> dict:
    raw = real_path.read_bytes()
    return {
        'path': str(recorded_path or real_path),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'size': len(raw),
    }


def _write_parquet(path: Path, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({'id': list(range(row_count))}), path)


def _iceberg_metadata(*, uuid: str, snapshot_id: int, total_records: int, schema_id: int = 0) -> bytes:
    payload = {
        'format-version': 2,
        'table-uuid': uuid,
        'schemas': [{'schema-id': schema_id, 'type': 'struct', 'fields': []}],
        'snapshots': [
            {
                'snapshot-id': snapshot_id,
                'schema-id': schema_id,
                'summary': {'operation': 'append', 'total-records': str(total_records)},
            }
        ],
    }
    return gzip.compress(json.dumps(payload).encode('utf-8'))


def test_archive_model_layout_and_remote_lake_metadata_with_verified_fallbacks(tmp_path):
    cache_root = tmp_path / '.cache/archive-release/build-a'
    (cache_root / 'archive-model').mkdir(parents=True)
    repo_root = tmp_path / 'repo'
    pruned_wt = tmp_path / 'pruned-wt'

    manifest_file = repo_root / 'model/jobs/spicy-regs/spicy-regs.json'
    manifest_file.parent.mkdir(parents=True)
    manifest_file.write_text(json.dumps({'tables': {'committees': {'rows': 819}}}))

    req_file = repo_root / 'model/jobs/inputs/recovery-requirements.parquet'
    _write_parquet(req_file, 3)

    prov_file = tmp_path / 'provenance/playlist-decisions.jsonl'
    prov_file.parent.mkdir(parents=True)
    prov_file.write_text('{"id": "1"}\n\n{"id": "2"}\n')

    lake_meta = tmp_path / 'lake-meta'
    lake_meta.mkdir()
    (lake_meta / 'playlist_records.metadata.json').write_bytes(
        _iceberg_metadata(uuid='uuid-playlist', snapshot_id=3020372319786105918, total_records=4362)
    )

    job = {
        'inputs': [
            {
                'name': 'playlist_records',
                'kind': 'native_table',
                'metadata_location': 's3://bucket/__r2/playlist_records/metadata/00002.gz.metadata.json',
                'table_uuid': 'uuid-playlist',
                'schema_id': 0,
                'snapshot': 3020372319786105918,
            },
            {
                'name': 'spicy_committees',
                'kind': 'parquet',
                'path': str(cache_root / '.archive-model-inputs-gone/62-committees.parquet'),
            },
            {
                'name': 'recovery_requirements_input',
                'kind': 'parquet',
                'path': str(cache_root / '.archive-model-inputs-gone/53-recovery-requirements.parquet'),
            },
            {
                'name': 'recording_decision_records',
                'kind': 'json_lines',
                'files': [
                    {
                        'key': 'provenance/recording_decisions/one.jsonl',
                        'path': str(cache_root / '.archive-model-inputs-gone/51-one.jsonl'),
                    }
                ],
            },
        ]
    }
    (cache_root / 'archive-model/job.json').write_text(json.dumps(job))

    spec = {
        'spicy_regs': _pin(manifest_file, pruned_wt / 'model/jobs/spicy-regs/spicy-regs.json'),
        'recovery_requirements': _pin(req_file, pruned_wt / 'model/jobs/inputs/recovery-requirements.parquet'),
        'recording_decision_files': [
            dict(_pin(prov_file), key='provenance/recording_decisions/one.jsonl')
        ],
    }
    (cache_root / 'model-spec.json').write_text(json.dumps(spec))
    (cache_root / 'steps.jsonl').write_text(
        '\n'.join(
            json.dumps(ev)
            for ev in [
                {'event': 'step', 'name': 'selected_playlist_records', 'storage': 'memory', 'rows': 4362},
                {'event': 'step', 'name': 'inline_view', 'storage': 'view', 'rows': 999},
                {'event': 'step', 'name': 'check_query', 'storage': 'query', 'rows': 1},
            ]
        )
        + '\n'
    )

    result = mrr.relation_rows(cache_root, lake_metadata=lake_meta, repo_root=repo_root)
    assert result == {
        'source': '.cache/archive-release/build-a',
        'head': None,
        'uncommitted': [],
        'rows': {
            'playlist_records': 4362,
            'recording_decision_records': 2,
            'recovery_requirements_input': 3,
            'selected_playlist_records': 4362,
            'spicy_committees': 819,
        },
    }

    proc = subprocess.run(
        [sys.executable, str(PATH), str(cache_root), '--lake-metadata', str(lake_meta)],
        capture_output=True,
        text=True,
    )
    # Using default repo_root in subprocess would not find tmp_path/repo, so verify CLI flag --repo-root or local pin:
    spec['spicy_regs'] = _pin(manifest_file)
    spec['recovery_requirements'] = _pin(req_file)
    (cache_root / 'model-spec.json').write_text(json.dumps(spec))
    proc = subprocess.run(
        [sys.executable, str(PATH), str(cache_root), '--lake-metadata', str(lake_meta)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout) == result


def test_legacy_model_scratch_layout_and_local_gzip_metadata(tmp_path):
    run = tmp_path / '.cache/archive-release/legacy-run'
    (run / 'model-scratch').mkdir(parents=True)
    local_meta = tmp_path / 'local-lake/00001.gz.metadata.json'
    local_meta.parent.mkdir(parents=True)
    local_meta.write_bytes(_iceberg_metadata(uuid='uuid-cap', snapshot_id=77, total_records=120))

    (run / 'model-scratch/job.json').write_text(
        json.dumps(
            {
                'inputs': [
                    {
                        'name': 'captures_input',
                        'kind': 'native_table',
                        'metadata_location': str(local_meta),
                        'table_uuid': 'uuid-cap',
                        'schema_id': 0,
                        'snapshot': 77,
                    },
                    {
                        'name': 'page_signals',
                        'kind': 'json_lines',
                        'files': [{'key': 'page_signals', 'path': str(tmp_path / 'page_signals.jsonl')}],
                    },
                ]
            }
        )
    )
    (tmp_path / 'page_signals.jsonl').write_text('{"id": "1"}\n')
    (run / 'model-spec.json').write_text(json.dumps({}))
    (run / 'steps.jsonl').write_text(
        json.dumps({'event': 'step', 'name': 'captures', 'storage': 'spill', 'rows': 120}) + '\n'
    )
    (run / 'head.txt').write_text('abc1234\n M model/sql/a.sql\n')

    assert mrr.relation_rows(run) == {
        'source': '.cache/archive-release/legacy-run',
        'head': 'abc1234',
        'uncommitted': ['model/sql/a.sql'],
        'rows': {'captures': 120, 'captures_input': 120, 'page_signals': 1},
    }
    overlaid = mrr.relation_rows(run, overlay_registries=True)
    assert overlaid['rows']['page_signals'] == 1  # never overwrites a relation measured in RUN
    assert 'recovered_file_roles' in overlaid['overlaid_registries']
    assert overlaid['rows']['recovered_file_roles'] >= 0


def test_refuses_missing_or_mismatched_lake_metadata_and_tampered_fallback(tmp_path):
    run = tmp_path / '.cache/archive-release/bad-run'
    (run / 'archive-model').mkdir(parents=True)
    lake_meta = tmp_path / 'lake-meta'
    lake_meta.mkdir()

    base_item = {
        'name': 'playlist_records',
        'kind': 'native_table',
        'metadata_location': 's3://bucket/playlist/00001.gz.metadata.json',
        'table_uuid': 'uuid-expected',
        'schema_id': 0,
        'snapshot': 101,
    }
    (run / 'archive-model/job.json').write_text(json.dumps({'inputs': [base_item]}))
    (run / 'model-spec.json').write_text(json.dumps({}))
    (run / 'steps.jsonl').write_text('')

    # Missing --lake-metadata on s3:// pin fails closed.
    with pytest.raises(ValueError, match='playlist_records'):
        mrr.relation_rows(run)

    # Wrong table-uuid fails closed.
    (lake_meta / 'playlist_records.metadata.json').write_bytes(
        _iceberg_metadata(uuid='uuid-wrong', snapshot_id=101, total_records=10)
    )
    with pytest.raises(ValueError, match='table_uuid|UUID'):
        mrr.relation_rows(run, lake_metadata=lake_meta)

    # Wrong snapshot-id fails closed.
    (lake_meta / 'playlist_records.metadata.json').write_bytes(
        _iceberg_metadata(uuid='uuid-expected', snapshot_id=999, total_records=10)
    )
    with pytest.raises(ValueError, match='snapshot'):
        mrr.relation_rows(run, lake_metadata=lake_meta)

    # Tampered repo fallback file fails SHA-256 verification.
    repo_root = tmp_path / 'repo'
    req_file = repo_root / 'model/jobs/inputs/req.parquet'
    _write_parquet(req_file, 5)
    bad_pin = _pin(req_file, tmp_path / 'gone-wt/model/jobs/inputs/req.parquet')
    _write_parquet(req_file, 9)  # mutate bytes after pin was recorded
    (run / 'archive-model/job.json').write_text(
        json.dumps(
            {
                'inputs': [
                    {
                        'name': 'recovery_requirements_input',
                        'kind': 'parquet',
                        'path': str(run / '.archive-model-inputs-gone/req.parquet'),
                    }
                ]
            }
        )
    )
    (run / 'model-spec.json').write_text(json.dumps({'recovery_requirements': bad_pin}))
    with pytest.raises(ValueError, match='sha256|digest|size'):
        mrr.relation_rows(run, repo_root=repo_root)
