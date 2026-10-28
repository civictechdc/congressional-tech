"""Capture facts require a completed reading, even when a verdict has an error code."""
import gzip
import hashlib
import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from congress_api.models.raw_fetch import BodyFile, FetchAttempt, FetchResult
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.pdf_tools import BODY_LIMIT
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.sniff import read_sniff_file


URL='https://fixture.test/source'
WRITER=dict(job='capture',commit='a'*40,lockfile_digest='b'*64)


def archive(entries):
    buffer=io.BytesIO()
    with ZipFile(buffer,'w',compression=ZIP_DEFLATED) as out:
        for name,data in entries:
            out.writestr(name,data)
    return buffer.getvalue()


def refused_zip(reason):
    if reason=='corrupt_archive':
        return b'PK\x03\x04broken'
    return archive([(str(index),b'x') for index in range(ZipLimits().max_members+1)])


def retain(tmp_path,data):
    source=tmp_path/'source'; source.write_bytes(data)
    body=BodyFile(source,hashlib.sha256(data).hexdigest(),len(data),None,None,None,None)
    attempt=FetchAttempt(URL,URL,'2026-10-27T10:00:00Z','direct',200,None,{},(),True,body)
    raw=tmp_path/'raw'
    writer=ReceiptWriter(BodyStore(LocalAdapter(raw)),identity=WRITER,run_id='completed-sniff',
        write_date='2026-10-27',archive_limits=ZipLimits())
    key,line=writer.write(FetchResult(attempt),family='documents')
    assert json.loads(gzip.decompress((raw/key).read_bytes()))==line
    assert line['outcome']=='stored' and line['http_status']==200
    assert line['requested_url']==line['url']==URL
    for capture in line['captures']:
        stored=raw/f"bodies/sha256/{capture['sha256'][:2]}/{capture['sha256']}{capture['stored_suffix']}"
        assert stored.is_file() and hashlib.sha256(stored.read_bytes()).hexdigest()==capture['sha256']
        assert capture['complete'] is True
    return source,line


@pytest.mark.parametrize('reason',['corrupt_archive','member_count_limit'])
def test_source_noncompleted_sniff_keeps_durable_bytes_and_unknown_facts(tmp_path,reason):
    data=refused_zip(reason)
    source,line=retain(tmp_path,data)
    reading=read_sniff_file(source)
    assert reading['status']==('error' if reason=='corrupt_archive' else 'size_limit')
    assert reading['error_type']==reason
    [capture]=line['captures']
    assert capture['sha256']==hashlib.sha256(data).hexdigest() and capture['bytes']==len(data)
    assert capture['sniff_error']==reason
    assert (capture['sniffed_format'],capture['sniff_version'],capture['intact'])==(None,)*3
    assert capture['expansion'] is None


@pytest.mark.parametrize('reason',['corrupt_archive','member_count_limit'])
def test_nested_member_noncompleted_sniff_keeps_durable_bytes_and_unknown_facts(tmp_path,reason):
    data=refused_zip(reason)
    _,line=retain(tmp_path,archive([('nested.zip',data)]))
    container,member=line['captures']
    assert container['sniffed_format']=='zip' and container['expansion']=='expanded'
    assert member['member_path']=='nested.zip'
    assert member['sha256']==hashlib.sha256(data).hexdigest() and member['bytes']==len(data)
    assert member['sniff_error']==reason
    assert (member['sniffed_format'],member['sniff_version'],member['intact'])==(None,)*3


@pytest.mark.parametrize('nested',[False,True])
@pytest.mark.parametrize('limited',[False,True])
def test_completed_pdf_reading_keeps_facts_even_with_error_type(tmp_path,nested,limited):
    data=b'%PDF-1.7\n'+(b'x'*BODY_LIMIT if limited else b'%%EOF')
    _,line=retain(tmp_path,archive([('member.pdf',data)]) if nested else data)
    capture=line['captures'][-1]
    assert capture['member_path']==('member.pdf' if nested else None)
    assert capture['sniffed_format']=='pdf' and capture['sniff_version']
    assert capture['intact'] is (not limited)
    assert capture.get('sniff_error')==('pdf_reader_size_limit' if limited else None)
