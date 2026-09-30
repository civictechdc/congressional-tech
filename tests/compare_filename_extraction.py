"""Compare literal House extraction with every saved native corpus output."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from time import perf_counter

from house_naming import Engine
from house_naming.filename_corpus import parser_source_paths
from house_naming.filenames import parse_filename


def strict_results_equal(before, after, *, allow_diagnostics=False):
    """Allow only additive, explained validation diagnostics, never new records."""
    for key, value in before.items():
        if key == 'issues' and allow_diagnostics:
            codes = {r['code'] for r in after.get('rejected_candidates', [])}
            if not set(value) <= set(after[key]) or not set(after[key]) - set(value) <= codes:
                return False
        elif after[key] != value:
            return False
    return True


def check_adapter(filename, result):
    """Exercise the actual application entry point and retain all engine fields."""
    parsed = parse_filename(filename).model_dump(mode='json')
    for key, target in [('input', 'filename'), ('stem_end', 'stem_end'), ('pieces', 'pieces'),
                        ('suppressed', 'suppressed'), ('issues', 'issues'),
                        ('rejected_candidates', 'rejected_candidates'), ('observations', 'matches')]:
        actual = parsed[target]
        assert actual == result[key], ('Typed adapter lost engine data', filename, key)


def reviewed_strict_change(before, after, review):
    """Permit only an exact, explained correction; never waive a whole kind."""
    return bool(review and review.get('reason') and before != after
                and before == review.get('before') and after == review.get('after'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fields(matches):
    return {(f['name'], f['raw'], f['start'], f['end']) for m in matches for f in m['fields']}


def field_metadata(matches):
    """Keep all meanings when multiple observations share one literal field."""
    values = defaultdict(lambda: defaultdict(set))
    for match in matches:
        for field in match['fields']:
            key = field['name'], field['raw'], field['start'], field['end']
            for attribute in ('code', 'label', 'note', 'candidates'):
                values[key][attribute].add(json.dumps(field.get(attribute), sort_keys=True))
    return values


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--experiment', type=Path, default=Path(__file__).with_name('house-naming-extraction.md'),
                    help='Predeclared experiment to retain with the source snapshot')
    ap.add_argument('--source', type=Path, action='append', default=[],
                    help='Additional test or validation source to snapshot (repeatable)')
    ap.add_argument('--allow-validation-diagnostics', action='store_true')
    ap.add_argument('--check-adapter', action='store_true')
    ap.add_argument('--strict-corrections', type=Path,
                    help='Exact per-filename before/after strict results with review reasons')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((args.baseline/'summary.json').read_text())
    for file, expected in baseline['hashes'].items():
        if '/packages/congress_api/' in file:
            frozen = args.baseline / 'source' / Path(file).relative_to(Path.cwd())
            assert sha(frozen) == expected, ('Frozen independent comparator changed', file)
    corrections = json.loads(args.strict_corrections.read_text()) if args.strict_corrections else {}
    assert isinstance(corrections, dict)
    used_corrections = set()
    paths = [Path(__file__), args.experiment,
             Path(__file__).with_name('audit_filename_extraction.py'), *args.source, *parser_source_paths()]
    if args.strict_corrections:
        paths.append(args.strict_corrections)
    hashes = {str(p.resolve()): sha(p) for p in paths}
    for p in paths:
        dest = args.output/'source'/p.resolve().relative_to(Path.cwd())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    counts = Counter(); added = Counter(); missing = Counter(); reasons = Counter(); rules = Counter()
    examples = defaultdict(list)
    engine = Engine()
    catalog = engine.guide['codes']
    metadata_counts = Counter(); metadata_examples = defaultdict(list)
    started = perf_counter()
    with (
        gzip.open(args.baseline/'paired-outputs.jsonl.gz','rt') as old,
        gzip.open(args.output/'extractions.jsonl.gz','wt',compresslevel=1) as out,
        gzip.open(args.output/'differences.jsonl.gz','wt',compresslevel=1) as differences,
        gzip.open(args.output/'metadata-differences.jsonl.gz','wt',compresslevel=1) as metadata_out,
    ):
        for line in old:
            row = json.loads(line); name = row['filename']; counts['inputs'] += 1
            if perf_counter() - started > 1800:
                raise TimeoutError('30-minute corpus limit reached; partial evidence retained')
            try:
                result = engine.extract(name)
            except Exception as exc:
                counts['exceptions'] += 1
                out.write(json.dumps({'filename': name, 'error': repr(exc)})+'\n')
                if len(examples['exceptions']) < 20: examples['exceptions'].append({'filename': name, 'error':repr(exc)})
                continue
            unchanged = strict_results_equal(row['b'], result, allow_diagnostics=args.allow_validation_diagnostics)
            if not unchanged:
                assert reviewed_strict_change(row['b'], engine.parse(name), corrections.get(name)), ('Unreviewed strict behavior changed', name)
                used_corrections.add(name)
                counts['reviewed_strict_corrections'] += 1
            else:
                counts['strict_records_unchanged'] += 1
            counts['strict_results_unchanged'] += all(result[k] == value for k, value in row['b'].items())
            counts['new_validation_diagnostics'] += result['issues'] != row['b']['issues']
            if args.check_adapter:
                check_adapter(name, result)
                counts['typed_adapter_results_checked'] += 1
            assert ''.join(p['raw'] for p in result['pieces']) == name
            counts['lossless_inputs'] += 1
            for m in result['observations']:
                rules[m['rule']] += 1
                for f in m['fields']:
                    assert 0 <= m['start'] <= f['start'] <= f['end'] <= m['end'] <= len(name), (name, m, f)
                    assert name[f['start']:f['end']] == f['raw'], (name,m,f)
                    counts['field_spans_checked'] += 1
                    if f['context']:
                        assert f['code'] in catalog[f['context']], ('Broken source-definition reference', name, f)
                        counts['definition_references_checked'] += 1
            for item in result['suppressed']:
                assert name[item['start']:item['end']] == item['raw']
                reasons[item['reason']] += 1
            non_extension = [m for m in result['observations'] if m['scope'] != 'extension']
            counts['names_with_observations'] += bool(non_extension)
            has_layout = any(m['scope'] in {'stem','collection-prefix'} for m in non_extension)
            counts['names_with_layout'] += has_layout
            has_assumptions = any(m['scope'] in {'unmatched-date','unmatched-stem'} for m in non_extension)
            counts['names_with_fallback_assumptions'] += has_assumptions
            if not non_extension:
                counts['without_semantic_observations'] += 1
                if len(examples['without_semantic_observations']) < 100: examples['without_semantic_observations'].append(name)
            a, b = fields(row['a']['matches']), fields(result['observations'])
            absent, gained = a-b, b-a
            for f in absent: missing[f[0]] += 1
            for f in gained: added[f[0]] += 1
            if not absent: counts['all_native_raw_fields_retained'] += 1
            if gained: counts['names_with_new_fields'] += 1
            code_a = {(f['name'],f['raw'],f['start'],f['end']): f['code'] for m in row['a']['matches'] for f in m['fields'] if f.get('code')}
            code_b = {(f['name'],f['raw'],f['start'],f['end']): f['code'] for m in result['observations'] for f in m['fields'] if f.get('code')}
            meaning_lost = {key:value for key,value in code_a.items() if key in b and code_b.get(key) != value}
            if absent or gained or meaning_lost:
                differences.write(json.dumps({'filename':name,'missing_raw_fields':sorted(absent),'new_raw_fields':sorted(gained),
                    'meaning_changes':[{'field':k,'before':v,'after':code_b.get(k)} for k,v in meaning_lost.items()],
                    'suppressed':result['suppressed']})+'\n')
            counts['changed_code_meanings'] += len(meaning_lost)
            metadata_a, metadata_b = field_metadata(row['a']['matches']), field_metadata(result['observations'])
            metadata_changes = []
            for key in sorted(metadata_a.keys() & metadata_b.keys()):
                for attribute, before in metadata_a[key].items():
                    after = metadata_b[key][attribute]
                    if before == after:
                        continue
                    group = f'{attribute}:{key[0]}'
                    metadata_counts[group] += 1
                    change = {'field':key, 'attribute':attribute,
                              'before':[json.loads(v) for v in sorted(before)],
                              'after':[json.loads(v) for v in sorted(after)]}
                    metadata_changes.append(change)
                    if len(metadata_examples[group]) < 5:
                        metadata_examples[group].append({'filename':name, **change})
            if metadata_changes:
                counts['names_with_metadata_differences'] += 1
                metadata_out.write(json.dumps({'filename':name,'changes':metadata_changes})+'\n')
            out.write(json.dumps({'filename':name,'result':result})+'\n')
            if counts['inputs'] % 50000 == 0: print(json.dumps({'processed':counts['inputs'],'seconds':round(perf_counter()-started,1)}),flush=True)
    report={'counts':counts,'rules':rules,'missing_field_names':missing,'new_field_names':added,'suppression_reasons':reasons,'examples':examples,
            'native_metadata_differences':metadata_counts,'native_metadata_examples':metadata_examples,
            'hashes':hashes,'baseline':str(args.baseline.resolve()),'baseline_output_sha256':sha(args.baseline/'paired-outputs.jsonl.gz'),
            'seconds':perf_counter()-started,'source_drift':[p for p,h in hashes.items() if sha(p)!=h],
            'reviewed_strict_corrections': sorted(used_corrections)}
    (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    assert counts['inputs'] == baseline['literal_filenames']
    assert not counts['exceptions'] and not report['source_drift']
    assert used_corrections == set(corrections), ('Stale or unused strict corrections', set(corrections) - used_corrections)


if __name__=='__main__': main()
