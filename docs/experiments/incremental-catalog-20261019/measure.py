"""Offline catalog dependency counterexample, using the maintained group policy.

This characterizes the existing path; it is neither an incremental implementation
nor a production fallback. All inputs are constructed, with no external reads.
"""
import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention.catalog_staging import WorkingCatalog
from congress_api.retention import catalog_staging, catalog_validation

SCHEMA = pa.schema([*index.SOURCE_SCHEMA, ('capture_outcome', index.STRINGS),
    ('source_document_label', index.STRINGS),
    ('source_occurrences', index.metadata_type('source_occurrences'))])


def source(name, body):
    return dict(body_key=body, filename=name, source_url='https://example.gov/' + name,
                media_type=['application/pdf'], http_status=['200'], capture_outcome=['saved'])


def fixture(unrelated):
    rows = [source('a.pdf', 'body-A'), source('b.pdf', 'body-B'), source('a.pdf', 'body-B')]
    # Exact duplicate nested observations must survive source storage. Canonical
    # document aggregation retains the maintained merge_values deduplication.
    occurrence = {'source_page_url': ['https://committee.test/hearing'],
                  'source_link_label': [], 'source_page_title': None}
    rows[0].update(source_document_label=None, source_occurrences=[occurrence, deepcopy(occurrence)])
    rows[1]['source_document_label'] = []
    rows[2]['source_document_label'] = ['']
    rows += [source(f'unrelated-{i}.pdf', f'unrelated-body-{i}') for i in range(unrelated)]
    return pa.Table.from_pylist(rows, schema=SCHEMA).to_pylist()


def canonical(rows):
    return Counter(json.dumps(row, sort_keys=True, separators=(',', ':')) for row in rows)


class CountedPrevious:
    """Count actual payload batches read by the maintained prior-group path."""
    def __init__(self, path):
        self.file = pq.ParquetFile(path)
        self.schema_arrow = self.file.schema_arrow
        self.rows_read = 0

    def iter_batches(self, **kwargs):
        for batch in self.file.iter_batches(**kwargs):
            self.rows_read += len(batch)
            yield batch

    def close(self):
        self.file.close()


def measure_case(root, *, unrelated):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    before, after = root / 'before', root / 'after'
    before.mkdir()
    after.mkdir()
    rows = fixture(unrelated)
    path = before / 'document-filenames.parquet'
    index.write_document_indexes(path, deepcopy(rows), SCHEMA)
    prior_sources = CountedPrevious(path)
    prior_documents = CountedPrevious(before / 'documents.parquet')
    prior_rows = pq.read_table(path).to_pylist()
    bridge_id = sha256(index.compact([rows[2].get(k) for k in ('body_key', 'filename', 'source_url')]).encode()).hexdigest()
    bridge = next(row for row in prior_rows if row['source_id'] == bridge_id)
    old_members = {row['source_id'] for row in prior_rows if row['document_id'] == bridge['document_id']}
    changed = [row for i, row in enumerate(rows) if i != 2]
    counts = dict(current_source_rows_visited=0, validation_rows_read=0)

    def current_rows():
        for row in deepcopy(changed):
            counts['current_source_rows_visited'] += 1
            yield row

    original_validator = index.validate_document_indexes

    def validate(*args, **kwargs):
        # The maintained validator scans the source_id/document_id columns of
        # every row in both files. Independently count those actual batches.
        with patch.object(pq.ParquetFile, 'iter_batches', counted_validation_batches):
            return original_validator(*args, **kwargs)

    original_batches = pq.ParquetFile.iter_batches

    def counted_validation_batches(file, *args, **kwargs):
        for batch in original_batches(file, *args, **kwargs):
            counts['validation_rows_read'] += len(batch)
            yield batch

    working = WorkingCatalog(after / 'working.sqlite')
    try:
        with patch.object(index, 'validate_document_indexes', validate):
            result = index.write_document_indexes(after / path.name, current_rows(), SCHEMA,
                previous=prior_sources, previous_documents=prior_documents, working=working)
    finally:
        working.close()
        prior_sources.close()
        prior_documents.close()
    expected_sources, source_schema, expected_documents, document_schema = index.prepare_document_indexes(deepcopy(changed), SCHEMA)
    actual_sources = pq.read_table(after / path.name)
    actual_documents = pq.read_table(after / 'documents.parquet')
    # Compare every field, null/list distinction and duplicate row count after
    # normalization only through the schema used by the maintained writer.
    if (actual_sources.schema.remove_metadata() != source_schema.remove_metadata()
            or actual_documents.schema.remove_metadata() != document_schema.remove_metadata()):
        raise AssertionError('Maintained catalog changed reference schema')
    parity = (canonical(actual_sources.to_pylist()) == canonical(pa.Table.from_pylist(expected_sources, schema=actual_sources.schema).to_pylist())
              and canonical(actual_documents.to_pylist()) == canonical(pa.Table.from_pylist(expected_documents, schema=actual_documents.schema).to_pylist()))
    if not parity:
        raise AssertionError('Maintained catalog disagrees with all-field reference')
    remaining = [row for row in actual_sources.to_pylist() if row['source_id'] in old_members]
    receipt = dict(unrelated_rows=unrelated, removed_source_count=1,
        affected_old_group_members=len(old_members), affected_new_group_members=len(remaining),
        affected_new_group_count=len({row['document_id'] for row in remaining}),
        prior_source_rows_read=prior_sources.rows_read, prior_document_rows_read=prior_documents.rows_read,
        **counts, reused_document_groups=result['reused_document_groups'],
        recomputed_document_groups=result['recomputed_document_groups'],
        output_bytes=sum((after / name).stat().st_size for name in (path.name, 'documents.parquet')),
        receipts_read=0, bodies_read=0, classification_calls=0,
        all_field_multiset_parity=parity,
        metric_scope='Grouping and paired-reference validation only; excludes acquisition, raw restoration, native storage, and filesystem I/O.')
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def require_bounded(small, large):
    grows = any(large[key] > small[key] for key in (
        'prior_source_rows_read', 'prior_document_rows_read',
        'current_source_rows_visited', 'validation_rows_read'))
    if grows:
        return dict(status='blocked', reason='unrelated_catalog_rows_scanned',
                    needs=['retained_old_new_dependency_lookup', 'recoverable_native_partition_custody'])
    return dict(status='bounded_in_measured_scope')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-bounded', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = [measure_case(args.output / f'unrelated-{size}', unrelated=size) for size in (10, 1000)]
    source_files = (Path(__file__).resolve(), Path(index.__file__),
                    Path(catalog_staging.__file__), Path(catalog_validation.__file__))
    summary = dict(source_sha256={str(path): sha256(path.read_bytes()).hexdigest() for path in source_files},
                   revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                   cases=cases, acceptance=require_bounded(*cases), production_adoption=False)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.require_bounded and summary['acceptance']['status'] == 'blocked':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
