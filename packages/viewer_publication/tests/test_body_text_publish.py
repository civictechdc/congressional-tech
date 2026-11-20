"""Portable incremental `body_text` + multi-version Iceberg export + R2 publish tests."""
from __future__ import annotations

from hashlib import md5, sha256
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pyarrow as pa
import pyarrow.parquet as pq
import pymupdf
import pytest

from congress_api.lake import body_text, body_text_selection, readings, tables as lake_tables
from congress_api.lake.reading_versions import (
    HTML_CMS_CONTENT_SELECTION_VERSION,
    PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION,
)
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import json_input, parquet_output, run_job
from docspec_client.client import NativeDatasets
from viewer_publication import body_text_export, body_text_publish
from viewer_publication.body_text_ssot import BodyTextSSOT


def _scan_pdf(label: str) -> bytes:
    src = pymupdf.open()
    pg = src.new_page(width=600, height=120)
    pg.insert_text((24, 60), label, fontsize=18)
    png = pg.get_pixmap(dpi=150, colorspace=pymupdf.csRGB, alpha=False).tobytes('png')
    src.close()
    out = pymupdf.open()
    opg = out.new_page(width=600, height=120)
    opg.insert_image(pymupdf.Rect(0, 0, 600, 120), stream=png)
    raw = out.tobytes()
    out.close()
    return raw


def test_committed_v12_selection_manifest_loads_and_matches_pinned_digest():
    sel_path = body_text_publish.DEFAULT_SELECTION
    assert sel_path.is_file()
    loaded = body_text_selection.load(
        sel_path,
        {p: readings.current_version(p) for p in ('pdf_text', 'html_text', 'xml_text', 'warc')},
    )
    assert loaded['identity']['sha256'] == 'c270fe1bfa190976511f9077d9ae9b1bb45cea9c44f78ae6567564cff64fa91b'
    assert loaded['identity']['overrides'] == 22_921
    assert loaded['identity']['excluded_bodies'] == 416


def test_portable_incremental_pipeline_separates_sniff_table_and_exports_mixed_iceberg_versions(tmp_path):
    """Verifies end-to-end over real Iceberg tables:
    1. Sniff rows live in `sniff_readings` while `body_text` outcomes live in `body_text_readings`.
    2. Settled historical v12 rows (baseline + overrides + baseline error) are NOT re-extracted.
    3. Unsettled new bodies (`pdf` scan -> Tesseract 200 DPI, `html` CMS -> stripped CMS, `xml` -> XML)
       are extracted into `body_text` + `body_text_readings` under `portable_versions()`.
    4. `body_text_export.export` with `incremental_versions=portable_versions()` keeps overrides >
       baseline > incremental, refuses unreviewed displacement of baseline errors, and binds
       `BodyTextSSOT` directly to `detail.parquet` with zero handoff file.
    """
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    catalog_root = tmp_path / 'catalog'
    raw_root = tmp_path / 'raw'
    unreadable_root = tmp_path / 'unreadable'
    unreadable_root.mkdir()

    # Create three separate Iceberg tables: sniff_readings, body_text_readings, body_text
    sniff_tbl = {'namespace': ['test_ns'], 'name': 'readings_sniff'}
    bt_rd_tbl = {'namespace': ['test_ns'], 'name': 'body_text_readings'}
    bt_tbl = {'namespace': ['test_ns'], 'name': 'body_text'}

    body_text.create_readings_table(
        engine=engine, work=tmp_path / 'create-sniff', catalog_root=catalog_root,
        table=sniff_tbl, location=catalog_root / 'readings_sniff', create_namespace=True,
    )
    body_text.create_readings_table(
        engine=engine, work=tmp_path / 'create-bt-rd', catalog_root=catalog_root,
        table=bt_rd_tbl, location=catalog_root / 'body_text_readings',
    )
    body_text.create_table(
        engine=engine, work=tmp_path / 'create-bt', catalog_root=catalog_root,
        table=bt_tbl, location=catalog_root / 'body_text',
    )

    # Prepare raw bodies:
    # - hist_base: historical Apple Vision baseline PDF (settled, must NOT re-OCR)
    # - hist_override: historical PDF with an explicit repaired override (override must win)
    # - hist_err: historical PDF that failed at baseline (must stay settled & NOT be displaced)
    # - new_scan: newly captured scanned PDF -> OCR'd by Tesseract 5.5.4 bounded 200 DPI
    # - new_cms_html: newly captured committee CMS HTML with nav + retroactive 119th Congress banner
    # - new_xml: newly captured XML document
    cms_html = (
        b'<!DOCTYPE html><html><head><meta property="article:published_time" content="2019-03-26">'
        b'<link rel="canonical" href="https://budget.house.gov/news/2019/03/26/hearing"></head>'
        b'<body><nav class="site-nav">119th Congress Navigation Menu</nav>'
        b'<main><p>Chairman Yarmuth opening statement on the 2020 HHS budget hearing held March 26, 2019.</p></main>'
        b'<footer class="site-footer">Committee Footer Boilerplate</footer></body></html>'
    )
    bodies = {
        'hist_base': (b'%PDF-1.4 historical vision bytes', 'pdf'),
        'hist_override': (b'%PDF-1.4 historical override bytes', 'pdf'),
        'hist_err': (b'%PDF-1.4 historical corrupt bytes', 'pdf'),
        'new_scan': (_scan_pdf('Committee Hearing Witness Testimony 2026'), 'pdf'),
        'new_cms_html': (cms_html, 'html'),
        'new_xml': (b'<doc><p>Clean legislative XML summary.</p></doc>', 'xml'),
    }

    shas = {}
    cap_rows = []
    sniff_ver = readings.current_version('sniff')
    sniff_rows = []
    for idx, (name, (payload, fmt)) in enumerate(bodies.items()):
        bsha = sha256(payload).digest()
        shas[name] = bsha
        rel = Path(f'bodies/sha256/{bsha.hex()[:2]}/{bsha.hex()}')
        dest = raw_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        cap_rows.append(dict(
            receipt_key='receipts/documents/2026-11-19/r.jsonl.gz',
            receipt_line=idx + 1,
            capture_index=0,
            sha256=bsha,
            stored_suffix='',
            bytes=len(payload),
            stored_bytes=len(payload),
            stored_md5=md5(payload).digest(),
            retrieved_at=f'2026-11-19T00:00:0{idx}Z',
            mode='direct',
            url=f'https://docs.house.gov/{name}.{fmt}',
            requested_url=f'https://docs.house.gov/{name}.{fmt}',
            member_path=None,
            h_content_disposition=None,
            context_url=None,
            sniff_version=None,
            sniffed_format=None,
            intact=True,
        ))
        sniff_rows.append(dict(
            body_hex=bsha.hex(), parser='sniff', parser_version=sniff_ver,
            status='completed', format=fmt, intact=True, error_type=None, text_bytes=None, text_head=None,
            fingerprint_hex=None, content_date=None, fields=[], named_meetings=[], links=[],
        ))

    captures_pq = tmp_path / 'captures.parquet'
    cap_schema = pa.schema([
        ('receipt_key', pa.string()), ('receipt_line', pa.int64()), ('capture_index', pa.int32()),
        ('sha256', pa.binary(32)), ('stored_suffix', pa.string()), ('bytes', pa.int64()),
        ('stored_bytes', pa.int64()), ('stored_md5', pa.binary(16)), ('retrieved_at', pa.string()),
        ('mode', pa.string()), ('url', pa.string()), ('requested_url', pa.string()),
        ('member_path', pa.string()), ('h_content_disposition', pa.string()), ('context_url', pa.string()),
        ('sniff_version', pa.string()), ('sniffed_format', pa.string()), ('intact', pa.bool_()),
    ])
    pq.write_table(pa.Table.from_pylist(cap_rows, schema=cap_schema), captures_pq)

    # Populate sniff_readings Iceberg table (sniff rows ONLY)
    s_in = tmp_path / 'sniff_in'
    s_in.mkdir()
    run_job(
        tmp_path / 'sniff-stage', engine,
        inputs=[json_input(s_in, 'rows', sniff_rows, **readings._reading_fields())],
        steps=[],
        outputs=[parquet_output(tmp_path, 'sniff', f'SELECT {readings._LAKE_READING_COLUMNS} FROM rows', readings.PK)],
    )
    lake_tables.append_rows(
        tmp_path / 'sniff.parquet', engine=engine, work=tmp_path / 'append-sniff',
        catalog_root=catalog_root, table=sniff_tbl, keys=readings.PK, definition='test:sniff',
    )

    # Seed historical v12 baseline + override + baseline error into body_text & body_text_readings
    old_pdf_ver = '2980a4db41cbe1f559532557c5ad59f86691527c2569e8b3746c9d32c6f8fdfd'
    old_html_ver = 'f1cefe442182dc8e4c456359aebdb37e5c50db6b0abb669b303e05763feb94a3'
    old_xml_ver = '5a0768bcbaaaf7f67e29e2ff989689b62356579780f99e518d137f7b222c798c'
    repair_pdf_ver = '5d84e2bca02998e7b509ec12d2b5c17ef12d9da8a76c3e4b8e1f487b6f7c8f82'

    seed_texts = [
        dict(body_sha=shas['hist_base'], parser='pdf_text', parser_version=old_pdf_ver,
             text='Historical Apple Vision prose.', page_offsets=[0], ocr_pages=[1],
             text_sha256=sha256(b'Historical Apple Vision prose.').digest(), macos_build='25G5057c'),
        dict(body_sha=shas['hist_override'], parser='pdf_text', parser_version=old_pdf_ver,
             text='Old broken text.', page_offsets=[0], ocr_pages=[],
             text_sha256=sha256(b'Old broken text.').digest(), macos_build=None),
        dict(body_sha=shas['hist_override'], parser='pdf_text', parser_version=repair_pdf_ver,
             text='Qualified repaired PDF text.', page_offsets=[0], ocr_pages=[],
             text_sha256=sha256(b'Qualified repaired PDF text.').digest(), macos_build=None),
        # Also plant an unreviewed row at portable version for hist_err to prove baseline error blocks it!
        dict(body_sha=shas['hist_err'], parser='pdf_text', parser_version=PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION,
             text='Unreviewed text on baseline error body.', page_offsets=[0], ocr_pages=[],
             text_sha256=sha256(b'Unreviewed text on baseline error body.').digest(), macos_build=None),
    ]
    seed_bt_pq = tmp_path / 'seed-bt.parquet'
    pq.write_table(
        pa.Table.from_pylist(sorted(seed_texts, key=lambda r: (r['body_sha'], r['parser'], r['parser_version'])),
                             schema=body_text._text_schema()),
        seed_bt_pq,
    )
    lake_tables.append_rows(
        seed_bt_pq, engine=engine, work=tmp_path / 'append-seed-bt',
        catalog_root=catalog_root, table=bt_tbl, keys=readings.PK, definition='test:seed-bt',
    )

    seed_rd = [
        dict(body_hex=shas['hist_base'].hex(), parser='pdf_text', parser_version=old_pdf_ver,
             status='completed', error_type=None, text_bytes=30, text_head='Historical',
             fingerprint_hex=None, content_date=None, fields=[], named_meetings=[], links=[]),
        dict(body_hex=shas['hist_override'].hex(), parser='pdf_text', parser_version=old_pdf_ver,
             status='completed', error_type=None, text_bytes=16, text_head='Old',
             fingerprint_hex=None, content_date=None, fields=[], named_meetings=[], links=[]),
        dict(body_hex=shas['hist_override'].hex(), parser='pdf_text', parser_version=repair_pdf_ver,
             status='completed', error_type=None, text_bytes=28, text_head='Qualified',
             fingerprint_hex=None, content_date=None, fields=[], named_meetings=[], links=[]),
        dict(body_hex=shas['hist_err'].hex(), parser='pdf_text', parser_version=old_pdf_ver,
             status='error', error_type='ExtractionError', text_bytes=None, text_head=None,
             fingerprint_hex=None, content_date=None, fields=[], named_meetings=[], links=[]),
    ]
    r_in = tmp_path / 'rd_in'
    r_in.mkdir()
    run_job(
        tmp_path / 'seed-rd-stage', engine,
        inputs=[json_input(r_in, 'rows', seed_rd, **readings._reading_fields())],
        steps=[],
        outputs=[parquet_output(tmp_path, 'seed_rd', f'SELECT {readings._LAKE_READING_COLUMNS} FROM rows', readings.PK)],
    )
    lake_tables.append_rows(
        tmp_path / 'seed_rd.parquet', engine=engine, work=tmp_path / 'append-seed-rd',
        catalog_root=catalog_root, table=bt_rd_tbl, keys=readings.PK, definition='test:seed-rd',
    )

    qual_md = tmp_path / 'qualification.md'
    qual_md.write_text('# Qualification fixture\n')
    sel_gz = tmp_path / 'selection.json.gz'
    import gzip
    sel_doc = {
        'version': 2,
        'baseline_versions': {
            'pdf_text': old_pdf_ver,
            'html_text': old_html_ver,
            'xml_text': old_xml_ver,
        },
        'qualification': {'path': 'qualification.md', 'sha256': sha256(qual_md.read_bytes()).hexdigest()},
        'overrides': [
            {
                'body_sha256': shas['hist_override'].hex(),
                'parser': 'pdf_text',
                'parser_version': repair_pdf_ver,
                'status': 'completed',
                'text_sha256': sha256(b'Qualified repaired PDF text.').hexdigest(),
            }
        ],
        'excluded_bodies': [],
    }
    sel_gz.write_bytes(gzip.compress(json.dumps(sel_doc).encode(), mtime=0))

    # Run incremental portable producer! Only new_scan, new_cms_html, new_xml should be planned & extracted.
    report = body_text.run(
        engine=engine,
        work=tmp_path / 'inc-run',
        captures=captures_pq,
        decided_at='2026-11-19T21:00:00Z',
        catalog_root=catalog_root,
        tables={'body_text': bt_tbl, 'readings': bt_rd_tbl},
        sniff_table=sniff_tbl,
        local_root=raw_root,
        execute=True,
        unreadable_store=BodyStore(LocalAdapter(unreadable_root)),
        selection=sel_gz,
        strategy=body_text.PORTABLE_STRATEGY,
        parser_workers=1,
    )
    assert report['status'] == 'completed'
    assert report['work_items'] == 3
    assert {r['parser']: r['n'] for r in report['by_parser']} == {'html_text': 1, 'pdf_text': 1, 'xml_text': 1}

    # Re-planning immediately must find 0 remaining work items!
    replan = body_text.run(
        engine=engine,
        work=tmp_path / 'inc-replan',
        captures=captures_pq,
        decided_at='2026-11-19T21:05:00Z',
        catalog_root=catalog_root,
        tables={'body_text': bt_tbl, 'readings': bt_rd_tbl},
        sniff_table=sniff_tbl,
        local_root=raw_root,
        execute=False,
        selection=sel_gz,
        strategy=body_text.PORTABLE_STRATEGY,
    )
    assert replan['work_items'] == 0

    # Export over the real Iceberg pins with incremental_versions=portable_versions()
    pins = lake_tables.resolve_tables(
        engine=engine, work=tmp_path / 'pins', catalog_root=catalog_root,
        tables={'body_text': bt_tbl, 'readings': bt_rd_tbl},
    )
    detail_pq = tmp_path / 'detail.parquet'
    ordered_names = ['hist_base', 'hist_override', 'hist_err', 'new_scan', 'new_cms_html', 'new_xml']
    pq.write_table(pa.table({
        'link_key': [f'k{i}'.encode() for i in range(len(ordered_names))],
        'saved_body': pa.array([shas[n] for n in ordered_names], pa.binary(32)),
        'filename': [f'{n}.doc' for n in ordered_names],
        'title': ordered_names,
        'format': ['pdf', 'pdf', 'pdf', 'pdf', 'html', 'xml'],
        'congress': [119] * len(ordered_names),
        'chambers': [['house']] * len(ordered_names),
        'committee_keys': [['hsbu00']] * len(ordered_names),
        'document_date': ['2026-11-19'] * len(ordered_names),
    }), detail_pq)

    export_dir = tmp_path / 'export'
    pointer = body_text_export.export(
        engine=engine,
        work=export_dir,
        body_text=pins['body_text'],
        readings_table=pins['readings'],
        detail=detail_pq,
        release_id='a' * 64,
        selection=sel_gz,
        incremental_versions=body_text.portable_versions(),
    )
    assert pointer['rows'] == 5  # hist_err excluded (baseline status='error' blocks unreviewed incremental text!)
    assert pointer['incremental_versions'] == body_text.portable_versions()
    assert pointer['coverage']['readings'] == {
        'html_text:completed': 1,
        'pdf_text:completed': 3,
        'pdf_text:error': 1,
        'xml_text:completed': 1,
    }

    # Verify BodyTextSSOT binds directly to detail.parquet with zero handoff file!
    ssot = BodyTextSSOT(export_dir, verify_file_sha256=True)
    docs = {d['filename']: d for d in ssot.iter_serenedb_documents(detail_pq)}
    assert docs['hist_base.doc']['text'] == 'Historical Apple Vision prose.'
    assert docs['hist_override.doc']['text'] == 'Qualified repaired PDF text.'
    assert docs['hist_err.doc']['text_status'] == 'missing' and docs['hist_err.doc']['text'] is None
    assert 'Committee Hearing Witness Testimony 2026' in docs['new_scan.doc']['text']
    assert 'Chairman Yarmuth opening statement' in docs['new_cms_html.doc']['text']
    assert '119th Congress' not in docs['new_cms_html.doc']['text']
    assert 'Committee Footer Boilerplate' not in docs['new_cms_html.doc']['text']
    assert docs['new_xml.doc']['text'] == 'Clean legislative XML summary.'


def test_upload_part_retries_transient_503_without_retrying_conditional_mutations(monkeypatch):
    monkeypatch.setattr(body_text_publish.time, 'sleep', lambda _: None)
    calls = []

    def upload_part(**kwargs):
        calls.append(('upload_part', kwargs['PartNumber']))
        if len(calls) < 3:
            raise ClientError(
                {'Error': {'Code': 'SlowDown', 'Message': 'Reduce request rate'},
                 'ResponseMetadata': {'HTTPStatusCode': 503}},
                'UploadPart',
            )
        return {'ETag': '"ok"'}

    def put_object(**kwargs):
        calls.append(('put_object', kwargs['Key']))
        raise ClientError(
            {'Error': {'Code': 'SlowDown', 'Message': '503'},
             'ResponseMetadata': {'HTTPStatusCode': 503}},
            'PutObject',
        )

    client = SimpleNamespace(upload_part=upload_part, put_object=put_object)
    body_text_publish.configure_upload_part_retries(client, max_attempts=4, base_delay=0.01)
    assert client.upload_part(PartNumber=7) == {'ETag': '"ok"'}
    assert calls == [('upload_part', 7), ('upload_part', 7), ('upload_part', 7)]
    with pytest.raises(ClientError):
        client.put_object(Key='derived/body_text/current.json')
    assert calls[-1] == ('put_object', 'derived/body_text/current.json')
