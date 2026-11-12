import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
async function compile(name){
  const result=await build({entryPoints:[new URL('../src/components/explorer/archive/'+name,import.meta.url).pathname],bundle:true,platform:'node',format:'cjs',packages:'external',write:false,define:{'import.meta.env':'globalThis.__IMPORT_META_ENV__'}});
  const compiled={exports:{}};new Function('require','module','exports',result.outputFiles[0].text)(require,compiled,compiled.exports);return compiled.exports;
}
const {
  ArchiveDetail,
  ArchiveRows,
  HearingDetail,
  CommitteeDetail,
  WitnessDetail,
  PersonDetail,
  MemberDetail,
  SubjectDetail,
}=await compile('ArchiveDetail.tsx');
let formatting;const formatModule=()=>formatting??=compile('ArchiveFormats.tsx');
const row={list_row:0,filename:'Report.pdf',title:'Publisher report',format:'pdf',date_kind:'captured',first_captured:'2024-01-02',document_date:'2023-12-01',meeting_keys:['118001','118002'],hidden:false};
const detail={link_key:new Uint8Array(8).fill(17),saved_body:new Uint8Array(32).fill(17),saved_suffix:'.gz',saved_bytes:101*1024*1024,saved_media_type:'application/pdf',document_date_source:'publisher',removed_on:'2024-03-01',alternates:[{format:'xml',body:new Uint8Array(32).fill(18),suffix:'.gz',size:50}]};
const render=entry=>renderToStaticMarkup(React.createElement(ArchiveDetail,{entry,meetings:[{event_id:118001,title:'Transportation hearing'}],versions:[{...row,list_row:3}],rawBase:'https://raw.test/',onSelect:()=>{},onHearing:()=>{},onOpenSaved:()=>{}}));

test('release detail shows public dates, physical copies, alternates and sources',()=>{
  const html=render({document:row,detail,sources:[{url:'https://publisher.test/report',listed_on:'https://publisher.test/hearing',link_text:'Witness report',member_path:'member/report.pdf'}],recoveries:[]});
  for(const text of ['Publisher report','Captured 2024-01-02','2023-12-01 (publisher)','Removed from the hearing page by the committee on 2024-03-01','compressed download','XML','Transportation hearing','118002','Other versions','https://publisher.test/hearing','member/report.pdf'])assert(html.includes(text),text);
  for(const text of ['body_key','http_status','response_usable'])assert(!html.includes(text),text);
});

test('publisher evidence shows recorded failures and omitted resolutions',()=>{
  const html=render({document:{...row,format:'html'},detail:{...detail,saved_media_type:'text/html',
    main_content:{outcome:'unreadable',reason:'timeout',decision_id:'fixture-timeout'}},sources:[],recoveries:[]});
  for(const text of ['The HTML reader could not process this saved page.','timeout','fixture-timeout','Open original saved page'])assert(html.includes(text),text);
  const limited=render({document:{...row,format:'html'},detail:{...detail,saved_media_type:'text/html',
    main_content:{outcome:'fallback',evidence_limited:true,facts_limited:true}},sources:[],recoveries:[]});
  assert(limited.includes('The HTML reading exceeded the publisher metadata size limit.'));
  assert(limited.includes('Some publisher evidence exceeded the detail size limit.'));
  assert(limited.includes('Open original saved page'));
});

test('all recovery kinds and hidden direct links show their recorded decisions',()=>{
  const recoveries=['recovered_document','official_substitute','requested_content_in_official_hearing'].map(kind=>({kind,body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:20,recovered_url:'https://recovery.test/file',imported_at:'2020-01-01',identity_note:'Recorded identity evidence'}));
  const html=render({document:{...row,hidden:true},detail:{...detail,saved_body:null,review_note:'Superseded complete record',review_decided_at:'2024-02-02'},recoveries,sources:[{url:'javascript:alert(1)',listed_on:'https://u:p@publisher.test/secret'}]});
  for(const text of ['Removed by review','Superseded complete record','2024-02-02','Recovered document','Official substitute','Requested content in an official hearing','Recorded identity evidence'])assert(html.includes(text),text);
  assert(!html.includes('href="javascript:'));assert(!html.includes('href="https://u:p@'));
});

test('list rows distinguish editions and import dates without inventing captures',()=>{
  const html=renderToStaticMarkup(React.createElement(ArchiveRows,{rows:[
    row,
    {...row,list_row:1,document_date:null},
    {...row,list_row:2,document_date:null,date_kind:'import_day',first_captured:null,in_archive_since:'2020-01-02'}
  ],onSelect:()=>{}}));
  assert(html.includes('Captured 2024-01-02'));assert(html.includes('In our archive since 2020-01-02 (original capture date not recorded)'));assert(html.includes('2023-12-01'));
  const datedOnly=renderToStaticMarkup(React.createElement(ArchiveRows,{rows:[row],onSelect:()=>{}}));
  assert(datedOnly.includes('Document date: 2023-12-01'));
  assert(!datedOnly.includes('Captured 2024-01-02'),'List row omits redundant capture date when document date is present');
});

test('recovery detail preserves authored continuations and withholds only legacy boilerplate',()=>{
  const legacy='Reconciled from pinned accepted mappings '+'7'.repeat(64);
  const sentinel=legacy+'; receipt categories preserved';
  const recovery={kind:'recovered_document',body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:20};
  for(const note of [null,legacy,sentinel]){
    const html=render({document:row,detail,sources:[],recoveries:[{...recovery,identity_note:note}]});
    assert(html.includes('Recovered document'));
    assert(!html.includes('Reconciled from pinned accepted mappings'));
    assert(!html.includes('<p>null</p>'));
  }
  for(const note of ['The hearing contains the requested statement.',
    sentinel+'; reviewed against the committee index',
    legacy+'; the committee index identifies the statement.']){
    const html=render({document:row,detail,sources:[],recoveries:[{...recovery,identity_note:note}]});
    assert(html.includes(`<p>${note}</p>`),note);
    assert(html.includes('Recovered document'));
  }
});

test('blank and generic scrape titles fall back to clean congressional context and true file formats',()=>{
  const zipEntry={
    document:{...row,list_row:9,filename:'CHRG-109hhrg32242.zip',title:'ZIP',format:'json',congress:109,committee_keys:['hsju00'],document_kind:['published-hearing'],measure_keys:['109-hr-475']},
    detail:{...detail,saved_bytes:590,saved_media_type:'application/json'},
    sources:[{url:'https://publisher.test/CHRG-109hhrg32242.zip',member_path:'CHRG-109hhrg32242.zip'}],
    recoveries:[{kind:'recovered_document',body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:590,imported_at:'2024-01-01',identity_note:'Reconciled from pinned accepted mappings 00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864; receipt categories preserved'}]
  };
  const detailHtml=render(zipEntry);
  assert(detailHtml.includes('<h2>CHRG-109hhrg32242.zip</h2>'));
  assert(!detailHtml.includes('<h2>ZIP</h2>'));
  assert(detailHtml.includes('Open saved ZIP'));
  assert(detailHtml.includes('(590 B)'));
  assert(detailHtml.includes('109th Congress'));
  assert(detailHtml.includes('House Judiciary'));
  assert(detailHtml.includes('Published Hearing'));
  assert(detailHtml.includes('H.R. 475'));
  assert(!detailHtml.includes('Reconciled from pinned accepted mappings'));
  assert(!detailHtml.includes('File in archive: CHRG-109hhrg32242.zip'));

  const blankRowsHtml=renderToStaticMarkup(React.createElement(ArchiveRows,{rows:[
    {...row,list_row:10,filename:'',title:null,format:'pdf',saved_kind:'recovery',congress:118,committee_keys:['hsju01'],document_kind:['witness-statement']}
  ],onSelect:()=>{}}));
  assert(blankRowsHtml.includes('Witness Statement — House Judiciary'));
  assert(blankRowsHtml.includes('118th Congress · House Judiciary · Witness Statement'));
});


test('new counterpart and related-file claims retain their exact meaning on the page',async()=>{
  const fixture=JSON.parse(await readFile(new URL('./fixtures/recovery-labels.json',import.meta.url),'utf8'));
  for(const kind of fixture.render_cases){
    const html=render({document:row,detail:{...detail,saved_body:null},sources:[],recoveries:[{kind,body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:20,imported_at:'2024-01-01'}]});
    assert(html.includes(fixture.expected_labels[kind]),kind);
    assert(html.includes('Recovered and related files'));
    assert(!html.includes('Recovered document'),kind+' is not a recovered original');
    assert(!html.includes('Official substitute'),kind+' retains its narrower claim');
  }
});

test('a recovery with no import record omits the date line and retains its source',()=>{
  const html=render({document:row,detail:{...detail,saved_body:null},sources:[],recoveries:[{kind:'recovered_document',body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:20,imported_at:null,recovered_url:'https://recovery.test/seed-copy'}]});
  assert(html.includes('Recovered document'));
  assert(html.includes('https://recovery.test/seed-copy'));
  assert(!html.includes('Added to the archive'));
  assert(!html.includes('unknown'));
});


test('all measured seed formats keep their exact option values and counts with readable labels',async()=>{
  const {JSDOM}=await import('jsdom');
  const fixture=JSON.parse(await readFile(new URL('./fixtures/archive-formats.json',import.meta.url),'utf8'));
  const {ArchiveFormatFilter,formatLabel}=await formatModule();
  const html=renderToStaticMarkup(React.createElement(ArchiveFormatFilter,{options:fixture.formats,value:'application/x-mpegurl',onChange:()=>{}}));
  const dom=new JSDOM(html);try{
    const select=dom.window.document.querySelector('select');
    assert.equal(select.value,'application/x-mpegurl');
    assert.equal(select.options.length,fixture.formats.length+1);
    assert.equal(fixture.formats.reduce((sum,item)=>sum+item.count,0),fixture.rows);
    for(const item of fixture.formats){
      const option=[...select.options].find(option=>option.value===item.value);
      assert(option,item.value);assert.equal(option.textContent,`${item.label} (${item.count.toLocaleString('en-US')})`);
      assert.equal(option.parentElement.label,item.section);assert.equal(formatLabel(item.value),item.label);
    }
    for(const item of fixture.additional_formats)assert.equal(formatLabel(item.value),item.label);
    assert.equal(formatLabel('APPLICATION/X-MPEGURL'),'HLS playlist (MPEGURL)');
    assert.equal(formatLabel('new-format'),'Other format (new-format)');
    assert.equal(formatLabel(null),'Format not recorded');
  }finally{dom.window.close();}
});

test('response states remain explicit and selectable rather than masquerading as file formats',async()=>{
  const {ArchiveFormatFilter}=await formatModule();
  const html=renderToStaticMarkup(React.createElement(ArchiveFormatFilter,{options:[{value:'challenge_html',count:9},{value:'html_requires_document_discovery',count:5402}],value:'challenge_html',onChange:()=>{}}));
  assert(html.includes('Recorded response states'));assert(html.includes('Access-check page (not document content) (9)'));
  assert(html.includes('value="challenge_html" selected=""'));assert(!html.includes('CHALLENGE_HTML'));
  assert(html.includes('Page awaiting document discovery (5,402)'));
});

test('rows and saved-copy links share format labels without changing recorded file types',()=>{
  const changed={...row,format:'application/x-mpegurl'};
  const rows=renderToStaticMarkup(React.createElement(ArchiveRows,{rows:[changed],onSelect:()=>{}}));
  const html=render({document:changed,detail:{...detail,alternates:[{format:'docx',body:new Uint8Array(32).fill(18),suffix:'.gz',size:50}]},sources:[],recoveries:[]});
  assert(rows.includes('HLS playlist (MPEGURL)'));assert(!rows.includes('APPLICATION/X-MPEGURL'));
  assert(html.includes('Open saved HLS playlist (MPEGURL)'));assert(html.includes('Open alternate Word document (DOCX)'));
  assert.equal(changed.format,'application/x-mpegurl');
});

test('detail view derives committees from facts and URLs, renders GovInfo package links, and honors BASE_URL',()=>{
  globalThis.__IMPORT_META_ENV__={BASE_URL:'/congressional-tech/'};
  try{
    const derivedEntry={
      document:{...row,congress:118,committee_keys:[],meeting_keys:['118001']},
      detail:{
        ...detail,
        package_id:'CHRG-118hhrg55469',
        facts:[{field:'committee_code',value:'ap06'}],
      },
      sources:[
        {url:'https://docs.house.gov/meetings/SY/SY15/20240101/118001/HHRG-118-SY15-Wstate.pdf',listed_on:'https://www.csce.gov/hearings'},
      ],
      recoveries:[{kind:'recovered_document',body:new Uint8Array(32).fill(19),suffix:'.gz',bytes:50,recovered_url:'https://d1dth6e84htgma.cloudfront.net/doc.pdf'}],
    };
    const html=renderToStaticMarkup(React.createElement(ArchiveDetail,{
      entry:derivedEntry,
      meetings:[{event_id:118001,title:'Transportation infrastructure hearing'}],
      versions:[],
      rawBase:'https://raw.test/',
      onSelect:()=>{},
      onHearing:()=>{},
      onCommittee:()=>{},
      onOpenSaved:()=>{},
    }));
    assert(html.includes('House Appropriations — Interior, Environment, &amp; Related Agencies'));
    assert(html.includes('House Science, Space, &amp; Technology — Research &amp; Technology'));
    assert(html.includes('Helsinki Commission'));
    assert(html.includes('House Energy &amp; Commerce'));
    assert(!html.includes('/dashboard/'));
    assert(html.includes('href="https://www.govinfo.gov/app/details/CHRG-118hhrg55469"'));
    assert(html.includes('>Transportation infrastructure hearing</button>'));

    const selectSubHtml=render({
      document:{...row,congress:118,committee_keys:['hlfd00','hlvc00','hsap10','hsfa16','hsvr10']},
      detail,
      sources:[],
      recoveries:[],
    });
    assert(selectSubHtml.includes('House Judiciary — Select Subcommittee on the Weaponization of the Federal Government'));
    assert(selectSubHtml.includes('House Oversight &amp; Accountability — Select Subcommittee on the Coronavirus Pandemic'));
    assert(selectSubHtml.includes('House Appropriations — Energy &amp; Water Development'));
    assert(selectSubHtml.includes('House Foreign Affairs — Africa'));
    assert(selectSubHtml.includes('House Veterans&#x27; Affairs — Economic Opportunity'));
  }finally{
    delete globalThis.__IMPORT_META_ENV__;
  }
});

test('hearing evidence distinguishes the roster, record entries and publisher links',()=>{
  const html=renderToStaticMarkup(React.createElement(HearingDetail,{meeting:{
    event_id:100031,title:'A hearing',witnesses:[
      {witness_key:'witness',name:'Witness Example',testified:true},
      {witness_key:'statement',name:'Statement Example',witness_type:'statement_for_record',testified:false},
      {witness_key:'bio',name:'Biography Author',witness_type:'record_material'},
    ],
    document_references:[{collection:'meetingDocuments',ordinal:0,name:'Printed Hearing Record',
      role:'Support Document',format:'PDF',url:'https://www.congress.gov/example.pdf'}],
  }}));
  assert(html.includes('Witnesses and record entries (1 on the roster)'));
  assert(html.includes('Statement for the record'));
  assert(html.includes('Biography Author'));
  assert(html.includes('Record material'));
  const biography=renderToStaticMarkup(React.createElement(WitnessDetail,{witness:{
    witness_key:'bio',name:'Biography Author',witness_type:'record_material',
    appearances:[{event_id:100031,title:'A hearing'}],
  }}));
  assert(biography.includes('Record material'));
  assert(biography.includes('Related Hearings (1)'));
  assert(!biography.includes('Congressional Witness'));
  for(const value of ['Printed Hearing Record','Support Document','Publisher format PDF','https://www.congress.gov/example.pdf']){
    assert(html.includes(value));
  }
});

test('hearing captions keep separate saved bodies and label HLS as a download',()=>{
  const first='a'.repeat(64), second='b'.repeat(64);
  const html=renderToStaticMarkup(React.createElement(HearingDetail,{
    rawBase:'https://raw.test/',
    meeting:{event_id:100,videos:[{video_key:'recording-a',url:'https://fixture.test/video',tracks:[
      {sha256:first,suffix:'.gz',language:'en',format:'vtt',production:'live'},
      {sha256:second,suffix:'',language:'en',format:'m3u8',production:'archive'},
    ]}]},
  }));
  assert(html.includes('data-recording-key="recording-a"'));
  for(const text of ['https://fixture.test/video',`https://raw.test/bodies/sha256/aa/${first}.gz`,
    `https://raw.test/bodies/sha256/bb/${second}`,'en · vtt · live','en · m3u8 · archive',
    'Download saved HLS playlist','Playback is unavailable here.','download=""'])assert(html.includes(text),text);
});

test('hearing transcript inventory preserves printed, committee and caption source labels',()=>{
  const body='c'.repeat(64);
  const html=renderToStaticMarkup(React.createElement(HearingDetail,{
    rawBase:'https://raw.test/',onSelect:()=>{},
    meeting:{event_id:100,videos:[{video_key:'senate:source-control',tracks:[
      {sha256:body,suffix:'.gz',language:'en',format:'m3u8',production:'live'},
    ]}],transcripts:[
      {source:'printed_hearing',package_id:'CHRG-118hhrg12345',list_row:0,formats:['pdf']},
      {source:'committee_transcript',title:'Committee verbatim record',list_row:1,formats:['pdf']},
      {source:'captions',video_key:'senate:source-control',formats:['m3u8'],language:'en',production:'live'},
    ]},
  }));
  for(const text of ['Transcripts and captions','Printed hearing','Committee transcript',
    'CHRG-118hhrg12345','Committee verbatim record','senate:source-control',
    'Captions or subtitles · en · m3u8 · live',`https://raw.test/bodies/sha256/cc/${body}.gz`,
    'Download saved HLS playlist'])assert(html.includes(text),text);
  assert(!html.includes('<h3>Official Transcripts</h3>'));
  assert.equal((html.match(/class="explorer-text-button"/g)||[]).length,2,
    'Both genuine document sources keep their existing document actions.');
});

test('nomination committee actions retain publisher precision and stay separate from floor votes',()=>{
  const html=renderToStaticMarkup(React.createElement(SubjectDetail,{subject:{
    nomination_id:'119-pn-1011',kind:'nomination',description:'Charles Baldis',
    committee_activities:[{system_code:'ssga00',activities:[{name:'Reported By',date:'2026-07-22T14:47:05Z'}]}],
    floor_votes:[{vote_id:'119-s-1-225',date:'2026-08-07',result:'Confirmed'}],
  }}));
  assert(html.includes('2026-07-22T14:47:05Z'));
  assert(html.indexOf('Committee activities') < html.indexOf('Floor Votes'));
});

test('Phase-2 entity detail components render hearings, committees, witnesses, members, bills, and nominations with cross-links',()=>{
  const hearingHtml=renderToStaticMarkup(React.createElement(HearingDetail,{
    meeting:{
      event_id:118001,
      chamber:'house',
      congress:118,
      title:'Transportation infrastructure hearing',
      meeting_date:'2024-05-01',
      meeting_type:'hearing',
      status:'held',
      sittings:[{datetime:'2024-05-01T10:00:00Z',building:'Rayburn',room:'2167'}],
      committees:[{committee_key:'hspw00',system_code:'hspw00',name:'House Committee on Transportation and Infrastructure'}],
      subjects:[{subject_key:'118-hr-1234',short_title:'Surface Transportation Modernization Act'},{subject_key:'118-pn-730-2',citation:'PN730-2',title:'Jane Doe nomination'}],
      videos:[{video_key:'youtube:yt118001',source:'youtube',url:'https://www.youtube.com/watch?v=yt118001',title:'Hearing Livestream',duration_s:5420,tracks:[{label:'English captions',url:'https://fixture.test/captions.vtt'}]}],
      transcripts:[{jacket_number:'55-123',title:'Official Hearing Transcript',list_row:0}],
      witnesses:[{witness_key:'smith_jane',name:'Dr. Jane Smith',organization:'National Transit Institute',position:'Director',panel:1,documents:[row]}],
    },
    onSelect:()=>{},
    onCommittee:()=>{},
    onSubject:()=>{},
    onWitness:()=>{},
    onMember:()=>{},
  }));
  for(const text of [
    'Transportation infrastructure hearing',
    'Rayburn 2167',
    'House Committee on Transportation and Infrastructure',
    'H.R. 1234 — Surface Transportation Modernization Act',
    'PN730-2 — Jane Doe nomination',
    'Hearing Livestream',
    '1:30:20',
    'English captions',
    'Official Hearing Transcript',
    'Dr. Jane Smith',
    'National Transit Institute',
  ])assert(hearingHtml.includes(text),`Missing in HearingDetail: ${text}`);
  assert(!hearingHtml.includes('/dashboard/'));

  const committeeHtml=renderToStaticMarkup(React.createElement(CommitteeDetail,{
    committee:{
      committee_key:'hspw00',
      system_code:'hspw00',
      chamber:'house',
      type:'standing',
      current_name:'House Committee on Transportation and Infrastructure',
      resolved_name:'House Committee on Transportation and Infrastructure',
      jurisdiction:'Transportation, highways, aviation, and water resources.',
      url:'https://transportation.house.gov',
      doc_count:42,
      hearing_count:5,
      active_congress:118,
      roster_congresses:[118,117],
      names:[
        {name:'House Committee on Public Works and Transportation',start:'1975-01-03',end:'1995-01-03'},
        {name:'House Committee on Transportation and Infrastructure',start:'1995-01-03',end:null},
      ],
      subcommittees:[{committee_key:'hspw12',current_name:'Highways and Transit'}],
      roster:[{bioguide_id:'G000546',name:'Sam Graves',party:'R',state:'MO',role:'Chair'},{bioguide_id:'S000510',name:'Adam Smith',party:'D',state:'WA',role:'Ranking Member'}],
      hearings:[{event_id:118001,title:'Transportation infrastructure hearing',meeting_date:'2024-05-01'}],
    },
    onCommittee:()=>{},
    onHearing:()=>{},
    onMember:()=>{},
  }));
  for(const text of [
    'House Committee on Transportation and Infrastructure',
    'Transportation, highways, aviation, and water resources.',
    'House Committee on Public Works and Transportation',
    'Highways and Transit',
    'Sam Graves',
    'Adam Smith',
  ])assert(committeeHtml.includes(text),`Missing in CommitteeDetail: ${text}`);
  assert(!committeeHtml.includes('/dashboard/'));

  const witnessHtml=renderToStaticMarkup(React.createElement(WitnessDetail,{
    witness:{
      witness_key:'smith_jane',
      name:'Dr. Jane Smith',
      organizations:['National Transit Institute'],
      positions:['Director'],
      appearances:[{event_id:118001,title:'Transportation infrastructure hearing',meeting_date:'2024-05-01',panel:1,committee_keys:['hspw00']}],
      documents:[row],
    },
    onSelect:()=>{},
    onHearing:()=>{},
    onCommittee:()=>{},
  }));
  for(const text of ['Dr. Jane Smith','National Transit Institute','Director','Transportation infrastructure hearing','Publisher report'])assert(witnessHtml.includes(text),`Missing in WitnessDetail: ${text}`);

  const memberHtml=renderToStaticMarkup(React.createElement(MemberDetail,{
    member:{
      bioguide_id:'S000510',
      name:'Adam Smith',
      party:'D',
      state:'WA',
      district:9,
      chamber:'house',
      official_url:'https://adamsmith.house.gov',
      terms:[{congress:118,chamber:'house',party:'D',state:'WA',district:9}],
      roster_entries:[{committee_key:'hspw00',congress:118,role:'Ranking Member'}],
      sponsored_bills:[{subject_key:'118-hr-1234',short_title:'Surface Transportation Modernization Act'}],
      hearings:[{event_id:118001,title:'Transportation infrastructure hearing',meeting_date:'2024-05-01'}],
    },
    onCommittee:()=>{},
    onHearing:()=>{},
    onSubject:()=>{},
  }));
  for(const text of ['Adam Smith','WA-9','Bioguide: S000510','Ranking Member','H.R. 1234','Surface Transportation Modernization Act'])assert(memberHtml.includes(text),`Missing in MemberDetail: ${text}`);

  const billHtml=renderToStaticMarkup(React.createElement(SubjectDetail,{
    subject:{
      kind:'bill',
      subject_key:'118-hr-1234',
      congress:118,
      short_title:'Surface Transportation Modernization Act',
      title:'A bill to modernize surface transportation.',
      introduced_date:'2024-03-15',
      sponsor_bioguide_id:'S000510',
      sponsor_name:'Rep. Smith, Adam',
      sponsor_party:'D',
      sponsor_state:'WA',
      status:'Reported by Committee',
      latest_action_date:'2024-05-02',
      latest_action_text:'Ordered to be Reported.',
      committees:['hspw00'],
      cbo_estimates:[{title:'CBO Estimate for H.R. 1234',pub_date:'2024-05-10',url:'https://www.cbo.gov/publication/59999'}],
      votes:[{chamber:'house',roll_number:210,date:'2024-05-15',question:'On Passage',result:'Passed',yea:310,nay:110,url:'https://clerk.house.gov/evs/2024/roll210.xml'}],
      amendment_count:1,
      amendments:[{type:'HAMDT',number:99,sponsor_name:'Rep. Smith',purpose:'Bridge inspection funding'}],
      related_bills:[{subject_key:'118-s-567',relationship:'Companion bill'}],
      hearings:[{event_id:118001,title:'Transportation infrastructure hearing',meeting_date:'2024-05-01'}],
    },
    onHearing:()=>{},
    onCommittee:()=>{},
    onMember:()=>{},
    onSubject:()=>{},
  }));
  for(const text of [
    'H.R. 1234 — Surface Transportation Modernization Act',
    'Rep. Smith, Adam',
    'CBO Estimate for H.R. 1234',
    'Roll #210',
    '310–110',
    'Bridge inspection funding',
    'S. 567 (Companion bill)',
    'Congress.gov',
    'GPO GovInfo',
    'spicy-regs',
  ])assert(billHtml.includes(text),`Missing in SubjectDetail: ${text}`);
});

test('Phase-2 entity browse tabs, navigation parser, and inspector document-filter actions render cleanly',async()=>{
  const {ArchiveEntityRows,normalizeArchiveTab,tabTotalCount}=await compile('ArchiveEntityBrowse.tsx');
  const {readArchiveNavigation}=await compile('ArchiveExplorer.tsx');

  assert.equal(normalizeArchiveTab(null),'documents');
  assert.equal(normalizeArchiveTab('hearings'),'hearings');
  assert.equal(normalizeArchiveTab('meetings'),'hearings');
  assert.equal(normalizeArchiveTab('committees'),'committees');
  assert.equal(normalizeArchiveTab('witnesses'),'witnesses');
  assert.equal(normalizeArchiveTab('members'),'members');
  assert.equal(normalizeArchiveTab('subjects'),'subjects');
  assert.equal(normalizeArchiveTab('bills'),'subjects');

  const counts={meetings:12,committees:8,witnesses:34,members:535,bills:100,nominations:25};
  assert.equal(tabTotalCount('documents',6,counts),6);
  assert.equal(tabTotalCount('hearings',6,counts),12);
  assert.equal(tabTotalCount('committees',6,counts),8);
  assert.equal(tabTotalCount('witnesses',6,counts),34);
  assert.equal(tabTotalCount('members',6,counts),535);
  assert.equal(tabTotalCount('subjects',6,counts),125);

  const parsed=readArchiveNavigation('?tab=hearings&chamber=house&hearing=118001&subject_kind=bills');
  assert.equal(parsed.tab,'hearings');
  assert.equal(parsed.chamber,'house');
  assert.equal(parsed.hearing,'118001');
  assert.equal(parsed.subjectKind,'bills');

  const commonCallbacks={
    onInspectHearing:()=>{},
    onInspectCommittee:()=>{},
    onInspectWitness:()=>{},
    onInspectMember:()=>{},
    onInspectSubject:()=>{},
  };
  const hearingsListHtml=renderToStaticMarkup(React.createElement(ArchiveEntityRows,{
    tab:'hearings',
    rows:[{event_id:118001,congress:118,chamber:'house',committee_keys:['hspw00'],title:'Transportation infrastructure hearing',meeting_date:'2024-05-01',list_rows:[0],witnesses:[{}]}],
    ...commonCallbacks,
  }));
  assert(hearingsListHtml.includes('Transportation infrastructure hearing'));
  assert(hearingsListHtml.includes('1 document · 1 witness'));

  const committeesListHtml=renderToStaticMarkup(React.createElement(ArchiveEntityRows,{
    tab:'committees',
    rows:[{committee_key:'hspw00',chamber:'house',type:'standing',current_name:'House Committee on Transportation and Infrastructure',doc_count:42,hearing_count:5}],
    ...commonCallbacks,
  }));
  assert(committeesListHtml.includes('House Committee on Transportation and Infrastructure'));
  assert(committeesListHtml.includes('42 documents'));

  const witnessesListHtml=renderToStaticMarkup(React.createElement(ArchiveEntityRows,{
    tab:'witnesses',
    rows:[{witness_key:'smith_jane',name:'Dr. Jane Smith',organizations:['National Transit Institute'],positions:['Director'],appearances:[{}],list_rows:[0,1]}],
    ...commonCallbacks,
  }));
  assert(witnessesListHtml.includes('Dr. Jane Smith'));
  assert(witnessesListHtml.includes('2 documents'));

  const membersListHtml=renderToStaticMarkup(React.createElement(ArchiveEntityRows,{
    tab:'members',
    rows:[{bioguide_id:'S000510',name:'Adam Smith',party:'D',state:'WA',district:9,chamber:'house',terms:[{}],list_rows:[0]}],
    ...commonCallbacks,
  }));
  assert(membersListHtml.includes('Adam Smith'));
  assert(membersListHtml.includes('WA-9'));

  const subjectsListHtml=renderToStaticMarkup(React.createElement(ArchiveEntityRows,{
    tab:'subjects',
    rows:[{subject_key:'118-hr-1234',kind:'bill',congress:118,short_title:'Surface Transportation Modernization Act',sponsor_name:'Rep. Smith, Adam',list_rows:[0]}],
    ...commonCallbacks,
  }));
  assert(subjectsListHtml.includes('H.R. 1234 — Surface Transportation Modernization Act'));

  const inspectorHtml=renderToStaticMarkup(React.createElement(HearingDetail,{
    meeting:{event_id:118001,title:'Transportation infrastructure hearing'},
    onSelect:()=>{},
    onCommittee:()=>{},
    onSubject:()=>{},
    onWitness:()=>{},
    onMember:()=>{},
    onFilterDocuments:()=>{},
  }));
  assert(inspectorHtml.includes('Filter documents in Document Search'));

  const multiVersionRowsHtml=renderToStaticMarkup(React.createElement(ArchiveRows,{
    rows:[{...row,format:'other',version_keys:['vk1']}],
    onSelect:()=>{},
  }));
  assert(multiVersionRowsHtml.includes('Other file type (PDF)'));
  assert(multiVersionRowsHtml.includes('Multiple versions'));

  const dedupRecoveryHtml=render({
    document:{...row,saved_kind:'recovery'},
    detail,
    sources:[{url:'https://publisher.test/report',posted:'2024-01-01',first_seen:'2024-01-02'}],
    recoveries:[{kind:'recovered_document',body:new Uint8Array(32).fill(17),suffix:'.gz',bytes:50,imported_at:'2024-01-03'}],
  });
  assert(dedupRecoveryHtml.includes('Recovered document (saved copy above)'));
  assert(dedupRecoveryHtml.includes('Archival verification metadata'));
  assert(dedupRecoveryHtml.includes('First seen 2024-01-02'));
  assert(dedupRecoveryHtml.includes('(Report.pdf)'));
});

test('meeting outcomes stay separate from publisher notices and older evidence',()=>{
  const renderMeeting=meeting=>renderToStaticMarkup(React.createElement(HearingDetail,{meeting:{event_id:1,title:'Dated hearing',meeting_date:'2025-02-01',status:'Scheduled',...meeting},onSelect:()=>{}}));
  const scheduled=renderMeeting({outcome:'unknown',outcome_reason:'Only a schedule is available.'});
  assert(scheduled.includes('Publisher status: Scheduled'));
  assert(scheduled.includes('Outcome: unknown'));
  const held=renderMeeting({status:'Canceled',publisher_status:'Canceled',outcome:'held',outcome_basis:'printed_hearing',outcome_source_reference:'CHRG-119hhrg1',publisher_status_observations:[{source:'congress_gov',status:'Canceled',meeting_date:'2025-02-01'},{source:'house_xml',status:'Scheduled',meeting_date:'2025-02-08'}]});
  for(const value of ['Publisher status: Canceled','Outcome: held','CHRG-119hhrg1','congress_gov: Canceled','house_xml: Scheduled'])assert(held.includes(value),value);
  assert(renderMeeting({outcome:'canceled'}).includes('Outcome: canceled'));
  assert(renderMeeting({}).includes('Outcome: evidence unavailable in this release'));
});

test('WitnessDetail renders parenthetical retirement credentials, on_behalf_of, and name-matched Member links cleanly',()=>{
  const retiredHtml=renderToStaticMarkup(React.createElement(WitnessDetail,{
    witness:{
      witness_key:'janes_william',
      name:'William H. Janes',
      rank:'Colonel',
      credentials:'(U.S. Army, Ret.)',
      appearances:[{event_id:110001,title:'Defense oversight',position:'Counsel',organization:'Veterans League',on_behalf_of:'Military Retirees Association'}],
    },
    onHearing:()=>{},
  }));
  assert(retiredHtml.includes('<h2>Colonel William H. Janes (U.S. Army, Ret.)</h2>'));
  assert(!retiredHtml.includes('Janes, (U.S. Army'));
  assert(retiredHtml.includes('Counsel — Veterans League — on behalf of Military Retirees Association'));

  const matchedMemberHtml=renderToStaticMarkup(React.createElement(WitnessDetail,{
    witness:{
      witness_key:'matched_member',
      name:'Gus Bilirakis',
      witness_type:'member_appearance',
      bioguide_id:'B00O257',
      matched_bioguide_id:'B001257',
      match_basis:'name_chamber',
      appearances:[{event_id:118200,title:'Members Day'}],
    },
    onMember:()=>{},
  }));
  assert(matchedMemberHtml.includes('View Member Profile (B001257, name-matched)'));
  assert(!matchedMemberHtml.includes('B00O257'));
});

test('ct-960v and ct-ha10: retained Congress.gov no_longer_listed badges, person links, and PersonDetail render cleanly',async()=>{
  const {readArchiveNavigation}=await compile('ArchiveExplorer.tsx');
  const nav=readArchiveNavigation('?person=aa11bb22cc33dd44');
  assert.equal(nav.person,'aa11bb22cc33dd44');

  const hearingHtml=renderToStaticMarkup(React.createElement(HearingDetail,{
    meeting:{
      event_id:118800,
      title:'Grid Reliability Hearing',
      meeting_date:'2024-05-01',
      subjects:[
        {subject_key:'118-hr-100',short_title:'Clean Grid Act'},
        {subject_key:'118-pn-50',citation:'PN50',title:'Jane Nominee',listing_status:'no_longer_listed',unlisted_since:'2026-10-25'},
      ],
      unlisted_subjects:[
        {subject_key:'118-pn-50',last_listed_on:'2026-10-20',unlisted_since:'2026-10-25'},
      ],
      document_references:[
        {collection:'meeting_documents',ordinal:1,name:'Dropped Report',role:'Support Document',format:'PDF',url:'https://www.banking.senate.gov/dropped.pdf',listing_status:'no_longer_listed',unlisted_since:'2026-10-25'},
      ],
      witnesses:[
        {witness_key:'w_carter',person_key:'aa11bb22cc33dd44',name:'Robert Carter',organization:'Wind Association',position:'Counsel',listing_status:'no_longer_listed',unlisted_since:'2026-10-25'},
      ],
    },
    onWitness:()=>{},
    onPerson:()=>{},
    onSubject:()=>{},
  }));
  assert(hearingHtml.includes('No longer listed by Congress.gov since 2026-10-25'));
  assert(hearingHtml.includes('All appearances'));

  const witnessHtml=renderToStaticMarkup(React.createElement(WitnessDetail,{
    witness:{
      witness_key:'w_carter',
      person_key:'aa11bb22cc33dd44',
      name:'Robert Carter',
      organizations:['Wind Association'],
      positions:['Counsel'],
      listing_status:'no_longer_listed',
      unlisted_since:'2026-10-25',
      appearances:[{witness_key:'w_carter',event_id:118800,title:'Grid Reliability Hearing',meeting_date:'2024-05-01',listing_status:'no_longer_listed',unlisted_since:'2026-10-25'}],
      documents:[],
    },
    onHearing:()=>{},
    onPerson:()=>{},
  }));
  assert(witnessHtml.includes('No longer listed by Congress.gov since 2026-10-25'));
  assert(witnessHtml.includes('Person page'));

  assert(PersonDetail,'PersonDetail exported from ArchiveDetail.tsx');
  const personHtml=renderToStaticMarkup(React.createElement(PersonDetail,{
    person:{
      person_key:'aa11bb22cc33dd44',
      name:'Dr. José O’Reilly-Smith',
      name_variants:['Dr. José O’Reilly-Smith','OReilly Smith, Jose'],
      organization:'The Brookings Institution',
      organizations:['The Brookings Institution','brookings institution.'],
      positions:['Senior Fellow','Director'],
      grouping_basis:'name_organization',
      appearance_count:3,
      hearing_count:3,
      first_seen_date:'2003-09-23',
      last_seen_date:'2009-12-09',
      redirectedFrom:'0011223344556677',
      appearances:[
        {witness_key:'w1',event_id:901,title:'Hearing 901',meeting_date:'2024-05-01',name:'Dr. José O’Reilly-Smith',organization:'The Brookings Institution',position:'Senior Fellow',listing_status:'listed'},
        {witness_key:'w2',event_id:902,title:'Hearing 902',meeting_date:'2024-06-15',name:'OReilly Smith, Jose',organization:'brookings institution.',position:'Director',listing_status:'no_longer_listed',unlisted_since:'2026-10-25'},
        {witness_key:'w3',event_id:null,package_id:'CHRG-111shrg57186',name:'Dr. José O’Reilly-Smith',organization:'The Brookings Institution',position:'Senior Fellow',listing_status:'listed'},
      ],
      documents:[row],
    },
    onSelect:()=>{},
    onHearing:()=>{},
    onWitness:()=>{},
    onMember:()=>{},
    onPerson:()=>{},
  }));
  for(const text of [
    'Dr. José O’Reilly-Smith',
    'OReilly Smith, Jose',
    'The Brookings Institution',
    'Senior Fellow',
    'Appearances recorded:',
    '2003-09-23 to 2009-12-09',
    'https://www.govinfo.gov/app/details/CHRG-111shrg57186',
    'normalized name and organization',
    '0011223344556677',
    'No longer listed by Congress.gov since 2026-10-25',
    'Publisher report',
    'public',
    '/issues',
  ])assert(personHtml.includes(text),`Missing in PersonDetail: ${text}`);
});

test('cat2-pkk1 and P0-3b UI: military rank/credentials, MODS witness stubs, partitioned nominations & compact activities, suspect row dates, bare UUID cards, and retired version filenames',async()=>{
  const {RemovedDocumentNotice}=await compile('ArchiveExplorer.tsx');

  // P0-3b UI: PersonDetail & WitnessDetail render military rank, recorded ranks, and credentials.
  const genPersonHtml=renderToStaticMarkup(React.createElement(PersonDetail,{
    person:{
      person_key:'pk_nakasone',
      name:'Paul M. Nakasone',
      rank:'General',
      ranks:['General','Lieutenant General'],
      credentials:'USA',
      organizations:['Department of Defense'],
      positions:['Commander, U.S. Cyber Command'],
      grouping_basis:'name_organization',
      appearances:[
        {witness_key:'w1',event_id:501,title:'Cyber Posture Hearing',meeting_date:'2024-03-05',name:'Paul M. Nakasone',rank:'General',position:'Commander',organization:'DoD'},
      ],
      documents:[],
    },
  }));
  assert(genPersonHtml.includes('<h2>General Paul M. Nakasone</h2>'),genPersonHtml);
  assert(genPersonHtml.includes('Lieutenant General'),genPersonHtml);
  assert(genPersonHtml.includes('USA'),genPersonHtml);

  // P0-1 UI & P0-3b UI: WitnessDetail renders credentials and never emits trailing "Hearing " stub when event_id is null.
  const modsWitnessHtml=renderToStaticMarkup(React.createElement(WitnessDetail,{
    witness:{
      witness_key:'a62c806895c31d8e',
      name:'Michael L. Kussman',
      credentials:'M.D., M.S. MACP',
      organizations:['U.S. Department of Veterans Affairs'],
      positions:['Under Secretary for Health'],
      appearances:[
        {event_id:null,package_id:'CHRG-110shrg40547',meeting_title:'- HEARING ON PENDING LEGISLATIVE',meeting_date:'2007-11-06',committee_keys:['ssva00']},
        {event_id:null,package_id:null,meeting_title:null},
      ],
      documents:[],
    },
  }));
  assert(modsWitnessHtml.includes('M.D., M.S. MACP'),modsWitnessHtml);
  assert(modsWitnessHtml.includes('HEARING ON PENDING LEGISLATIVE'),modsWitnessHtml);
  assert(!modsWitnessHtml.includes('>Hearing <'),modsWitnessHtml);

  // P1-7 UI: Partitioned nomination links to /1022/10 and renders committee_activities in both compact and full modes.
  const nomSubject={
    nomination_id:'119-pn-1022-10',
    kind:'nomination',
    congress:119,
    description:'Mark Cruz, of Oregon, to be Director of the Indian Health Service',
    committees:[],
    committee_activities:[
      {system_code:'slia00',activities:[
        {name:'Referred To',date:'2025-06-02'},
        {name:'Reported By',date:'2025-07-22T14:47:05Z'},
      ]},
    ],
    floor_votes:[{vote_id:'119-s-1-200',date:'2025-09-10',result:'Confirmed'}],
  };
  const fullNomHtml=renderToStaticMarkup(React.createElement(SubjectDetail,{subject:nomSubject,onCommittee:()=>{}}));
  assert(fullNomHtml.includes('href="https://www.congress.gov/nomination/119th-congress/1022/10"'),fullNomHtml);
  assert(fullNomHtml.includes('Senate Indian Affairs'),fullNomHtml);
  assert(fullNomHtml.includes('Reported By'),fullNomHtml);
  assert(fullNomHtml.includes('2025-07-22T14:47:05Z'),fullNomHtml);
  const compactNomHtml=renderToStaticMarkup(React.createElement(SubjectDetail,{subject:nomSubject,compact:true,onCommittee:()=>{}}));
  assert(compactNomHtml.includes('Reported By'),compactNomHtml);
  assert(compactNomHtml.includes('Senate Indian Affairs'),compactNomHtml);

  // P1-6 UI & P2-9 UI: ArchiveRows badges suspect dates and replaces bare UUID primary titles with contextual labels.
  const suspectAndUuidRowsHtml=renderToStaticMarkup(React.createElement(ArchiveRows,{
    rows:[
      {...row,list_row:295289,title:'Bisignano Nomination',date_kind:'captured',first_captured:'2025-03-25',document_date:'2031-01-19',congress:119},
      {...row,list_row:7870,title:'Nathan Law Testimony',date_kind:'captured',first_captured:'2019-09-27',document_date:'1901-09-26',congress:116},
      {...row,list_row:31505,title:null,filename:'B9D24D45-9CB8-4A1C-AF4B-0429CF06BB2C',format:'pdf',congress:116,committee_keys:['ssva00'],document_date:'2020-03-03'},
    ],
    onSelect:()=>{},
  }));
  assert(suspectAndUuidRowsHtml.includes('2031-01-19 (read from the filename; likely misread)'),suspectAndUuidRowsHtml);
  assert(suspectAndUuidRowsHtml.includes('1901-09-26 (read from the filename; likely misread)'),suspectAndUuidRowsHtml);
  assert(!suspectAndUuidRowsHtml.includes('<strong>B9D24D45-9CB8-4A1C-AF4B-0429CF06BB2C</strong>'),suspectAndUuidRowsHtml);
  assert(suspectAndUuidRowsHtml.includes('archive-document-subtitle">B9D24D45-9CB8-4A1C-AF4B-0429CF06BB2C</span>'),suspectAndUuidRowsHtml);

  // F5 UI: RemovedDocumentNotice renders human-readable part filenames rather than raw 16-hex keys.
  const removedHtml=renderToStaticMarkup(React.createElement(RemovedDocumentNotice,{
    removed:{
      key:'cb0383af1fd10c1e',
      lastRelease:'ede659a056c04ce0c4f51c70b6848b4eaf1db1a2a2fa8aee04076973e2a1a450',
      lastFilename:'CHRG-115hhrg24725.pdf',
      versions:['58cc6f3f89fac200','a7b7aa76c6268c40'],
      versionItems:[
        {key:'58cc6f3f89fac200',label:'CHRG-115hhrg24725-pt1.pdf'},
        {key:'a7b7aa76c6268c40',label:'CHRG-115hhrg24725-pt2.pdf'},
      ],
    },
  }));
  assert(removedHtml.includes('href="?key=58cc6f3f89fac200">CHRG-115hhrg24725-pt1.pdf</a>'),removedHtml);
  assert(removedHtml.includes('href="?key=a7b7aa76c6268c40">CHRG-115hhrg24725-pt2.pdf</a>'),removedHtml);

  // NIT 1: HearingDetail publisherDocuments gives distinct keys to listed vs retained no_longer_listed ordinal-1 refs.
  const consoleErrors=[];
  const origConsoleError=console.error;
  console.error=(...args)=>{consoleErrors.push(args.join(' '));};
  let dupOrdHearingHtml='';
  try{
    dupOrdHearingHtml=renderToStaticMarkup(React.createElement(HearingDetail,{
      meeting:{
        event_id:999,
        congress:118,
        chamber:'house',
        title:'Retained Ordinal Collision Test',
        committees:[],
        sittings:[],
        coverage:[],
        witnesses:[],
        subjects:[],
        transcripts:[],
        videos:[],
        documents:[],
        document_references:[
          {collection:'meetingDocuments',ordinal:1,url:'https://docs.house.gov/current-1.pdf',name:'Current Ordinal 1',listing_status:'listed'},
          {collection:'meetingDocuments',ordinal:1,url:'https://docs.house.gov/dropped-1.pdf',name:'Dropped Ordinal 1',listing_status:'no_longer_listed',last_listed_on:'2026-10-20',unlisted_since:'2026-10-25'},
        ],
      },
    }));
  }finally{
    console.error=origConsoleError;
  }
  assert(dupOrdHearingHtml.includes('Current Ordinal 1')&&dupOrdHearingHtml.includes('Dropped Ordinal 1'),dupOrdHearingHtml);
  assert(!consoleErrors.some(msg=>msg.includes('Encountered two children with the same key')),consoleErrors.join('\n'));
});
