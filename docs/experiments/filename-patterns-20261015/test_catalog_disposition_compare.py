"""The comparison must reject stale evidence and keep unavailable cases undecided."""
from copy import deepcopy
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from catalog_disposition_compare import COLUMNS, compare_case, selected_rows, run
from catalog_review_evidence import row_digest
from pilot_reconcile import file_digest
from test_catalog_content_review import fixture as review_fixture


def case():
    member = dict(source_id='source', document_id='document', body_key='body',
                  filename='Amendment.pdf', source_url='https://example.gov/Amendment.pdf')
    original = dict(document_id='document', filename='Amendment.pdf',
                    after_kind=['amendment'], members=[member], retained_body_keys=['body'])
    review = dict(receipt='review.json', receipt_sha256='receipt-digest',
                  source_row_sha256=row_digest(original), observation=dict(
                    body_key='body', sha256='body-digest', pages=1,
                    observed_document_forms=['committee-vote']))
    proposal = dict(document_id='document', source_row_sha256=row_digest(original),
                    proposed_primary_forms=['committee-vote'], proposed_component_forms=[],
                    status='assistant_proposal', handling='body_form',
                    evidence=dict(receipt='review.json', receipt_sha256='receipt-digest',
                                  body_key='body', sha256='body-digest', pages=1),
                    independent_reference=False, release_approved=False)
    document = dict(member, document_kind=['amendment'], filename_document_kind=['amendment'],
                    content_document_kind=None, document_kind_source=['filename'])
    return proposal, original, document, [member], review


def test_conflict_without_native_content_is_not_a_precedence_fix():
    inputs = case()
    before = deepcopy(inputs)
    result = compare_case(*inputs)
    assert result['label_comparison'] == 'different_labels'
    assert result['content_comparison'] == 'absent'
    assert result['selected_only_labels'] == ['amendment']
    assert result['review_only_forms'] == ['committee-vote']
    assert inputs == before


def test_matching_filename_does_not_supply_native_content_evidence():
    p, o, d, s, r = case()
    o['after_kind'] = d['document_kind'] = ['committee-vote']
    p['source_row_sha256'] = r['source_row_sha256'] = row_digest(o)
    result = compare_case(p, o, d, s, r)
    assert result['label_comparison'] == 'same_labels'
    assert result['content_comparison'] == 'absent'


def test_existing_native_reading_remains_separate():
    p, o, d, s, r = case()
    d['content_document_kind'] = ['committee-vote']
    result = compare_case(p, o, d, s, r)
    assert result['content_comparison'] == 'same_labels'
    assert result['label_comparison'] == 'different_labels'


def test_unavailable_empty_labels_are_not_agreement():
    p, o, d, s, _ = case()
    o['after_kind'] = d['document_kind'] = []
    p.update(source_row_sha256=row_digest(o), status='unresolved_no_body', evidence=None,
             proposed_primary_forms=[], handling='unresolved_no_body')
    result = compare_case(p, o, d, s, None)
    assert result['label_comparison'] == result['content_comparison'] == 'not_comparable_no_body'
    assert result['selected_only_labels'] is result['review_only_forms'] is None


@pytest.mark.parametrize('change', ['proposal_row', 'review_row', 'body', 'source', 'members',
                                    'forms', 'duplicate_form', 'selected_kind', 'approval'])
def test_changed_or_unsupported_evidence_is_rejected(change):
    p, o, d, s, r = case()
    if change == 'proposal_row': p['source_row_sha256'] = 'changed'
    elif change == 'review_row': r['source_row_sha256'] = 'changed'
    elif change == 'body': p['evidence']['body_key'] = 'other-body-at-same-url'
    elif change == 'source': s = [dict(s[0], body_key='other-body-at-same-url')]
    elif change == 'members': s = []
    elif change == 'forms': p['proposed_component_forms'] = ['letter']
    elif change == 'duplicate_form': p['proposed_component_forms'] = ['committee-vote']
    elif change == 'selected_kind': d['document_kind'] = ['statement']
    elif change == 'approval': p['release_approved'] = True
    with pytest.raises(ValueError):
        compare_case(p, o, d, s, r)


def test_projection_selects_only_requested_groups_and_rejects_duplicates(tmp_path):
    schema = pa.schema([(c, pa.list_(pa.string()) if c.endswith('_kind') or c == 'document_kind_source'
                        else pa.string()) for c in COLUMNS])
    _, _, doc, _, _ = case()
    other = dict(doc, source_id='other', document_id='unrelated')
    path = tmp_path / 'sources.parquet'
    pq.write_table(pa.Table.from_pylist([doc, other], schema=schema), path)
    assert set(selected_rows(path, {'document'}, 'source_id')) == {'source'}
    pq.write_table(pa.Table.from_pylist([doc, doc], schema=schema), path)
    with pytest.raises(ValueError, match='duplicate'):
        selected_rows(path, {'document'}, 'source_id')


@pytest.mark.parametrize('change', [None, 'duplicate_case', 'missing_case', 'catalog_bytes', 'render_bytes'])
def test_bound_comparison_integration(tmp_path, change):
    original, receipt, receipt_path, _, ledger = review_fixture(tmp_path)
    observed = receipt['records'][0]
    proposal = dict(document_id='d', source_row_sha256=row_digest(original),
                    proposed_primary_forms=['testimony-disclosure', 'biography'], proposed_component_forms=[],
                    status='assistant_proposal', handling='composite', independent_reference=False,
                    release_approved=False, evidence=dict(receipt=str(receipt_path),
                      receipt_sha256=file_digest(receipt_path), **{k: observed[k] for k in ['body_key', 'sha256', 'pages']}))
    spec = dict(records=[proposal], original_ledger=str(ledger), original_ledger_sha256=file_digest(ledger),
                receipt=str(receipt_path), receipt_sha256=file_digest(receipt_path),
                classification_mutations=False, independent_reference=False, release_approved=False)
    if change == 'duplicate_case': spec['records'].append(deepcopy(proposal))
    if change == 'missing_case': spec['records'] = []
    proposals = tmp_path / 'proposals.json'; proposals.write_text(json.dumps(spec))
    cp = tmp_path / 'checkpoint.json'
    cp.write_text(json.dumps(dict(inputs={str(ledger): file_digest(ledger)},
                                 outputs={str(proposals): file_digest(proposals)})))
    schema = pa.schema([(c, pa.list_(pa.string()) if c.endswith('_kind') or c == 'document_kind_source'
                        else pa.string()) for c in COLUMNS])
    source = dict(original['members'][0], document_kind=original['after_kind'],
                  document_kind_source=['filename'])
    source_path, doc_path = tmp_path / 'sources.parquet', tmp_path / 'documents.parquet'
    for path in [source_path, doc_path]:
        pq.write_table(pa.Table.from_pylist([source], schema=schema), path)
    summary = tmp_path / 'catalog-summary.json'
    summary.write_text(json.dumps(dict(outputs={'ledger.jsonl': file_digest(ledger)},
        bindings={str(p): file_digest(p) for p in [source_path, doc_path]})))
    if change == 'catalog_bytes':
        with source_path.open('ab') as stream: stream.write(b'changed')
    if change == 'render_bytes': (tmp_path / 'page-01-2.png').write_bytes(b'changed')
    output = tmp_path / 'comparison'
    if change:
        with pytest.raises(ValueError): run(proposals, cp, summary, source_path, doc_path, output)
        assert not output.exists()
    else:
        result = run(proposals, cp, summary, source_path, doc_path, output)
        assert result['records'] == result['source_rows'] == 1
        assert result['label_comparison'] == {'same_labels': 1}
        assert result['content_comparison'] == {'absent': 1}
        for name, digest in result['outputs'].items(): assert file_digest(output / name) == digest
        assert file_digest(ledger) == spec['original_ledger_sha256']
        with pytest.raises(FileExistsError): run(proposals, cp, summary, source_path, doc_path, output)
