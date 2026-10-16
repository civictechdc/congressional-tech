"""Read pinned local candidate bundles and recheck selection against the baseline."""
from collections import Counter, defaultdict
import json
from pathlib import Path

from .document_index import validate_document_indexes
from .document_review_catalog import selected_groups, implementation
from .document_review_receipts import verified
from .document_reviews import apply_review_candidate, _without_null_fields


def select_document(document, sources, candidates=None):
    """Omitting a bundle withdraws its selection; every use rechecks full scope."""
    candidate = (candidates or {}).get(document['document_id'])
    if candidate is None:
        return apply_review_candidate(document,sources)
    result = apply_review_candidate(document,sources,candidate['review'])
    if (result['status'] not in {'candidate_applied','annotation_only_unsupported_forms'}
            or _without_null_fields(result) != _without_null_fields(candidate)):
        raise ValueError('Saved candidate does not match the current baseline and review')
    return result


def load_bundle(summary_path, summary_sha256, sources, documents):
    """Verify the complete local evidence and return candidates for an exact pair."""
    return _load_bundle(summary_path,summary_sha256,sources,documents,resolve=Path)


def _policy_identity(policy):
    """Compare the same module bytes after installation at a different path."""
    hashes = policy['source_sha256']
    modules = {Path(path).name:digest for path,digest in hashes.items()}
    if len(modules) != len(hashes):
        raise ValueError('Ambiguous review implementation module names')
    return dict(policy,source_sha256=modules)


def _load_bundle(summary_path, summary_sha256, sources, documents, *, resolve, portable=False):
    """Shared verification; portable callers must supply a pinned, closed resolver."""
    bindings = {}
    candidate_locator = Path(summary_path).parent/'candidates.jsonl'
    summary = json.loads(verified(resolve(summary_path),summary_sha256,bindings).read_text())
    if type(summary.get('bundle_version')) is not int or summary['bundle_version'] != 2:
        raise ValueError('Unsupported review bundle version')
    if (any(summary.get(f) is not False for f in ['production_selected','independent_reference','release_approved'])
            or summary.get('baseline_files_unchanged') is not True
            or summary.get('withdrawal_restores_baseline') is not True):
        raise ValueError('Require an unapproved candidate bundle with an intact baseline')
    if set(summary['baseline']) != {'sources','documents'}:
        raise ValueError('Review bundle must identify both baseline files')
    for name,path in [('sources',sources),('documents',documents)]:
        bound = summary['baseline'][name]
        baseline_path = resolve(bound['path']) if portable else Path(bound['path'])
        if baseline_path.resolve() != Path(path).resolve() or summary['bindings'].get(bound['path']) != bound['sha256']:
            raise ValueError('Review bundle belongs to a different baseline pair')
        verified(path,bound['sha256'],bindings)
    policy = _policy_identity if portable else lambda value:value
    if policy(summary['implementation']) != policy(implementation()):
        raise ValueError('Review implementation differs from the admitted bundle')
    for path,digest in summary['bindings'].items(): verified(resolve(path),digest,bindings)
    if set(summary['outputs']) != {'candidates.jsonl'}:
        raise ValueError('Unexpected candidate bundle outputs')
    candidate_path = verified(resolve(candidate_locator),summary['outputs']['candidates.jsonl'],bindings)
    rows = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    candidates = {row['document']['document_id']:row for row in rows}
    if (not candidates or len(candidates) != len(rows) or type(summary['reviewed_groups']) is not int
            or len(candidates) != summary['reviewed_groups']):
        raise ValueError('Missing or duplicate candidate identities')
    receipts = {}
    for candidate in rows:
        review = candidate['review']
        path = review['receipt']
        if summary['bindings'].get(path) != review['receipt_sha256']:
            raise ValueError('Packet observation receipt is not bound by admission')
        if path not in receipts:
            records = json.loads(resolve(path).read_text())['records']
            receipts[path] = {r['document_id']:r for r in records}
            if len(receipts[path]) != len(records):
                raise ValueError('Duplicate packet observation in receipt')
        observed = receipts[path].get(review['document_id'])
        if (observed is None or review.get('body_observation') != observed
                or review['body_key'] != observed['body_key']
                or review['body_sha256'] != observed['sha256']
                or set(review['observed_forms']) != set(observed['observed_document_forms'])):
            raise ValueError('Packet observation differs from the verified receipt')
    validate_document_indexes(sources,documents)
    source_rows = selected_groups(sources,set(candidates),'source_id')
    docs = selected_groups(documents,set(candidates),'document_id')
    members = defaultdict(list)
    for row in source_rows.values(): members[row['document_id']].append(row)
    if set(docs) != set(candidates) or set(members) != set(candidates) or len(source_rows) != summary['source_rows']:
        raise ValueError('Candidate coverage differs from the current baseline')
    validated = {key:select_document(docs[key],members[key],candidates) for key in sorted(candidates)}
    if dict(Counter(row['status'] for row in validated.values())) != summary['case_status']:
        raise ValueError('Candidate status counts differ from the summary')
    for path,digest in bindings.items(): verified(path,digest,{})
    if policy(summary['implementation']) != policy(implementation()):
        raise ValueError('Review implementation changed during bundle verification')
    return validated
