"""Account for every omitted native field and compare the native name fallback."""
import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path

from compare_filename_families import load_baseline


def signature(field):
    return field['name'], field['raw'], field['start'], field['end']


def native_refinement_reason(field, observations):
    """Account for literal refinements, never waive an existing coded meaning."""
    if field.get('code') or field.get('label') or field.get('candidates') or field.get('context'):
        return None
    if field['name'] == 'suffix' and field['raw']:
        opaque = {'payload', 'suffix', 'descriptor', 'subject_token', 'target_subject',
                  'title_token', 'name_token', 'filer_token', 'local_identifier', 'measure_list',
                  'generic_identifier'}
        specific = [f for m in observations for f in m['fields']
                    if f['name'] not in opaque and not m['scope'].startswith('unmatched-')
                    and len(f['raw']) == f['end'] - f['start']]
        positions = [field['start'] + i for i, char in enumerate(field['raw']) if char.isalnum()]
        if positions and all(any(f['start'] <= i < f['end']
                                 and f['raw'][i - f['start']] == field['raw'][i - field['start']]
                                 for f in specific) for i in positions):
            return 'opaque_suffix_refined'
    for match in observations:
        if match['rule'] != 'legislative-text':
            continue
        fields = {f['name']: f for f in match['fields']}
        version, hanging, suffix = (fields.get(k) for k in ('version_token', 'ignored_suffix', 'suffix'))
        if not (version and hanging and version.get('context') == 'version'
                and version.get('code') == version['raw'].lower() and version.get('label')
                and hanging['raw'].lower() == 'pdf' and version['end'] == hanging['start']):
            continue
        if (field['name'] == 'version_token' and field['raw'] == version['raw'] + hanging['raw']
                and (field['start'], field['end']) == (version['start'], hanging['end'])):
            return 'hanging_pdf_separated'
        if (field['name'] == 'suffix' and field['raw'] == '' and suffix and suffix['raw'] == ''
                and field['start'] == field['end'] == hanging['end']
                and suffix['start'] == suffix['end'] == hanging['start']):
            return 'empty_suffix_boundary_refined'
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    ap.add_argument('--previous-extraction', type=Path,
                    help='Also retain full changed House outputs versus this saved extraction run')
    args = ap.parse_args()
    summary = json.loads((args.run/'summary.json').read_text())
    baseline = Path(summary['baseline'])
    native = load_baseline(baseline)
    counts = Counter(); missing = Counter(); examples = defaultdict(list)
    old = gzip.open(baseline/'paired-outputs.jsonl.gz','rt')
    new = gzip.open(args.run/'extractions.jsonl.gz','rt')
    details = gzip.open(args.run/'omission-audit.jsonl.gz','wt',compresslevel=1)
    fallback = gzip.open(args.run/'fallback-comparison.jsonl.gz','wt',compresslevel=1)
    prior_path = args.previous_extraction/'extractions.jsonl.gz' if args.previous_extraction else None
    changes = gzip.open(args.run/'iteration-differences.jsonl.gz','wt',compresslevel=1) if prior_path else nullcontext()
    iterations = Counter(); change_groups = Counter(); change_examples = defaultdict(list)
    with old, new, details, fallback, changes as changed, (gzip.open(prior_path,'rt') if prior_path else nullcontext()) as prior_results:
        for a, b in zip_longest(old,new):
            assert a is not None and b is not None
            previous, current = json.loads(a), json.loads(b)
            assert previous['filename'] == current['filename']
            name = current['filename']; result = current['result']; counts['inputs'] += 1
            if prior_results is not None:
                previous_house = json.loads(next(prior_results))
                assert previous_house['filename'] == name
                before = previous_house['result']
                iterations['inputs_compared'] += 1
                if before != result:
                    iterations['changed_inputs'] += 1
                    old_fields = {signature(f):f for m in before['observations'] for f in m['fields']}
                    new_fields = {signature(f):f for m in result['observations'] for f in m['fields']}
                    lost_keys = old_fields.keys()-new_fields.keys()
                    new_keys = new_fields.keys()-old_fields.keys()
                    changed_fields = [key for key in old_fields.keys() & new_fields.keys() if old_fields[key] != new_fields[key]]
                    iterations['removed_coded_fields'] += sum(bool(old_fields[k]['code']) for k in lost_keys)
                    iterations['changed_shared_code_meanings'] += sum(old_fields[k]['code']!=new_fields[k]['code'] for k in changed_fields)
                    for key in changed_fields:
                        for attribute in ('code', 'label', 'context', 'candidates', 'note'):
                            if old_fields[key].get(attribute) != new_fields[key].get(attribute):
                                group = f'changed-{attribute}:{key[0]}'
                                change_groups[group] += 1
                                if len(change_examples[group]) < 5:
                                    change_examples[group].append({'filename':name,
                                        'before':old_fields[key], 'after':new_fields[key]})
                    old_rules = {m['rule'] for m in before['observations']}
                    new_rules = {m['rule'] for m in result['observations']}
                    for key in [*('added-rule:'+r for r in new_rules-old_rules),
                                *('removed-rule:'+r for r in old_rules-new_rules),
                                *('added-field:'+k[0] for k in new_keys),
                                *('removed-field:'+k[0] for k in lost_keys)]:
                        change_groups[key] += 1
                        if len(change_examples[key])<5:change_examples[key].append(name)
                    changed.write(json.dumps({'filename':name,'before':before,'after':result,
                        'removed_fields':[old_fields[k] for k in sorted(lost_keys)],
                        'new_fields':[new_fields[k] for k in sorted(new_keys)],
                        'changed_fields':[{'before':old_fields[k],'after':new_fields[k]} for k in sorted(changed_fields)]})+'\n')
            for item in result['suppressed']:
                assert name[item['start']:item['end']] == item['raw']
                counts['suppressed_candidates_checked'] += 1
                for field in item['fields']:
                    assert item['start'] <= field['start'] <= field['end'] <= item['end']
                    assert name[field['start']:field['end']] == field['raw']
                    counts['suppressed_fields_checked'] += 1
            by_field = {signature(f):f for m in result['observations'] for f in m['fields']}
            by_span = {(f['raw'],f['start'],f['end']) for f in by_field.values()}
            lost = {}
            for match in previous['a']['matches']:
                for field in match['fields']:
                    key = signature(field)
                    if key in by_field or key in lost:
                        continue
                    reason = 'needs_review'
                    receipts = []
                    if key[1:] in by_span:
                        reason = 'same_literal_other_field'
                    else:
                        receipts = [item for item in result['suppressed'] if item['rule'] == match['rule']
                                    and item['start'] <= field['start'] and field['end'] <= item['end']]
                        if receipts:
                            reason = ('invalid_calendar_candidate' if any(item['reason'] == 'No valid supported calendar reading.' for item in receipts)
                                      else 'date_after_revision_wording' if any(item['reason'].startswith('Date follows revision wording') for item in receipts)
                                      else 'overlapping_assigned_token')
                        elif any(f['name']=='query_text' and f['start'] <= field['start'] and field['end'] <= f['end'] for f in by_field.values()):
                            reason = 'query_text_separated'
                        elif field['name'] in {'payload','suffix'} and any(f['name']=='extension' and field['start'] <= f['start'] < field['end'] for f in by_field.values()):
                            reason = 'extension_separated'
                    if reason == 'needs_review':
                        reason = native_refinement_reason(field, result['observations']) or reason
                    lost[key] = {'old_rule':match['rule'],'field':field,'reason':reason,'receipts':receipts}
                    missing[reason] += 1
                    if len(examples[reason]) < 20: examples[reason].append({'filename':name,**lost[key]})
            if lost:
                details.write(json.dumps({'filename':name,'omissions':list(lost.values())})+'\n')
            # Compare the real prior fallback, not an expected value generated
            # by the replacement. New explicit layouts can supersede an assumption.
            if not any(m['scope'] in {'stem','collection-prefix'} for m in result['observations']):
                old_fallback = native.resolve_unmatched_filename(native.ParsedFilename.model_validate(previous['a']))
                new_fallback = [m for m in result['observations'] if m['scope'] in {'unmatched-date','unmatched-stem'}]
                if old_fallback:
                    prior = old_fallback.model_dump()
                    available = {signature(f) for m in new_fallback for f in m['fields']}
                    absent = [f for f in prior['fields'] if signature(f) not in available]
                    counts['native_fallback_cases'] += 1
                    if absent:
                        counts['changed_fallbacks'] += 1
                        fallback.write(json.dumps({'filename':name,'before':prior,'after':new_fallback,'missing_fields':absent})+'\n')
                    else:
                        counts['native_fallback_fields_preserved'] += 1
        if prior_results is not None:
            assert next(prior_results,None) is None
    assert counts['inputs'] == summary['counts']['inputs']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in summary['hashes'].items())
    guide_path = Path('packages/house-naming/src/house_naming/data/guide.json')
    old_guide = json.loads((baseline/'source'/guide_path).read_text())
    new_guide = json.loads(guide_path.read_text())
    unchanged = ['document','codes','code_index','source_nodes','sections','examples',
                 'example_index','committees','footnotes']
    assert all(old_guide[key] == new_guide[key] for key in unchanged)
    report={'counts':counts,'omission_reasons':missing,'examples':examples,
            'unchanged_guide_sections':unchanged,
            'audit_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.run/'omission-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    if prior_path:
        (args.run/'iteration-summary.json').write_text(json.dumps({'counts':iterations,'changes':change_groups,
            'examples':change_examples,'previous_output':str(prior_path.resolve()),
            'previous_sha256':hashlib.sha256(prior_path.read_bytes()).hexdigest(),
            'audit_sha256':report['audit_sha256']},indent=2)+'\n')
    print(json.dumps({'counts':counts,'omission_reasons':missing},indent=2))


if __name__=='__main__':main()
