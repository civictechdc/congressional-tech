// DOM interaction tests, with mocked data and no browser or network access.
// npm install --prefix .cache/filename-viewer-tests --no-save --ignore-scripts jsdom
// node --test tests/test_filename_viewer_ui.mjs
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {test} from 'node:test';

const require = createRequire(new URL('../.cache/filename-viewer-tests/package.json', import.meta.url));
const {JSDOM} = require('jsdom');
const html = await readFile(new URL('../docs/youtube-coverage/research/filename-viewer.html', import.meta.url), 'utf8');
const script = await readFile(new URL('../docs/youtube-coverage/research/filename-viewer.mjs', import.meta.url), 'utf8');
const original = 'https://committee.test/UploadedFiles/Resolution.pdf';
const final = 'https://committee.test/uploadedfiles/resolution.pdf';
const origin = {file_url: final, pages: [], recovered_urls: [], redirects: [{original, final}]};
const record = {source_id: 'stable-final', document_id: 'group', filename: 'resolution.pdf',
  source_url: final, body_key: 'bodies/sha256/hidden-from-summary.gz', document_kind: null,
  source_congress: null, body_format: ['pdf'], format: ['pdf'],
  name_token: ['resolution_by_cmw'], date_token: ['01.30.2019'], date_token_candidates: ['2019-01-30'],
  source_occurrences: [{source_occurrence_scope: ['capture'], source_receipt_key: ['receipts/archive.jsonl.gz']}]};
const entry = {record, document: record, filename: record.filename, origin, document_origin: origin,
  catalog_id: 'snapshot', saved_file_available: true, sources_share_saved_file: true,
  sources: [{...record, retained: true}, {...record, source_id: 'stable-original', source_url: original, retained: true}],
  reading: {version: 'test', recognized_convention: false, metadata: {name_token: record.name_token,
    date_token: record.date_token, date_token_candidates: record.date_token_candidates}, observations: []}};
const evidence = {verified: true, bytes: 108272, page_count: 2, pages: [{number: 1, text: '<script>not executable</script>\nRESOLUTION'}],
  content_fields: {content_document_kind: ['committee-resolution'], content_congress: ['116']},
  receipt: {retrieved_at: '2026-10-11T01:39:53Z', http_status: 200, complete: true}};
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

async function app(respond) {
  const dom = new JSDOM(html, {url: 'https://viewer.test/?row=12', runScripts: 'outside-only'});
  const w = dom.window;
  w.HTMLDialogElement.prototype.showModal = function() {this.open = true;};
  w.HTMLDialogElement.prototype.close = function() {this.open = false;};
  w.HTMLElement.prototype.scrollIntoView = function() {};
  const requests = [];
  w.fetch = async url => {
    requests.push(url);
    if (url === '/api/info') return {ok:true, json:async()=>({catalog_id:'snapshot', house_naming_version:'published',
      documents:1, capture_records:0, rows:2, fields:Object.keys(record), facets:{congress:[],document_kind:[],document_family:[],format:['pdf']}})};
    if (url.startsWith('/api/rows')) return {ok:true, json:async()=>({rows:[{...record,_row:12,retained:true,source_count:2}],total:1,page:1,pages:1,limit:100})};
    return respond ? respond(url) : {ok:true, json:async()=>url.startsWith('/api/entry/') ? entry : evidence};
  };
  await w.eval('(async()=>{' + script + '\n})()');
  await flush();
  return {dom,w,requests,get:id=>w.document.getElementById(id)};
}

test('review shows publisher, catalog uncertainty, saved evidence and stable links separately', async()=>{
  const {dom,w,get} = await app();
  try {
    assert.equal(get('error').hidden,true);
    assert.match(get('origin').textContent,/committee.test/);
    assert.match(get('origin').textContent,/Referring page not recorded/);
    assert.doesNotMatch(get('origin').textContent,/receipts\/|bodies\//);
    assert.equal(get('source-link').href,final);
    assert.match(get('saved-link').href,/\/saved\/stable-final\?catalog=snapshot$/);
    assert.match(get('document-summary').textContent,/Unclassified/);
    assert.match(get('filename-findings').textContent,/not a verified person/);
    assert.match(get('filename-findings').textContent,/January 30, 2019/);
    assert.match(get('document-summary').textContent,/Committee resolution/);
    assert.match(get('document-summary').textContent,/116/);
    assert.match(get('saved-evidence').textContent,/2 pages/);
    assert.match(get('saved-evidence').textContent,/Complete response saved/);
    assert.equal(get('saved-evidence').querySelector('script'),null);
    assert.match(get('source-variants').textContent,/share one saved file/);
    assert.match(get('source-variants').textContent,/Original URL/);
    assert.match(get('source-variants').textContent,/Redirect destination/);
    assert.match(w.location.search,/source=stable-final/);
    assert.match(w.location.search,/catalog=snapshot/);
    assert.equal(new URL(w.location.href).searchParams.has('row'),false);
    assert.equal(get('technical').open,false);
    get('field-search').value='Remaining filename text';
    get('field-search').dispatchEvent(new w.Event('input'));
    assert.match(get('detail-data').textContent,/resolution_by_cmw/);
    get('field-search').value='source_congress';
    get('show-empty').checked=true;
    get('show-empty').dispatchEvent(new w.Event('change'));
    assert.match(get('detail-data').textContent,/Not recorded/);
  } finally {dom.window.close();}
});

test('referring page labels stay paired and candidate pages remain qualified', async()=>{
  const linked = structuredClone(entry);
  linked.origin.pages = [{urls:['https://committee.test/hearing'],titles:['<img src=x onerror=alert(1)>'],
    link_labels:['Resolution'],link_urls:[final],relationship:'Linked from'},
    {urls:['https://committee.test/one','https://committee.test/two'],titles:['Unpaired title'],
      link_labels:[],link_urls:[],relationship:'Possible source page'}];
  const {dom,get} = await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?linked:evidence}));
  try {
    assert.doesNotMatch(get('origin').textContent,/Referring page not recorded/);
    assert.match(get('origin').textContent,/Linked from/);
    assert.match(get('origin').textContent,/Possible source page/);
    assert.match(get('origin').textContent,/Recorded page titles: Unpaired title/);
    assert.equal(get('origin').querySelector('img'),null);
    assert.equal([...get('origin').querySelectorAll('a')].find(a=>a.textContent.startsWith('<img')).href,
      'https://committee.test/hearing');
  } finally {dom.window.close();}
});

test('snapshot error does not display another record or enable its actions', async()=>{
  const {dom,get} = await app(async()=>({ok:false,json:async()=>({error:'This link belongs to a different catalog snapshot.'})}));
  try {
    assert.equal(get('detail-title').textContent,'Record unavailable');
    assert.match(get('document-summary').textContent,/different catalog snapshot/);
    assert.equal(get('saved-link').hidden,true);
    assert.equal(get('copy').disabled,true);
  } finally {dom.window.close();}
});

test('switching a source prevents late content from replacing the current selection', async()=>{
  let finishOld;
  const {dom,w,get} = await app(async url=>{
    if(url.startsWith('/api/entry/')) {
      const selected=structuredClone(entry);
      if(url.includes('stable-original')) selected.record={...selected.record,source_id:'stable-original',source_url:original,filename:'Resolution.pdf'};
      return {ok:true,json:async()=>selected};
    }
    if(url.includes('stable-final')) return new Promise(resolve=>{finishOld=()=>resolve({ok:true,json:async()=>({...evidence,bytes:999})});});
    return {ok:true,json:async()=>({...evidence,bytes:456})};
  });
  try {
    get('source-variants').querySelectorAll('button')[1].click();
    await flush();
    assert.match(get('detail-selected').textContent,/Resolution.pdf/);
    assert.match(get('saved-evidence').textContent,/456 bytes/);
    finishOld();
    await flush();
    assert.match(get('saved-evidence').textContent,/456 bytes/);
    assert.doesNotMatch(get('saved-evidence').textContent,/999 bytes/);
    assert.match(w.location.search,/source=stable-original/);
  } finally {dom.window.close();}
});

test('bill facts consolidate aliases and expose Congress conflicts without losing raw fields', async()=>{
  const bill=structuredClone(entry);
  Object.assign(bill.record,{congress:['111','1117'],source_congress:['117'],measure_number:['2126'],measure_references:['s2126'],measure_token:['s'],measure_token_code:['s'],measure_token_label:['Senate Bill'],measure_type:['s'],package_family:['BILLS'],package_family_code:['bills'],package_family_label:['Congressional Measures']});
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?bill:evidence}));
  try {
    const facts=get('filename-findings').querySelector('dl');
    assert.equal([...facts.querySelectorAll('dt')].filter(el=>el.textContent==='Measure').length,1);
    assert.match(facts.textContent,/S\. 2126 — Senate bill/);
    assert.doesNotMatch(facts.textContent,/Measure token|Measure number|Measure type|Package family code/);
    assert.match(get('document-summary').textContent,/Competing filename readings/);
    assert.match(get('document-summary').textContent,/Source: 117/);
    assert.match(get('document-summary').textContent,/Filename and source values disagree/);
    assert.match(get('detail-data').textContent,/measure_token_code/);
  } finally {dom.window.close();}
});

test('source overview deduplicates URLs and separates machine evidence from website pages', async()=>{
  const sourced=structuredClone(entry);
  sourced.origin.pages=[{urls:['https://committee.test/hearing','https://api.congress.gov/v3/hearing/116/senate/1'],titles:[],link_labels:[],link_urls:[],relationship:'Recorded source page'},
    {urls:['https://committee.test/hearing','http://committee.test/hearing','https://committee.test/feed.xml'],titles:[],link_labels:[],link_urls:[],relationship:'Recorded source page'}];
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?sourced:evidence}));
  try {
    assert.equal([...get('origin').querySelectorAll('a')].filter(a=>a.href==='https://committee.test/hearing').length,1);
    assert.equal(get('origin').querySelectorAll(':scope > .provenance-item').length,1);
    const machine=[...get('origin').querySelectorAll('details')].find(el=>el.textContent.includes('API, feed or data'));
    assert.match(get('origin').textContent,/2 recorded URL forms/);
    assert.equal(machine.open,false); assert.match(machine.textContent,/API record/); assert.match(machine.textContent,/Feed/);
  } finally {dom.window.close();}
});

test('unsaved API identity and comparison do not claim missing format or content evidence', async()=>{
  const unsaved=structuredClone(entry);
  Object.assign(unsaved.record,{filename:'1',source_url:'https://api.congress.gov/v3/hearing/116/senate/1?format=json',body_key:null,format:null,body_format:null,record_role:['document'],name_token:null,date_token:null,date_token_candidates:null,filename_origins:['url_path']});
  unsaved.document=unsaved.record;unsaved.filename='1';unsaved.saved_file_available=false;unsaved.sources=[{...unsaved.record,retained:false}];
  unsaved.api_reference={title:'Senate hearing 1 · Congress 116'};
  unsaved.reading={version:'published',metadata:{generic_identifier:['1']},observations:[],recognized_convention:false};
  const {dom,get}=await app(async()=>({ok:true,json:async()=>unsaved}));
  try {
    assert.equal(get('detail-title').textContent,unsaved.api_reference.title);
    assert.equal(get('source-link').textContent,'Open API record ↗');
    assert.match(get('document-summary').textContent,/FormatUnknown/);
    assert.doesNotMatch(get('document-summary').textContent,/inferred from filename|recognizable type/);
    assert.match(get('filename-findings').textContent,/Literal URL-derived filename: 1/);
    const comparison=get('filename-findings').querySelector('table');
    assert.match(comparison.textContent,/Generic identifier—1/);
    assert.match(get('filename-findings').textContent,/Equal version labels do not establish identical/);
    assert.equal(get('saved-evidence').hidden,true);
  } finally {dom.window.close();}
});

test('field picker searches raw names and PDF text expands without a nested scroll region', async()=>{
  const {dom,w,get,requests}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?entry:{...evidence,pages:[{number:1,text:'Line of PDF text\n'.repeat(60)}]}}));
  try {
    get('field').value='__advanced__';get('field').dispatchEvent(new w.Event('change'));
    assert.equal(get('advanced-field').hidden,false);
    get('field-picker-search').value='name_token';get('field-picker-search').dispatchEvent(new w.Event('input'));
    assert.equal(get('field-options').querySelectorAll('button').length,1);
    get('field-options').querySelector('button').click();await flush();
    assert.equal(get('field').value,'name_token');assert.equal(get('advanced-field').hidden,true);
    assert(requests.some(url=>url.includes('field=name_token')));
    // Reopen a row after the filter closes details.
    get('rows').querySelector('button').click();await flush();
    const expand=[...get('saved-evidence').querySelectorAll('button')].find(el=>el.textContent==='Show full page text');
    expand.click();assert.equal(expand.getAttribute('aria-expanded'),'true');
    assert.equal(get('saved-evidence').querySelector('pre').classList.contains('preview'),false);
  } finally {dom.window.close();}
});

test('closing a direct review link restores search; a clicked row restores its button', async()=>{
  const {dom,w,get}=await app();
  try {
    get('close-detail').click();assert.equal(w.document.activeElement,get('q'));
    const button=get('rows').querySelector('button');button.focus();button.click();await flush();
    get('close-detail').click();assert.equal(w.document.activeElement,button);
  } finally {dom.window.close();}
});
