"""Local candidate selection from complete reviews; no production caller or defaults."""
from copy import deepcopy

from house_naming.categories import document_families

from catalog_disposition_compare import compare_case
from catalog_filename_replay import normalized
from catalog_review_evidence import row_digest


# Existing forms used in this experiment. Descriptive financial/tax/rules labels
# stay in review annotations until their public representation is decided.
SUPPORTED_FORMS = frozenset({'amendment', 'biography', 'committee-memorandum',
    'committee-print', 'committee-vote', 'legislative-text', 'letter',
    'member-statement', 'opening-statement', 'press-release',
    'testimony-disclosure', 'witness-list', 'witness-statement'})
REVIEW_SOURCE = 'assistant_complete_body_review'


def group_digest(document, sources):
    """Bind all semantic group/member values, ignoring only Arrow null padding."""
    ids = [r['source_id'] for r in sources]
    if len(ids) != len(set(ids)) or any(r['document_id'] != document['document_id'] for r in sources):
        raise ValueError('Duplicate member or inconsistent document identity')
    if REVIEW_SOURCE in (document.get('document_kind_source') or []):
        raise ValueError('Require a baseline group, not a previous review candidate')
    return row_digest(normalized(dict(document=document, sources=sorted(sources, key=lambda r: r['source_id']))))


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


def apply_review(document, sources, review=None):
    """Select on a fresh baseline copy; omission withdraws a review without cache edits.

    Call the existing grouping/refresh paths first. Review candidates are separate
    JSON results and must never be supplied as baseline catalog/cache inputs.
    """
    digest = group_digest(document, sources)
    result = deepcopy(document)
    status = 'no_review'
    if review is not None:
        forms = review['observed_forms']
        if (review.get('reviewer') != 'assistant'
                or review.get('independent_reference') is not False
                or review.get('release_approved') is not False
                or not forms or len(forms) != len(set(forms))
                or set(forms) != set(review['primary_forms'] + review['component_forms'])):
            raise ValueError('Invalid assistant review candidate')
        if review['document_id'] != document['document_id'] or review['group_sha256'] != digest:
            status = 'scope_changed'
        elif not set(forms) <= SUPPORTED_FORMS:
            status = 'annotation_only_unsupported_forms'
        else:
            result['document_kind'] = sorted(forms)
            result['document_kind_source'] = [REVIEW_SOURCE]
            # Preserve contextual navigation families already present on the
            # baseline; replace only those derived from its selected kinds.
            context_families = set(document.get('document_family') or []) - set(
                document_families(document.get('document_kind')))
            result['document_family'] = sorted(context_families | set(document_families(forms)))
            status = 'candidate_applied'
    return dict(status=status, baseline_group_sha256=digest, document=result,
                review=deepcopy(review), production_selected=False,
                independent_reference=False, release_approved=False)
