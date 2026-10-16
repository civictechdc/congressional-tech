"""Complete packet candidates preserve evidence and withdraw on the same baseline."""
from copy import deepcopy

import pytest

from packet_review_candidate import REVIEW_SOURCE, apply_review, bind_review
from test_catalog_disposition_compare import case


def bound():
    proposal, original, document, sources, review = case()
    document['document_family'] = ['amendment', 'nomination-support']
    return document, sources, bind_review(proposal, original, document, sources, review)


def test_application_preserves_filename_and_content_evidence():
    document, sources, review = bound()
    originals = deepcopy((document, sources, review))
    result = apply_review(document, sources, review)
    assert result['status'] == 'candidate_applied'
    assert result['document']['document_kind'] == ['committee-vote']
    assert result['document']['document_kind_source'] == [REVIEW_SOURCE]
    assert result['document']['document_family'] == ['nomination-support', 'vote-record']
    for field, value in document.items():
        if field not in {'document_kind', 'document_kind_source', 'document_family'}:
            assert result['document'][field] == value
    assert (document, sources, review) == originals
    assert result['production_selected'] is result['independent_reference'] is False


def test_withdrawal_restores_baseline_and_previous_candidate_is_not_a_cache_input():
    document, sources, review = bound()
    selected = apply_review(document, sources, review)['document']
    assert apply_review(document, sources)['document'] == document
    with pytest.raises(ValueError, match='baseline group'):
        apply_review(selected, sources)


def test_corrected_receipt_replaces_the_candidate_without_changing_baseline():
    proposal, original, document, sources, review = case()
    first = bind_review(proposal, original, document, sources, review)
    proposal['proposed_primary_forms'] = review['observation']['observed_document_forms'] = ['letter']
    proposal['evidence']['receipt_sha256'] = review['receipt_sha256'] = 'corrected-receipt'
    correction = bind_review(proposal, original, document, sources, review)
    assert apply_review(document, sources, first)['document']['document_kind'] == ['committee-vote']
    assert apply_review(document, sources, correction)['document']['document_kind'] == ['letter']
    assert apply_review(document, sources)['document']['document_kind'] == ['amendment']


@pytest.mark.parametrize('change', ['body', 'context', 'member', 'filename', 'kind'])
def test_changed_group_does_not_inherit_previous_review(change):
    document, sources, review = bound()
    if change == 'body': sources[0]['body_key'] = 'new-body-at-same-url'
    elif change == 'context': sources[0]['source_document_type'] = ['new publisher claim']
    elif change == 'member': sources.append(dict(sources[0], source_id='alias'))
    elif change == 'filename': document['filename'] = 'new-name.pdf'
    elif change == 'kind': document['content_document_kind'] = ['letter']
    result = apply_review(document, sources, review)
    assert result['status'] == 'scope_changed'
    assert result['document'] == document


def test_member_order_and_arrow_null_padding_do_not_change_scope():
    proposal, original, document, sources, receipt = case()
    sources.append(dict(sources[0], source_id='alias'))
    original['members'] = deepcopy(sources)
    from catalog_review_evidence import row_digest
    proposal['source_row_sha256'] = receipt['source_row_sha256'] = row_digest(original)
    review = bind_review(proposal, original, document, sources, receipt)
    reordered = [dict(r, added_null=None) for r in reversed(sources)]
    assert apply_review(dict(document, added_null=None), reordered, review)['status'] == 'candidate_applied'


def test_unsupported_component_holds_whole_packet_without_losing_observation():
    proposal, original, document, sources, receipt = case()
    proposal['proposed_component_forms'] = ['tax-return']
    receipt['observation']['observed_document_forms'].append('tax-return')
    review = bind_review(proposal, original, document, sources, receipt)
    result = apply_review(document, sources, review)
    assert result['status'] == 'annotation_only_unsupported_forms'
    assert result['document'] == document
    assert result['review']['observed_forms'] == ['committee-vote', 'tax-return']


def test_unavailable_case_never_gains_a_binding():
    proposal, original, document, sources, _ = case()
    proposal.update(status='unresolved_no_body', evidence=None, proposed_primary_forms=[])
    assert bind_review(proposal, original, document, sources, None) is None


@pytest.mark.parametrize('change', ['release', 'reference', 'forms'])
def test_invalid_candidate_is_rejected(change):
    document, sources, review = bound()
    if change == 'release': review['release_approved'] = True
    elif change == 'reference': review['independent_reference'] = True
    elif change == 'forms': review['observed_forms'].append('letter')
    with pytest.raises(ValueError): apply_review(document, sources, review)


@pytest.mark.parametrize('context',['paired','split','untrusted','absent'])
def test_review_form_preserves_only_supported_overlapping_context_family(context):
    from congress_api.retention.document_index import fill_document_kind
    from catalog_review_evidence import row_digest
    proposal,original,document,sources,receipt=case()
    occurrence=dict(source_original_page_url=['https://www.judiciary.senate.gov/committee-activity/hearings/nominations'],
        source_page_title=['Nominations'],source_occurrence_scope=['anchor'],
        source_link_url=['https://www.judiciary.senate.gov/download/support'],source_link_label=['Group Support for Smith'])
    occurrences=[occurrence]
    if context=='split':
        occurrences=[dict(occurrence,source_link_label=['Attachment']),
            dict(occurrence,source_original_page_url=['https://example.gov/nominations'])]
    elif context=='untrusted':occurrence['source_association_basis']=['candidate_without_legacy_directory']
    elif context=='absent':occurrences=[]
    document.update(document_kind=['nomination-support'],filename_document_kind=['nomination-support'],
                    record_role=['document'],source_occurrences=occurrences)
    if context=='paired':
        document['document_kind']=document['filename_document_kind']=None
    fill_document_kind(document)
    assert document['document_family']==['nomination-support']
    original['after_kind']=['nomination-support']
    proposal['source_row_sha256']=receipt['source_row_sha256']=row_digest(original)
    review=bind_review(proposal,original,document,sources,receipt)
    before=deepcopy(document)
    result=apply_review(document,sources,review)
    assert result['document']['document_kind']==['committee-vote']
    assert result['document']['document_family']==(
        ['nomination-support','vote-record'] if context=='paired' else ['vote-record'])
    assert document==before and apply_review(document,sources)['document']==before
