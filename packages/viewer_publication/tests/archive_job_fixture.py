"""Real local raw-to-lake inputs shared by model and publisher integration tests."""
import hashlib
import json
import os


def versions():
    from congress_api.lake import readings,filenames
    return {p:readings.current_version(p) for p in ['sniff','html','xml','json']},filenames.current_version()


def model_spec(tmp_path):
    parsers,catalog=versions()
    return dict(version=1,engine_config=str(tmp_path/'unopened-runtime.json'),
        **{name:dict(kind='parquet',path=str(tmp_path/(name+'.parquet')),sha256='a'*64,size=17)
           for name in ['captures','readings','filename_readings']},
        parser_versions=parsers,catalog_version=catalog,output=str(tmp_path/'release'),scratch=str(tmp_path/'model'))


def real_model_spec(tmp_path):
    import gzip
    from congress_api.lake import readings
    from congress_api.retention.provenance import file_pin
    raw=tmp_path/'raw';raw.mkdir()
    html=b'<html><head><title>Retained CLI report</title></head><body><p>'+b'Substantive retained report evidence. '*100+b'</p></body></html>'
    digest=hashlib.sha256(html).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest+'.gz'
    stored=gzip.compress(html,mtime=0);body=raw/key;body.parent.mkdir(parents=True);body.write_bytes(stored)
    url='https://fixture.test/report.html'
    row=dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',outcome='stored',
        requested_url=url,url=url,http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
        captures=[dict(sha256=digest,bytes=len(html),media_type='text/html',fidelity='exact-bytes',
            sniffed_format='html',sniff_version=readings.current_version('sniff'),stored_suffix='.gz',
            stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())])
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz';receipt.parent.mkdir(parents=True)
    receipt.write_bytes(gzip.compress((json.dumps(row)+'\n').encode(),mtime=0))
    qualification=tmp_path/'receipt-pin.json';qualification.write_text(json.dumps(dict(path=str(receipt),**file_pin(receipt),producer='fixture creation')))
    return rebuild_model_spec(tmp_path,raw=raw,qualification=qualification),digest,html


def rebuild_model_spec(tmp_path,*,raw,qualification):
    """Run the same producers from retained raw, with no earlier derived inputs."""
    from pathlib import Path
    from congress_api.lake import readings,filenames
    from congress_api.lake.captures import stage_captures
    from congress_api.retention.provenance import file_pin,parquet_output,run_job
    from docspec_client.client import NativeDatasets
    runtime=os.environ['DOCSPEC_JOB_CONFIG'];raw=Path(raw)
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz'
    with NativeDatasets.from_config(runtime) as engine:
        captures=stage_captures([dict(key=receipt.relative_to(raw).as_posix(),path=str(receipt),qualification=str(qualification))],engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
        inventory=tmp_path/'inventory';inventory.mkdir()
        run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
            parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
            'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
            stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
        pages=readings.stage_once(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,
            engine=engine,work=tmp_path/'reading-stage',decided_at='2026-10-27T12:00:00Z')
        names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'filename-stage',decided_at='2026-10-27T12:00:00Z')
        value=model_spec(tmp_path);value['engine_config']=runtime
        for name,path in [('captures',captures),('readings',pages['readings']),('filename_readings',names['readings'])]:
            value[name]=dict(kind='parquet',path=str(path),**file_pin(path))
    return value


def native_daily_spec(tmp_path,model,engine):
    """Seed real local tables from the independently rebuilt raw fixture."""
    from pathlib import Path
    from congress_api.lake import captures,readings,filenames,tables
    catalog=str(tmp_path/'catalog')
    refs={name:dict(namespace=['archive'],name=name) for name in ['captures','readings','filename_readings']}
    schema=json.loads((Path(__file__).resolve().parents[3]/'model/lake/captures.schema.json').read_text())
    tables.create_table(engine=engine,work=tmp_path/'create-captures',catalog_root=catalog,
        table=refs['captures'],schema=schema,location=tmp_path/'lake-captures',create_namespace=True)
    for name,module in [('readings',readings),('filename_readings',filenames)]:
        module.create_table(engine=engine,work=tmp_path/('create-'+name),catalog_root=catalog,
            table=refs[name],location=tmp_path/('lake-'+name))
    for name,keys,definition in [('captures',['receipt_key'],captures.current_version()),
            ('readings',readings.PK,'fixture-current-readings'),
            ('filename_readings',filenames.PK,'fixture-current-filenames')]:
        tables.append_rows(model[name]['path'],engine=engine,work=tmp_path/('seed-'+name),
            catalog_root=catalog,table=refs[name],keys=keys,definition=definition)
    return dict(work=str(tmp_path/'daily'),decided_at='2026-10-28T12:00:00Z',catalog_root=catalog,
        tables=refs,receipt_inventory=[],body_inventory=str(tmp_path/'inventory/bodies.parquet'),
        local_root=str(tmp_path/'raw'),max_work_items=10,
        provenance={kind:[] for kind in ['recoveries','reviews','unreadable']})
