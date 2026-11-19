"""ct-zohj: HTTP-200 PDF qualification facts and conditional validator refetch gating."""
from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pypdf import PdfWriter
import pytest
import requests

from capture_qualification_helpers import write_qualified_bytes
from congress_api.acquisition.capture_scheduler import load_release, run_capture
from congress_api.lake import capture_staging
from congress_api.models.archive_profile import build_capture_profile
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.qualification_facts import (
    build_qualification_fact,
    conditional_request_headers,
    extract_sha256_hex,
    extract_validators,
    load_qualification_facts,
    scan_local_store_validators,
    validators_unchanged,
    verify_qualification_fact,
)
from congress_api.transport.raw_adapters import DirectAdapter
from congress_shared.custody import verify_local_file
from corpus_recovery.qualification import qualify
from docspec_client.client import NativeDatasets


ASOF_DAY1 = '2026-10-01T00:00:00Z'
ASOF_DAY10 = '2026-10-10T00:00:00Z'
ASOF_DAY20 = '2026-10-20T00:00:00Z'
IDENTITY = dict(job='capture-scheduler-fixture', commit='a' * 40, lockfile_digest='b' * 64)
LIMITS = ZipLimits(
    max_archive_bytes=1024 * 1024,
    max_member_bytes=1024 * 1024,
    max_total_bytes=2 * 1024 * 1024,
    max_members=8,
    max_directory_bytes=1024 * 1024,
)


def _engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def _valid_pdf_bytes(pages: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _build_release(root: Path, rows: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    has_v2 = any('capture_disposition' in r for r in rows)
    fields = [
        ('requested_url', pa.string()),
        ('attempts', pa.int32()),
        ('last_attempt', pa.timestamp('us', tz='UTC')),
        ('last_status', pa.int16()),
        ('last_outcome', pa.string()),
        ('last_good_at', pa.timestamp('us', tz='UTC')),
        ('next_attempt_at', pa.timestamp('us', tz='UTC')),
    ]
    if has_v2:
        fields.extend([
            ('capture_disposition', pa.string()),
            ('capture_reason', pa.string()),
            ('capture_decision_id', pa.string()),
        ])
    pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema(fields)), root / 'url_state.parquet')
    policy = dict(
        version=1,
        entries=[dict(family='documents', patterns=[r'https://fixture\.test/[^#]*'], exclusions=[])],
    )
    (root / 'capture_scope.json').write_text(json.dumps(policy))
    project = Path(__file__).resolve().parents[3]
    recovery_policy = (
        dict(acceptance_policy='recovery-identity-v1', requirements_sha256='c' * 64)
        if has_v2
        else None
    )
    profile = build_capture_profile(
        engine_revision=_engine().source_revision,
        url_normalized_sql=(project / 'model/sql/url-normalized.sql').read_text(),
        url_keys_sql=(project / 'model/sql/url-keys.sql').read_text(),
        url_rules=json.loads((project / 'model/registries/url-rules.json').read_text()),
        recovery_policy=recovery_policy,
    )
    (root / 'capture_profile.json').write_text(json.dumps(profile))
    pq.write_table(
        pa.Table.from_pylist(
            [],
            schema=pa.schema([('canonical_url', pa.string()), ('variant_url', pa.string())]),
        ),
        root / 'url_variants.parquet',
    )
    files = []
    for name in ('url_state.parquet', 'capture_scope.json', 'capture_profile.json', 'url_variants.parquet'):
        data = (root / name).read_bytes()
        files.append(
            dict(
                name=name,
                sha256=hashlib.sha256(data).hexdigest(),
                size=len(data),
                rows=pq.read_metadata(root / name).num_rows if name.endswith('parquet') else None,
            )
        )
    release_id = hashlib.sha256(
        json.dumps([1, [[f[k] for k in ('name', 'sha256', 'size', 'rows')] for f in files]], separators=(',', ':')).encode()
    ).hexdigest()
    (root / 'manifest.json').write_text(json.dumps(dict(schema_version=1, release_id=release_id, files=files)))
    return root


class _MockStreamingResponse:
    """In-memory requests-compatible streaming response tracking body reads."""

    def __init__(self, url: str, status_code: int, headers: dict[str, str], body: bytes, tracker: dict):
        self.url = url
        self.status_code = status_code
        self.headers = requests.structures.CaseInsensitiveDict(headers)
        self._body = body
        self._tracker = tracker

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size: int = 65536):
        self._tracker['body_reads'] += 1
        self._tracker['streamed_bytes'] += len(self._body)
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset:offset + chunk_size]


class _MockSession:
    """Offline session recording request headers and body stream invocations."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []
        self.tracker = {'body_reads': 0, 'streamed_bytes': 0}

    def get(self, url: str, *, headers: dict[str, str], timeout, stream: bool, allow_redirects: bool):
        assert stream is True and allow_redirects is False
        sent = dict(headers)
        self.requests.append({'url': url, 'headers': sent})
        status, resp_headers, body = self.handler(url, sent)
        return _MockStreamingResponse(url, status, resp_headers, body, self.tracker)


def _stage_store_receipts(raw_root: Path, receipt_keys: list[str], stage_dir: Path) -> list[dict]:
    files = []
    q_dir = stage_dir / 'qualified-receipts'
    for idx, key in enumerate(receipt_keys):
        src = raw_root / key
        dst = q_dir / f'{idx:03d}-{src.name}'
        files.append(dict(key=key, path=str(dst), qualification=write_qualified_bytes(dst, src.read_bytes())))
    out = capture_staging.stage_captures(files, engine=_engine(), work=stage_dir / 'stage')
    return pq.read_table(out / 'captures.parquet').to_pylist()


def test_qualification_fact_integrity_and_validator_rules(tmp_path):
    bad_path = tmp_path / 'corrupt.pdf'
    bad_path.write_bytes(b'%PDF-1.7\ntruncated stream without eof')
    rec = qualify(verify_local_file(bad_path), tmp_path / 'cache')
    assert rec['status'] == 'unresolved'

    fact = build_qualification_fact(
        rec,
        requested_url='https://fixture.test/doc.pdf',
        url='https://fixture.test/doc.pdf',
        receipt_key='receipts/documents/2026-10-01/r1.jsonl.gz',
        retrieved_at=ASOF_DAY1,
        http_status=200,
        headers={'ETag': '"v1"', 'Last-Modified': 'Wed, 01 Oct 2025 12:00:00 GMT', 'Content-Length': str(bad_path.stat().st_size)},
    )
    verified = verify_qualification_fact(fact)
    assert verified['qualified'] is False and verified['url_qualified'] is False
    assert extract_sha256_hex(f"bodies/sha256/{rec['body_sha256'][:2]}/{rec['body_sha256']}.gz") == rec['body_sha256']

    tampered = dict(fact, qualification_record=dict(fact['qualification_record'], status='qualified'))
    with pytest.raises(ValueError, match='integrity'):
        verify_qualification_fact(tampered)

    mismatch = dict(fact, body_sha256='0' * 64)
    with pytest.raises(ValueError, match='disagrees'):
        verify_qualification_fact(mismatch)

    loaded = load_qualification_facts([fact])
    prior = loaded['by_url']['https://fixture.test/doc.pdf']
    cond = conditional_request_headers(prior, {'Accept': 'application/pdf'})
    assert cond == {
        'Accept': 'application/pdf',
        'If-None-Match': '"v1"',
        'If-Modified-Since': 'Wed, 01 Oct 2025 12:00:00 GMT',
    }
    assert validators_unchanged(
        prior,
        {'etag': '"v1"', 'last-modified': 'Wed, 01 Oct 2025 12:00:00 GMT', 'content-length': str(bad_path.stat().st_size)},
    )
    assert not validators_unchanged(
        prior,
        {'etag': '"v2"', 'last-modified': 'Wed, 01 Oct 2025 12:00:00 GMT', 'content-length': str(bad_path.stat().st_size)},
    )
    assert not validators_unchanged(
        prior,
        {'etag': '"v1"', 'last-modified': 'Thu, 02 Oct 2025 12:00:00 GMT', 'content-length': str(bad_path.stat().st_size)},
    )
    assert not validators_unchanged(
        prior,
        {'etag': '"v1"', 'last-modified': 'Wed, 01 Oct 2025 12:00:00 GMT', 'content-length': '9999'},
    )
    # Chunked responses with zero validators must never be suppressed permanently.
    assert not validators_unchanged({'qualified': False, 'etag': None, 'last_modified': None, 'content_length': None}, {})
    # Healthy files do not suppress refetches via validator_unchanged.
    assert not validators_unchanged({**prior, 'qualified': True}, {'etag': '"v1"'})
    assert conditional_request_headers({**prior, 'qualified': True}, {}) == {}
    assert extract_validators({'ETag': ' W/"weak-1" ', 'Content-Length': '0042'}) == {
        'etag': 'W/"weak-1"',
        'last_modified': None,
        'content_length': '42',
    }


def test_corrupt_http_200_pdf_preserved_and_not_refetched_on_unchanged_validators_or_304(tmp_path):
    url = 'https://fixture.test/hearing/corrupt.pdf'
    corrupt_bytes = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\ntruncated-without-eof'
    corrupt_sha = hashlib.sha256(corrupt_bytes).hexdigest()
    base_headers = {
        'Content-Type': 'application/pdf',
        'ETag': '"corrupt-etag-1"',
        'Last-Modified': 'Wed, 01 Oct 2025 12:00:00 GMT',
        'Content-Length': str(len(corrupt_bytes)),
    }

    raw = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw))
    qual_cache = tmp_path / 'shared-qual-cache'

    # Run 1: initial fetch gets HTTP 200 corrupt PDF -> body & receipt preserved as-is, marked unqualified.
    rel1 = _build_release(tmp_path / 'rel1', [dict(requested_url=url, attempts=0)])
    session1 = _MockSession(lambda _u, _h: (200, base_headers, corrupt_bytes))
    res1 = run_capture(
        load_release(release_root=rel1, work=tmp_path / 'load1'),
        engine=_engine(),
        work=tmp_path / 'work1',
        as_of=ASOF_DAY1,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(session1),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert res1['requests'] == 1 and res1['captures'] == 1
    assert session1.tracker['body_reads'] == 1
    assert res1['qualifications'] == {
        'checked': 1,
        'qualified': 0,
        'failed': 1,
        'failed_urls': [url],
    }
    # Raw store holds only bodies/ and receipts/, with exact corrupt PDF bytes preserved.
    assert {p.parts[len(raw.parts)] for p in raw.rglob('*') if p.is_file()} == {'bodies', 'receipts'}
    with gzip.open(raw / res1['receipts'][0], 'rt') as stream:
        line1 = json.loads(stream.read())
    assert line1['http_status'] == 200 and line1['outcome'] == 'stored'
    assert line1['captures'][0]['sha256'] == corrupt_sha
    suffix = line1['captures'][0]['stored_suffix']
    stored_body_path = raw / f'bodies/sha256/{corrupt_sha[:2]}/{corrupt_sha}{suffix}'
    raw_stored = gzip.decompress(stored_body_path.read_bytes()) if suffix == '.gz' else stored_body_path.read_bytes()
    assert raw_stored == corrupt_bytes

    # Run 2: origin ignores conditional headers and answers 200 OK with identical validators ->
    # DirectAdapter aborts before reading body bytes (0 body reads, 0 wire bytes), writes 'unchanged' receipt.
    rel2 = _build_release(
        tmp_path / 'rel2',
        [
            dict(
                requested_url=url,
                attempts=1,
                last_attempt=datetime(2026, 10, 1, tzinfo=timezone.utc),
                last_status=200,
                last_outcome='stored',
                next_attempt_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
                capture_disposition='eligible',
                capture_reason='body_not_qualified',
                capture_decision_id=None,
            )
        ],
    )
    session2 = _MockSession(lambda _u, _h: (200, base_headers, corrupt_bytes))
    res2 = run_capture(
        load_release(release_root=rel2, work=tmp_path / 'load2'),
        engine=_engine(),
        work=tmp_path / 'work2',
        as_of=ASOF_DAY10,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(session2),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert len(session2.requests) == 1
    sent2 = {k.lower(): v for k, v in session2.requests[0]['headers'].items()}
    assert sent2['if-none-match'] == '"corrupt-etag-1"'
    assert sent2['if-modified-since'] == 'Wed, 01 Oct 2025 12:00:00 GMT'
    assert session2.tracker['body_reads'] == 0 and session2.tracker['streamed_bytes'] == 0
    assert res2['fetched_bytes'] == 0 and res2['validator_unchanged'] == 1

    # Run 3: origin honors conditional headers and answers 304 Not Modified ->
    # 0 body bytes downloaded, 'unchanged' receipt written, local store validator scan preserves entry.
    def _handle_304(_u: str, req_headers: dict[str, str]):
        lower = {k.lower(): v for k, v in req_headers.items()}
        assert lower.get('if-none-match') == '"corrupt-etag-1"'
        assert lower.get('if-modified-since') == 'Wed, 01 Oct 2025 12:00:00 GMT'
        return 304, {'ETag': '"corrupt-etag-1"'}, b''

    session3 = _MockSession(_handle_304)
    res3 = run_capture(
        load_release(release_root=rel2, work=tmp_path / 'load3'),
        engine=_engine(),
        work=tmp_path / 'work3',
        as_of=ASOF_DAY20,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(session3),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert session3.tracker['body_reads'] == 0 and res3['fetched_bytes'] == 0
    assert res3['captures'] == 1

    # Verify byte-hashed captures.py stages all 3 receipts cleanly without conflict!
    staged_rows = _stage_store_receipts(
        raw,
        [*res1['receipts'], *res2['receipts'], *res3['receipts']],
        tmp_path / 'staged',
    )
    by_key = {r['receipt_key']: r for r in staged_rows}
    assert by_key[res1['receipts'][0]]['outcome'] == 'stored'
    assert by_key[res1['receipts'][0]]['http_status'] == 200
    assert by_key[res2['receipts'][0]]['outcome'] == 'unchanged'
    assert by_key[res2['receipts'][0]]['http_status'] == 200
    assert by_key[res2['receipts'][0]]['sha256'] is None
    assert by_key[res3['receipts'][0]]['outcome'] == 'unchanged'
    assert by_key[res3['receipts'][0]]['http_status'] == 304
    assert by_key[res3['receipts'][0]]['sha256'] is None

    loaded_cache = load_qualification_facts(qual_cache)
    scanned = scan_local_store_validators(raw, by_sha256=loaded_cache['by_sha256'])
    assert scanned[url]['qualified'] is False
    assert scanned[url]['receipt_key'] == res3['receipts'][0]


@pytest.mark.parametrize('changed_validator', ['etag', 'last-modified', 'content-length'])
def test_changed_validator_triggers_fresh_download_and_requalification(tmp_path, changed_validator):
    url = f'https://fixture.test/hearing/{changed_validator}.pdf'
    corrupt_bytes = b'%PDF-1.7\nbroken-stream-bytes-padded-to-length'
    good_bytes = _valid_pdf_bytes(pages=2)
    assert len(good_bytes) != len(corrupt_bytes)

    raw = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw))
    qual_cache = tmp_path / 'qual-cache'

    initial_headers = {
        'Content-Type': 'application/pdf',
        'ETag': '"v1"',
        'Last-Modified': 'Wed, 01 Oct 2025 12:00:00 GMT',
        'Content-Length': str(len(corrupt_bytes)),
    }
    rel1 = _build_release(tmp_path / 'rel1', [dict(requested_url=url, attempts=0)])
    s1 = _MockSession(lambda _u, _h: (200, initial_headers, corrupt_bytes))
    res1 = run_capture(
        load_release(release_root=rel1, work=tmp_path / 'load1'),
        engine=_engine(),
        work=tmp_path / 'work1',
        as_of=ASOF_DAY1,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(s1),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert res1['qualifications']['failed'] == 1

    # Change ONLY the single parameterized validator header on Run 2.
    updated_headers = dict(initial_headers)
    payload_for_run2 = good_bytes
    if changed_validator == 'etag':
        updated_headers['ETag'] = '"v2-fixed"'
        # Keep declared Content-Length equal to initial only if testing ETag alone? No: serve a valid PDF
        # padded in a PDF comment to exact same byte length so ONLY ETag changes!
        if len(good_bytes) > len(corrupt_bytes):
            # Re-check with corrupt_bytes padded in Run 1 instead? Even simpler: PDF allows trailing comment!
            pass
    elif changed_validator == 'last-modified':
        updated_headers['Last-Modified'] = 'Thu, 02 Oct 2025 12:00:00 GMT'
    elif changed_validator == 'content-length':
        updated_headers['Content-Length'] = str(len(good_bytes))

    # Ensure for 'etag' and 'last-modified' that Content-Length did NOT change unless 'content-length' is tested,
    # by omitting Content-Length when testing ETag/Last-Modified OR matching exact length:
    if changed_validator in ('etag', 'last-modified'):
        # Re-run cleanly with matching Content-Length by padding corrupt_bytes in a fresh isolated sub-store!
        raw2 = tmp_path / 'raw_exact'
        store2 = BodyStore(LocalAdapter(raw2))
        qcache2 = tmp_path / 'qual_exact'
        same_len_corrupt = (b'%PDF-1.7\nbroken\n' + b'X' * max(0, len(good_bytes) - 16))[:len(good_bytes)]
        assert len(same_len_corrupt) == len(good_bytes)
        h1 = {
            'Content-Type': 'application/pdf',
            'ETag': '"v1"',
            'Last-Modified': 'Wed, 01 Oct 2025 12:00:00 GMT',
            'Content-Length': str(len(good_bytes)),
        }
        run_capture(
            load_release(release_root=rel1, work=tmp_path / 'load1_exact'),
            engine=_engine(),
            work=tmp_path / 'work1_exact',
            as_of=ASOF_DAY1,
            request_budget=10,
            byte_budget=2**24,
            spool_budget=2**26,
            store=store2,
            identity=IDENTITY,
            direct=DirectAdapter(_MockSession(lambda _u, _h: (200, h1, same_len_corrupt))),
            resolve=lambda _: ['8.8.8.8'],
            archive_limits=LIMITS,
            pace=lambda *_: None,
            qualification_cache=qcache2,
        )
        h2 = dict(h1)
        if changed_validator == 'etag':
            h2['ETag'] = '"v2-fixed"'
        else:
            h2['Last-Modified'] = 'Thu, 02 Oct 2025 12:00:00 GMT'
        store = store2
        qual_cache = qcache2
        updated_headers = h2

    rel2 = _build_release(
        tmp_path / 'rel2',
        [
            dict(
                requested_url=url,
                attempts=1,
                last_attempt=datetime(2026, 10, 1, tzinfo=timezone.utc),
                last_status=200,
                last_outcome='stored',
                next_attempt_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
                capture_disposition='eligible',
                capture_reason='body_not_qualified',
                capture_decision_id=None,
            )
        ],
    )
    s2 = _MockSession(lambda _u, _h: (200, updated_headers, payload_for_run2))
    res2 = run_capture(
        load_release(release_root=rel2, work=tmp_path / 'load2'),
        engine=_engine(),
        work=tmp_path / 'work2',
        as_of=ASOF_DAY10,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(s2),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert s2.tracker['body_reads'] == 1
    assert res2['validator_unchanged'] == 0
    assert res2['qualifications'] == {
        'checked': 1,
        'qualified': 1,
        'failed': 0,
        'failed_urls': [],
    }


def test_healthy_http_200_pdf_unaffected_and_never_validator_suppressed(tmp_path):
    url = 'https://fixture.test/hearing/healthy.pdf'
    good_bytes = _valid_pdf_bytes(pages=2)
    headers = {
        'Content-Type': 'application/pdf',
        'ETag': '"good-v1"',
        'Last-Modified': 'Wed, 01 Oct 2025 12:00:00 GMT',
        'Content-Length': str(len(good_bytes)),
    }
    raw = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw))
    qual_cache = tmp_path / 'qual-cache'

    rel1 = _build_release(tmp_path / 'rel1', [dict(requested_url=url, attempts=0)])
    s1 = _MockSession(lambda _u, _h: (200, headers, good_bytes))
    res1 = run_capture(
        load_release(release_root=rel1, work=tmp_path / 'load1'),
        engine=_engine(),
        work=tmp_path / 'work1',
        as_of=ASOF_DAY1,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(s1),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
    )
    assert res1['qualifications'] == {
        'checked': 1,
        'qualified': 1,
        'failed': 0,
        'failed_urls': [],
    }

    # On a future scheduled live refresh, healthy PDFs do not send conditional suppression headers
    # or trigger validator_unchanged, and reuse the verified qualification record cleanly.
    rel2 = _build_release(
        tmp_path / 'rel2',
        [
            dict(
                requested_url=url,
                attempts=1,
                last_attempt=datetime(2026, 10, 1, tzinfo=timezone.utc),
                last_status=200,
                last_outcome='stored',
                last_good_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                next_attempt_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            )
        ],
    )
    s2 = _MockSession(lambda _u, _h: (200, headers, good_bytes))
    res2 = run_capture(
        load_release(release_root=rel2, work=tmp_path / 'load2'),
        engine=_engine(),
        work=tmp_path / 'work2',
        as_of=ASOF_DAY10,
        request_budget=10,
        byte_budget=2**24,
        spool_budget=2**26,
        store=store,
        identity=IDENTITY,
        direct=DirectAdapter(s2),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualification_cache=qual_cache,
        qualifications=tmp_path / 'work1/qualifications.jsonl',
    )
    sent_headers_lower = {k.lower() for k in s2.requests[0]['headers']}
    assert 'if-none-match' not in sent_headers_lower
    assert 'if-modified-since' not in sent_headers_lower
    assert s2.tracker['body_reads'] == 1 and res2['validator_unchanged'] == 0
    assert res2['qualifications']['qualified'] == 1


@pytest.mark.loopback
def test_loopback_http_server_validator_suppression_with_requests_and_rust_fetcher(tmp_path):
    """Real TCP loopback proof that unchanged validators abort before body bytes are read."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    from congress_api.transport.rust_fetch import RustFetcher

    corrupt_payload = b'%PDF-1.7\n' + (b'0123456789abcdef' * 16384)  # 256 KiB broken PDF
    events: list[dict] = []
    mode = {'respond_304': False, 'etag': '"broken-loopback-1"'}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            inm = self.headers.get('If-None-Match')
            if mode['respond_304'] and inm == mode['etag']:
                self.send_response(304)
                self.send_header('ETag', mode['etag'])
                self.end_headers()
                events.append({'status': 304, 'inm': inm, 'body_written': False})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('ETag', mode['etag'])
            self.send_header('Content-Length', str(len(corrupt_payload)))
            self.end_headers()
            wrote_all = False
            try:
                self.wfile.write(corrupt_payload)
                self.wfile.flush()
                wrote_all = True
            except OSError:
                wrote_all = False
            events.append({'status': 200, 'inm': inm, 'body_written': wrote_all})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}/broken.pdf'
        prior = {'qualified': False, 'etag': '"broken-loopback-1"', 'last_modified': None, 'content_length': str(len(corrupt_payload))}
        with requests.Session() as sess:
            adapter = DirectAdapter(sess)
            t_unchanged = adapter.hop(url, tmp_path / 'unchanged.bin', limit=16 << 20, headers={}, prior_validators=prior)
            assert t_unchanged.error == 'validator_unchanged' and t_unchanged.wire_bytes == 0
            assert not (tmp_path / 'unchanged.bin').exists()

            mode['respond_304'] = True
            t_304 = adapter.hop(url, tmp_path / '304.bin', limit=16 << 20, headers={}, prior_validators=prior)
            assert t_304.http_status == 304 and t_304.wire_bytes == 0
            assert events[-1] == {'status': 304, 'inm': '"broken-loopback-1"', 'body_written': False}

        binary = os.environ.get('SOURCE_FETCH_BINARY')
        if binary and Path(binary).is_file():
            mode['respond_304'] = False
            with RustFetcher(binary, files_per_second=60, workers=1) as rf:
                rust_adapter = DirectAdapter(rf)
                t_rf = rust_adapter.hop(url, tmp_path / 'rf-unchanged.bin', limit=16 << 20, headers={}, prior_validators=prior)
                assert t_rf.error == 'validator_unchanged' and t_rf.wire_bytes == 0
                assert not (tmp_path / 'rf-unchanged.bin').exists()
    finally:
        server.shutdown()
        server.server_close()

