import {test} from 'node:test';
import assert from 'node:assert/strict';
import {dateLabels, lookupUrl, recoveryLabel, savedCopy} from './archive.ts';
import {rangeFile} from './range-file.ts';
import {byteCache} from './filenames/cache.ts';

test('public lookup spelling preserves queries and rejects credentials',()=>{
  assert.equal(lookupUrl('http://www.EXAMPLE.test:80/report.pdf/#old'),'example.test/report.pdf');
  assert.equal(lookupUrl('https://example.test/?file=a.pdf&x=/'),'example.test?file=a.pdf&x=/');
  assert.throws(()=>lookupUrl('https://name:secret@example.test/file'));
  assert.throws(()=>lookupUrl('file:///tmp/example'));
});

test('saved copies use the recorded physical suffix and original size',()=>{
  const detail={saved_body:new Uint8Array(32).fill(17),saved_suffix:'.gz',saved_bytes:100*1024*1024,saved_media_type:'application/pdf'};
  assert.equal(savedCopy(detail,'https://raw.test/').compressedDownload,false);
  assert.equal(savedCopy({...detail,saved_bytes:detail.saved_bytes+1},'https://raw.test/').compressedDownload,true);
  assert.match(savedCopy({...detail,saved_suffix:'.pdf'},'https://raw.test/').url,/\.pdf$/);
  assert.throws(()=>savedCopy({...detail,saved_suffix:'/other'},'https://raw.test/'));
});

test('capture, import, document and removal dates retain their meaning',()=>{
  assert.deepEqual(dateLabels({date_kind:'captured',first_captured:new Date('2024-01-02Z'),document_date:'2023-12-01'},
    {document_date_source:'publisher',removed_on:'2024-03-04'}),{
      capture:'Captured 2024-01-02',document:'2023-12-01 (publisher)',removed:'Removed from the hearing page by the committee on 2024-03-04'});
  assert.equal(dateLabels({date_kind:'import_day'},{in_archive_since:'2020-01-02'}).capture,'In our archive since 2020-01-02 (original capture date not recorded)');
  assert.equal(dateLabels({date_kind:'unknown'},{}).capture,'Capture date not recorded');
  assert.equal(recoveryLabel('recovered_document'),'Recovered document');
  assert.equal(recoveryLabel('official_substitute'),'Official substitute');
  assert.equal(recoveryLabel('requested_content_in_official_hearing'),'Requested content in an official hearing');
});

test('shared range transport checks ranges, shares bytes and retries failures',async()=>{
  let calls=0;const bytes=new Uint8Array([0,1,2,3,4,5,6,7]);
  const fetcher=async(_url,options)=>{calls++;const [start,end]=options.headers.Range.slice(6).split('-').map(Number);
    return new Response(bytes.slice(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});};
  const file=rangeFile('https://raw.test/file',8,fetcher,byteCache(4096));
  const result=await Promise.all([file.slice(0,8),file.slice(0,8)]);
  assert.deepEqual(new Uint8Array(result[0]),bytes);assert.equal(calls,1);
  assert.deepEqual(new Uint8Array(await file.slice(1,3)),new Uint8Array([1,2]));assert.equal(calls,1);
  await assert.rejects(file.slice(-1,3),/range/i);
  const controller=new AbortController();controller.abort();await assert.rejects(file.slice(0,1,controller.signal));
  let failed=true;const retry=rangeFile('https://raw.test/retry',8,async(...args)=>{if(failed){failed=false;throw Error('offline');}return fetcher(...args);});
  await assert.rejects(retry.slice(0,2),/offline/);assert.equal((await retry.slice(0,2)).byteLength,2);
  const bad=rangeFile('https://raw.test/bad',8,async()=>new Response(bytes));await assert.rejects(bad.slice(0,2),/range/i);
});
