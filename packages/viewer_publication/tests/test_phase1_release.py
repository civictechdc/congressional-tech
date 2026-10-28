"""The real raw/lake producer feeds one document release and its private evidence."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings,filenames
from congress_api.lake.captures import stage_captures
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets


def test_raw_lake_model_exports_one_group_and_keeps_download_names(tmp_path):
    from viewer_publication.archive_model import build_release
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw=tmp_path/'raw';raw.mkdir()
    html=b'<html><head><title>Retained report</title></head><body><p>'+b'Substantive report evidence. '*80+b'</p><a href="report.pdf">Report PDF</a></body></html>'
    pdf=b'%PDF-1.7\nfixture retained bytes\n%%EOF\n'
    rows=[];bodies=[]
    for index,(name,data,fmt,header) in enumerate([('report.html',html,'html',None),('report.pdf',pdf,'pdf',None),('mirror.pdf',pdf,'pdf','attachment; filename="download report.pdf"')]):
        stored=gzip.compress(data,mtime=0) if fmt=='html' else data
        digest=hashlib.sha256(data).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest+('.gz' if fmt=='html' else '')
        path=raw/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(stored)
        url='https://fixture.test/'+name
        rows.append(dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',outcome='stored',requested_url='https://fixture.test/redirect/report.pdf' if index==1 else url,url=url,
            response_headers={'content-disposition':header} if header else {},http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
            captures=[dict(sha256=digest,bytes=len(data),media_type='text/html' if fmt=='html' else 'application/pdf',fidelity='saved-text' if index==1 else 'exact-bytes',
                sniffed_format=fmt,sniff_version=readings.current_version('sniff'),intact=True if fmt=='pdf' else None,
                stored_suffix='.gz' if fmt=='html' else '',stored_bytes=len(stored),stored_md5=hashlib.md5(stored).hexdigest())]))
    receipt=raw/'receipts/documents/2026-10-27/slice.jsonl.gz';receipt.parent.mkdir(parents=True)
    encoded=gzip.compress((''.join(json.dumps(r)+'\n' for r in rows)).encode(),mtime=0);receipt.write_bytes(encoded)
    qualification=tmp_path/'receipt-pin.json';qualification.write_text(json.dumps(dict(path=str(receipt),size=len(encoded),sha256=hashlib.sha256(encoded).hexdigest(),producer='fixture creation')))
    captures=stage_captures([dict(key=receipt.relative_to(raw).as_posix(),path=str(receipt),qualification=str(qualification))],engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
    inventory=tmp_path/'inventory';inventory.mkdir()
    run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
        parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
        stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
    pages=readings.stage(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,engine=engine,
        work=tmp_path/'reading-stage',decided_at='2026-10-27T12:00:00Z',parser='html')
    names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'filename-stage',decided_at='2026-10-27T12:00:00Z')
    variants=tmp_path/'variants.jsonl'
    variants.write_text(''.join(json.dumps(r)+'\n' for r in [
        dict(id='old',canonical_url='https://fixture.test/obsolete.pdf',variant_url='https://fixture.test/mirror.pdf',basis='fixture',decided_at='2026-10-20T12:00:00Z',supersedes=None),
        dict(id='current',canonical_url='https://fixture.test/report.pdf',variant_url='https://fixture.test/mirror.pdf',basis='fixture',decided_at='2026-10-21T12:00:00Z',supersedes='old')]))
    variant_files=[dict(key='provenance/url_variants/fixture.jsonl',path=str(variants))]
    manifest=build_release(captures=captures,readings=pages['readings'],filename_readings=names['readings'],
        parser_versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']},catalog_version=names['catalog_version'],variant_files=variant_files,
        engine=engine,output=tmp_path/'release',scratch=tmp_path/'model')
    listed=pq.read_table(tmp_path/'release/list.parquet').to_pylist()
    detail=pq.read_table(tmp_path/'release/detail.parquet').to_pylist()
    assert len(listed)==len(detail)==1
    assert listed[0]['format']=='pdf' and listed[0]['filename']=='download report.pdf'
    assert listed[0]['first_captured'].isoformat()=='2026-10-27'
    assert detail[0]['saved_suffix']=='' and detail[0]['saved_body']==hashlib.sha256(pdf).digest()
    assert detail[0]['alternates'][0]['format']=='html'
    assert detail[0]['alternates'][0]['size']==len(html)
    assert pq.read_table(tmp_path/'release/url_variants.parquet').to_pylist()==[dict(canonical_url='https://fixture.test/report.pdf',variant_url='https://fixture.test/mirror.pdf')]
    members=pq.read_table(tmp_path/'model/evidence/source_members.parquet').to_pylist()
    assert len({m['source_id'] for m in members})==3
    assert {m['effective_filename'] for m in members}=={'report.html','report.pdf','download report.pdf'}
    assert {f['name'] for f in manifest['files']}=={'list.parquet','detail.parquet','links.parquet','urls.parquet','sources.parquet','recoveries.parquet','meetings.parquet','url_state.parquet','url_variants.parquet','schema.json','capture_scope.json','capture_profile.json'}
    assert (tmp_path/'model/evidence/document_rows.parquet').is_file()
    assert {'body_sha256','decided_at','decision_id'} <= set(pq.read_schema(tmp_path/'model/evidence/current_recoveries.parquet').names)
    lookups=pq.read_table(tmp_path/'release/urls.parquet').to_pylist()
    assert hashlib.sha256(b'lookup:fixture.test/redirect/report.pdf').digest()[:8] in {r['lookup_key'] for r in lookups}

    # Identical pinned inputs must produce byte-identical content at a fresh path.
    arguments=dict(captures=captures,readings=pages['readings'],filename_readings=names['readings'],
        parser_versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']},
        catalog_version=names['catalog_version'],engine=engine,variant_files=variant_files)
    repeated=build_release(**arguments,output=tmp_path/'repeat-release',scratch=tmp_path/'repeat-model')
    assert repeated==manifest
    for item in manifest['files']:
        assert (tmp_path/'release'/item['name']).read_bytes()==(tmp_path/'repeat-release'/item['name']).read_bytes()
    for missing,column in [('page','readings'),('filename','filename_readings')]:
        source=arguments[column];empty=tmp_path/(missing+'-empty.parquet')
        pq.write_table(pq.read_table(source).slice(0,0),empty)
        with pytest.raises(ValueError,match='invariant'):
            build_release(**dict(arguments,**{column:empty}),output=tmp_path/(missing+'-release'),scratch=tmp_path/(missing+'-model'))
        assert not (tmp_path/(missing+'-release')/'manifest.json').exists()

    # A compressed saved original must carry its decoded size for the reader guard.
    subset=tmp_path/'html-only';subset.mkdir()
    run_job(subset,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
        parquet_output(subset,'captures',"SELECT * FROM captures WHERE media_type='text/html'",['receipt_key','receipt_line','capture_index'])])
    build_release(**dict(arguments,captures=subset/'captures.parquet'),output=tmp_path/'html-release',scratch=tmp_path/'html-model')
    html_detail=pq.read_table(tmp_path/'html-release/detail.parquet').to_pylist()[0]
    assert html_detail['saved_suffix']=='.gz' and html_detail['saved_bytes']==len(html)

    imported=tmp_path/'imported-only';imported.mkdir()
    registry=json.loads((Path(__file__).parents[3]/'model/registries/import-runs.json').read_text())
    run=registry[0]
    run_job(imported,engine,inputs=[dict(name='captures',kind='parquet',path=str(subset/'captures.parquet'))],steps=[],outputs=[
        parquet_output(imported,'captures',"SELECT * EXCLUDE(run_id),'"+run['run_id'].replace("'","''")+"' AS run_id FROM captures",['receipt_key','receipt_line','capture_index'])])
    build_release(**dict(arguments,captures=imported/'captures.parquet'),output=tmp_path/'import-release',scratch=tmp_path/'import-model')
    import_list=pq.read_table(tmp_path/'import-release/list.parquet').to_pylist()[0]
    import_detail=pq.read_table(tmp_path/'import-release/detail.parquet').to_pylist()[0]
    assert import_list['first_captured'] is None and import_list['date_kind']=='import_day'
    assert import_detail['in_archive_since'].isoformat()==run['date']
