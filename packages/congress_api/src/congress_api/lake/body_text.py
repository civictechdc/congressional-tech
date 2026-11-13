"""The body-text producer: one read per body writes `body_text` and its `readings` row.

Data model §6.6 (and §6.2 for the narrow readings row). The work list is every body whose
pinned sniff format is `pdf`, `html` or `xml` with no `readings` row at that format's
declared body-text version and no active `unreadable` decision; an `error` or `size_limit`
row settles a body too. Per batch, `body_text` commits first and `readings` second, each
through `append_rows`' PK anti-join, so a crash between the commits leaves the body on the
list and its retry appends no second text row.

Reads use the copy each capture recorded (as `readings.plan(captured_copies=True)` picks it), from a
local raw root or, given ``origin``, the raw bucket's public origin: one ranged GET per body through
the readings range cache and R2Store's pinned read (`retention/public_origin.py`), conditional on the
capture's stored MD5 and size, then the readings storage rule, which decodes and checks the body's
SHA-256. Most captures record no MD5 (1,280 of 158,267 rows for one sixteenth of the corpus, 2026-11-09);
given ``body_listing`` (from one credentialed bucket LIST), such a read is pinned directly by the
listed strong ETag and size with no extra request, or without a listing by the ETag a one-byte GET
answers first, so it still reads one object version, and the SHA-256 check alone decides the bytes. A body whose stored size is over the
bound settles as `size_limit` before any byte is fetched; one with no stored size stays listed
(`missing_pins`). A worker returns its
text as a file (path, bytes, SHA-256), so no text crosses the supervisor's 8 MiB pipe; the
supervisor's timeout is a fixed document deadline and each page has its own deadline inside the
worker. Batches are sized by an upper bound on their text bytes against ``max_cache_bytes``.

Cost: one native plan (two narrow scans of captures and one of readings, all joined to the
candidate set); one ranged GET per origin body, and a one-byte GET before it for each body with no
captured MD5; O(B) worker time per body in its bytes; O(T) disk per batch in its text, freed once
the batch commits.
"""
from functools import lru_cache
import gzip
import io
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import traceback
from tempfile import NamedTemporaryFile
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import readings, body_text_selection
from congress_api.lake.tables import table_input
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.parser_worker import ParserWorker, ParserWorkerPool, reading_input
from congress_api.retention.process_resources import resident_bytes
from congress_api.retention.provenance import (active_unreadable_where, field, finish_stage, import_unreadable,
    instant, json_input, parquet_output, parquet_records, run_job)
from congress_api.retention.r2_edge_rules import PUBLIC_BUCKET, PUBLIC_HOSTNAME

ROOT = Path(__file__).resolve().parents[5]
# Read here, not through tables.LAKE_SCHEMA_PATHS, whose module every reading version's evidence hashes.
SCHEMA = ROOT / 'model/lake/body-text.schema.json'
PK = readings.PK
FORMAT_PARSERS = {'pdf': 'pdf_text', 'html': 'html_text', 'xml': 'xml_text'}
PARSERS = tuple(FORMAT_PARSERS.values())
MAX_STORED_BYTES = readings.MAX_STORED_BYTES
MAX_DECODED_BYTES = readings.MAX_DECODED_BYTES
WORKER_MEMORY_BYTES = 2 << 30
PARSER_MEMORY_BYTES = 32 << 30
# A fixed bound per document (the supervisor kills the worker past it) and per page (inside the
# worker). Both are first-pass values for the census to confirm (plan §1, "Census").
DOCUMENT_DEADLINE_SECONDS = 1800
PAGE_DEADLINE_SECONDS = 60
MAX_CACHE_BYTES = 8 << 30
MAX_BATCH_ITEMS = 4096
STAGE_TEXT_BYTES = 64 << 20
ORIGIN = 'https://' + PUBLIC_HOSTNAME
USER_AGENT = 'ct-body-text/1'


def current_versions():
    """The declared version of each body-text parser (reading_versions)."""
    return {parser: readings.current_version(parser) for parser in PARSERS}


def recovery_versions():
    """Separate identities for an explicit retry without stored or decoded byte exclusions.

    Ordinary completed readings retain their original identity. A recovery result names the
    original text rule and the relaxed resource policy; it cannot collide with an old failure.
    """
    from congress_api.lake.reading_versions import BODY_TEXT_DECLARATIONS
    return {parser: sha256((declaration + '\nRecovery policy 2026-11-13: no stored, decoded, or page-render '
            'size exclusion; original OCR resolution and routing retained; supervised worker memory and '
            'time limits still apply.').encode()).hexdigest()
            for parser, declaration in BODY_TEXT_DECLARATIONS.items()}


def worker_limits(memory_bytes=WORKER_MEMORY_BYTES):
    """The supervisor policy: the document deadline replaces the readings 15 s timeout."""
    return dict(timeout_seconds=DOCUMENT_DEADLINE_SECONDS, memory_bytes=memory_bytes,
                max_input_bytes=65536, max_output_bytes=8 << 20)


LISTING_SCHEMA = pa.schema([('key', pa.string()), ('size', pa.int64()), ('etag', pa.string())])


def _register_body_listing(body_listing):
    source = table_input('body_listing', body_listing)
    if source['kind'] == 'parquet':
        observed = pq.read_schema(source['path'])
        expected = {f.name: f.type for f in LISTING_SCHEMA}
        actual = {f.name: f.type for f in observed if f.name in expected}
        if set(actual) != set(expected) or actual != expected:
            raise ValueError('body_listing Parquet must match LISTING_SCHEMA (key: string, size: int64, etag: string)')
    return source


def write_body_listing(client, *, bucket=PUBLIC_BUCKET, out, prefix='bodies/sha256/'):
    """Write one credentialed ``list_objects_v2`` pass under ``prefix`` as ``(key, size, etag)`` Parquet.

    One LIST request per 1,000 objects, streamed page-by-page to a temporary file in ``out.parent``
    and atomically replaced on completion; preserves quoted ETags so weak ETags (``W/...``) remain
    distinguishable from strong ones.
    """
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    paginator = client.get_paginator('list_objects_v2')
    keys, sizes, etags, total = [], [], [], 0
    with NamedTemporaryFile(dir=out.parent, prefix=f'.{out.name}.', suffix='.tmp', delete=False) as handle:
        tmp = Path(handle.name)
    try:
        with pq.ParquetWriter(tmp, LISTING_SCHEMA, compression='zstd') as writer:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get('Contents', ()):
                    key, size, etag = obj['Key'], obj['Size'], obj['ETag']
                    validate_key(key)
                    if type(size) is not int or size < 0 or not isinstance(etag, str):
                        raise ValueError('Invalid body listing object metadata')
                    keys.append(key)
                    sizes.append(size)
                    etags.append(etag)
                    total += 1
                    if len(keys) >= 16384:
                        writer.write_table(pa.Table.from_pydict(
                            {'key': keys, 'size': sizes, 'etag': etags}, schema=LISTING_SCHEMA))
                        keys, sizes, etags = [], [], []
            if keys or total == 0:
                writer.write_table(pa.Table.from_pydict(
                    {'key': keys, 'size': sizes, 'etag': etags}, schema=LISTING_SCHEMA))
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dict(path=out, rows=total)


def copy_selection_steps(*, with_listing=False):
    """The candidate bodies' chosen captured copies, joined to ``body_listing`` before ranking when supplied."""
    steps = [
        # Captures grouped only after the semi-join to the candidates (AGENTS.md pushdown rule).
        dict(name='body_storage', materialize=True, sql="""SELECT c.sha256 AS body_sha,
            coalesce(c.stored_suffix,'.gz') AS stored_suffix,
            concat('bodies/sha256/',substr(encode(c.sha256,'hex'),1,2),'/',encode(c.sha256,'hex'),
                coalesce(c.stored_suffix,'.gz')) AS physical_key,
            max(c.bytes) AS decoded_bytes,max(c.stored_bytes) AS stored_bytes,max(c.retrieved_at) AS latest,
            max(encode(c.stored_md5,'hex')) AS stored_md5,
            min(c.bytes)<>max(c.bytes) OR min(c.stored_bytes)<>max(c.stored_bytes)
                OR min(encode(c.stored_md5,'hex'))<>max(encode(c.stored_md5,'hex')) AS conflict
            FROM candidates k RIGHT SEMI JOIN captures c ON k.body_sha=c.sha256
            GROUP BY c.sha256,coalesce(c.stored_suffix,'.gz')"""),
    ]
    if with_listing:
        steps.append(dict(name='copy_candidates', materialize=True, sql=f'''SELECT s.*,
            nullif(l.etag,'') AS listed_etag,
            CASE WHEN s.physical_key IS NULL OR s.stored_bytes IS NULL OR s.stored_bytes>{MAX_STORED_BYTES} THEN NULL
                 WHEN l.key IS NULL THEN 'missing_remote'
                 WHEN nullif(l.etag,'') IS NULL OR starts_with(l.etag,'W/') THEN 'changed_input'
                 WHEN l.size<>s.stored_bytes THEN 'changed_input'
                 WHEN s.stored_md5 IS NOT NULL AND lower(trim(BOTH '"' FROM l.etag))<>s.stored_md5 THEN 'changed_input'
                 END AS listing_refusal,
            s.stored_bytes IS NOT NULL AND NOT coalesce(s.conflict,false) AND l.key IS NOT NULL
                AND nullif(l.etag,'') IS NOT NULL AND NOT starts_with(l.etag,'W/')
                AND l.size=s.stored_bytes
                AND (s.stored_md5 IS NULL OR lower(trim(BOTH '"' FROM l.etag))=s.stored_md5) AS copy_usable
            FROM body_storage s LEFT JOIN body_listing l ON s.physical_key=l.key'''))
    else:
        steps.append(dict(name='copy_candidates', sql='''SELECT s.*,
            cast(NULL AS VARCHAR) AS listed_etag,
            cast(NULL AS VARCHAR) AS listing_refusal,
            s.stored_bytes IS NOT NULL AND NOT coalesce(s.conflict,false) AS copy_usable
            FROM body_storage s'''))
    steps.append(dict(name='body_copies', materialize=True, sql='''SELECT * FROM (
        SELECT *,row_number() OVER (
            PARTITION BY body_sha
            ORDER BY copy_usable DESC,stored_bytes IS NULL,
                CASE stored_suffix WHEN '' THEN 0 WHEN '.gz' THEN 1 ELSE 2 END) AS choice
        FROM copy_candidates) WHERE choice=1'''))
    return steps


def plan(*, captures, engine, work, decided_at, local_root=None, existing=None, unreadable_files=(),
         registry=None, filename_readings=None, body_listing=None, selection=None, existing_text=None):
    """Materialize the ordered work list in one native job, opening no body.

    Newest Congress first (plan §1), each body taking the highest Congress any of its captures'
    effective filenames reads at the current filename catalog version (`filename_readings`, the
    model's join on filename and source URL); then, and for a body with no Congress or without
    `filename_readings`, newest capture first, so weekly bodies lead a backfill.
    """
    from congress_api.lake import compatible_versions
    if body_listing is not None and local_root is not None:
        raise ValueError('body_listing applies to remote origin reads, not local_root')
    instant(decided_at)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    versions = current_versions()
    accepted = body_text_selection.load(selection, versions)
    if accepted['overrides'] and (existing is None or existing_text is None):
        raise ValueError('Explicit selections require both retained readings and body_text')
    pins = compatible_versions.current_pins()
    entries = compatible_versions.load_registry(current=pins, **({} if registry is None else dict(path=registry)))
    sniff_entries = [e for e in entries if e['parser'] == 'sniff']
    selected = {'sniff': pins['sniff'], **versions}
    unreadable_schema = dict(id='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8',
                             reason='Utf8', supersedes='Utf8')
    inputs = [json_input(work, 'parser_versions', [dict(parser=p, version=v) for p, v in selected.items()],
                         parser='Utf8', version='Utf8'),
              json_input(work, 'format_parsers', [dict(format=f, parser=p) for f, p in FORMAT_PARSERS.items()],
                         format='Utf8', parser='Utf8'),
              compatible_versions.accepted_versions_input(work, sniff_entries, pins={'sniff': pins['sniff']}),
              table_input('captures', captures), body_text_selection.selection_input(work, accepted)]
    if existing_text is not None:
        inputs.append(table_input('body_text', existing_text))
    if body_listing is not None:
        inputs.append(_register_body_listing(body_listing))
    if unreadable_files:
        inputs.append(dict(name='unreadable', kind='json_lines', files=list(unreadable_files),
            schema=dict(fields=[field(k, v) for k, v in unreadable_schema.items()], metadata={})))
    else:
        inputs.append(json_input(work, 'unreadable', [], **unreadable_schema))
    steps = []
    if filename_readings is not None:
        from congress_api.lake import filenames
        inputs += [table_input('filename_readings', filename_readings),
                   json_input(work, 'current_recoveries', [], id='Utf8', original_url='Utf8',
                              recovered_filename='Utf8', kind='Utf8'),
                   json_input(work, 'filename_parameters', json.loads(filenames.PARAMETERS.read_text()),
                              priority='Int32', parameter='Utf8')]
    if existing:
        inputs.append(table_input('existing', existing))
    else:
        empty = json_input(work, 'existing_json', [], **readings._reading_fields())
        inputs.append(empty)
        steps.append(dict(name='existing', sql=f'SELECT {readings._LAKE_READING_COLUMNS} FROM existing_json'))
    steps += [
        dict(name='readings', sql='SELECT * FROM existing'),
        *compatible_versions.selected_readings_steps(sniff_entries, parsers=('sniff',)),
        *[dict(name=name.replace('-', '_'), sql=(ROOT / 'model/sql' / (name + '.sql')).read_text())
          for name in ['pinned-readings', 'sniff-observations', 'sniff-conflicts', 'sniff-facts']],
        dict(name='active_unreadable', sql=f'SELECT u.* FROM unreadable u WHERE {active_unreadable_where()}'),
        dict(name='selected_body_readings', materialize=True,
             sql=body_text_selection.selected_sql('readings', accepted,
                 columns=('body_sha', 'parser', 'parser_version', 'status'))),
        dict(name='selected_body_unreadable', materialize=True,
             sql=body_text_selection.selected_sql('active_unreadable', accepted, body="decode(r.body_sha256,'hex')")),
        # Extraction completion and publication acceptance are different. A new current
        # attempt awaiting qualification must not be extracted again on every resume.
        dict(name='current_body_attempts', materialize=True,
             sql=f'SELECT body_sha,parser,parser_version FROM readings WHERE {body_text_selection.at_versions(versions)}'),
        dict(name='settled', materialize=True, sql='''SELECT body_sha,parser FROM selected_body_readings
            UNION ALL SELECT decode(body_sha256,'hex') AS body_sha,parser FROM selected_body_unreadable
            UNION ALL SELECT body_sha,parser FROM current_body_attempts'''),
        dict(name='candidates', materialize=True, sql='''SELECT f.body_sha,f.format,p.parser,v.version AS parser_version
            FROM sniff_facts f JOIN format_parsers p ON f.format=p.format JOIN parser_versions v ON v.parser=p.parser
            WHERE NOT EXISTS (SELECT 1 FROM settled s WHERE s.body_sha=f.body_sha AND s.parser=p.parser)
              AND NOT EXISTS (SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(f.body_sha,'hex')
                AND u.parser=p.parser AND u.parser_version=v.version)'''),
        *copy_selection_steps(with_listing=body_listing is not None),
    ]
    if filename_readings is not None:
        version = "'" + filenames.current_version().replace("'", "''") + "'"
        steps += [
            # Only the candidates' captures are named (AGENTS.md pushdown rule), by the model's rule.
            dict(name='filename_captures', materialize=True, sql='''SELECT c.sha256,c.receipt_key,c.receipt_line,
                c.capture_index,c.mode,c.url,c.requested_url,c.member_path,c.h_content_disposition,c.context_url,
                encode(sha256(json_array(c.receipt_key,c.receipt_line,c.capture_index)),'hex') AS capture_id
                FROM candidates k RIGHT SEMI JOIN captures c ON k.body_sha=c.sha256'''),
            dict(name='filename_inputs', sql=filenames.INPUT_SQL.read_text()),
            dict(name='effective_names', sql=filenames.SQL.read_text()),
            dict(name='named_bodies', materialize=True, sql='''SELECT c.sha256 AS body_sha,n.filename,
                coalesce(n.source_url,'') AS source_url FROM filename_captures c
                JOIN effective_names n ON n.input_id=c.capture_id'''),
            dict(name='body_congress', materialize=True, sql=f'''SELECT b.body_sha,max(f.congress) AS congress
                FROM named_bodies b JOIN (SELECT filename,source_url,congress FROM filename_readings
                    WHERE catalog_version={version} AND congress IS NOT NULL) f
                ON f.filename=b.filename AND f.source_url=b.source_url GROUP BY b.body_sha''')]
    congress = ('g.congress', ' LEFT JOIN body_congress g ON k.body_sha=g.body_sha') if filename_readings is not None \
        else ('cast(NULL AS INT)', '')
    steps.append(dict(name='pending_bodies', materialize=True, sql=f'''SELECT k.body_sha,k.format,k.parser,
        k.parser_version,s.physical_key,s.physical_key AS relative_path,s.stored_bytes,s.stored_md5,s.decoded_bytes,
        s.listed_etag,s.listing_refusal,
        coalesce(s.conflict,false) AS conflict,{congress[0]} AS congress,
        cast(row_number() OVER (ORDER BY {congress[0]} DESC NULLS LAST,s.latest DESC NULLS LAST,k.body_sha) AS BIGINT)
            AS position
        FROM candidates k LEFT JOIN body_copies s ON k.body_sha=s.body_sha{congress[1]}'''))
    queries = [dict(name='work_items', sql='SELECT count(*) AS n,count(congress) AS with_congress FROM pending_bodies'),
               dict(name='unselected_current_attempts', sql='''SELECT count(*) AS n FROM selected_body_readings s
                   RIGHT ANTI JOIN current_body_attempts r ON s.body_sha=r.body_sha AND s.parser=r.parser
                       AND s.parser_version=r.parser_version'''),
               dict(name='by_parser', sql='''SELECT parser,count(*) AS n,coalesce(sum(stored_bytes),0) AS stored_bytes
                  FROM pending_bodies GROUP BY parser ORDER BY parser'''),
               dict(name='conflicts', sql='''SELECT count(*) AS n FROM (SELECT body_sha FROM sniff_conflicts
                  UNION ALL SELECT body_sha FROM pending_bodies WHERE conflict
                  UNION ALL SELECT body_sha FROM body_storage WHERE stored_suffix NOT IN ('','.gz','.pdf'))''')]
    if body_listing is not None:
        queries.append(dict(name='listing_conflicts', sql='''SELECT count(*) AS n FROM (
            SELECT key FROM body_listing WHERE key IS NULL OR size IS NULL OR size<0
            UNION ALL SELECT key FROM body_listing GROUP BY key HAVING count(*)>1)'''))
    queries += body_text_selection.validation_queries(accepted, text_table='body_text' if existing_text else None)
    staged_work_list = work / 'work-list.staged.parquet'
    checks = run_job(work, engine, inputs=inputs, steps=steps,
        outputs=[parquet_output(work, 'work-list.staged', 'SELECT * FROM pending_bodies', ['position'])],
        queries=queries)
    try:
        body_text_selection.validate_counts(checks)
        if checks['conflicts'][0]['n']:
            raise ValueError('Conflicting sniff facts or captured copies for body-text work')
        if body_listing is not None and checks['listing_conflicts'][0]['n']:
            raise ValueError('Invalid or duplicate keys in body_listing')
        os.replace(staged_work_list, work / 'work-list.parquet')
    except BaseException:
        staged_work_list.unlink(missing_ok=True)
        raise
    return dict(status='planned', work=work, work_list=work / 'work-list.parquet', versions=versions,
                work_items=checks['work_items'][0]['n'], with_congress=checks['work_items'][0]['with_congress'],
                by_parser=checks['by_parser'], selection=accepted['identity'],
                unselected_current_attempts=checks['unselected_current_attempts'][0]['n'],
                local_root=None if local_root is None else Path(local_root).resolve(), decided_at=decided_at)


def batches(items, *, max_cache_bytes=MAX_CACHE_BYTES, max_items=MAX_BATCH_ITEMS):
    """Split the ordered work list by an upper bound on each batch's staged text.

    A body's text is bounded by its decoded size (at most MAX_DECODED_BYTES); a body over the
    stored bound is never read, so it counts nothing. One pass, O(N).
    """
    if type(max_cache_bytes) is not int or not MAX_DECODED_BYTES <= max_cache_bytes <= readings.RAW_CACHE_CEILING:
        raise ValueError('max_cache_bytes must cover one decoded body and stay within the 10 GiB ceiling')
    batch, spent = [], 0
    for item in items:
        stored = item['stored_bytes']
        cost = 0 if stored is not None and stored > MAX_STORED_BYTES else min(
            MAX_DECODED_BYTES, item['decoded_bytes'] if item['decoded_bytes'] is not None else MAX_DECODED_BYTES)
        if batch and (spent + cost > max_cache_bytes or len(batch) >= max_items):
            yield batch
            batch, spent = [], 0
        batch.append(item)
        spent += cost
    if batch:
        yield batch


def _read_decoded(request):
    """The body's decoded bytes (None above MAX_DECODED_BYTES), from its local copy or the origin."""
    if 'remote' in request:
        return _read_remote(request)
    return _read_local(request)


@lru_cache(maxsize=2)
def _origin_store(origin):
    """One read-only store per worker process and origin; its client has no write call."""
    from congress_api.retention.public_origin import PublicOrigin
    from congress_api.retention.r2 import R2Store
    return R2Store(PublicOrigin(origin, user_agent=USER_AGENT), PUBLIC_BUCKET)


def _read_remote(request):
    """One ranged GET of the whole stored object, pinned by size and the captured MD5 or listed
    ETag (with neither, by the ETag a one-byte GET answers first), kept in the body's range cache
    so a retried body reads no byte twice; the storage rule then decodes and checks the SHA-256."""
    remote = request['remote']
    if remote.get('md5') is None and not remote.get('etag'):  # no captured MD5 or listed ETag: probe once
        remote = dict(remote, etag=_observed_etag(remote, request['stored_bytes']))
    source = readings._ReadOnceBody(None, request['cache'], request['stored_bytes'], remote=remote,
                                    body_store=_origin_store(remote['origin']))
    try:
        stored = source.read(0, source.size)
        if request.get('unlimited_body_bytes'):
            stream = io.BytesIO(stored)
            compressed = readings._storage_gzip(stream, request['body_sha'], verify_plain=True)
            stream.seek(0)
            data = gzip.GzipFile(fileobj=stream).read() if compressed else stored
        else:
            data, _ = readings._page_entity(stored, request['body_sha'])
    finally:
        source.close()
    return data


def _observed_etag(remote, stored_bytes):
    """The object's strong ETag from a one-byte GET whose Content-Range total is the captured size."""
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        response = _origin_store(remote['origin']).client.get_object(
            Bucket=remote['bucket'], Key=remote['key'], Range='bytes=0-0')
    except (BotoCoreError, ClientError) as error:
        raise OSError('origin_probe') from error
    response['Body'].close()
    etag = response.get('ETag') or ''
    if (response['ResponseMetadata']['HTTPStatusCode'] != 206 or etag.startswith('W/') or not etag
            or response.get('ContentRange') != f'bytes 0-0/{stored_bytes}'):
        raise OSError('changed_input')
    return etag


def _read_local(request):
    """One open of the local copy: the storage rule decides gzip by hash, then a bounded read."""
    path = Path(request['path'])
    with reading_input():
        stream = path.open('rb')
    with stream:
        with reading_input():
            observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_size != request['stored_bytes']:
            raise OSError('changed_input')
        stored_gzip = readings._storage_gzip(stream, request['body_sha'], verify_plain=bool(request.get('unpinned')))
        with reading_input():
            stream.seek(0)
            entity = gzip.GzipFile(fileobj=stream) if stored_gzip else stream
            try:
                data = entity.read() if request.get('unlimited_body_bytes') else entity.read(MAX_DECODED_BYTES + 1)
            finally:
                if entity is not stream:
                    entity.close()
    return None if not request.get('unlimited_body_bytes') and len(data) > MAX_DECODED_BYTES else data


def _sniff_format(payload):
    from congress_api.retention.sniff import read_sniff
    row = read_sniff(lambda start, length: payload[start:start + length], stored_size=len(payload))
    return row.get('format') if row.get('status') == 'completed' else None


def _read_reason(error):
    """The read rule's own label when it raised one (`changed_input`, `origin_probe`), else the error's type."""
    label = error.args[0] if len(error.args) == 1 else None
    return label if isinstance(label, str) and label.isidentifier() else type(error).__name__


_STRATEGIES = {}


def _worker_lifetime_peak_rss_bytes():
    """Historical high-water mark; never attribute this to one request."""
    import resource
    import sys
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    ru_bytes = int(ru) if sys.platform == 'darwin' else int(ru) * 1024
    return max(resident_bytes(os.getpid()), ru_bytes)


def parse_payload(payload):
    """Keep the diagnostic for a worker crash before its supervisor restarts it."""
    request = json.loads(payload)
    try:
        return _parse_payload(payload)
    except Exception:
        if request.get('diagnostics'):
            Path(request['diagnostics']).write_text(traceback.format_exc(limit=12))
        raise


class _QualityEvidence:
    """Optional page evidence, streamed outside the bounded worker response."""

    def __init__(self, request):
        self.path = request.get('quality_evidence')
        self.identity = {key: request.get(key) for key in ('body_sha', 'parser', 'parser_version')}
        self.stream, self.digest, self.bytes = None, sha256(), 0

    def __enter__(self):
        if self.path:
            requested = Path(self.path)
            # A retry must not overwrite the failed attempt's page evidence.
            self.path = str(requested.with_name(requested.stem + '.' + uuid4().hex + requested.suffix))
            self.stream = Path(self.path).open('wb')
            self.emit(dict(event='attempt_started', schema='ct-body-text-quality-v1', **self.identity))
        return self

    def emit(self, event):
        if self.stream is not None:
            encoded = (json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
            self.stream.write(encoded)
            self.stream.flush()  # completed page evidence survives a later worker crash
            self.digest.update(encoded)
            self.bytes += len(encoded)

    def __exit__(self, kind, error, trace):
        if self.stream is not None:
            try:
                if kind is not None:
                    self.emit(dict(event='attempt_interrupted', error_type=kind.__name__))
            finally:
                self.stream.close()

    def reference(self):
        return dict(path=self.path, bytes=self.bytes, sha256=self.digest.hexdigest())


def _parse_payload(payload):
    """Worker callable: read one body, derive its reading, write its text to the named directory.

    Returns ``read_error`` (no verdict; its reason), ``pending`` (OCR needed, no engine), ``retry`` (a page
    outlived its deadline) or a ``row`` with ``text`` naming the file, its bytes and SHA-256.
    """
    from congress_api.parsers import body_text as derivation
    from congress_api.retention.page_checkpoints import CheckpointError, adapter
    request = json.loads(payload)
    try:
        data = _read_decoded(request)
    except (OSError, EOFError) as error:
        return dict(read_error=_read_reason(error), error=f'{type(error).__name__}: {error}')
    if data is None:
        return dict(row=dict(status='error', error_type='decoded_size_limit'),
                    worker_lifetime_peak_rss_bytes=_worker_lifetime_peak_rss_bytes())
    spec = request['strategy']
    if spec not in _STRATEGIES:  # one strategy object per worker process, reused across bodies
        _STRATEGIES[spec] = derivation.load_page_rule(spec)
    with _QualityEvidence(request) as evidence:
        try:
            reading = derivation.derive(data, request['parser'], strategy=_STRATEGIES[spec],
                page_deadline_seconds=request['page_deadline_seconds'], sniff_format=_sniff_format,
                max_bytes=None if request.get('unlimited_body_bytes') else MAX_DECODED_BYTES,
                evidence=evidence.emit if evidence.path else None, checkpoint=adapter(request.get('page_checkpoints')))
        except CheckpointError as error:
            evidence.emit(dict(event='checkpoint_failed', error=str(error)))
            return dict(read_error='page_checkpoint', error=str(error),
                        worker_lifetime_peak_rss_bytes=_worker_lifetime_peak_rss_bytes())
        except derivation.OcrRequired:
            evidence.emit(dict(event='attempt_pending', reason='ocr_required'))
            return dict(pending='ocr_required', worker_lifetime_peak_rss_bytes=_worker_lifetime_peak_rss_bytes())
        except derivation.PageDeadline:
            evidence.emit(dict(event='attempt_pending', reason='page_deadline'))
            return dict(retry='page_deadline', worker_lifetime_peak_rss_bytes=_worker_lifetime_peak_rss_bytes())
        evidence.emit(dict(event='derivation_finished', reading_status=reading.status, error_type=reading.error_type))
    child_rss = _worker_lifetime_peak_rss_bytes()
    del data
    value = dict(row=reading.row(), worker_lifetime_peak_rss_bytes=child_rss)
    if evidence.path:
        value['quality_evidence'] = evidence.reference()
    if reading.diagnostic:
        if request.get('diagnostics'):
            Path(request['diagnostics']).write_text(reading.diagnostic)
            value['diagnostic_path'] = request['diagnostics']
        # Detailed page failures stay in a file rather than filling the supervisor's output pipe.
        value['error'] = reading.diagnostic[-32768:]
    if reading.text is not None:
        encoded = reading.text.encode()
        target = Path(request['texts']) / (request['body_sha'] + '.txt')
        partial = target.with_suffix('.partial')
        partial.write_bytes(encoded)
        partial.replace(target)
        value.update(text=dict(path=str(target), bytes=len(encoded), sha256=sha256(encoded).hexdigest()),
                     page_offsets=list(reading.page_offsets), ocr_pages=list(reading.ocr_pages),
                     macos_build=reading.macos_build)
    return value


def _text_schema():
    import pyarrow as pa
    pages = pa.list_(pa.field('element', pa.int32(), nullable=False))
    return pa.schema([pa.field('body_sha', pa.binary(32), nullable=False),
        pa.field('parser', pa.string(), nullable=False), pa.field('parser_version', pa.string(), nullable=False),
        pa.field('text', pa.large_string(), nullable=False), pa.field('page_offsets', pages, nullable=False),
        pa.field('ocr_pages', pages, nullable=False), pa.field('text_sha256', pa.binary(32), nullable=False),
        pa.field('macos_build', pa.string())])


def _write_texts(path, texts):
    """Stage completed texts sorted by PK, checking each file against the worker's report.

    Holds one bounded row batch of text at a time; O(T) read once.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = _text_schema()
    rows, held = [], 0
    with pq.ParquetWriter(path, schema, compression='zstd') as writer:
        for key in sorted(texts):
            value = texts[key]
            source = Path(value['text']['path'])
            encoded = source.read_bytes()
            if len(encoded) != value['text']['bytes'] or sha256(encoded).hexdigest() != value['text']['sha256']:
                raise ValueError('Staged text changed after its worker reported it')
            body_hex, parser, version = key
            rows.append(dict(body_sha=bytes.fromhex(body_hex), parser=parser, parser_version=version,
                text=encoded.decode(), page_offsets=value['page_offsets'], ocr_pages=value['ocr_pages'],
                text_sha256=bytes.fromhex(value['text']['sha256']), macos_build=value['macos_build']))
            held += len(encoded)
            if held >= STAGE_TEXT_BYTES:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                rows, held = [], 0
        if rows or not texts:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
    return len(texts)


def stage(planned, items, *, engine, work, worker_factory=ParserWorker, unreadable_store=None,
          parser_workers=1, parser_memory_bytes=PARSER_MEMORY_BYTES,
          strategy=None, page_deadline_seconds=PAGE_DEADLINE_SECONDS, origin=None,
          recovery=False, worker_memory_bytes=WORKER_MEMORY_BYTES, retain_quality_evidence=False, page_checkpoints=None):
    """Read one batch with bounded workers; stage its texts, readings rows and decisions.

    ``origin`` reads bodies from the archive origin rather than the plan's local raw root.
    """
    from congress_api.parsers.body_text import DEFAULT_STRATEGY, load_page_rule
    ParserWorkerPool.validate_budget(parser_workers, parser_memory_bytes, worker_memory_bytes)
    if recovery and any(recovery_versions().get(p) != v for p, v in planned['versions'].items()):
        raise ValueError('Unlimited body reads require the explicit recovery reading versions')
    strategy = strategy or DEFAULT_STRATEGY
    rule = load_page_rule(strategy)  # an engine this host lacks refuses before any body is read
    if page_checkpoints is not None and rule.checkpoint_identity is None:
        raise ValueError('Page checkpoints require a strategy with reproducible identity')
    work = Path(work).resolve()
    if page_checkpoints is not None:
        page_checkpoints = Path(page_checkpoints).resolve()
        if page_checkpoints.is_relative_to(work):
            raise ValueError('Page checkpoints must live outside the transient batch stage')
    work.mkdir(parents=True, exist_ok=False)
    texts_dir = work / 'texts'
    texts_dir.mkdir()
    diagnostics_dir = work / 'diagnostics'
    diagnostics_dir.mkdir()
    raw, decided_at = planned['local_root'], planned['decided_at']
    if origin is None and raw is None:
        raise ValueError('Body text reads need a local raw root or an origin')
    bodies_dir = work / 'bodies'  # each remote body's range cache, removed once its reading returns
    counters = dict(work_items=0, pending_reads=0, missing_pins=0, ocr_pending=0, unreadable=0, ocr_pages=0)
    rows, texts, decisions, reasons, body_outcomes = [], {}, [], {}, []

    def pending_read(reason):  # no verdict: the body stays listed, counted under what stopped its read
        counters['pending_reads'] += 1
        reasons[reason] = reasons.get(reason, 0) + 1

    def record_outcome(body_hex, parser, version, status, *, reading_status=None, reason=None,
                       error=None, peak_rss_bytes=None, worker_lifetime_peak_rss_bytes=None,
                       rss_samples=0):
        body_outcomes.append(dict(
            body_sha256=body_hex,
            parser=parser,
            parser_version=version,
            status=status,
            reading_status=reading_status,
            reason=reason,
            error=error,
            peak_rss_bytes=peak_rss_bytes,
            peak_rss_scope='request_sampled_worker_rss' if peak_rss_bytes is not None else None,
            rss_sample_interval_seconds=ParserWorker.rss_sample_interval_seconds if rss_samples else None,
            rss_samples=rss_samples,
            worker_lifetime_peak_rss_bytes=worker_lifetime_peak_rss_bytes,
        ))
        diagnostic = diagnostics_dir / (body_hex + '.txt')
        if diagnostic.is_file():
            body_outcomes[-1]['diagnostic_path'] = str(diagnostic)
        quality = sorted(diagnostics_dir.glob(body_hex + '.quality.*.jsonl'))
        if quality:
            body_outcomes[-1]['quality_evidence_paths'] = [str(path) for path in quality]
        with (work / 'body-outcomes.jsonl').open('a') as progress:
            progress.write(json.dumps(body_outcomes[-1], sort_keys=True) + '\n')

    def jobs():
        for item in items:
            counters['work_items'] += 1
            body_hex = item['body_sha'].hex()
            parser, version = item['parser'], item['parser_version']
            if item['physical_key'] is None:
                pending_read('no_captured_copy')
                record_outcome(body_hex, parser, version, 'pending', reason='no_captured_copy', error='no_captured_copy')
                continue
            validate_key(item['physical_key'])
            relative = Path(item['relative_path'])
            if relative.is_absolute() or '..' in relative.parts or body_object_digest(item['physical_key']) != body_hex:
                raise ValueError('Body copy path or key does not name its body')
            request = dict(body_sha=body_hex, parser=parser, stored_bytes=item['stored_bytes'],
                           texts=str(texts_dir), strategy=strategy, page_deadline_seconds=page_deadline_seconds,
                           unlimited_body_bytes=recovery, diagnostics=str(diagnostics_dir / (body_hex + '.txt')))
            if page_checkpoints is not None:
                request['page_checkpoints'] = str(page_checkpoints)
            if retain_quality_evidence:
                request.update(parser_version=version,
                               quality_evidence=str(diagnostics_dir / (body_hex + '.quality.jsonl')))
            if origin is not None:
                oversize = not recovery and item['stored_bytes'] is not None and item['stored_bytes'] > MAX_STORED_BYTES
                if not oversize and item['stored_bytes'] is None:
                    counters['missing_pins'] += 1  # a ranged read needs the captured size
                    record_outcome(body_hex, parser, version, 'pending', reason='missing_pins', error='missing_pins')
                    continue
                if not oversize and item.get('listing_refusal'):
                    pending_read(item['listing_refusal'])
                    record_outcome(body_hex, parser, version, 'pending',
                                   reason=item['listing_refusal'], error=item['listing_refusal'])
                    continue
                remote = dict(origin=origin, bucket=PUBLIC_BUCKET, key=item['physical_key'], md5=item.get('stored_md5'))
                if remote['md5'] is None and item.get('listed_etag'):
                    remote['etag'] = item['listed_etag']
                request.update(cache=str(bodies_dir / body_hex), remote=remote)
                yield item, request
                continue
            request['path'] = str(raw / relative)
            if item['stored_bytes'] is None:  # no pinned size: a local copy sized now and verified by hash
                try:
                    request.update(stored_bytes=(raw / relative).stat().st_size, unpinned=True)
                except OSError as error:
                    reason = _read_reason(error)
                    pending_read(reason)
                    record_outcome(body_hex, parser, version, 'pending',
                                   reason=reason, error=f'{type(error).__name__}: {error}')
                    continue
            yield item, request

    def invoke(worker, job):
        item, request = job
        if not recovery and request['stored_bytes'] > MAX_STORED_BYTES:
            return item, request, dict(status='completed', value=dict(
                row=dict(status='size_limit', error_type='stored_size_limit'))), {}
        resources = dict(peak_rss_bytes=None, worker_lifetime_peak_rss_bytes=None, rss_samples=0)
        try:
            for attempt in range(2):  # §6: a page past its deadline is a resource failure, retried once
                outcome = worker.parse(request['body_sha'], json.dumps(request, separators=(',', ':')).encode())
                sup_rss = getattr(worker, 'last_peak_rss_bytes', None)
                child_rss = (outcome.get('value', {}).get('worker_lifetime_peak_rss_bytes')
                             if isinstance(outcome, dict) and isinstance(outcome.get('value'), dict) else None)
                for key, candidate in (('peak_rss_bytes', sup_rss), ('worker_lifetime_peak_rss_bytes', child_rss)):
                    if type(candidate) is int and candidate > (resources[key] or 0):
                        resources[key] = candidate
                resources['rss_samples'] += getattr(worker, 'last_rss_samples', 0)
                if outcome['status'] != 'completed' or 'retry' not in outcome['value']:
                    return item, request, outcome, resources
            return item, request, dict(status='unreadable', reason=outcome['value']['retry']), resources
        finally:
            if 'cache' in request:
                shutil.rmtree(request['cache'], ignore_errors=True)

    with ParserWorkerPool('body_text', json.dumps(planned['versions'], sort_keys=True),
            'congress_api.lake.body_text:parse_payload', workers=parser_workers,
            memory_budget=parser_memory_bytes, worker_factory=worker_factory, **worker_limits(worker_memory_bytes)) as pool:
        for item, request, outcome, resources in pool.map(invoke, jobs()):
            body_hex, parser, version = request['body_sha'], item['parser'], item['parser_version']
            peak_rss = resources.get('peak_rss_bytes')
            if outcome['status'] == 'read_error':
                pending_read(outcome['reason'])
                record_outcome(body_hex, parser, version, 'pending', reason=outcome['reason'],
                               error=outcome.get('error') or outcome['reason'], **resources)
                continue
            if outcome['status'] == 'unreadable':
                identity = json.dumps([body_hex, parser, version, decided_at], separators=(',', ':'))
                decisions.append(dict(id=sha256(identity.encode()).hexdigest(), body_sha256=body_hex,
                    parser=parser, parser_version=version, reason=outcome['reason'],
                    decided_by='body_text', decided_at=decided_at, supersedes=None))
                err_msg = outcome.get('error') or (
                    f"{outcome['reason']} (peak_rss_bytes={peak_rss})" if peak_rss else outcome['reason']
                )
                diagnostic = Path(request['diagnostics'])
                if diagnostic.is_file():
                    err_msg = diagnostic.read_text()[-32768:]
                record_outcome(body_hex, parser, version, 'unreadable', reason=outcome['reason'],
                               error=err_msg, **resources)
                continue
            if outcome['status'] != 'completed':
                raise ValueError('Invalid body-text worker outcome')
            value = outcome['value']
            if value.get('read_error'):
                pending_read(value['read_error'])
                record_outcome(body_hex, parser, version, 'pending', reason=value['read_error'],
                               error=value.get('error') or value['read_error'], **resources)
                continue
            if value.get('pending'):
                counters['ocr_pending'] += 1
                record_outcome(body_hex, parser, version, 'pending', reason=value['pending'],
                               error=value.get('error') or value['pending'], **resources)
                continue
            if value['row']['status'] == 'completed':
                if 'text' not in value:
                    raise ValueError('A completed body-text reading must name its text file')
                texts[(body_hex, parser, version)] = value
                counters['ocr_pages'] += len(value['ocr_pages'])
            row_status = value['row']['status']
            row_err = value['row'].get('error_type')
            record_outcome(body_hex, parser, version, 'read', reading_status=row_status,
                           reason=row_err, error=value.get('error') or row_err, **resources)
            row = dict(value['row'], body_hex=body_hex, parser=parser, parser_version=version,
                       named_meetings=[], links=[])
            row['fingerprint_hex'] = row.pop('fingerprint', None)
            row.setdefault('fields', [])
            rows.append(row)
    parsed = work / 'parsed'
    parsed.mkdir()
    source = json_input(parsed, 'parsed_readings', rows, **readings._reading_fields())
    run_job(parsed, engine, inputs=[source], steps=[], outputs=[parquet_output(work, 'readings',
        f'SELECT {readings._LAKE_READING_COLUMNS} FROM parsed_readings', PK)])
    text_rows = _write_texts(work / 'body-text.parquet', texts)
    shutil.rmtree(texts_dir)
    shutil.rmtree(bodies_dir, ignore_errors=True)
    staged = dict(readings=work / 'readings.parquet', body_text=work / 'body-text.parquet',
                  readings_rows=len(rows), body_text_rows=text_rows, versions=planned['versions'],
                  unreadable_key=None, unreadable_pending=False, unreadable_stage=None,
                  pending_read_reasons=dict(sorted(reasons.items())),
                  body_outcomes=sorted(body_outcomes, key=lambda o: o['body_sha256']), **counters)
    if decisions:
        counters['unreadable'] = staged['unreadable'] = len(decisions)
        path = parsed / 'unreadable.jsonl'
        path.write_text(''.join(json.dumps(d, separators=(',', ':')) + '\n' for d in decisions))
        if unreadable_store is None:
            stage_root = work / 'unreadable-stage'
            stage_root.mkdir()
            imported = import_unreadable(BodyStore(LocalAdapter(stage_root)), path, decided_at=decided_at)
            finish_stage(stage_root, kind='unreadable', provenance=imported['key'], records=len(decisions),
                         inputs={}, extra=dict(decided_at=decided_at))
            staged.update(unreadable_pending=True, unreadable_stage=stage_root)
        else:
            imported = import_unreadable(unreadable_store, path, decided_at=decided_at)
        staged['unreadable_key'] = imported['key']
    return staged


def append(staged, *, engine, work, catalog_root, tables):
    """Commit `body_text` first, then `readings` (§6.6); each append anti-joins its PK."""
    from congress_api.lake import tables as lake_tables
    if staged.get('unreadable_pending'):
        raise ValueError('Pending unreadable decisions require durable import: '
            '.venv/bin/python -I -m congress_api.cli.provenance --stage ' + str(staged['unreadable_stage'])
            + ' --apply --bucket congressional-tech-raw')
    work = Path(work)
    definition = json.dumps(staged['versions'], sort_keys=True, separators=(',', ':'))
    result = {}
    for name, rows in (('body_text', 'body_text_rows'), ('readings', 'readings_rows')):
        result[name] = (lake_tables.append_rows(staged[name], engine=engine, work=work / name.replace('_', '-'),
            catalog_root=catalog_root, table=tables[name], keys=PK, definition=name + ':body_text:' + definition)
            if staged[rows] else None)
    return result


def create_table(*, engine, work, catalog_root, table, location, create_namespace=False):
    """Create `body_text`, partitioned like `readings` by (parser, parser_version)."""
    from congress_api.lake.tables import create_table as native_create
    return native_create(engine=engine, work=work, catalog_root=catalog_root, table=table, location=location,
        create_namespace=create_namespace, schema=json.loads(SCHEMA.read_text()), partition_spec={'spec-id': 0, 'fields': [
            {'source-id': 2, 'field-id': 1000, 'name': 'parser', 'transform': 'identity'},
            {'source-id': 3, 'field-id': 1001, 'name': 'parser_version', 'transform': 'identity'}]})


def run(*, engine, work, captures, decided_at, catalog_root, tables, local_root=None, origin=None, execute=False,
        unreadable_store=None, unreadable_files=(), max_cache_bytes=MAX_CACHE_BYTES, max_batch_items=MAX_BATCH_ITEMS,
        max_batches=None, worker_factory=ParserWorker, parser_workers=1,
        parser_memory_bytes=PARSER_MEMORY_BYTES, strategy=None,
        page_deadline_seconds=PAGE_DEADLINE_SECONDS, registry=None, filename_readings=None, body_listing=None,
        retain_quality_evidence=False, selection=None, page_checkpoints=None):
    """Plan once against current `readings`, then stage and commit batches in work-list order.

    Bodies come from ``local_root`` or ``origin`` (exactly one); ``body_listing`` pins MD5-less
    ``origin`` reads from one credentialed bucket LIST. Resuming is a fresh run: a new plan
    against the current tables, never a local journal.
    """
    from congress_api.lake.tables import resolve_tables, validate_catalog_authority
    validate_catalog_authority(engine, catalog_root)
    if (local_root is None) == (origin is None):
        raise ValueError('Name exactly one body source: a local raw root or an origin')
    if body_listing is not None and local_root is not None:
        raise ValueError('body_listing applies to remote origin reads, not local_root')
    if set(tables) != {'readings', 'body_text'}:
        raise ValueError('Body text needs the readings and body_text table identifiers')
    if execute and unreadable_store is None:
        raise ValueError('Execution requires an explicit durable unreadable store')
    if max_batches is not None and (type(max_batches) is not int or max_batches <= 0):
        raise ValueError('max_batches must be a positive integer')
    work = Path(work).resolve()
    current = resolve_tables(engine=engine, work=work / 'current', catalog_root=catalog_root,
                             tables=tables if selection else {'readings': tables['readings']})
    files = list(unreadable_files)
    if execute:
        from congress_api.retention.provenance_inventory import unreadable_inventory
        known = {r['key'] for r in files}
        files += [r for r in unreadable_inventory(unreadable_store, work=work / 'unreadable-inventory').files()
                  if r['key'] not in known]
    planned = plan(captures=captures, engine=engine, work=work / 'plan', decided_at=decided_at,
                   local_root=local_root, existing=current['readings'], unreadable_files=files, registry=registry,
                   filename_readings=filename_readings, body_listing=body_listing, selection=selection,
                   existing_text=current.get('body_text'))
    report = dict(status='planned', work_items=planned['work_items'], with_congress=planned['with_congress'],
                  by_parser=planned['by_parser'],
                  versions=planned['versions'], selection=planned['selection'],
                  unselected_current_attempts=planned['unselected_current_attempts'],
                  batches=[], pending_read_reasons={}, applied=False)
    if not execute:
        return report
    report['status'] = 'completed'
    for number, items in enumerate(batches(parquet_records(planned['work_list']),
                                           max_cache_bytes=max_cache_bytes, max_items=max_batch_items)):
        if max_batches is not None and number >= max_batches:
            report['status'] = 'partial'
            break
        batch_work = work / ('batch-' + str(number).zfill(6))
        staged = stage(planned, items, engine=engine, work=batch_work / 'stage', worker_factory=worker_factory,
                       unreadable_store=unreadable_store, parser_workers=parser_workers,
                       parser_memory_bytes=parser_memory_bytes, strategy=strategy,
                       page_deadline_seconds=page_deadline_seconds, origin=origin,
                       retain_quality_evidence=retain_quality_evidence, page_checkpoints=page_checkpoints)
        staged['append'] = append(staged, engine=engine, work=batch_work, catalog_root=catalog_root, tables=tables)
        report['applied'] |= any(value is not None for value in staged['append'].values())
        staged['body_text'].unlink()  # committed (or empty): the staged text copy is the batch's disk cost
        for reason, count in staged['pending_read_reasons'].items():
            report['pending_read_reasons'][reason] = report['pending_read_reasons'].get(reason, 0) + count
        report['batches'].append(staged)
    if any(b['pending_reads'] or b['missing_pins'] or b['ocr_pending'] for b in report['batches']) \
            and report['status'] == 'completed':
        report['status'] = 'pending'
    return report
