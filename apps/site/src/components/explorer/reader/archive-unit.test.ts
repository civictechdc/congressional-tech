import {test} from 'node:test';
import assert from 'node:assert/strict';
import {dateLabels, lookupUrl, recoveryLabel, savedCopy, openArchive} from './archive.ts';
import {
  cleanIdentityNote,
  committeeLabel,
  committeeShortLabel,
  congressGovBillUrl,
  congressGovMemberUrl,
  congressGovNominationUrl,
  effectiveFormat,
  expandCommitteeKeys,
  formatDuration,
  formatMeasure,
  formatSubject,
  gpoBillUrl,
  presentDocument,
  resolveCommitteeName,
  spicyRegsUrl,
} from '../archive/archive-metadata.ts';
import {rangeFile} from './range-file.ts';
import {readFile} from 'node:fs/promises';
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

test('generic worker transport pins release replies and cancels pending calls',async()=>{
  const {createWorkerClient}=await import('./filenames/client.ts');
  const workers=[];let pin;
  const client=createWorkerClient({context:()=>({releaseId:pin}),validate:(_url,data)=>{
    if(!/^[a-f0-9]{64}$/.test(data.releaseId)||pin&&data.releaseId!==pin)throw Error('Archive release changed');pin=data.releaseId;
  },createWorker:()=>{const worker={postMessage(message){this.last=message;},terminate(){this.dead=true;}};workers.push(worker);return worker;}});
  const first=client.request('info');workers[0].onmessage({data:{id:1,result:{count:7},releaseId:'ab'.repeat(32)}});assert.deepEqual(await first,{count:7});
  const controller=new AbortController(),pending=client.request('search',controller.signal);controller.abort();await assert.rejects(pending);assert.equal(client.pendingCount,0);
  workers[0].onerror();const retry=client.request('info');assert.equal(workers[1].last.releaseId,pin);
  workers[1].onmessage({data:{id:3,result:{},releaseId:'cd'.repeat(32)}});await assert.rejects(retry,/changed/);client.dispose();
});

test('fixed lookup spelling agrees with producer for dot paths and Unicode hosts',()=>{
  for(const [url,expected] of [
    ['https://example.test/a/../report.pdf','example.test/a/../report.pdf'],
    ['https://example.test/a/%2e%2e/report.pdf/','example.test/a/%2e%2e/report.pdf'],
    ['https://www.BÜCHER.test:443/report.pdf#old','bücher.test/report.pdf'],
  ])assert.equal(lookupUrl(url),expected);
});

test('pinned index and dictionary bytes survive data-cache pressure',async()=>{
  const bytes=new Uint8Array(10000),requests=[];
  const cache=byteCache(500,400),retained={entries:new Map(),bytes:0,maxBytes:1024};
  const file=rangeFile('https://raw.test/indexed',bytes.length,async(_url,options)=>{const [start,end]=options.headers.Range.slice(6).split('-').map(Number);requests.push([start,end]);return new Response(bytes.slice(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});},cache,{},retained);
  file.retain([[0,20],[9800,9850]]);
  await file.slice(0,20);await file.slice(9800,9850);await file.slice(200,500);await file.slice(500,800);
  const before=requests.length;await file.slice(0,20);await file.slice(9800,9850);assert.equal(requests.length,before);
});

test('worker payloads preserve native int64 sizes through structured cloning',async()=>{
  const {createWorkerClient}=await import('./filenames/client.ts');let message;
  const worker={postMessage(value){message=value;},terminate(){}};
  const client=createWorkerClient({context:()=>({}),createWorker:()=>worker});
  const request=client.request('/saved',undefined,{saved_bytes:100n});assert.equal(message.payload.saved_bytes,100n);
  worker.onmessage({data:{id:1,result:{url:'https://raw.test/body'}}});await request;client.dispose();
});

test('partial pinned ranges are composed with missing data without refetching dictionaries',async()=>{
  const bytes=Uint8Array.from({length:200},(_,i)=>i),ranges=[];
  const file=rangeFile('https://raw.test/partial',200,async(_url,options)=>{const [start,end]=options.headers.Range.slice(6).split('-').map(Number);ranges.push([start,end+1]);return new Response(bytes.slice(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/200`}});},byteCache(1));
  file.retain([[0,20]]);await file.slice(0,20);ranges.length=0;
  assert.deepEqual(new Uint8Array(await file.slice(0,200)),bytes);assert.deepEqual(ranges,[[20,200]]);
});


test('all named recovery claims remain readable without becoming recovered originals',async()=>{
  const fixture=JSON.parse(await readFile(new URL('../../../../scripts/fixtures/recovery-labels.json',import.meta.url),'utf8'));
  for(const [kind,label] of Object.entries(fixture.expected_labels))assert.equal(recoveryLabel(kind),label,kind);
  assert.equal(recoveryLabel(fixture.unknown.kind),fixture.unknown.label);
});


test('the actual old viewer pointer refuses before any archive or legacy asset request',async()=>{
  const pointer=JSON.parse(await readFile(new URL('../../../../scripts/fixtures/old-viewer-pointer.json',import.meta.url),'utf8'));
  const url='https://public.test/viewer-publications/manifest.json',requests=[];
  await assert.rejects(openArchive(url,{fetcher:async address=>{
    requests.push(String(address));return Response.json(pointer);
  }}),{message:'Invalid archive release identity.'});
  assert.deepEqual(requests,[url]);
});

test('document presentation resolves generic scrape titles, missing filenames, formats, and plumbing notes',()=>{
  const zipDoc=presentDocument(
    {title:'ZIP',filename:'CHRG-109hhrg32242.zip',format:'ZIP',document_kind:['hearing_serial'],congress:109},
    {saved_media_type:'application/json'},
    [{url:'https://www.govinfo.gov/content/pkg/CHRG-109hhrg32242/zip/CHRG-109hhrg32242.zip'}],
  );
  assert.equal(zipDoc.title,'CHRG-109hhrg32242.zip');
  assert.equal(zipDoc.subtitle,'');
  assert.equal(zipDoc.format,'ZIP');
  assert.equal(effectiveFormat({filename:'CHRG-109hhrg32242.zip',format:'ZIP'},{saved_media_type:'application/json'}),'zip');

  const recovered=presentDocument(
    {title:null,filename:null,format:'PDF',document_kind:['hearing_transcript'],congress:114,committee_keys:['hswm06']},
    undefined,
    [{url:'https://waysandmeans.house.gov/UploadedFiles/2015.02.11_Transcript.pdf'}],
    [{recovered_url:'https://www.govinfo.gov/content/pkg/CHRG-114hhrg94847/pdf/HHRG-114-WM06-Transcript-20150211.pdf'}],
  );
  assert.equal(recovered.title,'2015.02.11_Transcript.pdf');
  assert.ok(recovered.contextParts.includes('114th Congress'));
  assert.ok(recovered.contextParts.includes('House Ways & Means'));

  assert.equal(cleanIdentityNote('Reconciled from pinned accepted mappings 00922c1ef98d2431d98987234abc0123456789abcdef0123456789abcdef0123'),null);
  assert.equal(cleanIdentityNote('Verified against printed GPO serial'), 'Verified against printed GPO serial');
  assert.equal(formatMeasure('114-hr-475'),'H.R. 475');
  assert.equal(committeeLabel('hsju00'),'House Judiciary');
  assert.deepEqual(
    expandCommitteeKeys('hsju00',[{value:'hsju00',count:10},{value:'hsju01',count:5},{value:'ssju00',count:8}]),
    ['hsju00','hsju01'],
  );
});

test('historical committee names, nominations, durations, and external URLs resolve accurately',()=>{
  const catalog=[
    {
      committee_key:'hspw00',
      system_code:'hspw00',
      current_name:'House Committee on Transportation and Infrastructure',
      names:[
        {name:'House Committee on Public Works and Transportation',start:'1975-01-03',end:'1995-01-03'},
        {name:'House Committee on Transportation and Infrastructure',start:'1995-01-03',end:null},
      ],
      subcommittees:['hspw12'],
    },
    {
      committee_key:'hspw12',
      system_code:'hspw12',
      parent_key:'hspw00',
      current_name:'Highways and Transit',
      names:[
        {name:'Surface Transportation',start:'1975-01-03',end:'1999-01-03'},
        {name:'Highways and Transit',start:'1999-01-03',end:null},
      ],
    },
  ];
  assert.equal(resolveCommitteeName(catalog[0],'1988-04-10'),'House Committee on Public Works and Transportation');
  assert.equal(resolveCommitteeName(catalog[0],'2024-05-01'),'House Committee on Transportation and Infrastructure');
  assert.equal(committeeLabel('hspw12',catalog,'1990-01-01'),'House Committee on Public Works and Transportation — Surface Transportation');
  assert.equal(committeeLabel('hspw12',catalog,'2024-05-01'),'House Committee on Transportation and Infrastructure — Highways and Transit');
  assert.equal(committeeShortLabel('hspw12',catalog,'2024-05-01'),'House Committee on Transportation and Infrastructure');

  assert.equal(formatMeasure('119-pn-730-2'),'PN730-2');
  assert.equal(formatSubject('119-pn-730-2',{citation:'PN730-2'}),'PN730-2');
  assert.equal(formatDuration(5420),'1:30:20');
  assert.equal(formatDuration(125),'2:05');
  assert.equal(congressGovBillUrl('118-hr-1234'),'https://www.congress.gov/bill/118th-congress/house-bill/1234');
  assert.match(gpoBillUrl('118-hr-1234')??'',/govinfo\.gov.*1234/);
  assert.equal(congressGovNominationUrl('119-pn-730-2'),'https://www.congress.gov/nomination/119th-congress/730-2');
  assert.equal(congressGovMemberUrl('S000510','Adam Smith'),'https://www.congress.gov/member/adam-smith/S000510');
  assert.equal(spicyRegsUrl('H.R. 1234'),'https://spicyregs.org/?q=H.R.%201234');
});
