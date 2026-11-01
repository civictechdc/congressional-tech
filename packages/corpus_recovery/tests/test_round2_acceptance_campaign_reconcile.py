"""Round 2 fixes: fail-closed PDF bill identity, url_state planning and idempotent stage imports."""
from hashlib import sha256
import io
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import file_pin
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_shared.custody import verify_local_file
from corpus_recovery.acceptance import (
    BODY_BILL_CONFLICT, BODY_BILL_UNVERIFIED, _corroborate_pdf_bill_identifier, _extract_expected_bill,
    bill_text_disagreement, decide, page_bill_identifiers,
)
from corpus_recovery.campaign import plan
from corpus_recovery.reconcile import import_reconciled_stage, reconcile
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).resolve().parents[3]
STAMP = '2026-10-31T12:00:00Z'
WRITER = dict(job='round2-test', commit='a' * 40, lockfile_digest='b' * 64)
HR4824_PDF = ROOT / 'docs/experiments/url-normalization-validation-20261031/evidence/accepted-hr4824.pdf'


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def gpo_page(heading, *, margin_lines=0, stamp=None):
    """Synthetic pypdf-shaped GPO page text: heading, numbered body lines, job footer and stamp."""
    body = ''.join(f'line of statutory text {n}\n' for n in range(1, margin_lines + 1))
    footer = 'VerDate Nov 24 2008 13:56 Jul 19, 2023 Jkt 000000 PO 00000 Frm 00001\n'
    footer += 'g:\\V\\F\\071923\\F071923.032.xml           (892898|2)'
    return f'118TH CONGRESS \n{heading}\nTo support research.\n{body}{footer}' + (f'\n{stamp}' if stamp else '')


# --- R2-F4: pure text analysis -------------------------------------------------

def test_real_gpo_layout_reads_footer_stamp_not_margin_numbers():
    text = gpo_page('1ST SESSION H. R. ', margin_lines=25, stamp='4755')
    assert page_bill_identifiers(text) == {('hr', '4755')}
    # H.R. 12 is one of the margin numbers but the stamp names another bill.
    assert bill_text_disagreement(('hr', '12'), text) == BODY_BILL_CONFLICT


def test_small_bill_number_with_many_margin_lines_is_corroborated():
    stamped = gpo_page('1ST SESSION H. R. ', margin_lines=12, stamp='3')
    inline = gpo_page('1ST SESSION H. R. 3', margin_lines=12)
    for text in (stamped, inline):
        assert page_bill_identifiers(text) == {('hr', '3')}
        assert bill_text_disagreement(('hr', '3'), text) is None


def test_cross_chamber_heading_is_a_conflict():
    text = gpo_page('2D SESSION S. 4755', margin_lines=10)
    assert page_bill_identifiers(text) == {('s', '4755')}
    assert bill_text_disagreement(('hr', '4824'), text) == BODY_BILL_CONFLICT
    assert bill_text_disagreement(('hr', '4824'), 'H.R. 4824 as reported; compare S. 4755') == BODY_BILL_CONFLICT


@pytest.mark.parametrize('text', ['', '   \n', 'Image-only scan with no heading text'])
def test_empty_or_heading_free_text_is_unverified(text):
    assert bill_text_disagreement(('hr', '4824'), text) == BODY_BILL_UNVERIFIED


def test_session_heading_without_stamp_is_unverified():
    text = gpo_page('1ST SESSION H. R. ', margin_lines=25)
    assert page_bill_identifiers(text) == set()
    assert bill_text_disagreement(('hr', '12'), text) == BODY_BILL_UNVERIFIED


def test_us_code_and_possessives_are_not_senate_bills():
    text = 'Section 101 of title 42, U.S. 2023 and U. S. 2024; the Member\'s 12 amendments. H.R. 2023 follows.'
    assert page_bill_identifiers(text) == {('hr', '2023')}
    assert bill_text_disagreement(('hr', '2023'), text) is None


@pytest.mark.parametrize('target,expected', [
    (dict(identifiers=dict(bill='BILLS-118hr4824ih')), ('hr', '4824')),
    (dict(identifiers=dict(document='BILLS-118-hr-4824.pdf')), ('hr', '4824')),
    (dict(identifiers=dict(package='BILLS-118sres12is')), ('sres', '12')),
    (dict(identifiers=dict(bill='HR-4824')), ('hr', '4824')),
    (dict(url='https://www.govinfo.gov/content/pkg/BILLS-118s4755is/pdf/BILLS-118s4755is.pdf'), ('s', '4755')),
    (dict(url='https://democrats-science.house.gov/download/hr-4824?download=1'), ('hr', '4824')),
    # Non-GPO document IDs never become bill numbers.
    (dict(identifiers=dict(document='HHRG-118-SY00-Wstate-S0001'), url='https://docs.house.gov/x.pdf'), None),
    (dict(identifiers=dict(document='D-7'), url='https://docs.house.gov/missing.html'), None),
])
def test_expected_bill_from_bill_document_package_and_url(target, expected):
    assert _extract_expected_bill(target) == expected


# --- R2-F4: custody-bound body reads --------------------------------------------

def blank_pdf(path):
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = io.BytesIO()
    writer.write(stream)
    path.write_bytes(stream.getvalue())
    return verify_local_file(path)


def test_body_corroboration_fails_closed_and_leaves_html_and_billless_targets_alone(tmp_path):
    target = dict(url='https://democrats-science.house.gov/download/hr-4824?download=1', identifiers={})
    blank = blank_pdf(tmp_path / 'blank.pdf')
    assert _corroborate_pdf_bill_identifier(blank, target, media_type='application/pdf') == BODY_BILL_UNVERIFIED
    assert _corroborate_pdf_bill_identifier(blank, target, media_type='text/html') is None
    assert _corroborate_pdf_bill_identifier(blank, dict(url='https://docs.house.gov/a.pdf', identifiers={}),
                                            media_type='application/pdf') is None
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(b'%PDF-1.7\nnot a PDF object structure\n%%EOF\n')
    assert _corroborate_pdf_bill_identifier(verify_local_file(broken), target,
                                            media_type='application/pdf') == BODY_BILL_UNVERIFIED


@pytest.mark.skipif(not HR4824_PDF.is_file(), reason='accepted-hr4824.pdf evidence not present')
def test_body_changed_after_verification_is_unverified(tmp_path):
    copy = tmp_path / 'hr.pdf'
    copy.write_bytes(HR4824_PDF.read_bytes())
    verified = verify_local_file(copy)
    target = dict(url='https://democrats-science.house.gov/download/hr-4755?download=1', identifiers={})
    assert _corroborate_pdf_bill_identifier(verified, target, media_type='application/pdf') is None
    raw = bytearray(copy.read_bytes()); raw[-10] ^= 1; copy.write_bytes(bytes(raw))
    assert _corroborate_pdf_bill_identifier(verified, target, media_type='application/pdf') == BODY_BILL_UNVERIFIED


@pytest.mark.skipif(not HR4824_PDF.is_file(), reason='accepted-hr4824.pdf evidence not present')
@pytest.mark.parametrize('bill,status,reason', [
    ('HR-4824', 'review_required', BODY_BILL_CONFLICT),
    ('HR-4755', 'accepted', 'source_identifiers_match'),
    ('S-4755', 'review_required', BODY_BILL_CONFLICT),
])
def test_decide_on_real_hr4824_pdf(tmp_path, bill, status, reason):
    from corpus_recovery.qualification import qualify
    verified = verify_local_file(HR4824_PDF)
    qualification = dict(qualify(verified, tmp_path / 'qual-cache'))
    assert qualification['media_type'] == 'application/pdf'
    candidate_url = 'https://democrats-science.house.gov/download/hr-4824?download=1'
    receipt = dict(http_status=200, url=candidate_url, retrieved_at=STAMP, response_headers={}, captures=[
        dict(attempt=0, member_path=None, context_url=candidate_url, complete=True,
             sha256=verified.sha256, bytes=verified.size_bytes)])
    side = lambda url: dict(url=url, identifiers=dict(bill=bill, congress=118), required_fields=['bill', 'congress'])
    decision = decide(side('https://democrats-science.house.gov/download/hr-4824&download=1'), side(candidate_url),
                      requirement='historical_exact', relationship='recovered_document', body=verified,
                      qualification=qualification, receipt=receipt, receipt_sha256='c' * 64)
    assert (decision['status'], decision['reason']) == (status, reason)


# --- R2-F5: campaign planning over url_state.parquet ----------------------------

TARGET = 'https://docs.house.gov/missing.html'


def pinned(path):
    return dict(path=str(path.resolve()), sha256=file_pin(path)['sha256'])


@pytest.mark.parametrize('url_column', ['requested_url', 'url'])
def test_plan_accepts_url_state_requested_url_column(tmp_path, url_column):
    from congress_api.models.archive_profile import build_capture_profile
    targets, candidates = tmp_path / 'targets.parquet', tmp_path / 'candidates.parquet'
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET)]), targets)
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET, candidate_url=TARGET + '?v=2')]), candidates)
    state, requirements, profile = tmp_path / 'url_state.parquet', tmp_path / 'req.parquet', tmp_path / 'profile.json'
    pq.write_table(pa.Table.from_pylist([{url_column: TARGET, 'capture_disposition': 'satisfied',
                                          'capture_decision_id': 'decision-1', 'attempts': 1}]), state)
    pq.write_table(pa.Table.from_pylist([dict(original_url=TARGET, target_requirement='historical_exact',
        acceptance_policy='recovery-identity-v1', refresh_policy='historical_only')]), requirements)
    profile.write_text(json.dumps(build_capture_profile(engine_revision='a' * 40, url_normalized_sql='SELECT 1',
        url_keys_sql='SELECT 1', url_rules=[dict(id='rule', kind='strip', host_pattern=None, pattern='#.*$',
                                                 replacement=None, decoder=None)],
        recovery_policy=dict(acceptance_policy='recovery-identity-v1', requirements_sha256=file_pin(requirements)['sha256']))))
    descriptor = tmp_path / 'campaign.json'
    descriptor.write_text(json.dumps(dict(version=1, campaign_id='url-state', requirement='historical_exact',
        tables=dict(targets=pinned(targets), candidates=pinned(candidates), state=pinned(state),
                    state_requirements=pinned(requirements), state_profile=pinned(profile)),
        target_table='targets', candidate_table='candidates')))
    plan(descriptor, output=tmp_path / 'plan', engine=engine())
    [row] = pq.read_table(tmp_path / 'plan/url-dispositions.parquet').to_pylist()
    assert (row['disposition'], row['evidence_id']) == ('accepted_recovery', 'decision-1')


def test_plan_refuses_state_without_any_url_column(tmp_path):
    targets, candidates = tmp_path / 'targets.parquet', tmp_path / 'candidates.parquet'
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET)]), targets)
    pq.write_table(pa.Table.from_pylist([dict(target_url=TARGET, candidate_url=TARGET)]), candidates)
    state = tmp_path / 'state.parquet'
    pq.write_table(pa.Table.from_pylist([dict(address=TARGET, capture_disposition='eligible',
                                              capture_decision_id=None)]), state)
    descriptor = tmp_path / 'campaign.json'
    descriptor.write_text(json.dumps(dict(version=1, campaign_id='bad-state', requirement='historical_exact',
        tables=dict(targets=pinned(targets), candidates=pinned(candidates), state=pinned(state)),
        target_table='targets', candidate_table='candidates')))
    with pytest.raises(ValueError, match='capture eligibility'):
        plan(descriptor, output=tmp_path / 'plan', engine=engine())


# --- R2-F8: verified, idempotent reconciled-stage imports -----------------------

def staged_imports(tmp_path):
    """A reconciled stage with two ready imports whose bodies exist as local files."""
    bodies, recoveries, captures = {}, [], []
    for name in ('a', 'b'):
        data = f'<html><title>Recovered {name}</title></html>'.encode()
        digest = sha256(data).hexdigest()
        path = tmp_path / f'{name}.html'; path.write_bytes(data)
        bodies[digest] = path
        recovered = f'https://archive.example/{name}'
        recoveries.append(dict(original_url=f'https://docs.house.gov/{name}', recovered_url=recovered,
            body_key=f'bodies/sha256/{digest[:2]}/{digest}.gz', kind='html', recovery_status='recovered',
            recovery_basis='verified_archive_capture'))
        captures.append(dict(sha256=digest, mode='fetch', original_url=None, recovered_url=None, match_basis=None,
            recovery_category=None, url=recovered, retrieved_at='2019-01-01T00:00:00Z', receipt_key=f'receipts/{name}',
            receipt_line=1, capture_index=0, bytes=len(data), media_type='text/html', stored_suffix='.gz'))
    accepted = tmp_path / 'accepted.json'; accepted.write_text(json.dumps(dict(version=1, recoveries=recoveries)))
    capture_path = tmp_path / 'captures.parquet'; pq.write_table(pa.Table.from_pylist(captures), capture_path)
    result = reconcile(accepted, capture_path, ROOT / 'model/registries/recovery-kinds.json', output=tmp_path / 'stage',
                       engine=engine(), decided_at=STAMP, decided_by='round2-test')
    assert result['import_counts'] == dict(ready=2, unresolved=0)
    return tmp_path / 'stage', bodies


def receipts(raw):
    return sorted(p.relative_to(raw).as_posix() for p in (raw / 'receipts').rglob('*.gz')) if (raw / 'receipts').exists() else []


def test_retry_after_partial_failure_writes_no_duplicate_receipts(tmp_path):
    stage, bodies = staged_imports(tmp_path)
    raw = tmp_path / 'raw'; store = BodyStore(LocalAdapter(raw))
    first = ReceiptWriter(store, identity=WRITER, run_id='attempt-1', write_date='2026-10-31', archive_limits=None)

    class FailsSecondWrite:
        calls = 0
        def write(self, *args, **kwargs):
            FailsSecondWrite.calls += 1
            if FailsSecondWrite.calls == 2:
                raise RuntimeError('simulated crash after the first receipt')
            return first.write(*args, **kwargs)

    with pytest.raises(RuntimeError, match='simulated crash'):
        import_reconciled_stage(stage, writer=FailsSecondWrite(), imported_at=STAMP, body_paths_by_sha256=bodies)
    assert len(receipts(raw)) == 1
    retry = ReceiptWriter(store, identity=WRITER, run_id='attempt-2', write_date='2026-10-31', archive_limits=None)
    result = import_reconciled_stage(stage, writer=retry, imported_at='2026-11-01T00:00:00Z', body_paths_by_sha256=bodies)
    assert len(result['imported_receipts']) == 2
    assert len(receipts(raw)) == 2
    # The first row's receipt is the frozen attempt-1 receipt, not a new attempt-2 copy.
    assert sorted(r['receipt_key'] for r in result['imported_receipts']) == receipts(raw)
    assert sum('attempt-1-' in key for key in receipts(raw)) == 1
    again = import_reconciled_stage(stage, writer=retry, imported_at=STAMP, body_paths_by_sha256=bodies)
    assert [r['receipt_key'] for r in again['imported_receipts']] == [r['receipt_key'] for r in result['imported_receipts']]
    assert len(receipts(raw)) == 2


@pytest.mark.parametrize('corruption', ['content', 'missing'])
def test_corrupt_local_body_fails_before_any_receipt_write(tmp_path, corruption):
    stage, bodies = staged_imports(tmp_path)
    last = sorted(bodies)[-1]
    if corruption == 'content':
        bodies[last].write_bytes(b'<html>tampered</html>')
    else:
        bodies[last] = tmp_path / 'does-not-exist.html'

    class NoWrites:
        def write(self, *args, **kwargs):
            raise AssertionError('Receipt write reached before body verification')

    with pytest.raises((ValueError, OSError)):
        import_reconciled_stage(stage, writer=NoWrites(), imported_at=STAMP, body_paths_by_sha256=bodies)
    assert not (stage / 'frozen-receipts').exists()


def test_session_heading_extracts_all_resolution_types_with_gpo_footer():
    """R3-F5: GPO typeset session headings + footer stamps work for resolutions as well as bills."""
    for heading, expected in (
        ('1ST SESSION H. RES.\nVerDate Nov 24 2008 (99999|1)\n42', ('hres', '42')),
        ('2D SESSION S. J. RES.\nfoo.xml\n19', ('sjres', '19')),
        ('1ST SESSION H. CON. RES. 104', ('hconres', '104')),
        ('2D SESSION S. CON. RES.\n   77', ('sconres', '77')),
    ):
        assert page_bill_identifiers(heading) == {expected}

