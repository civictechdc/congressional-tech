"""File-backed PDF reads preserve physical pages and verify bounded archived bytes."""
import gzip
from hashlib import sha256
import json
import logging
from pathlib import Path
import os
import subprocess
import sys
import time

import pypdf
import pytest

from congressional_explorer_mcp import large_body_reader as large
from congressional_explorer_mcp.models import ExplorerError
from test_body_reader import local_archive_server, make_pdf_bytes


BOUNDS=dict(max_source_bytes=1<<20,max_decoded_bytes=1<<20,max_output_bytes=1<<20,min_free_bytes=0)


def target(origin,body,suffix):
    return dict(saved_body=body,saved_suffix=suffix,saved_url=f'{origin}/bodies/sha256/{body[:2]}/{body}{suffix}',
                archive_origin=origin,format='pdf',filename='retained.pdf')


def pages(result):
    with gzip.open(result['pages_path'],'rt') as stream:
        return [json.loads(line) for line in stream]


@pytest.mark.parametrize('mode',['identity','wire_gzip','storage_gzip','identity_with_gzip_suffix'])
def test_streamed_verification_modes_file_handle_and_blank_physical_pages(tmp_path,monkeypatch,mode):
    pdf=make_pdf_bytes(['First physical page.','','Third physical page.'])
    raw=gzip.compress(pdf,mtime=0) if mode in ('wire_gzip','storage_gzip') else pdf
    suffix='.pdf' if mode=='identity' else '.gz'
    body=sha256(pdf if mode=='storage_gzip' else raw).hexdigest()
    routes={f'/bodies/sha256/{body[:2]}/{body}{suffix}':raw}
    original=pypdf.PdfReader
    def file_reader(stream,*args,**kwargs):
        assert not isinstance(stream,(str,bytes,Path))
        assert stream.fileno()>=0 and stream.seekable()
        return original(stream,*args,**kwargs)
    monkeypatch.setattr(pypdf,'PdfReader',file_reader)
    with local_archive_server(routes) as (origin,requests):
        result=large.read_pdf_pages_verified(target(origin,body,suffix),work_dir=tmp_path,backend='pypdf',**BOUNDS)
    assert pages(result)==[dict(page=1,text='First physical page.'),dict(page=2,text=''),dict(page=3,text='Third physical page.')]
    assert result['page_count']==result['backend']['physical_page_count']==3
    assert result['textless_pages']==1 and result['textless_page_ranges']==[[2,2]]
    assert result['backend']['input_mode']=='seekable_file_handle'
    assert result['source']['wire_sha256']==sha256(raw).hexdigest()
    assert result['source']['decoded_sha256']==sha256(pdf).hexdigest()
    assert result['source']['wire_bytes']==len(raw) and result['source']['decoded_bytes']==len(pdf)
    assert result['source']['hash_binding']==('storage_gzip_decoded' if mode=='storage_gzip' else 'wire')
    assert len(requests)==1 and not (tmp_path/'source.pdf.partial').exists()
    assert result['completion_sha256']==sha256(Path(result['pages_path']).read_bytes()).hexdigest()


def test_completion_reuse_does_not_reopen_source_and_corruption_is_explicit(tmp_path):
    pdf=make_pdf_bytes(['Retained reading.'])
    body=sha256(pdf).hexdigest()
    routes={f'/bodies/sha256/{body[:2]}/{body}.pdf':pdf}
    with local_archive_server(routes) as (origin,requests):
        value=target(origin,body,'.pdf')
        first=large.read_pdf_pages_verified(value,work_dir=tmp_path,backend='pypdf',**BOUNDS)
        routes.clear()
        reused=large.read_pdf_pages_verified(value,work_dir=tmp_path,backend='pypdf',**BOUNDS)
        assert reused['reused'] and len(requests)==1
        code='''import json,sys
from congressional_explorer_mcp.large_body_reader import read_pdf_pages_verified
result=read_pdf_pages_verified(json.loads(sys.argv[1]),work_dir=sys.argv[2],backend='pypdf',**json.loads(sys.argv[3]))
print(json.dumps(dict(reused=result['reused'],page_count=result['page_count'])))'''
        child=subprocess.run([sys.executable,'-c',code,json.dumps(value),str(tmp_path),json.dumps(BOUNDS)],
                             capture_output=True,text=True,timeout=10,check=True)
        assert json.loads(child.stdout)==dict(reused=True,page_count=1) and len(requests)==1
        Path(first['pages_path']).write_bytes(b'corrupt retained output')
        with pytest.raises(large.LargePDFError) as caught:
            large.read_pdf_pages_verified(value,work_dir=tmp_path,backend='pypdf',**BOUNDS)
        assert caught.value.code=='completion_corrupt' and len(requests)==1


@pytest.mark.parametrize(('condition','expected'),[
    ('digest','body_digest_mismatch'),('source_limit','source_limit'),('decoded_limit','decoded_limit'),
    ('output_limit','output_limit'),('disk_floor','disk_floor'),('invalid_gzip','invalid_gzip')])
def test_bounds_failures_keep_reason_and_remove_spool(tmp_path,condition,expected):
    pdf=make_pdf_bytes(['A substantive physical page.'])
    raw=gzip.compress(pdf,mtime=0) if condition in ('decoded_limit','invalid_gzip') else pdf
    if condition=='invalid_gzip':
        raw=raw[:-8]
    body=sha256(raw).hexdigest() if condition!='digest' else 'ff'*32
    suffix='.gz' if condition in ('decoded_limit','invalid_gzip') else '.pdf'
    bounds=dict(BOUNDS)
    if condition in ('source_limit','decoded_limit','output_limit'):
        bounds['max_'+condition.replace('_limit','')+'_bytes']=10
    if condition=='disk_floor':
        bounds['min_free_bytes']=1<<80
    with local_archive_server({f'/bodies/sha256/{body[:2]}/{body}{suffix}':raw}) as (origin,requests):
        with pytest.raises(large.LargePDFError) as caught:
            large.read_pdf_pages_verified(target(origin,body,suffix),work_dir=tmp_path,backend='pypdf',**bounds)
    assert caught.value.code==expected
    assert not (tmp_path/'source.pdf.partial').exists() and not (tmp_path/'pdf-pages.partial').exists()
    assert not (tmp_path/'pdf-reading.json').exists()
    assert json.loads((tmp_path/'pdf-failure.json').read_text())['code']==expected
    if condition=='disk_floor':
        assert not requests


def test_existing_archive_guard_rejects_untrusted_address_before_fetch(tmp_path):
    value=target('https://archive.example','aa'*32,'.pdf')
    value['saved_url']='https://publisher.example/untrusted.pdf'
    with pytest.raises(ExplorerError,match='outside archive_origin'):
        large.read_pdf_pages_verified(value,work_dir=tmp_path,**BOUNDS)


def test_pinned_poppler_fallback_preserves_physical_page_boundaries(tmp_path,monkeypatch):
    definition=large.large_pdf_definition()
    if not all(definition['facts']['tools'][tool].get('qualified') for tool in ('pdfinfo','pdftotext')):
        pytest.skip('Requires the retained pinned Poppler toolchain')
    pdf=make_pdf_bytes(['Poppler first.','','Poppler third.'])
    body=sha256(pdf).hexdigest()
    def failed_primary(*args):
        raise large.LargePDFError('Planted primary reader failure','backend_error')
    monkeypatch.setattr(large,'_pypdf',failed_primary)
    with local_archive_server({f'/bodies/sha256/{body[:2]}/{body}.pdf':pdf}) as (origin,_):
        result=large.read_pdf_pages_verified(target(origin,body,'.pdf'),work_dir=tmp_path,**BOUNDS)
    assert result['backend']['name']=='pdftotext' and result['backend']['physical_page_count']==3
    assert [p['text'] for p in pages(result)]==['Poppler first.','','Poppler third.']
    assert result['attempts'][0]['state']=='failed' and result['attempts'][1]['state']=='completed'
    assert result['textless_page_ranges']==[[2,2]]


def test_font_dependency_warning_cannot_silently_qualify_partial_text(tmp_path,monkeypatch,caplog):
    definition=large.large_pdf_definition()
    if not all(definition['facts']['tools'][tool].get('qualified') for tool in ('pdfinfo','pdftotext')):
        pytest.skip('Requires the retained pinned Poppler toolchain')
    original=pypdf.PdfReader
    def warning_reader(stream,*args,**kwargs):
        logging.getLogger('pypdf.controlled').warning('fontTools is required to decode this planted CFF font')
        return original(stream,*args,**kwargs)
    monkeypatch.setattr(pypdf,'PdfReader',warning_reader)
    pdf=make_pdf_bytes(['The fallback retains this text.'])
    body=sha256(pdf).hexdigest()
    with local_archive_server({f'/bodies/sha256/{body[:2]}/{body}.pdf':pdf}) as (origin,_):
        result=large.read_pdf_pages_verified(target(origin,body,'.pdf'),work_dir=tmp_path/'auto',**BOUNDS)
        with pytest.raises(large.LargePDFError) as caught:
            large.read_pdf_pages_verified(target(origin,body,'.pdf'),work_dir=tmp_path/'primary',backend='pypdf',**BOUNDS)
    assert caught.value.code=='backend_dependency_missing'
    assert result['backend']['name']=='pdftotext'
    assert result['attempts'][0]['code']=='backend_dependency_missing'
    assert result['attempts'][0]['evidence']['warnings']['count']==1
    assert pages(result)[0]['text']=='The fallback retains this text.'
    assert 'fontTools is required' in result['attempts'][0]['evidence']['warnings']['samples'][0]


def test_tool_timeout_stops_the_actual_child(tmp_path):
    stdout,stderr=tmp_path/'stdout',tmp_path/'stderr'
    command=[sys.executable,'-c','import os,time;print(os.getpid(),flush=True);time.sleep(60)']
    with pytest.raises(large.LargePDFError) as caught:
        large._tool(command,stdout,stderr,deadline=time.monotonic()+.5,limit=65536)
    assert caught.value.code=='timeout'
    pid=int(stdout.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid,0)
