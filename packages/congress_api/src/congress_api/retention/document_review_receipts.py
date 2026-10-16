"""Verify local assistant review receipts and compile exact current group bindings.

Historical receipt paths are relative to the caller's working directory. This
reader validates retained evidence; it does not independently repeat the review.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from pypdf import PdfReader

from .document_index import document_body
from .document_reviews import review_group_digest


def file_digest(path):
    with Path(path).open('rb') as stream:
        digest = sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def row_digest(row):
    return sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verified(path, expected, bindings):
    path = Path(path)
    if file_digest(path) != expected:
        raise ValueError('Evidence digest mismatch: ' + str(path))
    bindings[str(path)] = expected
    return path


def eligible_body(row):
    return document_body(row.get('body_key'), row.get('media_type'), row.get('http_status'),
                         row.get('capture_outcome'), row.get('body_format'), row)


def read_ledger(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    if len({row['document_id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate ledger document ID')
    return {row['document_id']: row for row in rows}


def validate_record(record, original, fetched, bindings):
    """Verify coverage and saved evidence; this does not independently redo the review."""
    if (record.get('reviewer') != 'assistant'
            or record.get('all_pages_visually_reviewed') is not True
            or record.get('independent_reference') is not False
            or record.get('release_approved') is not False):
        raise ValueError('Require complete assistant review without reference or release approval')
    for field in ['document_id', 'body_key', 'sha256', 'path', 'pages', 'filename']:
        if record[field] != fetched[field]:
            raise ValueError('Review differs from fetched evidence: ' + field)
    digest = record['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Invalid decoded PDF digest')
    if record['body_key'] != f'bodies/sha256/{digest[:2]}/{digest}.gz':
        raise ValueError('Body key does not bind decoded PDF digest')
    keys = {key for member in original['members'] if (key := eligible_body(member))}
    if keys != {record['body_key']} or record['document_id'] != original['document_id']:
        raise ValueError('Review must bind the only eligible body of its original document')
    pages = record['pages']
    if type(pages) is not int or pages < 1:
        raise ValueError('Invalid page count')
    pdf = verified(record['path'], digest, bindings)
    if not pdf.read_bytes().startswith(b'%PDF-') or len(PdfReader(pdf).pages) != pages:
        raise ValueError('Saved PDF page count or signature mismatch')
    forms = record.get('observed_document_forms')
    if not forms or not all(isinstance(f, str) and f for f in forms) or len(set(forms)) != len(forms):
        raise ValueError('Require distinct observed forms')
    renders = record['rendered_pages']
    numbers = []
    for path, expected in renders.items():
        match = re.search(r'-(\d+)\.png$', str(path))
        if not match:
            raise ValueError('Render path lacks a page number')
        numbers.append(int(match[1]))
        verified(path, expected, bindings)
    if sorted(numbers) != list(range(1, pages + 1)):
        raise ValueError('Incomplete or duplicate rendered page coverage')
    if 'page_sections' in record:
        coverage = []
        for section in record['page_sections']:
            a, b = section['first_page'], section['last_page']
            if type(a) is not int or type(b) is not int or not 1 <= a <= b <= pages:
                raise ValueError('Invalid component page range')
            if not set(section['observed_form'].split('|')) <= set(forms):
                raise ValueError('Component form absent from observed forms')
            coverage.extend(range(a, b + 1))
        if coverage != list(range(1, pages + 1)):
            raise ValueError('Incomplete or overlapping component coverage')
    for path_key, hash_key in [('text_path', 'text_sha256'), ('native_text_path', 'native_text_sha256')]:
        if path_key in record:
            verified(record[path_key], record[hash_key], bindings)


def load_reviews(receipt_path, expected, bindings):
    reviews, seen_paths = {}, set()
    while True:
        path = verified(receipt_path, expected, bindings)
        if path.resolve() in seen_paths:
            raise ValueError('Cyclic receipt chain')
        seen_paths.add(path.resolve())
        receipt = json.loads(path.read_text())
        # The first receipt stores independent_reference on each record only.
        # Record validation always requires an explicit false value.
        if ('independent_reference' in receipt and receipt['independent_reference'] is not False
                or receipt.get('release_approved') is not False):
            raise ValueError('Assistant receipt cannot approve reference or release')
        originals = read_ledger(verified(receipt['input_ledger'], receipt['input_ledger_sha256'], bindings))
        fetched_path = verified(receipt['fetch_results_path'], receipt['fetch_results_sha256'], bindings)
        fetched_rows = json.loads(fetched_path.read_text())['results']
        fetched = {r['document_id']: r for r in fetched_rows}
        if len(fetched) != len(fetched_rows):
            raise ValueError('Duplicate fetched document ID')
        for bound, digest in receipt.get('selection_bindings', {}).items():
            verified(bound, digest, bindings)
        for record in receipt['records']:
            key = record['document_id']
            if key in reviews:
                raise ValueError('Duplicate or conflicting content review for document: ' + key)
            if key not in originals or key not in fetched:
                raise ValueError('Review document absent from bound evidence')
            validate_record(record, originals[key], fetched[key], bindings)
            reviews[key] = dict(receipt=str(path), receipt_sha256=expected,
                                source_row_sha256=row_digest(originals[key]), observation=deepcopy(record))
        if 'previous_review' not in receipt:
            return reviews
        receipt_path, expected = receipt['previous_review'], receipt['previous_review_sha256']


def compile_review(proposal, original, document, sources, review):
    """Compile only a validated receipt matching the original and current members."""
    key = document['document_id']
    if (proposal['document_id'] != key or original['document_id'] != key
            or proposal.get('status') != 'assistant_proposal'
            or any(proposal.get(f) is not False for f in ['independent_reference','release_approved'])
            or proposal['source_row_sha256'] != row_digest(original)
            or review['source_row_sha256'] != row_digest(original)):
        raise ValueError('Proposal does not bind the validated original review')
    if document.get('record_role') != ['document']:
        raise ValueError('Reviewed current group is not a document')
    if sorted(document.get('document_kind') or []) != original['after_kind']:
        raise ValueError('Current selected kinds differ from the original review row')
    expected = {row['source_id']:row for row in original['members']}
    actual = {row['source_id']:row for row in sources}
    if len(expected) != len(original['members']) or len(actual) != len(sources) or set(expected) != set(actual):
        raise ValueError('Current source membership differs from the original review')
    for sid,row in actual.items():
        if row['document_id'] != key or any(row.get(f) != expected[sid].get(f) for f in ['body_key','filename','source_url']):
            raise ValueError('Current source identity differs from the original review')
    observed = review['observation']
    if {b for row in sources if (b := eligible_body(row))} != {observed['body_key']}:
        raise ValueError('Current group no longer has exactly the reviewed eligible body')
    if set(document.get('body_keys') or []) != {row['body_key'] for row in sources if row.get('body_key')}:
        raise ValueError('Current group body union differs from source members')
    forms = proposal['proposed_primary_forms'] + proposal['proposed_component_forms']
    evidence = proposal.get('evidence') or {}
    if (len(forms) != len(set(forms)) or set(forms) != set(observed['observed_document_forms'])
            or any(evidence.get(f) != observed[f] for f in ['body_key','sha256','pages'])
            or any(evidence.get(f) != review[f] for f in ['receipt','receipt_sha256'])):
        raise ValueError('Proposed forms differ from the verified complete review')
    return dict(document_id=key,group_sha256=review_group_digest(document,sources),
        original_row_sha256=review['source_row_sha256'],receipt=review['receipt'],receipt_sha256=review['receipt_sha256'],
        body_key=observed['body_key'],body_sha256=observed['sha256'],observed_forms=sorted(observed['observed_document_forms']),
        primary_forms=list(proposal['proposed_primary_forms']),component_forms=list(proposal['proposed_component_forms']),
        reviewer='assistant',independent_reference=False,release_approved=False)
