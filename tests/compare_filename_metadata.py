"""Audit both directions of saved native filename outputs, without reparsing."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from compare_filename_engines import FIELD_MAP, scalar, suffix_class


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def unique_fields(parsed):
    """Keep overlapping claims, but combine identical fields across rules."""
    unique = {}
    for match in parsed['matches']:
        for field in match['fields']:
            key = (field['name'], field['raw'], field['start'], field['end'])
            unique.setdefault(key, {**field, 'rules': []})['rules'].append(match['rule'])
    return list(unique.values())


def inside(field, owners):
    return any(owner['start'] <= field['start'] and field['end'] <= owner['end']
               for owner in owners)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    baseline = json.loads((args.run / 'summary.json').read_text())
    drift = [path for path, expected in baseline['hashes'].items()
             if not Path(path).exists() or digest(path) != expected]
    if drift:
        raise RuntimeError(f'Saved comparison no longer describes current sources: {drift}')
    args.output.mkdir(parents=True, exist_ok=False)
    raw_path = args.run / 'paired-outputs.jsonl.gz'
    inputs = [raw_path, args.run / 'summary.json', Path(__file__),
              Path(__file__).with_name('filename-metadata-comparison.md')]
    hashes = {str(path.resolve()): digest(path) for path in inputs}
    counts = Counter()
    patterns = Counter()
    by_extension = defaultdict(Counter)
    by_kind = defaultdict(Counter)
    field_inventory = Counter()
    b_field_inventory = Counter()
    rejection_rules = Counter()
    examples = defaultdict(list)
    index = []
    with gzip.open(raw_path, 'rt') as stream:
        for line in stream:
            row = json.loads(line)
            assert not row['errors'], row['errors']
            name = row['filename']
            ext = suffix_class(name)
            accepted = row['b']['valid']
            counts['total'] += 1
            by_extension[ext]['total'] += 1
            fields = unique_fields(row['a'])
            grouped = defaultdict(list)
            for field in fields:
                grouped[field['name']].append(field)
            flags = set()
            rules = {match['rule'] for match in row['a']['matches']}
            kind = None
            record = None
            if accepted:
                assert len(row['b']['matches']) == 1
                record = row['b']['matches'][0]['record']
                kind = record['kind']
                counts['accepted'] += 1
                by_extension[ext]['accepted'] += 1
                by_kind[kind]['total'] += 1
                for key in record:
                    b_field_inventory[kind, key] += 1
                for field_name in grouped:
                    field_inventory[kind, field_name] += 1
                checks = row['field_comparisons'][0]['fields']
                if all(check['status'] == 'present' for check in checks):
                    counts['all_mapped_scalar_values_present'] += 1
                for check in checks:
                    if check['status'] != 'present':
                        flags.add(f"scalar_{check['status']}:{check['field']}")
                    if check.get('additional_values'):
                        flags.add(f"additional_A_values:{check['field']}")
                if kind == 'appropriation-described':
                    flags.add('A_separates_appropriation_description')
                if kind == 'bill-preintroduced':
                    flags.add('B_separates_preintroduced_description')
                if kind == 'conference-legislation-part':
                    flags.add('B_separates_conference_part')
                if kind == 'conference-numbered':
                    flags.add('B_conference_kind_from_generic_report_layout')
                if kind == 'published-hearing' and record['publicationSuffix']:
                    flags.add('B_retains_publication_suffix')
                    if grouped['publication_marker'] or grouped['part_marker']:
                        flags.add('A_separates_publication_suffix')
                if 'witnessId' in record and any(
                    f['raw'] == record['witnessId'] for f in grouped['bioguide_token']
                ):
                    flags.add('A_recognizes_witness_ID_Bioguide_shape')

                # These are span collisions, not assertions about document contents.
                for match in row['a']['matches']:
                    if match['rule'] == 'measure-reference' and inside(match, grouped['bioguide_token']):
                        flags.add('A_measure_inside_Bioguide')
                    if match['rule'] == 'measure-reference' and 'witnessId' in record:
                        if any(f['name'] == 'measure_number' and f['raw'] == record['meetingDate']
                               for f in match['fields']):
                            flags.add('A_measure_crosses_witness_and_date_slots')
                    if match['rule'] == 'revision-token' and inside(match, grouped['bioguide_token']):
                        # U849615 can also be a revision suffix. Check the B member slot.
                        token = name[match['start']:match['end']]
                        if token in {record.get('sponsorBioguideId'), record.get('memberBioguideId'), record.get('witnessId')}:
                            flags.add('A_revision_inside_person_ID')
                for f in grouped['bioguide_token']:
                    if any(m['rule'] == 'revision-token' and inside(f, [m])
                           and f['raw'].lower() == f"u{record.get('revision')}"
                           and f['end'] == row['a']['stem_end'] for m in row['a']['matches']):
                        flags.add('A_Bioguide_inside_terminal_revision')
                for f in grouped['short_date_token']:
                    flags.add('A_six_digit_date_candidate')
                    if inside(f, grouped['bioguide_token']):
                        flags.add('A_six_digit_date_inside_Bioguide_shape')
                    elif inside(f, grouped['document_number'] + grouped['document_identifier']):
                        flags.add('A_six_digit_date_inside_document_ID')
                    else:
                        flags.add('A_six_digit_date_other')
                for f in grouped['date_token']:
                    if f['raw'] in {record.get('meetingDate'), record.get('voteDate')}:
                        continue
                    owner = next((owner for owner in ('publication_number', 'document_number',
                                 'document_identifier', 'revision_number', 'measure_number',
                                 'amendment_identifier', 'amendment_token', 'subject_token')
                                  if inside(f, grouped[owner])), 'unassigned')
                    flags.add(f'A_extra_date_inside:{owner}')
                    flags.add('A_extra_date_has_calendar_candidate' if f['candidates']
                              else 'A_extra_date_has_no_calendar_candidate')
                if any(c['field'] == 'amendmentId' and c.get('additional_values') for c in checks):
                    flags.add('A_amendment_tail_contains_enbloc' if 'enblocId' in record
                              else 'A_amendment_tail_contains_revision')
                # Account for every A field name not aligned to a B scalar.
                # Implicit kind markers and empty captures are retained here;
                # this inventory is not a count of missing B information.
                for field_name, values in grouped.items():
                    nonempty = [f for f in values if f['raw']]
                    if not nonempty:
                        continue
                    keys = [key for key in record if field_name in FIELD_MAP.get(key, ())]
                    matched = any(scalar(f['raw'], record[key], key) == scalar(record[key], record[key], key)
                                  for f in nonempty for key in keys)
                    if not matched:
                        by_kind[kind][f'A_unaligned_field:{field_name}'] += 1
            else:
                counts['rejected'] += 1
                for rule in rules:
                    rejection_rules[ext, rule] += 1
                for field_name in grouped:
                    field_inventory['B-rejected:' + ext, field_name] += 1
            for flag in sorted(flags):
                patterns[flag] += 1
                by_kind[kind][flag] += 1
                if len(examples[flag]) < 3:
                    examples[flag].append({'filename': name, 'A': fields, 'B': record})
            index.append({'filename': name, 'extension_class': ext, 'accepted': accepted,
                          'kind': kind, 'patterns': sorted(flags)})
    assert counts['total'] == baseline['literal_filenames']
    assert counts['accepted'] == baseline['counts']['b_valid']
    assert all(digest(path) == expected for path, expected in hashes.items())
    pq.write_table(pa.Table.from_pylist(index), args.output / 'patterns.parquet', compression='zstd')
    summary = {'counts': counts, 'patterns': patterns, 'by_extension': by_extension,
               'by_kind': by_kind, 'input_hashes': hashes, 'current_source_hashes_verified': True,
               'A_field_inventory': [{'kind': k, 'field': f, 'filenames': n}
                                     for (k, f), n in sorted(field_inventory.items())],
               'B_field_inventory': [{'kind': k, 'field': f, 'filenames': n}
                                     for (k, f), n in sorted(b_field_inventory.items())],
               'rejected_A_rules': [{'extension_class': e, 'rule': r, 'filenames': n}
                                    for (e, r), n in sorted(rejection_rules.items())]}
    for filename, value in [('summary.json', summary), ('examples.json', examples)]:
        (args.output / filename).write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps({'counts': counts, 'patterns': patterns}, indent=2))


if __name__ == '__main__':
    main()
