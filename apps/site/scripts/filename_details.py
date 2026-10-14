"""Small, typed serving records. The full source export remains unchanged."""
from datetime import datetime, timezone
import re
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq

CORE = '''source_id body_key filename source_url filename_origins format
body_format media_type document_kind document_kind_source document_family congress
source_congress source_committee_name source_document_type source_document_type_basis
recovered_source_url state_outcome response_format'''.split()
TYPES = {'http_status': pa.uint16(), 'response_usable': pa.bool_(),
         'response_body_complete': pa.bool_(), 'record_role': pa.string(),
         'state_checked_at': pa.timestamp('ms', tz='UTC'),
         'state_retrieved_at': pa.timestamp('ms', tz='UTC')}
NON_FILENAME = set(CORE) | set(TYPES) | set('''document_id response_result capture_outcome
cache_marker_state recovered_filename state_family state_body_key hearing_package_id
hearing_resources'''.split())
ORIGIN = '''source_association_basis source_associated_url source_original_page_url source_page_url source_page_title source_link_label source_link_url source_occurrence_scope source_page_type source_page_date'''.split()
READINGS = pa.list_(pa.struct([('field', pa.string()), ('values', pa.list_(pa.string()))]))
FRAGMENT = re.compile(r'(?:^|_)(?:token|marker|wording|prefix|suffix|placeholder|remainder)(?:_|$)|^(?:opaque|local|generic|ambiguous)_|^(?:extension|embedded_extension|label|name_token)$|_code$')


def typed_value(name, values):
    if not values or len(values) != 1:
        return None
    value = values[0]
    if name == 'http_status':
        return int(value) if value.isdigit() and str(int(value)) == value and 100 <= int(value) <= 599 else None
    if pa.types.is_boolean(TYPES[name]):
        return {'true': True, 'false': False}.get(value)
    if pa.types.is_timestamp(TYPES[name]):
        try:
            stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
        except ValueError:
            return None
    return value


def publish_details(source, path):
    names = source.schema_arrow.names
    core = [name for name in CORE + ORIGIN if name in names]
    core += [name for name in names if name.startswith('content_')]
    readings = [name for name in names if name not in NON_FILENAME and not name.startswith(('source_', 'content_'))]
    visible = [name for name in readings if not FRAGMENT.search(name) or name in {'date_token_candidates', 'measure_token', 'measure_token_code'}]
    # Include paired labels/measure fields used to avoid duplicate interpretations.
    visible = list(dict.fromkeys(visible + [name for name in readings if name.endswith('_label') or name in {'measure_type', 'measure_number'}]))
    typed = [name for name in TYPES if name in names]
    schema = pa.schema([source.schema_arrow.field(name) for name in core] +
                      [pa.field(name, TYPES[name]) for name in typed] +
                      [pa.field('fact_alternatives', READINGS), pa.field('filename_readings', READINGS),
                       pa.field('filename_field_count', pa.uint16())], metadata=source.schema_arrow.metadata)
    def observation_counts():
        folder = path.parent
        descriptor = json.loads((folder / 'observation-index.json').read_text())
        with (folder / 'observation-rows.bin').open('rb') as stream:
            for block in descriptor['references']['blocks']:
                parts = []
                for start, size, decoded in block['parts']:
                    stream.seek(start); parts.append(pa.decompress(stream.read(size), decoded, codec='brotli').to_pybytes())
                for refs in json.loads(b''.join(parts)):
                    yield len(refs or [])
    counts = observation_counts()
    expected = hashlib.sha256()
    encode = lambda table: json.dumps(table.to_pylist(), ensure_ascii=False, separators=(',', ':'), default=lambda value: value.isoformat()).encode()
    count = 0
    with pq.ParquetWriter(path, schema, compression='zstd', compression_level=9, write_page_index=True) as writer:
        for batch in source.iter_batches(batch_size=8192, columns=list(dict.fromkeys(core + typed + readings))):
            result = []
            for row in batch.to_pylist():
                has_observations = next(counts) > 0
                record = {name: None if name in ORIGIN and has_observations else row[name] for name in core}
                record['fact_alternatives'] = []
                for name in typed:
                    value = typed_value(name, row[name])
                    record[name] = value
                    if value is None and row[name] is not None:
                        record['fact_alternatives'].append({'field': name, 'values': row[name]})
                record['filename_readings'] = [{'field': name, 'values': row[name]} for name in visible if row[name]]
                record['filename_field_count'] = sum(bool(row[name]) for name in readings)
                result.append(record)
            table = pa.Table.from_pylist(result, schema=schema)
            expected.update(encode(table))
            writer.write_table(table, row_group_size=8192)
            count += len(table)
    # Check every emitted typed/derived value, independently of browser reads.
    written = pq.ParquetFile(path)
    if written.metadata.num_rows != count or count != source.metadata.num_rows or next(counts, None) is not None:
        raise ValueError('Detail/source observation row counts differ')
    actual = hashlib.sha256()
    for batch in written.iter_batches(batch_size=8192):
        if not batch.schema.equals(schema):
            raise ValueError('Detail schema changed during publication')
        actual.update(encode(batch))
    if actual.digest() != expected.digest():
        raise ValueError('Detail values changed during publication')
    return {'rows': count, 'typed_fields': typed}
