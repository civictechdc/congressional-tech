"""Link bound historical review results to current aliases without approving content."""
import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

from catalog_alias_review import read_rows
from catalog_filename_replay import encode, implementation_identity, implementation_manifest
from pilot_reconcile import file_digest


def verified(path, expected, bindings):
    path = Path(path)
    if file_digest(path) != expected:
        raise ValueError('Evidence digest mismatch: ' + str(path))
    bindings[str(path)] = expected
    return path


FILENAME_DECISIONS = {'reviewed_explicit_disclosure_wording': True, 'unresolved_award_list': False}


def row_digest(row):
    return sha256(encode(row).encode()).hexdigest()


def load_filename_reviews(specs, bindings):
    """Bind reviewed decisions to complete original rows, not document IDs alone."""
    reviews = []
    names = set()
    for spec in specs:
        if spec['name'] in names:
            raise ValueError('Duplicate filename review name')
        names.add(spec['name'])
        checkpoint = json.loads(verified(spec['checkpoint'], spec['checkpoint_sha256'], bindings).read_text())
        verified(spec['review'], spec['review_sha256'], bindings)
        path = verified(checkpoint['input_ledger'], checkpoint['input_ledger_sha256'], bindings)
        originals = {}
        for line in path.read_text().splitlines():
            row = json.loads(line)
            key = row['document_id']
            if key in originals:
                raise ValueError('Duplicate filename review input ID')
            originals[key] = row
        decisions = {}
        for decision in checkpoint['decisions']:
            key = decision['document_id']
            if key in decisions:
                raise ValueError('Duplicate filename review decision ID')
            if key not in originals or row_digest(originals[key]) != decision['source_row_sha256']:
                raise ValueError('Filename decision does not bind its original row')
            if decision['filename_interpretation'] not in FILENAME_DECISIONS:
                raise ValueError('Unknown filename review decision')
            if decision.get('content_review') != 'not_performed' or decision.get('release_approved') is not False:
                raise ValueError('Filename review cannot approve content or release')
            decisions[key] = decision
        reviews.append((spec, decisions))
    return reviews


def apply_filename_reviews(row, reviews):
    # Compare before adding any new review fields; all receipts see the same row.
    digest = row_digest(row)
    row['filename_reviews'] = []
    row['nonmatching_filename_reviews'] = []
    supported = False
    for spec, decisions in reviews:
        decision = decisions.get(row['document_id'])
        if decision is None:
            continue
        if digest != decision['source_row_sha256']:
            row['nonmatching_filename_reviews'].append(dict(name=spec['name'], reason='complete_row_changed'))
            continue
        interpretation = decision['filename_interpretation']
        row['filename_reviews'].append(dict(name=spec['name'], review=spec['review'],
            checkpoint_sha256=spec['checkpoint_sha256'], interpretation=interpretation,
            scope='filename_interpretation_only'))
        supported |= FILENAME_DECISIONS[interpretation]
    if supported and row['review_basis'] == 'needs_review':
        row['review_basis'] = 'filename_interpretation_review'


def match_group(current, current_members, prior, prior_members):
    """Return mismatches; a shared ID alone cannot carry a review forward."""
    reasons = []
    for field in ['document_id', 'source_id']:
        if current.get(field) != prior.get(field):
            reasons.append(field + '_changed')
    for field in ['document_kind', 'document_kind_source', 'record_role', 'filenames',
                  'source_urls', 'body_keys', 'content_document_kind']:
        if set(current.get(field) or []) != set(prior.get(field) or []):
            reasons.append(field + '_changed')
    left = {r['source_id']: r for r in current_members}
    right = {r['source_id']: r for r in prior_members}
    if left.keys() != right.keys():
        reasons.append('source_membership_changed')
    else:
        for sid in sorted(left):
            for field in ['document_id', 'filename', 'source_url', 'body_key']:
                if left[sid].get(field) != right[sid].get(field):
                    reasons.append('member_' + field + '_changed')
            for field in ['document_kind', 'document_kind_source', 'record_role',
                          'content_document_kind', 'source_document_type', 'source_document_type_basis']:
                if set(left[sid].get(field) or []) != set(right[sid].get(field) or []):
                    reasons.append('member_' + field + '_changed')
    return sorted(set(reasons))


def load_tables(summary, bindings):
    tables = {}
    for name, key in [('filenames', 'source_id'), ('documents', 'document_id')]:
        entry = summary['output_files'][name]
        path = verified(entry['path'], entry['sha256'], bindings)
        tables[name] = read_rows(path, key)
        if len(tables[name]) != entry['rows']:
            raise ValueError('Receipt row count mismatch')
    groups = defaultdict(list)
    for row in tables['filenames'].values():
        groups[row['document_id']].append(row)
    if set(groups) != set(tables['documents']):
        raise ValueError('Receipt source/document membership mismatch')
    return tables['documents'], groups


def run(registry_path, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    bindings = {str(registry_path): file_digest(registry_path)}
    implementation = implementation_manifest()
    registry = json.loads(Path(registry_path).read_text())
    cp_path = verified(registry['alias_checkpoint'], registry['alias_checkpoint_sha256'], bindings)
    checkpoint = json.loads(cp_path.read_text())
    summary_path = verified(registry['alias_summary'], checkpoint['summary_sha256'], bindings)
    audit = json.loads(summary_path.read_text())
    ledger_path = verified(summary_path.parent / 'ledger.jsonl', audit['outputs']['ledger.jsonl'], bindings)
    ledger = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    if len(ledger) != audit['changed_kind_groups'] or len({r['document_id'] for r in ledger}) != len(ledger):
        raise ValueError('Alias ledger identities/count mismatch')
    current_summary = {'output_files': {
        name: dict(audit['inputs']['after_' + source], rows=audit[count])
        for name, source, count in [('filenames', 'sources', 'source_rows'), ('documents', 'documents', 'document_groups')]}}
    current, groups = load_tables(current_summary, bindings)
    receipts = []
    for spec in registry['receipts']:
        receipt_checkpoint = json.loads(verified(spec['checkpoint'], spec['checkpoint_sha256'], bindings).read_text())
        declared = (receipt_checkpoint.get('replay_summary_sha256')
                    if receipt_checkpoint.get('replay_summary_path') == spec['summary']
                    else receipt_checkpoint.get('artifacts', {}).get(spec['summary']))
        if declared != spec['summary_sha256']:
            raise ValueError('Checkpoint does not bind the selected replay summary')
        verified(spec['review'], spec['review_sha256'], bindings)
        path = verified(spec['summary'], spec['summary_sha256'], bindings)
        replay = json.loads(path.read_text())
        if not all(replay.get(key) is True for key in ['completed', 'input_bytes_unchanged', 'invariants_preserved']):
            raise ValueError('Receipt is not a completed preservation replay: ' + spec['name'])
        changes = verified(path.parent / 'documents-changes.csv',
                           replay['comparisons']['documents']['changes_sha256'], bindings)
        changed = {}
        for row in csv.DictReader(changes.open()):
            if row['change'] not in {'new_assignment', 'removed_assignment', 'changed_prior_kind'}:
                continue
            if row['id'] in changed:
                raise ValueError('Duplicate receipt change ID')
            changed[row['id']] = row
        documents, members = load_tables(replay, bindings)
        for key, row in changed.items():
            if key not in documents or set(json.loads(row['after_kind'])) != set(documents[key].get('document_kind') or []):
                raise ValueError('Receipt changed-kind row disagrees with its output table')
        receipts.append((spec, changed, documents, members))
    filename_reviews = load_filename_reviews(registry.get('filename_reviews', []), bindings)
    counts = Counter()
    for row in ledger:
        key = row['document_id']
        if key not in current or row['after_kind'] != sorted(current[key].get('document_kind') or []):
            raise ValueError('Alias ledger disagrees with current document kind')
        row['prior_reviews'] = []
        row['nonmatching_prior_reviews'] = []
        for spec, changed, documents, members in receipts:
            if key not in changed:
                continue
            reasons = match_group(current[key], groups[key], documents[key], members[key])
            if reasons:
                row['nonmatching_prior_reviews'].append(dict(name=spec['name'], reasons=reasons))
            else:
                row['prior_reviews'].append(dict(name=spec['name'], review=spec['review'],
                                                summary_sha256=spec['summary_sha256'],
                                                scope='historical_interpretation_only'))
                counts[spec['name']] += 1
        row['review_basis'] = (row['metadata_review'] if row['metadata_review'] != 'needs_review'
                               else 'prior_interpretation_review' if row['prior_reviews'] else 'needs_review')
        # Prior review notes never become independent content truth or approval.
        row['content_review'] = 'not_performed'
        row['release_approved'] = False
        apply_filename_reviews(row, filename_reviews)
    if any(file_digest(path) != digest for path, digest in bindings.items()):
        raise ValueError('Review evidence changed during linkage')
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during linkage')
    output.mkdir(parents=True)
    (output / 'implementation.json').write_text(json.dumps(implementation, indent=2) + '\n')
    with (output / 'ledger.jsonl').open('x') as stream:
        for row in ledger:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    buckets = defaultdict(list)
    for row in ledger:
        buckets[row['review_basis'], tuple(row['before_kind']), tuple(row['after_kind'])].append(row)
    with (output / 'groupings.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['review_basis', 'count', 'before', 'after', 'sample_1', 'sample_2', 'sample_3'])
        for (basis, before, after), rows in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0])):
            examples = [r['filename'] or '(unnamed)' for r in rows[:3]]
            writer.writerow([basis, len(rows), '|'.join(before), '|'.join(after), *examples, *[''] * (3-len(examples))])
    summary = dict(records=len(ledger), review_basis=dict(Counter(r['review_basis'] for r in ledger)),
                   matched_prior_reviews=dict(counts),
                   nonmatching_prior_reviews=sum(len(r['nonmatching_prior_reviews']) for r in ledger),
                   filename_review_decisions=dict(Counter(review['interpretation'] for r in ledger
                                                          for review in r['filename_reviews'])),
                   nonmatching_filename_reviews=sum(len(r['nonmatching_filename_reviews']) for r in ledger),
                   filename_reviews=[dict(name=spec['name'], decisions=len(decisions),
                       outside_current_changed_ledger=len(set(decisions)-{r['document_id'] for r in ledger}))
                       for spec, decisions in filename_reviews],
                   receipts=[dict(name=spec['name'], changed_groups=len(changed),
                                  outside_current_changed_ledger=len(set(changed)-{r['document_id'] for r in ledger}),
                                  outside_current_cohort=len(set(changed)-set(current)),
                                  current_unchanged_groups=len(set(changed)&(set(current)-{r['document_id'] for r in ledger})))
                             for spec, changed, _, _ in receipts],
                   bindings=bindings, implementation_sha256=file_digest(output / 'implementation.json'),
                   body_reads=False, classification_mutations=False, release_approved=False,
                   outputs={name:file_digest(output/name) for name in ['ledger.jsonl','groupings.csv']})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.registry, args.output), indent=2))
