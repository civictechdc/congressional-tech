"""Apply a verified, compiled body review to a fresh grouped baseline copy.

The caller verifies receipt bytes, complete page coverage, original evidence and
review eligibility before compiling this input. This module performs no I/O and
never approves release or independent reference status. Candidate documents must
not be used as baseline cache inputs; omit the review to withdraw its selection.
"""
from copy import deepcopy
from hashlib import sha256
import json

from house_naming.categories import document_families
from .document_index import nomination_support_context


# Existing forms admitted for review candidates. Descriptive financial/tax/rules labels
# stay in review annotations until their public representation is decided.
SUPPORTED_FORMS = frozenset({'amendment', 'biography', 'committee-memorandum',
    'committee-print', 'committee-vote', 'legislative-text', 'letter',
    'member-statement', 'opening-statement', 'press-release',
    'testimony-disclosure', 'witness-list', 'witness-statement'})
REVIEW_SOURCE = 'assistant_complete_body_review'


def _without_null_fields(value):
    """Ignore only Arrow dictionary padding; preserve list order and null items."""
    if isinstance(value, dict):
        return {key: _without_null_fields(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_null_fields(item) for item in value]
    return value


def review_group_digest(document, sources):
    """Bind all semantic group/member values, ignoring only Arrow null padding."""
    ids = [r['source_id'] for r in sources]
    if len(ids) != len(set(ids)) or any(r['document_id'] != document['document_id'] for r in sources):
        raise ValueError('Duplicate member or inconsistent document identity')
    if REVIEW_SOURCE in (document.get('document_kind_source') or []):
        raise ValueError('Require a baseline group, not a previous review candidate')
    payload = _without_null_fields(dict(document=document, sources=sorted(sources, key=lambda r: r['source_id'])))
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def apply_review_candidate(document, sources, review=None):
    """Select on a fresh baseline copy; omission withdraws a review without cache edits.

    Call the existing grouping/refresh paths first. Review candidates are separate
    JSON results and must never be supplied as baseline catalog/cache inputs.
    """
    digest = review_group_digest(document, sources)
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
            # A family can have both kind and publisher-context support. Restore
            # that independent basis using the maintained paired-link policy.
            if nomination_support_context(document):
                context_families.add('nomination-support')
            result['document_family'] = sorted(context_families | set(document_families(forms)))
            status = 'candidate_applied'
    return dict(status=status, baseline_group_sha256=digest, document=result,
                review=deepcopy(review), production_selected=False,
                independent_reference=False, release_approved=False)
