"""Small, typed serving records. The full source export remains unchanged."""
from datetime import datetime, timezone

from viewer_publication.filename_compression import DEFAULT_COMPRESSION_POLICY, validate_compression
import re
import hashlib
from contextlib import closing
from viewer_publication.filename_resources import owned_resources
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, ArrowStager, DecodedBudgetExceeded, bounded_batches, failure_receipt, json_chunks, open_parquet

from congress_api.retention.saved_responses import FIELDS as SAVED_FIELDS, saved_response

import pyarrow as pa
import pyarrow.parquet as pq

CORE = '''source_id body_key filename source_url filename_origins format
body_format media_type document_kind document_kind_source document_family congress
source_congress source_committee_name source_committee_code source_chamber
source_meeting_type source_meeting_title
source_document_type source_document_type_basis
recovered_source_url state_outcome response_format'''.split()
# These stay on the detail row. Observations still carry the full page graph.
RETAINED_PAGE = set('source_page_title source_page_url'.split())
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


def publish_details(source, path, *, observation_counts, policy=DEFAULT_DECODED_POLICY, metrics=None, compression_policy=DEFAULT_COMPRESSION_POLICY):
    metrics = metrics if metrics is not None else {}
    try:
        with owned_resources() as owned:
            return _publish_details(source, path, owned, observation_counts, policy, metrics, compression_policy)
    except DecodedBudgetExceeded as error:
        failure_receipt(path.parent, error, policy, metrics)
        raise


def _publish_details(source, path, owned, observation_counts, policy, metrics, compression_policy):
    source_schema = source.schema if isinstance(source, pa.Table) else source.schema_arrow
    source_rows = len(source) if isinstance(source, pa.Table) else source.metadata.num_rows
    names = source_schema.names
    core = [name for name in CORE + ORIGIN if name in names]
    core += [name for name in names if name.startswith('content_')]
    readings = [name for name in names if name not in NON_FILENAME and not name.startswith(('source_', 'content_'))]
    visible = [name for name in readings if not FRAGMENT.search(name) or name in {'date_token_candidates', 'measure_token', 'measure_token_code'}]
    # Include paired labels/measure fields used to avoid duplicate interpretations.
    visible = list(dict.fromkeys(visible + [name for name in readings if name.endswith('_label') or name in {'measure_type', 'measure_number'}]))
    typed = [name for name in TYPES if name in names]
    schema = pa.schema([source_schema.field(name) for name in core] +
                      [pa.field(name, TYPES[name]) for name in typed] +
                      [pa.field('fact_alternatives', READINGS), pa.field('filename_readings', READINGS),
                       pa.field('filename_field_count', pa.uint16())], metadata=source_schema.metadata)
    counts = owned.enter_context(closing(observation_counts.values(source)))
    expected = hashlib.sha256()
    def update(hasher, rows):
        # Per-row framing makes exact verification independent of batch boundaries.
        for row in rows:
            for piece in json_chunks(row, policy=policy, default=lambda value: value.isoformat()):
                hasher.update(piece)
            hasher.update(b'\n')
    count = 0
    with pq.ParquetWriter(path, schema, compression=validate_compression(compression_policy).codec, compression_level=compression_policy.level, write_page_index=True) as writer:
        staging = ArrowStager(writer, schema, policy=policy, metrics=metrics, stage='detail')
        columns = list(dict.fromkeys(core + typed + readings + [name for name in SAVED_FIELDS if name in names]))
        for batch in bounded_batches(source, columns=columns, policy=policy, stage='details', metrics=metrics):
            result = []
            for row in batch.to_pylist():
                value = next(counts, None)
                if value is None: raise ValueError('Detail/source observation row counts differ')
                has_observations = value > 0
                record = {name: None if name in ORIGIN and name not in RETAINED_PAGE and has_observations else row[name] for name in core}
                # The full source export retains failed-response evidence.
                # Only usable content receives a saved-copy link in the viewer.
                if not saved_response(row):
                    record['body_key'] = None
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
            result.clear()
            update(expected, (row.as_py() for row in table.to_struct_array()))
            for emitted in table.to_batches(): staging.append(emitted)
            count += len(table)
        staging.flush()
    # Check every emitted typed/derived value, independently of browser reads.
    written = owned.enter_context(open_parquet(path))
    if written.metadata.num_rows != count or count != source_rows or next(counts, None) is not None:
        raise ValueError('Detail/source observation row counts differ')
    actual = hashlib.sha256()
    for batch in bounded_batches(written, policy=policy, stage='detail verification', metrics=metrics):
        # Parquet normalizes generated list child names (item/element).
        if not batch.schema.equals(schema) or batch.schema.metadata != schema.metadata:
            raise ValueError('Detail schema changed during publication')
        update(actual, (row.as_py() for row in batch.to_struct_array()))
    if actual.digest() != expected.digest():
        raise ValueError('Detail values changed during publication')
    return {'rows': count, 'typed_fields': typed}
