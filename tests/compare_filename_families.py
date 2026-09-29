"""Replay the same inputs through frozen/current parsers; retain both results.

Run with the repository interpreter and --gaps-only for candidate development;
omit that option for the final full-inventory comparison.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from time import perf_counter

import pyarrow.parquet as pq

from congress_api import filenames as current
from congress_api.filename_corpus import member_surnames_by_congress, file_hashes, SOURCE_FILES
from congress_api.models.legislators import parse_legislators


def load_baseline(root):
    """Use the frozen vocabulary as well as the frozen regex implementation."""
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    vocabulary = load('filename_baseline_bill_codes', root / 'bill_codes.py')
    current_vocabulary = sys.modules['congress_api.bill_codes']
    try:
        sys.modules['congress_api.bill_codes'] = vocabulary
        return load('filename_family_baseline', root / 'filenames.py')
    finally:
        sys.modules['congress_api.bill_codes'] = current_vocabulary


def matches_digest(matches):
    return hashlib.sha256(json.dumps(matches, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trial')
    parser.add_argument('--gaps-only', action='store_true')
    parser.add_argument('--root', type=Path, default=Path('output/filename-regex/family-experiment-20260929'),
                        help='Frozen filenames.py and baseline-remaining-legislative-payloads.json directory.')
    parser.add_argument('--minimum-useful', type=int, default=595)
    parser.add_argument('--inventory', type=Path, default=Path('output/filename-clustering/filenames.parquet'))
    parser.add_argument('--legislators', type=Path, default=Path('.cache/source-models/legislators-current.json'))
    parser.add_argument('--expected-changes', type=Path, help='Reviewed exact before/after match hashes, keyed by filename.')
    args = parser.parse_args()
    root = args.root
    out = root / args.trial
    out.mkdir(exist_ok=False)
    source = Path(current.__file__)
    ref, inventory = args.legislators, args.inventory
    paths = [*(source.parent / name for name in SOURCE_FILES), root / 'filenames.py', root / 'bill_codes.py',
             root / 'baseline-remaining-legislative-payloads.json', inventory, ref, Path(__file__)]
    if args.expected_changes:
        paths.append(args.expected_changes)
    before_hashes = file_hashes(paths)
    shutil.copy2(source, out / 'filenames.py')
    shutil.copy2(__file__, out / 'compare_filename_families.py')
    baseline = load_baseline(root)
    context = member_surnames_by_congress(parse_legislators(ref.read_bytes()))
    gaps = {r['filename']: r['group'] for r in json.loads((root / 'baseline-remaining-legislative-payloads.json').read_text())}
    expected_changes = json.loads(args.expected_changes.read_text()) if args.expected_changes else {}
    rows = pq.read_table(inventory, columns=['filename', 'variants']).to_pylist()
    names = sorted(gaps if args.gaps_only else {n for r in rows for n in [r['filename'], *(r['variants'] or [])]})
    scopes = {r.id: r.scope for r in current.RULES}
    counts = Counter(); by_group = {}; problems = []; remaining = []; opaque_only = []
    changed = {}
    excluded = {'payload', 'descriptor', 'subject_token', 'suffix', 'annotation'}
    begun = perf_counter()
    with gzip.open(out / 'outputs.jsonl.gz', 'wt') as stream:
        for name in names:
            before = baseline.parse_filename(name, member_surnames=context)
            after = current.parse_filename(name, member_surnames=context)
            counts['filenames'] += 1
            old = [m.model_dump() for m in before.matches]
            new = [m.model_dump() for m in after.matches]
            if old != new:
                changed[name] = {'before_sha256': matches_digest(old), 'after_sha256': matches_digest(new)}
            reviewed = name in changed and expected_changes.get(name) == changed[name]
            lost = [m for m in old if m not in new]
            if lost and not reviewed:
                problems.append({'filename': name, 'lost_or_changed': lost})
            assert ''.join(p.raw for p in after.pieces) == name
            for match in after.matches:
                for f in match.fields:
                    assert 0 <= match.start <= f.start <= f.end <= match.end <= len(name)
                    assert name[f.start:f.end] == f.raw
            inner = [m for m in after.matches if scopes.get(m.rule) == 'legislative-payload']
            if len(inner) > 1:
                problems.append({'filename': name, 'competing_layouts': [m.rule for m in inner]})
            previous = {(f.name, f.raw, f.start, f.end) for m in before.matches for f in m.fields}
            useful = [f.model_dump() for m in after.matches for f in m.fields
                      if f.raw and f.name not in excluded and (f.name, f.raw, f.start, f.end) not in previous]
            if name in gaps:
                group = by_group.setdefault(gaps[name], Counter())
                group['total'] += 1
                group['matched'] += bool(inner)
                group['useful_gain'] += bool(inner and useful)
                counts['gap_layouts_recovered'] += bool(inner)
                counts['gaps_with_useful_gain'] += bool(inner and useful)
                if not inner:
                    remaining.append(name)
                elif not useful:
                    opaque_only.append(name)
            if old != new:
                counts['changed_outputs'] += 1
                if name not in gaps:
                    counts['changed_outside_gaps'] += 1
                    counts['unreviewed_changes'] += not reviewed
            if old != new or name in gaps:
                stream.write(json.dumps({'filename': name, 'before': old, 'after': new, 'useful_added_fields': useful}) + '\n')
    for name, value in expected_changes.items():
        if changed.get(name) != value:
            problems.append({'filename': name, 'stale_expected_change': value})
    after_hashes = file_hashes(paths)
    unstable = [name for name in before_hashes if before_hashes[name] != after_hashes[name]]
    result = {'counts': dict(counts), 'by_group': by_group, 'problems': problems,
              'remaining': remaining, 'matches_without_new_useful_fields': opaque_only,
              'elapsed_seconds': perf_counter() - begun, 'gaps_only': args.gaps_only,
              'hashes': before_hashes, 'changed_during_run': unstable,
              'minimum_useful': args.minimum_useful,
              'mechanical_gate': not problems and not unstable and not counts['unreviewed_changes']
                                 and counts['gaps_with_useful_gain'] >= args.minimum_useful}
    (out / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    (out / 'changes.json').write_text(json.dumps(changed, indent=2) + '\n')
    print(json.dumps({**{k: v for k, v in result.items() if k not in {'hashes', 'problems', 'remaining', 'matches_without_new_useful_fields'}},
                      'problem_count': len(problems), 'problem_examples': problems[:5], 'remaining_count': len(remaining)}, indent=2))
    return 0 if result['mechanical_gate'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
