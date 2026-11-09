"""Small bodies for the body-text parsers, built in the test rather than checked in as bytes."""
import gzip
import hashlib
import io

import os

import pyarrow as pa
import pyarrow.parquet as pq

STAMP = '2026-11-08T12:00:00Z'
TABLES = dict(readings=dict(namespace=['archive'], name='readings'),
              body_text=dict(namespace=['archive'], name='body_text'))

PAGE_ONE = 'Opening statement of the chairman on the appropriations hearing for fiscal year 2027.'
PAGE_TWO = 'Testimony of the witness continues on the second page of the printed record.'


def two_page_pdf():
    import pymupdf
    document = pymupdf.open()
    for text in (PAGE_ONE, PAGE_TWO):
        page = document.new_page()
        page.insert_text((72, 72), text, fontsize=9)
    return document.tobytes()


def scanned_pdf():
    """One text page and one page that draws only an image: the second needs OCR."""
    import pymupdf
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), PAGE_ONE, fontsize=9)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 32, 32), False)
    pixmap.clear_with(180)
    document.new_page().insert_image(pymupdf.Rect(72, 72, 400, 400), pixmap=pixmap)
    return document.tobytes()


HTML = (b'<html><head><title>Hearing transcript</title></head><body><pre>'
        b'STATEMENT OF THE WITNESS\n\n    Mr. Chairman, thank you.\n</pre></body></html>')
XML = b'<?xml version="1.0"?><hearing><title>Oversight</title><para>The committee met.</para></hearing>'


def warc_member(payload, *, content_type='text/html', target='https://example.house.gov/statement'):
    """One gzip WARC response member, as Common Crawl stores it, its payload digest stated."""
    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter
    out = io.BytesIO()
    writer = WARCWriter(out, gzip=True)
    headers = StatusAndHeaders('200 OK', [('Content-Type', content_type)], protocol='HTTP/1.1')
    writer.write_record(writer.create_warc_record(target, 'response', payload=io.BytesIO(payload),
                                                  http_headers=headers))
    return out.getvalue()


def raw_inputs(root, bodies, *, sniff_version, gzip_stored=(), captured_sniff=True):
    """A local raw root, a captures file and sniff readings for ``{name: (bytes, format)}``.

    With ``captured_sniff`` the captures record each format at ``sniff_version`` (the fetcher's
    sniff); the sniff rows are returned either way. Returns (captures, sniff rows, raw, digests).
    """
    raw = root / 'raw'
    captures, sniff, digests = [], [], {}
    for position, (name, (data, fmt)) in enumerate(bodies.items()):
        digest = hashlib.sha256(data).digest()
        digests[name] = digest
        stored = gzip.compress(data, mtime=0) if name in gzip_stored else data
        suffix = '.gz' if name in gzip_stored else ''
        key = 'bodies/sha256/' + digest.hex()[:2] + '/' + digest.hex() + suffix
        (raw / key).parent.mkdir(parents=True, exist_ok=True)
        (raw / key).write_bytes(stored)
        captures.append(dict(sha256=digest, bytes=len(data), stored_bytes=len(stored), stored_suffix=suffix,
                             stored_md5=hashlib.md5(stored).digest(),
                             retrieved_at=1_700_000_000_000_000 + position,
                             **(dict(sniffed_format=fmt, sniff_version=sniff_version) if captured_sniff else {})))
        sniff.append(dict(body_sha=digest, parser='sniff', parser_version=sniff_version,
                          status='completed', format=fmt))
    schema = pa.schema([('sha256', pa.binary(32)), ('bytes', pa.int64()), ('stored_bytes', pa.int64()),
                        ('stored_suffix', pa.string()), ('stored_md5', pa.binary(16)),
                        ('retrieved_at', pa.timestamp('us', tz='UTC')),
                        ('sniffed_format', pa.string()), ('sniff_version', pa.string()), ('intact', pa.bool_())])
    path = root / 'captures.parquet'
    pq.write_table(pa.Table.from_pylist(captures, schema=schema), path)
    return path, sniff, raw, digests


def lake(tmp_path, bodies, **kwargs):
    """Empty readings and body_text tables in a local catalog, and the run arguments over ``bodies``.

    Returns (run arguments, {body digest: name}).
    """
    from congress_api.lake import body_text, readings
    from congress_api.retention.body_store import BodyStore, LocalAdapter
    from docspec_client.client import NativeDatasets
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    captures, _, raw, digests = raw_inputs(tmp_path / 'source', bodies,
                                           sniff_version=readings.current_version('sniff'), **kwargs)
    catalog = tmp_path / 'catalog'
    readings.create_table(engine=engine, work=tmp_path / 'create-readings', catalog_root=catalog,
                          table=TABLES['readings'], location=tmp_path / 'readings-table', create_namespace=True)
    body_text.create_table(engine=engine, work=tmp_path / 'create-text', catalog_root=catalog,
                           table=TABLES['body_text'], location=tmp_path / 'text-table')
    args = dict(engine=engine, captures=captures, local_root=raw, decided_at=STAMP, catalog_root=catalog,
                tables=TABLES, unreadable_store=BodyStore(LocalAdapter(tmp_path / 'raw-provenance')))
    return args, {digest: name for name, digest in digests.items()}


def committed(args, work, table, columns):
    """The rows a later run would plan against: ``columns`` of the committed ``table``."""
    from congress_api.lake.tables import resolve_tables, table_input
    from congress_api.retention.provenance import run_job
    pin = resolve_tables(engine=args['engine'], work=work / 'resolve', catalog_root=args['catalog_root'],
                         tables={'t': TABLES[table]})['t']
    return run_job(work / 'read', args['engine'], inputs=[table_input('t', pin)], steps=[], outputs=[],
                   queries=[dict(name='rows', sql=f"SELECT encode(body_sha,'hex') AS body,{columns} FROM t")])['rows']
