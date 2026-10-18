"""Construct frozen shared-URL inputs; use benchmark_core_rebuild.py to measure."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention.raw_archive import CAPTURE_SCHEMA
from congress_api.retention.catalog_publication import local_catalog_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'indexes').mkdir()
    rows = []
    for url_number in range(32):
        url = f'https://committee.example.test/shared-{url_number}.pdf'
        for source_number in range(16):
            occurrences = []
            for number in range(source_number * 4, (source_number + 1) * 4):
                occurrences.append({
                    'source_page_url': [f'https://committee.example.test/hearing/{url_number}/{number}'],
                    'source_original_page_url': [f'https://committee.example.test/hearing/{url_number}/{number}'],
                    'source_page_title': [f'Hearing {url_number}, publisher title {number}'],
                    'source_page_sha256': [sha256(f'{url_number}/{number}'.encode()).hexdigest()],
                    'source_link_url': [url],
                    'source_link_label': [f'Publisher document label {number}'],
                    'source_document_type': ['Support Document'],
                    'source_document_type_basis': ['publisher'],
                    'source_receipt_key': [f'receipts/source-{url_number}.jsonl.gz'],
                    'source_receipt_line': [str(number + 1)],
                    'source_occurrence_scope': ['anchor'],
                })
            filters = {}
            for occurrence in occurrences:
                index.merge_context(filters, occurrence)
            rows.append({
                'body_key': None,
                'filename': f'source-{url_number}-{source_number}.pdf',
                'source_url': url,
                **{field: sorted(values) for field, values in filters.items()},
                'source_occurrences': occurrences,
            })
    index.write_filename_metadata(args.output, rows, workers=1)
    filenames, documents = local_catalog_paths(args.output)
    # Legacy paired inputs intentionally have no capture checkpoint, so each
    # timed rebuild restores all retained context instead of returning unchanged.
    for source, name in ((filenames, 'document-filenames.parquet'), (documents, 'documents.parquet')):
        target = args.output / 'indexes' / name
        if source != target:
            target.write_bytes(source.read_bytes())
    selector = args.output / 'indexes/catalog.json'
    if selector.exists():
        selector.unlink()
    pq.write_table(pa.Table.from_pylist([], schema=CAPTURE_SCHEMA), args.output / 'indexes/captures.parquet')
    files = {str(path.relative_to(args.output)): {'bytes': path.stat().st_size,
             'sha256': sha256(path.read_bytes()).hexdigest()}
             for path in sorted((args.output / 'indexes').glob('*')) if path.is_file()}
    (args.output / 'fixture.json').write_text(json.dumps({
        'kind': 'constructed-high-fanout', 'urls': 32, 'source_rows_per_url': 16,
        'occurrences_per_url': 64, 'source_rows': len(rows), 'files': files,
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
