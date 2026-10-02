"""The archive migration preserves bytes, source values and missing observations."""
import gzip
import importlib.util
import json
from pathlib import Path
import hashlib

import pyarrow.parquet as pq
import pytest

from congress_api.models.content import RawContent
from congress_api.retention.bundles import restore

spec = importlib.util.spec_from_file_location('assemble_raw_archive', Path(__file__).parents[1]/'docs/youtube-coverage/research/scripts/assemble_raw_archive.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def item(path, **kwargs):
    stat = path.stat()
    return dict(path=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns, **kwargs)


@pytest.mark.parametrize(('url','expected'),[
 ('https://api.congress.gov/v3/committee-meeting/119/house/123','congress/meetings'),
 ('https://api.congress.gov/v3/committee/house/hsag00','congress/committees'),
 ('https://docs.house.gov/meetings/A/1/HMTG-119-20260930.xml','house/meeting-xml'),
 ('https://docs.house.gov/meetings/A/1/HMTG-119-WList-20260930.xml','house/witness-xml'),
 ('https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=123','house/pages'),
 ('https://intelligence.house.gov/event/business-meeting/','house/pages'),
 ('https://rules.house.gov/files/report.pdf','documents'),
 ('https://www.cbo.gov/files/testimony.pdf','documents'),
 ('https://www.govinfo.gov/metadata/pkg/CHRG-1/mods.xml','govinfo/mods'),
 ('https://www.govinfo.gov/metadata/pkg/CHRG-1/premis.xml','govinfo/premis'),
 ('https://www.govinfo.gov/content/pkg/CHRG-1/mets.xml','govinfo/mets'),
 ('https://www.govinfo.gov/content/pkg/CHRG-1/html/CHRG-1.htm','govinfo/transcript-html'),
 ('https://www.govinfo.gov/content/pkg/CRPT-119hrpt1/html/CRPT-119hrpt1.htm','documents'),
 ('https://www.senate.gov/isvp/?comm=finance&filename=finance010124','senate/players'),
 ('https://www.help.senate.gov/hearings?page=2','senate/listings'),
 ('https://www.help.senate.gov/hearings/a-hearing','senate/pages'),
 ('https://www.help.senate.gov/imo/media/doc/testimony.pdf','documents'),
 ('https://www.epw.senate.gov/public/?a=Files.Serve&File_id=ABC','documents'),
 ('https://www.epw.senate.gov/public/?A=files.serve&FILE_ID=ABC','documents'),
 ('https://www.epw.senate.gov/public/?a=Files.Serve','senate/pages'),
 ('https://www.epw.senate.gov/public/?a=Hearings&File_id=ABC','senate/pages'),
 ('https://www.googleapis.com/youtube/v3/videos?id=abc','youtube/api'),
 ('https://www.youtube.com/watch?v=abc','youtube/watch-pages'),
 ('https://www.youtube.com/api/timedtext?v=abc','youtube/captions'),
 ('https://web.archive.org/web/123/https://www.help.senate.gov/hearings/a','external/wayback'),
 ('https://api.zyte.com/v1/extract','external/provider-responses'),
])
def test_source_families(url,expected):
    assert archive.family(url=url)==expected


def test_dates_are_observations_not_migration_or_filename():
    assert archive.capture_date([None,'garbled'])=='undated'
    assert archive.capture_date(['2026-09-29T01:02:03Z','2026-09-29T22:00:00Z'])=='2026-09-29'
    assert archive.capture_date(['2026-09-29','2026-09-30'])=='mixed-dates'
    assert archive.capture_date(['2026-99-99'])=='undated'


def test_house_loose_files_keep_their_source_family():
    assert archive.family('external-sources/hearing-text/docs_house_xml/wlist_none_before_fix/100141.none')=='house/witness-xml'
    assert archive.family('external-sources/hearing-text/docs_house_xml/meta/Help.aspx')=='house/pages'
    assert archive.family('external-sources/hearing-text/docs_house_xml/meta/cr-public.xslt')=='documents'
    assert archive.family('external-sources/hearing-text/docs_house_xml/meeting_none_before_fix/100141.none')=='house/meeting-xml'
    assert archive.family('review/CRPT-119hrpt795.html')=='documents'
    assert archive.record_family({'eventId':'1','congress':119})=='congress/meetings'
    assert archive.record_family({'committee':{},'request':{}})=='congress/committees'


def test_independent_copy_and_corrupt_existing_body(tmp_path):
    cache=tmp_path/'cache';cache.mkdir();out=cache/'archive';out.mkdir()
    source=cache/'body.gz';source.write_bytes(gzip.compress(b'original\xff'))
    store=archive.Bodies(out,cache,0)
    r=store.adopt(item(source,gzip=True))
    source.write_bytes(gzip.compress(b'changed'))
    assert store.get(r['body_key'])==b'original\xff'
    (out/r['body_key']).write_bytes(gzip.compress(b'corrupt'))
    source.write_bytes(gzip.compress(b'original\xff'))
    with pytest.raises(ValueError,match='integrity'):
        archive.Bodies(out,cache,0).adopt(item(source,gzip=True))


def test_older_capture_journals_link_prefixed_and_pathless_digests(tmp_path):
    cache=tmp_path/'cache';cache.mkdir();output=cache/'archive';output.mkdir()
    source=cache/'retained.xml';source.write_bytes(b'<mods>Original bytes</mods>')
    bodies=archive.Bodies(output,cache,0)
    body=bodies.adopt(item(source,gzip=False))
    record={'event':'capture','byte_size':body['bytes'],
            'sha256':'sha256:'+body['sha256'],
            'requested_url':'https://www.govinfo.gov/metadata/pkg/CHRG-1/mods.xml',
            'observed_at':'2026-09-24T01:00:00Z','status_code':200,
            'content_type':'application/xml'}
    refs=archive.file_references(record,'journal.jsonl',cache,{},bodies)
    assert len(refs)==1
    assert refs[0]['body_key']==body['body_key']
    assert refs[0]['original_path'] is None
    assert refs[0]['pointer_json']=='["sha256"]'
    assert refs[0]['family']=='govinfo/mods'
    assert refs[0]['retrieved_at']==record['observed_at']
    assert refs[0]['media_type']=='application/xml'
    # A digest in arbitrary metadata is not a claim of captured source bytes.
    assert archive.file_references({k:v for k,v in record.items() if k!='event'},'report.json',cache,{},bodies)==[]
    record.update(path=str(source),bytes=body['bytes']);record.pop('event')
    refs=archive.file_references(record,'ledger.json',cache,{},bodies)
    assert refs[0]['body_key']==body['body_key']
    assert refs[0]['resolution']=='digest_verified'
    assert archive.file_references({'body_path':'','status_code':404},'attempts.jsonl',cache,{},bodies)==[]
    record={'raw_path':'cache/retained.xml','sha256':body['sha256'],
            'final_url':'https://docs.house.gov/file.xml','status':200}
    refs=archive.file_references(record,'receipt.json',cache,{},bodies)
    assert refs[0]['body_key']==body['body_key']
    assert refs[0]['context_url']==record['final_url']
    assert refs[0]['http_status']==200
    record={'kind':'original_html','package_id':None,'path':str(source),'sha256':body['sha256'],'bytes':body['bytes']}
    assert archive.file_references(record,'gpo-xml-refresh/transcript-inventory.json',cache,{},bodies)[0]['family']=='documents'


def test_archive_end_to_end_preserves_metadata_and_missing_checks(tmp_path):
    cache=tmp_path/'cache';cache.mkdir();admin=tmp_path/'admin';admin.mkdir()
    raw=cache/'testimony.pdf';raw.write_bytes(b'%PDF-1.7\nretained\x00\xff')
    docsha=hashlib.sha256(raw.read_bytes()).hexdigest()
    record={'url':'https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=1',
            'retrieved_at':'2026-09-29T01:00:00Z','status_code':200,
            'raw_html':RawContent.from_bytes(b'<html>Native\xff</html>','text/html').source_dict(),
            'document':{'url':'https://example.gov/testimony.pdf','raw_path':str(raw),'sha256':docsha,'bytes':len(raw.read_bytes())},
            'missing':{'url':'https://example.gov/missing.pdf','raw_path':str(cache/'missing.pdf'),'status_code':404},
            'unknown_publisher_field':{'value':None,'list':[1,'1']}}
    # A pending file for a JSONL capture is still a single JSON document.
    source=cache/'house.jsonl.gz.pending.json';source.write_text(json.dumps(record,indent=2))
    bm=admin/'bodies.jsonl';bm.write_text(json.dumps(item(raw,gzip=False,family_hint='documents'))+'\n')
    rm=admin/'records.jsonl';rm.write_text(json.dumps(item(source))+'\n')
    output=cache/'congressional-tech-raw'
    summary=archive.run(bm,rm,None,cache,output,admin,'test-run',workers=1,min_free_gib=0)
    assert not (output/'snapshots').exists()
    assert summary['unresolved_reference_occurrences']==1
    assert record==json.loads(source.read_text())
    table=pq.read_table(output/'indexes/captures.parquet').to_pylist()
    assert any(r['resolution']=='not_retained' and r['body_key'] is None for r in table)
    assert any(r['sha256']==docsha for r in table)
    restored=[]
    for p in (output/'receipts').rglob('*.jsonl.gz'):
        for line in gzip.open(p,'rt'):
            r=json.loads(line)
            if r['source_file']==source.name:
                restored.append(restore(r['record'],r['captures'],lambda key:gzip.decompress((output/key).read_bytes())))
    assert restored==[record]
    assert raw.read_bytes()==b'%PDF-1.7\nretained\x00\xff'


def test_identical_response_bytes_do_not_merge_source_families(tmp_path):
    cache=tmp_path/'cache';cache.mkdir();admin=tmp_path/'admin';admin.mkdir()
    files=[cache/'first.bin',cache/'second.bin']
    for path in files:path.write_bytes(b'Not found')
    digest=hashlib.sha256(files[0].read_bytes()).hexdigest()
    source=cache/'responses.jsonl'
    source.write_text('\n'.join(json.dumps({'url':url,'raw_path':str(path),'sha256':digest,'bytes':9,'http_status':404}) for path,url in zip(files,('https://intelligence.house.gov/event/missing','https://www.help.senate.gov/hearings/missing')))+'\n')
    bm=admin/'bodies.jsonl';bm.write_text(''.join(json.dumps(item(path,gzip=False))+'\n' for path in files))
    rm=admin/'records.jsonl';rm.write_text(json.dumps(item(source))+'\n')
    out=cache/'archive'
    result=archive.run(bm,rm,None,cache,out,admin,'same-bytes',workers=2,min_free_gib=0)
    assert result['distinct_bodies']==1
    aliases={r['source_file']:r['family'] for r in pq.read_table(out/'indexes/captures.parquet').to_pylist() if r['reference_kind']=='retained-file'}
    assert aliases=={'first.bin':'house/pages','second.bin':'senate/pages'}
