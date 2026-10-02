"""Recover catalog associations from immutable capture receipts, without fetching.

Only exact requested/final URLs link a retained body to an unlinked URL. A local
copy takes response facts only from a receipt naming that same body and path.
Probe attempts remain observations about generated candidates, not publisher links.
"""
from collections import defaultdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re

import pyarrow as pa
import pyarrow.compute as pc


def recovery_fingerprint():
    return sha256(Path(__file__).read_bytes()).hexdigest()


def retained_path(path):
    """Match the hearing-text archive relocation, keeping the whole relative path.

    The migration copied ~/hearing-text under external-sources/hearing-text.
    This key is always paired with the exact retained body hash, never a basename.
    """
    return re.sub(r'^(?:/Users/[^/]+|/home/[^/]+|external-sources)/hearing-text/',
                  'hearing-text/', path or '')


def recover_sources(rows, captures, *, read_receipt):
    """Return source rows with all proved body versions and original evidence kept."""
    from congress_api.retention import document_index as index

    rows = list(rows)
    missing = defaultdict(list)
    local = defaultdict(list)
    wanted = set()
    for row in rows:
        if not row.get('body_key') and row.get('source_url'):
            missing[row['source_url']].append(row)
            wanted.add(row['source_url'])
            for occurrence in row.get('source_occurrences') or []:
                if occurrence.get('source_association_basis') == ['publisher_redirect']:
                    wanted.update(occurrence.get('source_associated_url') or [])
        elif row.get('body_key') and not row.get('source_url'):
            for path in row.get('source_paths') or []:
                local[(row['body_key'], retained_path(path))].append(row)
    if not missing and not local:
        return rows
    references = defaultdict(lambda: defaultdict(list))
    schema = captures.schema_arrow if hasattr(captures, 'schema_arrow') else captures.schema
    required = {'body_key', 'receipt_key', 'receipt_line', 'pointer_json', 'context_url'}
    if not required <= set(schema.names):
        return rows
    columns = sorted(required | ({'family', 'source_file', 'original_path', 'media_type', 'http_status'} & set(schema.names)))
    batches = (captures.iter_batches(columns=columns) if hasattr(captures, 'iter_batches')
               else captures.select(columns).to_batches(max_chunksize=65536))
    urls = pa.array(sorted(wanted), type=pa.string())
    bodies = pa.array(sorted({key[0] for key in local}), type=pa.string())
    for batch in batches:
        table = pa.Table.from_batches([batch])
        selected = pc.or_(pc.is_in(pc.cast(table['context_url'], pa.string()), value_set=urls),
                          pc.is_in(pc.cast(table['body_key'], pa.string()), value_set=bodies))
        if missing and 'source_file' in columns:
            selected = pc.or_(selected, pc.fill_null(pc.match_substring_regex(table['source_file'],
                r'/(?:xml_path_families|pdf_xml_probe)/(?:attempts|inventory)\.jsonl$'), False))
        for capture in table.filter(selected).to_pylist():
            references[capture['receipt_key']][capture['receipt_line']].append(capture)

    recovered = {}
    replaced = set()

    def merge(row, values):
        for field, items in values.items():
            if items:
                row[field] = index.merge_values(field, row.get(field), items)

    def locate(row, capture, number, **extra):
        occurrence = {field: sorted(values) for field, values in index.context_values(
            source_capture_file=capture.get('source_file'), source_capture_pointer=capture.get('pointer_json'),
            source_receipt_key=capture['receipt_key'], source_receipt_line=number,
            source_occurrence_scope='capture', **extra).items()}
        merge(row, {**occurrence, 'source_occurrences': [occurrence]})

    for key, lines in sorted(references.items()):
        payload = read_receipt(key)
        if payload is None:
            raise ValueError(f'Missing capture receipt: {key}')
        with gzip.open(BytesIO(payload), 'rt', encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                selected = lines.pop(number, None)
                if selected:
                    record = json.loads(line)['record']
                    for capture in selected:
                        # These collectors explicitly record generated XML candidates.
                        file = capture.get('source_file') or ''
                        if any(file.endswith(f'/{folder}/{name}.jsonl')
                               for folder in ('xml_path_families', 'pdf_xml_probe')
                               for name in ('attempts', 'inventory')):
                            for row in missing.get(record.get('xml_url'), ()):
                                facts = index.response_metadata({**capture, 'pointer_json': '[]'}, record)
                                merge(row, facts)
                                locate(row, capture, number, source_capture_url=record.get('xml_url'),
                                    source_association_basis='generated_xml_probe',
                                    source_associated_url=record.get('pdf_url'),
                                    source_probe_status=record.get('status') or 'candidate',
                                    source_probe_method=record.get('arm') or 'extension replacement',
                                    source_probe_checked_at=record.get('checked_at'))
                            continue  # A diagnostic excerpt is not a recovered XML body.
                        if capture.get('family') not in {*index.FAMILIES, 'senate/pages', 'house/pages', None}:
                            continue  # Provider transport bodies are not publisher responses.
                        facts = index.response_metadata(capture, record)
                        owner = index.nearest_record(record, capture['pointer_json'])
                        observed_urls = {u for u in (capture['context_url'], owner.get('requested_url'),
                            owner.get('final_url'), owner.get('url')) if isinstance(u, str) and u}
                        for url in observed_urls:
                            for original in missing.get(url, ()):
                                if not capture.get('body_key'):
                                    if any(facts.values()):
                                        merge(original, facts)
                                        locate(original, capture, number, source_capture_url=sorted(observed_urls))
                                    continue
                                identity = (capture['body_key'], original.get('filename'), url)
                                row = recovered.setdefault(identity, {**original, 'body_key': capture['body_key']})
                                merge(row, facts)
                                locate(row, capture, number, source_capture_url=sorted(observed_urls))
                                replaced.add(id(original))
                        for row in local.get((capture['body_key'], retained_path(capture.get('original_path'))), ()):
                            merge(row, facts)
                            locate(row, capture, number, source_capture_url=sorted(observed_urls))
                if not lines:
                    break
        if lines:
            raise ValueError(f'Capture index references missing receipt lines: {key}')
    # Coalesce an existing body/name/URL row while preserving every source value.
    result = {}
    for row in [*(row for row in rows if id(row) not in replaced), *recovered.values()]:
        identity = tuple(row.get(field) for field in ('body_key', 'filename', 'source_url'))
        if identity in result:
            merge(result[identity], {k: v for k, v in row.items() if isinstance(v, list)})
        else:
            result[identity] = row
    return list(result.values())
