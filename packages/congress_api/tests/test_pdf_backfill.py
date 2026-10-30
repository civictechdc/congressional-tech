"""B13 contract tests: streamed .pdf copies through BodyStore and verification provenance."""
from __future__ import annotations

import gzip
from hashlib import md5, sha256
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake.readings import current_version
from congress_api.retention.body_store import BodyStore, LocalAdapter, R2Adapter
from congress_api.retention.pdf_backfill import (
    apply_staged,
    backfill_uncompressed_pdfs,
    select_pdf_candidates,
)
from congress_api.retention.pdf_tools import PdfToolError
from congress_api.retention.provenance import field, run_job
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).resolve().parents[3]


def _engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


class _MockR2S3Client:
    def __init__(self):
        self.meta = SimpleNamespace(
            config=SimpleNamespace(retries={'total_max_attempts': 1}),
            events=SimpleNamespace(register_first=lambda *args, **kwargs: None),
        )
        self.objects: dict[tuple[str, str], dict] = {}
        self.put_calls: list[dict] = []
        self.get_calls: list[tuple[str, str]] = []
        self.head_calls: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str):
        self.head_calls.append((Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise ClientError({'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject')
        obj = self.objects[(Bucket, Key)]
        return {'ETag': obj['ETag'], 'ContentLength': len(obj['Body'])}

    def get_object(self, *, Bucket: str, Key: str, **kwargs):
        self.get_calls.append((Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'NoSuchKey'}}, 'GetObject')
        obj = self.objects[(Bucket, Key)]
        raw = obj['Body']
        return {
            'Body': io.BytesIO(raw),
            'ContentLength': len(raw),
            'ETag': obj['ETag'],
        }

    def put_object(self, **kwargs):
        bucket = kwargs['Bucket']
        key = kwargs['Key']
        body = kwargs['Body']
        raw = body.read() if hasattr(body, 'read') else bytes(body)
        if kwargs.get('IfNoneMatch') == '*' and (bucket, key) in self.objects:
            self.put_calls.append({**kwargs, 'Body': raw})
            raise ClientError(
                {'Error': {'Code': 'PreconditionFailed', 'Message': 'PreconditionFailed'}},
                'PutObject',
            )
        etag = f'"{md5(raw).hexdigest()}"'
        self.objects[(bucket, key)] = {
            'Body': raw,
            'ETag': etag,
            'ContentType': kwargs.get('ContentType'),
            'CacheControl': kwargs.get('CacheControl'),
            'ContentDisposition': kwargs.get('ContentDisposition'),
        }
        self.put_calls.append({**kwargs, 'Body': raw})
        return {'ETag': etag}


def _seed_gz(root: Path, payload: bytes, *, digest: str | None = None) -> tuple[str, str, str, bytes]:
    digest = digest or sha256(payload).hexdigest()
    gz_key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    pdf_key = f'bodies/sha256/{digest[:2]}/{digest}.pdf'
    gz_bytes = gzip.compress(payload, compresslevel=1, mtime=0)
    target = root / gz_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gz_bytes)
    return digest, gz_key, pdf_key, gz_bytes


def test_local_body_store_pdf_backfill_dry_run_and_verification_records(tmp_path: Path):
    raw_root = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_root))
    pdf_bytes = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
    pdf_sha, gz_key, pdf_key, gz_bytes = _seed_gz(raw_root, pdf_bytes)

    dry = backfill_uncompressed_pdfs(
        store,
        [pdf_sha],
        checked_at='2026-10-30T00:00:00Z',
        dry_run=True,
    )
    assert dry['would_backfill'] == [pdf_key]
    assert dry['backfilled'] == []
    assert dry['provenance_key'] is None
    assert not (raw_root / pdf_key).exists()

    first = backfill_uncompressed_pdfs(
        store,
        [pdf_sha],
        checked_at='2026-10-30T00:00:00Z',
        dry_run=False,
    )
    assert first['backfilled'] == [pdf_key]
    assert first['already_present'] == []
    assert first['mismatches'] == []
    assert (raw_root / pdf_key).read_bytes() == pdf_bytes
    assert (raw_root / gz_key).read_bytes() == gz_bytes
    assert first['provenance_key'] is not None
    prov_path = raw_root / first['provenance_key']
    assert prov_path.is_file()

    records = [json.loads(line) for line in prov_path.read_text(encoding='utf-8').splitlines()]
    assert len(records) == 2
    by_key = {row['key']: row for row in records}
    assert by_key[gz_key] == dict(
        key=gz_key,
        size=len(gz_bytes),
        etag=md5(gz_bytes).hexdigest(),
        sha256_verified=True,
        stored_sha256=sha256(gz_bytes).hexdigest(),
        checked_at='2026-10-30T00:00:00+00:00',
        job='pdf-backfill',
    )
    assert by_key[pdf_key] == dict(
        key=pdf_key,
        size=len(pdf_bytes),
        etag=md5(pdf_bytes).hexdigest(),
        sha256_verified=True,
        stored_sha256=pdf_sha,
        intact=True,
        checked_at='2026-10-30T00:00:00+00:00',
        job='pdf-backfill',
    )

    # Feeding the verification inventory skips already-copied .pdf keys without re-reading.
    second = backfill_uncompressed_pdfs(
        store,
        [pdf_sha],
        verification_files=[dict(key=first['provenance_key'], path=str(prov_path))],
        checked_at='2026-10-30T00:05:00Z',
    )
    assert second['candidates'] == 0
    assert second['backfilled'] == []
    assert second['provenance_key'] is None


def test_r2_pdf_backfill_no_pre_upload_head_and_412_checks_expected_md5():
    s3 = _MockR2S3Client()
    bucket = 'congressional-tech-raw'
    store = BodyStore(R2Adapter(s3, bucket))

    pdf_bytes = b'%PDF-1.5\n% mocked r2 pdf payload\n%%EOF\n'
    pdf_sha = sha256(pdf_bytes).hexdigest()
    gz_key = f'bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.gz'
    pdf_key = f'bodies/sha256/{pdf_sha[:2]}/{pdf_sha}.pdf'

    gz_bytes = gzip.compress(pdf_bytes, compresslevel=1, mtime=0)
    s3.objects[(bucket, gz_key)] = {
        'Body': gz_bytes,
        'ETag': f'"{md5(gz_bytes).hexdigest()}"',
    }

    result = backfill_uncompressed_pdfs(store, [pdf_sha], checked_at='2026-10-30T00:00:00Z')
    assert result['backfilled'] == [pdf_key]
    assert s3.head_calls == []
    stored_pdf = s3.objects[(bucket, pdf_key)]
    assert stored_pdf['Body'] == pdf_bytes
    assert stored_pdf['ContentType'] == 'application/pdf'
    assert stored_pdf['CacheControl'] == 'public, max-age=31536000, immutable'
    assert stored_pdf['ContentDisposition'] == 'inline'

    # Re-running without prior verification hits 412 and verifies MD5 with exactly one HEAD.
    s3.head_calls.clear()
    again = backfill_uncompressed_pdfs(store, [pdf_sha], checked_at='2026-10-30T00:01:00Z')
    assert again['already_present'] == [pdf_key]
    assert again['backfilled'] == []
    assert s3.head_calls == [(bucket, pdf_key)]

    # If the existing .pdf object on 412 has a wrong MD5, the single HEAD check refuses it.
    s3.objects[(bucket, pdf_key)]['ETag'] = '"' + ('0' * 32) + '"'
    with pytest.raises(ValueError, match='Existing PDF copy differs from expected MD5 or size'):
        backfill_uncompressed_pdfs(store, [pdf_sha], checked_at='2026-10-30T00:02:00Z')


def test_pdf_backfill_records_key_mismatch_and_continues(tmp_path: Path):
    raw_root = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_root))

    claimed_pdf = b'%PDF-1.4\nexpected content\n%%EOF\n'
    claimed_sha = sha256(claimed_pdf).hexdigest()
    tampered_pdf = b'%PDF-1.4\ntampered content\n%%EOF\n'
    _, bad_gz_key, bad_pdf_key, bad_gz_bytes = _seed_gz(raw_root, tampered_pdf, digest=claimed_sha)

    good_pdf = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
    good_sha, good_gz_key, good_pdf_key, _ = _seed_gz(raw_root, good_pdf)

    report = backfill_uncompressed_pdfs(
        store,
        [claimed_sha, good_sha],
        checked_at='2026-10-30T00:00:00Z',
    )
    assert report['mismatches'] == [dict(key=bad_gz_key, error='identity_mismatch')]
    assert report['backfilled'] == [good_pdf_key]
    assert not (raw_root / bad_pdf_key).exists()
    assert (raw_root / good_pdf_key).read_bytes() == good_pdf

    prov_path = raw_root / report['provenance_key']
    records = {row['key']: row for row in map(json.loads, prov_path.read_text().splitlines())}
    assert records[bad_gz_key]['sha256_verified'] is False
    assert records[bad_gz_key]['error'] == 'identity_mismatch'
    assert records[bad_gz_key]['stored_sha256'] == sha256(bad_gz_bytes).hexdigest()
    assert bad_pdf_key not in records
    assert records[good_gz_key]['sha256_verified'] is True
    assert records[good_pdf_key]['sha256_verified'] is True
    assert records[good_pdf_key]['intact'] is True


def test_pdf_backfill_intact_checks_eof_and_propagates_tool_errors(tmp_path: Path, monkeypatch):
    raw_root = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_root))

    truncated_pdf = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\n'
    trunc_sha, _, trunc_pdf_key, _ = _seed_gz(raw_root, truncated_pdf)

    report = backfill_uncompressed_pdfs(store, [trunc_sha], checked_at='2026-10-30T00:00:00Z')
    assert report['backfilled'] == [trunc_pdf_key]
    prov_path = raw_root / report['provenance_key']
    records = {row['key']: row for row in map(json.loads, prov_path.read_text().splitlines())}
    assert records[trunc_pdf_key]['intact'] is False

    # Tool resource failure must propagate rather than record a false damage verdict.
    def _boom(_data):
        raise PdfToolError('pdfinfo timed out')

    monkeypatch.setattr('congress_api.retention.pdf_backfill.check_pdf', _boom)
    with pytest.raises(PdfToolError, match='timed out'):
        backfill_uncompressed_pdfs(store, [trunc_sha], checked_at='2026-10-30T00:01:00Z')


def test_select_pdf_candidates_and_model_verification_sql_integration(tmp_path: Path):
    raw_root = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_root))
    pdf_bytes = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
    pdf_sha, gz_key, pdf_key, _ = _seed_gz(raw_root, pdf_bytes)

    bare_pdf = b'%PDF-1.7\nbare pdf already uncompressed\n%%EOF\n'
    bare_sha = sha256(bare_pdf).hexdigest()
    html_bytes = b'<html><body>not a pdf</body></html>'
    html_sha = sha256(html_bytes).hexdigest()

    sniff_ver = current_version('sniff')
    captures_path = tmp_path / 'captures.parquet'
    captures_schema = pa.schema([
        ('sha256', pa.binary(32)),
        ('stored_suffix', pa.string()),
        ('stored_bytes', pa.int64()),
        ('bytes', pa.int64()),
        ('sniffed_format', pa.string()),
        ('sniff_version', pa.string()),
        ('intact', pa.bool_()),
    ])
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    sha256=bytes.fromhex(pdf_sha),
                    stored_suffix='.gz',
                    stored_bytes=100,
                    bytes=len(pdf_bytes),
                    sniffed_format=None,
                    sniff_version=None,
                    intact=None,
                ),
                dict(
                    sha256=bytes.fromhex(bare_sha),
                    stored_suffix='',
                    stored_bytes=len(bare_pdf),
                    bytes=len(bare_pdf),
                    sniffed_format='pdf',
                    sniff_version=sniff_ver,
                    intact=True,
                ),
                dict(
                    sha256=bytes.fromhex(html_sha),
                    stored_suffix='.gz',
                    stored_bytes=50,
                    bytes=len(html_bytes),
                    sniffed_format=None,
                    sniff_version=None,
                    intact=None,
                ),
            ],
            schema=captures_schema,
        ),
        captures_path,
    )

    readings_path = tmp_path / 'readings.parquet'
    readings_schema = pa.schema([
        ('body_sha', pa.binary(32)),
        ('parser', pa.string()),
        ('parser_version', pa.string()),
        ('status', pa.string()),
        ('format', pa.string()),
        ('intact', pa.bool_()),
        ('error_type', pa.string()),
    ])
    pq.write_table(
        pa.Table.from_pylist(
            [
                dict(
                    body_sha=bytes.fromhex(pdf_sha),
                    parser='sniff',
                    parser_version=sniff_ver,
                    status='completed',
                    format='pdf',
                    intact=None,
                    error_type=None,
                ),
                dict(
                    body_sha=bytes.fromhex(html_sha),
                    parser='sniff',
                    parser_version=sniff_ver,
                    status='completed',
                    format='html',
                    intact=True,
                    error_type=None,
                ),
            ],
            schema=readings_schema,
        ),
        readings_path,
    )

    engine = _engine()
    candidates = select_pdf_candidates(
        captures=captures_path,
        readings=readings_path,
        engine=engine,
        work=tmp_path / 'plan-only',
        sniff_version=sniff_ver,
    )
    assert candidates == [pdf_sha]

    report = backfill_uncompressed_pdfs(
        store,
        captures=captures_path,
        readings=readings_path,
        engine=engine,
        work=tmp_path / 'run',
        checked_at='2026-10-30T00:00:00Z',
        sniff_version=sniff_ver,
    )
    assert report['backfilled'] == [pdf_key]
    prov_file = raw_root / report['provenance_key']

    # Verify model SQL views consume the emitted verification records cleanly.
    v_schema = dict(key='Utf8', size='Int64', intact='Boolean', sha256_verified='Boolean', checked_at='Utf8')
    sql_res = run_job(
        tmp_path / 'model-check',
        engine,
        inputs=[
            dict(
                name='verification_records',
                kind='json_lines',
                files=[dict(key=report['provenance_key'], path=str(prov_file))],
                schema=dict(fields=[field(k, v) for k, v in v_schema.items()], metadata={}),
            )
        ],
        steps=[
            dict(name='copy_verifications', sql=(ROOT / 'model/sql/copy-verifications.sql').read_text(), materialize=True),
            dict(name='storage_verifications', sql=(ROOT / 'model/sql/storage-verifications.sql').read_text(), materialize=True),
            dict(name='verification_conflicts', sql=(ROOT / 'model/sql/verification-conflicts.sql').read_text(), materialize=True),
        ],
        outputs=[],
        queries=[
            dict(name='copies', sql='SELECT body_sha, intact FROM copy_verifications'),
            dict(name='storage', sql='SELECT key, size FROM storage_verifications ORDER BY key'),
            dict(name='conflicts', sql='SELECT count(*) AS n FROM verification_conflicts'),
        ],
    )
    assert sql_res['copies'] == [dict(body_sha=pdf_sha, intact=True)]
    assert {r['key'] for r in sql_res['storage']} == {gz_key, pdf_key}
    assert sql_res['conflicts'][0]['n'] == 0


def test_backfill_cli_stage_and_apply_staged(tmp_path: Path):
    from viewer_publication import backfill_uncompressed_pdfs as cli_mod

    store_dir = tmp_path / 'local-store'
    pdf_bytes = b'%PDF-1.7\ncli stage test\n%%EOF\n'
    pdf_sha, _, pdf_key, _ = _seed_gz(store_dir, pdf_bytes)

    candidates_file = tmp_path / 'candidates.json'
    candidates_file.write_text(json.dumps([pdf_sha]), encoding='utf-8')
    work_dir = tmp_path / 'work'
    report_file = tmp_path / 'report.json'

    rc = cli_mod.main([
        '--candidates', str(candidates_file),
        '--local-store', str(store_dir),
        '--work', str(work_dir),
        '--stage-only',
        '--output', str(report_file),
    ])
    assert rc == 0
    staged = json.loads(report_file.read_text(encoding='utf-8'))
    assert staged['backfilled'] == [pdf_key]
    assert not (store_dir / staged['provenance_key']).exists()

    rc_apply = cli_mod.main([
        '--local-store', str(store_dir),
        '--work', str(work_dir),
        '--apply-staged',
    ])
    assert rc_apply == 0
    assert (store_dir / staged['provenance_key']).is_file()
    assert (store_dir / pdf_key).read_bytes() == pdf_bytes
