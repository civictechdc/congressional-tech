"""Link complete assistant PDF reviews to exact ledger rows without resolving kinds."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

from pypdf import PdfReader

from catalog_alias_review import eligible_body
from catalog_filename_replay import implementation_identity, implementation_manifest
from catalog_review_evidence import row_digest, verified
from pilot_reconcile import file_digest


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


def link_row(row, reviews):
    """Only content review status and annotations may change; filename claims stay intact."""
    if 'content_reviews' in row or 'nonmatching_content_reviews' in row or row['content_review'] != 'not_performed':
        raise ValueError('Expected an unlinked ledger row')
    result = deepcopy(row)
    result['content_reviews'] = []
    result['nonmatching_content_reviews'] = []
    review = reviews.get(row['document_id'])
    if review:
        if row_digest(row) != review['source_row_sha256']:
            result['nonmatching_content_reviews'].append(dict(receipt=review['receipt'],
                receipt_sha256=review['receipt_sha256'], reason='complete_row_changed'))
        else:
            result['content_reviews'].append(deepcopy(review))
            result['content_review'] = 'assistant_all_retained_pages_reviewed'
    return result


def run(ledger_path, receipt_path, receipt_sha256, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    bindings = {str(ledger_path): file_digest(ledger_path)}
    implementation = implementation_manifest()
    originals = read_ledger(ledger_path)
    reviews = load_reviews(receipt_path, receipt_sha256, bindings)
    rows = [link_row(row, reviews) for row in originals.values()]
    if any(file_digest(path) != digest for path, digest in bindings.items()):
        raise ValueError('Content evidence changed during linkage')
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during linkage')
    summary = dict(records=len(rows), content_review=dict(Counter(r['content_review'] for r in rows)),
        review_basis=dict(Counter(r['review_basis'] for r in rows)),
        linked_reviews=sum(bool(r['content_reviews']) for r in rows),
        nonmatching_reviews=sum(bool(r['nonmatching_content_reviews']) for r in rows),
        reviews_outside_current_ledger=sorted(set(reviews)-set(originals)),
        reviewed_pages=sum(r['content_reviews'][0]['observation']['pages'] for r in rows if r['content_reviews']),
        bindings=bindings, classification_mutations=False, independent_reference=False, release_approved=False,
        verification_scope='Saved evidence identity and review coverage; assistant observations are not independently validated')
    output.mkdir(parents=True)
    (output/'implementation.json').write_text(json.dumps(implementation, indent=2)+'\n')
    with (output/'ledger.jsonl').open('x') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
    summary['outputs'] = {name: file_digest(output/name) for name in ['ledger.jsonl', 'implementation.json']}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--receipt-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.ledger, args.receipt, args.receipt_sha256, args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in {'bindings', 'outputs'}}, indent=2))
