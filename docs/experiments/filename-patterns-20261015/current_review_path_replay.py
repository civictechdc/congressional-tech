"""Replay current groups without silently rebinding reviews after metadata changes."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import resource
import sys
import time

import pyarrow.parquet as pq

from catalog_filename_replay import implementation_manifest, implementation_identity, normalized
from catalog_review_evidence import verified
from current_review_candidates import compact_rows
from packet_review_candidate import apply_review
from packet_review_replay import exercise_paths, keyed, semantic
from pilot_reconcile import file_digest


def changes(before, after, identity):
    """Retain exact changed values, added IDs and missing IDs for review."""
    left = {k:normalized(v) for k,v in keyed(before, identity).items()}
    right = {k:normalized(v) for k,v in keyed(after, identity).items()}
    fields = {}
    for key in sorted(left.keys() & right.keys()):
        changed = {f:dict(before=left[key].get(f), after=right[key].get(f))
                   for f in sorted(left[key].keys() | right[key].keys()) if left[key].get(f) != right[key].get(f)}
        if changed: fields[key] = changed
    return dict(added_ids=sorted(right.keys()-left.keys()), missing_ids=sorted(left.keys()-right.keys()), fields=fields)


def audit_scenario(sources, documents, baseline_sources, baseline_documents, candidates):
    source_changes = changes(baseline_sources, sources, 'source_id')
    document_changes = changes(baseline_documents, documents, 'document_id')
    groups = defaultdict(list)
    for row in sources: groups[row['document_id']].append(row)
    docs = keyed(documents, 'document_id')
    results, mismatches = {}, []
    for key, candidate in candidates.items():
        if key not in docs:
            results[key] = 'missing_document'; mismatches.append(key); continue
        actual = apply_review(docs[key], groups[key], candidate['review'])
        results[key] = actual['status']
        if normalized(actual) != normalized(candidate): mismatches.append(key)
        withdrawn = apply_review(docs[key], groups[key])
        if withdrawn['status'] != 'no_review' or withdrawn['document'] != docs[key]:
            raise ValueError('Withdrawal changed a current baseline')
    unchanged = not any(v for diff in [source_changes, document_changes] for v in diff.values())
    return dict(source_rows=len(sources), documents=len(documents),
        baseline_semantics_unchanged=unchanged, candidates_identical=not mismatches,
        candidate_mismatches=sorted(mismatches), candidate_status=dict(Counter(results.values())),
        source_changes=source_changes, document_changes=document_changes,
        withdrawal_restores_present_baselines=True,
        source_semantic_sha256=semantic(sources,'source_id'), document_semantic_sha256=semantic(documents,'document_id'))


def compact_pair(directory):
    return (list(compact_rows(directory/'document-filenames.parquet','source_id').values()),
            list(compact_rows(directory/'documents.parquet','document_id').values()))


def run(checkpoint, output):
    started=time.monotonic();output=Path(output)
    if output.exists(): raise FileExistsError(output)
    implementation=implementation_manifest()
    bindings={str(checkpoint):file_digest(checkpoint)}
    cp=json.loads(Path(checkpoint).read_text())
    summary_path=verified(cp['summary_path'],cp['summary_sha256'],bindings)
    prior=json.loads(summary_path.read_text());directory=summary_path.parent
    for path,digest in prior['bindings'].items():verified(path,digest,bindings)
    for name,digest in prior['outputs'].items():verified(directory/name,digest,bindings)
    sources,documents=compact_pair(directory)
    rows=[json.loads(line) for line in (directory/'candidates.jsonl').read_text().splitlines()]
    candidates={r['document']['document_id']:r for r in rows}
    if len(candidates)!=len(rows) or set(candidates)!=set(keyed(documents,'document_id')):
        raise ValueError('Candidate coverage differs from current groups')
    baseline=audit_scenario(sources,documents,sources,documents,candidates)
    if not baseline['baseline_semantics_unchanged'] or not baseline['candidates_identical']:
        raise ValueError('Saved candidates do not match current baseline')
    output.mkdir(parents=True)
    (output/'implementation.json').write_text(json.dumps(implementation,indent=2)+'\n')
    scenarios={'saved_baseline':baseline}
    def verify(name, current_sources, current_documents, stats=None):
        result=audit_scenario(current_sources,current_documents,sources,documents,candidates)
        result['stats']=stats;scenarios[name]=result
        (output/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    exercise_paths(pq.ParquetFile(directory/'document-filenames.parquet'),
        pq.ParquetFile(directory/'documents.parquet'),sources,output,verify,reader=compact_pair)
    for path,digest in bindings.items():verified(path,digest,{})
    if implementation_identity(implementation_manifest())!=implementation_identity(implementation):
        raise ValueError('Implementation changed during current path replay')
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result=dict(current_groups=len(documents),source_rows=len(sources),
        scenarios={name:{k:v for k,v in r.items() if k not in ['source_changes','document_changes']} for name,r in scenarios.items()},
        all_baselines_unchanged=all(r['baseline_semantics_unchanged'] for r in scenarios.values()),
        all_candidates_identical=all(r['candidates_identical'] for r in scenarios.values()),
        bindings=bindings,outputs={str(p.relative_to(output)):file_digest(p) for p in output.rglob('*') if p.is_file()},
        elapsed_seconds=round(time.monotonic()-started,3),peak_process_rss_bytes=peak if sys.platform=='darwin' else peak*1024,
        review_rebinding=False,production_changes=False,independent_reference=False,release_approved=False,
        scope='Seven local scenarios on complete selected current groups; changed bindings remain rejected. Not full-catalog refresh qualification.')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    result=run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings','outputs']},indent=2))
