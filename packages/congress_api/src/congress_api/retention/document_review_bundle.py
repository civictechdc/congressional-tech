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
    bindings = {}
    summary_path = verified(summary_path,summary_sha256,bindings)
    summary = json.loads(summary_path.read_text())
    if type(summary.get('bundle_version')) is not int or summary['bundle_version'] != 1:
        raise ValueError('Unsupported review bundle version')
    if (any(summary.get(f) is not False for f in ['production_selected','independent_reference','release_approved'])
            or summary.get('baseline_files_unchanged') is not True
            or summary.get('withdrawal_restores_baseline') is not True):
        raise ValueError('Require an unapproved candidate bundle with an intact baseline')
    if set(summary['baseline']) != {'sources','documents'}:
        raise ValueError('Review bundle must identify both baseline files')
    for name,path in [('sources',sources),('documents',documents)]:
        bound = summary['baseline'][name]
        if Path(bound['path']).resolve() != Path(path).resolve() or summary['bindings'].get(bound['path']) != bound['sha256']:
            raise ValueError('Review bundle belongs to a different baseline pair')
        verified(path,bound['sha256'],bindings)
    if summary['implementation'] != implementation():
        raise ValueError('Review implementation differs from the admitted bundle')
    for path,digest in summary['bindings'].items(): verified(path,digest,bindings)
    if set(summary['outputs']) != {'candidates.jsonl'}:
        raise ValueError('Unexpected candidate bundle outputs')
    candidate_path = verified(summary_path.parent/'candidates.jsonl',summary['outputs']['candidates.jsonl'],bindings)
    rows = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    candidates = {row['document']['document_id']:row for row in rows}
    if (not candidates or len(candidates) != len(rows) or type(summary['reviewed_groups']) is not int
            or len(candidates) != summary['reviewed_groups']):
        raise ValueError('Missing or duplicate candidate identities')
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
    if summary['implementation'] != implementation():
        raise ValueError('Review implementation changed during bundle verification')
    return validated
