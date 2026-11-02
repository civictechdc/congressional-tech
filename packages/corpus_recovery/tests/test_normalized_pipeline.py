"""End-to-end tests for corpus recovery orchestration across canonical owner modules."""
from __future__ import annotations

import base64
from hashlib import sha1, sha256
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.acquisition.admission import Admission
from congress_api.lake.model_sql import model_steps
from congress_api.acquisition.capture_scheduler import CapturePolicy
from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import json_input, validate_provenance
from congress_api.retention.receipt_writer import ReceiptWriter
from corpus_recovery.acceptance import VERSION, decide
from corpus_recovery.campaign import plan
from corpus_recovery.cdx import key as surt_key
from corpus_recovery.discovery import Response, wayback_lookup
from corpus_recovery.discovery_runtime import DiscoveryRuntime
from corpus_recovery.inventory import build_target_inventory, scan_receipt_history
from corpus_recovery.pipeline import (
    discover_target_candidates,
    evaluate_campaign_url_state,
    import_accepted_candidates,
    pin_file,
    qualify_candidate_body,
    reconcile_and_import_retained,
    run_recovery_campaign,
    write_candidates_parquet,
)
from docspec_client.client import NativeDatasets
from viewer_publication.archive_model import registry_inputs

ROOT = Path(__file__).resolve().parents[3]
STAMP = '2026-10-31T12:00:00Z'
WRITER_IDENTITY = {'job': 'pipeline-test', 'commit': 'a' * 40, 'lockfile_digest': 'b' * 64}
WAYBACK_FIELDS = ['urlkey', 'timestamp', 'original', 'mimetype', 'statuscode', 'digest', 'length']


def engine() -> NativeDatasets:
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_target_inventory_delegates_to_receipt_history_and_capture_policy(tmp_path: Path):
    policy = CapturePolicy(ROOT / 'model/registries/capture-scope.json')
    direct_url = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-20230315.pdf'
    unresolved_url = 'https://democrats-science.house.gov/download/witness-testimony&download=1'
    out_of_scope_url = 'https://outside.example.com/not-in-capture-scope.pdf'

    captures = pa.Table.from_pylist([
        {
            'url': direct_url,
            'context_url': direct_url,
            'family': 'documents',
            'body_key': 'bodies/sha256/11/' + '1' * 64 + '.gz',
            'sha256': '1' * 64,
            'media_type': 'application/pdf',
            'fidelity': 'raw',
            'retrieved_at': STAMP,
            'outcome': 'stored',
            'http_status': 200,
            'complete': True,
            'receipt_key': 'receipts/documents/2026-10-31/direct.jsonl.gz',
            'receipt_line': 1,
        },
        {
            'url': unresolved_url,
            'context_url': unresolved_url,
            'family': 'documents',
            'body_key': None,
            'sha256': None,
            'media_type': 'text/html',
            'fidelity': None,
            'retrieved_at': STAMP,
            'outcome': 'request_failed',
            'http_status': 404,
            'complete': False,
            'receipt_key': 'receipts/documents/2026-10-31/direct.jsonl.gz',
            'receipt_line': 2,
        },
    ])

    history = scan_receipt_history(captures=captures, urls=[direct_url, unresolved_url, out_of_scope_url])
    assert set(history) == {direct_url, unresolved_url}

    targets_parquet = tmp_path / 'targets.parquet'
    rows = build_target_inventory(
        [direct_url, unresolved_url, out_of_scope_url],
        policy=policy,
        history=history,
        output=targets_parquet,
    )
    by_url = {r['target_url']: r for r in rows}

    assert by_url[direct_url]['usable_direct'] is True
    assert by_url[direct_url]['acquisition_excluded'] is False
    assert by_url[direct_url]['evidence_id'] == 'receipts/documents/2026-10-31/direct.jsonl.gz#1'

    # Unresolved in-scope target remains eligible (never marked excluded by post-hoc flags)
    assert by_url[unresolved_url]['usable_direct'] is False
    assert by_url[unresolved_url]['acquisition_excluded'] is False
    assert by_url[unresolved_url]['subtype'] == 'request_failed'
    assert by_url[unresolved_url]['unresolved_reason'] is None

    # Out-of-scope target is excluded strictly by CapturePolicy with the policy digest
    assert by_url[out_of_scope_url]['usable_direct'] is False
    assert by_url[out_of_scope_url]['acquisition_excluded'] is True
    assert by_url[out_of_scope_url]['evidence_id'].startswith('capture_scope:')
    assert len(by_url[out_of_scope_url]['evidence_id'].split(':', 1)[1]) == 64
    assert by_url[out_of_scope_url]['subtype'] == 'capture_scope_excluded'


def test_discover_target_candidates_composes_canonical_owners(tmp_path: Path):
    dl_target = 'https://democrats-transportation.house.gov/download/witness-testimony&download=1'
    house_target = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-20230315-SD001.xml'
    house_candidate = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-20230315-SD001.pdf'
    house_listing_url = 'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115432'
    gov_doc_target = 'https://www.congress.gov/116/cdoc/CDOC-116hdoc12/CDOC-116hdoc12.pdf'
    gov_bill_target = 'https://www.congress.gov/118/bills/hr4775/BILLS-118hr4775ih.pdf'
    wb_target = 'https://www.veterans.house.gov/sites/republicans.veterans.house.gov/files/testimony.pdf'

    wb_archived_orig = 'http://veterans.house.gov:80/sites/republicans.veterans.house.gov/files/testimony.pdf'
    wb_cdx_payload = json.dumps([
        WAYBACK_FIELDS,
        [
            surt_key(wb_target),
            '20210615102030',
            wb_archived_orig,
            'application/pdf',
            '200',
            'A' * 32,
            '4096',
        ],
    ]).encode('utf-8')

    def fake_wayback_call(kind: str, url: str) -> Response:
        assert kind == 'cdx'
        if 'veterans.house.gov' in url:
            return Response(200, wb_cdx_payload, True, 'ev:wb:veterans', 'application/json', url)
        # Empty JSON array `[]` from Wayback when 0 captures exist
        return Response(200, b'[]', True, 'ev:wb:empty', 'application/json', url)

    empty_check = wayback_lookup(dl_target, fake_wayback_call, max_pages=1)
    assert empty_check['complete'] is True
    assert empty_check['candidates'] == []

    candidates_out = tmp_path / 'candidates.parquet'
    candidates = discover_target_candidates(
        [dl_target, house_target, gov_doc_target, gov_bill_target, wb_target],
        wayback_call=fake_wayback_call,
        house_listings={
            house_target: [
                {
                    'candidate_url': house_candidate,
                    'listing_url': house_listing_url,
                    'listing_urls': {house_target, house_candidate},
                    'evidence': 'ev:house:115432',
                    'target_version': 'v1',
                    'candidate_version': 'v1',
                }
            ]
        },
        govinfo_documents={
            gov_doc_target: [
                {
                    'package_id': 'CDOC-116hdoc12',
                    'expected_package_id': 'CDOC-116hdoc12',
                    'evidence': 'ev:govinfo:cdoc',
                }
            ]
        },
        govinfo_bills={
            gov_bill_target: [
                {
                    'congress': 118,
                    'bill_type': 'hr',
                    'number': 4775,
                    'version': 'ih',
                    'source_identity': {'congress': 118, 'bill_type': 'hr', 'number': 4775, 'version': 'ih'},
                    'evidence': 'ev:govinfo:bill',
                }
            ]
        },
        max_pages=1,
        output=candidates_out,
    )

    by_target = {(c['target_url'], c['source']): c for c in candidates}
    assert by_target[(dl_target, 'publisher_download_query_fallback')]['candidate_url'] == (
        'https://democrats-transportation.house.gov/download/witness-testimony?download=1'
    )
    assert by_target[(house_target, 'house_listing')]['candidate_url'] == house_candidate
    assert by_target[(gov_doc_target, 'govinfo')]['candidate_url'] == (
        'https://www.govinfo.gov/content/pkg/CDOC-116hdoc12/pdf/CDOC-116hdoc12.pdf'
    )
    assert by_target[(gov_bill_target, 'govinfo')]['candidate_url'] == (
        'https://www.govinfo.gov/content/pkg/BILLS-118hr4775ih/pdf/BILLS-118hr4775ih.pdf'
    )
    wb_cand = by_target[(wb_target, 'wayback')]
    assert wb_cand['original_url'] == wb_archived_orig
    assert wb_cand['candidate_url'] == f'https://web.archive.org/web/20210615102030id_/{wb_archived_orig}'
    assert pq.read_table(candidates_out).num_rows == 5


def test_discovery_runtime_wayback_control_and_replay(tmp_path: Path):
    target_url = 'https://www.veterans.house.gov/files/statement.html'
    archived_orig = 'http://veterans.house.gov:80/files/statement.html'
    body_bytes = (
        b'<html><title>Committee Statement</title>'
        b'<div class="field-name-body">' + b'Substantive witness statement text. ' * 60 + b'</div></html>'
    )
    digest_b32 = base64.b32encode(sha1(body_bytes).digest()).decode('ascii')

    cdx_payload = json.dumps([
        WAYBACK_FIELDS,
        [surt_key(target_url), '20210501120000', archived_orig, 'text/html', '200', digest_b32, str(len(body_bytes))],
    ]).encode('utf-8')

    class StubHttpResponse:
        def __init__(self, url: str, body: bytes):
            self.url = url
            self.body = body
            self.status_code = 200
            self.headers = {'content-type': 'application/json' if '/cdx/search/cdx' in url else 'text/html'}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, chunk_size: int):
            for i in range(0, len(self.body), chunk_size):
                yield self.body[i : i + chunk_size]

    class StubSession:
        def __init__(self):
            self.calls = []

        def get(self, url: str, **kwargs):
            self.calls.append(url)
            data = cdx_payload if '/cdx/search/cdx' in url else body_bytes
            return StubHttpResponse(url, data)

    admission = Admission(tmp_path / 'admission.sqlite', 10, 1000)
    runtime = DiscoveryRuntime(
        tmp_path / 'journal',
        binding={'campaign': 'runtime-test'},
        session=StubSession(),
        admission=admission,
        resolve=lambda _: ['8.8.8.8'],
    )
    candidates = discover_target_candidates([target_url], runtime=runtime, max_pages=1)
    assert len(candidates) == 1
    cand = candidates[0]
    fetched, operation = runtime.replay({
        'url': cand['candidate_url'],
        'original_url': cand['original_url'],
        'timestamp': cand['timestamp'],
        'digest': cand['digest'],
        'source': 'wayback',
    })
    assert operation
    assert fetched.final.body.path.read_bytes() == body_bytes
    assert fetched.final.body.sha256 == sha256(body_bytes).hexdigest()


def test_qualify_candidate_body_rejects_fake_pdf_and_accepts_valid_html(tmp_path: Path):
    cache_dir = tmp_path / 'qual-cache'
    good_html = tmp_path / 'good.html'
    good_html.write_text(
        '<html><title>Hearing Testimony</title>'
        '<div class="field-name-body">' + 'Substantive hearing testimony content. ' * 70 + '</div></html>'
    )
    verified, record = qualify_candidate_body(good_html, cache_dir, require_qualified=True)
    assert record['status'] == 'qualified'
    assert record['body_sha256'] == verified.sha256
    assert len(record.qualification_sha256) == 64

    fake_pdf = tmp_path / 'fake.pdf'
    fake_pdf.write_bytes(b'%PDF-1.4\nnot a valid pdf stream\n')
    _, bad_record = qualify_candidate_body(fake_pdf, cache_dir)
    assert bad_record['status'] != 'qualified'


def test_end_to_end_recovery_campaign_plan_import_reconcile_and_url_state(tmp_path: Path):
    policy = CapturePolicy(ROOT / 'model/registries/capture-scope.json')
    target_url = 'https://democrats-transportation.house.gov/download/witness-testimony&download=1'
    candidate_url = 'https://democrats-transportation.house.gov/download/witness-testimony?download=1'
    excluded_url = 'https://outside.example.com/unscoped.pdf'

    raw_dir = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_dir))
    writer = ReceiptWriter(
        store,
        identity=WRITER_IDENTITY,
        run_id='campaign-e2e',
        write_date='2026-10-31',
        archive_limits=None,
    )

    body_path = tmp_path / 'candidate.html'
    body_path.write_text(
        '<html><title>Prepared Statement</title>'
        '<div class="field-name-body">' + 'Prepared statement of witness before committee. ' * 65 + '</div></html>'
    )
    body_pin = pin_file(body_path)
    attempt = FetchAttempt(
        candidate_url,
        candidate_url,
        '2023-03-15T14:00:00Z',
        'direct',
        200,
        None,
        {},
        (),
        True,
        BodyFile(body_path, body_pin['sha256'], body_path.stat().st_size, 'text/html', None, None, None),
    )
    receipt_key, _ = writer.write(FetchResult(attempt), family='documents', mode='fetch')

    # Pinned source-native metadata records for target and candidate
    specs = {}
    for side, url in (('target', target_url), ('candidate', candidate_url)):
        meta = {
            'url': url,
            'meeting': 'H-118-SY00-1',
            'document': 'DOC-42',
            'version': 'ih',
            'date': '2023-03-15',
            'title': 'Prepared Statement',
            'witness': 'Dr. Jane Smith',
        }
        meta_path = tmp_path / f'{side}-meta.json'
        meta_path.write_text(json.dumps(meta))
        specs[side] = {
            'source': pin_file(meta_path),
            'source_url': 'https://docs.house.gov/meetings/SY/115432/metadata.json',
            'record_pointer': '',
            'url_field': 'url',
            'identifier_fields': {k: k for k in meta if k != 'url'},
            'required_fields': ['meeting', 'document', 'version'],
            'reviewed_by': 'publisher-metadata-review',
            'reviewed_at': STAMP,
        }

    import_req = {
        **specs,
        'body': body_pin,
        'receipt': pin_file(raw_dir / receipt_key),
        'relationship': 'recovered_document',
        'decided_by': 'campaign-identity-v1',
        'decided_at': STAMP,
    }

    with engine() as eng:
        campaign_res = run_recovery_campaign(
            tmp_path / 'campaign',
            campaign_id='e2e-normalized-campaign',
            targets=[target_url, excluded_url],
            policy=policy,
            engine=eng,
            import_requests=[import_req],
            writer=writer,
            store=store,
        )

        assert campaign_res['counts']['invariants'][0]['targets'] == 2
        dispositions = {r['disposition']: r['targets'] for r in campaign_res['counts']['dispositions']}
        assert dispositions == {'acquisition_excluded': 1, 'retained_candidate_pending': 1}
        assert len(campaign_res['imports']) == 1
        imp = campaign_res['imports'][0]
        assert imp['status'] == 'accepted'
        assert imp['provenance_key'].startswith('provenance/recoveries/')

        # Verify provenance record written by canonical provenance writer
        prov_path = raw_dir / imp['provenance_key']
        prov_lines = [
            json.loads(line)
            for line in prov_path.read_text(encoding='utf-8').splitlines()
            if line.strip()
        ]
        assert len(prov_lines) == 1
        prov_rec = prov_lines[0]
        validate_provenance('recoveries', prov_rec)
        assert prov_rec['recovery_record_version'] == 2
        assert prov_rec['acceptance_policy'] == VERSION
        assert prov_rec['original_url'] == target_url
        assert prov_rec['body_sha256'] == body_pin['sha256']

        # Reconcile accepted mapping through `reconcile_and_import_retained`
        accepted_json = tmp_path / 'accepted.json'
        accepted_json.write_text(
            json.dumps({
                'version': 1,
                'recoveries': [
                    {
                        'original_url': target_url,
                        'recovered_url': candidate_url,
                        'body_key': f"bodies/sha256/{body_pin['sha256'][:2]}/{body_pin['sha256']}.gz",
                        'kind': 'html',
                        'recovery_status': 'recovered',
                        'recovery_basis': 'verified_archive_capture',
                    }
                ],
            })
        )
        captures_pq = tmp_path / 'captures.parquet'
        pq.write_table(
            pa.Table.from_pylist([
                {
                    'sha256': body_pin['sha256'],
                    'mode': 'fetch',
                    'original_url': None,
                    'recovered_url': None,
                    'match_basis': None,
                    'recovery_category': None,
                    'url': candidate_url,
                    'retrieved_at': '2023-03-15T14:00:00Z',
                    'receipt_key': receipt_key,
                    'receipt_line': 1,
                    'capture_index': 0,
                    'bytes': body_path.stat().st_size,
                    'media_type': 'text/html',
                }
            ]),
            captures_pq,
        )
        rec_report = reconcile_and_import_retained(
            accepted_json,
            captures_pq,
            ROOT / 'model/registries/recovery-kinds.json',
            output_dir=tmp_path / 'reconciled',
            engine=eng,
            decided_at=STAMP,
            decided_by='reconciliation-test',
            writer=writer,
            body_paths_by_sha256={body_pin['sha256']: body_path},
        )
        assert rec_report['import_counts'] == {'ready': 1, 'unresolved': 0}
        assert len(rec_report['imported_receipts']) == 1

        # Evaluate full URL state steps + invariants (including recovery eligibility)
        state_work = tmp_path / 'url-state-work'
        inputs = registry_inputs(state_work / 'registries')
        inputs.extend([
            json_input(
                state_work,
                'fixture_captures',
                [
                    {
                        'receipt_key': 'r_fetch',
                        'receipt_line': 1,
                        'capture_index': 0,
                        'attempt': 0,
                        'mode': 'fetch',
                        'requested_url': target_url,
                        'url': target_url,
                        'context_url': target_url,
                        'member_path': None,
                        'family': 'documents',
                        'retrieved_at': '2023-03-15T14:00:00Z',
                        'http_status': 404,
                        'outcome': 'request_failed',
                        'complete': False,
                        'fetch_http_status': 404,
                        'fetch_outcome': 'request_failed',
                        'body_hex': None,
                        'record_role': 'error_response',
                        'original_url': None,
                    },
                    {
                        'receipt_key': imp['receipt_key'],
                        'receipt_line': 1,
                        'capture_index': 0,
                        'attempt': 0,
                        'mode': 'retained_import',
                        'requested_url': candidate_url,
                        'url': candidate_url,
                        'context_url': candidate_url,
                        'member_path': None,
                        'family': 'documents',
                        'retrieved_at': '2023-03-15T14:00:00Z',
                        'http_status': 200,
                        'outcome': 'stored',
                        'complete': True,
                        'fetch_http_status': 200,
                        'fetch_outcome': 'stored',
                        'body_hex': body_pin['sha256'],
                        'record_role': 'document',
                        'original_url': target_url,
                    },
                ],
                receipt_key='Utf8',
                receipt_line='Int32',
                capture_index='Int32',
                attempt='Int32',
                mode='Utf8',
                requested_url='Utf8',
                url='Utf8',
                context_url='Utf8',
                member_path='Utf8',
                family='Utf8',
                retrieved_at='Utf8',
                http_status='Int32',
                outcome='Utf8',
                complete='Boolean',
                fetch_http_status='Int32',
                fetch_outcome='Utf8',
                body_hex='Utf8',
                record_role='Utf8',
                original_url='Utf8',
            ),
            json_input(
                state_work,
                'resolved_links',
                [],
                target_url='Utf8',
                target_member_path='Utf8',
                page_body='Utf8',
                context_url='Utf8',
                member_path='Utf8',
            ),
            json_input(state_work, 'url_state_meeting_dates', [], requested_url='Utf8', meeting_date='Utf8'),
            json_input(state_work, 'url_variants', [], canonical_url='Utf8', variant_url='Utf8'),
            json_input(
                state_work,
                'recovery_requirements',
                [
                    {
                        'original_url': target_url,
                        'target_requirement': 'historical_exact',
                        'acceptance_policy': VERSION,
                        'refresh_policy': 'historical_only',
                    }
                ],
                original_url='Utf8',
                target_requirement='Utf8',
                acceptance_policy='Utf8',
                refresh_policy='Utf8',
            ),
            json_input(
                state_work,
                'recovery_decisions',
                [
                    {
                        'id': prov_rec['id'],
                        'original_url': prov_rec['original_url'],
                        'body_sha256': prov_rec['body_sha256'],
                        'kind': prov_rec['kind'],
                        'target_requirement': prov_rec['target_requirement'],
                        'acceptance_policy': prov_rec['acceptance_policy'],
                        'acceptance_status': prov_rec['acceptance_status'],
                        'evidence_sha256': prov_rec['evidence_sha256'],
                        'qualification_sha256': prov_rec['qualification_sha256'],
                        'recovery_record_version': prov_rec['recovery_record_version'],
                        'supersedes': prov_rec['supersedes'],
                    }
                ],
                id='Utf8',
                original_url='Utf8',
                body_sha256='Utf8',
                kind='Utf8',
                target_requirement='Utf8',
                acceptance_policy='Utf8',
                acceptance_status='Utf8',
                evidence_sha256='Utf8',
                qualification_sha256='Utf8',
                recovery_record_version='Int32',
                supersedes='Utf8',
            ),
        ])
        prep_steps = [
            {
                'name': 'captures',
                'sql': (
                    'SELECT * EXCLUDE(body_hex,record_role,retrieved_at),cast(NULL AS VARCHAR) AS expansion,'
                    "decode(body_hex,'hex') AS sha256,"
                    'arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'
                    '\'Timestamp(Microsecond, Some("UTC"))\') AS retrieved_at FROM fixture_captures'
                ),
            },
            {'name': 'record_roles', 'sql': 'SELECT receipt_key,receipt_line,capture_index,record_role FROM fixture_captures'},
            {'name': 'capture_evidence', 'sql': 'SELECT * FROM captures'},
            *model_steps(['good-fetches'], provided=['capture_evidence']),
            {'name': 'good_fetch_contexts', 'sql': 'SELECT receipt_key,receipt_line,capture_index,sha256,context_url,member_path FROM good_fetches'},
            {
                'name': 'resolved_link_targets',
                'sql': 'SELECT DISTINCT page_body,context_url,member_path,target_url,cast(NULL AS VARCHAR) AS target_member_path FROM resolved_links WHERE target_member_path IS NULL',
            },
            {
                'name': 'url_inputs',
                'sql': 'SELECT DISTINCT encode(sha256(json_array(url)),\'hex\') AS input_id,url FROM (SELECT requested_url AS url FROM captures UNION SELECT url FROM captures) WHERE url IS NOT NULL',
            },
            {'name': 'url_normalized', 'sql': (ROOT / 'model/sql/url-normalized.sql').read_text(), 'materialize': True},
            {'name': 'model_url_keys', 'sql': (ROOT / 'model/sql/url-keys.sql').read_text(), 'materialize': True},
        ]

        state_res = evaluate_campaign_url_state(
            state_work / 'job',
            engine=eng,
            inputs=inputs,
            prep_steps=prep_steps,
            recovery_policy={'acceptance_policy': VERSION},
            output_dir=tmp_path / 'release',
        )
        assert not any(state_res['url_state_invariants'][0].values())
        assert 'url_state' not in state_res
        rows = {r['requested_url']: r for r in pq.read_table(state_res['url_state_parquet']).to_pylist()}
        assert rows[target_url]['capture_disposition'] == 'satisfied'
        assert rows[target_url]['capture_decision_id'] == prov_rec['id']


def test_wayback_lookup_preserves_pagination_before_empty_array_and_rejects_mismatched_surt():
    target_url = 'https://www.veterans.house.gov/sites/republicans.veterans.house.gov/files/testimony.pdf'
    archived_orig = 'http://veterans.house.gov:80/sites/republicans.veterans.house.gov/files/testimony.pdf'
    page1_payload = json.dumps([
        WAYBACK_FIELDS,
        [surt_key(target_url), '20210615102030', archived_orig, 'application/pdf', '200', 'A' * 32, '4096'],
        [],
        ['resume-token-2'],
    ]).encode('utf-8')

    def paginated_call(kind: str, url: str) -> Response:
        assert kind == 'cdx'
        if 'resumeKey=resume-token-2' in url:
            return Response(200, b'[]', True, 'ev:wb:page2', 'application/json', url)
        return Response(200, page1_payload, True, 'ev:wb:page1', 'application/json', url)

    res = wayback_lookup(target_url, paginated_call, max_pages=2)
    assert res['complete'] is True
    assert [e['ref'] for e in res['evidence']] == ['ev:wb:page1', 'ev:wb:page2']
    assert len(res['candidates']) == 1
    assert res['candidates'][0]['target_url'] == target_url
    assert res['candidates'][0]['original_url'] == archived_orig

    # Negative control: mismatched archived original URL must be rejected
    bad_orig_payload = json.dumps([
        WAYBACK_FIELDS,
        [
            surt_key(target_url),
            '20210615102030',
            'http://veterans.house.gov:80/sites/republicans.veterans.house.gov/files/other.pdf',
            'application/pdf',
            '200',
            'A' * 32,
            '4096',
        ],
    ]).encode('utf-8')
    bad_res = wayback_lookup(
        target_url,
        lambda kind, url: Response(200, bad_orig_payload, True, 'ev:wb:bad', 'application/json', url),
        max_pages=1,
    )
    assert bad_res['complete'] is False
    assert bad_res['reason'] == 'invalid_index_response'
    assert bad_res['candidates'] == []


def test_import_accepted_candidates_rejects_mismatched_source_native_bill_metadata(tmp_path: Path):
    policy = CapturePolicy(ROOT / 'model/registries/capture-scope.json')
    target_url = 'https://docs.house.gov/meetings/FA/FA00/20230713/116205/BILLS-118-hr-4824.pdf'
    candidate_url = 'https://www.govinfo.gov/content/pkg/BILLS-118hr4755ih/html/BILLS-118hr4755ih.htm'

    raw_dir = tmp_path / 'raw'
    store = BodyStore(LocalAdapter(raw_dir))
    writer = ReceiptWriter(
        store,
        identity=WRITER_IDENTITY,
        run_id='campaign-neg',
        write_date='2026-10-31',
        archive_limits=None,
    )

    body_path = tmp_path / 'candidate.html'
    body_path.write_text(
        '<html><title>H.R. 4755</title>'
        '<div class="field-name-body">' + 'Text of H.R. 4755 introduced in House. ' * 65 + '</div></html>'
    )
    body_pin = pin_file(body_path)
    attempt = FetchAttempt(
        candidate_url,
        candidate_url,
        '2023-07-13T14:00:00Z',
        'direct',
        200,
        None,
        {},
        (),
        True,
        BodyFile(body_path, body_pin['sha256'], body_path.stat().st_size, 'text/html', None, None, None),
    )
    receipt_key, _ = writer.write(FetchResult(attempt), family='documents', mode='fetch')

    # Target metadata specifies HR-4824, while candidate metadata specifies HR-4755
    specs = {}
    for side, url, bill_doc in (
        ('target', target_url, 'HR-4824'),
        ('candidate', candidate_url, 'HR-4755'),
    ):
        meta = {
            'url': url,
            'meeting': 'H-118-FA00-116205',
            'document': bill_doc,
            'version': 'ih',
        }
        meta_path = tmp_path / f'{side}-meta.json'
        meta_path.write_text(json.dumps(meta))
        specs[side] = {
            'source': pin_file(meta_path),
            'source_url': 'https://docs.house.gov/meetings/FA/116205/metadata.json',
            'record_pointer': '',
            'url_field': 'url',
            'identifier_fields': {'meeting': 'meeting', 'document': 'document', 'version': 'version'},
            'required_fields': ['meeting', 'document', 'version'],
            'reviewed_by': 'publisher-metadata-review',
            'reviewed_at': STAMP,
        }

    with engine() as eng:
        campaign_res = run_recovery_campaign(
            tmp_path / 'campaign-neg',
            campaign_id='neg-bill-mismatch',
            targets=[target_url],
            policy=policy,
            candidates=[{'target_url': target_url, 'candidate_url': candidate_url, 'source': 'govinfo'}],
            engine=eng,
            import_requests=[
                {
                    **specs,
                    'body': body_pin,
                    'receipt': pin_file(raw_dir / receipt_key),
                    'relationship': 'recovered_document',
                    'decided_by': 'campaign-identity-v1',
                    'decided_at': STAMP,
                }
            ],
            writer=writer,
            store=store,
        )
    results = campaign_res['imports']
    assert len(results) == 1
    assert results[0]['status'] == 'rejected'
    assert results[0]['reason'] == 'conflicting_document'
    assert results[0].get('receipt_key') is None
    assert results[0].get('provenance_key') is None


def test_scan_receipt_history_and_inventory_edge_cases(tmp_path: Path):
    """F1, F2, F5: multi-row captures, cross-row status/body isolation, redirected URLs, wrapper rejection, offline DNS, and URL normalization."""
    # Offline resolver ensures static inventory never calls live DNS
    policy = CapturePolicy(
        ROOT / 'model/registries/capture-scope.json',
        resolve=lambda host: (_ for _ in ()).throw(OSError('offline DNS should not be called')),
    )

    multi_row_url = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-WState-1.pdf'
    cross_row_url = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-WState-2.pdf'
    redirected_target = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-WState-3.pdf'
    redirected_final = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-WState-3-final.pdf'
    html_wrapper_download = 'https://democrats-science.house.gov/download/witness-testimony?download=1'
    amp_target = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'

    captures = pa.Table.from_pylist([
        # 1a. Initial 404 failure for multi_row_url
        {
            'url': multi_row_url,
            'context_url': multi_row_url,
            'requested_url': multi_row_url,
            'family': 'documents',
            'body_key': None,
            'sha256': None,
            'media_type': 'text/html',
            'retrieved_at': '2026-01-01T00:00:00Z',
            'resolution': 'error',
            'http_status': 404,
            'complete': False,
            'receipt_key': 'receipts/r1.jsonl.gz',
            'receipt_line': 1,
        },
        # 1b. Later 200 valid PDF capture for multi_row_url
        {
            'url': multi_row_url,
            'context_url': multi_row_url,
            'requested_url': multi_row_url,
            'family': 'documents',
            'body_key': 'bodies/sha256/aa/' + 'a' * 64 + '.gz',
            'sha256': 'a' * 64,
            'media_type': 'application/pdf',
            'retrieved_at': '2026-02-01T00:00:00Z',
            'resolution': 'stored',
            'http_status': 200,
            'complete': True,
            'receipt_key': 'receipts/r2.jsonl.gz',
            'receipt_line': 2,
        },
        # 2. 403 error body for cross_row_url (ct-sh4j / GB1)
        {
            'url': cross_row_url,
            'context_url': cross_row_url,
            'requested_url': cross_row_url,
            'family': 'documents',
            'body_key': 'bodies/sha256/bb/' + 'b' * 64 + '.gz',
            'sha256': 'b' * 64,
            'media_type': 'text/html',
            'retrieved_at': '2026-01-01T00:00:00Z',
            'resolution': 'error',
            'http_status': 403,
            'complete': True,
            'receipt_key': 'receipts/r3.jsonl.gz',
            'receipt_line': 1,
        },
        # 3. Redirected capture where requested_url != url
        {
            'url': redirected_final,
            'context_url': redirected_final,
            'requested_url': redirected_target,
            'family': 'documents',
            'body_key': 'bodies/sha256/cc/' + 'c' * 64 + '.gz',
            'sha256': 'c' * 64,
            'media_type': 'application/pdf',
            'retrieved_at': '2026-02-01T00:00:00Z',
            'resolution': 'stored',
            'http_status': 200,
            'complete': True,
            'receipt_key': 'receipts/r4.jsonl.gz',
            'receipt_line': 1,
        },
        # 4. HTTP 200 HTML wrapper on a /download/ route must not be usable_direct
        {
            'url': html_wrapper_download,
            'context_url': html_wrapper_download,
            'requested_url': html_wrapper_download,
            'family': 'documents',
            'body_key': 'bodies/sha256/dd/' + 'd' * 64 + '.gz',
            'sha256': 'd' * 64,
            'media_type': 'text/html; charset=utf-8',
            'retrieved_at': '2026-02-01T00:00:00Z',
            'resolution': 'stored',
            'http_status': 200,
            'complete': True,
            'receipt_key': 'receipts/r5.jsonl.gz',
            'receipt_line': 1,
        },
    ])
    states = pa.Table.from_pylist([
        # Status-less 'unchanged' state row for cross_row_url must NOT combine with 403 body_key
        {
            'requested_url': cross_row_url,
            'attempts': 2,
            'outcome': 'unchanged',
            'http_status': None,
            'checked_at': '2026-03-01T00:00:00Z',
        }
    ])

    inv = build_target_inventory(
        [multi_row_url, cross_row_url, redirected_target, html_wrapper_download, amp_target],
        policy=policy,
        captures=captures,
        states=states,
    )
    by_url = {r['target_url']: r for r in inv}

    assert by_url[multi_row_url]['usable_direct'] is True
    assert by_url[multi_row_url]['evidence_id'] == 'receipts/r2.jsonl.gz#2'

    assert by_url[cross_row_url]['usable_direct'] is False
    assert by_url[cross_row_url]['acquisition_excluded'] is False

    assert by_url[redirected_target]['usable_direct'] is True
    assert by_url[redirected_target]['evidence_id'] == 'receipts/r4.jsonl.gz#1'

    assert by_url[html_wrapper_download]['usable_direct'] is False
    assert by_url[html_wrapper_download]['acquisition_excluded'] is False

    # F5: normalized_url and url_key are computed from url-rules.json without calling DNS
    assert by_url[amp_target]['acquisition_excluded'] is False
    assert by_url[amp_target]['normalized_url'] == (
        'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'
    )
    assert by_url[amp_target]['url_key'] == (
        'democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'
    )


def test_discover_target_candidates_preserves_literals_and_replay_schema(tmp_path: Path):
    """F3, F6/Work Item 5, F7, F10: literal target_url, dot-segment Wayback original_url, narrow repairs, and Parquet replay columns."""
    with pytest.raises(ValueError, match='invalid target'):
        wayback_lookup('not-a-valid-url', lambda kind, url: (_ for _ in ()).throw(AssertionError('should not call')), max_pages=1)

    frag_target = 'https://democrats-science.house.gov/download/witness-testimony&download=1#page=2'
    wb_target = 'https://www.veterans.house.gov/files/statement.html'
    wb_dot_orig = 'http://veterans.house.gov:80/a/../files/statement.html'
    mailto_target = 'mailto:https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-1.pdf'
    file_path_target = 'http://File URL path: /docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-2.pdf'
    space_target = 'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-3.pdf%20%20'

    wb_payload = json.dumps([
        WAYBACK_FIELDS,
        [surt_key(wb_target), '20210615102030', wb_dot_orig, 'text/html', '200', 'B' * 32, '2048'],
    ]).encode('utf-8')

    out_pq = tmp_path / 'candidates.parquet'
    cands = discover_target_candidates(
        [frag_target, wb_target, mailto_target, file_path_target, space_target],
        wayback_call=lambda kind, url: (
            Response(200, wb_payload, True, 'ev:wb:dot', 'application/json', url)
            if 'veterans.house.gov' in url
            else Response(200, b'[]', True, 'ev:wb:empty', 'application/json', url)
        ),
        max_pages=1,
        output=out_pq,
    )
    by_target = {c['target_url']: c for c in cands}

    # Exact target_url with #fragment is preserved
    assert frag_target in by_target
    assert by_target[frag_target]['candidate_url'] == (
        'https://democrats-science.house.gov/download/witness-testimony?download=1'
    )

    # Wayback candidate_url preserves dot-segment original_url verbatim
    assert by_target[wb_target]['candidate_url'] == f'https://web.archive.org/web/20210615102030id_/{wb_dot_orig}'

    # Narrow repairs for mailto:, File URL path:, and trailing %20
    assert by_target[mailto_target]['candidate_url'] == (
        'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-1.pdf'
    )
    assert by_target[file_path_target]['candidate_url'] == (
        'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-2.pdf'
    )
    assert by_target[space_target]['candidate_url'] == (
        'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-3.pdf'
    )

    # F7: write_candidates_parquet deduplicates and preserves Wayback replay columns
    dup_pq = tmp_path / 'dup_candidates.parquet'
    write_candidates_parquet(cands + cands, dup_pq)
    persisted = pq.read_table(dup_pq).to_pylist()
    assert len(persisted) == len(cands)
    wb_persisted = next(r for r in persisted if r['target_url'] == wb_target)
    assert wb_persisted['original_url'] == wb_dot_orig
    assert wb_persisted['timestamp'] == '20210615102030'
    assert wb_persisted['digest'] == 'B' * 32


def test_reconcile_and_import_retained_enforces_unresolved_gate_and_empty_suffix(tmp_path: Path):
    """F8: unresolved gate blocks silent partial imports unless ready_only=True, and stored_suffix='' is preserved."""
    ready_url = 'https://democrats-science.house.gov/download/ready-doc&download=1'
    ready_rec = 'https://democrats-science.house.gov/download/ready-doc?download=1'
    unres_url = 'https://democrats-science.house.gov/download/unresolved-doc&download=1'
    unres_rec = 'https://democrats-science.house.gov/download/unresolved-doc?download=1'
    sha_ready = 'e' * 64
    sha_unres = 'f' * 64

    accepted_json = tmp_path / 'accepted.json'
    accepted_json.write_text(json.dumps({
        'version': 1,
        'recoveries': [
            {
                'original_url': ready_url,
                'recovered_url': ready_rec,
                'body_key': f'bodies/sha256/{sha_ready[:2]}/{sha_ready}.gz',
                'kind': 'pdf',
                'recovery_status': 'recovered',
                'recovery_basis': 'verified_archive_capture',
            },
            {
                'original_url': unres_url,
                'recovered_url': unres_rec,
                'body_key': f'bodies/sha256/{sha_unres[:2]}/{sha_unres}.gz',
                'kind': 'pdf',
                'recovery_status': 'recovered',
                'recovery_basis': 'verified_archive_capture',
            },
        ],
    }))
    captures_pq = tmp_path / 'captures.parquet'
    pq.write_table(
        pa.Table.from_pylist([
            {
                'sha256': sha_ready,
                'mode': 'fetch',
                'original_url': None,
                'recovered_url': None,
                'match_basis': None,
                'recovery_category': None,
                'url': ready_rec,
                'retrieved_at': '2023-03-15T14:00:00Z',
                'receipt_key': 'receipts/r1.jsonl.gz',
                'receipt_line': 1,
                'capture_index': 0,
                'bytes': 1024,
                'media_type': 'application/pdf',
                'stored_suffix': '',
            }
        ]),
        captures_pq,
    )
    raw_dir = tmp_path / 'raw'
    uncompressed_body = raw_dir / 'bodies' / 'sha256' / sha_ready[:2] / sha_ready
    uncompressed_body.parent.mkdir(parents=True, exist_ok=True)
    uncompressed_body.write_bytes(b'%PDF-1.4\n' + b'x' * 1015)
    store = BodyStore(LocalAdapter(raw_dir))
    writer = ReceiptWriter(
        store,
        identity=WRITER_IDENTITY,
        run_id='reconcile-gate-test',
        write_date='2026-10-31',
        archive_limits=None,
    )

    with engine() as eng:
        with pytest.raises(ValueError, match='Unresolved source times remain'):
            reconcile_and_import_retained(
                accepted_json,
                captures_pq,
                ROOT / 'model/registries/recovery-kinds.json',
                output_dir=tmp_path / 'stage-blocked',
                engine=eng,
                decided_at=STAMP,
                decided_by='reconciliation-test',
                writer=writer,
                ready_only=False,
            )

        res = reconcile_and_import_retained(
            accepted_json,
            captures_pq,
            ROOT / 'model/registries/recovery-kinds.json',
            output_dir=tmp_path / 'stage-ready-only',
            engine=eng,
            decided_at=STAMP,
            decided_by='reconciliation-test',
            writer=writer,
            ready_only=True,
        )
        assert res['import_counts'] == {'ready': 1, 'unresolved': 1}
        assert len(res['imported_receipts']) == 1
        rec_cap = res['imported_receipts'][0]['record']['captures'][0]
        # Uncompressed stored_suffix='' must be preserved on the retained body reference
        assert rec_cap['sha256'] == sha_ready
        assert store.known[f'bodies/sha256/{sha_ready[:2]}/{sha_ready}'].suffix == ''


def test_acceptance_rejects_mismatched_pdf_bill_body_hr4824(tmp_path: Path):
    """F6 / Work Item 4: acceptance.decide rejects the real hr-4824 PDF whose body is H.R. 4755."""
    pdf_src = ROOT / 'docs/experiments/url-normalization-validation-20261031/evidence/accepted-hr4824.pdf'
    if not pdf_src.is_file():
        pytest.skip('accepted-hr4824.pdf evidence file not present')

    verified, qual = qualify_candidate_body(pdf_src, tmp_path / 'qual-cache', require_qualified=True)
    candidate_url = 'https://democrats-science.house.gov/download/hr-4824?download=1'
    receipt = {
        'http_status': 200,
        'url': candidate_url,
        'retrieved_at': STAMP,
        'response_headers': {},
        'captures': [
            {
                'attempt': 0,
                'member_path': None,
                'context_url': candidate_url,
                'complete': True,
                'sha256': verified.sha256,
                'bytes': verified.size_bytes,
            }
        ],
    }

    # Even if both target and candidate metadata claim HR-4824, the PDF body's page-1 heading is H.R. 4755
    target_4824 = {
        'url': 'https://democrats-science.house.gov/download/hr-4824&download=1',
        'identifiers': {'bill': 'HR-4824', 'congress': 118},
        'required_fields': ['bill', 'congress'],
    }
    cand_4824 = {
        'url': candidate_url,
        'identifiers': {'bill': 'HR-4824', 'congress': 118},
        'required_fields': ['bill', 'congress'],
    }
    bad_decision = decide(
        target_4824,
        cand_4824,
        requirement='historical_exact',
        relationship='recovered_document',
        body=verified,
        qualification=dict(qual),
        receipt=receipt,
        receipt_sha256='c' * 64,
    )
    assert bad_decision['status'] == 'review_required'
    assert bad_decision['reason'] == 'conflicting_body_bill_identifier'

    # Positive control: when target and candidate specify HR-4755, the PDF body corroborates
    target_4755 = {
        'url': 'https://democrats-science.house.gov/download/hr-4755&download=1',
        'identifiers': {'bill': 'HR-4755', 'congress': 118},
        'required_fields': ['bill', 'congress'],
    }
    cand_4755 = {
        'url': candidate_url,
        'identifiers': {'bill': 'HR-4755', 'congress': 118},
        'required_fields': ['bill', 'congress'],
    }
    good_decision = decide(
        target_4755,
        cand_4755,
        requirement='historical_exact',
        relationship='recovered_document',
        body=verified,
        qualification=dict(qual),
        receipt=receipt,
        receipt_sha256='c' * 64,
    )
    assert good_decision['status'] == 'accepted'
    assert good_decision['reason'] == 'source_identifiers_match'


# --- URL identity parity, scope probes, discovery coverage, history rows, reruns ---

from datetime import datetime, timezone  # noqa: E402

import corpus_recovery.pipeline as pipeline_module  # noqa: E402
from corpus_recovery.inventory import (  # noqa: E402
    _is_usable_direct_row, _iter_table_rows, _row_evidence_id, _row_order_key,
    narrow_address_repairs, url_identity,
)

URL_KEY_CASES = json.loads((ROOT / 'model/fixtures/url-key-cases.json').read_text())


@pytest.mark.parametrize('case', URL_KEY_CASES, ids=[c['id'] for c in URL_KEY_CASES])
def test_url_identity_matches_every_model_url_key_fixture(case):
    """R2-F1: the Python twin agrees with url-normalized.sql + url-keys.sql on every fixture."""
    identity = url_identity(case['url'])
    assert identity['url_key'] == case['key']
    assert identity['error'] == case.get('error')
    assert identity['still_wrapped'] == case.get('still_wrapped', False)
    if case['key'] is None:
        assert identity['normalized_url'] is None


def test_url_identity_keeps_normalized_url_distinct_from_key():
    """R2-F1: normalized_url is the SQL `parsed` URL; only url_key drops scheme, www., one slash."""
    identity = url_identity('HTTP://WWW.Example.GOV:80/a b//c/%7e/?z=1&utm_source=x#frag')
    assert identity['normalized_url'] == 'http://www.example.gov/a%20b//c/~/?z=1&utm_source=x#frag'
    assert identity['url_key'] == 'example.gov/a%20b//c/~?z=1'


PARITY_EXTRA_URLS = [
    'https://example.gov/a//b//c.pdf', 'https://example.gov/a//', 'https://example.gov/a?&&b=1&',
    'https://example.gov/a?', 'https://Example.gov/A/%2e%2E/b', 'https:example.gov/a', 'https:\\\\example.gov\\a',
    '  https://example.gov/a\tb  ', 'https://example.gov/a"<>`{}|^b?x=\'"#f`', 'https://example.gov/%zz%2',
    'https://exa%6Dple.gov/a', 'https://ex ample.gov/a', 'https://例え.テスト/a', 'https://0x7f.1/a',
    'https://[0:0:0:0:0:0:0:1]:8080/a', 'https://user:pass@www.example.gov/a', 'http://example.gov:0080/x',
    'https://example.gov:99999/x', 'mailto:https://example.gov/a', 'HTTPS://WWW.CONGRESS.GOV/b?Q=x&q=y&UTM_y=2',
    'https://www.judiciary.senate.gov/404?notfound=%2fdownload%2f%E9%2fa%20b',
    'https://urldefense.com/v2/url?u=https-3A__web.archive.org_web_20250610160415_https-3A__example.gov_a.pdf&d=x',
]


def test_url_identity_matches_native_sql_on_edge_cases(tmp_path: Path):
    """R2-F1: cross-check WHATWG parsing and RFC 3986 escapes against the native engine."""
    rules = json.loads((ROOT / 'model/registries/url-rules.json').read_text())
    inputs = [
        json_input(tmp_path, 'url_inputs', [dict(input_id=f'{i:03d}', url=u) for i, u in enumerate(PARITY_EXTRA_URLS)],
                   input_id='Utf8', url='Utf8'),
        json_input(tmp_path, 'url_rules', rules, id='Utf8', kind='Utf8', host_pattern='Utf8', pattern='Utf8',
                   replacement='Utf8', decoder='Utf8'),
        json_input(tmp_path, 'url_variants', [], canonical_url='Utf8', variant_url='Utf8'),
    ]
    from congress_api.retention.provenance import run_job
    with engine() as eng:
        native = run_job(tmp_path, eng, inputs=inputs, steps=[
            dict(name='url_normalized', materialize=True, sql=(ROOT / 'model/sql/url-normalized.sql').read_text()),
            dict(name='url_keys', sql=(ROOT / 'model/sql/url-keys.sql').read_text()),
        ], outputs=[], queries=[dict(name='keys', sql='SELECT * FROM url_keys ORDER BY input_id')])['keys']
    for row in native:
        identity = url_identity(PARITY_EXTRA_URLS[int(row['input_id'])])
        assert (identity['url_key'], identity['error'], identity['still_wrapped']) == (
            row['url_key'], row['error'], row['still_wrapped']), row['url']


def test_inventory_scope_uses_repaired_and_unwrapped_spellings(tmp_path: Path):
    """R2-F3: senate-notfound, t2GPO, fragment and http:// targets are judged by their repaired spelling."""
    policy = CapturePolicy(ROOT / 'model/registries/capture-scope.json',
                           resolve=lambda host: (_ for _ in ()).throw(OSError('no DNS')))
    in_scope = [
        'https://www.judiciary.senate.gov/404?notfound=%2fdownload%2f01%2f06%2f2026%2fbenton-sjq#page=1',
        'https://www.lis.gov/cgi-lis/t2GPO/https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf',
        'https://www.congress.gov/cgi-lis/t2GPO/https://www.gpo.gov/fdsys/pkg/BILLS-113hr4005ih/pdf/BILLS-113hr4005ih.pdf',
        'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-1.pdf#page=2',
        'http://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-2.pdf',
    ]
    out_of_scope = 'https://outside.example.com/a.pdf#page=1'
    rows = build_target_inventory(in_scope + [out_of_scope], policy=policy, history={}, output=tmp_path / 't.parquet')
    by_url = {r['target_url']: r for r in rows}
    assert all(by_url[u]['acquisition_excluded'] is False for u in in_scope)
    assert by_url[out_of_scope]['acquisition_excluded'] is True
    assert pq.read_schema(tmp_path / 't.parquet').names[-1] == 'context_url'


def test_narrow_repairs_resolve_relative_file_url_path_and_reescape_spaces():
    """R2-F3: the corpus's relative File URL path literal resolves against its context page."""
    literal = 'http://File URL path: /sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf'
    context = 'https://naturalresources.house.gov/calendar/eventsingle.aspx?EventID=402426'
    assert narrow_address_repairs(literal) == []
    assert narrow_address_repairs(literal, context) == [(
        'https://naturalresources.house.gov/sites/default/files/documents/7.7.17DallinMaybeeTestimoney.pdf',
        'file_url_path_prefix_repair',
    )]
    senate = 'https://www.judiciary.senate.gov/404?notfound=%2fdownload%2fa%20b%20testimony'
    assert ('https://www.judiciary.senate.gov/download/a%20b%20testimony', 'senate_notfound_wrapper_repair') in (
        narrow_address_repairs(senate))
    senate_amp = 'https://www.finance.senate.gov/404?notfound=%2fdownload%2ftest%26download%3d1'
    assert narrow_address_repairs(senate_amp) == [
        ('https://www.finance.senate.gov/download/test&download=1', 'senate_notfound_wrapper_repair'),
        ('https://www.finance.senate.gov/download/test?download=1', 'publisher_download_query_fallback'),
    ]
    senate_space = 'https://www.finance.senate.gov/404?notfound=%2fdownload%2ftest.pdf%20'
    assert narrow_address_repairs(senate_space) == [
        ('https://www.finance.senate.gov/download/test.pdf%20', 'senate_notfound_wrapper_repair'),
        ('https://www.finance.senate.gov/download/test.pdf', 'trailing_space_trim_repair'),
    ]
    t2gpo = 'https://www.congress.gov/cgi-lis/t2GPO/https://www.gpo.gov/fdsys/pkg/X/pdf/X.pdf'
    assert narrow_address_repairs(t2gpo) == [('https://www.gpo.gov/fdsys/pkg/X/pdf/X.pdf',
                                               'congress_t2gpo_wrapper_repair')]

    rows = discover_target_candidates([{'target_url': literal, 'context_url': context}])
    assert [r['candidate_url'] for r in rows] == [narrow_address_repairs(literal, context)[0][0]]


def test_discovery_probes_every_repair_and_retains_lookup_diagnostics(tmp_path: Path):
    """R2-F6: valid-HTTP malformed targets are probed raw and repaired; config errors propagate."""
    target = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1'
    repaired = 'https://democrats-science.house.gov/download/ashley-nunes-witness-testimony?download=1'
    queried = []

    def wayback(kind, url):
        queried.append(url)
        return Response(200, b'[]', True, f'ev:{len(queried)}', 'application/json', url)

    diagnostics: list = []
    discover_target_candidates([target], wayback_call=wayback, max_pages=1, from_timestamp='2020',
                               diagnostics=diagnostics)
    assert [d['probe_url'] for d in diagnostics] == [target, repaired]
    assert all(d['complete'] is True and d['reason'] == 'complete' and d['window'] == {'from': '2020', 'to': None}
               and d['evidence'][0]['ref'] for d in diagnostics)
    assert len(queried) == 2

    with pytest.raises(ValueError, match='invalid target or limits'):
        discover_target_candidates([target], wayback_call=wayback, max_pages=0)
    with pytest.raises(ValueError, match='reversed archive time bounds'):
        discover_target_candidates([target], wayback_call=wayback, from_timestamp='2024', to_timestamp='2020')
    with pytest.raises(ValueError, match='invalid target or collection'):
        discover_target_candidates([target], webharvest_call=wayback, webharvest_collections=['bogus'])
    with pytest.raises(ValueError, match='durable evidence'):
        discover_target_candidates([target], wayback_call=lambda kind, url: Response(200, b'[]', True, '', 'application/json', url))
    # Non-URL literals are skipped by the explicit pre-check rather than a swallowed error.
    assert discover_target_candidates(['mailto:nobody'], wayback_call=wayback) == []


def test_write_candidates_parquet_accepts_discovery_rows_and_preserves_metadata(tmp_path: Path):
    """R2-F6: raw discovery `url` rows keep listing, mapping, version, and identity metadata."""
    from corpus_recovery.discovery import govinfo_bill_candidate, house_listing_candidate
    xml = 'https://docs.house.gov/meetings/PW/PW00/20230315/115432/HHRG-118-PW00-20230315-SD001.xml'
    pdf = xml[:-4] + '.pdf'
    listing = 'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=115432'
    identity = {'congress': 118, 'bill_type': 'hr', 'number': 4775, 'version': 'ih'}
    rows = [
        house_listing_candidate(xml, pdf, listing_url=listing, listing_urls={xml, pdf}, evidence='ev:l',
                                target_version='v1', candidate_version='v1'),
        govinfo_bill_candidate(xml, 118, 'hr', 4775, 'ih', source_identity=identity, evidence='ev:b'),
    ]
    out = write_candidates_parquet(rows, tmp_path / 'c.parquet')
    persisted = pq.read_table(out).to_pylist()
    assert persisted[0]['candidate_url'] == pdf
    assert (persisted[0]['listing_url'], persisted[0]['version'], persisted[0]['mapping']) == (
        listing, 'v1', 'house-listed-sibling-v1')
    assert json.loads(persisted[1]['identity']) == identity
    for bad in ({'target_url': xml, 'url': ''}, {'target_url': xml, 'candidate_url': None}, {'url': pdf}):
        with pytest.raises(ValueError, match='non-empty target_url'):
            write_candidates_parquet([bad], tmp_path / 'bad.parquet')


def test_usable_direct_row_requires_complete_intact_document_evidence():
    """R2-F7: explicit gates on completeness, integrity, role, mode, evidence, and HTML wrappers."""
    good = dict(body_key='bodies/x', outcome='stored', http_status=200, media_type='application/pdf',
                receipt_key='receipts/r.jsonl.gz', receipt_line=None, complete=True)
    assert _is_usable_direct_row(good)
    assert _row_evidence_id(good) == 'receipts/r.jsonl.gz#1'
    assert _is_usable_direct_row({k: v for k, v in good.items() if k != 'complete'})
    for change in (dict(complete=None), dict(complete=False), dict(intact=False), dict(mode='retained_import'),
                   dict(record_role='listing'), dict(receipt_key=None, body_key=None, sha256='a' * 64),
                   dict(usable_direct=False)):
        assert not _is_usable_direct_row({**good, **change}), change
    assert not _is_usable_direct_row({**good, 'receipt_key': None, 'body_key': None, 'usable_direct': True})
    assert _is_usable_direct_row({**good, 'record_role': 'document'})
    html = {**good, 'media_type': 'text/html', 'url': 'https://example.senate.gov/page'}
    assert _is_usable_direct_row(html)
    for column, value in (('requested_url', 'https://x.senate.gov/404?notfound=download/a'),
                          ('context_url', 'https://x.house.gov/files/a.docx'),
                          ('requested_url', 'https://x.house.gov/files/a.xml?v=1')):
        assert not _is_usable_direct_row({**html, column: value}), value


def test_row_order_and_table_scan_normalize_instants_and_project(tmp_path: Path):
    """R2-F7: datetimes order with ISO strings; scans short-circuit, project, and keep max attempts."""
    later = dict(retrieved_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    earlier = dict(retrieved_at='2026-01-31T23:59:59Z')
    assert _row_order_key(later) > _row_order_key(earlier)
    assert _row_order_key(dict(last_attempt='2026-03-01T00:00:00+00:00')) > _row_order_key(later)

    assert list(_iter_table_rows(tmp_path / 'missing.parquet', wanted=set())) == []
    url = 'https://docs.house.gov/meetings/a.pdf'
    path = tmp_path / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist([
        dict(url=url, payload='x' * 100, receipt_key='r', receipt_line=i, outcome='stored') for i in range(3)
    ] + [dict(url='https://other.gov/', payload='y', receipt_key='r', receipt_line=9, outcome='stored')]), path)
    rows = list(_iter_table_rows(path, wanted={url}))
    assert len(rows) == 3 and 'payload' not in rows[0]

    outcomes = pa.Table.from_pylist([dict(url=url, attempts=1, outcome='request_failed', checked_at=STAMP)])
    history = scan_receipt_history(captures=path, fetch_outcomes=outcomes, urls=[url])
    assert history[url]['attempts'] == 3
    assert scan_receipt_history(captures=path, urls=[]) == {}


class _StopCampaign(Exception):
    pass


def test_run_recovery_campaign_forwards_inventory_inputs(tmp_path: Path, monkeypatch):
    """R2-F10: history, store, membership, and refresh inputs reach build_target_inventory."""
    seen = {}

    def fake_inventory(targets, **kwargs):
        seen.update(kwargs)
        raise _StopCampaign

    monkeypatch.setattr(pipeline_module, 'build_target_inventory', fake_inventory)
    history = {'https://example.gov/a': {}}
    with pytest.raises(_StopCampaign):
        run_recovery_campaign(tmp_path, campaign_id='c', targets=['https://example.gov/a'], engine=None,
                              source_or_store=tmp_path / 'raw', history=history,
                              membership_origin='later_batch', refresh_policy='refresh_live')
    assert seen['source_or_store'] == tmp_path / 'raw' and seen['history'] is history
    assert (seen['membership_origin'], seen['refresh_policy']) == ('later_batch', 'refresh_live')


def test_import_accepted_candidates_names_operations_by_request_digest(tmp_path: Path, monkeypatch):
    """R2-F9: request files and operation dirs do not depend on list order."""
    calls = []

    def fake_import(descriptor, request_path, *, output, **kwargs):
        calls.append((Path(request_path).name, Path(output).name))
        return {'status': 'accepted', 'operation': Path(output).name}

    monkeypatch.setattr(pipeline_module, 'import_candidate', fake_import)
    a, b = {'id': 'a'}, {'id': 'b'}
    common = dict(output_dir=tmp_path / 'ops', engine=None, writer=None, store=None)
    first = import_accepted_candidates(tmp_path / 'campaign.json', [a, b], **common)
    second = import_accepted_candidates(tmp_path / 'campaign.json', [b, a], **common)
    assert sorted(calls[:2]) == sorted(calls[2:])
    assert [r['operation'] for r in first] == [r['operation'] for r in reversed(second)]
    for request_name, op_name in calls:
        digest = op_name.removeprefix('import-')
        assert request_name == f'request-{digest}.json' and len(digest) == 16


def test_evaluate_campaign_url_state_publishes_only_after_invariants(tmp_path: Path, monkeypatch):
    """R2-F5: url_state.parquet is staged in work_dir and moved after invariants pass."""
    verdict = {'bad_rows': 1}

    def fake_run_job(root, eng, *, inputs, steps, outputs, queries):
        target = Path(outputs[0]['path'])
        assert target.is_relative_to(Path(root))
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist([{'requested_url': 'https://example.gov/a'}]), target)
        return {'url_state_invariants': [dict(verdict)]}

    monkeypatch.setattr(pipeline_module, 'run_job', fake_run_job)
    out = tmp_path / 'release'
    with pytest.raises(ValueError, match='URL state invariants failed'):
        evaluate_campaign_url_state(tmp_path / 'work', engine=None, inputs=[], output_dir=out)
    assert not (out / 'url_state.parquet').exists()
    assert (tmp_path / 'work/staged-outputs/url_state.parquet').exists()

    verdict['bad_rows'] = 0
    result = evaluate_campaign_url_state(tmp_path / 'work', engine=None, inputs=[], output_dir=out)
    assert result['url_state_parquet'] == out / 'url_state.parquet'
    assert pq.read_table(out / 'url_state.parquet').num_rows == 1
    assert not (tmp_path / 'work/staged-outputs/url_state.parquet').exists()


def test_reconcile_and_import_retained_reuses_matching_stage(tmp_path: Path):
    """R2-F8: a rerun reuses a sealed stage with the same pinned inputs and decision."""
    sha = '9' * 64
    url = 'https://democrats-science.house.gov/download/rerun-doc&download=1'
    rec = 'https://democrats-science.house.gov/download/rerun-doc?download=1'
    accepted = tmp_path / 'accepted.json'
    accepted.write_text(json.dumps({'version': 1, 'recoveries': [{
        'original_url': url, 'recovered_url': rec, 'body_key': f'bodies/sha256/{sha[:2]}/{sha}.gz',
        'kind': 'pdf', 'recovery_status': 'recovered', 'recovery_basis': 'verified_archive_capture'}]}))
    captures = tmp_path / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist([{
        'sha256': sha, 'mode': 'fetch', 'original_url': None, 'recovered_url': None, 'match_basis': None,
        'recovery_category': None, 'url': rec, 'retrieved_at': '2023-03-15T14:00:00Z',
        'receipt_key': 'receipts/r1.jsonl.gz', 'receipt_line': 1, 'capture_index': 0, 'bytes': 1024,
        'media_type': 'application/pdf', 'stored_suffix': '.gz'}]), captures)
    registry = ROOT / 'model/registries/recovery-kinds.json'
    stage = tmp_path / 'stage'
    args = dict(output_dir=stage, decided_at=STAMP, decided_by='rerun-test', ready_only=True)
    with engine() as eng:
        first = reconcile_and_import_retained(accepted, captures, registry, engine=eng, **args)
        second = reconcile_and_import_retained(accepted, captures, registry, engine=eng, **args)
        assert second['provenance'] == first['provenance'] and second['inputs'] == first['inputs']
        with pytest.raises(ValueError, match='different decision'):
            reconcile_and_import_retained(accepted, captures, registry, engine=eng,
                                          **{**args, 'decided_by': 'someone-else'})
        accepted.write_text(accepted.read_text() + '\n')
        with pytest.raises(ValueError, match='different inputs'):
            reconcile_and_import_retained(accepted, captures, registry, engine=eng, **args)


def test_scan_receipt_history_preserves_raw_url_for_redirected_soft_404():
    """R3-F1: matching a row via requested_url must not hide a redirected soft-404 url."""
    clean = 'https://www.finance.senate.gov/hearings/clean-hearing'
    soft_404 = 'https://www.finance.senate.gov/404?notfound=hearings/clean-hearing'
    row = dict(
        url=soft_404,
        requested_url=clean,
        body_key='bodies/soft404',
        outcome='stored',
        http_status=200,
        media_type='text/html',
        receipt_key='receipts/r1.jsonl.gz',
        receipt_line=1,
        complete=True,
    )
    history = scan_receipt_history(fetch_outcomes=[row], urls=[clean])
    assert history[clean]['usable_attempt'] is None
    assert not _is_usable_direct_row(history[clean]['latest_state'], clean)


def test_fragmented_target_probes_archive_and_narrow_repairs_normalize_utf8():
    """R3-F3, R3-F4, R3-F5: fragmented targets probe archive without #fragment; senate-notfound normalizes UTF-8."""
    senate_utf8 = 'https://www.judiciary.senate.gov/404?notfound=%2fdownload%2fcaf%C3%A9%20doc.pdf'
    assert narrow_address_repairs(senate_utf8) == [(
        'https://www.judiciary.senate.gov/download/caf%C3%A9%20doc.pdf',
        'senate_notfound_wrapper_repair',
    )]
    queried = []

    def wayback(kind, url):
        queried.append(url)
        return Response(200, b'[]', True, f'ev:{len(queried)}', 'application/json', url)

    frag_target = 'https://docs.house.gov/meetings/IF/IF00/20230315/115400/HHRG-118-IF00-WState-1.pdf#page=2'
    discover_target_candidates([frag_target], wayback_call=wayback, max_pages=1)
    assert len(queried) == 1
    assert 'HHRG-118-IF00-WState-1.pdf' in queried[0] and '#page=2' not in queried[0]

