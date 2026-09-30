"""Compare native parsers on all literal saved filenames; no parser changes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import shutil
from time import perf_counter

import pyarrow as pa
import pyarrow.parquet as pq
from house_naming import Engine
from house_naming.compiler import stem_pattern
from house_naming.filenames import registry, parse_filename
from house_naming.filename_corpus import file_hashes, parser_source_paths

# Compare printed scalar values, not document identities or inferred relationships.
FIELD_MAP = {
    'congress': ('congress',),
    'measureType': ('measure_token',),
    'measureNumber': ('measure_number',),
    'stage': ('version_token', 'scope_token', 'local_code_token'),
    'committeeCode': ('committee_code',),
    'meetingType': ('meeting_token', 'package_family'),
    'meetingDate': ('date_token',), 'voteDate': ('date_token',), 'weekOf': ('date_token',),
    'fiscalYear': ('fiscal_year_token',),
    'sequence': ('appropriation_sequence',),
    'witnessId': ('subject_token',),
    'sponsorBioguideId': ('bioguide_token',), 'memberBioguideId': ('bioguide_token',),
    'amendmentId': ('amendment_identifier', 'amendment_token'),
    'enblocId': ('enbloc_number',),
    'reportNumber': ('publication_number',),
    'partNumber': ('part_number',),
    'quarter': ('quarter_number',),
    'meetingOccurrence': ('meeting_sequence',),
    'revision': ('revision_number',),
    'supportId': ('document_identifier',), 'voteId': ('document_number',),
    'subject': ('appropriation_subject', 'descriptor'),
    'description': ('descriptor', 'title_token'),
    'extension': ('extension',),
    'amendmentType': ('amendment_marker',),
    'documentType': ('document_token',), 'documentNumber': ('document_number',),
    'publicationType': ('publication_code',), 'publicationNumber': ('publication_number',),
    'publicationSuffix': ('suffix',),
}
CASEFOLD = {'measureType', 'stage', 'committeeCode', 'meetingType', 'extension', 'amendmentType'}
OPAQUE = {'extension', 'payload', 'descriptor', 'suffix', 'subject_token', 'annotation'}
SCOPES = {r['id']: r['scope'] for r in registry()}
FAMILIES = ('BILLS', 'HHRG', 'HMKP', 'HMTG', 'CRPT', 'HRPT', 'SRPT', 'CHRG', 'CPRT', 'AMDT', 'AMNT')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def family(name):
    match = re.match(r'([A-Za-z]+)\s*-', name)
    value = match[1].upper() if match else ''
    return value if value in FAMILIES else 'other'


def suffix_class(name):
    extension = Path(name).suffix.casefold()
    if extension in {'.pdf', '.xml'}:
        return 'pdf_xml'
    if extension in {'.htm', '.html', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.rtf', '.zip', '.csv', '.tsv', '.xsd'}:
        return 'other_document_extension'
    return 'other_extension' if extension else 'no_extension'


def scalar(value, expected, key):
    if type(expected) is int:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return str(value)
    text = str(value)
    return text.casefold() if key in CASEFOLD else text


def compare_fields(native, parsed):
    fields = [f for m in parsed.matches for f in m.fields] if parsed else []
    comparisons = []
    for match in native['matches']:
        checks = []
        for key, expected in match['record'].items():
            if key == 'kind':
                continue
            if key not in FIELD_MAP:
                checks.append({'field': key, 'expected': expected, 'status': 'unmapped', 'observed': []})
                continue
            observed = []
            for field in fields:
                if field.name not in FIELD_MAP[key]:
                    continue
                if key == 'stage' and field.name == 'version_token' and field.code is None:
                    continue  # An uncertain suffix is not an asserted stage.
                value = field.code if key == 'amendmentType' and field.code else field.raw
                if value not in observed:
                    observed.append(value)
            target = scalar(expected, expected, key)
            values = {scalar(v, expected, key) for v in observed}
            status = 'present' if target in values else 'different' if observed else 'missing'
            checks.append({'field': key, 'expected': expected, 'status': status, 'observed': observed,
                           'additional_values': sorted(values - {target})})
        comparisons.append({'kind': match['kind'], 'fields': checks})
    return comparisons


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('output', type=Path)
    ap.add_argument('--inventory', type=Path, default=Path('output/filename-clustering/filenames.parquet'))
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = [args.inventory, Path(__file__), Path(__file__).with_name('filename-engine-comparison.md'), *parser_source_paths()]
    for sidecar in ('inventory-recovery.json', 'rebuild_inventory.py'):
        if (path := args.inventory.parent / sidecar).exists():
            inputs.append(path)
    hashes = file_hashes(inputs)
    snapshot = args.output / 'source'
    for path in inputs[1:]:
        target = snapshot / path.resolve().relative_to(Path.cwd())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    rows = pq.read_table(args.inventory, columns=['filename', 'variants', 'hosts', 'url_examples']).to_pylist()
    names = sorted({n for row in rows for n in (row['filename'], *(row['variants'] or []))})
    contexts = {n: {'hosts': row['hosts'], 'url_examples': row['url_examples']} for row in rows
                for n in (row['filename'], *(row['variants'] or []))}
    engine = Engine()
    guide = engine.guide
    lexical = [(k, re.compile(stem_pattern(guide, k, capture=False), re.I))
               for k, r in guide['patterns'].items() if r['action'] == 'filename']
    counts = Counter(); by_family = defaultdict(Counter); by_suffix = defaultdict(Counter); a_rules = Counter(); b_kinds = Counter()
    reasons = Counter(); field_counts = defaultdict(Counter); kind_fields = defaultdict(Counter)
    examples = defaultdict(list); timings = {'a': [], 'b': []}; index = []
    names_digest = hashlib.sha256()
    started = perf_counter()
    raw_path = args.output / 'paired-outputs.jsonl.gz'
    with gzip.open(raw_path, 'wt', compresslevel=1, encoding='utf-8') as stream:
        for i, name in enumerate(names):
            if perf_counter() - started > 1800:
                raise TimeoutError('Declared 30-minute experiment bound reached; partial raw outputs retained.')
            names_digest.update((json.dumps(name, ensure_ascii=False) + '\n').encode())
            results = {}; errors = {}
            for arm in (('a', 'b') if i % 2 == 0 else ('b', 'a')):
                before = perf_counter()
                try:
                    results[arm] = parse_filename(name) if arm == 'a' else engine.parse(name)
                except Exception as exc:
                    errors[arm] = {'type': type(exc).__name__, 'message': str(exc)}
                    results[arm] = None
                timings[arm].append(perf_counter() - before)
            a, b = results['a'], results['b']
            flags = Counter(total=1)
            for arm in errors:
                flags[f'{arm}_exception'] += 1
            layouts = [m for m in a.matches if SCOPES.get(m.rule) == 'stem'] if a else []
            a_layout = bool(layouts)
            a_fields = any(f.raw and f.name not in OPAQUE for m in a.matches for f in m.fields) if a else False
            if a:
                assert ''.join(p.raw for p in a.pieces) == name
                for match in a.matches:
                    for f in match.fields:
                        assert 0 <= match.start <= f.start <= f.end <= match.end <= len(name)
                        assert name[f.start:f.end] == f.raw
                        flags['a_field_spans_checked'] += 1
                flags['a_lossless'] += 1
                for rule in {m.rule for m in a.matches}:
                    a_rules[rule] += 1
                scopes = Counter(SCOPES.get(m.rule) for m in a.matches)
                flags['a_competing_layouts'] += any(scopes[s] > 1 for s in ('stem', 'legislative-payload', 'committee-payload'))
                flags['a_unparsed_inner_payload'] += any(
                    m.rule in {'legislative-file', 'committee-file'} and
                    not any(SCOPES.get(child.rule) == ('legislative-payload' if m.rule == 'legislative-file' else 'committee-payload') for child in a.matches)
                    for m in layouts)
            b_valid = bool(b and b['valid'])
            flags['a_layout'] += a_layout
            flags['a_fields'] += a_fields
            flags['a_partial_only'] += a_fields and not a_layout
            flags['b_valid'] += b_valid
            bucket = 'both' if a_layout and b_valid else 'a_only' if a_layout else 'b_only' if b_valid else 'neither'
            flags[bucket] += 1
            diagnostics = []
            comparisons = compare_fields(b, a) if b_valid else []
            if b:
                flags['b_ambiguous'] += b['ambiguous']
                flags['b_source_example'] += b['found_in_source']
                for kind in {m['kind'] for m in b['matches']}:
                    b_kinds[kind] += 1
                for match in b['matches']:
                    canonical = engine.render(match['record'])
                    assert canonical == match.get('canonical_filename', name)
                    assert match['record'] in [m['record'] for m in engine.parse(canonical)['matches']], (name, match, engine.parse(canonical))
                    flags['b_literal_roundtrips'] += canonical == name
                    flags['b_roundtrips_checked'] += 1
                for reason in b['issues']:
                    reasons[reason] += 1
                if not b_valid:
                    stem, dot, ext = name.rpartition('.')
                    if dot and ext.lower() in ('pdf', 'xml'):
                        stem = re.sub(r'-U[0-9]+$', '', stem, flags=re.I)
                        diagnostics = [kind for kind, pattern in lexical if pattern.fullmatch(stem)]
                    flags['b_rejected_case_insensitive_lexical_hit'] += bool(diagnostics)
            candidate_complete = []
            for comparison in comparisons:
                misses = []
                for check in comparison['fields']:
                    field_counts[check['field']][check['status']] += 1
                    kind_fields[comparison['kind']][check['status']] += 1
                    if check.get('additional_values'):
                        field_counts[check['field']]['with_additional_a_values'] += 1
                    if check['status'] != 'present':
                        misses.append(check)
                        key = f"field:{check['field']}:{check['status']}"
                        if len(examples[key]) < 5:
                            examples[key].append({'filename': name, 'kind': comparison['kind'], **check})
                candidate_complete.append(not misses)
            if b_valid:
                flags['b_names_all_candidates_fields_present_in_a'] += all(candidate_complete)
                flags['b_names_some_candidate_fields_present_in_a'] += any(candidate_complete)
            fam = family(name)
            counts.update(flags); by_family[fam].update(flags); by_suffix[suffix_class(name)].update(flags)
            key = f'{fam}:{bucket}'
            if len(examples[key]) < 5:
                examples[key].append({'filename': name, 'a_layouts': [m.rule for m in layouts],
                                      'b_kinds': [m['kind'] for m in b['matches']] if b else [],
                                      'b_issues': b['issues'] if b else errors.get('b'),
                                      'lexical_diagnostic': diagnostics, **contexts[name]})
            if b and b['ambiguous'] and len(examples['b_ambiguous']) < 10:
                examples['b_ambiguous'].append({'filename':name, 'matches':b['matches']})
            stream.write(json.dumps({'filename': name, 'family': fam,
                'a': a.model_dump() if a else None, 'b': b, 'errors': errors,
                'field_comparisons': comparisons, 'case_insensitive_lexical_matches': diagnostics},
                ensure_ascii=False, separators=(',', ':')) + '\n')
            index.append({'filename':name, 'family':fam, 'suffix_class':suffix_class(name), 'a_layout':a_layout, 'a_fields':a_fields,
                'b_valid':b_valid, 'b_ambiguous':bool(b and b['ambiguous']), 'bucket':bucket,
                'a_rules': [m.rule for m in a.matches] if a else [],
                'b_kinds': [m['kind'] for m in b['matches']] if b else [],
                'b_issues': b['issues'] if b else [],
                'case_insensitive_lexical_matches':diagnostics,
                'b_candidate_fields_all_present': bool(b_valid and all(candidate_complete))})
            if (i + 1) % 25000 == 0:
                print(json.dumps({'processed':i+1, 'total':len(names), 'elapsed_seconds':round(perf_counter()-started,1),
                                  'a_layout':counts['a_layout'], 'b_valid':counts['b_valid']}),flush=True)
    elapsed = perf_counter() - started
    timing_summary = {}
    for arm, values in timings.items():
        ordered = sorted(values)
        timing_summary[arm] = {'total_seconds':sum(values),'median_ms':ordered[len(values)//2]*1000,
                              'p95_ms':ordered[int(len(values)*.95)]*1000}
    after_hashes = file_hashes(inputs)
    changed = [p for p in hashes if hashes[p] != after_hashes[p]]
    summary = {'inventory_rows':len(rows), 'literal_filenames':len(names),
               'literal_filenames_sha256':names_digest.hexdigest(), 'counts':dict(counts),
               'by_family':dict(by_family), 'by_suffix_class':dict(by_suffix), 'a_rules':a_rules, 'b_kinds':b_kinds,
               'b_issues':reasons, 'field_comparisons':dict(field_counts), 'by_kind_fields':dict(kind_fields),
               'timing':timing_summary,'elapsed_seconds':elapsed,
               'hashes':hashes,'changed_during_run':changed,
               'environment':{'python':platform.python_version(), 'platform':platform.platform(),
                   'house-naming-guide':version('house-naming-guide'),'pydantic':version('pydantic'),
                   'jsonschema':version('jsonschema'),'pyarrow':version('pyarrow')},
               'mechanical_checks_passed':not changed, 'all_cases_processed':counts['total']==len(names)}
    pq.write_table(pa.Table.from_pylist(index), args.output/'comparison.parquet',compression='zstd')
    write_json(args.output/'summary.json', summary)
    write_json(args.output/'examples.json', dict(examples))
    print(json.dumps({k:summary[k] for k in ('literal_filenames','counts','timing','elapsed_seconds','changed_during_run','mechanical_checks_passed')},indent=2))
    return 0 if summary['mechanical_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
