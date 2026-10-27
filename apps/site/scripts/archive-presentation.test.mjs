import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {build} from 'esbuild';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const result=await build({entryPoints:[new URL('../src/components/explorer/archive/ArchiveDetail.tsx',import.meta.url).pathname],bundle:true,platform:'node',format:'cjs',packages:'external',write:false});
const compiled={exports:{}};new Function('require','module','exports',result.outputFiles[0].text)(require,compiled,compiled.exports);
const {ArchiveDetail,ArchiveRows}=compiled.exports;
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
  const html=renderToStaticMarkup(React.createElement(ArchiveRows,{rows:[row,{...row,list_row:1,date_kind:'import_day',first_captured:null,in_archive_since:'2020-01-02'}],onSelect:()=>{}}));
  assert(html.includes('Captured 2024-01-02'));assert(html.includes('In our archive since 2020-01-02 (original capture date not recorded)'));assert(html.includes('2023-12-01'));
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
