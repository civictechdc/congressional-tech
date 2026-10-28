"""The model derives writer facts from current captures, never a prior proof file."""
import gzip
import hashlib
import json
import os

import pyarrow.parquet as pq
import pytest

from congress_api.lake import readings,filenames
from congress_api.lake.captures import stage_captures
from congress_api.retention.provenance import parquet_output,run_job
from docspec_client.client import NativeDatasets


def model_inputs(tmp_path,*,conflict=False):
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw=tmp_path/'raw';raw.mkdir()
    pdf=b'%PDF-1.7\nretained fixture bytes\n%%EOF\n'
    caption=(b'<html><head><title>Retained page</title></head><body><p>'+b'Evidence '*100+b'</p></body></html>' if conflict else
             b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nRetained words\n')
    rows=[]
    for name,data,media,format,fidelity in [('report.pdf',pdf,'application/pdf','pdf','exact-bytes'),
            ('caption.vtt',caption,'text/vtt','html' if conflict else None,'saved-text')]:
        digest=hashlib.sha256(data).hexdigest();key='bodies/sha256/'+digest[:2]+'/'+digest
        path=raw/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        url='https://fixture.test/'+name
        rows.append(dict(writer=dict(job='fixture',commit='a'*40),run_id='fixture',mode='fetch',family='documents',
            outcome='stored',requested_url=url,url=url,http_status=200,complete=True,retrieved_at='2026-10-27T12:00:00Z',
            captures=[dict(sha256=digest,bytes=len(data),media_type=media,fidelity=fidelity,sniffed_format=format,
                sniff_version=readings.current_version('sniff') if format else None,intact=True if format=='pdf' else None,
                stored_suffix='',stored_bytes=len(data),stored_md5=hashlib.md5(data).hexdigest())]))
    receipt=raw/'receipts/documents/2026-10-27/writer.jsonl.gz';receipt.parent.mkdir(parents=True)
    encoded=gzip.compress((''.join(json.dumps(row)+'\n' for row in rows)).encode(),mtime=0);receipt.write_bytes(encoded)
    qualification=tmp_path/'receipt-pin.json';qualification.write_text(json.dumps(dict(path=str(receipt),size=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),producer='fixture creation')))
    captures=stage_captures([dict(key=receipt.relative_to(raw).as_posix(),path=str(receipt),qualification=str(qualification))],
        engine=engine,work=tmp_path/'capture-stage')/'captures.parquet'
    inventory=tmp_path/'inventory';inventory.mkdir()
    run_job(inventory,engine,inputs=[dict(name='captures',kind='parquet',path=str(captures))],steps=[],outputs=[
        parquet_output(inventory,'bodies',"""SELECT DISTINCT sha256 AS body_sha,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex') AS relative_path,
        stored_bytes,false AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""",['body_sha'])])
    pages=readings.stage(captures=captures,body_inventory=inventory/'bodies.parquet',local_root=raw,engine=engine,
        work=tmp_path/'page-stage',decided_at='2026-10-27T12:00:00Z',parser='html')
    names=filenames.stage(captures=captures,recovery_files=(),engine=engine,work=tmp_path/'name-stage',decided_at='2026-10-27T12:00:00Z')
    return dict(captures=captures,readings=pages['readings'],filename_readings=names['readings'],
        parser_versions={p:readings.current_version(p) for p in ['sniff','html','xml','json']},
        catalog_version=names['catalog_version'],engine=engine)


def test_metadata_only_writer_caption_never_becomes_a_public_source(tmp_path):
    from viewer_publication.archive_model import build_release
    arguments=model_inputs(tmp_path)
    assert pq.ParquetFile(arguments['readings']).metadata.num_rows==0
    build_release(**arguments,output=tmp_path/'release',scratch=tmp_path/'model')
    listed=pq.read_table(tmp_path/'release/list.parquet').to_pylist()
    assert len(listed)==1 and listed[0]['format']=='pdf'
    sources=pq.read_table(tmp_path/'release/sources.parquet').to_pylist()
    assert {row['url'] for row in sources}=={'https://fixture.test/report.pdf'}
    roles=pq.read_table(tmp_path/'model/evidence/record_roles.parquet').to_pylist()
    captions=[row for row in roles if row['record_role']=='caption']
    assert len(captions)==1 and captions[0]['is_real_file'] is False
    assert {'recovered_url','identity_note','decided_at'}<=set(pq.read_schema(tmp_path/'model/evidence/current_recoveries.parquet').names)


def test_model_refuses_a_current_byte_fact_that_conflicts_with_writer_proof(tmp_path):
    from viewer_publication.archive_model import build_release
    arguments=model_inputs(tmp_path,conflict=True)
    assert pq.ParquetFile(arguments['readings']).metadata.num_rows==1
    with pytest.raises(ValueError,match='invariant'):
        build_release(**arguments,output=tmp_path/'release',scratch=tmp_path/'model')
    assert not (tmp_path/'release/manifest.json').exists()


def test_prepared_admission_checks_current_pins_without_public_artifacts(tmp_path):
    from viewer_publication.archive_model import prepare_model_inputs,admission_checks
    arguments=model_inputs(tmp_path)
    prepared=prepare_model_inputs(**arguments,scratch=tmp_path/'admission')
    assert (prepared['scratch']/'profile.json').is_file()
    assert json.loads((prepared['scratch']/'profile.json').read_text())==prepared['profile']
    assert not (tmp_path/'release').exists()
    check=prepared['scratch']/'check';check.mkdir()
    reports=run_job(check,arguments['engine'],inputs=prepared['inputs'],steps=prepared['steps'],outputs=[],
        queries=admission_checks(parser_versions=arguments['parser_versions'],catalog_version=arguments['catalog_version']))
    assert set(reports)=={'model_invariants','profile_completeness'}
    assert not any(value for rows in reports.values() for row in rows for value in row.values())
    with pytest.raises(FileExistsError):prepare_model_inputs(**arguments,scratch=prepared['scratch'])
    empty=tmp_path/'missing-filenames.parquet'
    pq.write_table(pq.read_table(arguments['filename_readings']).slice(0,0),empty)
    incomplete=prepare_model_inputs(**dict(arguments,filename_readings=empty),scratch=tmp_path/'incomplete')
    check=incomplete['scratch']/'check';check.mkdir()
    refused=run_job(check,arguments['engine'],inputs=incomplete['inputs'],steps=incomplete['steps'],outputs=[],
        queries=admission_checks(parser_versions=arguments['parser_versions'],catalog_version=arguments['catalog_version']))
    assert refused['profile_completeness'][0]['missing_filenames']>0
    assert not (tmp_path/'release').exists()
