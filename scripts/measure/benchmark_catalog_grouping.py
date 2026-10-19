"""Measure grouping on a frozen local Parquet sample; never accesses R2.

Run each implementation in its own process and a new output directory.
Use --implementation with a saved catalog_staging.py to compare a baseline.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import resource
import time

import pyarrow.parquet as pq
from congress_api.retention import catalog_staging


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--implementation', type=Path)
    parser.add_argument('--label', default='candidate')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    module = catalog_staging
    if args.implementation:
        spec = importlib.util.spec_from_file_location('benchmark_staging', args.implementation)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    args.output.mkdir(parents=True, exist_ok=False)
    sample = pq.read_table(args.sample)
    if args.limit:
        sample = sample.slice(0, args.limit)
    rows = sample.to_pylist()
    results = []
    for case in ('cold', 'unchanged', 'sparse'):
        output = args.output / case
        output.mkdir()
        state = module.WorkingCatalog(output / 'working.sqlite')
        try:
            current = [dict(row) for row in rows]
            if case == 'sparse':
                for i in range(0, len(current), 100):
                    current[i]['source_document_label'] = [
                        *(current[i].get('source_document_label') or []),
                        'Performance fixture: changed recorded label']
            previous = documents = None
            if case != 'cold':
                previous = pq.ParquetFile(args.output / 'cold/document-filenames.parquet')
                documents = (args.output / 'cold/documents.parquet').read_bytes()
            counts = {'sql': 0}

            def trace(_):
                counts['sql'] += 1

            state.connection.set_trace_callback(trace)
            start = time.monotonic()
            result = module.write_grouped_indexes(
                output / 'document-filenames.parquet', current, sample.schema,
                working=state, previous=previous, previous_documents=documents)
            elapsed = time.monotonic() - start
            state.connection.set_trace_callback(None)
            item = dict(case=case, arm=args.label, rows=len(current), seconds=elapsed,
                        sqlite_bytes=(output / 'working.sqlite').stat().st_size,
                        sql_statements=counts['sql'],
                        peak_rss_native_units=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        reused_groups=result['reused_document_groups'],
                        recomputed_groups=result['recomputed_document_groups'])
            results.append(item)
            print(json.dumps(item), flush=True)
        finally:
            state.close()
    (args.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
