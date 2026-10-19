"""Inventory retained House-engine rejections and probe bounded formatting edits."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import gzip
import hashlib
import json
from pathlib import Path
import re
from time import perf_counter

import pyarrow as pa
import pyarrow.parquet as pq
from house_naming import Engine, NamingError
from house_naming.compiler import escape_literal, lexeme, parts, stem_pattern

SEPARATOR = r"[-_\s]*"


def matcher(guide, kind, *, separators=False, numbers=False, dates=False):
    rule = guide['patterns'][kind]
    if not (separators or numbers or dates):
        return re.compile(stem_pattern(guide, kind, capture=True), re.I)
    out = []
    for literal, name in parts(rule['stem_template']):
        out.append(escape_literal(literal).replace('-', SEPARATOR) if separators else escape_literal(literal))
        if name is None:
            continue
        if name == 'meetingSuffix':
            out.append(r'(?:[-_\s]+(?P<meetingOccurrence>[0-9]{1,12}))?')
            continue
        schema = guide['field_types'][rule['fields'][name]]
        atom = lexeme(schema)
        if numbers and schema['type'] == 'integer':
            atom = r'[0-9]{1,12}'
        if dates and name in ('meetingDate', 'voteDate', 'weekOf'):
            atom = r'[0-9]{8}'
        if separators and not literal:
            out.append(SEPARATOR)
        out.append(f'(?P<{name}>{atom})')
    return re.compile(''.join(out), re.I)


def clean_separators(name):
    return re.sub(r'[-_\s]', '', name).casefold()


def changes(original, rendered):
    return [{'old': original[a:b], 'new': rendered[c:d], 'start': a, 'end': b}
            for op, a, b, c, d in SequenceMatcher(None, original, rendered, autojunk=False).get_opcodes()
            if op != 'equal']


def probe(name, engine, guide, matchers, mode):
    stem, dot, extension = name.rpartition('.')
    if not dot or extension.casefold() not in ('pdf', 'xml'):
        return [], []
    revision = re.search(r'-U([0-9]+)$', stem, re.I)
    if revision:
        stem = stem[:revision.start()]
    successes = []; failures = []
    for kind, rx in matchers:
        hit = rx.fullmatch(stem)
        if hit is None:
            continue
        rule = guide['patterns'][kind]
        record = {'kind': kind, 'extension': extension.lower()}
        if revision:
            record['revision'] = int(revision[1])
        raw_fields = {k: v for k, v in hit.groupdict().items() if v is not None}
        for key, raw in raw_fields.items():
            schema = guide['field_types'][rule['fields'][key]]
            if schema['type'] == 'integer':
                record[key] = int(raw)
            elif 'enum' in schema:
                record[key] = next((v for v in schema['enum'] if str(v).casefold() == raw.casefold()), raw)
            elif rule['fields'][key] in ('committeeCode', 'bioguideId'):
                record[key] = raw.upper()
            else:
                record[key] = raw
        try:
            rendered = engine.render(record)
            if mode == 'case' and rendered.casefold() != name.casefold():
                continue
            if mode == 'separator' and clean_separators(rendered) != clean_separators(name):
                continue
            accepted = engine.parse(rendered)
            assert any(m['record'] == record for m in accepted['matches'])
            successes.append({'kind': kind, 'record': record, 'rendered': rendered,
                              'edits': changes(name, rendered), 'raw_fields': raw_fields,
                              'rendered_ambiguous': accepted['ambiguous']})
        except NamingError as exc:
            failures.append({'kind': kind, 'record': record, 'code': exc.code, 'message': str(exc)})
    return successes, failures


def shape(row):
    fields = defaultdict(list)
    rules = []
    for match in row['a']['matches']:
        rules.append(match['rule'])
        for f in match['fields']:
            if f['raw'] and f['raw'] not in fields[f['name']]:
                fields[f['name']].append(f['raw'])
    structural = [r for r in rules if r not in SEARCH_RULES]
    # Existing extractor fields distinguish document layouts from prose/route names.
    tokens = {key: values for key, values in fields.items()
              if key in ('document_token', 'publication_code', 'version_token', 'local_code_token',
                         'scope_token', 'amendment_marker', 'document_marker')}
    signature = '|'.join(structural) or 'no-structural-rule'
    for key, values in tokens.items():
        signature += f';{key}=' + ','.join(v.casefold() for v in values)
    if row['family'] == 'other':
        signature += ';' + ('uuid' if 'uuid' in rules else 'hex' if 'hex-identifier' in rules
                           else 'numeric-basename' if re.fullmatch(r'[0-9]+(?:\.[A-Za-z]+)?', row['filename'])
                           else 'free-name')
    return signature, dict(fields), structural


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    primary = json.loads((args.run/'summary.json').read_text())
    for p, digest in primary['hashes'].items():
        if '/packages/' in p:
            assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest, p
    engine = Engine(); guide = engine.guide
    kinds = [k for k, r in guide['patterns'].items() if r['action'] == 'filename']
    probes = {
        mode: [(k, matcher(guide, k, **options)) for k in kinds]
        for mode, options in (
            ('case', {}), ('separator', {'separators': True}),
            ('padding', {'separators': True, 'numbers': True}),
            ('validation', {'separators': True, 'numbers': True, 'dates': True}),
        )}
    # Constructed controls guard against counting token deletion or invalid dates as formatting.
    assert probe('HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf', engine, guide, probes['case'], 'case')[0]
    assert not probe('HHRG-113-AG00-Wstate-ColbyJ-20130230.pdf', engine, guide, probes['validation'], 'validation')[0]
    assert not probe('HHRG-113-AG00-20130314-SD001.pdf', engine, guide, probes['padding'], 'padding')[0]
    assert not probe('CHRG-106hhrg53880.pdf', engine, guide, probes['padding'], 'padding')[0]
    index = {r['filename']: r for r in pq.read_table(args.run/'comparison.parquet').to_pylist() if not r['b_valid']}
    results = []; counts = Counter(); by_suffix = defaultdict(Counter); groups = {}; failures_count = Counter()
    started = perf_counter()
    with gzip.open(args.run/'paired-outputs.jsonl.gz', 'rt') as stream, gzip.open(args.output/'candidates.jsonl.gz', 'wt') as output:
        for line in stream:
            row = json.loads(line); name = row['filename']
            if name not in index:
                continue
            info = index[name]; signature, fields, structural = shape(row)
            category = ''; candidates = []; errors = []; attempts = []
            if info['suffix_class'] == 'no_extension':
                category = 'no_extension'
            elif info['suffix_class'] != 'pdf_xml':
                category = 'unsupported_extension'
            else:
                for mode in probes:
                    candidates, errors_here = probe(name, engine, guide, probes[mode], mode)
                    errors.extend(errors_here); attempts.append(mode)
                    if candidates:
                        category = {'case': 'case_only', 'separator': 'separator_and_case',
                                    'padding': 'numeric_padding_and_formatting', 'validation': 'relaxed_shape_validated'}[mode]
                        break
                if not category:
                    category = 'validation_failure' if errors else 'unmatched_shape'
            errors_unique = {json.dumps(e, sort_keys=True): e for e in errors}
            errors = list(errors_unique.values())
            failure_codes = sorted({e['code'] for e in errors})
            # Multiple diagnostic conventions or records remain alternatives, never silently ranked away.
            candidate_ambiguous = len(candidates) > 1 or any(c['rendered_ambiguous'] for c in candidates)
            result = {'filename': name, 'family': row['family'], 'suffix_class': info['suffix_class'],
                      'original_issues': info['b_issues'], 'category': category,
                      'shape': signature, 'extractor_rules': structural,
                      'candidate_kinds': sorted({c['kind'] for c in candidates}),
                      'candidate_filenames': [c['rendered'] for c in candidates],
                      'candidate_ambiguous': candidate_ambiguous, 'validation_codes': failure_codes,
                      'extractor_fields_json': json.dumps(fields, ensure_ascii=False)}
            results.append(result)
            output.write(json.dumps({**result, 'attempts': attempts, 'candidates': candidates,
                                     'validation_failures': errors}, ensure_ascii=False)+'\n')
            counts[category] += 1; by_suffix[info['suffix_class']][category] += 1
            failures_count.update(failure_codes)
            key = (category, row['family'], signature)
            group = groups.setdefault(key, {'category': category, 'family': row['family'], 'shape': signature,
                                          'count': 0, 'examples': []})
            group['count'] += 1
            if len(group['examples']) < 3:
                group['examples'].append(name)
            if len(results) % 25000 == 0:
                print(json.dumps({'processed': len(results), 'seconds': round(perf_counter()-started,1), 'counts': counts}), flush=True)
            if perf_counter()-started > 1200:
                raise TimeoutError('20-minute bound; partial candidate log retained')
    assert len(results) == len(index) == 268187
    pq.write_table(pa.Table.from_pylist(results), args.output/'rejections.parquet', compression='zstd')
    grouped = sorted(groups.values(), key=lambda r: (-r['count'], r['category'], r['shape']))
    pq.write_table(pa.Table.from_pylist(grouped), args.output/'shapes.parquet', compression='zstd')
    for p, digest in primary['hashes'].items():
        if '/packages/' in p:
            assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest, p
    summary = {'rejected': len(results), 'counts': counts, 'by_suffix': by_suffix,
               'validation_codes': failures_count, 'ambiguous_diagnostics': sum(r['candidate_ambiguous'] for r in results),
               'shapes': len(grouped), 'elapsed_seconds': perf_counter()-started,
               'source_hashes': {p: d for p, d in primary['hashes'].items() if '/packages/' in p},
               'primary_outputs_sha256': hashlib.sha256((args.run/'paired-outputs.jsonl.gz').read_bytes()).hexdigest(),
               'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'note_sha256': hashlib.sha256(Path(__file__).with_name('filename-engine-comparison.md').read_bytes()).hexdigest(),
               'all_rejections_processed': True}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if not k.endswith('hashes')}, indent=2))


if __name__ == '__main__':
    from house_naming.filenames import registry
    SEARCH_RULES = {r['id'] for r in registry() if r['scope'] == 'search'} | {'extension'}
    main()
