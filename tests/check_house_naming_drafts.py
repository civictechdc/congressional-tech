"""Review every new draft/list record against independent retained native outputs."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('before', type=Path)
    ap.add_argument('after', type=Path)
    args = ap.parse_args()
    counts = Counter()
    alignments = defaultdict(Counter)
    disagreements = []
    gained = []
    mappings = {
        'stage': ['version_token'], 'draftLabel': ['draft_label'],
        'draftIdentifier': ['identifier_token'], 'numberPlaceholder': ['number_placeholder'],
        'measureType': ['measure_token'], 'measureNumber': ['measure_number'],
        'description': ['descriptor'], 'amendmentSuffix': ['amendment_token'],
    }
    before = gzip.open(args.before/'paired-outputs.jsonl.gz', 'rt')
    after = gzip.open(args.after/'paired-outputs.jsonl.gz', 'rt')
    with before, after:
        for left, right in zip_longest(before, after):
            assert left is not None and right is not None
            old, new = json.loads(left), json.loads(right)
            assert old['filename'] == new['filename']
            counts['all_inputs'] += 1
            if old['b']['valid'] or not new['b']['valid']:
                continue
            name = new['filename']
            native = new['a']['matches']
            fields = [f for m in native for f in m['fields']]
            congress = {int(f['raw']) for f in fields if f['name'] == 'congress'}
            counts['new_names'] += 1
            for match in new['b']['matches']:
                record = match['record']
                assert congress == {record['congress']}, (name, congress, record)
                assert name[:9].upper() == f"BILLS-{record['congress']}", name
                counts['congress_checked'] += 1
                counts['kind:' + record['kind']] += 1
                if record['kind'] == 'bill-numbered-described':
                    number = re.fullmatch(r'([A-Za-z]*)([0-9]+)', record['numberedSubject'])
                    assert number
                    if not number[1]:
                        assert 'measureType' not in record and 'measureNumber' not in record
                if record['kind'] == 'bill-unnumbered':
                    assert 'measureNumber' not in record
                if record['kind'] == 'bill-named-draft':
                    assert 'measureNumber' not in record
                if record['kind'] == 'bill-measure-list':
                    assert 'measureType' not in record and 'measureNumber' not in record
                    refs = [r for r in record['references'] if r['sourceField'] == 'measureList']
                    assert ''.join(r['raw'] for r in refs) == record['measureList']
                for ref in record.get('references', []):
                    assert record[ref['sourceField']][ref['start']:ref['end']] == ref['raw']
                    counts['reference_spans_checked'] += 1
                for key, native_names in mappings.items():
                    if key not in record or record[key] == '':
                        continue
                    values = {f['raw'] for f in fields if f['name'] in native_names}
                    if key == 'measureNumber':
                        values = {str(int(v)) for v in values if v.isdigit()}
                    status = ('aligned' if str(record[key]).lower() in {v.lower() for v in values}
                              else 'different' if values else 'absent_from_internal')
                    alignments[match['kind']][key + ':' + status] += 1
                    if status == 'different':
                        disagreements.append({'filename': name, 'kind': match['kind'], 'field': key,
                                              'house_naming': record[key], 'internal_values': sorted(values)})
            gained.append({'filename': name, 'house_naming': new['b']['matches'],
                           'internal': native, 'field_comparisons': new['field_comparisons']})
    summary = json.loads((args.after/'summary.json').read_text())
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in summary['hashes'].items())
    assert counts['all_inputs'] == summary['literal_filenames']
    with gzip.open(args.after/'drafts-new-records.jsonl.gz', 'wt') as out:
        for row in gained:
            out.write(json.dumps(row) + '\n')
    report = {'counts': counts, 'alignments': alignments, 'disagreements': disagreements,
              'audit_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.after/'drafts-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
