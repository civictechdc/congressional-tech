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
from congress_shared.custody import canonical_json_bytes, verify_local_file
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


def test_qualification_facts_refuse_unverified_overrides_retryable_and_length_only_gates(tmp_path):
    """Review 7: flat summaries, url_qualified upgrades, stale records, retryable failures and
    length-only validators never decide routing or suppress a refetch."""
    from congress_api.retention.qualification_facts import StaleQualification, merge_fact

    bad_path = tmp_path / 'corrupt.pdf'
    bad_path.write_bytes(b'%PDF-1.7\ntruncated stream without eof')
    rec = qualify(verify_local_file(bad_path), tmp_path / 'cache')
    headers = {'Content-Type': 'application/pdf', 'ETag': '"v1"', 'Content-Length': str(bad_path.stat().st_size)}
    fact = build_qualification_fact(rec, requested_url='https://fixture.test/a', url='https://fixture.test/b.pdf',
                                    receipt_key='r1', retrieved_at=ASOF_DAY1, http_status=200, headers=headers)

    # A flat summary with an arbitrary checksum and no record is refused.
    flat = {k: fact[k] for k in ('body_sha256', 'body_bytes', 'status', 'media_type', 'reason', 'retryable')}
    flat.update(qualified=True, status='qualified', qualification_sha256='f' * 64, requested_url='https://fixture.test/a')
    with pytest.raises(ValueError, match='full qualification record'):
        verify_qualification_fact(flat)
    # A stored url_qualified=True cannot upgrade a failed verified record.
    assert verify_qualification_fact(dict(fact, url_qualified=True))['url_qualified'] is False
    # A record from another validator configuration is stale and ignored, never trusted.
    body = {k: v for k, v in dict(rec).items() if k != 'qualification_sha256'}
    body['config'] = dict(body['config'], max_pages=body['config']['max_pages'] + 1)
    stale = dict(body, qualification_sha256=hashlib.sha256(canonical_json_bytes(body)).hexdigest())
    with pytest.raises(StaleQualification):
        verify_qualification_fact(stale)
    assert load_qualification_facts([stale])['stale'] == 1

    # Validators bind to the resource that answered, not the redirecting address.
    loaded = load_qualification_facts([fact])
    assert set(loaded['by_url']) == {'https://fixture.test/b.pdf'}
    prior = loaded['by_url']['https://fixture.test/b.pdf']
    assert conditional_request_headers(prior, {}) == {'If-None-Match': '"v1"'}

    # Retryable checker failures never gate a refetch.
    retryable = dict(prior, retryable=True)
    assert conditional_request_headers(retryable, {}) == {}
    assert not validators_unchanged(retryable, headers)
    # Equal Content-Length alone cannot show the publisher kept the same file.
    length_only = dict(prior, etag=None, last_modified=None)
    assert not validators_unchanged(length_only, {'content-length': headers['Content-Length']})

    # A newer non-retryable record replaces a retryable one for the same body.
    by_sha, by_url = {}, {}
    merge_fact(by_sha, by_url, dict(fact, retryable=True))
    merge_fact(by_sha, by_url, fact)
    assert by_sha[fact['body_sha256']]['retryable'] is False

    # A torn final ledger line from an interrupted append is skipped; earlier lines load,
    # and repair_qualifications_ledger truncates the fragment so subsequent appends stay valid JSONL.
    from congress_api.retention.qualification_facts import repair_qualifications_ledger, scan_local_store_validators

    ledger = tmp_path / 'qualifications.jsonl'
    ledger.write_text(json.dumps(fact) + '\n' + json.dumps(fact)[:40])
    assert set(load_qualification_facts(ledger)['by_url']) == {'https://fixture.test/b.pdf'}
    repair_qualifications_ledger(ledger)
    fact2 = dict(fact, requested_url='https://fixture.test/second.pdf', url='https://fixture.test/second.pdf', receipt_key='r2')
    with ledger.open('a', encoding='utf-8') as out:
        out.write(json.dumps(fact2) + '\n')
    repaired_loaded = load_qualification_facts(ledger)
    assert set(repaired_loaded['by_url']) == {'https://fixture.test/b.pdf', 'https://fixture.test/second.pdf'}
    # Review 7c: a malformed final line that ALREADY ends in a newline is corruption, not a torn append -> must raise!
    corrupt_newline_ledger = tmp_path / 'corrupt-newline.jsonl'
    corrupt_newline_ledger.write_text(json.dumps(fact) + '\n{not-valid-json\n')
    with pytest.raises(json.JSONDecodeError):
        repair_qualifications_ledger(corrupt_newline_ledger)

    # Review 7b: checker implementation hash, classifier hash, or parser version drift raises StaleQualification.
    for mutated_validator in (
        dict(rec['validator'], implementation_sha256='0' * 64),
        dict(rec['validator'], classifier_sha256='1' * 64),
        dict(rec['validator'], pypdf='0.0.0-ancient'),
    ):
        stale_body = {k: v for k, v in dict(rec).items() if k != 'qualification_sha256'}
        stale_body['validator'] = mutated_validator
        stale_rec = dict(stale_body, qualification_sha256=hashlib.sha256(canonical_json_bytes(stale_body)).hexdigest())
        with pytest.raises(StaleQualification):
            verify_qualification_fact(stale_rec)
        assert load_qualification_facts([stale_rec])['stale'] == 1

    # Review 7b: scan_local_store_validators never synthesizes a suppression entry without a verified record.
    fake_store = tmp_path / 'local-raw'
    fake_receipt = fake_store / 'receipts/documents/2026-10-01/r1.jsonl.gz'
    fake_receipt.parent.mkdir(parents=True)
    fake_receipt.write_bytes(gzip.compress((json.dumps({
        'mode': 'fetch', 'http_status': 200, 'outcome': 'stored',
        'requested_url': 'https://fixture.test/b.pdf', 'url': 'https://fixture.test/b.pdf',
        'retrieved_at': ASOF_DAY1, 'response_headers': {'ETag': '"v1"'},
        'captures': [{'attempt': 0, 'sha256': fact['body_sha256']}],
    }) + '\n').encode()))
    assert scan_local_store_validators(fake_store, by_sha256={}, unqualified_urls={'https://fixture.test/b.pdf'}) == {}


@pytest.mark.parametrize('status,extra,body_expected', [
    (206, {'Content-Range': 'bytes 0-9/100'}, True),
    (200, {'Content-Range': 'bytes 0-9/100'}, True),
    (202, {}, True),
])
def test_only_a_full_http_200_can_be_validator_suppressed(tmp_path, status, extra, body_expected):
    from congress_api.acquisition.fetcher import Fetcher
    from congress_api.models.raw_fetch import FetchAttempt
    from congress_api.retention.receipt_writer import outcome

    url = 'https://fixture.test/partial.pdf'
    payload = b'%PDF-1.7\nbroken'
    headers = {'Content-Type': 'application/pdf', 'ETag': '"p1"', 'Content-Length': str(len(payload)), **extra}
    prior = {'qualified': False, 'retryable': False, 'etag': '"p1"', 'last_modified': None,
             'content_length': str(len(payload))}
    session = _MockSession(lambda _u, _h: (status, headers, payload))
    fetcher = Fetcher(scope=lambda _u: True, direct=DirectAdapter(session), provider=None, pace=lambda *_: None,
                      directory=tmp_path / 'spool', spool_limit=1 << 20, validators=lambda _u: prior)
    final = fetcher.fetch(url).final
    assert final.error != 'validator_unchanged'
    assert session.tracker['body_reads'] == 1 and (final.body is not None) is body_expected
    # The writer never calls a non-200 or ranged validator match 'unchanged'.
    forged = FetchAttempt(url, url, ASOF_DAY1, 'direct', status, None, {k.lower(): v for k, v in headers.items()},
                          (), True, None, 'validator_unchanged')
    assert outcome(forged, None) != 'unchanged'


def test_incomplete_or_mismatched_url_200_cannot_be_validator_suppressed(tmp_path):
    """Review 7b: DirectAdapter refuses pre-stream validator_unchanged when capture_complete is False
    or response.url differs from the requested hop URL."""
    url = 'https://fixture.test/chunked.pdf'
    payload = b'%PDF-1.7\ntruncated'
    headers = {'Content-Type': 'application/pdf', 'ETag': '"p1"', 'Content-Length': str(len(payload))}
    prior = {'qualified': False, 'retryable': False, 'etag': '"p1"', 'last_modified': None,
             'content_length': str(len(payload))}

    class _CustomResp:
        def __init__(self, *, capture_complete=True, resp_url=url):
            self.status_code = 200
            self.headers = dict(headers)
            self.url = resp_url
            self.capture_complete = capture_complete
            self.reads = 0
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def iter_content(self, chunk_size=65536):
            self.reads += 1
            yield payload

    class _CustomSess:
        def __init__(self, resp):
            self.resp = resp
        def get(self, *_a, **_kw):
            return self.resp

    r_incomplete = _CustomResp(capture_complete=False)
    t_inc = DirectAdapter(_CustomSess(r_incomplete)).hop(url, tmp_path / 'inc.bin', limit=1 << 20, headers={}, prior_validators=prior)
    assert t_inc.error != 'validator_unchanged' and t_inc.complete is False and r_incomplete.reads == 1

    r_diff_url = _CustomResp(capture_complete=True, resp_url='https://fixture.test/other.pdf')
    t_diff = DirectAdapter(_CustomSess(r_diff_url)).hop(url, tmp_path / 'diff.bin', limit=1 << 20, headers={}, prior_validators=prior)
    assert t_diff.error != 'validator_unchanged' and r_diff_url.reads == 1


def test_journal_replays_a_hop_sealed_before_validators_existed(tmp_path):
    """A sealed hop replays across validator state transitions in both directions while refusing
    URL, limit or non-conditional header drift."""
    from congress_api.acquisition.capture_journal import DurableCapture
    from congress_api.models.raw_fetch import Transfer

    url = 'https://fixture.test/r.pdf'
    calls = []

    class Plain:
        def hop(self, u, dest, *, limit, headers, prior_validators=None):
            calls.append(dict(headers))
            Path(dest).write_bytes(b'x')
            return Transfer(Path(dest), u, 200, {'etag': '"e"'}, True, sha256=hashlib.sha256(b'x').hexdigest(), size=1)

    journal = DurableCapture(tmp_path / 'journal', {'binding': 1})
    journal.adapter('op', Plain(), 'direct').hop(url, tmp_path / 'd1', limit=10, headers={})
    replay = journal.adapter('op', Plain(), 'direct').hop(
        url, tmp_path / 'd2', limit=10, headers={'If-None-Match': '"e"'},
        prior_validators={'qualified': False, 'etag': '"e"'})
    assert calls == [{}] and replay.http_status == 200 and (tmp_path / 'd2').read_bytes() == b'x'
    with pytest.raises(ValueError, match='request definition changed'):
        journal.adapter('op', Plain(), 'direct').hop(url, tmp_path / 'd3', limit=11, headers={})

    # Reverse direction (Review 7b): hop sealed WITH conditional headers replays when validators change or clear,
    # while non-conditional header changes still raise.
    journal.adapter('op-cond', Plain(), 'direct').hop(
        url, tmp_path / 'c1', limit=10,
        headers={'Accept': 'application/pdf', 'If-None-Match': '"e"'},
        prior_validators={'qualified': False, 'etag': '"e"'})
    replay_changed = journal.adapter('op-cond', Plain(), 'direct').hop(
        url, tmp_path / 'c2', limit=10,
        headers={'Accept': 'application/pdf', 'If-None-Match': '"e2"'},
        prior_validators={'qualified': False, 'etag': '"e2"'})
    replay_cleared = journal.adapter('op-cond', Plain(), 'direct').hop(
        url, tmp_path / 'c3', limit=10,
        headers={'Accept': 'application/pdf'},
        prior_validators=None)
    assert len(calls) == 2 and replay_changed.http_status == 200 and replay_cleared.http_status == 200
    with pytest.raises(ValueError, match='request definition changed'):
        journal.adapter('op-cond', Plain(), 'direct').hop(
            url, tmp_path / 'c4', limit=10,
            headers={'Accept': 'text/html'},
            prior_validators=None)

    # Review 7c: an older conditional hop sealed BEFORE base_headers_sha256 existed (only headers_sha256)
    # still replays cleanly on an identical conditional request!
    legacy_headers = {'Accept': 'application/pdf', 'If-None-Match': '"legacy-etag"'}
    legacy_prior = {'qualified': False, 'etag': '"legacy-etag"'}
    legacy_root = tmp_path / 'journal' / 'op-legacy'
    legacy_root.mkdir(parents=True)
    (legacy_root / 'direct-0.sealed').write_bytes(b'z')
    (legacy_root / 'direct-0.json').write_text(json.dumps({
        'phase': 'downloaded',
        'request': {
            'url': url,
            'limit': 10,
            'headers_sha256': hashlib.sha256(json.dumps(legacy_headers, sort_keys=True).encode()).hexdigest(),
            'validators_sha256': hashlib.sha256(json.dumps(legacy_prior, sort_keys=True, default=str).encode()).hexdigest(),
        },
        'transfer': {
            'url': url, 'http_status': 200, 'headers': {'etag': '"legacy-etag"'}, 'complete': True,
            'error': None, 'sha256': hashlib.sha256(b'z').hexdigest(), 'size': 1, 'wire_bytes': 1,
        },
    }))
    replay_legacy = journal.adapter('op-legacy', Plain(), 'direct').hop(
        url, tmp_path / 'legacy-out', limit=10, headers=legacy_headers, prior_validators=legacy_prior,
    )
    assert len(calls) == 2 and replay_legacy.http_status == 200 and (tmp_path / 'legacy-out').read_bytes() == b'z'


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


def test_durable_store_qualifications_survive_fresh_work_dirs_and_retry_transient_failures(tmp_path):
    """R2/store-backed provenance/qualifications/ survives fresh work dirs and retries transient failures."""
    from dataclasses import asdict
    import io
    from botocore.exceptions import ClientError
    from congress_api.retention.body_store import R2Adapter
    from corpus_recovery.qualification import QualificationConfig, _finish, _identity, qualify as real_qualify

    class _FakeR2Client:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def head_object(self, *, Bucket, Key):
            if Key not in self.objects:
                raise ClientError({'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject')
            data = self.objects[Key]
            return {'ContentLength': len(data), 'ETag': f'"{hashlib.md5(data).hexdigest()}"'}

        def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None, **kwargs):
            if IfNoneMatch == '*' and Key in self.objects:
                raise ClientError({'Error': {'Code': '412', 'Message': 'PreconditionFailed'}}, 'PutObject')
            data = Body if isinstance(Body, (bytes, bytearray)) else Body.read()
            self.objects[Key] = bytes(data)
            return {'ETag': f'"{hashlib.md5(data).hexdigest()}"'}

        def get_object(self, *, Bucket, Key, IfMatch=None):
            if Key not in self.objects:
                raise ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'Missing'}}, 'GetObject')
            data = self.objects[Key]
            return {'Body': io.BytesIO(data), 'ContentLength': len(data), 'ETag': f'"{hashlib.md5(data).hexdigest()}"'}

        def get_paginator(self, operation):
            assert operation == 'list_objects_v2'
            objects = self.objects
            class _Paginator:
                def paginate(self, *, Bucket, Prefix=''):
                    contents = [
                        {'Key': k, 'Size': len(v), 'ETag': f'"{hashlib.md5(v).hexdigest()}"'}
                        for k, v in sorted(objects.items())
                        if k.startswith(Prefix)
                    ]
                    return [{'Contents': contents}]
            return _Paginator()

    r2 = _FakeR2Client()
    store = BodyStore(R2Adapter(r2, 'raw-bucket'))
    url = 'https://fixture.test/hearing/transient-broken.pdf'
    corrupt_pdf = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\ntruncated'
    headers = {'Content-Type': 'application/pdf', 'ETag': '"r2-broken-1"', 'Content-Length': str(len(corrupt_pdf))}

    # Night 1 (fresh work1): checker suffers a transient retryable failure; persisted to R2 provenance/qualifications/.
    def transient_qualify(verified_body, _cache_dir):
        return _finish({
            'body_sha256': verified_body.sha256,
            'body_bytes': verified_body.size_bytes,
            'validator': _identity(),
            'config': asdict(QualificationConfig()),
            'status': 'unresolved',
            'media_type': 'application/pdf',
            'reason': 'worker_timeout',
            'retryable': True,
        })

    rel1 = _build_release(tmp_path / 'rel1', [dict(requested_url=url, attempts=0)])
    sess1 = _MockSession(lambda _u, _h: (200, headers, corrupt_pdf))
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
        direct=DirectAdapter(sess1),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualify=transient_qualify,
        qualification_store=store,
    )
    assert res1['qualification_metrics']['provenance_key'].startswith('provenance/qualifications/')
    assert any(k.startswith('provenance/qualifications/') for k in r2.objects)

    # Night 2 (completely fresh work2, zero runner-scratch handoff): loads from R2, retries the
    # retryable failure directly against the retained R2 body, settles definitive failure, and
    # sends If-None-Match on the due recheck -> 304 Not Modified without re-downloading bytes.
    rel2 = _build_release(
        tmp_path / 'rel2',
        [dict(requested_url=url, attempts=1, last_attempt=datetime(2026, 10, 1, tzinfo=timezone.utc),
              last_status=200, last_outcome='stored', next_attempt_at=datetime(2026, 10, 8, tzinfo=timezone.utc))],
    )
    sess2 = _MockSession(lambda _u, h: (304, {'ETag': '"r2-broken-1"'}, b'') if h.get('If-None-Match') == '"r2-broken-1"' else (200, headers, corrupt_pdf))
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
        direct=DirectAdapter(sess2),
        resolve=lambda _: ['8.8.8.8'],
        archive_limits=LIMITS,
        pace=lambda *_: None,
        qualify=real_qualify,
        qualification_store=store,
    )
    assert res2['qualification_metrics']['retried'] == 1
    assert res2['qualification_metrics']['provenance_key'].startswith('provenance/qualifications/')
    assert sess2.tracker['body_reads'] == 0
    assert sess2.requests[0]['headers'].get('If-None-Match') == '"r2-broken-1"'
    r2_receipt = json.loads(gzip.decompress(r2.objects[res2['receipts'][0]]).decode('utf-8'))
    assert r2_receipt['http_status'] == 304 and r2_receipt['outcome'] == 'unchanged' and r2_receipt['captures'] == []
    assert len([k for k in r2.objects if k.startswith('provenance/qualifications/')]) == 2


def test_retained_byte_retry_decompresses_gzip_suffix_free_html_on_local_and_r2(tmp_path):
    """Review 7b: compressible text/html stored via BodyStore.put under a suffix-free key with
    gzip encoding decompresses cleanly during retained-byte qualification retry on Local and R2."""
    from dataclasses import asdict
    import io
    from botocore.exceptions import ClientError
    from congress_api.retention.body_store import R2Adapter
    from congress_api.retention.qualification_facts import retry_retained_qualifications
    from corpus_recovery.qualification import QualificationConfig, _finish, _identity, qualify as real_qualify

    html_bytes = b'<html><head><title>404 Not Found</title></head><body><p>' + (b'Missing PDF page. ' * 20) + b'</p></body></html>'
    html_sha = hashlib.sha256(html_bytes).hexdigest()
    html_src = tmp_path / 'error-page.html'
    html_src.write_bytes(html_bytes)
    body_key = f'bodies/sha256/{html_sha[:2]}/{html_sha}'
    pdf_url = 'https://fixture.test/hearing/missing-statement.pdf'

    transient_rec = _finish({
        'body_sha256': html_sha,
        'body_bytes': len(html_bytes),
        'validator': _identity(),
        'config': asdict(QualificationConfig()),
        'status': 'unresolved',
        'media_type': 'text/html',
        'reason': 'worker_timeout',
        'retryable': True,
    })
    retry_fact = build_qualification_fact(
        transient_rec,
        requested_url=pdf_url,
        url=pdf_url,
        receipt_key='receipts/documents/2026-10-01/r-html.jsonl.gz',
        retrieved_at=ASOF_DAY1,
        http_status=200,
        headers={'Content-Type': 'text/html; charset=utf-8', 'ETag': '"html-err-1"'},
    )

    # 1. LocalAdapter: suffix-free key contains raw gzip bytes with no ContentEncoding header.
    local_root = tmp_path / 'local-store'
    local_store = BodyStore(LocalAdapter(local_root))
    local_res = local_store.put(body_key, html_src, 'text/html')
    assert local_res.suffix == ''
    assert (local_root / body_key).read_bytes()[:2] == b'\x1f\x8b'
    assert hashlib.sha256((local_root / body_key).read_bytes()).hexdigest() != html_sha

    retried_local = retry_retained_qualifications(
        local_store, [retry_fact], qualify_fn=real_qualify,
        cache_dir=tmp_path / 'l-cache', work=tmp_path / 'l-work',
    )
    assert len(retried_local) == 1
    assert retried_local[0]['body_sha256'] == html_sha and retried_local[0]['retryable'] is False
    assert retried_local[0]['url_qualified'] is False and retried_local[0]['reason'] in ('error_or_challenge', 'candidate_format_mismatch')

    # 2. R2Adapter: suffix-free key stores gzip bytes alongside ContentEncoding='gzip'.
    class _EncodingR2Client:
        def __init__(self):
            self.objects: dict[str, tuple[bytes, str | None]] = {}

        def head_object(self, *, Bucket, Key):
            if Key not in self.objects:
                raise ClientError({'Error': {'Code': '404', 'Message': 'Not Found'}}, 'HeadObject')
            data, enc = self.objects[Key]
            meta = {'ContentLength': len(data), 'ETag': f'"{hashlib.md5(data).hexdigest()}"'}
            if enc:
                meta['ContentEncoding'] = enc
            return meta

        def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None, ContentEncoding=None, **kwargs):
            if IfNoneMatch == '*' and Key in self.objects:
                raise ClientError({'Error': {'Code': '412', 'Message': 'PreconditionFailed'}}, 'PutObject')
            data = Body if isinstance(Body, (bytes, bytearray)) else Body.read()
            self.objects[Key] = (bytes(data), ContentEncoding)
            return {'ETag': f'"{hashlib.md5(data).hexdigest()}"'}

        def get_object(self, *, Bucket, Key, IfMatch=None):
            if Key not in self.objects:
                raise ClientError({'Error': {'Code': 'NoSuchKey', 'Message': 'Missing'}}, 'GetObject')
            data, enc = self.objects[Key]
            resp = {'Body': io.BytesIO(data), 'ContentLength': len(data), 'ETag': f'"{hashlib.md5(data).hexdigest()}"'}
            if enc:
                resp['ContentEncoding'] = enc
            return resp

    r2_client = _EncodingR2Client()
    r2_store = BodyStore(R2Adapter(r2_client, 'raw-bucket'))
    r2_res = r2_store.put(body_key, html_src, 'text/html')
    assert r2_res.suffix == '' and r2_client.objects[body_key][1] == 'gzip'
    assert r2_client.objects[body_key][0][:2] == b'\x1f\x8b'

    retried_r2 = retry_retained_qualifications(
        r2_store, [retry_fact], qualify_fn=real_qualify,
        cache_dir=tmp_path / 'r2-cache', work=tmp_path / 'r2-work',
    )
    assert len(retried_r2) == 1
    assert retried_r2[0]['body_sha256'] == html_sha and retried_r2[0]['retryable'] is False
    assert retried_r2[0]['url_qualified'] is False and retried_r2[0]['reason'] in ('error_or_challenge', 'candidate_format_mismatch')


def test_reconcile_explicit_receipts_handles_whole_206_and_propagates_get_errors(tmp_path):
    """Explicit-key qualification reconciliation handles whole-range 206, skips assemble-* and
    partial 206 receipts without bucket listing, and propagates GET/if_match errors fail-closed."""
    from congress_api.retention.qualification_facts import reconcile_store_receipt_qualifications
    from corpus_recovery.qualification import qualify as real_qualify

    raw_dir = tmp_path / 'reconcile-raw'
    store = BodyStore(LocalAdapter(raw_dir))
    bad_pdf = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\ntruncated'
    bad_sha = hashlib.sha256(bad_pdf).hexdigest()
    pdf_src = tmp_path / 'broken.pdf'
    pdf_src.write_bytes(bad_pdf)
    store.put(f'bodies/sha256/{bad_sha[:2]}/{bad_sha}', pdf_src, 'application/pdf')

    interrupted_key = 'receipts/documents/2026-11-15/0000-interrupted.jsonl.gz'
    interrupted_path = raw_dir / interrupted_key
    interrupted_path.parent.mkdir(parents=True, exist_ok=True)
    interrupted_path.write_bytes(gzip.compress((json.dumps({
        'mode': 'fetch', 'http_status': 200, 'outcome': 'stored',
        'requested_url': 'https://fixture.test/a.pdf', 'url': 'https://fixture.test/a.pdf',
        'retrieved_at': '2026-11-15T12:00:00Z',
        'response_headers': {'Content-Type': 'application/pdf', 'ETag': '"v1"'},
        'captures': [{'attempt': 0, 'sha256': bad_sha, 'bytes': len(bad_pdf), 'sniffed_format': 'pdf'}],
    }) + '\n').encode()))

    whole_206_key = 'receipts/documents/2026-11-15/0001-whole206.jsonl.gz'
    partial_206_key = 'receipts/documents/2026-11-15/0002-partial206.jsonl.gz'
    inconsistent_cap_key = 'receipts/documents/2026-11-15/0003-incomplete-cap.jsonl.gz'
    assemble_key = 'receipts/documents/undated/assemble-20260930.jsonl.gz'
    (raw_dir / whole_206_key).write_bytes(gzip.compress((json.dumps({
        'mode': 'fetch', 'complete': True, 'http_status': 206, 'outcome': 'stored',
        'requested_url': 'https://fixture.test/range.pdf', 'url': 'https://fixture.test/range.pdf',
        'retrieved_at': '2026-11-15T12:30:00Z',
        'response_headers': {'Content-Type': 'application/pdf', 'Content-Range': f'bytes 0-{len(bad_pdf) - 1}/{len(bad_pdf)}'},
        'captures': [{'attempt': 0, 'sha256': bad_sha, 'bytes': len(bad_pdf), 'sniffed_format': 'pdf'}],
    }) + '\n').encode()))
    (raw_dir / partial_206_key).write_bytes(gzip.compress((json.dumps({
        'mode': 'fetch', 'complete': True, 'http_status': 206, 'outcome': 'stored',
        'requested_url': 'https://fixture.test/partial.pdf', 'url': 'https://fixture.test/partial.pdf',
        'retrieved_at': '2026-11-15T12:35:00Z',
        'response_headers': {'Content-Type': 'application/pdf', 'Content-Range': 'bytes 0-9/100'},
        'captures': [{'attempt': 0, 'sha256': bad_sha, 'bytes': len(bad_pdf), 'sniffed_format': 'pdf'}],
    }) + '\n').encode()))
    (raw_dir / inconsistent_cap_key).write_bytes(gzip.compress((json.dumps({
        'mode': 'fetch', 'http_status': 206, 'outcome': 'stored',
        'requested_url': 'https://fixture.test/inconsistent.pdf', 'url': 'https://fixture.test/inconsistent.pdf',
        'retrieved_at': '2026-11-15T12:40:00Z',
        'response_headers': {'Content-Type': 'application/pdf', 'Content-Range': f'bytes 0-{len(bad_pdf) - 1}/{len(bad_pdf)}'},
        'captures': [{'attempt': 0, 'complete': False, 'sha256': bad_sha, 'bytes': len(bad_pdf), 'sniffed_format': 'pdf'}],
    }) + '\n').encode()))

    rec_res = reconcile_store_receipt_qualifications(
        store, existing_loaded={'by_sha256': {}, 'receipt_keys': set()},
        qualify_fn=real_qualify, cache_dir=tmp_path / 'qcache', work=tmp_path / 'qwork',
        decided_at='2026-11-16T13:00:00Z',
        receipt_keys=[interrupted_key, whole_206_key, partial_206_key, inconsistent_cap_key, assemble_key],
        persist=True,
    )
    assert {f['receipt_key'] for f in rec_res['facts']} == {interrupted_key, whole_206_key}
    assert rec_res['imported'] is not None

    # A broken store GET must propagate its exception rather than returning an empty result.
    class _BrokenAdapter:
        def get(self, key):
            raise RuntimeError('r2-get-explosion')

    with pytest.raises(RuntimeError, match='r2-get-explosion'):
        reconcile_store_receipt_qualifications(
            type('S', (), {'adapter': _BrokenAdapter()})(),
            existing_loaded={'by_sha256': {}, 'receipt_keys': set()},
            qualify_fn=real_qualify, cache_dir=tmp_path / 'qcache2', work=tmp_path / 'qwork2',
            decided_at='2026-11-16T13:00:00Z',
            receipt_keys=['receipts/documents/2026-11-16/boom.jsonl.gz'],
            persist=False,
        )

    # Conditional receipt GET (if_match present) that raises TypeError inside the client MUST
    # propagate TypeError and MUST NEVER fall back to an unpinned adapter.get(key) read!
    get_calls: list[tuple[str, str | None]] = []

    class _ConditionalTypeErrorAdapter:
        def get(self, key, *, if_match=None):
            get_calls.append((key, if_match))
            if if_match is not None:
                raise TypeError('r2-client-internal-type-error')
            return {'Body': io.BytesIO((raw_dir / interrupted_key).read_bytes())}

    with pytest.raises(TypeError, match='r2-client-internal-type-error'):
        reconcile_store_receipt_qualifications(
            type('S', (), {'adapter': _ConditionalTypeErrorAdapter()})(),
            existing_loaded={'by_sha256': {}, 'receipt_keys': set()},
            qualify_fn=real_qualify, cache_dir=tmp_path / 'qcache3', work=tmp_path / 'qwork3',
            decided_at='2026-11-16T13:00:00Z',
            receipt_keys=[interrupted_key],
            receipt_etags={interrupted_key: '"pinned-etag-1"'},
            persist=False,
        )
    assert get_calls == [(interrupted_key, '"pinned-etag-1"')]
