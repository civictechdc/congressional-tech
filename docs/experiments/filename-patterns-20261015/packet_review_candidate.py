"""Compile experiment receipts for the maintained package review selector."""
from congress_api.retention.document_reviews import (
    REVIEW_SOURCE, SUPPORTED_FORMS,
    apply_review_candidate as apply_review,
    review_group_digest as group_digest,
)

from catalog_disposition_compare import compare_case


def bind_review(proposal, original, document, sources, review):
    """Compile only after full receipt validation by the caller and exact row comparison."""
    compare_case(proposal, original, document, sources, review)
    if review is None:
        return None
    observed = review['observation']
    return dict(document_id=document['document_id'], group_sha256=group_digest(document, sources),
                original_row_sha256=review['source_row_sha256'],
                receipt=review['receipt'], receipt_sha256=review['receipt_sha256'],
                body_key=observed['body_key'], body_sha256=observed['sha256'],
                observed_forms=sorted(observed['observed_document_forms']),
                primary_forms=list(proposal['proposed_primary_forms']),
                component_forms=list(proposal['proposed_component_forms']),
                reviewer='assistant', independent_reference=False, release_approved=False)
