"""C3: model exports are byte-identical across threads, batch sizes and a forced spill.

This is why engine limits stay out of the semantic profile (archive_model_profile.runtime_pins).
The spill case must actually spill: the engine reports each retained step's storage
in result.json, and at least one model step must be `scratch`, or the case proves nothing.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path

from congress_api.lake import readings,filenames
from congress_api.lake.capture_staging import stage_captures
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets

CAPTURES=2000
# Retained steps share a pool of memory_bytes/8 (docspec-rs budget.rs). This fixture
# retains more than a 64 MiB pool's 8 MiB, so model steps spill (7 of 229 measured
# 2026-11-08; 96 MiB spilled 1, 48 MiB failed a query aggregate). Writers reserve
# 3 x max_batch_bytes plus the metadata allowance from memory_bytes/2, so those shrink with it.
LIMITS={
    'threads-1-batch-64':dict(compute_threads=1,batch_rows=64),
    'threads-8-batch-1024':dict(compute_threads=8,batch_rows=1024),
    'forced-spill':dict(compute_threads=2,batch_rows=512,memory_bytes=64<<20,max_batch_bytes=1<<20,max_metadata_bytes=1<<20),
}


def _runtime(tmp_path,name,**limits):
    source=Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve()
    config=json.loads(source.read_text())
    values=dict(json.loads((source.parent/config['limits']).read_text()),**limits)
    (tmp_path/(name+'-limits.json')).write_text(json.dumps(values))
    config.update(binary=str((source.parent/config['binary']).resolve()),limits=str(tmp_path/(name+'-limits.json')),
                  workspace=str(tmp_path/(name+'-workspace')))
    (tmp_path/(name+'-runtime.json')).write_text(json.dumps(config))
    return NativeDatasets.from_config(tmp_path/(name+'-runtime.json'))


def _stage(tmp_path,engine):
    raw=tmp_path/'raw';raw.mkdir();rows=[]
    html=b'<html><head><title>Retained report</title></head><body><p>'+b'Substantive report evidence. '*80+b'</p><a href="report-0.pdf">Report PDF</a></body></html>'
    bodies=[('report.html',html,'html')]+[(f'report-{i}.pdf',b'%PDF-1.7\nfixture '+str(i).encode()+b'\n%%EOF\n','pdf') for i in range(CAPTURES)]
    for name,data,fmt in bodies:
        stored=gzip.compress(data,mtime=0) if fmt=='html' else data
        digest=hashlib.sha256(data).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest+('.gz' if fmt=='html' else '')
        path=raw/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(stored)
        url='https://fixture.test/'+name
        rows.append(dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',outcome='stored',
            requested_url=url,url=url,response_headers={},http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
            captures=[dict(sha256=digest,bytes=len(data),media_type='text/html' if fmt=='html' else 'application/pdf',fidelity='exact-bytes',
                sniffed_format=fmt,sniff_version=readings.current_version('sniff'),intact=True if fmt=='pdf' else None,
                stored_suffix='.gz' if fmt=='html' else '',stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())]))
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz';receipt.parent.mkdir(parents=True)
    encoded=gzip.compress((''.join(json.dumps(r)+'\n' for r in rows)).encode(),mtime=0);receipt.write_bytes(encoded)
    pin=tmp_path/'receipt-pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt),size=len(encoded),sha256=hashlib.sha256(encoded).hexdigest(),producer='fixture creation')))
    captures=stage_captures([dict(key=receipt.relative_to(raw).as_posix(),path=str(receipt),qualification=str(pin))],
                            engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
    inventory=tmp_path/'inventory';inventory.mkdir()
    run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
        parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
        stored_bytes FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
    pages=readings.stage(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,engine=engine,
        work=tmp_path/'reading-stage',decided_at='2026-10-27T12:00:00Z',parser='html')
    names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'filename-stage',decided_at='2026-10-27T12:00:00Z')
    return dict(captures=captures,readings=pages['readings'],filename_readings=names['readings'],catalog_version=names['catalog_version'],
                parser_versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']})


def test_model_release_bytes_and_identity_do_not_depend_on_threads_batches_or_a_forced_spill(tmp_path):
    from viewer_publication.archive_model import build_release
    from viewer_publication.archive_publish import input_digest
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    arguments=_stage(tmp_path,engine)
    def build(name,native):
        output,scratch=tmp_path/(name+'-release'),tmp_path/(name+'-model')
        manifest=build_release(**arguments,engine=native,output=output,scratch=scratch)
        storage=[step['storage'] for step in json.loads((scratch/'result.json').read_text())['steps']]
        files={item['name']:(output/item['name']).read_bytes() for item in manifest['files']}
        files['manifest.json']=(output/'manifest.json').read_bytes()
        profile=json.loads((scratch/'profile.json').read_text())
        digest=input_digest(receipt_keys=['receipts/documents/2026-10-27/slice.jsonl.gz'],provenance=[],
                            profile=profile['profile'],entity_digests={})
        return manifest,storage,files,profile['profile_sha256'],digest
    reference,storage,expected,profile_sha256,digest=build('reference',engine)
    assert 'scratch' not in storage and 'manifest.json' in expected
    for name,limits in LIMITS.items():
        manifest,storage,files,profile,identity=build(name,_runtime(tmp_path,name,**limits))
        if name=='forced-spill':
            assert storage.count('scratch')>0, 'the forced-spill limits no longer spill a model step'
        assert (profile,identity)==(profile_sha256,digest),name
        assert manifest['release_id']==reference['release_id'],name
        assert files.keys()==expected.keys(),name
        assert [key for key in files if files[key]!=expected[key]]==[],name
