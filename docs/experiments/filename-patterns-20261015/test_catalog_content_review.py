from copy import deepcopy
import json

from pypdf import PdfWriter
import pytest

from catalog_content_review import load_reviews, link_row, run
from pilot_reconcile import file_digest


def fixture(tmp_path):
    pdf = tmp_path/'saved.pdf'
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    digest = file_digest(pdf)
    body = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    row = dict(document_id='d', filename='disclosure.pdf', before_kind=['biography'],
               after_kind=['biography','testimony-disclosure'], review_basis='needs_review',
               content_review='not_performed', release_approved=False, retained_body_keys=[body],
               members=[dict(document_id='d', source_id='s', body_key=body, body_format=['pdf'],
                   media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved'],
                   response_body_complete=['true'], filename='disclosure.pdf',
                   filename_document_kind=['testimony-disclosure'])])
    ledger = tmp_path/'original.jsonl'; ledger.write_text(json.dumps(row)+'\n')
    fetched = dict(document_id='d', filename='disclosure.pdf', body_key=body, sha256=digest,
                   path=str(pdf), pages=2)
    fetched_path = tmp_path/'fetch.json'; fetched_path.write_text(json.dumps({'results':[fetched]}))
    renders = {}
    for n in [1,2]:
        p = tmp_path/f'page-01-{n}.png'; p.write_bytes(b'test-render'+bytes([n])); renders[str(p)] = file_digest(p)
    record = dict(fetched, reviewer='assistant', all_pages_visually_reviewed=True,
                  observed_document_forms=['testimony-disclosure','biography'], rendered_pages=renders,
                  page_sections=[dict(first_page=1,last_page=1,observed_form='testimony-disclosure'),
                                 dict(first_page=2,last_page=2,observed_form='biography')],
                  source_completeness_observations=[dict(observation='Referenced attachment absent')],
                  independent_reference=False,release_approved=False)
    receipt = dict(input_ledger=str(ledger),input_ledger_sha256=file_digest(ledger),
                   fetch_results_path=str(fetched_path),fetch_results_sha256=file_digest(fetched_path),
                   records=[record],independent_reference=False,release_approved=False)
    path = tmp_path/'receipt.json'
    def save():
        path.write_text(json.dumps(receipt)); return file_digest(path)
    save()
    return row, receipt, path, save, ledger


def test_complete_composite_review_preserves_claims_and_source_limitations(tmp_path):
    row, _, path, save, _ = fixture(tmp_path)
    original = deepcopy(row)
    reviews = load_reviews(path, save(), {})
    linked = link_row(row, reviews)
    assert row == original
    assert linked['content_review'] == 'assistant_all_retained_pages_reviewed'
    for key in original:
        if key != 'content_review': assert linked[key] == original[key]
    observation = linked['content_reviews'][0]['observation']
    assert observation['observed_document_forms'] == ['testimony-disclosure','biography']
    assert observation['source_completeness_observations']
    assert observation['independent_reference'] is False and observation['release_approved'] is False


@pytest.mark.parametrize('change', ['body','membership','filename','kind','eligibility'])
def test_changed_current_evidence_does_not_inherit_review(tmp_path, change):
    row, _, path, save, _ = fixture(tmp_path)
    reviews = load_reviews(path, save(), {})
    if change == 'body': row['members'][0]['body_key'] = 'different'
    if change == 'membership': row['members'].append(dict(row['members'][0], source_id='s2'))
    if change == 'filename': row['members'][0]['filename'] = 'statement.pdf'
    if change == 'kind': row['after_kind'] = ['witness-statement']
    if change == 'eligibility': row['members'][0]['http_status'] = ['404']
    linked = link_row(row, reviews)
    assert linked['content_review'] == 'not_performed'
    assert not linked['content_reviews']
    assert linked['nonmatching_content_reviews'][0]['reason'] == 'complete_row_changed'


@pytest.mark.parametrize('change', ['partial','render','overlap','gap','count','digest','body_key','approval','reference','unknown_form'])
def test_invalid_or_incomplete_receipt_is_rejected(tmp_path, change):
    _, receipt, path, save, _ = fixture(tmp_path)
    record = receipt['records'][0]
    if change == 'partial': record['all_pages_visually_reviewed'] = False
    if change == 'render': record['rendered_pages'].pop(next(iter(record['rendered_pages'])))
    if change == 'overlap': record['page_sections'][0]['last_page'] = 2
    if change == 'gap': record['page_sections'].pop()
    if change == 'count': record['pages'] = 1
    if change == 'digest': record['sha256'] = '0'*64
    if change == 'body_key': record['body_key'] = 'other'
    if change == 'approval': record['release_approved'] = True
    if change == 'reference': record['independent_reference'] = True
    if change == 'unknown_form': record['page_sections'][0]['observed_form'] = 'letter'
    with pytest.raises(ValueError): load_reviews(path, save(), {})


def test_changed_saved_pdf_is_rejected(tmp_path):
    _, _, path, save, _ = fixture(tmp_path)
    (tmp_path/'saved.pdf').write_bytes(b'%PDF-changed')
    with pytest.raises(ValueError, match='digest mismatch'): load_reviews(path, save(), {})


def test_changed_render_is_rejected(tmp_path):
    _, _, path, save, _ = fixture(tmp_path)
    (tmp_path/'page-01-2.png').write_bytes(b'changed')
    with pytest.raises(ValueError, match='digest mismatch'): load_reviews(path, save(), {})


def test_conflicting_receipts_are_rejected(tmp_path):
    _, receipt, path, save, _ = fixture(tmp_path)
    prior = tmp_path/'prior.json'
    previous = deepcopy(receipt)
    previous['records'][0]['observed_document_forms'] = ['letter']
    prior.write_text(json.dumps(previous))
    receipt.update(previous_review=str(prior), previous_review_sha256=file_digest(prior))
    with pytest.raises(ValueError, match='Duplicate or conflicting'): load_reviews(path, save(), {})


def test_tampered_parent_receipt_is_rejected(tmp_path):
    _, receipt, path, save, _ = fixture(tmp_path)
    prior = tmp_path/'prior.json'; prior.write_text('{}')
    receipt.update(previous_review=str(prior), previous_review_sha256='0'*64)
    with pytest.raises(ValueError, match='digest mismatch'): load_reviews(path, save(), {})


def test_full_run_preserves_metadata_disposition_and_refuses_overwrite(tmp_path):
    _, _, path, save, ledger = fixture(tmp_path)
    before = ledger.read_bytes()
    result = run(ledger, path, save(), tmp_path/'output')
    assert result['linked_reviews'] == 1 and result['reviewed_pages'] == 2
    assert result['review_basis'] == {'needs_review':1}
    assert result['classification_mutations'] is False and result['release_approved'] is False
    assert before == ledger.read_bytes()
    assert file_digest(tmp_path/'output'/'ledger.jsonl') == result['outputs']['ledger.jsonl']
    with pytest.raises(FileExistsError): run(ledger, path, save(), tmp_path/'output')


def test_legacy_receipt_still_requires_explicit_record_reference_status(tmp_path):
    _, receipt, path, save, _ = fixture(tmp_path)
    del receipt['independent_reference']
    assert len(load_reviews(path, save(), {})) == 1
    del receipt['records'][0]['independent_reference']
    with pytest.raises(ValueError): load_reviews(path, save(), {})
