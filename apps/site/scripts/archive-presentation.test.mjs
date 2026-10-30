import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
async function compile(name){
  const result=await build({entryPoints:[new URL('../src/components/explorer/archive/'+name,import.meta.url).pathname],bundle:true,platform:'node',format:'cjs',packages:'external',write:false});
  const compiled={exports:{}};new Function('require','module','exports',result.outputFiles[0].text)(require,compiled,compiled.exports);return compiled.exports;
}
const {ArchiveDetail,ArchiveRows}=await compile('ArchiveDetail.tsx');
let formatting;const formatModule=()=>formatting??=compile('ArchiveFormats.tsx');
const row={list_row:0,filename:'Report.pdf',title:'Publisher report',format:'pdf',date_kind:'captured',first_captured:'2024-01-02',document_date:'2023-12-01',meeting_keys:['118001','118002'],hidden:false};
const detail={link_key:new Uint8Array(8).fill(17),saved_body:new Uint8Array(32).fill(17),saved_suffix:'.gz',saved_bytes:101*1024*1024,saved_media_type:'application/pdf',document_date_source:'publisher',removed_on:'2024-03-01',alternates:[{format:'xml',body:new Uint8Array(32).fill(18),suffix:'.gz',size:50}]};
const render=entry=>renderToStaticMarkup(React.createElement(ArchiveDetail,{entry,meetings:[{event_id:118001,title:'Transportation hearing'}],versions:[{...row,list_row:3}],rawBase:'https://raw.test/',onSelect:()=>{},onHearing:()=>{},onOpenSaved:()=>{}}));

test('release detail shows public dates, physical copies, alternates and sources',()=>{
  const html=render({document:row,detail,sources:[{url:'https://publisher.test/report',listed_on:'https://publisher.test/hearing',link_text:'Witness report',member_path:'member/report.pdf'}],recoveries:[]});
  for(const text of ['Publisher report','Captured 2024-01-02','2023-12-01 (publisher)','Removed from the hearing page by the committee on 2024-03-01','compressed download','XML','Transportation hearing','118002','Other versions','https://publisher.test/hearing','member/report.pdf'])assert(html.includes(text),text);
  for(const text of ['body_key','http_status','response_usable'])assert(!html.includes(text),text);
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
