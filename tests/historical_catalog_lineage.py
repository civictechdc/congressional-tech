"""Historical fixture: replay discovery evidence without reinterpreting filenames or regrouping files.

The existing pair supplies the parsed legacy publisher records. Recurring
download receipts supply discovery observations that older builders omitted.
Only source-context columns change; Arrow equality checks every other value.
"""
from uuid import uuid4
from functools import lru_cache

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.retention import document_index as index
from congress_api.retention import raw_progress as progress


def replay_discovery(context, captures, read):
    selected = captures.filter(pc.fill_null(pc.match_substring(captures['receipt_key'], '/download-'), False))
    report = {'capture_rows_replayed': len(selected), 'receipt_records_replayed': 0,
              'discovery_observations_replayed': 0}
    for record, _, receipt in index.retained_records(selected, read, stage='restore_source_lineage'):
        report['receipt_records_replayed'] += 1
        if not isinstance(record, dict):
            continue
        for link in [*(record.get('source_context') or {}).get('observations', []), *record.get('links', [])]:
            context.add_link(link, receipt)
            report['discovery_observations_replayed'] += 1
        context.add_redirect(record, receipt)
        context.add_associations(record, receipt)
    return report


def has_parent(row):
    """A paired parent/link observation, including qualified candidate evidence."""
    return any((o.get('source_original_page_url') or o.get('source_page_url'))
               and o.get('source_link_url') for o in row.get('source_occurrences') or [])


def refresh_lineage_pair(previous, documents, captures, read, *, root, working, version):
    """Produce a complete pair locally; the caller owns conditional publication."""
    context = index.DocumentSources(working=working)
    restored = 0
    for batch in previous.iter_batches(columns=['source_url', 'source_occurrences'], batch_size=2048):
        for row in batch.to_pylist():
            context.add_url(row['source_url'], {'source_occurrences': [
                o for o in row.get('source_occurrences') or []
                if o.get('source_occurrence_scope') not in (['capture'], ['association'])]})
            for occurrence in row.get('source_occurrences') or []:
                context.restore_association(row['source_url'], occurrence)
        restored += len(batch)
        progress.report('restore_lineage_graph', completed=restored,
                        total=previous.metadata.num_rows, unit='source_rows')
    report = replay_discovery(context, captures, read)
    # Meeting records can enrich links that arrived before their parent record.
    meetings = captures.filter(pc.equal(captures['family'], 'congress/meetings'))
    for record, _, receipt in index.retained_records(meetings, read, stage='restore_lineage_meetings'):
        context.add_meeting(record, receipt)
    context.refresh_meeting_context()
    # Alias rows often repeat a URL. The graph is now fixed, so reuse its read.
    lookup = lru_cache(maxsize=128)(context.for_url)
    additions = working.mapping('lineage_document_additions')
    catalog_id = uuid4().hex
    report.update(rows=previous.metadata.num_rows, document_rows=documents.metadata.num_rows,
                  sources_changed=0, documents_changed=0, sources_with_parent_before=0,
                  sources_with_parent_after=0, all_non_lineage_values_preserved=True)
    for label, source, filename in [('sources', previous, 'document-filenames.parquet'),
                                    ('documents', documents, 'documents.parquet')]:
        fields = [f.name for f in source.schema_arrow if f.name in index.SOURCE_CONTEXT_FIELDS]
        protected = [f for f in source.schema_arrow.names if f not in fields]
        metadata = dict(source.schema_arrow.metadata or {})
        metadata.pop(b'source_lineage_overlay', None)
        metadata.update({b'catalog_id': catalog_id.encode(), b'source_lineage_version': version.encode()})
        schema = source.schema_arrow.with_metadata(metadata)
        count = 0
        with pq.ParquetWriter(root / 'indexes' / filename, schema, compression='zstd') as writer:
            for batch in source.iter_batches(batch_size=2048):
                table = pa.Table.from_batches([batch])
                # Decode only evidence columns. All filename, recovery, grouping,
                # availability and response columns remain the original arrays.
                rows = table.select(fields).to_pylist()
                ids = table['document_id'].to_pylist()
                incoming = ([lookup(url) for url in table['source_url'].to_pylist()]
                            if label == 'sources' else [additions.get(id, {}) for id in ids])
                for row, id, values in zip(rows, ids, incoming):
                    if label == 'sources':
                        report['sources_with_parent_before'] += has_parent(row)
                    changed = {}
                    for field, items in values.items():
                        if field not in fields or not items:
                            continue
                        merged = index.merge_values(field, row.get(field), items)
                        # Arrow expands absent struct members to null. Compare
                        # normalized observations, not that storage padding.
                        if merged != index.merge_values(field, row.get(field)):
                            row[field] = merged
                            changed[field] = items
                    if changed:
                        report[f'{label}_changed'] += 1
                        if label == 'sources':
                            group = additions.get(id, {})
                            for field, items in changed.items():
                                group[field] = index.merge_values(field, group.get(field), items)
                            additions[id] = group
                    if label == 'sources':
                        report['sources_with_parent_after'] += has_parent(row)
                context_table = pa.Table.from_pylist(rows, schema=pa.schema([schema.field(f) for f in fields]))
                output = pa.Table.from_arrays([context_table[f.name] if f.name in fields else table[f.name]
                                               for f in schema], schema=schema)
                if not table.select(protected).equals(output.select(protected)):
                    raise ValueError('Provenance refresh changed a non-provenance value')
                writer.write_table(output, row_group_size=2048)
                count += len(batch)
                progress.report(f'write_lineage_{label}', completed=count,
                                total=source.metadata.num_rows, unit='rows')
        if count != source.metadata.num_rows:
            raise ValueError('Provenance refresh changed the row count')
    report['sources_without_recorded_parent'] = report['rows'] - report['sources_with_parent_after']
    report['catalog_id'] = catalog_id
    return report
