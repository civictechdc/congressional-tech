"""Interactive document review form vocabulary and provenance verdict builder."""
import re

from .provenance import VERDICTS, validate_provenance


# Existing forms admitted for review candidates. Descriptive financial/tax/rules labels
# stay in review annotations until their public representation is decided.
SUPPORTED_FORMS = frozenset({'amendment', 'biography', 'committee-memorandum',
    'committee-print', 'committee-vote', 'legislative-text', 'letter',
    'member-statement', 'opening-statement', 'press-release',
    'testimony-disclosure', 'witness-list', 'witness-statement'})
REVIEW_SOURCE = 'assistant_complete_body_review'
_BODY_KEY_RE = re.compile(r'^bodies/sha256/([0-9a-f]{2})/([0-9a-f]{64})(?:\.(?:gz|pdf))?$')


def resolve_review_target(target):
    """Normalize a 16-hex link key, 64-hex SHA-256, raw body key, or original_url to a 16-hex target key."""
    if not isinstance(target, str):
        raise ValueError('Invalid review target')
    if re.fullmatch(r'[0-9a-f]{16}', target):
        return target
    if re.fullmatch(r'[0-9a-f]{64}', target):
        return target[:16]
    match = _BODY_KEY_RE.fullmatch(target)
    if match and match.group(1) == match.group(2)[:2]:
        return match.group(2)[:16]
    if target.startswith(('http://', 'https://', 'url:')):
        raw_url = target[4:] if target.startswith('url:') else target
        if not raw_url:
            raise ValueError('Invalid review target')
        return sha256(('url:' + raw_url).encode('utf-8')).hexdigest()[:16]
    raise ValueError('Invalid review target')


def build_review_verdict(form, *, default_decided_at=None, default_reviewer=None, require_supported_forms=False):
    """Convert an interactive review form submission into a schema-validated provenance record."""
    if not isinstance(form, dict):
        raise ValueError('Review form submission must be a mapping')
    raw_target = (
        form.get('target')
        or form.get('link_key')
        or form.get('body_key')
        or form.get('body_sha256')
        or form.get('sha256')
        or form.get('original_url')
    )
    target = resolve_review_target(raw_target)
    verdict = form.get('verdict')
    value = form.get('value')
    if verdict is None:
        forms = form.get('observed_forms') or form.get('observed_document_forms')
        if forms is None and ('primary_forms' in form or 'component_forms' in form):
            forms = list(form.get('primary_forms') or []) + list(form.get('component_forms') or [])
        if forms is not None:
            verdict = 'kind_override'
            value = list(forms)
    if verdict not in VERDICTS:
        raise ValueError('Invalid review target or verdict')
    if verdict == 'kind_override':
        if value is None:
            forms = form.get('observed_forms') or form.get('observed_document_forms') or (
                list(form.get('primary_forms') or []) + list(form.get('component_forms') or [])
            )
            value = list(forms) if forms is not None else None
        if (not isinstance(value, list) or not value
                or any(not isinstance(item, str) or not item for item in value)
                or len(set(value)) != len(value)):
            raise ValueError('Invalid review value')
        if require_supported_forms and not set(value) <= SUPPORTED_FORMS:
            raise ValueError('Unsupported document review form')
    elif verdict == 'duplicate_of' and isinstance(value, str):
        value = resolve_review_target(value)
    decided_at = form.get('decided_at') if form.get('decided_at') is not None else default_decided_at
    reviewer = form.get('reviewer') if form.get('reviewer') is not None else default_reviewer
    note = form.get('note') if 'note' in form else form.get('notes')
    record = dict(
        id=form.get('id'),
        target=target,
        verdict=verdict,
        value=value,
        note=note,
        reviewer=reviewer,
        decided_at=decided_at,
        supersedes=form.get('supersedes'),
    )
    return validate_provenance('reviews', record)

