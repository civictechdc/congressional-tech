"""Check all native outputs before/after the metadata upgrade."""
import argparse
from collections import Counter
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    old_summary = json.loads((args.before / 'summary.json').read_text())
    new_summary = json.loads((args.after / 'summary.json').read_text())
    assert old_summary['literal_filenames_sha256'] == new_summary['literal_filenames_sha256']
    counts = Counter()
    gains = Counter()
    migrations = Counter()
    failures = []
    ambiguous = []
    # These are explicit, reviewed convention-to-record changes, not wildcard exemptions.
    kind_changes = {'conference-numbered': 'published-report'}
    with gzip.open(args.before / 'paired-outputs.jsonl.gz', 'rt') as before, gzip.open(args.after / 'paired-outputs.jsonl.gz', 'rt') as after:
        for left, right in zip_longest(before, after):
            assert left is not None and right is not None
            old, new = json.loads(left), json.loads(right)
            name = old['filename']
            assert name == new['filename'] == new['b']['input']
            counts['all_inputs'] += 1
            if old['a'] != new['a']:
                failures.append({'filename': name, 'failure': 'internal extractor changed'})
            else:
                counts['unchanged_internal_outputs'] += 1
            if new['errors']:
                failures.append({'filename': name, 'failure': new['errors']})
            if old['b']['valid']:
                if not new['b']['valid']:
                    failures.append({'filename': name, 'failure': 'lost acceptance'})
                    continue
                counts['old_acceptances_preserved'] += 1
                for match in old['b']['matches']:
                    expected = {**match['record'], 'kind': kind_changes.get(match['kind'], match['kind'])}
                    if not any(all(m['record'].get(k) == v for k, v in expected.items()) for m in new['b']['matches']):
                        failures.append({'filename': name, 'failure': 'lost metadata', 'before': match, 'after': new['b']})
                    else:
                        counts['old_records_fields_preserved'] += 1
                    if expected['kind'] != match['kind']:
                        migrations[f"{match['kind']} -> {expected['kind']}"] += 1
                        assert any(match['kind'] in m['matched_conventions'] for m in new['b']['matches'])
            elif new['b']['valid']:
                counts['new_acceptances'] += 1
                gains[' + '.join(sorted(m['kind'] for m in new['b']['matches']))] += 1
            if new['b']['ambiguous']:
                ambiguous.append({'filename': name, 'matches': new['b']['matches']})
    old_guide = json.loads((args.before / 'source/packages/house-naming/src/house_naming/data/guide.json').read_text())
    new_guide = json.loads((args.after / 'source/packages/house-naming/src/house_naming/data/guide.json').read_text())
    preserved = ['document', 'codes', 'code_index', 'source_nodes', 'sections', 'examples',
                 'example_index', 'committees', 'footnotes']
    for key in preserved:
        assert old_guide[key] == new_guide[key], ('source evidence changed', key)
    for kind, old_rule in old_guide['patterns'].items():
        for key in ('sources', 'conventions', 'source_example_ids', 'footnote_ids', 'title'):
            assert old_rule[key] == new_guide['patterns'][kind][key], (kind, key)
    drift = [name for name, value in new_summary['hashes'].items()
             if hashlib.sha256(Path(name).read_bytes()).hexdigest() != value]
    result = {'counts': counts, 'gains_by_kind': gains, 'kind_changes': migrations,
              'guide_evidence_preserved': preserved, 'failures': failures,
              'ambiguous_names': len(ambiguous), 'changed_since_run': drift}
    for filename, data in [('upgrade-regression.json', result), ('upgrade-ambiguities.json', ambiguous)]:
        (args.after / filename).write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'failures'}, indent=2))
    assert not failures, f'{len(failures)} regressions; see upgrade-regression.json'
    assert not drift, drift
    assert counts['all_inputs'] == old_summary['literal_filenames']
    assert counts['old_acceptances_preserved'] == old_summary['counts']['b_valid']


if __name__ == '__main__':
    main()
