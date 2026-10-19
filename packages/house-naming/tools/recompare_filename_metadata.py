"""Compare current native metadata, retaining unresolved alignment explicitly."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from compare_filename_engines import FIELD_MAP, scalar, suffix_class
from compare_filename_metadata import digest, unique_fields

MAP = {**FIELD_MAP, 'subject': ('subject_token', 'appropriation_subject', 'descriptor', 'payload'),
       'stageOccurrence': ('version_number_token',), 'annotation': ('annotation',),
       'descriptionRemainder': ('descriptor',), 'versionSuffix': ('suffix',)}
CASE_CODES = {'publicationType'}
MARKERS = {'part': {'p', 'pt', 'part'}, 'volume': {'v', 'vol', 'volume'},
           'addendum': {'add', 'addendum'}, 'errata': {'err', 'errata'}}


def equal(a, b, key):
    if key in CASE_CODES:
        return str(a).casefold() == str(b).casefold()
    return scalar(a, b, key) == scalar(b, b, key)


def compare(row, record, fields):
    checks = []
    for key, expected in record.items():
        if key == 'kind':
            continue
        owners = MAP.get(key, ())
        observed = []
        for f in fields:
            if f['name'] not in owners:
                continue
            if key == 'stage' and f['name'] == 'version_token' and f['code'] is None:
                continue
            value = f['code'] if key == 'amendmentType' and f['code'] else f['raw']
            if value not in observed:
                observed.append(value)
        explanation = None
        if key in MARKERS and record['kind'].startswith('published-'):
            # Match each marker and its identifier from the SAME A match.
            observed = []
            for m in row['a']['matches']:
                fs = {f['name']: f['raw'] for f in m['fields']}
                marker = fs.get('publication_marker', fs.get('part_marker', '')).casefold()
                if marker in MARKERS[key]:
                    observed.append(fs.get('publication_identifier', fs.get('part_number', '')))
            owners = ('publication_marker+publication_identifier', 'part_marker+part_number')
        if key == 'witnessIdType':
            observed = ['bioguide'] if any(f['name'] == 'bioguide_token' and f['raw'] == record['witnessId']
                                         for f in fields) else []
            owners = ('bioguide_token in witnessId slot',)
        if key == 'documentType' and record['kind'] == 'published-report':
            observed = ['report'] if any(m['rule'] == 'published-report' for m in row['a']['matches']) else []
            owners = ('published-report rule',)
        if any(equal(v, expected, key) for v in observed):
            status = 'same_scalar'
        elif key == 'versionSuffix' and expected == '':
            status = 'empty_default'
        elif key == 'versionSuffix' and expected:
            suffix = ''.join(f['raw'] if f['name'] == 'version_number_token' else '(' + f['raw'] + ')'
                             for f in sorted(fields, key=lambda f: f['start'])
                             if f['name'] in {'version_number_token', 'annotation'})
            status = 'same_split_text' if suffix == expected else 'unresolved'
        elif key == 'description' and record['kind'] == 'appropriation-described':
            # B retains a larger routing description; A preserves it within payload.
            status = 'retained_in_A_text' if any(expected in f['raw'] for f in fields
                                                if f['name'] == 'payload') else 'unresolved'
        elif key == 'description' and record['kind'] == 'bill-preintroduced':
            status = 'retained_in_A_text' if any(f['name'] == 'suffix' and f['raw'] == '-' + expected
                                                for f in fields) else 'unresolved'
        elif key == 'part' and record['kind'] == 'conference-legislation-part':
            status = 'retained_in_A_text' if any(f['name'] == 'payload' and f['raw'].endswith('-' + expected)
                                                for f in fields) else 'unresolved'
        elif key == 'descriptionRemainder':
            status = 'retained_in_A_text' if any(f['name'] == 'descriptor' and f['raw'].endswith('-' + expected)
                                                for f in fields) else 'unresolved'
        else:
            status = 'unresolved' if owners else 'unmapped'
        checks.append({'field': key, 'B': expected, 'A': observed, 'status': status})
    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('previous_run', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    baseline = json.loads((args.run / 'summary.json').read_text())
    drift = [path for path, expected in baseline['hashes'].items()
             if not Path(path).exists() or digest(path) != expected]
    assert not drift, drift
    args.output.mkdir(parents=True, exist_ok=False)
    raw = args.run / 'paired-outputs.jsonl.gz'
    previous = args.previous_run / 'comparison.parquet'
    previous_rows = pq.read_table(previous).to_pylist()
    # Read the actual accepted column, not a reconstruction of old grammar.
    accepted_key = 'b_valid'
    old_names = {r['filename'] for r in previous_rows if r[accepted_key]}
    note = Path(__file__).with_name('filename-metadata-recomparison.md')
    dependencies = [raw, args.run / 'summary.json', previous, note, Path(__file__),
                    Path(__file__).with_name('compare_filename_metadata.py'),
                    Path(__file__).with_name('compare_filename_engines.py')]
    hashes = {str(p.resolve()): digest(p) for p in dependencies}
    for p in dependencies[3:]:
        shutil.copy2(p, args.output / p.name)
    counts = Counter()
    per_field = defaultdict(Counter)
    per_cohort = defaultdict(Counter)
    per_kind = defaultdict(Counter)
    flags = Counter()
    reverse = Counter()
    examples = defaultdict(list)
    a_examples = defaultdict(list)
    index = []
    rejected_rules = Counter()
    with gzip.open(raw, 'rt') as stream, gzip.open(args.output / 'differences.jsonl.gz', 'wt') as out:
        for line in stream:
            row = json.loads(line)
            assert not row['errors'], row['errors']
            counts['total'] += 1
            name = row['filename']
            fields = unique_fields(row['a'])
            ext = suffix_class(name)
            if not row['b']['valid']:
                counts['rejected'] += 1
                for rule in {m['rule'] for m in row['a']['matches']}:
                    rejected_rules[ext, rule] += 1
                index.append({'filename': name, 'cohort': 'rejected', 'kind': None, 'differences': []})
                continue
            assert len(row['b']['matches']) == 1
            record = row['b']['matches'][0]['record']
            kind = record['kind']
            cohort = 'previously_accepted' if name in old_names else 'newly_accepted'
            counts['accepted'] += 1
            per_cohort[cohort]['total'] += 1
            per_kind[kind]['total'] += 1
            checks = compare(row, record, fields)
            differences = [c for c in checks if c['status'] != 'same_scalar' and c['status'] != 'empty_default']
            unresolved = [c for c in checks if c['status'] in {'unresolved', 'unmapped'}]
            if not unresolved:
                counts['all_fields_aligned'] += 1
                per_cohort[cohort]['all_fields_aligned'] += 1
            else:
                counts['names_with_unresolved_fields'] += 1
                per_cohort[cohort]['names_with_unresolved_fields'] += 1
            for c in checks:
                per_field[c['field']][c['status']] += 1
            row_flags = set()
            for c in differences:
                flag = f"{kind}:{c['field']}:{c['status']}"
                row_flags.add(flag)
                per_kind[kind][f"{c['field']}:{c['status']}"] += 1
                per_cohort[cohort][flag] += 1
                if len(examples[flag]) < 5:
                    examples[flag].append({'filename': name, 'check': c, 'B': record, 'A': fields})
            # Reverse inventory: literal A values absent from all B scalar values.
            # This intentionally includes implicit markers and wrappers; it is a
            # review queue, not a declaration that these fields are useful/missing.
            b_values = [str(v).casefold() for k, v in record.items() if k != 'kind']
            unaligned = []
            for f in fields:
                if not f['raw']:
                    continue
                value = f['raw'].casefold()
                if value in b_values:
                    continue
                relation = 'within_B_text' if any(value in v for v in b_values) else 'not_in_B_scalar'
                entry = (kind, f['name'], relation)
                reverse[entry] += 1
                unaligned.append({**f, 'relation': relation})
                if len(a_examples[':'.join(entry)]) < 3:
                    a_examples[':'.join(entry)].append({'filename': name, 'field': f, 'B': record})
            flags.update(row_flags)
            if differences or unaligned:
                out.write(json.dumps({'filename': name, 'cohort': cohort, 'kind': kind, 'B': record,
                                      'checks': differences, 'A_other_fields': unaligned}) + '\n')
            index.append({'filename': name, 'cohort': cohort, 'kind': kind, 'differences': sorted(row_flags)})
    assert counts['total'] == baseline['literal_filenames']
    assert counts['accepted'] == baseline['counts']['b_valid']
    assert per_cohort['previously_accepted']['total'] == len(old_names)
    assert all(digest(p) == h for p, h in hashes.items())
    assert all(digest(p) == h for p, h in baseline['hashes'].items())
    pq.write_table(pa.Table.from_pylist(index), args.output / 'patterns.parquet', compression='zstd')
    summary = {'counts': counts, 'per_field': per_field, 'per_cohort': per_cohort, 'per_kind': per_kind,
               'flags': flags, 'hashes': hashes, 'current_source_hashes_verified': True,
               'reverse_inventory': [{'kind': k, 'field': f, 'relation': r, 'captures': n}
                                      for (k, f, r), n in sorted(reverse.items())],
               'rejected_rules': [{'extension_class': e, 'rule': r, 'filenames': n}
                                  for (e, r), n in sorted(rejected_rules.items())]}
    for name, data in [('summary.json', summary), ('examples.json', examples), ('A-extra-examples.json', a_examples)]:
        (args.output / name).write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps({'counts': counts, 'flags': flags, 'per_field': per_field}, indent=2))


if __name__ == '__main__':
    main()
