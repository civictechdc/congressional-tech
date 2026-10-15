"""Independently check a completed dry run against its frozen inputs."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path

from rule_review import DEFAULT_INPUT, ROOT, digest


def verify(source, output):
    stats = json.loads((output / 'verification.json').read_text())
    for name, expected in stats['input_sha256'].items():
        assert digest(source / name) == expected, name
    assert digest(Path(__file__).with_name('rule_review.py')) == stats['implementation_sha256']
    for name, expected in stats['source_reader_sha256'].items():
        assert digest(ROOT / name) == expected, name
    rules = {r['rule_id']: r for r in json.loads((output / 'rules.json').read_text())}
    counts = Counter()
    seen, candidates, conflicts, matched = set(), set(), set(), set()
    rule_counts = Counter()
    with gzip.open(output / 'document-review.jsonl.gz', 'rt') as f:
        for line in f:
            row = json.loads(line)
            doc = row['document_id']
            assert doc not in seen, doc
            seen.add(doc)
            counts[row['status']] += 1
            kinds = set(row['baseline_kinds']) | set(row['proposed_kinds']) | {e['kind'] for e in row['source_evidence']}
            if row['status'] not in {'reader_error', 'role_review'}:
                assert (len(kinds) > 1) == (row['status'] == 'conflict'), doc
            if row['status'] == 'proposed_corroborated':
                assert set(row['proposed_kinds']) == {e['kind'] for e in row['source_evidence']}, doc
            if row['status'] == 'role_review':
                assert not row['proposed_kinds'] and row['role_review'], doc
            if row['rule_ids']:
                matched.add(doc)
            for match in row['matches']:
                assert match['publishers'] and set(match['publishers']) <= set(rules[match['rule_id']]['publishers']), doc
                rule_counts[match['rule_id']] += 1
            if row['status'] not in {'role_review', 'unresolved'}:
                candidates.add(doc)
            if row['status'] == 'conflict':
                conflicts.add(doc)
    assert dict(counts) == stats['status_counts']
    assert len(seen) == stats['documents']
    assert len(matched) == stats['unique_rule_matched_documents']
    for name, expected in [('candidate-documents.csv', candidates), ('conflicts.csv', conflicts)]:
        with (output / name).open(newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(expected) and {r['document_id'] for r in rows} == expected, name
    for r in json.loads((output / 'rule-review.json').read_text()):
        assert rule_counts[r['rule_id']] == r['unique_document_count'], r['rule_id']
    names = [json.loads(line)['filename'] for line in (source / 'filename-records.jsonl').read_text().splitlines()]
    inventory = {}
    for filename in ['similarity-groups.json', 'templates.json', 'hdbscan-groups.json']:
        for group in json.loads((source / filename).read_text()):
            if group['method'] == 'template' and not group['descriptive']:
                continue
            inventory[(group['method'], group['group_id'])] = {names[i] for i in group['filename_indices']}
    samples = json.loads((output / 'group-review-samples.json').read_text())
    assert len(samples) == len(inventory) == stats['group_rows']
    checked = set()
    for group in samples:
        key = group['method'], group['group_id']
        assert key not in checked
        checked.add(key)
        picked = [s['filename'] for s in group['samples']]
        assert len(set(picked)) == len(picked) == min(3, len(inventory[key])), key
        assert set(picked) <= inventory[key], key
    assert checked == set(inventory)
    assert stats['classification_changes'] == 0 and stats['inputs_unchanged']
    print(json.dumps({'verified_documents': len(seen), 'verified_group_rows': len(checked),
                      'verified_candidates': len(candidates), 'verified_conflicts': len(conflicts),
                      'input_hashes_match': True}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.input, args.output)
