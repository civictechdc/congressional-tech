"""Compare default extraction, optional member references and corpus helpers."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import shutil
from time import perf_counter

from house_naming import Engine
from house_naming.corpus import filename_tokens, shared_token_pattern, residual_fields, DESCRIPTIVE_FIELDS
from congress_api.models.legislators import member_surnames_by_congress
from house_naming.filename_corpus import parser_source_paths
from house_naming.filenames import ParsedFilename, filename_tokens as native_tokens, parse_filename
from congress_api.models.legislators import parse_legislators


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def member_fields(matches):
    return {(f['name'], f['raw'], f['start'], f['end']) for m in matches for f in m['fields']
            if f['name'] in {'member_marker', 'member_surname_token', 'title_token'}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('reference', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    previous = json.loads((args.baseline/'summary.json').read_text())
    native = Path(previous['baseline'])
    for path, digest in previous['hashes'].items():
        if '/congress_api/' in path:
            assert sha(Path(path)) == digest, ('Native comparator changed', path)
    sources = [*parser_source_paths(), Path(__file__), Path(__file__).with_name('house-naming-context-corpus.md'), args.reference]
    hashes = {str(p.resolve()): sha(p) for p in sources}
    for path in sources:
        dst = args.output/'source'/path.resolve().relative_to(Path.cwd())
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
    context = member_surnames_by_congress(parse_legislators(args.reference.read_bytes()))
    (args.output/'member-surnames.json').write_text(json.dumps(context, indent=2)+'\n')
    counts = Counter(); stats = {}; residual_groups = {}; engine = Engine(); started = perf_counter()
    new_member_examples = []
    with (gzip.open(args.baseline/'extractions.jsonl.gz','rt') as baseline,
          gzip.open(native/'paired-outputs.jsonl.gz','rt') as frozen_native,
          gzip.open(args.output/'token-differences.jsonl.gz','wt',compresslevel=1) as differences,
          gzip.open(args.output/'residual-fields.jsonl.gz','wt',compresslevel=1) as residuals,
          gzip.open(args.output/'member-comparison.jsonl.gz','wt',compresslevel=1) as members):
        for old_line, native_line in zip_longest(baseline, frozen_native):
            assert old_line is not None and native_line is not None
            old, a = json.loads(old_line), json.loads(native_line)
            name = old['filename']; assert name == a['filename']
            result = engine.extract(name)
            assert result == old['result'], ('Default extraction changed', name)
            counts['unchanged_default_extractions'] += 1
            tokens = filename_tokens(result)
            old_tokens = [p.model_dump() for p in native_tokens(ParsedFilename.model_validate(a['a']))]
            assert tokens == [t for t in old_tokens if t['start'] < result['stem_end']], name
            if tokens != old_tokens:
                counts['token_inputs_with_transport_or_extension_removed'] += 1
                differences.write(json.dumps({'filename':name,'before':old_tokens,'after':tokens})+'\n')
            else:
                counts['token_inputs_identical_to_native'] += 1
            seen = set()
            for token in tokens:
                assert name[token['start']:token['end']] == token['raw']
                key = token['kind'],token['raw'].casefold()
                row = stats.setdefault(key, {'names':0,'occurrences':0,'variants':set()})
                row['occurrences'] += 1; row['variants'].add(token['raw'])
                if key not in seen: row['names'] += 1; seen.add(key)
            # Re-run both engines with the same context for every BILLS layout,
            # including filenames without Rep wording as negative controls.
            if any(m['rule']=='legislative-file' for m in result['observations']):
                contextual = engine.extract(name, member_surnames=context)
                native_context = parse_filename(name, member_surnames=context).model_dump()
                before, after = member_fields(native_context['matches']), member_fields(contextual['observations'])
                assert before <= after, ('Lost native member fields', name, before-after)
                assert {k:v for k,v in contextual.items() if k!='observations'} == {k:v for k,v in result.items() if k!='observations'}
                assert [m for m in contextual['observations'] if m['rule']!='member-title'] == result['observations']
                counts['member_context_cases_checked'] += 1
                if before or after:
                    counts['member_names_with_fields'] += 1
                    counts['member_fields_identical_to_native'] += before == after
                    counts['additional_member_fields'] += len(after-before)
                    members.write(json.dumps({'filename':name,'native':native_context,'house':contextual})+'\n')
                    new_member_examples.append({'filename':name,'native':sorted(before),'house':sorted(after)})
                result = contextual
            rows = residual_fields(result, field_names=DESCRIPTIVE_FIELDS | {'amendment_token','document_number'}, include_unstructured=True)
            nonempty = []
            for row in rows:
                field = row['field']; start,end = field['start'],field['end']
                source = {i for i in range(start,end) if name[i].isalnum()}
                covered = {i for item in row['covered_by'] for i in range(max(start,item['field']['start']),min(end,item['field']['end'])) if name[i].isalnum()}
                remaining = {i for span in row['residual_spans'] for i in range(span['start'],span['end']) if name[i].isalnum()}
                assert source == covered | remaining and not covered & remaining, (name,row)
                counts['residual_partitions_checked'] += 1
                if row['residual_spans']:
                    nonempty.append(row)
                    shape = ' … '.join(re.sub('[0-9]+','<n>',s['raw'].casefold()) for s in row['residual_spans'])
                    key = row['rule'],field['name'],shape
                    group = residual_groups.setdefault(key, {'fields':0,'examples':[]})
                    group['fields'] += 1
                    if len(group['examples'])<3:group['examples'].append({'filename':name,'spans':row['residual_spans']})
            if nonempty:
                counts['inputs_with_residual_text'] += 1
                residuals.write(json.dumps({'filename':name,'fields':nonempty})+'\n')
            if counts['unchanged_default_extractions'] % 50000 == 0:
                print(json.dumps({'processed':counts['unchanged_default_extractions'],'seconds':round(perf_counter()-started,1)}),flush=True)
            if perf_counter()-started>1800: raise TimeoutError('30-minute bound reached')
    shared = {k:v for k,v in stats.items() if v['names']>=2}
    compiled = {}
    with gzip.open(args.output/'shared-token-patterns.jsonl.gz','wt',compresslevel=1) as out:
        for (kind,key),row in sorted(shared.items()):
            variants = tuple(sorted(row['variants']))
            pattern = shared_token_pattern(variants,kind); regex = re.compile(pattern)
            compiled[kind,key] = regex
            for variant in variants:
                assert regex.fullmatch(variant)
                if kind in {'word','number'}:
                    adjacent = '9' if kind=='number' else 'x'
                    assert not regex.search(adjacent+variant+adjacent)
                counts['token_variant_controls'] += 1
            out.write(json.dumps({'kind':kind,'key':key,'variants':variants,'pattern':pattern,'filenames':row['names'],'occurrences':row['occurrences']})+'\n')
    with gzip.open(args.baseline/'extractions.jsonl.gz','rt') as stream:
        for line in stream:
            saved = json.loads(line); result = saved['result']; name = saved['filename']; expected=defaultdict(list)
            for t in filename_tokens(result):
                key = t['kind'],t['raw'].casefold()
                if key in compiled:expected[key].append((t['start'],t['end'],t['raw']))
            for key,spans in expected.items():
                actual = [(m.start('token'),m.end('token'),m['token']) for m in compiled[key].finditer(name[:result['stem_end']])]
                assert actual==spans,(name,key,actual,spans)
                counts['shared_token_occurrences_checked'] += len(spans)
            counts['inputs_with_shared_token'] += bool(expected)
            counts['token_pairs_checked'] += len(expected)
            if perf_counter()-started>1800:raise TimeoutError('30-minute bound reached')
    groups=[{'rule':k[0],'field':k[1],'shape':k[2],**v} for k,v in sorted(residual_groups.items(),key=lambda item:(-item[1]['fields'],item[0]))]
    with gzip.open(args.output/'residual-patterns.jsonl.gz','wt',compresslevel=1) as out:
        for row in groups:out.write(json.dumps(row)+'\n')
    report={'counts':counts,'shared_patterns':len(shared),'residual_patterns':len(groups),'top_residual_patterns':groups[:50],
            'member_examples':new_member_examples,'baseline':str(args.baseline.resolve()),'hashes':hashes,
            'baseline_output_sha256':sha(args.baseline/'extractions.jsonl.gz'),
            'seconds':perf_counter()-started,'source_drift':[p for p,h in hashes.items() if sha(Path(p))!=h]}
    (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['counts','shared_patterns','residual_patterns','seconds','source_drift']},indent=2))
    assert counts['unchanged_default_extractions']==previous['counts']['inputs'] and not report['source_drift']


if __name__=='__main__':main()
