"""Recovery keeps strong copy pins and the declared rendering resolution."""
import importlib.util
from pathlib import Path

import pytest


def command():
    spec = importlib.util.spec_from_file_location('retry_body_text', Path(__file__).parents[1] / 'retry_body_text.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_copy_probe_retries_an_unpinned_response_and_preserves_observations(monkeypatch):
    module = command()
    closed = []
    class Body:
        def close(self): closed.append(True)
    class Client:
        calls = 0
        def __init__(self,*args,**kwargs): pass
        def get_object(self,**kwargs):
            Client.calls += 1
            return dict(Body=Body(),ContentRange='' if Client.calls==1 else 'bytes 0-0/123',
                        ETag='"strong"',ResponseMetadata={'HTTPStatusCode':200 if Client.calls==1 else 206})
    monkeypatch.setattr(module,'PublicOrigin',Client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    item=dict(body_sha256='a'*64,physical_key='bodies/sha256/aa/'+'a'*64,stored_bytes=None)
    result=module.observed_copy(item,'https://example.invalid')
    assert result['stored_bytes']==123 and result['listed_etag']=='"strong"'
    assert result['captured_stored_bytes'] is None and 'probe_error' not in result
    assert [r['status'] for r in result['copy_observations']]==['unpinned_response','refused','observed']
    assert len(closed)==2 and item['stored_bytes'] is None


def test_copy_probe_never_accepts_a_weak_etag(monkeypatch):
    module=command()
    class Body:
        def close(self): pass
    class Client:
        def __init__(self,*args,**kwargs): pass
        def get_object(self,**kwargs):
            return dict(Body=Body(),ContentRange='bytes 0-0/1',ETag='W/"weak"',ResponseMetadata={'HTTPStatusCode':206})
    monkeypatch.setattr(module,'PublicOrigin',Client)
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    result=module.observed_copy(dict(physical_key='body',stored_bytes=1),'https://example.invalid')
    assert 'strong ETag' in result['probe_error']
    assert sum(r['status']=='refused' for r in result['copy_observations'])==3


@pytest.mark.parametrize('identity', [None, {'backend': 'scripted'}])
def test_recovery_lifts_pixel_exclusion_without_changing_resolution(monkeypatch, identity):
    from congress_api.parsers import body_text
    from spicy_docs.extraction import DefaultReader, ExtractionError
    reader=DefaultReader(dpi=200,raw_rgb=True)
    strategy=object()
    monkeypatch.setattr(body_text,'apple_vision',lambda:body_text.PageRule(strategy,reader,identity))
    with pytest.raises(ExtractionError,match='max_pixels'):
        reader.check_pixels(5000,5000)
    rule=body_text.recovery_apple_vision()
    rule.reader.check_pixels(5000,5000)
    assert rule.strategy is strategy and rule.reader.dpi==200 and rule.reader.raw_rgb
    if identity is None:
        assert rule.checkpoint_identity is None  # A missing policy cannot become reusable by lifting a bound.
    else:
        assert rule.checkpoint_identity == dict(identity, max_pixels=(1 << 63) - 1)


def test_reuse_completed_refuses_version_drift_without_recorded_equivalence(tmp_path):
    from hashlib import sha256
    import json
    import os
    import pyarrow.parquet as pq
    from docspec_client import NativeDatasets
    from congress_api.lake import body_text, readings, tables
    from congress_api.retention.provenance import json_input, parquet_output, run_job

    module = command()
    table_ids = {n: dict(namespace=['archive'], name=n) for n in ('readings', 'body_text')}
    source = tmp_path / 'source-run'
    src_catalog = source / 'catalog'
    dest_catalog = tmp_path / 'dest-catalog'
    body_bytes = b'%PDF-1.4\nstub'
    body_hex = sha256(body_bytes).hexdigest()
    prior_ver = 'a' * 64
    target_versions = body_text.recovery_versions()
    assert target_versions['pdf_text'] != prior_ver

    cfg = os.environ.get('DOCSPEC_JOB_CONFIG')
    with (NativeDatasets.from_config(cfg) if cfg else NativeDatasets()) as engine:
        for root_dir in (src_catalog, dest_catalog):
            readings.create_table(engine=engine, work=tmp_path / f'create-r-{root_dir.name}', catalog_root=root_dir,
                                  table=table_ids['readings'], location=tmp_path / f'tbl-r-{root_dir.name}', create_namespace=True)
            body_text.create_table(engine=engine, work=tmp_path / f'create-t-{root_dir.name}', catalog_root=root_dir,
                                   table=table_ids['body_text'], location=tmp_path / f'tbl-t-{root_dir.name}')

        seed = tmp_path / 'seed'
        seed.mkdir()
        text_val = 'Carried forward PDF prose.'
        text_sha = sha256(text_val.encode()).hexdigest()
        bt_path = seed / 'body-text.parquet'
        pq.write_table(
            __import__('pyarrow').Table.from_pylist([dict(
                body_sha=bytes.fromhex(body_hex), parser='pdf_text', parser_version=prior_ver,
                text=text_val, page_offsets=[0], ocr_pages=[], text_sha256=bytes.fromhex(text_sha), macos_build=None,
            )], schema=body_text._text_schema()),
            bt_path,
        )
        r_src = json_input(seed, 'parsed_readings', [dict(
            body_hex=body_hex, parser='pdf_text', parser_version=prior_ver, status='completed', error_type=None,
            text_bytes=len(text_val.encode()), text_head=text_val, fingerprint_hex=None, content_date=None,
            fields=[], named_meetings=[], links=[],
        )], **readings._reading_fields())
        run_job(seed, engine, inputs=[r_src], steps=[], outputs=[parquet_output(
            seed, 'readings', f'SELECT {readings._LAKE_READING_COLUMNS} FROM parsed_readings', body_text.PK)])
        tables.append_rows(bt_path, engine=engine, work=seed / 'app-bt', catalog_root=src_catalog,
                           table=table_ids['body_text'], keys=body_text.PK, definition='seed')
        tables.append_rows(seed / 'readings.parquet', engine=engine, work=seed / 'app-r', catalog_root=src_catalog,
                           table=table_ids['readings'], keys=body_text.PK, definition='seed')

        batch_dir = source / 'batches/batch-00001'
        batch_dir.mkdir(parents=True)
        (batch_dir / 'result.json').write_text(json.dumps(dict(body_outcomes=[dict(
            body_sha256=body_hex, parser='pdf_text', parser_version=prior_ver,
            status='read', reading_status='completed',
        )])))

        # 1. Refuses reusing a prior PDF version under the new recovery ID without explicit equivalence.
        work_refused = tmp_path / 'work-refused'
        work_refused.mkdir()
        with pytest.raises(ValueError, match='no recorded equivalence decision'):
            module.reuse_completed(source, work_refused, engine, dest_catalog, table_ids, target_versions)
        assert not (work_refused / 'carried-completed.json').exists()

        # 2. Accepts explicit recorded equivalence and stamps target version cleanly.
        work_equiv = tmp_path / 'work-equiv'
        work_equiv.mkdir()
        carried = module.reuse_completed(
            source, work_equiv, engine, dest_catalog, table_ids, target_versions,
            equivalent_versions={'pdf_text': [prior_ver]},
        )
        assert len(carried) == 1
        assert carried[0]['prior_parser_version'] == prior_ver
        assert carried[0]['parser_version'] == target_versions['pdf_text']

        # 2b. Resuming with a retained carried-completed.json WITHOUT equivalent_versions MUST refuse!
        with pytest.raises(ValueError, match='no recorded equivalence decision'):
            module.reuse_completed(source, work_equiv, engine, dest_catalog, table_ids, target_versions)
        # Resuming with a different target version or different source MUST also refuse!
        with pytest.raises(ValueError, match='does not match current source or target versions'):
            module.reuse_completed(
                source, work_equiv, engine, dest_catalog, table_ids,
                dict(target_versions, pdf_text='b' * 64),
                equivalent_versions={'pdf_text': [prior_ver]},
            )
        with pytest.raises(ValueError, match='does not match current source or target versions'):
            module.reuse_completed(
                tmp_path / 'other-source', work_equiv, engine, dest_catalog, table_ids, target_versions,
                equivalent_versions={'pdf_text': [prior_ver]},
            )
        # Resuming with matching source, target versions, and recorded equivalence succeeds cleanly.
        resumed = module.reuse_completed(
            source, work_equiv, engine, dest_catalog, table_ids, target_versions,
            equivalent_versions={'pdf_text': [prior_ver]},
        )
        assert resumed == carried

        # Tampered carried-completed receipts (pending status, duplicate key, empty vs non-empty source, missing dest row) refuse!
        receipt_path = work_equiv / 'carried-completed.json'
        saved_receipt = receipt_path.read_text()
        try:
            receipt_path.write_text(json.dumps([dict(carried[0], reading_status='pending')]))
            with pytest.raises(ValueError, match='non-completed'):
                module.reuse_completed(source, work_equiv, engine, dest_catalog, table_ids, target_versions,
                                       equivalent_versions={'pdf_text': [prior_ver]})
            receipt_path.write_text(json.dumps([carried[0], carried[0]]))
            with pytest.raises(ValueError, match='Duplicate carried-completed key'):
                module.reuse_completed(source, work_equiv, engine, dest_catalog, table_ids, target_versions,
                                       equivalent_versions={'pdf_text': [prior_ver]})
            receipt_path.write_text('[]')
            with pytest.raises(ValueError, match='does not match source completed outcomes'):
                module.reuse_completed(source, work_equiv, engine, dest_catalog, table_ids, target_versions,
                                       equivalent_versions={'pdf_text': [prior_ver]})
            receipt_path.write_text(saved_receipt)
            empty_dest = tmp_path / 'empty-dest-catalog'
            readings.create_table(engine=engine, work=tmp_path / 'create-r-empty', catalog_root=empty_dest,
                                  table=table_ids['readings'], location=tmp_path / 'tbl-r-empty', create_namespace=True)
            body_text.create_table(engine=engine, work=tmp_path / 'create-t-empty', catalog_root=empty_dest,
                                   table=table_ids['body_text'], location=tmp_path / 'tbl-t-empty')
            with pytest.raises(ValueError, match='missing retained carried-completed rows'):
                module.reuse_completed(source, work_equiv, engine, empty_dest, table_ids, target_versions,
                                       equivalent_versions={'pdf_text': [prior_ver]})
        finally:
            receipt_path.write_text(saved_receipt)

        # 3. Accepts exact matching version without equivalent_versions.
        exact_dest = tmp_path / 'exact-dest-catalog'
        readings.create_table(engine=engine, work=tmp_path / 'create-r-exact', catalog_root=exact_dest,
                              table=table_ids['readings'], location=tmp_path / 'tbl-r-exact', create_namespace=True)
        body_text.create_table(engine=engine, work=tmp_path / 'create-t-exact', catalog_root=exact_dest,
                               table=table_ids['body_text'], location=tmp_path / 'tbl-t-exact')
        work_exact = tmp_path / 'work-exact'
        work_exact.mkdir()
        exact_versions = dict(target_versions, pdf_text=prior_ver)
        carried_exact = module.reuse_completed(source, work_exact, engine, exact_dest, table_ids, exact_versions)
        assert len(carried_exact) == 1 and carried_exact[0]['parser_version'] == prior_ver
