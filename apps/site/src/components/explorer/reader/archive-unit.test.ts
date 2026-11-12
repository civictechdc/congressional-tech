import {test} from 'node:test';
import assert from 'node:assert/strict';
import {computeMaxPlausibleDateEpoch, dateLabels, detailProjection, lookupUrl, rankDocumentDateEpoch, recoveryLabel, savedCopy, openArchive} from './archive.ts';
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
import {ArchiveReleaseChangedError,byteCache} from './cache.ts';

test('a detail read requests only columns the packed list does not hold',()=>{
  assert.deepEqual(detailProjection(['link_key','saved_body','filename','title'],['filename','title','hidden']),['link_key','saved_body']);
  assert.deepEqual(detailProjection(['link_key','saved_body'],['filename']),['link_key','saved_body']);
});

test('default detail leaves publisher declarations and full text for on-demand reads',()=>{
  assert.deepEqual(detailProjection(
    ['link_key','title','description','main_content','page_metadata','selected_text'],['title'],
  ), ['link_key','description','main_content']);
});

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
  assert.equal(dateLabels({document_date:'2303-05-04'},{document_date_source:'filename',document_date_status:'suspect'}).document,
    '2303-05-04 (read from the filename; likely misread)');
  assert.equal(dateLabels({document_date:'2023-05-04'},{document_date_source:'filename',document_date_status:'accepted'}).document,'2023-05-04');
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
  const {createWorkerClient}=await import('./client.ts');
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
  const {createWorkerClient}=await import('./client.ts');let message;
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

test('recovery explanations survive legacy boilerplate cleanup',()=>{
  const legacy='Reconciled from pinned accepted mappings '+'7'.repeat(64);
  const sentinel=legacy+'; receipt categories preserved';
  for(const note of [null,undefined,'',legacy,sentinel]) assert.equal(cleanIdentityNote(note),null);
  for(const note of ['The hearing contains the requested statement.',
    sentinel+'; reviewed against the committee index',
    legacy+'; the committee index identifies the statement.']) assert.equal(cleanIdentityNote(note),note);
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
  assert.equal(congressGovNominationUrl('119-pn-730-2'),'https://www.congress.gov/nomination/119th-congress/730/2');
  assert.equal(congressGovNominationUrl('119-pn-1022-10'),'https://www.congress.gov/nomination/119th-congress/1022/10');
  assert.equal(congressGovNominationUrl('119-pn-850'),'https://www.congress.gov/nomination/119th-congress/850');
  assert.equal(congressGovNominationUrl('101-pn-50-1'),'https://www.congress.gov/nomination/101st-congress/50/1');
  assert.equal(congressGovMemberUrl('S000510','Adam Smith'),'https://www.congress.gov/member/adam-smith/S000510');
  assert.equal(spicyRegsUrl('H.R. 1234'),'https://spicyregs.org/?q=H.R.%201234');
});


test('a meeting names each transcript source it holds (ct-1i4q)', async () => {
  const {transcriptSourceLabels} = await import('./archive-entities.ts');
  assert.deepEqual(transcriptSourceLabels([
    {source: 'printed_hearing', package_id: 'CHRG-118hhrg1', list_row: 3},
    {source: 'committee_transcript', list_row: 9},
    {source: 'captions', video_key: 'youtube:abc'}, {source: 'captions', video_key: 'youtube:def'},
  ]), ['Printed hearing', 'Committee transcript', 'Captions or subtitles']);
  // Older releases list prints without a source.
  assert.deepEqual(transcriptSourceLabels([{package_id: 'CHRG-118hhrg1', list_row: 3}]), ['Printed hearing']);
  assert.deepEqual(transcriptSourceLabels(null), []);
});

test('default hearing, document and member views keep each current witness occurrence',async()=>{
  const {createArchiveEntities}=await import('./archive-entities.ts');
  const member='A000001';
  const table:Record<string,any[]>={
    witnesses:[
      {witness_key:'earlier',superseded_by:'current',event_id:100,name:'Alex Smith',bioguide_id:member},
      {witness_key:'current',superseded_by:null,event_id:100,name:'Alex Smith',bioguide_id:member},
      {witness_key:'repeated',superseded_by:null,event_id:100,name:'Alex Smith',bioguide_id:member,witness_type:'statement_for_record'},
      {witness_key:'bio',superseded_by:null,event_id:100,name:'Alex Smith',witness_type:'record_material'},
    ],
    meetings:[{event_id:100,title:'Test hearing'}],
    members:[{bioguide_id:member,name:'Alex Smith'}],
  };
  const document={list_row:0,witness_keys:['earlier','repeated']};
  const reader=createArchiveEntities({
    count:1,files:new Map(Object.keys(table).map(name=>[name+'.parquet',{}])),columns:new Map(),
    row:()=>document,value:()=>null,entity:async name=>table[name]??[],
    resolve:async()=>0,entry:async()=>({document}),versions:async()=>[],
  });
  const keys=(rows:any[])=>rows.map(w=>w.witness_key).sort();
  const meeting=await reader.getMeeting(100);
  assert.deepEqual(keys(meeting?.witnesses??[]),['bio','current','repeated']);
  assert.equal(meeting?.witnesses.find(w=>w.witness_key==='repeated').witness_type,'statement_for_record');
  assert.deepEqual(keys((await reader.openDocument(0)).witnesses),['current','repeated']);
  assert.deepEqual(keys((await reader.getMember(member))?.witness_records??[]),['current','repeated']);
  assert.equal((await reader.getWitness('earlier'))?.witness_key,'earlier');
  assert.equal((await reader.getWitness('bio'))?.witness_type,'record_material');
  assert.deepEqual(keys((await reader.listEntities('witnesses')).rows),['current']);
});

test('a sitting Member keeps a Member tag in the hearing list, leaves the witness lists, and reaches their page name-matched (ct-kw85)',async()=>{
  // 'matched' is a name alone at a Member Day hearing (match_basis member_day): it links like every name-matched row.
  const {createArchiveEntities,witnessMember,witnessRecordEntryLabel}=await import('./archive-entities.ts');
  const member='B001257';
  const table:Record<string,any[]>={
    witnesses:[
      {witness_key:'outside',superseded_by:null,event_id:200,name:'Dr. Ada Lovelace'},
      {witness_key:'matched',superseded_by:null,event_id:200,name:'The Honorable Gus Bilirakis',witness_type:'member_appearance',
        matched_bioguide_id:member,match_basis:'member_day'},
      {witness_key:'published',superseded_by:null,event_id:201,name:'The Honorable Gus M. Bilirakis',bioguide_id:member,
        witness_type:'member_appearance',matched_bioguide_id:member,match_basis:'publisher_id'},
    ],
    meetings:[{event_id:200,title:'Members Day'},{event_id:201,title:'Hearing on H.R. 1'}],
    members:[{bioguide_id:member,name:'Gus Bilirakis'}],
  };
  const reader=createArchiveEntities({
    count:0,files:new Map(Object.keys(table).map(name=>[name+'.parquet',{}])),columns:new Map(),
    row:()=>null,value:()=>null,entity:async name=>table[name]??[],
    resolve:async()=>null,entry:async()=>null,versions:async()=>[],
  });
  const meeting=await reader.getMeeting(200);
  const rows=meeting?.witnesses??[];
  assert.deepEqual(rows.map((w:any)=>w.witness_key).sort(),['matched','outside']);
  assert.equal(witnessRecordEntryLabel(rows.find((w:any)=>w.witness_key==='matched').witness_type),'Member');
  assert.equal(rows.filter((w:any)=>!witnessRecordEntryLabel(w.witness_type)).length,1);
  assert.deepEqual(witnessMember(rows.find((w:any)=>w.witness_key==='matched')),{bioguide_id:member,name_matched:true});
  assert.deepEqual(witnessMember(table.witnesses[2]),{bioguide_id:member,name_matched:false});
  // A publisher's typo stays published; the link goes to the matched Member.
  assert.deepEqual(witnessMember({bioguide_id:'KOOO395',matched_bioguide_id:'K000395',match_basis:'name_chamber'}),
    {bioguide_id:'K000395',name_matched:true});
  assert.deepEqual(witnessMember({bioguide_id:'W000789'}),{bioguide_id:'W000789',name_matched:false});
  assert.deepEqual((await reader.listEntities('witnesses')).rows.map((w:any)=>w.witness_key),['outside']);
  const page=await reader.getMember(member);
  assert.deepEqual(page?.witness_records.map((w:any)=>w.witness_key).sort(),['matched','published']);
  assert.deepEqual(page?.hearings.map((h:any)=>[String(h.event_id),Boolean(h.name_matched)]).sort(),[['200',true],['201',false]]);
  assert.equal((await reader.getWitness('matched'))?.member_name_matched,true);
});

test('a nomination keeps its own data when optional hearings fail',async()=>{
  const {createArchiveEntities}=await import('./archive-entities.ts');
  const reads:string[]=[];
  const nomination={nomination_id:'119-pn-850',citation:'PN850',committee_activities:[]};
  const unreadable={nomination_id:'119-pn-12-10',committee_activities:undefined};
  let loadMeetings=async ():Promise<any[]>=>{throw new Error('Hearings unavailable');};
  const reader=createArchiveEntities({
    count:0,files:new Map(['bills','meetings','nominations'].map(name=>[name+'.parquet',{}])),columns:new Map(),
    row:()=>null,value:()=>null,resolve:async()=>null,entry:async()=>null,versions:async()=>[],
    entity:async name=>{
      reads.push(name);
      if(name==='nominations')return [nomination,unreadable];
      if(name==='meetings')return loadMeetings();
      throw new Error('Bills unavailable');
    },
  });
  const found=await reader.getSubject(nomination.citation);
  assert.equal(found?.nomination_id,nomination.nomination_id);
  assert.deepEqual(found?.committee_activities,[]);
  assert.deepEqual(reads,['nominations','meetings']);
  assert.equal((await reader.getSubject(unreadable.nomination_id))?.committee_activities,null);

  loadMeetings=async ()=>{throw new ArchiveReleaseChangedError('Release changed');};
  await assert.rejects(reader.getSubject(nomination.nomination_id),ArchiveReleaseChangedError);

  let markStarted!:()=>void;
  const started=new Promise<void>(resolve=>{markStarted=resolve;});
  loadMeetings=()=>{markStarted();return new Promise(()=>{});};
  const controller=new AbortController();
  const pending=reader.getSubject(nomination.nomination_id,controller.signal);
  await started;
  controller.abort();
  await assert.rejects(pending,{name:'AbortError'});
});

test('a witness row with no name is labelled by its organization, never by its key (ct-rg34)',async()=>{
  const {witnessLabel}=await import('./archive-entities.ts');
  assert.equal(witnessLabel({witness_key:'865fc801b9f493de',name:null,organization:'American Legion'}),'American Legion');
  assert.equal(witnessLabel({witness_key:'k',name:'Richard F. Weidman',organization:'Vietnam Veterans of America'}),'Richard F. Weidman');
  assert.equal(witnessLabel({witness_key:'k',name:null,organization:'American Legion',witness_type:'statement_for_record'}),'Statement for the record');
  assert.equal(witnessLabel({witness_key:'k',name:null,organization:null}),'k');
});

test('witnessLabel, witness search, and member document filter preserve rank, parenthetical credentials, on_behalf_of, and name-matched Members (ct-17op, ct-eofd)',async()=>{
  const {witnessLabel, createArchiveEntities}=await import('./archive-entities.ts');
  assert.equal(witnessLabel({witness_key:'k',name:'Michael E. Conley',rank:'Lt. Gen.',credentials:'USAF'}),'Lt. Gen. Michael E. Conley, USAF');
  assert.equal(witnessLabel({witness_key:'k',name:'Rochelle Walensky',rank:null,credentials:'MD, MPH'}),'Rochelle Walensky, MD, MPH');
  assert.equal(witnessLabel({witness_key:'k',name:'William H. Janes',rank:'Colonel',credentials:'(U.S. Army, Ret.)'}),'Colonel William H. Janes (U.S. Army, Ret.)');
  assert.equal(witnessLabel({witness_key:'k',name:'Nancy Knight',rank:'Rear Admiral',credentials:'M.D., USPHS (Ret.)'}),'Rear Admiral Nancy Knight, M.D., USPHS (Ret.)');
  const entities=createArchiveEntities({
    count:2,files:new Map([['witnesses.parquet',{}],['members.parquet',{}]]),columns:new Map(),value:()=>null,row:(i:number)=>({list_row:i}),
    entity:async(name:string)=>name==='witnesses'?[
      {witness_key:'w1',occasion:'meeting:1001',name:'Michael E. Conley',rank:'Lt. Gen.',credentials:'USAF',position:'Commander',organization:'U.S. Air Force',on_behalf_of:'Air Mobility Coalition',list_rows:[0]},
      {witness_key:'w2',occasion:'meeting:1002',name:'Gus Bilirakis',witness_type:'member_appearance',matched_bioguide_id:'B001257',match_basis:'member_day',list_rows:[1]},
    ]:[{bioguide_id:'B001257',name:'Gus M. Bilirakis'}],
    resolve:async()=>null,entry:async()=>null,versions:async()=>[],
  });
  const res:any=await entities.getWitness('w1');
  assert.ok(res);
  assert.equal(res.rank,'Lt. Gen.');
  assert.equal(res.credentials,'USAF');
  assert.equal(res.appearances[0].rank,'Lt. Gen.');
  assert.equal(res.appearances[0].credentials,'USAF');
  for(const q of ['Lt. Gen.','USAF','Lt. Gen. Michael E. Conley','Air Mobility Coalition']){
    assert.deepEqual((await entities.listEntities('witnesses',{q})).rows.map((w:any)=>w.witness_key),['w1'],`query=${q}`);
  }
  const filtered=await entities.prepareQuery({member:['B001257']});
  assert.deepEqual([...(filtered.allowedRows??[])],[1]);
});

test('person pages resolve direct keys, 1-hop aliases, ambiguous splits, variant search, and unlisted meeting subjects (ct-ha10, ct-960v)',async()=>{
  const {createArchiveEntities}=await import('./archive-entities.ts');
  const table:Record<string,any[]>={
    people:[
      {
        person_key:'pk_jane',name:'Dr. Jane Doe',name_variants:['Jane Doe','Dr. Jane Doe'],
        bioguide_id:null,grouping_basis:'name_organization',organizations:['Energy Institute'],
        positions:['Director'],witness_keys:['w1','w2','w3'],event_ids:[300,301],appearance_count:3,
        first_seen_date:'2024-03-01',last_seen_date:'2025-01-15',
      },
      {
        person_key:'pk_a',name:'Alex Smith',name_variants:['Alex Smith'],bioguide_id:null,
        grouping_basis:'name_organization',organizations:['Org A'],positions:[],
        witness_keys:['wa'],event_ids:[302],appearance_count:1,
      },
      {
        person_key:'pk_b',name:'Alex Smith',name_variants:['Alex Smith'],bioguide_id:null,
        grouping_basis:'name_organization',organizations:['Org B'],positions:[],
        witness_keys:['wb'],event_ids:[303],appearance_count:1,
      },
    ],
    witnesses:[
      {witness_key:'w1',person_key:'pk_jane',superseded_by:null,event_id:300,name:'Jane Doe',organization:'Energy Institute',listing_status:'listed'},
      {witness_key:'w2',person_key:'pk_jane',superseded_by:null,event_id:301,name:'Dr. Jane Doe',organization:'Energy Institute',listing_status:'no_longer_listed',unlisted_since:'2025-02-01'},
      {witness_key:'w3',person_key:'pk_jane',superseded_by:null,event_id:null,package_id:'CHRG-119shrg99999',name:'Jane Doe',organization:'Energy Institute',listing_status:'listed'},
    ],
    meetings:[
      {
        event_id:300,congress:118,chamber:'house',title:'Grid Reliability',meeting_date:'2024-03-01',
        subject_keys:['118-hr-100','118-hr-200'],
        unlisted_subjects:[{subject_key:'118-hr-200',last_listed_on:'2024-02-20',unlisted_since:'2024-02-25'}],
        document_references:[{title:'Prepared Statement',url:'https://docs.house.gov/1.pdf',witness_key:'w1',listing_status:'listed'}],
      },
      {event_id:301,congress:119,chamber:'senate',title:'Clean Power',meeting_date:'2025-01-15',transcripts:[{package_id:'CHRG-119shrg99999'}],subject_keys:[],unlisted_subjects:[],document_references:[]},
    ],
    bills:[
      {bill_id:'118-hr-100',citation:'H.R. 100',title:'Grid Act'},
      {bill_id:'118-hr-200',citation:'H.R. 200',title:'Dropped Bill Act'},
    ],
  };
  const aliases:Record<string,any>={
    pk_old_jane:{key:'pk_old_jane',successor:'pk_jane',candidates:[],status:'unambiguous',kind:'merged'},
    pk_split:{key:'pk_split',successor:null,candidates:['pk_a','pk_b'],status:'ambiguous',kind:'split'},
    pk_retired:{key:'pk_retired',successor:null,candidates:[],status:'unresolved',kind:null},
  };
  const reader=createArchiveEntities({
    count:1,
    files:new Map([...Object.keys(table).map(name=>[name+'.parquet',{}]),['person_aliases.parquet',{}],['witness_key_map.parquet',{}]]),
    columns:new Map([['witness_keys',[['w1']]]]),
    row:()=>({title:'Prepared Statement',event_id:300,witness_keys:['w1']}),
    value:(col,idx)=>col==='witness_keys'&&idx===0?['w1']:null,
    entity:async name=>table[name]??[],
    personRecord:async key=>table.people.find(p=>p.person_key===key)??null,
    personAlias:async key=>aliases[key]??null,
    witnessKeyMap:async key=>key==='w_old_1'?{key:'w_old_1',successor:'w1',candidates:[],status:'unambiguous',basis:'locator',occasion:'meeting:300',source:'congress_gov'}:null,
    resolve:async()=>null,entry:async()=>null,versions:async()=>[],
  });

  const direct=await reader.getPerson('pk_jane');
  assert.equal(direct?.person_key,'pk_jane');
  assert.equal(direct?.redirected_from,null);
  assert.equal(direct?.appearances.length,3);
  const pkgApp=direct?.appearances.find((a:any)=>a.witness_key==='w3');
  assert.equal(pkgApp?.meeting_title,'Clean Power');
  assert.equal(pkgApp?.meeting_date,'2025-01-15');
  assert.equal(direct?.documents.length,1);

  const redirected=await reader.getPerson('pk_old_jane');
  assert.equal(redirected?.person_key,'pk_jane');
  assert.equal(redirected?.redirected_from,'pk_old_jane');

  const split=await reader.getPerson('pk_split');
  assert.equal(split?.retired?.status,'ambiguous');
  assert.deepEqual(split?.retired?.candidates,['pk_a','pk_b']);

  const retired=await reader.getPerson('pk_retired');
  assert.equal(retired?.retired?.status,'unresolved');

  const listed=await reader.listEntities('people',{q:'Jane Doe'});
  assert.deepEqual(listed.rows.map((p:any)=>p.person_key),['pk_jane']);

  const prepared=await reader.prepareQuery({person:'pk_jane'});
  assert.deepEqual([...(prepared?.allowedRows??[])],[0]);
  const preparedAlias=await reader.prepareQuery({person:'pk_old_jane'});
  assert.deepEqual([...(preparedAlias?.allowedRows??[])],[0]);
  const preparedWitnessAlias=await reader.prepareQuery({witness:'w_old_1'});
  assert.deepEqual([...(preparedWitnessAlias?.allowedRows??[])],[0]);

  const meeting=await reader.getMeeting(300);
  const droppedSubject=meeting?.subjects.find((s:any)=>s.subject_key==='118-hr-200');
  assert.equal(droppedSubject?.listing_status,'no_longer_listed');
  assert.equal(droppedSubject?.unlisted_since,'2024-02-25');
});

test('cat2-pkk1 and P0-3b: dynamic 2027+ date bound, suspect list-row dates, bare-UUID fallback labels, ranked names, and MODS package_id enrichment',async()=>{
  const {createArchiveEntities,formatRankedName,witnessLabel}=await import('./archive-entities.ts');
  const {formatRetiredVersions}=await import('./archive.ts');

  // P1-6: 2027 dates sort normally (no hardcoded 2026-12-31 cliff) while far-future 2031/2303 dates demote.
  const bound2027=computeMaxPlausibleDateEpoch(Date.parse('2027-02-01T00:00:00Z'),Date.parse('2027-01-20T00:00:00Z'));
  const feb2027=Date.parse('2027-02-15T00:00:00Z');
  const dec2026=Date.parse('2026-12-15T00:00:00Z');
  const jan2031=Date.parse('2031-01-19T00:00:00Z');
  assert.ok(rankDocumentDateEpoch(feb2027,bound2027)>rankDocumentDateEpoch(dec2026,bound2027));
  assert.ok(rankDocumentDateEpoch(dec2026,bound2027)>rankDocumentDateEpoch(jan2031,bound2027));

  // P1-6: list-row calls dateLabels(row, row) without detail.document_date_status on Release 4.
  const suspectFutureRow={date_kind:'captured',first_captured:'2025-03-25',document_date:'2031-01-19',congress:119};
  assert.equal(dateLabels(suspectFutureRow,suspectFutureRow).document,'2031-01-19 (read from the filename; likely misread)');
  const suspect1901Row={date_kind:'captured',first_captured:'2019-09-27',document_date:'1901-09-26',congress:116};
  assert.equal(dateLabels(suspect1901Row,suspect1901Row).document,'1901-09-26 (read from the filename; likely misread)');
  const validScheduledRow={date_kind:'captured',first_captured:'2026-11-10',document_date:'2026-11-18',congress:119};
  assert.equal(dateLabels(validScheduledRow,validScheduledRow).document,'2026-11-18');

  // P2-9: untitled bare-UUID filenames synthesize contextual titles while keeping the UUID in subtitle.
  const uuidPresented=presentDocument({
    title:null,
    filename:'B9D24D45-9CB8-4A1C-AF4B-0429CF06BB2C',
    format:'pdf',
    congress:116,
    committee_keys:['ssva00'],
    document_date:'2020-03-03',
  });
  assert.ok(!uuidPresented.title.includes('B9D24D45'),`UUID leaked into primary title: ${uuidPresented.title}`);
  assert.ok(uuidPresented.title.includes("Senate Veterans' Affairs"),uuidPresented.title);
  assert.equal(uuidPresented.subtitle,'B9D24D45-9CB8-4A1C-AF4B-0429CF06BB2C');

  // P0-3b: military rank + credentials propagate without duplicating existing prefixes.
  assert.equal(formatRankedName('Paul M. Nakasone','General'),'General Paul M. Nakasone');
  assert.equal(formatRankedName('General Paul M. Nakasone','General'),'General Paul M. Nakasone');
  assert.equal(witnessLabel({witness_key:'w_nak',name:'Paul M. Nakasone',rank:'General'}),'General Paul M. Nakasone');

  // P0-1 & P0-3b: historical MODS witness (event_id = null, package_id = CHRG-110shrg40547) enriches from list.parquet.
  const docs=[
    {list_row:0,filename:'CHRG-110shrg40547.htm',title:'- HEARING ON PENDING LEGISLATIVE',format:'html',congress:110,chambers:['senate'],committee_keys:['ssva00'],document_date:'2007-11-06',meeting_keys:[]},
    {list_row:1,filename:'CHRG-110shrg40547.pdf',title:null,format:'pdf',congress:110,chambers:[],committee_keys:[],document_date:null,meeting_keys:[]},
  ];
  const table:Record<string,any[]>={
    witnesses:[
      {
        witness_key:'a62c806895c31d8e',person_key:'pk_kussman',superseded_by:null,
        event_id:null,package_id:'CHRG-110shrg40547',name:'Michael L. Kussman',
        rank:null,credentials:'M.D., M.S. MACP',position:'Under Secretary for Health',
        organization:'U.S. Department of Veterans Affairs',listing_status:'listed',
      },
      {
        witness_key:'w_nak_1',person_key:'pk_nakasone',superseded_by:null,
        event_id:501,name:'Paul M. Nakasone',rank:'General',credentials:'USA',
        position:'Commander, U.S. Cyber Command',organization:'Department of Defense',listing_status:'listed',
      },
    ],
    people:[
      {
        person_key:'pk_nakasone',name:'Paul M. Nakasone',name_variants:['Paul M. Nakasone'],
        rank:'General',ranks:['General','Lieutenant General'],credentials:'USA',
        grouping_basis:'name_organization',organizations:['Department of Defense'],
        positions:['Commander, U.S. Cyber Command'],witness_keys:['w_nak_1'],event_ids:[501],appearance_count:1,
      },
    ],
    meetings:[{event_id:501,congress:118,chamber:'senate',title:'Cyber Posture Hearing',meeting_date:'2024-03-05',committee_keys:['ssas00']}],
    members:[],
  };
  const colNames=['filename','title','format','congress','chambers','committee_keys','document_date','meeting_keys'];
  const reader=createArchiveEntities({
    count:docs.length,
    files:new Map([...Object.keys(table).map(n=>[n+'.parquet',{}]),['people.parquet',{}]]),
    columns:new Map(colNames.map(c=>[c,{}])),
    row:i=>docs[i],
    value:(col,i)=>(docs[i] as any)?.[col]??null,
    entity:async name=>table[name]??[],
    resolve:async()=>null,entry:async()=>null,versions:async()=>[],
  });

  const kussman=await reader.getWitness('a62c806895c31d8e');
  assert.equal(kussman?.credentials,'M.D., M.S. MACP');
  assert.equal(kussman?.appearances[0]?.meeting_title,'HEARING ON PENDING LEGISLATIVE');
  assert.equal(kussman?.appearances[0]?.meeting_date,'2007-11-06');
  assert.equal(kussman?.appearances[0]?.congress,110);
  assert.deepEqual(kussman?.appearances[0]?.committee_keys,['ssva00']);
  assert.equal(kussman?.documents.length,2);

  const nakasone=await reader.getPerson('pk_nakasone');
  assert.equal(nakasone?.rank,'General');
  assert.deepEqual(nakasone?.ranks,['General','Lieutenant General']);
  assert.equal(nakasone?.credentials,'USA');
  const searchGen=await reader.listEntities('people',{q:'general paul'});
  assert.deepEqual(searchGen.rows.map((p:any)=>p.person_key),['pk_nakasone']);

  // F5: formatRetiredVersions resolves part filenames and disambiguates identical-filename splits.
  const distinctParts=formatRetiredVersions([
    {key:'58cc6f3f89fac200',doc:{filename:'CHRG-115hhrg24725-pt1.pdf',format:'pdf'}},
    {key:'a7b7aa76c6268c40',doc:{filename:'CHRG-115hhrg24725-pt2.pdf',format:'pdf'}},
  ]);
  assert.deepEqual(distinctParts,[
    {key:'58cc6f3f89fac200',label:'CHRG-115hhrg24725-pt1.pdf'},
    {key:'a7b7aa76c6268c40',label:'CHRG-115hhrg24725-pt2.pdf'},
  ]);
  const sameFilenameParts=formatRetiredVersions([
    {key:'58cc6f3f89fac200',doc:{filename:'CHRG-115hhrg24725.pdf',format:'pdf',first_captured:'2024-01-02'}},
    {key:'a7b7aa76c6268c40',doc:{filename:'CHRG-115hhrg24725.pdf',format:'pdf',first_captured:'2024-06-01'}},
  ]);
  assert.equal(sameFilenameParts[0].label,'CHRG-115hhrg24725.pdf (captured 2024-01-02, PDF, 58cc6f3f)');
  assert.equal(sameFilenameParts[1].label,'CHRG-115hhrg24725.pdf (captured 2024-06-01, PDF, a7b7aa76)');
});
