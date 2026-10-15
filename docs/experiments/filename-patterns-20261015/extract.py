"""Freeze the public selection and extract a read-only analysis population."""
from collections import Counter
from datetime import datetime, timezone
from hashlib import file_digest
import importlib.util
import json
from pathlib import Path
import sys
import urllib.request

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'output/viewer-sync-20261015/source'
WORK = Path('/Users/mikewolfd/.codex/worktrees/viewer-retained-sync/congressional-tech')
sys.path.insert(0, str(WORK / 'packages/congress_api/src'))
from congress_api.retention.catalog_publication import local_catalog_paths
from congress_api.retention.saved_responses import saved_response, FIELDS


def save(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    out = ROOT / 'output/filename-patterns-20261015'
    out.mkdir(exist_ok=True)
    assert not (out / 'documents.parquet').exists(), 'Do not overwrite a frozen input'
    spec = importlib.util.spec_from_file_location('viewer', WORK / 'docs/youtube-coverage/research/scripts/view_document_filenames.py')
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    manifest = json.loads((SOURCE / 'indexes/catalog.json').read_text())
    pointer = json.loads((HERE / 'public-pointer.json').read_text())
    assert manifest == pointer['source_manifest']
    filenames, documents = local_catalog_paths(SOURCE)
    print('Verified both source file hashes and catalog IDs', flush=True)
    columns = ['document_id', 'source_id', 'filename', 'filenames', 'source_url', 'source_urls',
               'document_kind', 'document_kind_source', 'record_role', 'format', 'body_keys',
               'source_committee_name', 'source_link_label', 'source_link_heading',
               'source_page_title', 'source_original_page_url', 'source_document_type',
               'source_document_type_basis', 'source_occurrences', 'recovered_filename',
               'date_token', 'short_date_token', 'date_range_token', 'opaque_uuid', 'opaque_hex',
               'name_token', 'descriptor', 'suffix', 'congress', 'source_congress']
    counts = Counter()
    roles = Counter()
    selected_ids = set()
    writer = None
    for batch in pq.ParquetFile(documents).iter_batches(batch_size=8192, columns=columns):
        table = pa.Table.from_batches([batch])
        counts['all_catalog_documents'] += len(table)
        null = table.filter(pc.equal(pc.fill_null(pc.list_value_length(table['document_kind']), 0), 0))
        counts['null_kind_all_roles'] += len(null)
        kept = []
        for r in null.to_pylist():
            roles['|'.join(r['record_role'] or [])] += 1
            if r['record_role'] != ['document']:
                counts['excluded_non_document_role'] += 1
                continue
            urls = r['source_urls'] or ([r['source_url']] if r['source_url'] else [])
            if urls and all(viewer.api_reference(u) for u in urls):
                counts['excluded_api_reference'] += 1
                continue
            if urls and all(viewer.video_reference(u) for u in urls):
                counts['excluded_youtube_reference'] += 1
                continue
            counts['unclassified_documents'] += 1
            if not r['filename']:
                counts['missing_filename'] += 1
                continue
            selected_ids.add(r['document_id'])
            kept.append(r)
        if kept:
            part = pa.Table.from_pylist(kept, schema=table.schema)
            if writer is None:
                writer = pq.ParquetWriter(out / 'documents.parquet', table.schema, compression='zstd')
            writer.write_table(part)
    writer.close()
    counts['named_unclassified_documents'] = len(selected_ids)
    print(dict(counts), flush=True)
    # A saved alias counts even when the preferred alias failed, matching the viewer.
    saved_ids = set()
    source_counts = Counter()
    schema = pq.ParquetFile(filenames).schema_arrow
    minimal = list(dict.fromkeys(['document_id', *FIELDS]))
    for batch in pq.ParquetFile(filenames).iter_batches(batch_size=16384, columns=minimal):
        table = pa.Table.from_batches([batch])
        table = table.filter(pc.is_in(table['document_id'], value_set=pa.array(sorted(selected_ids))))
        for r in table.to_pylist():
            source_counts[r['document_id']] += 1
            if saved_response(r):
                saved_ids.add(r['document_id'])
    (out / 'source-status.json').write_text(json.dumps({k: {'saved': k in saved_ids, 'source_count': v} for k, v in sorted(source_counts.items())}))
    counts['named_with_usable_saved_alias'] = len(saved_ids)
    assert counts['null_kind_all_roles'] == counts['excluded_non_document_role'] + counts['excluded_api_reference'] + counts['excluded_youtube_reference'] + counts['unclassified_documents']
    assert counts['unclassified_documents'] == counts['missing_filename'] + counts['named_unclassified_documents']
    save('input-manifest.json', {'checked_at': datetime.now(timezone.utc).isoformat(),
        'catalog_id': manifest['catalog_id'], 'source_root': str(SOURCE), 'source_manifest': manifest,
        'counts': dict(counts), 'null_kind_roles': dict(roles),
        'selection': 'Viewer document roles, excluding API-only and YouTube-only groups; no kind; nonempty preferred filename. All formats and saved states included.',
        'input_sha256': file_digest((out / 'documents.parquet').open('rb'), 'sha256').hexdigest(),
        'population_file': str(out / 'documents.parquet'),
        'prior_network_error': 'Generic urllib User-Agent returned HTTP 403; retry using the maintained publisher User-Agent succeeded.'})
    print('Frozen population and saved-alias status complete', flush=True)


if __name__ == '__main__':
    main()
