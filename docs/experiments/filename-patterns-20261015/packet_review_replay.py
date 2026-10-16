"""Exercise packet-review candidates after existing grouping, cache and refresh paths."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention.catalog_staging import WorkingCatalog
from catalog_content_review import load_reviews, read_ledger
from catalog_filename_replay import implementation_manifest, implementation_identity, normalized, refused_body
from catalog_review_evidence import row_digest, verified
from packet_review_candidate import apply_review, bind_review
from pilot_reconcile import file_digest


def keyed(rows, field):
    result = {r[field]: r for r in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate replay identity')
    return result


def semantic(rows, field):
    # Hash one complete row at a time. A whole-catalog normalized copy expands
    # large repeated occurrence structures without adding comparison evidence.
    return row_digest([(key, row_digest(normalized(row))) for key, row in sorted(keyed(rows, field).items())])


def evaluate(source_rows, documents, reviews):
    members = defaultdict(list)
    for row in source_rows:
        members[row['document_id']].append(row)
    # Controls are covered by the complete baseline semantic hashes. Do not
    # build redundant candidate copies of their potentially huge nested values.
    results = {row['document_id']: apply_review(row, members[row['document_id']], reviews[row['document_id']])
               for row in documents if reviews.get(row['document_id']) is not None}
    if any(r['status'] == 'scope_changed' for r in results.values()):
        raise ValueError('Replay changed a reviewed group')
    return results


def read_pair(directory):
    return (pq.read_table(directory / 'document-filenames.parquet').to_pylist(),
            pq.read_table(directory / 'documents.parquet').to_pylist())


def exercise_paths(source_file, document_file, baseline_sources, output, verify, *, reader=read_pair):
    """Run the same six maintained grouping/refresh paths for any bound cohort."""
    ref_sources, _, ref_docs, _ = index.prepare_document_indexes(deepcopy(baseline_sources), source_file.schema_arrow)
    verify('reference_grouper', ref_sources, ref_docs)
    reverse_sources, _, reverse_docs, _ = index.prepare_document_indexes(
        deepcopy(list(reversed(baseline_sources))), source_file.schema_arrow)
    verify('reference_reversed_alias_order', reverse_sources, reverse_docs)
    disk = output / 'disk'; disk.mkdir()
    stats = index.write_document_indexes(disk / 'document-filenames.parquet', deepcopy(baseline_sources), source_file.schema_arrow)
    verify('disk_grouper', *reader(disk), stats)
    reused = output / 'reused'; reused.mkdir()
    stats = index.write_document_indexes(reused / 'document-filenames.parquet', deepcopy(baseline_sources), source_file.schema_arrow,
        previous=pq.ParquetFile(disk / 'document-filenames.parquet'), previous_documents=pq.ParquetFile(disk / 'documents.parquet'))
    if stats['reused_document_groups'] != document_file.metadata.num_rows:
        raise ValueError('Cache scenario did not reuse every unchanged group')
    verify('cached_disk_groups', *reader(reused), stats)
    for reuse in [True, False]:
        refreshed = output / ('refresh_reuse' if reuse else 'refresh_reparse')
        (refreshed / 'indexes').mkdir(parents=True)
        inputs, metadata = index.filename_refresh_inputs(source_file)
        working = WorkingCatalog(refreshed / 'working.sqlite')
        try:
            stats = index.write_filename_metadata(refreshed, inputs, workers=1, previous=source_file,
                previous_documents=document_file, metadata=metadata, read_body=refused_body,
                reuse_results=reuse, inspect_bodies=False, working=working, output_root=refreshed)
        finally:
            working.close()
        verify('metadata_refresh_' + ('reuse' if reuse else 'reparse'), *reader(refreshed / 'indexes'), stats)


def run(proposals, original_ledger, receipt, comparison_checkpoint, sources, documents, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    bindings = {str(comparison_checkpoint): file_digest(comparison_checkpoint)}
    cp = json.loads(Path(comparison_checkpoint).read_text())
    summary_path = verified(cp['summary_path'], cp['summary_sha256'], bindings)
    comparison = json.loads(summary_path.read_text())
    for path, digest in comparison['bindings'].items():
        verified(path, digest, bindings)
    for path in [proposals, original_ledger, receipt, sources, documents]:
        verified(path, comparison['bindings'][str(path)], bindings)
    implementation = implementation_manifest()
    spec = json.loads(Path(proposals).read_text())
    originals = read_ledger(original_ledger)
    observations = load_reviews(receipt, file_digest(receipt), bindings)
    source_file, document_file = pq.ParquetFile(sources), pq.ParquetFile(documents)
    baseline_sources, baseline_documents = source_file.read().to_pylist(), document_file.read().to_pylist()
    baseline_by_id = keyed(baseline_documents, 'document_id')
    members = defaultdict(list)
    for row in baseline_sources:
        members[row['document_id']].append(row)
    if set(members) != set(baseline_by_id):
        raise ValueError('Incomplete baseline pair')
    review_inputs = {}
    for proposal in spec['records']:
        key = proposal['document_id']
        review_inputs[key] = bind_review(proposal, originals[key], baseline_by_id[key],
                                        members[key], observations.get(key))
    if len(review_inputs) != len(spec['records']) or set(review_inputs) != {
            key for key, row in originals.items() if row['review_basis'] == 'needs_review'}:
        raise ValueError('Missing or duplicate proposed case')
    reference_results = evaluate(baseline_sources, baseline_documents, review_inputs)
    expected = {key: normalized(value) for key, value in reference_results.items()}
    baseline_hashes = [semantic(baseline_sources, 'source_id'), semantic(baseline_documents, 'document_id')]
    output.mkdir(parents=True)
    (output / 'implementation.json').write_text(json.dumps(implementation, indent=2) + '\n')
    scenarios = {}

    def verify(name, source_rows, document_rows, stats=None):
        hashes = [semantic(source_rows, 'source_id'), semantic(document_rows, 'document_id')]
        if hashes != baseline_hashes:
            raise ValueError('Baseline semantics changed: ' + name)
        actual = evaluate(source_rows, document_rows, review_inputs)
        if {key: normalized(value) for key, value in actual.items()} != expected:
            raise ValueError('Candidate selection differs: ' + name)
        grouped_sources = defaultdict(list)
        for row in source_rows:
            grouped_sources[row['document_id']].append(row)
        for row in document_rows:
            if review_inputs.get(row['document_id']) is not None:
                withdrawn = apply_review(row, grouped_sources[row['document_id']])
                if withdrawn['status'] != 'no_review' or withdrawn['document'] != row:
                    raise ValueError('Withdrawal does not restore baseline: ' + name)
        scenarios[name] = dict(source_rows=len(source_rows), documents=len(document_rows),
                               baseline_semantics_unchanged=True, candidates_identical=True,
                               withdrawal_restores_baseline=True, stats=stats)

    verify('saved_baseline', baseline_sources, baseline_documents)
    exercise_paths(source_file, document_file, baseline_sources, output, verify)
    if implementation_identity(implementation_manifest()) != implementation_identity(implementation):
        raise ValueError('Implementation changed during replay')
    for path, digest in bindings.items():
        verified(path, digest, {})
    cases = {p['document_id'] for p in spec['records']}
    with (output / 'candidates.jsonl').open('x') as stream:
        for key in sorted(cases):
            result = reference_results.get(key) or dict(status='no_review', document_id=key,
                baseline_document_sha256=row_digest(normalized(baseline_by_id[key])),
                production_selected=False, independent_reference=False, release_approved=False)
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
    result = dict(source_rows=len(baseline_sources), documents=len(baseline_documents), reviewed_cases=len(cases),
        case_status=dict(Counter(reference_results[k]['status'] if k in reference_results else 'no_review' for k in cases)),
        unaffected_controls=len(baseline_documents)-len(cases), scenarios=scenarios,
        baseline_source_semantic_sha256=baseline_hashes[0], baseline_document_semantic_sha256=baseline_hashes[1],
        bindings=bindings, outputs={name: file_digest(output / name) for name in ['candidates.jsonl', 'implementation.json']},
        production_changes=False, independent_reference=False, release_approved=False,
        scope='Local post-grouping candidate experiment on the saved historical cohort; no production ingestion or fresh-catalog qualification.')
    (output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['proposals', 'original-ledger', 'receipt', 'comparison-checkpoint', 'sources', 'documents', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in result.items() if k not in ['bindings', 'outputs', 'scenarios']}, indent=2))
