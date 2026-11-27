"""Tests for zero-copy DDK + Iceberg v2 publication sidecar (`ct-zg0z`)."""
from __future__ import annotations

from copy import deepcopy
from hashlib import md5, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
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
    """Minimal boto3 S3-compatible client supporting ETag CAS preconditions, Range reads, and list_objects_v2."""

    def __init__(self, store: dict[str, dict[str, object]] | None = None, *, max_attempts: int = 1):
        self.meta = SimpleNamespace(config=Config(retries={'total_max_attempts': max_attempts}))
        self.store: dict[str, dict[str, object]] = store if store is not None else {}
        self.put_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

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

    def list_objects_v2(self, *, Bucket: str, Prefix: str = '', ContinuationToken: str | None = None) -> dict[str, object]:
        contents = [
            {'Key': k, 'Size': len(bytes(v['body']))}
            for k, v in sorted(self.store.items())
            if k.startswith(Prefix)
        ]
        return {'Contents': contents, 'IsTruncated': False}

    def get_object(self, *, Bucket: str, Key: str, Range: str | None = None, IfMatch: str | None = None) -> dict[str, object]:
        self.get_calls.append({'Bucket': Bucket, 'Key': Key, 'Range': Range, 'IfMatch': IfMatch})
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


def _make_drifted_roll_call_votes_schema(contracts: dict[str, dict[str, object]]) -> tuple[pa.Schema, pa.Schema, int, pa.Field, pa.StructType]:
    """Build roll_call_votes Arrow schema matching SPICY_SCHEMAS with nomination_id at struct index 2."""
    rcv_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['roll_call_votes'], 'roll_call_votes'), pa=pa,
    )
    doc_idx = rcv_canon.get_field_index('documents')
    doc_field = rcv_canon.field(doc_idx)
    doc_elem = doc_field.type.value_field
    canon_fields = list(doc_elem.type)
    # SPICY_SCHEMAS['spicy_roll_call_votes']['documents'] places nomination_id at index 2 (after congress, name)
    drifted_struct_fields = canon_fields[:2] + [pa.field('nomination_id', pa.string())] + canon_fields[2:]
    drifted_struct = pa.struct(drifted_struct_fields)
    drifted_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, drifted_struct, nullable=doc_elem.nullable)))
    rcv_fields = [drifted_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)]
    # Reverse top-level column order matching SELECT * FROM roll_call_votes_export behavior
    return rcv_canon, pa.schema(list(reversed(rcv_fields))), doc_idx, doc_elem, drifted_struct


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


def test_validate_public_origin_and_manifest_edge_guards(tmp_path: Path) -> None:
    assert sidecar.validate_public_origin('https://congressional-data.spicygov.ai/') == 'https://congressional-data.spicygov.ai'
    assert sidecar.validate_public_origin('http://127.0.0.1:8080', allow_insecure_http=True) == 'http://127.0.0.1:8080'
    assert sidecar.validate_public_origin('https://127.0.0.1:8443', allow_insecure_http=True) == 'https://127.0.0.1:8443'

    for bad in (
        '',
        'ftp://congressional-data.spicygov.ai',
        'https://user:pass@congressional-data.spicygov.ai',
        'https://@congressional-data.spicygov.ai',
        'https://congressional-data.spicygov.ai/subpath',
        'https://congressional-data.spicygov.ai?q=1',
        'https://congressional-data.spicygov.ai#frag',
        'https://10.0.0.1',
        'https://169.254.169.254',
        'https://0.0.0.0',
        'https://[::ffff:127.0.0.1]',
        'https://127.0.0.1',
        'https://localhost',
        'http://congressional-data.spicygov.ai',
    ):
        with pytest.raises(ValueError):
            sidecar.validate_public_origin(bad)

    # Http non-loopback rejected even when allow_insecure_http=True
    with pytest.raises(ValueError, match='disallowed IP'):
        sidecar.validate_public_origin('http://10.0.0.5', allow_insecure_http=True)
    with pytest.raises(ValueError, match='loopback'):
        sidecar.validate_public_origin('http://congressional-data.spicygov.ai', allow_insecure_http=True)

    # Malformed manifest rejections
    with pytest.raises(ValueError, match='64-hex release_id'):
        sidecar.resolve_release_manifest({'schema_version': 1, 'release_id': 'short', 'files': [{'name': 'a.parquet'}]})
    with pytest.raises(ValueError, match='nonempty files list'):
        sidecar.resolve_release_manifest({'schema_version': 1, 'release_id': 'a' * 64, 'files': []})
    bad_json = tmp_path / 'bad.json'
    bad_json.write_text('[]', encoding='utf-8')
    with pytest.raises(ValueError, match='must be a JSON object'):
        sidecar.resolve_release_manifest(bad_json)

    # Bad footer_sha256 in manifest entry and export.parquet smuggling rejected
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    bad_footer_manifest = deepcopy(manifest)
    bad_footer_manifest['files'][0]['footer_sha256'] = 'not-hex'
    with pytest.raises(ValueError, match='footer_sha256'):
        sidecar.build_sidecar_descriptor(bad_footer_manifest)

    export_smuggle = deepcopy(manifest)
    export_smuggle['files'].append({'name': 'export.parquet', 'sha256': 'a' * 64, 'size': 10, 'rows': 1})
    with pytest.raises(ValueError, match='export.parquet'):
        sidecar.build_sidecar_descriptor(export_smuggle)


def test_capture_profile_v2_extends_url_state_contract_and_error_handling(tmp_path: Path) -> None:
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

    # Non-404 errors in remote capture_profile.json lookup MUST re-raise (never silently swallowed!)
    class _BrokenStorage:
        def get_bytes(self, key: str) -> bytes:
            raise ClientError({'Error': {'Code': 'InternalError'}, 'ResponseMetadata': {'HTTPStatusCode': 500}}, 'GetObject')

    with pytest.raises(ClientError):
        sidecar.detect_capture_profile_v2(manifest, storage=_BrokenStorage())

    # Remote non-dict JSON capture_profile.json MUST fail loudly
    class _ArrayProfileStorage:
        def get_bytes(self, key: str) -> bytes:
            return b'[1, 2, 3]'

    with pytest.raises(ValueError, match='must be a JSON object'):
        sidecar.detect_capture_profile_v2(manifest, storage=_ArrayProfileStorage())


def test_body_text_ssot_rejects_mismatched_release_detail_and_remote_edges(tmp_path: Path) -> None:
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

    # Edge cases: public_origin validation inside validate_body_text_ssot_binding, bad sha256/bytes/footer_sha256
    with pytest.raises(ValueError, match='disallowed IP'):
        sidecar.validate_body_text_ssot_binding(
            valid_detail_ptr, release_id=release_id, manifest=detail_manifest, public_origin='http://127.0.0.1:8080',
        )
    for field, bad_val in (
        ('sha256', 'xyz'),
        ('bytes', -1),
        ('bytes', True),
        ('footer_sha256', '1234'),
    ):
        bad_ptr = deepcopy(valid_detail_ptr)
        bad_ptr[field] = bad_val
        with pytest.raises(ValueError):
            sidecar.validate_body_text_ssot_binding(bad_ptr, release_id=release_id, manifest=detail_manifest)

    # Remote pointer lookup + verify_storage_object size check + non-dict JSON rejection
    client = _InMemoryBotoClient()
    storage = sidecar._BotoSidecarStorage(client, bucket='bkt')
    bt_payload = b'PARQUET-STUB-BODY-TEXT'
    ptr = _sample_body_text_pointer(release_id, payload=bt_payload)
    client.store['derived/body_text/current.json'] = {
        'body': json.dumps(ptr).encode('utf-8'),
        'etag': 'e1',
        'content_type': 'application/json',
        'cache_control': 'no-store',
    }
    client.store[ptr['key']] = {
        'body': b'WRONG_SIZE',
        'etag': 'e2',
        'content_type': 'application/vnd.apache.parquet',
        'cache_control': 'immutable',
    }
    with pytest.raises(ValueError, match='disagrees with pointer'):
        sidecar.validate_body_text_ssot_binding(
            'derived/body_text/current.json',
            release_id=release_id,
            manifest=manifest,
            storage=storage,
            verify_storage_object=True,
        )
    client.store[ptr['key']]['body'] = bt_payload
    ok_remote = sidecar.validate_body_text_ssot_binding(
        'derived/body_text/current.json',
        release_id=release_id,
        manifest=manifest,
        storage=storage,
        verify_storage_object=True,
    )
    assert ok_remote is not None and ok_remote['pointer_key'] == 'derived/body_text/current.json'

    client.store['derived/body_text/bad.json'] = {
        'body': b'[1, 2]',
        'etag': 'e3',
        'content_type': 'application/json',
        'cache_control': 'no-store',
    }
    with pytest.raises(ValueError, match='must be a JSON object'):
        sidecar.validate_body_text_ssot_binding(
            'derived/body_text/bad.json',
            release_id=release_id,
            manifest=manifest,
            storage=storage,
        )


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
    # Unexpected column alongside documented 'evidence' fails closed
    org_unexpected = pa.schema(list(org_drift_schema) + [pa.field('mystery_col', pa.string())])
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.inspect_table_schema_parity('organization_ids', org_unexpected, contracts['organization_ids'])

    # 2) witness_organizations: documented extra columns ('method', 'score', 'evidence') with Float64 / f64
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
    score_prop = next(p for p in res_wo['contract_for_sidecar']['schema'][0]['properties'] if p['name'] == 'score')
    assert score_prop['physicalType'] == 'Float64'
    assert score_prop['logicalTypeOptions'] == {'format': 'f64'}
    # Wrong Arrow type on documented 'score' fails closed
    wo_bad_type = pa.schema(
        list(wo_canon) + [pa.field('method', pa.string()), pa.field('score', pa.string()), pa.field('evidence', pa.string())]
    )
    with pytest.raises(sidecar.SchemaDriftError, match='unexpected Arrow type'):
        sidecar.inspect_table_schema_parity('witness_organizations', wo_bad_type, contracts['witness_organizations'])

    # 3) roll_call_votes: nomination_id at exact struct index 2 (matching SPICY_SCHEMAS['spicy_roll_call_votes']['documents'])
    rcv_canon, rcv_drift_schema, doc_idx, doc_elem, drifted_struct = _make_drifted_roll_call_votes_schema(contracts)
    res_rcv = sidecar.inspect_table_schema_parity('roll_call_votes', rcv_drift_schema, contracts['roll_call_votes'])
    assert res_rcv['status'] == 'documented_sql_drift'
    assert res_rcv['canonical_parity_passed'] is False
    assert res_rcv['documented_divergences'][0]['struct_field'] == 'nomination_id'
    assert res_rcv['documented_divergences'][0]['struct_index'] == 2
    docs_prop = next(p for p in res_rcv['contract_for_sidecar']['schema'][0]['properties'] if p['name'] == 'documents')
    nested_names = [sp['name'] for sp in docs_prop['items']['properties']]
    assert nested_names[2] == 'nomination_id'
    assert nested_names == ['congress', 'name', 'nomination_id', 'number', 'short_title', 'title', 'type']

    # Canonical struct field reordering inside roll_call_votes.documents[] MUST fail closed
    reordered_fields = list(drifted_struct)
    reordered_fields[-1], reordered_fields[-2] = reordered_fields[-2], reordered_fields[-1]
    reordered_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, pa.struct(reordered_fields))))
    with pytest.raises(sidecar.SchemaDriftError, match='struct field order'):
        sidecar.inspect_table_schema_parity(
            'roll_call_votes',
            pa.schema([reordered_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)]),
            contracts['roll_call_votes'],
        )

    # Unexpected extra struct field inside roll_call_votes.documents[] fails closed
    bad_struct = pa.struct(list(drifted_struct) + [pa.field('bogus_sub', pa.string())])
    bad_docs = pa.field('documents', pa.list_(pa.field(doc_elem.name, bad_struct)))
    with pytest.raises(sidecar.SchemaDriftError, match='struct field order'):
        sidecar.inspect_table_schema_parity(
            'roll_call_votes',
            pa.schema([bad_docs if i == doc_idx else f for i, f in enumerate(rcv_canon)]),
            contracts['roll_call_votes'],
        )

    # 4) Multi-shard inconsistent drift on organization_ids (shard 0 has 'evidence', shard 1 does not) MUST fail closed!
    shard_dir = tmp_path / 'shards'
    shard_dir.mkdir()
    e0 = _write_empty_parquet_from_schema(shard_dir / 'organization_ids-00.parquet', org_drift_schema)
    e1 = _write_empty_parquet_from_schema(shard_dir / 'organization_ids-01.parquet', org_canon)
    e0['table_name'] = 'organization_ids'
    e1['table_name'] = 'organization_ids'
    with pytest.raises(sidecar.SchemaDriftError, match='Inconsistent shard schemas'):
        sidecar.build_sidecar_descriptor({'schema_version': 1, 'release_id': 'f' * 64, 'files': [e0, e1]}, local_parquet_paths={
            'viewer-publications/releases/' + 'f' * 64 + '/organization_ids-00.parquet': shard_dir / 'organization_ids-00.parquet',
            'viewer-publications/releases/' + 'f' * 64 + '/organization_ids-01.parquet': shard_dir / 'organization_ids-01.parquet',
        })

    # 5) Standard non-drift table (committees) fails closed on any extra column
    com_canon = archive_odcs.odcs_object_to_arrow_schema(
        sidecar._schema_object_from_contract(contracts['committees'], 'committees'), pa=pa,
    )
    with pytest.raises(sidecar.SchemaDriftError, match='Unexpected Parquet schema drift'):
        sidecar.inspect_table_schema_parity(
            'committees',
            pa.schema(list(com_canon) + [pa.field('undocumented', pa.string())]),
            contracts['committees'],
        )


def test_storage_range_reader_and_boto_sidecar_guards() -> None:
    client = _InMemoryBotoClient()
    storage = sidecar._BotoSidecarStorage(client, bucket='test-bucket')

    # Uppercase .PARQUET, traversal, outside prefix, pointer_key outside prefix
    with pytest.raises(ValueError, match='forbids writing Parquet'):
        storage.put_bytes('ddk-catalogs/congressional-tech/releases/r1/committees.PARQUET', b'PAR1')
    with pytest.raises(ValueError, match='Unsafe key'):
        storage.put_bytes('ddk-catalogs/congressional-tech/../escape.json', b'{}')
    with pytest.raises(ValueError, match='outside isolated prefix'):
        storage.put_bytes('viewer-publications/manifest.json', b'{}')
    with pytest.raises(ValueError, match='pointer_key'):
        sidecar._BotoSidecarStorage(client, bucket='test-bucket', pointer_key='viewer-publications/current.json')
    with pytest.raises(ValueError, match='sidecar_prefix'):
        sidecar.validate_sidecar_prefix('viewer-publications/sub')
    with pytest.raises(ValueError, match='sidecar_prefix'):
        sidecar.validate_sidecar_prefix('derived/body_text')

    # Check retries == 1 enforcement
    bad_client = _InMemoryBotoClient(max_attempts=3)
    with pytest.raises(ValueError, match='retries'):
        sidecar._BotoSidecarStorage(bad_client, bucket='test-bucket')

    # ConditionalRequestConflict (HTTP 409) MUST map to 412 / CATALOG-REMOTE-CONFLICT
    class _Conflict409Client(_InMemoryBotoClient):
        def put_object(self, **kwargs):  # type: ignore[override]
            raise self._client_error('ConditionalRequestConflict', '409 conflict', 409)

    storage_409 = sidecar._BotoSidecarStorage(_Conflict409Client(), bucket='test-bucket')
    with pytest.raises(Exception) as conflict_409:
        storage_409.put_bytes('ddk-catalogs/congressional-tech/current.json', b'{}', if_none_match=True)
    assert getattr(conflict_409.value, 'code', None) == 'CATALOG-REMOTE-CONFLICT'

    # CacheControl + IfMatch CAS preconditions + 404
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
    # Wrong IfMatch fails CAS; matching IfMatch updates cleanly
    with pytest.raises(Exception) as mismatch_exc:
        storage.put_bytes('ddk-catalogs/congressional-tech/current.json', b'{}', if_match='wrong-etag')
    assert getattr(mismatch_exc.value, 'code', None) == 'CATALOG-REMOTE-CONFLICT'
    put_res2 = storage.put_bytes(
        'ddk-catalogs/congressional-tech/current.json',
        b'{"release_id":"r2"}',
        if_match=put_res['etag'],
    )
    assert put_res2['bytes'] == 19
    with pytest.raises(Exception) as missing_exc:
        storage.head_object('ddk-catalogs/congressional-tech/missing.json')
    assert getattr(missing_exc.value, 'code', None) == 'CATALOG-OBJECT-MISSING'

    # Verify remote Parquet schema check uses ONLY byte-range reads (never full-object GET with Range=None)
    contracts = archive_odcs.export_odcs_contracts()['table_contracts']
    pq_bytes = (FIXTURE_RELEASE_DIR / 'committees.parquet').read_bytes()
    remote_pq_key = 'viewer-publications/releases/' + 'a' * 64 + '/committees.parquet'
    client.store[remote_pq_key] = {
        'body': pq_bytes,
        'etag': md5(pq_bytes).hexdigest(),
        'content_type': 'application/vnd.apache.parquet',
        'cache_control': 'public,max-age=31536000,immutable',
    }
    client.get_calls.clear()
    res = sidecar.inspect_table_schema_parity(
        'committees', remote_pq_key, contracts['committees'], storage=storage, remote_key=remote_pq_key,
    )
    assert res['status'] == 'passed'
    assert client.get_calls
    assert all(c['Range'] is not None for c in client.get_calls)


def test_archive_publish_commit_and_candidate_post_flip_sidecar_hooks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        if callable(canary):
            canary()
        cli.put_object(Bucket=bucket, Key=archive_publish.POINTER, Body=json.dumps({'release_id': release_id}).encode('utf-8'))
        return SimpleNamespace(etag='etag-new-1', reconciled=False)

    orig_clear = archive_publish.clear_staged_pointer

    def wrapped_clear(cli, *, bucket):
        events.append('clear_staged_pointer')
        return orig_clear(cli, bucket=bucket)

    monkeypatch.setattr(archive_publish, 'gate_and_flip', fake_gate_and_flip)
    monkeypatch.setattr(archive_publish, 'clear_staged_pointer', wrapped_clear)

    # 1) commit_staged_release runs hook strictly AFTER gate_and_flip & clear_staged_pointer
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
    monkeypatch.setattr(archive_publish, 'gate_and_flip', lambda *_a, **_kw: (_ for _ in ()).throw(ValueError('gate failed')))
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

    # 4) publish_candidate: stage_only=True skips hook; stage_only=False invokes hook strictly post-flip & isolates failure
    assert inspect.signature(archive_publish.publish_candidate).parameters['post_flip_sidecar'].default is None
    cand_client = _InMemoryBotoClient()
    rel_dir = tmp_path / 'cand-rel'
    rel_dir.mkdir()
    pq_bytes = (FIXTURE_RELEASE_DIR / 'committees.parquet').read_bytes()
    (rel_dir / 'committees.parquet').write_bytes(pq_bytes)
    files = [{'name': 'committees.parquet', 'sha256': sha256(pq_bytes).hexdigest(), 'size': len(pq_bytes), 'rows': 0}]
    cand_rid = archive_publish.release_identity(1, files)
    cand_manifest = {'schema_version': 1, 'release_id': cand_rid, 'files': files, 'origin': {'kind': 'test'}}
    m_bytes = json.dumps(cand_manifest).encode('utf-8')
    m_path = rel_dir / 'manifest.json'
    m_path.write_bytes(m_bytes)
    r_path = rel_dir / 'result.json'
    r_path.write_text('{}', encoding='utf-8')

    in_rec = {'provenance': [], 'profile': {'schema_version': 1}, 'entity_digests': {}}
    expected_dig = archive_publish.input_digest(receipt_keys=[], provenance=in_rec['provenance'], profile=in_rec['profile'], entity_digests=in_rec['entity_digests'], extra_pins=None)
    in_rec['input_digest'] = expected_dig

    monkeypatch.setattr(archive_publish, '_candidate', lambda *_a, **_kw: (cand_manifest, m_bytes, cand_rid, {}))
    monkeypatch.setattr(archive_publish, 'require_release_gates', lambda *_a, **_kw: None)
    monkeypatch.setattr(archive_publish, 'write_input_receipts', lambda *_a, **_kw: None)
    monkeypatch.setattr(archive_publish, 'validate_receipt', lambda *_a, **_kw: None)
    monkeypatch.setattr(
        archive_publish,
        'NativeArchiveStore',
        lambda **_kw: SimpleNamespace(upload_file=lambda *_a, **_k: None),
    )

    stage_hook_calls: list[object] = []
    staged_res = archive_publish.publish_candidate(
        client=cand_client,
        engine=None,
        bucket='bkt',
        work=tmp_path / 'work-stage',
        release=rel_dir,
        manifest_pin={'path': m_path},
        result_pin={'path': r_path},
        input_record=in_rec,
        receipt_keys=[],
        pointer=None,
        expected_etag=None,
        public_origin='https://congressional-data.spicygov.ai',
        contract=lambda **_kw: {'status': 'passed'},
        canary=lambda **_kw: {'status': 'passed'},
        first_release=True,
        stage_only=True,
        post_flip_sidecar=lambda **_kw: stage_hook_calls.append(True),
    )
    assert staged_res['status'] == 'staged'
    assert stage_hook_calls == []
    assert 'ddk_sidecar' not in staged_res

    cand_events: list[str] = []

    def cand_gate_and_flip(cli, *, bucket, release_id, previous_release_id, expected_etag, contract, canary, manifest_origin, comparison_acceptance, before_flip):
        cand_events.append('gate_and_flip')
        canary()
        cli.put_object(Bucket=bucket, Key=archive_publish.POINTER, Body=json.dumps({'release_id': release_id}).encode('utf-8'))
        return SimpleNamespace(etag='etag-cand-1', reconciled=False)

    monkeypatch.setattr(archive_publish, 'gate_and_flip', cand_gate_and_flip)
    monkeypatch.setattr(archive_publish, 'clear_staged_pointer', lambda cli, *, bucket: cand_events.append('clear_staged_pointer'))

    pub_res = archive_publish.publish_candidate(
        client=cand_client,
        engine=None,
        bucket='bkt',
        work=tmp_path / 'work-pub',
        release=rel_dir,
        manifest_pin={'path': m_path},
        result_pin={'path': r_path},
        input_record=in_rec,
        receipt_keys=[],
        pointer=None,
        expected_etag=None,
        public_origin='https://congressional-data.spicygov.ai',
        contract=lambda **_kw: {'status': 'passed'},
        canary=lambda **_kw: {'status': 'passed'},
        first_release=True,
        stage_only=False,
        post_flip_sidecar=lambda **_kw: (cand_events.append('post_flip_sidecar'), {'ok': True})[1],
    )
    assert cand_events == ['gate_and_flip', 'clear_staged_pointer', 'post_flip_sidecar']
    assert pub_res['status'] == 'published'
    assert pub_res['ddk_sidecar'] == {'status': 'published', 'ok': True}

    pub_fail = archive_publish.publish_candidate(
        client=cand_client,
        engine=None,
        bucket='bkt',
        work=tmp_path / 'work-fail',
        release=rel_dir,
        manifest_pin={'path': m_path},
        result_pin={'path': r_path},
        input_record=in_rec,
        receipt_keys=[],
        pointer=None,
        expected_etag=None,
        public_origin='https://congressional-data.spicygov.ai',
        contract=lambda **_kw: {'status': 'passed'},
        canary=lambda **_kw: {'status': 'passed'},
        first_release=True,
        stage_only=False,
        post_flip_sidecar=failing_hook,
    )
    assert pub_fail['status'] == 'published'
    assert pub_fail['ddk_sidecar']['status'] == 'failed'
    assert json.loads(bytes(cand_client.store[archive_publish.POINTER]['body']))['release_id'] == cand_rid


def test_cli_wrapper_dry_run_and_flag_validation(tmp_path: Path) -> None:
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

    # Mutually exclusive flags --expect-absent and --expected-prior-release-id MUST fail cleanly
    conflict = subprocess.run(
        [
            sys.executable,
            str(WRAPPER_SCRIPT),
            '--release-dir', str(rel_dir),
            '--expect-absent',
            '--expected-prior-release-id', 'a' * 64,
            '--dry-run',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert conflict.returncode != 0


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
def test_ddk_cli_main_dry_run_expected_prior_and_remote_publish(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rel_dir, manifest = _build_fixture_five_table_dir(tmp_path)
    release_id = manifest['release_id']
    prior_id = '9' * 64

    # 1) --dry-run --expected-prior-release-id <id> --require-ddk with local manifest & Parquets
    dry_out = tmp_path / 'dry-prior.json'
    rc = sidecar.main([
        '--release-dir', str(rel_dir),
        '--expected-prior-release-id', prior_id,
        '--dry-run',
        '--require-ddk',
        '--out', str(dry_out),
    ])
    assert rc == 0
    dry_payload = json.loads(dry_out.read_text(encoding='utf-8'))
    assert dry_payload['sidecar_status'] == 'dry_run_passed'
    assert dry_payload['dry_run']['status'] == 'dry_run_accepted'

    # 2) --publish with remote storage key --body-text-pointer + remote Parquet schema check (no local .parquet!)
    manifest_only_dir = tmp_path / 'manifest-only'
    manifest_only_dir.mkdir()
    (manifest_only_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    bt_payload = b'CLI_PUBLISH_REMOTE_BODY_TEXT'
    pointer = _sample_body_text_pointer(release_id, payload=bt_payload)
    store: dict[str, dict[str, object]] = {
        'derived/body_text/current.json': {
            'body': json.dumps(pointer).encode('utf-8'),
            'etag': 'bt-ptr-etag',
            'content_type': 'application/json',
            'cache_control': 'no-store',
        },
        pointer['key']: {
            'body': bt_payload,
            'etag': md5(bt_payload).hexdigest(),
            'content_type': 'application/vnd.apache.parquet',
            'cache_control': 'public,max-age=31536000,immutable',
        },
    }
    for entry in manifest['files']:
        raw = (rel_dir / entry['name']).read_bytes()
        store[f'viewer-publications/releases/{release_id}/{entry["name"]}'] = {
            'body': raw,
            'etag': md5(raw).hexdigest(),
            'content_type': 'application/vnd.apache.parquet',
            'cache_control': 'public,max-age=31536000,immutable',
        }
    boto_cli = _InMemoryBotoClient(store)
    monkeypatch.setattr(sidecar, '_create_boto_client_from_env', lambda: boto_cli)

    with _LoopbackR2Server(store) as srv:
        pub_out = tmp_path / 'cli-pub.json'
        rc_pub = sidecar.main([
            '--release-dir', str(manifest_only_dir),
            '--public-origin', srv.base_url,
            '--bucket', 'cli-bucket',
            '--body-text-pointer', 'derived/body_text/current.json',
            '--expect-absent',
            '--publish',
            '--allow-insecure-http',
            '--out', str(pub_out),
        ])
        assert rc_pub == 0
        pub_report = json.loads(pub_out.read_text(encoding='utf-8'))
        assert pub_report['mode'] == 'publish'
        assert pub_report['body_text_ssot']['pointer_key'] == 'derived/body_text/current.json'
        assert pub_report['parity_summary']['status'] == 'passed'
        assert pub_report['publication']['status'] == 'committed'
        assert pub_report['put_keys']
        assert all(not k.lower().endswith('.parquet') for k in pub_report['put_keys'])
        # Remote Parquet schema verification issued ONLY byte-range reads (no full-file GET with Range=None)
        parquet_gets = [c for c in boto_cli.get_calls if str(c['Key']).endswith('.parquet')]
        assert parquet_gets and all(c['Range'] is not None for c in parquet_gets)


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

    # roll_call_votes documents[].nomination_id at exact struct index 2 (SPICY_SCHEMAS ordering) + reversed columns
    _, rcv_drifted, _, _, _ = _make_drifted_roll_call_votes_schema(contracts)
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

    # Directly confirm ddk.publication.verify_parquet_schema_parity passes on annotated roll_call_votes (index 2)
    rcv_desc = next(t for t in desc['tables'] if t['table_name'] == 'roll_call_votes')
    direct_ddk = dp.verify_parquet_schema_parity(
        rel_dir / 'roll_call_votes.parquet',
        rcv_desc['contract'],
        table_name='roll_call_votes',
        normalize_arrow_encodings=True,
        check_column_order=False,
    )
    assert direct_ddk['status'] == 'passed'

    bundle = sidecar.build_sidecar_bundle(
        desc,
        output_dir=tmp_path / 'drift-out',
        allow_insecure_http=True,
    )
    assert [r['status'] for r in bundle.schema_parity] == ['passed', 'passed', 'passed']
    cat_ddk = json.loads((Path(bundle.catalog_dir) / 'catalog.ddk.json').read_text(encoding='utf-8'))
    assert any('schema-drift' in vs['tags'] for vs in cat_ddk['products'][0]['context']['verifiedStatements'])
