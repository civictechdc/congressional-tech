"""The body-text producer: one read per body writes `body_text` and its `readings` row.

Data model §6.6 (and §6.2 for the narrow readings row). The work list is every body whose
pinned sniff format is `pdf`, `html`, `xml` or `warc` with no `readings` row at that format's
declared body-text version and no active `unreadable` decision; an `error` or `size_limit`
row settles a body too. Per batch, `body_text` commits first and `readings` second, each
through `append_rows`' PK anti-join, so a crash between the commits leaves the body on the
list and its retry appends no second text row.

Reads use the copy each capture recorded (as `readings.plan(captured_copies=True)` picks it) in a
local raw root; R2 ranged reads are not wired here yet. A worker returns its text as a file (path, bytes,
SHA-256), so no text crosses the supervisor's 8 MiB pipe; the supervisor's timeout is a fixed
document deadline and each page has its own deadline inside the worker. Batches are sized by
an upper bound on their text bytes against ``max_cache_bytes``.

Cost: one native plan (two narrow scans of captures and one of readings, all joined to the
candidate set); O(B) worker time per body in its bytes; O(T) disk per batch in its text.
"""
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat

from congress_api.lake import readings
from congress_api.lake.tables import table_input
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.parser_worker import ParserWorker, ParserWorkerPool, reading_input
from congress_api.retention.provenance import (field, finish_stage, import_unreadable, instant, json_input,
    parquet_output, parquet_records, run_job)

ROOT = Path(__file__).resolve().parents[5]
# Read here, not through tables.LAKE_SCHEMA_PATHS, whose module every reading version's evidence hashes.
SCHEMA = ROOT / 'model/lake/body-text.schema.json'
PK = readings.PK
FORMAT_PARSERS = {'pdf': 'pdf_text', 'html': 'html_text', 'xml': 'xml_text', 'warc': 'warc'}
PARSERS = tuple(FORMAT_PARSERS.values())
MAX_STORED_BYTES = readings.MAX_STORED_BYTES
MAX_DECODED_BYTES = readings.MAX_DECODED_BYTES
WORKER_MEMORY_BYTES = readings.WORKER_MEMORY_BYTES
# A fixed bound per document (the supervisor kills the worker past it) and per page (inside the
# worker). Both are first-pass values for the census to confirm (plan §1, "Census").
DOCUMENT_DEADLINE_SECONDS = 1800
PAGE_DEADLINE_SECONDS = 60
MAX_CACHE_BYTES = 8 << 30
MAX_BATCH_ITEMS = 4096
STAGE_TEXT_BYTES = 64 << 20


def current_versions():
    """The declared version of each body-text parser (reading_versions)."""
    return {parser: readings.current_version(parser) for parser in PARSERS}


def worker_limits():
    """The supervisor policy: the document deadline replaces the readings 15 s timeout."""
    return dict(timeout_seconds=DOCUMENT_DEADLINE_SECONDS, memory_bytes=WORKER_MEMORY_BYTES,
                max_input_bytes=65536, max_output_bytes=8 << 20)


def plan(*, captures, engine, work, decided_at, local_root, existing=None, unreadable_files=(),
         registry=None):
    """Materialize the ordered work list in one native job, opening no body.

    The newest captured bodies come first, so weekly bodies lead a backfill.
    """
    from congress_api.lake import compatible_versions
    instant(decided_at)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    versions = current_versions()
    pins = compatible_versions.current_pins()
    entries = compatible_versions.load_registry(current=pins, **({} if registry is None else dict(path=registry)))
    sniff_entries = [e for e in entries if e['parser'] == 'sniff']
    selected = {'sniff': pins['sniff'], **versions}
    unreadable_schema = dict(id='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8', supersedes='Utf8')
    inputs = [json_input(work, 'parser_versions', [dict(parser=p, version=v) for p, v in selected.items()],
                         parser='Utf8', version='Utf8'),
              json_input(work, 'format_parsers', [dict(format=f, parser=p) for f, p in FORMAT_PARSERS.items()],
                         format='Utf8', parser='Utf8'),
              compatible_versions.accepted_versions_input(work, sniff_entries, pins={'sniff': pins['sniff']}),
              table_input('captures', captures)]
    if unreadable_files:
        inputs.append(dict(name='unreadable', kind='json_lines', files=list(unreadable_files),
            schema=dict(fields=[field(k, v) for k, v in unreadable_schema.items()], metadata={})))
    else:
        inputs.append(json_input(work, 'unreadable', [], **unreadable_schema))
    steps = []
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
        dict(name='active_unreadable', sql='''SELECT u.* FROM unreadable u
            WHERE NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id)'''),
        # Body-text rows at their declared versions: the four (parser, version) partitions only.
        dict(name='settled', materialize=True, sql='''SELECT r.body_sha,r.parser FROM parser_versions v
            JOIN readings r ON r.parser=v.parser AND r.parser_version=v.version WHERE v.parser<>'sniff' '''),
        dict(name='candidates', materialize=True, sql='''SELECT f.body_sha,f.format,p.parser,v.version AS parser_version
            FROM sniff_facts f JOIN format_parsers p ON f.format=p.format JOIN parser_versions v ON v.parser=p.parser
            WHERE NOT EXISTS (SELECT 1 FROM settled s WHERE s.body_sha=f.body_sha AND s.parser=p.parser)
              AND NOT EXISTS (SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(f.body_sha,'hex')
                AND u.parser=p.parser AND u.parser_version=v.version)'''),
        # Captures grouped only after the semi-join to the candidates (AGENTS.md pushdown rule).
        dict(name='body_storage', materialize=True, sql="""SELECT c.sha256 AS body_sha,
            coalesce(c.stored_suffix,'.gz') AS stored_suffix,
            concat('bodies/sha256/',substr(encode(c.sha256,'hex'),1,2),'/',encode(c.sha256,'hex'),
                coalesce(c.stored_suffix,'.gz')) AS physical_key,
            max(c.bytes) AS decoded_bytes,max(c.stored_bytes) AS stored_bytes,max(c.retrieved_at) AS latest,
            min(c.bytes)<>max(c.bytes) OR min(c.stored_bytes)<>max(c.stored_bytes) AS conflict
            FROM candidates k RIGHT SEMI JOIN captures c ON k.body_sha=c.sha256
            GROUP BY c.sha256,coalesce(c.stored_suffix,'.gz')"""),
        dict(name='body_copies', materialize=True, sql='''SELECT * FROM (SELECT *,row_number() OVER (
            PARTITION BY body_sha ORDER BY stored_bytes IS NULL,
                CASE stored_suffix WHEN '' THEN 0 WHEN '.gz' THEN 1 ELSE 2 END) AS choice
            FROM body_storage) WHERE choice=1'''),
        dict(name='pending_bodies', materialize=True, sql='''SELECT k.body_sha,k.format,k.parser,k.parser_version,
            s.physical_key,s.physical_key AS relative_path,s.stored_bytes,s.decoded_bytes,
            coalesce(s.conflict,false) AS conflict,
            cast(row_number() OVER (ORDER BY s.latest DESC NULLS LAST,k.body_sha) AS BIGINT) AS position
            FROM candidates k LEFT JOIN body_copies s ON k.body_sha=s.body_sha'''),
    ]
    checks = run_job(work, engine, inputs=inputs, steps=steps,
        outputs=[parquet_output(work, 'work-list', 'SELECT * FROM pending_bodies', ['position'])],
        queries=[dict(name='work_items', sql='SELECT count(*) AS n FROM pending_bodies'),
                 dict(name='by_parser', sql='''SELECT parser,count(*) AS n,coalesce(sum(stored_bytes),0) AS stored_bytes
                    FROM pending_bodies GROUP BY parser ORDER BY parser'''),
                 dict(name='conflicts', sql='''SELECT count(*) AS n FROM (SELECT body_sha FROM sniff_conflicts
                    UNION ALL SELECT body_sha FROM pending_bodies WHERE conflict
                    UNION ALL SELECT body_sha FROM body_storage WHERE stored_suffix NOT IN ('','.gz','.pdf'))''')])
    if checks['conflicts'][0]['n']:
        raise ValueError('Conflicting sniff facts or captured copies for body-text work')
    return dict(status='planned', work=work, work_list=work / 'work-list.parquet', versions=versions,
                work_items=checks['work_items'][0]['n'], by_parser=checks['by_parser'],
                local_root=Path(local_root).resolve(), decided_at=decided_at)


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
                data = entity.read(MAX_DECODED_BYTES + 1)
            finally:
                if entity is not stream:
                    entity.close()
    return None if len(data) > MAX_DECODED_BYTES else data


def _sniff_format(payload):
    from congress_api.retention.sniff import read_sniff
    row = read_sniff(lambda start, length: payload[start:start + length], stored_size=len(payload))
    return row.get('format') if row.get('status') == 'completed' else None


_STRATEGIES = {}


def parse_payload(payload):
    """Worker callable: read one body, derive its reading, write its text to the named directory.

    Returns ``read_error`` (no verdict), ``pending`` (OCR needed, no engine), ``retry`` (a page
    outlived its deadline) or a ``row`` with ``text`` naming the file, its bytes and SHA-256.
    """
    from congress_api.parsers import body_text as derivation
    request = json.loads(payload)
    try:
        data = _read_decoded(request)
    except (OSError, EOFError) as error:
        return dict(read_error=type(error).__name__)
    if data is None:
        return dict(row=dict(status='error', error_type='decoded_size_limit'))
    spec = request['strategy']
    if spec not in _STRATEGIES:  # one strategy object per worker process, reused across bodies
        _STRATEGIES[spec] = derivation.load_strategy(spec)
    try:
        reading = derivation.derive(data, request['parser'], strategy=_STRATEGIES[spec],
            page_deadline_seconds=request['page_deadline_seconds'], sniff_format=_sniff_format,
            max_bytes=MAX_DECODED_BYTES)
    except derivation.OcrRequired:
        return dict(pending='ocr_required')
    except derivation.PageDeadline:
        return dict(retry='page_deadline')
    del data
    value = dict(row=reading.row())
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
          parser_workers=1, parser_memory_bytes=readings.PARSER_MEMORY_BYTES,
          strategy=None, page_deadline_seconds=PAGE_DEADLINE_SECONDS):
    """Read one batch with bounded workers; stage its texts, readings rows and decisions."""
    from congress_api.parsers.body_text import DEFAULT_STRATEGY
    ParserWorkerPool.validate_budget(parser_workers, parser_memory_bytes, WORKER_MEMORY_BYTES)
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    texts_dir = work / 'texts'
    texts_dir.mkdir()
    raw, decided_at = planned['local_root'], planned['decided_at']
    counters = dict(work_items=0, pending_reads=0, ocr_pending=0, unreadable=0, ocr_pages=0)
    rows, texts, decisions = [], {}, []

    def jobs():
        for item in items:
            counters['work_items'] += 1
            body_hex = item['body_sha'].hex()
            if item['physical_key'] is None:
                counters['pending_reads'] += 1
                continue
            validate_key(item['physical_key'])
            relative = Path(item['relative_path'])
            if relative.is_absolute() or '..' in relative.parts or body_object_digest(item['physical_key']) != body_hex:
                raise ValueError('Body copy path or key does not name its body')
            request = dict(path=str(raw / relative), body_sha=body_hex, parser=item['parser'],
                           stored_bytes=item['stored_bytes'], texts=str(texts_dir),
                           strategy=strategy or DEFAULT_STRATEGY, page_deadline_seconds=page_deadline_seconds)
            if item['stored_bytes'] is None:  # no pinned size: a local copy sized now and verified by hash
                try:
                    request.update(stored_bytes=(raw / relative).stat().st_size, unpinned=True)
                except OSError:
                    counters['pending_reads'] += 1
                    continue
            yield item, request

    def invoke(worker, job):
        item, request = job
        if request['stored_bytes'] > MAX_STORED_BYTES:
            return item, request, dict(status='completed', value=dict(
                row=dict(status='size_limit', error_type='stored_size_limit')))
        for attempt in range(2):  # §6: a page past its deadline is a resource failure, retried once
            outcome = worker.parse(request['body_sha'], json.dumps(request, separators=(',', ':')).encode())
            if outcome['status'] != 'completed' or 'retry' not in outcome['value']:
                return item, request, outcome
        return item, request, dict(status='unreadable', reason=outcome['value']['retry'])

    with ParserWorkerPool('body_text', json.dumps(planned['versions'], sort_keys=True),
            'congress_api.lake.body_text:parse_payload', workers=parser_workers,
            memory_budget=parser_memory_bytes, worker_factory=worker_factory, **worker_limits()) as pool:
        for item, request, outcome in pool.map(invoke, jobs()):
            body_hex, parser, version = request['body_sha'], item['parser'], item['parser_version']
            if outcome['status'] == 'read_error':
                counters['pending_reads'] += 1
                continue
            if outcome['status'] == 'unreadable':
                identity = json.dumps([body_hex, parser, version, decided_at], separators=(',', ':'))
                decisions.append(dict(id=sha256(identity.encode()).hexdigest(), body_sha256=body_hex,
                    parser=parser, parser_version=version, reason=outcome['reason'],
                    decided_by='body_text', decided_at=decided_at, supersedes=None))
                continue
            if outcome['status'] != 'completed':
                raise ValueError('Invalid body-text worker outcome')
            value = outcome['value']
            if value.get('read_error'):
                counters['pending_reads'] += 1
                continue
            if value.get('pending'):
                counters['ocr_pending'] += 1
                continue
            if value['row']['status'] == 'completed':
                if 'text' not in value:
                    raise ValueError('A completed body-text reading must name its text file')
                texts[(body_hex, parser, version)] = value
                counters['ocr_pages'] += len(value['ocr_pages'])
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
    staged = dict(readings=work / 'readings.parquet', body_text=work / 'body-text.parquet',
                  readings_rows=len(rows), body_text_rows=text_rows, versions=planned['versions'],
                  unreadable_key=None, unreadable_pending=False, unreadable_stage=None, **counters)
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


def run(*, engine, work, captures, local_root, decided_at, catalog_root, tables, execute=False,
        unreadable_store=None, unreadable_files=(), max_cache_bytes=MAX_CACHE_BYTES, max_batch_items=MAX_BATCH_ITEMS,
        max_batches=None, worker_factory=ParserWorker, parser_workers=1,
        parser_memory_bytes=readings.PARSER_MEMORY_BYTES, strategy=None,
        page_deadline_seconds=PAGE_DEADLINE_SECONDS, registry=None):
    """Plan once against current `readings`, then stage and commit batches in work-list order.

    Resuming is a fresh run: a new plan against the current tables, never a local journal.
    """
    from congress_api.lake.tables import resolve_tables, validate_catalog_authority
    validate_catalog_authority(engine, catalog_root)
    if set(tables) != {'readings', 'body_text'}:
        raise ValueError('Body text needs the readings and body_text table identifiers')
    if execute and unreadable_store is None:
        raise ValueError('Execution requires an explicit durable unreadable store')
    if max_batches is not None and (type(max_batches) is not int or max_batches <= 0):
        raise ValueError('max_batches must be a positive integer')
    work = Path(work).resolve()
    current = resolve_tables(engine=engine, work=work / 'current', catalog_root=catalog_root,
                             tables={'readings': tables['readings']})['readings']
    files = list(unreadable_files)
    if execute:
        from congress_api.retention.provenance_inventory import unreadable_inventory
        known = {r['key'] for r in files}
        files += [r for r in unreadable_inventory(unreadable_store, work=work / 'unreadable-inventory').files()
                  if r['key'] not in known]
    planned = plan(captures=captures, engine=engine, work=work / 'plan', decided_at=decided_at,
                   local_root=local_root, existing=current, unreadable_files=files, registry=registry)
    report = dict(status='planned', work_items=planned['work_items'], by_parser=planned['by_parser'],
                  versions=planned['versions'], batches=[], applied=False)
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
                       page_deadline_seconds=page_deadline_seconds)
        staged['append'] = append(staged, engine=engine, work=batch_work, catalog_root=catalog_root, tables=tables)
        report['applied'] |= any(value is not None for value in staged['append'].values())
        report['batches'].append(staged)
    if any(b['pending_reads'] or b['ocr_pending'] for b in report['batches']) and report['status'] == 'completed':
        report['status'] = 'pending'
    return report
