"""Extract body facts during capture and retain bounded, immutable Parquet parts.

Bodies reach storage before their metadata; metadata reaches storage before the
capture receipts. Existing readings survive reader changes until explicit repair.
"""

from collections import Counter
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
import json
import time

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.parsers.document_cover import COVER_FIELDS, document_cover, document_page_fields
from congress_api.parsers.pdf_tools import page_count_file, opening_page_text_file
from congress_api.retention.document_evidence import (
    BODY_FIELDS, document_body_fields, evidence_fingerprint,
)


PREFIX = 'indexes/processing/body-results/'
FIELDS = sorted(BODY_FIELDS)
RESULT_COLUMNS = ('body_key', 'parser_fingerprint', 'status', 'error_type')
SCHEMA = pa.schema([
    (name, pa.string()) for name in RESULT_COLUMNS
] + [(name, pa.list_(pa.string())) for name in FIELDS], metadata={'format_version': '1'})
BODY_LIMIT = 16 * 1024**2


def inspect_document(data):
    """Reuse native XML/format readers and the bounded PDF opening-page reader."""
    fields = document_body_fields(data)
    if fields.get('body_format') == ['pdf']:
        fields.update(document_cover(data, strict=True))
    return fields


def read_document(data, body_key, fingerprint, inspect=inspect_document):
    """Pure, process-safe reading: no store, writer or deduplication state."""
    fields, error = {}, None
    if len(data) > BODY_LIMIT:
        status = 'size_limit'
    else:
        try:
            fields = inspect(data)
            status = 'completed' if fields else 'unclassified'
        except Exception as exc:
            # A reader failure is evidence, not a failed raw-body upload.
            status, error = 'failed', type(exc).__name__
            if data.lstrip().startswith(b'%PDF-'):
                fields = {'body_format': ['pdf']}
    return dict(body_key=body_key, parser_fingerprint=fingerprint,
                status=status, error_type=error, **fields)


def inspect_pdf_file(path):
    """Read PDF opening-page facts, not full text or OCR, without body buffering."""
    pages = page_count_file(path)
    first = opening_page_text_file(path, 1)
    fields = document_page_fields(first)
    if not fields and not first.strip() and pages > 1:
        candidate = document_page_fields('', opening_page_text_file(path, 2))
        if candidate.get('content_document_kind') == ['transcript']:
            fields = candidate
    return {'body_format': ['pdf'], **fields}


def read_document_file(path, body_key, fingerprint, inspect=inspect_document):
    """Keep byte readers bounded; large PDFs use the bounded file-based reader.

    The caller owns the immutable, already-hash-verified local file. Other large
    formats remain refused. A completed result describes opening-page metadata,
    never a claim that all PDF pages were parsed.
    """
    path = Path(path)
    with path.open('rb') as source:
        if path.stat().st_size <= BODY_LIMIT:
            data = source.read(BODY_LIMIT + 1)
            return read_document(data, body_key, fingerprint, inspect)
        pdf = source.read(1024).lstrip().startswith(b'%PDF-')
    fields, error, status = {}, None, 'size_limit'
    if pdf:
        fields = {'body_format': ['pdf']}
        try:
            fields = inspect_pdf_file(path)
            status = 'completed'
        except Exception as exc:
            status, error = 'failed', type(exc).__name__
    return dict(body_key=body_key, parser_fingerprint=fingerprint,
                status=status, error_type=error, **fields)


def saved_readings(store, *, columns=None):
    """Read completed parts individually; never concatenate the whole dataset."""
    for key in sorted(store.keys(PREFIX)):
        if not key.endswith('.parquet'):
            continue
        payload = store.read(key)
        file = pq.ParquetFile(pa.BufferReader(payload))
        schema = file.schema_arrow
        if ((schema.metadata or {}).get(b'format_version') != b'1'
                or not set(RESULT_COLUMNS) <= set(schema.names)
                or any(field.type != (pa.string() if field.name in RESULT_COLUMNS
                                      else pa.list_(pa.string())) for field in schema)):
            raise ValueError(f'Unexpected body metadata schema: {key}')
        # Optional fact columns can grow as readers learn new fields. Older
        # completed parts remain valid and retain their original provenance.
        for batch in file.iter_batches(batch_size=256, columns=columns):
            yield from batch.to_pylist()


def restore_body_results(store, cache):
    """Adapt new capture readings to the existing shared body-result cache."""
    for row in saved_readings(store):
        key = row['body_key']
        fields = {field: value for field, value in row.items()
                  if field not in RESULT_COLUMNS and value is not None}
        pdf = fields.get('body_format') == ['pdf']
        # These are byte-derived facts. HTTP outcomes and source labels are
        # applied separately for each occurrence by the existing catalog reader.
        # Cover results have their own cache entry. Keeping them in generic
        # format facts would resurrect an old classification after a deliberate
        # rebuild produced an empty cover result.
        xml = fields.get('body_format') == ['xml']
        xml_fields = cache.setdefault(('xml', key), fields if xml else {})
        cache.setdefault(('document', key), xml_fields if xml else {
            field: value for field, value in fields.items() if not pdf or field not in COVER_FIELDS})
        cache.setdefault(('cover', key), {field: value for field, value in fields.items()
                                        if field in COVER_FIELDS and pdf})


class MetadataWriter:
    """One incremental writer; rotate on row, byte or time limits.

    A failed upload retains the exact closed payload for retry. The caller may
    publish capture receipts only after flush succeeds.
    """

    def __init__(self, store, run_id, *, max_rows=1000, max_bytes=4 * 1024**2,
                 interval=300, clock=time.monotonic):
        self.store, self.run_id = store, run_id
        self.max_rows, self.max_bytes, self.interval = max_rows, max_bytes, interval
        self.clock = clock
        self.sequence = 0
        self.buffer = []
        self.count = self.bytes = 0
        self.started = clock()
        self.file = self.writer = self.upload = None

    def append(self, row):
        if self.upload is not None:
            self.flush()
        if self.file is None:
            self.file = TemporaryFile()
            self.writer = pq.ParquetWriter(self.file, SCHEMA, compression='zstd')
            self.started = self.clock()
        self.buffer.append(row)
        self.count += 1
        self.bytes += len(json.dumps(row, ensure_ascii=False).encode())
        if len(self.buffer) >= 64:
            self._write_buffer()
        if self.count >= self.max_rows or self.bytes >= self.max_bytes:
            self.flush()

    def _write_buffer(self):
        if self.buffer:
            self.writer.write_table(pa.Table.from_pylist(self.buffer, schema=SCHEMA))
            self.buffer.clear()

    def flush_due(self):
        if self.count and self.clock() - self.started >= self.interval:
            self.flush()
            return True
        return False

    def flush(self):
        if self.upload is None:
            if not self.count:
                return
            self._write_buffer()
            self.writer.close()
            self.writer = None
            self.file.seek(0)
            payload = self.file.read()
            self.file.close()
            self.file = None
            self.sequence += 1
            key = f'{PREFIX}{self.run_id}/{self.sequence:06d}-{sha256(payload).hexdigest()}.parquet'
            self.upload = (key, payload)
        key, payload = self.upload
        self.store.put(key, payload, immutable=True)
        self.upload = None
        self.count = self.bytes = 0

    def close(self):
        try:
            self.flush()
        finally:
            if self.writer is not None:
                self.writer.close()
            if self.file is not None:
                self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class CaptureMetadata:
    """Extract once per body, keeping only completed identities in memory."""

    def __init__(self, store, run_id, *, inspect=inspect_document, refresh_body_keys=(), **writer_options):
        self.inspect = inspect
        self.writer = MetadataWriter(store, run_id, **writer_options)
        self.fingerprint = sha256((evidence_fingerprint() + Path(__file__).read_text()).encode()).hexdigest()
        self.seen = {row['body_key'] for row in saved_readings(store, columns=['body_key'])}
        # Keep previously saved readings, including completed negative results.
        legacy = store.read('indexes/processing/bodies.parquet')
        if legacy:
            file = pq.ParquetFile(pa.BufferReader(legacy))
            for batch in file.iter_batches(columns=['body_key'], batch_size=4096):
                self.seen.update(batch.column(0).to_pylist())
        self.counts = Counter()
        # Explicit retained-body validation appends a new reading without
        # deleting any old part or refreshing unrelated bodies.
        self.seen.difference_update(refresh_body_keys)

    def record(self, data, body_key):
        if body_key in self.seen:
            self.counts['reused'] += 1
            return
        self.accept(self.reading(data, body_key))

    def reading(self, data, body_key):
        """Compute a reading off the event loop, without touching writer state."""
        return read_document(data, body_key, self.fingerprint, self.inspect)

    def record_file(self, path, body_key):
        """Read a retained spool file once, preserving all previous readings."""
        if body_key in self.seen:
            self.counts['reused'] += 1
            return
        self.accept(read_document_file(path, body_key, self.fingerprint, self.inspect))

    def accept(self, reading):
        """The single collector admits each durable body's result once."""
        body_key = reading['body_key']
        if body_key in self.seen:
            self.counts['reused'] += 1
            return
        self.writer.append(reading)
        self.seen.add(body_key)
        self.counts[reading['status']] += 1

    def flush(self):
        self.writer.flush()

    def flush_due(self):
        return self.writer.flush_due()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.writer.close()
