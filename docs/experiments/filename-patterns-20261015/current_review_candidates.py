"""Bind local review candidates to complete current rows without changing a catalog."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import resource
import sys
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from catalog_alias_review import eligible_body
from catalog_content_review import load_reviews, read_ledger
from catalog_filename_replay import implementation_manifest, implementation_identity, normalized
from catalog_review_evidence import row_digest, verified
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.document_index import validate_document_indexes
from packet_review_candidate import bind_review, apply_review
from pilot_reconcile import file_digest


def extract_groups(source, target, ids, identity, *, batch_size=64):
    """Save exact full rows; only matching rows become Python values for verification."""
    target = Path(target)
    if target.exists(): raise FileExistsError(target)
    if not ids or batch_size < 1: raise ValueError('Require selected IDs and a positive batch size')
    file = pq.ParquetFile(source)
    wanted = pa.array(sorted(ids), type=pa.string())
    groups = []
    for group in range(file.num_row_groups):
        column = file.read_row_group(group, columns=['document_id'])['document_id']
        if pc.any(pc.is_in(column, value_set=wanted)).as_py(): groups.append(group)
    expected = {}
    with pq.ParquetWriter(target, file.schema_arrow) as writer:
        for batch in file.iter_batches(row_groups=groups, batch_size=batch_size, use_threads=False):
            selected = batch.filter(pc.is_in(batch['document_id'], value_set=wanted))
            if not selected.num_rows: continue
            for row in selected.to_pylist():
                key = row[identity]
                if not key or key in expected: raise ValueError('Missing or duplicate selected identity')
                # Include null values here: extraction must preserve them too.
                expected[key] = row_digest(row)
            writer.write_batch(selected)
    saved = pq.ParquetFile(target)
    if not saved.schema_arrow.equals(file.schema_arrow, check_metadata=True):
        raise ValueError('Extraction changed the full schema')
    actual = {}
    for batch in saved.iter_batches(batch_size=batch_size, use_threads=False):
        for row in batch.to_pylist():
            key = row[identity]
            if key in actual: raise ValueError('Duplicate saved identity')
            actual[key] = row_digest(row)
    if actual != expected: raise ValueError('Extraction changed complete rows')
    return dict(rows=len(actual), selected_row_groups=len(groups), total_row_groups=file.num_row_groups,
                full_rows_sha256=row_digest(sorted(actual.items())), sha256=file_digest(target),
                schema_and_all_values_preserved=True)


def compact_rows(path, identity):
    """Discard only null dictionary padding after exact Parquet readback is verified."""
    rows = {}
    for batch in pq.ParquetFile(path).iter_batches(batch_size=32, use_threads=False):
        for row in batch.to_pylist():
            key = row[identity]
            if not key or key in rows: raise ValueError('Missing or duplicate compact identity')
            rows[key] = normalized(row)
    return rows


def select_candidates(proposals, originals, documents, sources, reviews):
    """Use existing selection only after exact evidence and eligibility validation."""
    if set(proposals) != set(originals) or set(proposals) != set(documents) or set(proposals) != set(reviews):
        raise ValueError('Candidate inputs must cover exactly the same groups')
    members = defaultdict(list)
    for row in sources.values(): members[row['document_id']].append(row)
    if set(members) != set(documents): raise ValueError('Incomplete extracted groups')
    results = {}
    for key in sorted(documents):
        document, group = documents[key], members[key]
        if document.get('record_role') != ['document']:
            raise ValueError('Reviewed current group is not a document')
        bodies = {b for row in group if (b := eligible_body(row))}
        if bodies != {reviews[key]['observation']['body_key']}:
            raise ValueError('Current group no longer has exactly the reviewed body')
        if set(document.get('body_keys') or []) != {r['body_key'] for r in group if r.get('body_key')}:
            raise ValueError('Current group body union differs from members')
        review = bind_review(proposals[key], originals[key], document, group, reviews[key])
        result = apply_review(document, group, review)
        if result['status'] not in {'candidate_applied', 'annotation_only_unsupported_forms'}:
            raise ValueError('Candidate binding did not apply')
        if apply_review(document, group)['document'] != document:
            raise ValueError('Withdrawal did not restore baseline')
        results[key] = result
    return results


def run(reconciliation_checkpoint, palmer_checkpoint, catalog_root, output):
    started = time.monotonic(); output = Path(output)
    if output.exists(): raise FileExistsError(output)
    implementation = implementation_manifest()
    bindings = {str(p):file_digest(p) for p in [reconciliation_checkpoint, palmer_checkpoint]}
    cp = json.loads(Path(reconciliation_checkpoint).read_text())
    summary = json.loads(verified(cp['summary_path'], cp['summary_sha256'], bindings).read_text())
    for path, digest in summary['bindings'].items(): verified(path, digest, bindings)
    directory = Path(cp['summary_path']).parent
    for path, digest in summary['outputs'].items(): verified(directory/path, digest, bindings)
    cases = list(read_ledger(directory/'reconciliation.jsonl').values())
    matched = {r['document_id'] for r in cases if r['matching_body_and_source_identity']}
    palmer = json.loads(Path(palmer_checkpoint).read_text())
    receipt_path = verified(palmer['receipt_path'], palmer['receipt_sha256'], bindings)
    receipt = json.loads(receipt_path.read_text())
    reviews = load_reviews(receipt_path, palmer['receipt_sha256'], bindings)
    added = {r['document_id'] for r in receipt['records']}
    if added & matched or set(reviews) != matched | added:
        raise ValueError('Current review chain does not match reconciled and added groups')
    spec_paths = [p for p in summary['bindings'] if Path(p).name == 'content_disposition_proposals_v1.json']
    if len(spec_paths) != 1: raise ValueError('Require one bound historical proposal input')
    spec = json.loads(Path(spec_paths[0]).read_text())
    proposals = {p['document_id']:p for p in spec['records'] if p['document_id'] in matched}
    historical = read_ledger(verified(spec['original_ledger'], spec['original_ledger_sha256'], bindings))
    originals = {key:historical[key] for key in matched}
    current = read_ledger(verified(receipt['input_ledger'], receipt['input_ledger_sha256'], bindings))
    for key in added:
        observation = reviews[key]['observation']
        if len(observation['observed_document_forms']) != 1:
            raise ValueError('New composite requires an explicit primary/component proposal')
        originals[key] = current[key]
        proposals[key] = dict(document_id=key, source_row_sha256=reviews[key]['source_row_sha256'],
            proposed_primary_forms=observation['observed_document_forms'], proposed_component_forms=[],
            status='assistant_proposal', handling='body_form', independent_reference=False, release_approved=False,
            evidence={**{k:observation[k] for k in ['body_key','sha256','pages']},
                      **{k:reviews[key][k] for k in ['receipt','receipt_sha256']}})
    paths = local_catalog_paths(catalog_root)
    # A caller cannot substitute another valid pair from a different generation.
    for path in [Path(catalog_root)/'indexes/catalog.json', *paths]:
        if str(path) not in bindings: raise ValueError('Catalog path absent from current evidence')
        verified(path, bindings[str(path)], bindings)
    output.mkdir(parents=True)
    extracted = {}
    for label, path, identity, name in [('sources',paths[0],'source_id','document-filenames.parquet'),
                                       ('documents',paths[1],'document_id','documents.parquet')]:
        extracted[label] = extract_groups(path, output/name, set(reviews), identity)
    validate_document_indexes(output/'document-filenames.parquet', output/'documents.parquet')
    sources = compact_rows(output/'document-filenames.parquet', 'source_id')
    documents = compact_rows(output/'documents.parquet', 'document_id')
    before = row_digest(dict(sources=sources, documents=documents))
    results = select_candidates(proposals, originals, documents, sources, reviews)
    if row_digest(dict(sources=sources, documents=documents)) != before:
        raise ValueError('Candidate selection mutated baseline evidence')
    for path, digest in bindings.items(): verified(path, digest, {})
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during current selection')
    (output/'implementation.json').write_text(json.dumps(implementation, indent=2)+'\n')
    (output/'proposals.json').write_text(json.dumps(dict(records=list(proposals.values()),
        historical_cases_unchanged=True, classification_mutations=False), indent=2)+'\n')
    with (output/'candidates.jsonl').open('x') as stream:
        for result in results.values(): stream.write(json.dumps(result,ensure_ascii=False)+'\n')
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = dict(current_groups=len(results), source_rows=len(sources), extracted=extracted,
        case_status=dict(Counter(r['status'] for r in results.values())),
        changed_kind_sets=sum(set(r['document'].get('document_kind') or []) != set(documents[k].get('document_kind') or []) for k,r in results.items()),
        fresh_group_digests={key:r['baseline_group_sha256'] for key,r in results.items()},
        baseline_preserved=True, withdrawal_restores_baseline=True, bindings=bindings,
        outputs={name:file_digest(output/name) for name in ['implementation.json','proposals.json','candidates.jsonl','document-filenames.parquet','documents.parquet']},
        elapsed_seconds=round(time.monotonic()-started,3),
        peak_process_rss_bytes=peak if sys.platform=='darwin' else peak*1024,
        production_selected=False, independent_reference=False, release_approved=False,
        scope='Local candidates on complete selected current rows. Full raw input hashes bind every excluded control; no catalog file is modified. This is not a full-catalog refresh or production qualification.')
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['reconciliation-checkpoint','palmer-checkpoint','catalog-root','output']:
        parser.add_argument('--'+name,type=Path,required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in ['bindings','outputs','fresh_group_digests']},indent=2))
