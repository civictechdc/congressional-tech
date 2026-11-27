"""Tests for zero-copy DDK + Iceberg v2 publication sidecar (`ct-zg0z`)."""
from __future__ import annotations

from copy import deepcopy
from hashlib import md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import threading

from botocore.config import Config
from botocore.exceptions import ClientError
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication import archive_ddk_sidecar as sidecar
from viewer_publication import archive_odcs, archive_publish

FIXTURE_RELEASE_DIR = Path(__file__).resolve().parents[3] / 'model' / 'fixtures' / 'archive-contract' / 'current'
WRAPPER_SCRIPT = Path(__file__).resolve().parents[3] / 'scripts' / 'publication' / 'publish-ddk-sidecar.py'
_HAS_DDK_BRIDGE = sidecar.ddk_bridge_available()


class _BytesBody:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, n: int | None = -1) -> bytes:
        return self._buf.read(-1 if n is None else n)

    def close(self) -> None:
        self._buf.close()


class _InMemoryBotoClient:
    """Minimal boto3 S3-compatible client supporting ETag CAS preconditions and Range reads."""

    def __init__(self, store: dict[str, dict[str, object]] | None = None, *, max_attempts: int = 1):
        self.meta = SimpleNamespace(config=Config(retries={'total_max_attempts': max_attempts}))
        self.store: dict[str, dict[str, object]] = store if store is not None else {}
        self.put_calls: list[dict[str, object]] = []

    def _client_error(self, code: str, message: str, status_code: int) -> ClientError:
        return ClientError(
            {
                'Error': {'Code': code, 'Message': message},
                'ResponseMetadata': {'HTTPStatusCode': status_code},
            },
            'S3Op',
        )

    def _clean(self, val: str) -> str:
        return val.strip().removeprefix('W/').strip('"')

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        item = self.store.get(Key)
        if item is None:
            raise self._client_error('NoSuchKey', f'Missing {Key}', 404)
        body = bytes(item['body'])
        return {
            'ETag': f'"{item["etag"]}"',
            'ContentLength': len(body),
            'ContentType': item['content_type'],
        }

    def get_object(self, *, Bucket: str, Key: str, Range: str | None = None, IfMatch: str | None = None) -> dict[str, object]:
        item = self.store.get(Key)
        if item is None:
            raise self._client_error('NoSuchKey', f'Missing {Key}', 404)
        if IfMatch is not None and self._clean(IfMatch) != item['etag']:
            raise self._client_error('PreconditionFailed', f'ETag mismatch for {Key}', 412)
        raw = bytes(item['body'])
        if Range is not None:
            assert Range.startswith('bytes=')
            start_s, end_s = Range.removeprefix('bytes=').split('-', 1)
            start = int(start_s)
            end = int(end_s) if end_s else len(raw) - 1
            raw = raw[start:end + 1]
        return {
            'Body': _BytesBody(raw),
            'ETag': f'"{item["etag"]}"',
            'ContentLength': len(raw),
            'ContentType': item['content_type'],
        }

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str = 'application/octet-stream',
        ContentLength: int | None = None,
        CacheControl: str | None = None,
        IfMatch: str | None = None,
        IfNoneMatch: str | None = None,
    ) -> dict[str, object]:
        existing = self.store.get(Key)
        if IfNoneMatch == '*' and existing is not None:
            raise self._client_error('PreconditionFailed', f'Object already exists at {Key}', 412)
        if IfMatch is not None:
            if existing is None or self._clean(IfMatch) != existing['etag']:
                raise self._client_error('PreconditionFailed', f'CAS mismatch at {Key}', 412)
        payload = bytes(Body)
        etag = md5(payload).hexdigest()
        self.store[Key] = {
            'body': payload,
            'etag': etag,
            'content_type': ContentType,
            'cache_control': CacheControl,
        }
        self.put_calls.append({
            'Bucket': Bucket,
            'Key': Key,
            'ContentType': ContentType,
            'CacheControl': CacheControl,
            'IfMatch': IfMatch,
            'IfNoneMatch': IfNoneMatch,
            'bytes': len(payload),
        })
        return {'ETag': f'"{etag}"'}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.store.pop(Key, None)
        return {}


class _LoopbackR2Server:
    """In-process loopback HTTP/R2 origin supporting anonymous GET, HEAD, and Byte-Range 206 readback."""

    def __init__(self, store: dict[str, dict[str, object]]):
        self.store = store
        self.http_gets: list[str] = []
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

            def _serve(self, *, send_body: bool) -> None:
                key = self.path.split('?', 1)[0].lstrip('/')
                parent.http_gets.append(key)
                item = parent.store.get(key)
                if item is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = bytes(item['body'])
                total = len(raw)
                range_hdr = self.headers.get('Range')
                if range_hdr and range_hdr.startswith('bytes='):
                    start_s, end_s = range_hdr.removeprefix('bytes=').split('-', 1)
                    start = int(start_s)
                    end = min(int(end_s) if end_s else total - 1, total - 1)
                    slice_bytes = raw[start:end + 1]
                    self.send_response(206)
                    self.send_header('Content-Type', str(item['content_type']))
                    self.send_header('Content-Length', str(len(slice_bytes)))
                    self.send_header('Content-Range', f'bytes {start}-{end}/{total}')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('ETag', f'"{item["etag"]}"')
                    self.end_headers()
                    if send_body:
                        self.wfile.write(slice_bytes)
                    return

                self.send_response(200)
                self.send_header('Content-Type', str(item['content_type']))
                self.send_header('Content-Length', str(total))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('ETag', f'"{item["etag"]}"')
                self.end_headers()
                if send_body:
                    self.wfile.write(raw)

            def do_GET(self) -> None:
                self._serve(send_body=True)

            def do_HEAD(self) -> None:
                self._serve(send_body=False)

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = int(self._server.server_port)
        self.base_url = f'http://127.0.0.1:{self.port}'
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> _LoopbackR2Server:
        self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _sample_body_text_pointer(
    release_id: str,
    *,
    detail_entry: dict[str, object] | None = None,
    payload: bytes = b'PARQUET-STUB-BODY-TEXT',
) -> dict[str, object]:
    digest = sha256(payload).hexdigest()
    pointer: dict[str, object] = {
        'version': 1,
        'release_id': release_id,
        'key': f'derived/body_text/{digest}.parquet',
        'sha256': digest,
        'bytes': len(payload),
        'rows': 42,
        'footer_sha256': sha256(b'footer').hexdigest(),
        'selection': {'corpus': 'serenedb_documents', 'ticket': 'ct-0a35'},
        'coverage': {'documents': 42},
    }
    if detail_entry is not None:
        pointer['detail'] = {'sha256': detail_entry['sha256'], 'size': detail_entry['size']}
    return pointer


def _parquet_bytes_from_schema(schema: pa.Schema) -> bytes:
    table = pa.table({field.name: pa.array([], type=field.type) for field in schema})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _write_empty_parquet_from_schema(path: Path, schema: pa.Schema) -> dict[str, object]:
    raw = _parquet_bytes_from_schema(schema)
    path.write_bytes(raw)
    return {
        'name': path.name,
        'sha256': sha256(raw).hexdigest(),
        'md5': md5(raw).hexdigest(),
        'size': len(raw),
        'rows': 0,
    }


def _build_fixture_five_table_dir(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    manifest = json.loads((FIXTURE_RELEASE_DIR / 'manifest.json').read_text(encoding='utf-8'))
    target_names = {'committees.parquet', 'links.parquet', 'recoveries.parquet', 'sources.parquet', 'urls.parquet'}
    subset_manifest = deepcopy(manifest)
    subset_manifest['files'] = [e for e in manifest['files'] if e['name'] in target_names]
    out_dir = tmp_path / 'release'
    out_dir.mkdir(parents=True, exist_ok=True)
    for entry in subset_manifest['files']:
        (out_dir / entry['name']).write_bytes((FIXTURE_RELEASE_DIR / entry['name']).read_bytes())
    (out_dir / 'manifest.json').write_text(json.dumps(subset_manifest, indent=2), encoding='utf-8')
    return out_dir, subset_manifest


# ---------------------------------------------------------------------------
# Pure-CT offline tests (must run inside CT frozen .venv without ddk installed)
# ---------------------------------------------------------------------------

def test_build_sidecar_descriptor_deterministic_zero_copy_and_body_text_binding(tmp_path: Path) -> None:
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    release_id = manifest['release_id']
    pointer = _sample_body_text_pointer(release_id)
    pointer_path = tmp_path / 'body_text_current.json'
    pointer_path.write_text(json.dumps(pointer), encoding='utf-8')

    # Full fixture manifest includes non-Parquet metadata entries ('schema.json', 'capture_scope.json')
    desc_raw_fixture = sidecar.build_sidecar_descriptor(
        FIXTURE_RELEASE_DIR,
        tables=['committees', 'links', 'recoveries', 'sources', 'urls'],
    )
    assert [t['table_name'] for t in desc_raw_fixture['tables']] == ['committees', 'links', 'recoveries', 'sources', 'urls']

    desc_a = sidecar.build_sidecar_descriptor(rel_dir, body_text_pointer=pointer_path)
    desc_b = sidecar.build_sidecar_descriptor(rel_dir, body_text_pointer=pointer)
    assert json.dumps(desc_a, sort_keys=True) == json.dumps(desc_b, sort_keys=True)

    assert desc_a['zero_copy'] is True
    assert desc_a['sidecar_prefix'] == 'ddk-catalogs/congressional-tech'
    assert desc_a['base_url'] == 'https://congressional-data.spicygov.ai'
    assert desc_a['parity_summary']['status'] == 'passed'
    assert desc_a['parity_summary']['canonical_parity_passed'] is True
    assert desc_a['parity_summary']['passed_tables'] == ['committees', 'links', 'recoveries', 'sources', 'urls']
    assert [t['table_name'] for t in desc_a['tables']] == ['committees', 'links', 'recoveries', 'sources', 'urls']

    for t in desc_a['tables']:
        assert len(t['members']) == 1
        m = t['members'][0]
        assert m['remote_key'] == f'viewer-publications/releases/{release_id}/{t["table_name"]}.parquet'
        assert m['url'] == f'https://congressional-data.spicygov.ai/viewer-publications/releases/{release_id}/{t["table_name"]}.parquet'

    # BodyTextSSOT / ct-0a35 binding attached in descriptor & ODPS product without adding export.parquet table
    assert all('body_text' not in t['table_name'] and 'export' not in t['table_name'] for t in desc_a['tables'])
    assert desc_a['body_text_ssot']['sha256'] == pointer['sha256']
    assert desc_a['body_text_ssot']['release_id'] == release_id
    assert desc_a['ct_0a35_binding']['iterator'] == sidecar.SERENEDB_ITERATOR_SYMBOL
    product = desc_a['product']
    custom_map = {item['property']: item['value'] for item in product['customProperties']}
    assert custom_map['bodyTextSsot']['sha256'] == pointer['sha256']
    assert any('ct-0a35' in vs['tags'] for vs in product['context']['verifiedStatements'])
    assert pointer['key'] in product['context']['instructions']


def test_capture_profile_v2_extends_url_state_contract(tmp_path: Path) -> None:
    rel_dir = tmp_path / 'rel-v2'
    rel_dir.mkdir()
    url_contract_v1 = archive_odcs.export_odcs_contracts(include_capture_eligibility=False)['table_contracts']['url_state']
    url_contract_v2 = archive_odcs.export_odcs_contracts(include_capture_eligibility=True)['table_contracts']['url_state']
    schema_v2 = archive_odcs.odcs_object_to_arrow_schema(sidecar._schema_object_from_contract(url_contract_v2, 'url_state'), pa=pa)
    entry = _write_empty_parquet_from_schema(rel_dir / 'url_state.parquet', schema_v2)

    release_id = 'a' * 64
    manifest = {'schema_version': 1, 'release_id': release_id, 'files': [entry]}
    (rel_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    # Without capture_profile.json v2, extra capture eligibility columns MUST fail closed!
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.build_sidecar_descriptor(rel_dir)

    # With capture_profile.json version == 2, url_state contract picks up the 3 capture eligibility fields and passes
    (rel_dir / 'capture_profile.json').write_text(json.dumps({'version': 2}), encoding='utf-8')
    desc = sidecar.build_sidecar_descriptor(rel_dir)
    assert desc['capture_profile']['version'] == 2
    assert desc['capture_profile']['include_capture_eligibility'] is True
    assert desc['parity_summary']['status'] == 'passed'
    prop_names = {p['name'] for p in desc['tables'][0]['contract']['schema'][0]['properties']}
    assert {'capture_disposition', 'capture_reason', 'capture_decision_id'} <= prop_names
    v1_names = {p['name'] for p in url_contract_v1['schema'][0]['properties']}
    assert not ({'capture_disposition', 'capture_reason', 'capture_decision_id'} & v1_names)


def test_body_text_ssot_rejects_mismatched_release_and_detail(tmp_path: Path) -> None:
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    release_id = manifest['release_id']
    wrong_pointer = _sample_body_text_pointer('b' * 64)
    with pytest.raises(ValueError, match='does not bind to release'):
        sidecar.build_sidecar_descriptor(rel_dir, body_text_pointer=wrong_pointer)

    # When manifest includes detail.parquet, BodyTextSSOT pointer MUST match its sha256 + size
    detail_manifest = deepcopy(manifest)
    detail_entry = {'name': 'detail.parquet', 'sha256': 'c' * 64, 'size': 1234, 'rows': 5}
    detail_manifest['files'] = [detail_entry]
    mismatched_detail_ptr = _sample_body_text_pointer(
        release_id, detail_entry={'sha256': 'd' * 64, 'size': 1234},
    )
    with pytest.raises(ValueError, match='detail pin .* disagrees'):
        sidecar.validate_body_text_ssot_binding(
            mismatched_detail_ptr, release_id=release_id, manifest=detail_manifest,
        )

    valid_detail_ptr = _sample_body_text_pointer(release_id, detail_entry=detail_entry)
    bound = sidecar.validate_body_text_ssot_binding(
        valid_detail_ptr, release_id=release_id, manifest=detail_manifest,
    )
    assert bound is not None
    assert bound['detail'] == {'sha256': 'c' * 64, 'size': 1234}


def test_documented_sql_drift_reported_without_faking_parity_and_unexpected_drift_fails_closed(tmp_path: Path) -> None:
    contracts = archive_odcs.export_odcs_contracts(include_capture_eligibility=False)['table_contracts']

    # 1) organization_ids: documented extra column 'evidence' (string)
    org_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['organization_ids'], 'organization_ids'), pa=pa,
    )
    org_drift_schema = pa.schema(list(org_canon) + [pa.field('evidence', pa.string())])
    res_org = sidecar.inspect_table_schema_parity('organization_ids', org_drift_schema, contracts['organization_ids'])
    assert res_org['status'] == 'documented_sql_drift'
    assert res_org['canonical_parity_passed'] is False
    assert any(d.get('column') == 'evidence' for d in res_org['documented_divergences'])
    # Ensure canonical parity fails closed if an UNDOCUMENTED extra column is present alongside 'evidence'
    org_unexpected = pa.schema(list(org_drift_schema) + [pa.field('mystery_col', pa.string())])
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.inspect_table_schema_parity('organization_ids', org_unexpected, contracts['organization_ids'])

    # 2) witness_organizations: documented extra columns ('method', 'score', 'evidence')
    wo_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['witness_organizations'], 'witness_organizations'), pa=pa,
    )
    wo_drift_schema = pa.schema(
        list(wo_canon) + [pa.field('method', pa.string()), pa.field('score', pa.float64()), pa.field('evidence', pa.string())]
    )
    res_wo = sidecar.inspect_table_schema_parity(
        'witness_organizations', wo_drift_schema, contracts['witness_organizations'],
    )
    assert res_wo['status'] == 'documented_sql_drift'
    assert res_wo['canonical_parity_passed'] is False
    assert {d['column'] for d in res_wo['documented_divergences']} == {'method', 'score', 'evidence'}
    # Wrong Arrow type on documented 'score' fails closed
    wo_bad_type = pa.schema(
        list(wo_canon) + [pa.field('method', pa.string()), pa.field('score', pa.string()), pa.field('evidence', pa.string())]
    )
    with pytest.raises(sidecar.SchemaDriftError, match='unexpected Arrow type'):
        sidecar.inspect_table_schema_parity('witness_organizations', wo_bad_type, contracts['witness_organizations'])

    # 3) roll_call_votes: documented extra documents[].nomination_id (string), even with reversed top-level column order
    rcv_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['roll_call_votes'], 'roll_call_votes'), pa=pa,
    )
    doc_idx = rcv_canon.get_field_index('documents')
    doc_field = rcv_canon.field(doc_idx)
    doc_elem = doc_field.type.value_field
    drifted_struct = pa.struct(list(doc_elem.type) + [pa.field('nomination_id', pa.string())])
    drifted_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, drifted_struct, nullable=doc_elem.nullable)))
    rcv_fields = [drifted_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)]
    rcv_drift_schema = pa.schema(list(reversed(rcv_fields)))
    res_rcv = sidecar.inspect_table_schema_parity('roll_call_votes', rcv_drift_schema, contracts['roll_call_votes'])
    assert res_rcv['status'] == 'documented_sql_drift'
    assert res_rcv['canonical_parity_passed'] is False
    assert res_rcv['documented_divergences'][0]['struct_field'] == 'nomination_id'
    # Unexpected extra struct field inside roll_call_votes.documents[] fails closed
    bad_struct = pa.struct(list(drifted_struct) + [pa.field('bogus_sub', pa.string())])
    bad_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, bad_struct)))
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.inspect_table_schema_parity(
            'roll_call_votes',
            pa.schema([bad_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)]),
            contracts['roll_call_votes'],
        )

    # 4) Standard non-drift table (committees) fails closed on any extra column
    com_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['committees'], 'committees'), pa=pa,
    )
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.inspect_table_schema_parity(
            'committees',
            pa.schema(list(com_canon) + [pa.field('undocumented', pa.string())]),
            contracts['committees'],
        )


def test_boto_sidecar_storage_guards_zero_parquet_and_isolated_prefix() -> None:
    client = _InMemoryBotoClient()
    storage = sidecar._BotoSidecarStorage(client, bucket='test-bucket')

    with pytest.raises(ValueError, match='forbids writing Parquet'):
        storage.put_bytes('ddk-catalogs/congressional-tech/releases/r1/committees.parquet', b'PAR1')
    with pytest.raises(ValueError, match='outside isolated prefix'):
        storage.put_bytes('viewer-publications/manifest.json', b'{}')
    with pytest.raises(ValueError, match='sidecar_prefix'):
        sidecar.validate_sidecar_prefix('viewer-publications/sub')
    with pytest.raises(ValueError, match='sidecar_prefix'):
        sidecar.validate_sidecar_prefix('derived/body_text')

    # Check retries == 1 enforcement
    bad_client = _InMemoryBotoClient(max_attempts=3)
    with pytest.raises(ValueError, match='retries'):
        sidecar._BotoSidecarStorage(bad_client, bucket='test-bucket')

    # Verify CacheControl and CAS translations
    put_res = storage.put_bytes(
        'ddk-catalogs/congressional-tech/current.json',
        b'{"release_id":"r1"}',
        content_type='application/json',
        if_none_match=True,
    )
    assert client.put_calls[-1]['CacheControl'] == 'no-store'
    with pytest.raises(Exception) as conflict_exc:
        storage.put_bytes('ddk-catalogs/congressional-tech/current.json', b'{}', if_none_match=True)
    assert getattr(conflict_exc.value, 'code', None) == 'CATALOG-REMOTE-CONFLICT'
    with pytest.raises(Exception) as missing_exc:
        storage.head_object('ddk-catalogs/congressional-tech/missing.json')
    assert getattr(missing_exc.value, 'code', None) == 'CATALOG-OBJECT-MISSING'
    assert storage.get_bytes('ddk-catalogs/congressional-tech/current.json', byte_range=(0, 9)) == b'{"release_'
    assert put_res['bytes'] == 19


def test_archive_publish_post_flip_sidecar_hook_ordering_and_failure_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _InMemoryBotoClient()
    live_manifest = json.dumps({'release_id': '1' * 64}).encode('utf-8')
    client.put_object(Bucket='bkt', Key=archive_publish.POINTER, Body=live_manifest)

    def _seed_release(tag: str) -> tuple[str, dict[str, object]]:
        files = [{'name': f'tbl_{tag}.parquet', 'sha256': tag * 64, 'size': 10, 'rows': 1}]
        rid = archive_publish.release_identity(1, files)
        m = {'schema_version': 1, 'release_id': rid, 'files': files, 'origin': {'kind': 'test'}}
        client.put_object(
            Bucket='bkt',
            Key=f'{archive_publish.PREFIX}{rid}/manifest.json',
            Body=json.dumps(m).encode('utf-8'),
        )
        return rid, m

    rid2, manifest = _seed_release('a')
    rid3, manifest3 = _seed_release('b')
    rid4, manifest4 = _seed_release('c')
    events: list[str] = []

    def fake_gate_and_flip(cli, *, bucket, release_id, previous_release_id, expected_etag, contract, canary, manifest_origin, comparison_acceptance, before_flip):
        events.append('gate_and_flip')
        cli.put_object(Bucket=bucket, Key=archive_publish.POINTER, Body=json.dumps({'release_id': release_id}).encode('utf-8'))
        return SimpleNamespace(etag='etag-new-1', reconciled=False)

    orig_clear = archive_publish.clear_staged_pointer

    def wrapped_clear(cli, *, bucket):
        events.append('clear_staged_pointer')
        return orig_clear(cli, bucket=bucket)

    monkeypatch.setattr(archive_publish, 'gate_and_flip', fake_gate_and_flip)
    monkeypatch.setattr(archive_publish, 'clear_staged_pointer', wrapped_clear)

    # 1) Hook runs strictly AFTER gate_and_flip & clear_staged_pointer
    def ok_hook(*, release_id, status, pointer_etag, **_kw):
        assert status['status'] == 'published'
        assert status['live_release'] == release_id
        events.append(f'post_flip_sidecar:{pointer_etag}')
        return {'sidecar_prefix': 'ddk-catalogs/congressional-tech', 'put_count': 4}

    res = archive_publish.commit_staged_release(
        client=client,
        bucket='bkt',
        release_id=rid2,
        previous_release_id='1' * 64,
        expected_etag='old',
        contract_receipt={},
        canary_receipt={},
        manifest=manifest,
        post_flip_sidecar=ok_hook,
    )
    assert events == ['gate_and_flip', 'clear_staged_pointer', 'post_flip_sidecar:etag-new-1']
    assert res['ddk_sidecar'] == {'status': 'published', 'sidecar_prefix': 'ddk-catalogs/congressional-tech', 'put_count': 4}
    assert json.loads(bytes(client.store[archive_publish.POINTER]['body']))['release_id'] == rid2

    # 2) Sidecar hook failure does NOT fail commit_staged_release and does NOT revert viewer-publications/manifest.json
    def failing_hook(**_kw):
        raise RuntimeError('sidecar CAS conflict')

    res_fail = archive_publish.commit_staged_release(
        client=client,
        bucket='bkt',
        release_id=rid3,
        previous_release_id=rid2,
        expected_etag='old2',
        contract_receipt={},
        canary_receipt={},
        manifest=manifest3,
        post_flip_sidecar=failing_hook,
    )
    assert res_fail['status'] == 'published'
    assert res_fail['live_release'] == rid3
    assert res_fail['ddk_sidecar'] == {
        'status': 'failed',
        'error_type': 'RuntimeError',
        'error': 'sidecar CAS conflict',
    }
    assert json.loads(bytes(client.store[archive_publish.POINTER]['body']))['release_id'] == rid3
    persisted_status = json.loads(bytes(client.store[archive_publish.STATUS]['body']))
    assert persisted_status['ddk_sidecar']['status'] == 'failed'

    # 3) If gate_and_flip fails before flipping pointer, post_flip_sidecar MUST NOT run
    called_on_gate_fail = []

    def abort_gate(*_a, **_kw):
        raise ValueError('gate failed')

    monkeypatch.setattr(archive_publish, 'gate_and_flip', abort_gate)
    with pytest.raises(ValueError, match='gate failed'):
        archive_publish.commit_staged_release(
            client=client,
            bucket='bkt',
            release_id=rid4,
            previous_release_id=rid3,
            expected_etag='old3',
            contract_receipt={},
            canary_receipt={},
            manifest=manifest4,
            post_flip_sidecar=lambda **_kw: called_on_gate_fail.append(True),
        )
    assert called_on_gate_fail == []


def test_cli_wrapper_dry_run_and_body_text_binding(tmp_path: Path) -> None:
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    pointer_path = tmp_path / 'body_text.json'
    pointer_path.write_text(json.dumps(_sample_body_text_pointer(manifest['release_id'])), encoding='utf-8')
    out_path = tmp_path / 'sidecar-out.json'

    proc = subprocess.run(
        [
            sys.executable,
            str(WRAPPER_SCRIPT),
            '--release-dir', str(rel_dir),
            '--release-id', manifest['release_id'],
            '--body-text-pointer', str(pointer_path),
            '--expect-absent',
            '--dry-run',
            '--out', str(out_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert report['release_id'] == manifest['release_id']
    assert report['zero_copy'] is True
    assert report['body_text_ssot']['release_id'] == manifest['release_id']
    assert report['parity_summary']['status'] == 'passed'


# ---------------------------------------------------------------------------
# Cross-repo DDK E2E tests (run when ddk.publication external bridge is available)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_DDK_BRIDGE, reason='ddk.publication external generation bridge not installed in pure-CT venv')
def test_ddk_e2e_loopback_publication_iceberg_v2_cas_and_zero_parquet_puts(tmp_path: Path) -> None:
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    release_id = manifest['release_id']
    bt_payload = b'BODY_TEXT_SSOT_ZERO_COPY_PAYLOAD'
    pointer = _sample_body_text_pointer(release_id, payload=bt_payload)

    store: dict[str, dict[str, object]] = {}
    for entry in manifest['files']:
        raw = (rel_dir / entry['name']).read_bytes()
        remote_key = f'viewer-publications/releases/{release_id}/{entry["name"]}'
        store[remote_key] = {
            'body': raw,
            'etag': md5(raw).hexdigest(),
            'content_type': 'application/vnd.apache.parquet',
            'cache_control': 'public,max-age=31536000,immutable',
        }
    store[pointer['key']] = {
        'body': bt_payload,
        'etag': md5(bt_payload).hexdigest(),
        'content_type': 'application/vnd.apache.parquet',
        'cache_control': 'public,max-age=31536000,immutable',
    }
    immutable_snapshot_before = {
        k: sha256(bytes(v['body'])).hexdigest()
        for k, v in store.items()
    }

    boto_client = _InMemoryBotoClient(store)
    storage = sidecar._BotoSidecarStorage(boto_client, bucket='test-r2-bucket')

    with _LoopbackR2Server(store) as srv:
        descriptor = sidecar.build_sidecar_descriptor(
            rel_dir,
            public_origin=srv.base_url,
            body_text_pointer=pointer,
            allow_insecure_http=True,
            observed_at='2026-11-27T00:00:00Z',
        )
        bundle = sidecar.build_sidecar_bundle(
            descriptor,
            output_dir=tmp_path / 'out1',
            bundle_dir=tmp_path / 'bundle1',
            expected_prior_release_id=None,
            storage=storage,
            allow_insecure_http=True,
        )
        assert bundle.schema_parity
        assert all(r['status'] == 'passed' for r in bundle.schema_parity)

        dry = sidecar.dry_run_sidecar(
            bundle,
            storage=storage,
            expected_prior_release_id=None,
            allow_insecure_http=True,
        )
        assert dry['status'] == 'ok'

        # Wrong prior release_id MUST fail CAS on first publish
        with pytest.raises(Exception) as bad_cas:
            sidecar.publish_sidecar(
                bundle,
                storage=storage,
                expected_prior_release_id='f' * 64,
                allow_insecure_http=True,
            )
        assert getattr(bad_cas.value, 'code', None) == 'CATALOG-REMOTE-CONFLICT'

        receipt1 = sidecar.publish_sidecar(
            bundle,
            storage=storage,
            expected_prior_release_id=None,
            allow_insecure_http=True,
        )
        assert receipt1['status'] == 'committed'
        assert len(receipt1['readback']['verified_iceberg_snapshots']) == 5
        assert len(receipt1['readback']['verified_members']) == 5

        # Assert ZERO .parquet PUTs occurred anywhere in boto3 put calls or storage log
        assert storage.put_keys
        assert all(not k.lower().endswith('.parquet') for k in storage.put_keys)
        assert all(k.startswith('ddk-catalogs/congressional-tech/') for k in storage.put_keys)
        assert all(not str(c['Key']).lower().endswith('.parquet') for c in boto_client.put_calls)

        # Immutable Parquet payloads untouched
        for k, digest in immutable_snapshot_before.items():
            assert sha256(bytes(store[k]['body'])).hexdigest() == digest

        # Verify Iceberg v2 snapshots & current.json & BodyTextSSOT metadata in live published sidecar objects
        ptr_key = 'ddk-catalogs/congressional-tech/current.json'
        assert ptr_key in store
        live_ptr = json.loads(bytes(store[ptr_key]['body']))
        r1_ddk_release_id = live_ptr['release_id']

        iceberg_metadata_keys = [k for k in storage.put_keys if '/iceberg/' in k and k.endswith('.metadata.json')]
        assert len(iceberg_metadata_keys) == 5
        for mk in iceberg_metadata_keys:
            meta_json = json.loads(bytes(store[mk]['body']))
            assert meta_json['format-version'] == 2
            assert meta_json['snapshots']

        catalog_key = next(k for k in storage.put_keys if k.endswith('/catalog.ddk.json'))
        catalog_ddk = json.loads(bytes(store[catalog_key]['body']))
        assert catalog_ddk['releases'][0]['reference']['value'] == release_id
        prod = catalog_ddk['products'][0]
        assert any('ct-0a35' in vs['tags'] for vs in prod['context']['verifiedStatements'])
        assert pointer['key'] in prod['context']['instructions']

        # Anonymous loopback HTTP consumer readback (zero credentials)
        dp = sidecar._load_ddk_publication()
        destination = sidecar.make_remote_destination(
            bucket='test-r2-bucket',
            public_origin=srv.base_url,
            allow_insecure_http=True,
        )

        def anon_fetch(path_or_url: str):
            import urllib.request
            target = (
                path_or_url
                if path_or_url.startswith(('http://', 'https://'))
                else f'{srv.base_url}/{path_or_url.lstrip("/")}'
            )
            with urllib.request.urlopen(target, timeout=10) as resp:
                return resp.read(), resp.headers.get('ETag')

        readback = dp.verify_http_consumer_readback(
            anon_fetch,
            destination,
            expected_release_id=r1_ddk_release_id,
            verify_member_bytes=True,
            allow_insecure_http=True,
            schema_check_order=False,
        )
        assert readback['release_id'] == r1_ddk_release_id
        assert len(readback['verified_iceberg_snapshots']) == 5
        assert len(readback['verified_members']) == 5

        # Stale absent CAS MUST fail now that current.json is live!
        with pytest.raises(Exception) as stale_cas:
            sidecar.publish_sidecar(
                bundle,
                storage=storage,
                expected_prior_release_id=None,
                allow_insecure_http=True,
            )
        assert getattr(stale_cas.value, 'code', None) == 'CATALOG-REMOTE-CONFLICT'

        # Updating with exact prior release_id succeeds cleanly
        desc2 = sidecar.build_sidecar_descriptor(
            rel_dir,
            public_origin=srv.base_url,
            body_text_pointer=pointer,
            allow_insecure_http=True,
            observed_at='2026-11-28T00:00:00Z',
        )
        bundle2 = sidecar.build_sidecar_bundle(
            desc2,
            output_dir=tmp_path / 'out2',
            bundle_dir=tmp_path / 'bundle2',
            expected_prior_release_id=r1_ddk_release_id,
            storage=storage,
            allow_insecure_http=True,
        )
        receipt2 = sidecar.publish_sidecar(
            bundle2,
            storage=storage,
            expected_prior_release_id=r1_ddk_release_id,
            allow_insecure_http=True,
        )
        assert receipt2['status'] == 'committed'
        assert len(receipt2['readback']['verified_iceberg_snapshots']) == 5
        assert all(not k.lower().endswith('.parquet') for k in storage.put_keys)


@pytest.mark.skipif(not _HAS_DDK_BRIDGE, reason='ddk.publication external generation bridge not installed in pure-CT venv')
def test_ddk_parity_bridge_handles_documented_sql_drift_tables_without_faking_parity(tmp_path: Path) -> None:
    contracts = archive_odcs.export_odcs_contracts(include_capture_eligibility=False)['table_contracts']
    dp = sidecar._load_ddk_publication()

    rel_dir = tmp_path / 'drift-rel'
    rel_dir.mkdir()
    entries = []
    for tname, extra in (
        ('organization_ids', [('evidence', pa.string())]),
        ('witness_organizations', [('method', pa.string()), ('score', pa.float64()), ('evidence', pa.string())]),
    ):
        canon = archive_odcs.odcs_object_to_arrow_schema(
            sidecar._schema_object_from_contract(contracts[tname], tname), pa=pa,
        )
        drifted = pa.schema(list(canon) + [pa.field(n, tp) for n, tp in extra])
        entries.append(_write_empty_parquet_from_schema(rel_dir / f'{tname}.parquet', drifted))

    # Also test roll_call_votes documents[].nomination_id drift with reversed column order through DDK
    rcv_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['roll_call_votes'], 'roll_call_votes'), pa=pa,
    )
    doc_idx = rcv_canon.get_field_index('documents')
    doc_elem = rcv_canon.field(doc_idx).type.value_field
    drifted_struct = pa.struct(list(doc_elem.type) + [pa.field('nomination_id', pa.string())])
    drifted_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, drifted_struct, nullable=doc_elem.nullable)))
    rcv_drifted = pa.schema(list(reversed([drifted_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)])))
    entries.append(_write_empty_parquet_from_schema(rel_dir / 'roll_call_votes.parquet', rcv_drifted))

    release_id = 'e' * 64
    manifest = {'schema_version': 1, 'release_id': release_id, 'files': entries}
    (rel_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    desc = sidecar.build_sidecar_descriptor(
        rel_dir,
        public_origin='http://127.0.0.1:18080',
        allow_insecure_http=True,
        observed_at='2026-11-27T00:00:00Z',
    )
    assert desc['parity_summary']['status'] == 'documented_sql_drift'
    assert desc['parity_summary']['canonical_parity_passed'] is False
    assert desc['parity_summary']['documented_sql_drift_tables'] == ['organization_ids', 'roll_call_votes', 'witness_organizations']

    bundle = sidecar.build_sidecar_bundle(
        desc,
        output_dir=tmp_path / 'drift-out',
        allow_insecure_http=True,
    )
    assert [r['status'] for r in bundle.schema_parity] == ['passed', 'passed', 'passed']
    cat_ddk = json.loads((Path(bundle.catalog_dir) / 'catalog.ddk.json').read_text(encoding='utf-8'))
    assert any('schema-drift' in vs['tags'] for vs in cat_ddk['products'][0]['context']['verifiedStatements'])
