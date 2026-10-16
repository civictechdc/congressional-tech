// DOM interaction tests, with mocked data and no browser or network access.
// npm install --workspace apps/site
// node --test tests/test_filename_viewer_ui.mjs
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {showPublicationUpdate} from '../apps/site/src/components/filename-publication.mjs';

const require = createRequire(new URL('../apps/site/package.json', import.meta.url));
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

test('new data is reachable inside an open detail panel and follows the selected file', () => {
  const dom = new JSDOM(html, {url: 'https://viewer.test/?source=first&catalog=old'});
  try {
    const {document, location, history} = dom.window;
    showPublicationUpdate({catalogId: 'latest', document, location});
    const notice = document.querySelector('dialog [data-catalog-update]');
    assert.ok(notice);
    assert.equal(notice.hidden, false);
    const link = notice.querySelector('a');
    assert.equal(new URL(link.href).searchParams.get('source'), 'first');
    history.replaceState(null, '', '?source=second&catalog=old&q=hearing');
    link.onfocus();
    assert.equal(new URL(link.href).searchParams.get('source'), 'second');
    assert.equal(new URL(link.href).searchParams.get('catalog'), 'latest');
    assert.equal(new URL(link.href).searchParams.get('q'), 'hearing');
    showPublicationUpdate({message: 'This review snapshot could not be loaded.', document, location});
    assert.match(notice.textContent, /could not be loaded/);
    assert.equal(new URL(link.href).searchParams.has('catalog'), false);
  } finally { dom.window.close(); }
});

async function app(respond, info={}) {
  const dom = new JSDOM(html, {url: 'https://viewer.test/?row=12', runScripts: 'outside-only'});
  const w = dom.window;
  w.HTMLDialogElement.prototype.showModal = function() {this.open = true;};
  w.HTMLDialogElement.prototype.close = function() {this.open = false;};
  w.HTMLElement.prototype.scrollIntoView = function() {};
  const requests = [];
  w.fetch = async url => {
    requests.push(url);
    if (url === '/api/info') return {ok:true, json:async()=>({catalog_id:'snapshot', house_naming_version:'published',
      documents:1, capture_records:0, rows:2, fields:Object.keys(record), facets:{congress:[],document_kind:[],document_family:[],format:['pdf']},...info})};
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
    assert.doesNotMatch(get('filename-findings').textContent,/Remaining filename text|resolution_by_cmw/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/not a verified person/);
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
    assert.equal(get('technical').open,true);
    get('field-search').value='Remaining filename text';
    get('field-search').dispatchEvent(new w.Event('input'));
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/resolution_by_cmw/);
    get('field-search').value='source_congress';
    get('show-empty').checked=true;
    get('show-empty').dispatchEvent(new w.Event('change'));
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
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
    assert.match(get('origin').textContent,/Found on/);
    assert.match(get('origin').textContent,/Possible source page/);
    assert.doesNotMatch(get('origin').textContent,/Unpaired title/); // No invented page/title pairing.
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

test('transitive provenance shows an ordered hearing-to-page-to-file chain', async()=>{
  const linked=structuredClone(entry),hearing='https://committee.test/hearing',article='https://news.test/article';
  linked.origin.pages=[
    {urls:[article],titles:['UN article'],link_labels:['Event programme'],link_urls:[final],relationship:'Recorded source page'},
    {urls:[hearing],titles:['Armed Conflict and Starvation'],dates:['2022-04-12'],types:['hearing notice'],
      link_labels:['Yemen'],link_urls:[article],relationship:'Linked through'},
  ];
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?linked:evidence}));
  try {
    const chain=get('origin').querySelector('.source-chain');
    assert.ok(chain);
    assert.deepEqual([...chain.querySelectorAll('a')].map(a=>a.href),[hearing,article]);
    assert.match(get('origin').textContent,/Associated hearing/);
    assert.match(chain.textContent,/Armed Conflict and Starvation.*April 12, 2022.*UN article.*This file/s);
    assert.equal(get('origin').querySelectorAll('a[href="'+article+'"]').length,1);
    const supporting=get('origin').querySelector('.supporting-links');
    assert.equal(supporting.open,false);
    assert.match(supporting.textContent,/committee.test.*Yemen.*news.test.*Event programme/s);
    assert.doesNotMatch(chain.textContent,/Yemen|Event programme/);
    assert.doesNotMatch(get('origin').textContent,/Possible source page/);
  } finally {dom.window.close();}
});

test('ambiguous page and link lists remain references, not an invented hearing path', async()=>{
  const linked=structuredClone(entry),hearing='https://committee.test/hearing',article='https://news.test/article';
  linked.origin.pages=[
    {urls:[article],titles:[],link_labels:[],link_urls:[final],relationship:'Recorded source page'},
    {urls:[hearing,'https://committee.test/other'],titles:[],types:['hearing notice'],
      link_labels:['Yemen'],link_urls:[article],relationship:'Linked through'},
  ];
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?linked:evidence}));
  try {
    assert.equal(get('origin').querySelector('.source-chain'),null);
    assert.equal(get('origin').querySelectorAll('a[href="'+hearing+'"]').length,1);
    assert.match(get('origin').textContent,/Related source/);
  } finally {dom.window.close();}
});

test('a displayed provenance path requires the recorded URL scheme to match', async()=>{
  const linked=structuredClone(entry);
  linked.origin.pages=[
    {urls:['https://news.test/article'],titles:[],link_labels:[],link_urls:[final],relationship:'Recorded source page'},
    {urls:['https://committee.test/hearing'],titles:[],types:['hearing notice'],
      link_labels:[],link_urls:['http://news.test/article'],relationship:'Linked through'},
  ];
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?linked:evidence}));
  try {
    assert.equal(get('origin').querySelector('.source-chain'),null);
    assert.match(get('origin').textContent,/Related source/);
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
    assert.match(get('document-summary').textContent,/Group kind/);
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
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
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
    const machine=get('origin').querySelector('.supporting-links');
    assert.equal([...get('origin').querySelectorAll('a')].filter(a=>a.href==='http://committee.test/hearing').length,0);
    assert.equal(machine.open,false); assert.match(machine.textContent,/Senate hearing 1/); assert.match(machine.textContent,/Feed/);
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
    assert.equal(get('source-link').firstElementChild.textContent,'Open API record ↗');
    assert.match(get('document-summary').textContent,/FormatUnknown/);
    assert.doesNotMatch(get('document-summary').textContent,/inferred from filename|recognizable type/);
    assert.match(get('filename-findings').textContent,/Literal URL-derived filename: 1/);
    const comparison=get('filename-findings').querySelector('table');
    assert.match(comparison.textContent,/Unclassified identifier—1/);
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

test('static publication shows recorded evidence without claiming live inspection or rerunning rules', async()=>{
  const published=structuredClone(entry);
  published.saved_file_available=false;published.published_only=true;published.reading=null;
  published.record.content_congress=['116'];
  const {dom,get,requests}=await app(async url=>({ok:true,json:async()=>published}));
  try {
    assert.equal(get('saved-link').hidden,true);
    assert.match(get('document-summary').textContent,/Stored in R2/);
    assert.match(get('content-summary').textContent,/published findings/);
    assert.match(get('content-summary').textContent,/116/);
    assert.match(get('document-summary').textContent,/file access unavailable here/);
    assert.equal(get('saved-evidence').hidden,true);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/bodies\/sha256\/hidden-from-summary.gz/);
    assert.match(get('filename-findings').textContent,/does not rerun/);
    assert.equal(requests.some(url=>url.startsWith('/api/evidence/')),false);
  } finally {dom.window.close();}
});

test('published saved-copy action sits beside the original without invoking local evidence services', async()=>{
  const published=structuredClone(entry);
  Object.assign(published,{saved_file_available:false,published_only:true,reading:null,saved_file_url:'https://data.test/saved/hash/Recovered.pdf'});
  const {dom,get,requests}=await app(async()=>({ok:true,json:async()=>published}));
  try {
    assert.equal(get('saved-link').hidden,false);
    assert.equal(get('saved-link').firstElementChild.textContent,'Open saved copy ↗');
    assert.match(get('saved-link').textContent,/R2 archive/);
    assert.match(get('source-link').textContent,/committee.test/);
    assert.equal(get('saved-link').href,published.saved_file_url);
    assert.equal(get('source-link').href,final);
    assert.equal(get('saved-link').parentElement,get('source-link').parentElement);
    assert.doesNotMatch(get('document-summary').textContent,/Saved response|file access unavailable/);
    assert.equal(requests.some(url=>url.startsWith('/api/evidence/')),false);
  } finally {dom.window.close();}
});

test('repeated hearing observations become one source note without discarding original evidence', async()=>{
  const hearing='https://www.rules.senate.gov/hearings/dara-lindenbaum';
  const apiUrl='https://api.congress.gov/v3/committee-meeting/117/senate/332244';
  const download='https://www.rules.senate.gov/download/dana-lindenbaum';
  const linkText='Transcript_Nomination Hearing of Dara Lindenbaum.pdf';
  const observed=structuredClone(entry);
  observed.origin={file_url:final,recovered_urls:[],redirects:[{original:download,final}],pages:[
    {urls:[hearing,apiUrl],titles:['Nomination Hearing'],link_labels:[linkText],link_urls:[download],relationship:'Linked from'},
    {urls:[hearing,apiUrl],titles:['Nomination Hearing'],link_labels:[],link_urls:[download],relationship:'Recorded source page'},
    {urls:[apiUrl,hearing],titles:['Nomination Hearing'],link_labels:[linkText],link_urls:[download],relationship:'Recorded source page'},
    {urls:[hearing],titles:['Nomination Hearing'],link_labels:[linkText],link_urls:[download],relationship:'Linked from'},
  ]};
  observed.record.source_occurrences=observed.origin.pages.map((page,i)=>({source_page_url:page.urls,source_page_title:page.titles,
    source_link_label:page.link_labels,source_link_url:page.link_urls,source_receipt_line:[String(i+1)]}));
  const before=JSON.stringify(observed.record);
  const {dom,w,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?observed:evidence}));
  try {
    const links=[...get('origin').querySelectorAll('a')];
    for(const url of [hearing,apiUrl,download])assert.equal(links.filter(a=>a.href===url).length,1);
    assert.equal(get('origin').querySelectorAll('blockquote').length,1);
    assert.equal(get('origin').querySelector('blockquote').textContent,linkText);
    assert.equal(links.find(a=>a.href===hearing).textContent,'Nomination Hearing ↗');
    assert.doesNotMatch(get('origin').textContent,/Recorded page and link associations|Recorded page titles/);
    const evidenceButton=get('origin').querySelector('button');assert.equal(evidenceButton.textContent,'View 4 source observations');
    evidenceButton.click();
    assert.equal(get('technical').open,true);assert.equal(get('field-search').value,'source_occurrences');
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.equal(get('detail-data').querySelectorAll('details').length,4);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    for(const item of get('detail-data').querySelectorAll('details')){item.open=true;item.dispatchEvent(new dom.window.Event('toggle'));}await flush();
    assert.match(get('detail-data').textContent,/Receipt line/);
    assert.equal(JSON.stringify(observed.record),before);
    assert.equal(w.document.activeElement,get('technical').querySelector('summary'));
  } finally {dom.window.close();}
});

test('compact heading expands without altering the filename and resets on the next record', async()=>{
  const {dom,get}=await app();
  try {
    const full=get('detail-title').textContent;
    get('title-toggle').click();
    assert.equal(get('title-toggle').getAttribute('aria-expanded'),'true');
    assert.equal(get('detail-title').textContent,full);
    assert.equal(get('detail-title').classList.contains('expanded'),true);
    get('source-variants').querySelectorAll('button')[1].click();await flush();
    assert.equal(get('title-toggle').getAttribute('aria-expanded'),'false');
    assert.equal(get('detail-title').classList.contains('expanded'),false);
  } finally {dom.window.close();}
});


test('download state and related hearing resources are not filename interpretations', async()=>{
  const current=structuredClone(entry);
  Object.assign(current.record,{state_outcome:['pending'],state_family:['documents'],
    state_checked_at:['2026-10-13T12:00:00Z'],hearing_package_id:['CHRG-118shrg53528'],
    hearing_resources:[{url:'https://www.govinfo.gov/package.pdf',association_basis:'endpoint_package_candidate'}]});
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?current:evidence}));
  try {
    assert.match(get('document-summary').textContent,/Recorded fetchPending/);
    assert.doesNotMatch(get('filename-findings').textContent,/pending|state|CHRG|package.pdf|hearing resources/i);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/pending|Pending/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/endpoint_package_candidate/);
  } finally {dom.window.close();}
});

test('parser fragments are secondary, all original fields remain searchable by purpose', async()=>{
  const parsed=structuredClone(entry);
  Object.assign(parsed.record,{day_token:['20'],month_token:['September'],generic_identifier:['00'],
    short_date_token:['210915'],label:['nomination'],subject_token:['An appointment'],state_outcome:['pending']});
  parsed.document={...parsed.record,document_kind:['nomination']};
  const before=JSON.stringify(parsed.record);
  const {dom,w,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?parsed:evidence}));
  try {
    assert.doesNotMatch(get('filename-findings').querySelector('dl').textContent,/Day token|Month token|Unclassified identifier|Unresolved short date|Nomination/);
    assert.doesNotMatch(get('filename-findings').querySelector('dl').textContent,/Subject text|An appointment/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/Subject text.*An appointment/s);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    const raw=[...get('detail-data').querySelectorAll('.raw-key')].map(el=>el.textContent);
    for(const key of ['day_token','month_token','generic_identifier','short_date_token','name_token','state_outcome']) assert(raw.includes(key),key);
    get('filename-findings').querySelector('button').click();
    assert.equal(get('technical').open,true);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/day_token/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.doesNotMatch(get('detail-data').textContent,/state_outcome/);
    assert.equal(w.document.activeElement,get('field-search'));
    assert.equal(JSON.stringify(parsed.record),before);
  } finally {dom.window.close();}
});

test('source-page classification remains visible when it disagrees with filename classification', async()=>{
  const parsed=structuredClone(entry);
  Object.assign(parsed.record,{document_kind:['nomination'],document_kind_source:['filename'],source_document_type:['transcript'],source_document_type_basis:['senate_parser_inference']});
  parsed.document={...parsed.record};
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?parsed:evidence}));
  try {
    assert.match(get('document-summary').textContent,/Filename kindNomination/);
    assert.match(get('document-summary').textContent,/Source-page kindTranscriptInferred from page metadata/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/senate_parser_inference/);
  } finally {dom.window.close();}
});

test('empty results and search errors provide recovery without stale pagination', async()=>{
  const {dom,w,get}=await app();
  try {
    get('close-detail').click();
    w.filenameViewerApi=async()=>({rows:[],total:0,page:1,pages:0,limit:50});
    get('q').value='no match';
    get('search-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await flush();
    assert.equal(get('empty').hidden,false);
    assert.equal(w.document.querySelector('.pager').hidden,true);
    assert.equal(get('reset').disabled,false);
    w.filenameViewerApi=async()=>{throw new Error('Temporary range failure');};
    get('search-form').dispatchEvent(new w.Event('submit',{cancelable:true}));await flush();
    assert.equal(get('empty').hidden,true);
    assert.equal(get('error').hidden,false);
    assert.match(get('error-message').textContent,/Temporary range failure/);
    assert.equal(get('results').inert,false);
    w.filenameViewerApi=async()=>({rows:[],total:0,page:1,pages:0,limit:50});
    get('retry').click();await flush();
    assert.equal(get('error').hidden,true);
    assert.equal(get('empty').hidden,false);
  } finally {dom.window.close();}
});

test('search-field selection remains discoverable when filters are collapsed', async()=>{
  const {dom,w,get}=await app();
  try {
    get('close-detail').click();
    get('field').value='source_url';get('field').dispatchEvent(new w.Event('change'));await flush();
    assert.match(get('filters-caption').textContent,/Search: Publisher URL/);
    assert.equal(get('q').placeholder,'Search publisher url…');
    get('reset').click();await flush();
    assert.equal(get('field').value,'filename');assert.equal(get('reset').disabled,true);
    get('field').value='__advanced__';get('field').dispatchEvent(new w.Event('change'));
    get('close-field-picker').click();assert.equal(get('advanced-field').hidden,true);
    assert.equal(w.document.activeElement,get('field'));
  } finally {dom.window.close();}
});

test('accepted recovery is usable without erasing the original fetch outcome or URLs', async()=>{
  const recovered=structuredClone(entry);
  const recovery={original_url:final,recovered_url:'https://web.archive.org/web/20220101/https://committee.test/resolution.pdf',
    body_key:'bodies/sha256/recovered.gz',kind:'html',recovery_status:'recovered',recovery_basis:'user_accepted_url_variant'};
  Object.assign(recovered.record,{body_key:null,state_outcome:['http_404'],recovery});
  recovered.recovery=recovery;recovered.origin.recovered_urls=[recovery.recovered_url];recovered.published_only=true;recovered.saved_file_available=false;
  const before=JSON.stringify(recovered.record);
  const {dom,get}=await app(async()=>({ok:true,json:async()=>recovered}));
  try {
    assert.match(get('document-summary').textContent,/Saved responseRecovered/);
    assert.match(get('document-summary').textContent,/Recovered formatHTML/);
    assert.match(get('document-summary').textContent,/Original URL fetchHTTP 404/);
    assert.doesNotMatch(get('document-summary').textContent,/review required|candidate/i);
    assert.equal(get('source-link').href,final);
    assert.equal(get('origin').querySelector('.recovery-source a').href,recovery.recovered_url);
    assert.doesNotMatch(get('origin').textContent,/Recovered URL candidate/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/user_accepted_url_variant/);
    assert.doesNotMatch(get('filename-findings').textContent,/recovered.gz|user_accepted/);
    assert.equal(JSON.stringify(recovered.record),before);
  } finally {dom.window.close();}
});

test('long article identifiers are not confidently presented as legislative measures', async()=>{
  const article=structuredClone(entry);
  Object.assign(article.record,{filename:'S169726001730039X',measure_references:['s169726001730039'],measure_number:['169726001730039'],measure_token:['s'],measure_token_label:['Senate Bill']});
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?article:evidence}));
  try {
    const findings=get('filename-findings').querySelector('dl').textContent;
    assert.match(findings,/s169726001730039 · Needs review/);
    assert.match(findings,/publisher identifier/);
    assert.doesNotMatch(findings,/Senate bill/i);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/measure_references.*s169726001730039/s);
  } finally {dom.window.close();}
});


test('a filename with only raw fragments has one compact disclosure and retains every source field', async()=>{
  const sparse=structuredClone(entry);
  Object.assign(sparse.record,{date_token_candidates:null,subject_token:['resolution'],document_kind:['resolution'],document_kind_source:['filename']});
  sparse.document=sparse.record;sparse.published_only=true;sparse.reading=null;sparse.saved_file_available=false;
  const before=JSON.stringify(sparse.record);
  const {dom,get}=await app(async()=>({ok:true,json:async()=>sparse}));
  try {
    const section=get('filename-findings');
    assert.equal(section.querySelector('h3'),null);
    assert.equal(section.querySelectorAll('details').length,1);
    assert.equal(section.querySelector('details').open,false);
    assert.equal(section.querySelector('summary').textContent,'Filename analysis');
    assert.doesNotMatch(section.textContent,/No additional|Raw filename fragments/);
    get('technical').open=true;get('technical').dispatchEvent(new dom.window.Event('toggle'));await flush();
    assert.match(get('detail-data').textContent,/subject_token.*resolution/s);
    assert.equal(get('source-link').firstElementChild.textContent,'Open original URL ↗');
    assert.equal(JSON.stringify(sparse.record),before);
  } finally {dom.window.close();}
});

test('published details defer technical reads, page observations, and copy complete metadata explicitly', async()=>{
  const initial=structuredClone(entry);
  initial.record_complete=false;initial.published_only=true;initial.reading=null;initial.saved_file_available=false;
  initial.observation_count=42;initial.origin_next=20;initial.saved_file_url='https://data.test/saved/hash/copy.pdf';
  delete initial.record.source_occurrences;delete initial.record.name_token;
  const all=Array.from({length:42},(_,i)=>({source_occurrence_scope:['anchor'],source_receipt_line:[String(i+1)],source_page_title:['Observation '+i]}));
  const full={...record,source_occurrences:all};
  const {dom,w,get,requests}=await app(async url=>{
    const route=new URL(url,'https://viewer.test');let value;
    if(route.pathname.startsWith('/api/entry/'))value=initial;
    else if(route.pathname.startsWith('/api/technical/')){value={...full};delete value.source_occurrences;}
    else if(route.pathname.startsWith('/api/observations/')){const offset=Number(route.searchParams.get('offset'));value={items:all.slice(offset,offset+20),offset,total:42,next:offset+20<42?offset+20:null,is_null:false};}
    else if(route.pathname.startsWith('/api/origin/'))value={origin:{pages:[{urls:['https://committee.test/hearing'],titles:['A recorded hearing'],link_urls:[final],link_labels:[],relationship:'Linked from'}],redirects:[]},next:null};
    else if(route.pathname.startsWith('/api/full/'))value=full;
    else throw Error('Unexpected request '+url);
    return {ok:true,json:async()=>structuredClone(value)};
  });
  try {
    assert.equal(get('technical').open,false);assert.equal(get('detail-data').childElementCount,0);
    assert(!requests.some(url=>/\/api\/(technical|observations|full)\//.test(url)));
    assert.equal(get('saved-link').hidden,false);
    const more=[...get('origin').querySelectorAll('button')].find(button=>button.textContent==='More source pages');
    more.click();await flush();assert.match(get('origin').textContent,/A recorded hearing/);
    assert(![...get('origin').querySelectorAll('button')].some(button=>button.textContent==='More source pages'));
    get('technical').open=true;await flush();await flush();
    assert.equal(requests.filter(url=>url.startsWith('/api/technical/')).length,1);
    assert.equal(get('detail-data').querySelectorAll('details').length,20);
    assert.match(get('detail-data').textContent,/1–20 of 42 observations/);
    assert.doesNotMatch(get('detail-data').textContent,/Observation 0/,'closed observations do not build their contents');
    const first=get('detail-data').querySelector('details');first.open=true;first.dispatchEvent(new w.Event('toggle'));await flush();
    assert.match(first.textContent,/Observation 0/);
    [...get('detail-data').querySelectorAll('button')].find(button=>button.textContent==='Next observations').click();await flush();
    assert.equal(get('detail-data').querySelectorAll('details').length,20);
    assert.match(get('detail-data').textContent,/21–40 of 42 observations/);
    assert.equal(w.document.activeElement.dataset.field,'source_occurrences');
    let copied;
    Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>{copied=text;}}});
    get('copy').click();await flush();
    assert.equal(JSON.parse(copied).source_occurrences.length,42);
    assert.equal(requests.filter(url=>url.startsWith('/api/full/')).length,1);
  } finally {dom.window.close();}
});

test('failed technical evidence can retry without discarding the useful detail', async()=>{
  const initial={...structuredClone(entry),record_complete:false,published_only:true,saved_file_available:false,reading:null};
  let attempts=0;
  const {dom,w,get}=await app(async url=>{
    if(url.startsWith('/api/technical/')){if(++attempts===1)throw Error('Temporary evidence failure');return {ok:true,json:async()=>record};}
    if(url.startsWith('/api/observations/'))return {ok:true,json:async()=>({items:[],total:0,offset:0,next:null,is_null:true})};
    return {ok:true,json:async()=>initial};
  });
  try {
    get('technical').open=true;await flush();await flush();
    assert.match(get('detail-data').textContent,/Temporary evidence failure/);
    assert.equal(get('source-link').href,final);
    get('detail-data').querySelector('button').click();await flush();
    assert.equal(attempts,2);assert.match(get('detail-data').textContent,/resolution_by_cmw/);
  } finally {dom.window.close();}
});

test('long flat evidence lists also render one page without dropping values', async()=>{
  const current=structuredClone(entry);current.record.source_page_url=Array.from({length:45},(_,i)=>`https://committee.test/page/${i}`);
  const {dom,w,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?current:evidence}));
  try {
    get('technical').open=true;await flush();
    const field=[...get('detail-data').querySelectorAll('.entry')].find(el=>el.querySelector('.raw-key')?.textContent==='source_page_url');
    assert.equal(field.querySelectorAll('a').length,20);
    assert.match(field.textContent,/1–20 of 45 values/);
    [...field.querySelectorAll('button')].find(button=>button.textContent==='Next values').click();
    assert.equal(field.querySelectorAll('a').length,20);assert.match(field.textContent,/21–40 of 45 values/);
    assert.equal(w.document.activeElement.dataset.field,'source_page_url');
    [...field.querySelectorAll('button')].find(button=>button.textContent==='Next values').click();
    assert.equal(field.querySelectorAll('a').length,5);assert.match(field.textContent,/41–45 of 45 values/);
    assert.equal(current.record.source_page_url.length,45);
  } finally {dom.window.close();}
});

test('multiple classifications and committees remain inspectable without reading as a single finding', async()=>{
  const mixed=structuredClone(entry);
  Object.assign(mixed.record,{document_kind:['member-statement','witness-statement'],document_kind_source:['source_document_type'],
    source_document_type:['member statement','other','witness statement'],source_document_type_basis:['senate_parser_inference'],
    source_committee_name:['Senate Finance','Senate Finance Subcommittee on Health Care']});
  mixed.document=mixed.record;mixed.published_only=true;mixed.reading=null;
  const before=JSON.stringify(mixed.record);
  const {dom,get}=await app(async()=>({ok:true,json:async()=>mixed}));
  try {
    const facts=get('document-summary');
    assert.match(facts.textContent,/Multiple recorded kinds/);
    assert.doesNotMatch(facts.textContent,/Source-page kind/);
    const disclosures=[...facts.querySelectorAll('details')];
    assert.equal(disclosures.length,2);assert(disclosures.every(item=>!item.open));
    assert.match(disclosures[0].textContent,/Member statement.*Witness statement.*Inferred source-page readings/s);
    assert.match(disclosures[1].textContent,/2 recorded committees.*Senate Finance Subcommittee on Health Care/s);
    assert.equal(JSON.stringify(mixed.record),before);
  } finally {dom.window.close();}
});

test('saved errors and recovered copies have distinct actions while retaining recovery evidence', async()=>{
  const failed=structuredClone(entry);
  Object.assign(failed,{published_only:true,reading:null,saved_file_available:false,saved_file_url:'https://data.test/saved/hash/response.html'});
  failed.record.record_role=['error-response'];
  const errorApp=await app(async()=>({ok:true,json:async()=>failed}));
  try {
    assert.match(errorApp.get('saved-link').textContent,/Open saved response.*Failed response.*R2 archive/);
    assert.doesNotMatch(errorApp.get('saved-link').textContent,/Open saved copy/);
  } finally {errorApp.dom.window.close();}
  const recovered=structuredClone(failed),original='https://committee.test/RESOLUTION.pdf';
  recovered.record.recovery={recovery_status:'recovered',original_url:original,recovered_url:final,kind:'pdf'};
  const recoveredApp=await app(async()=>({ok:true,json:async()=>recovered}));
  try {
    const {get}=recoveredApp;
    assert.match(get('saved-link').textContent,/Open saved copy.*Recovered copy.*R2 archive/);
    assert.doesNotMatch(get('saved-link').textContent,/Failed response/);
    assert.match(get('origin').querySelector('.recovery-source').textContent,/Saved copy recovered from/);
    const oldLink=get('origin').querySelector(`a[href="${original}"]`);
    assert(oldLink.closest('details'));assert.equal(oldLink.closest('details').open,false);
    assert.equal(get('origin').querySelectorAll(`a[href="${original}"]`).length,1);
    assert.match(get('origin').textContent,/Referring page not recorded/);
  } finally {recoveredApp.dom.window.close();}
});

test('source-page dates stay with their observed page and ambiguous dates are not selected', async()=>{
  const dated=structuredClone(entry);
  dated.origin.pages=[{urls:['https://committee.test/hearing'],titles:[],link_labels:[],link_urls:[final],relationship:'Linked from',dates:['2024-02-06']},
    {urls:['https://committee.test/one','https://committee.test/two'],titles:[],link_labels:[],link_urls:[final],relationship:'Recorded source page',dates:['2023-01-01']}];
  const {dom,get}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/entry/')?dated:evidence}));
  try {
    assert.match(get('origin').textContent,/Recorded date: February 6, 2024/);
    assert.doesNotMatch(get('origin').textContent,/January 1, 2023/);
  } finally {dom.window.close();}
});

test('video details distinguish the recording from its saved webpage and retain provenance', async()=>{
  const video=structuredClone(entry),url='https://youtu.be/-oNSVIeynzI';
  Object.assign(video,{published_only:true,reading:null,saved_file_available:false,saved_file_url:'https://data.test/saved/hash/page',
    video_reference:{provider:'YouTube',id:'-oNSVIeynzI'}});
  Object.assign(video.record,{source_url:url,filename:'-oNSVIeynzI',format:['html'],body_format:['html'],document_kind:['opening-statement']});
  video.document=video.record;video.filename=video.record.filename;
  video.origin={file_url:url,redirects:[],recovered_urls:[],pages:[{urls:['https://smallbusiness.house.gov/calendar/eventsingle.aspx?EventID=398957'],
    titles:[],link_labels:['Opening Statement (As Prepared for Delivery)'],link_urls:[url],relationship:'Linked from'}]};
  const {dom,get}=await app(async()=>({ok:true,json:async()=>video}));
  try {
    assert.equal(get('source-link').firstElementChild.textContent,'Watch video ↗');
    assert.equal(get('source-link').href,url);
    assert.match(get('saved-link').textContent,/Open saved webpage.*Webpage only.*R2 archive/);
    assert.match(get('detail-title').textContent,/YouTube video/);
    assert.match(get('document-summary').textContent,/Saved format/);
    assert.doesNotMatch(get('document-summary').textContent,/Document kind|Opening statement/);
    assert.equal(get('filename-findings').hidden,true);
    assert.match(get('origin').textContent,/smallbusiness.house.gov/);
    assert.equal(video.record.document_kind[0],'opening-statement','published evidence remains unchanged');
  } finally {dom.window.close();}
});

test('a recovered HTML response is labeled as a webpage despite the original PDF filename', async()=>{
  const recovered=structuredClone(entry);
  Object.assign(recovered,{published_only:true,reading:null,saved_file_available:false,saved_file_url:'https://data.test/saved/hash/page'});
  recovered.record.recovery={recovery_status:'recovered',original_url:original,recovered_url:final,kind:'html'};
  const {dom,get}=await app(async()=>({ok:true,json:async()=>recovered}));
  try {assert.match(get('saved-link').textContent,/Open saved webpage.*Recovered copy.*R2 archive/);}
  finally {dom.window.close();}
});

test('saved link renders before provenance, then source labels update without reopening', async () => {
  let finishOrigin;
  const pending = new Promise(resolve => { finishOrigin = resolve; });
  const deferred = {...entry, origin_pending: true, origin: {...origin, redirects: []}, document_origin: {redirects: []}};
  const {dom, get} = await app(url => url.startsWith('/api/entry-origin/') ? pending
    : Promise.resolve({ok:true, json:async()=>url.startsWith('/api/entry/') ? deferred : evidence}));
  try {
    assert.equal(get('saved-link').hidden, false);
    assert.equal(get('detail-title').textContent, record.filename);
    assert.equal(get('detail').getAttribute('aria-busy'), 'false');
    assert.match(get('origin').textContent, /Loading source pages/);
    assert.doesNotMatch(get('origin').textContent, /not recorded/);
    get('source-variants').querySelectorAll('button')[1].focus();
    finishOrigin({ok:true, json:async()=>({origin_pending:false, origin, document_origin:origin, observation_count:1, origin_next:null})});
    await flush(); await flush();
    assert.doesNotMatch(get('origin').textContent, /Loading source pages/);
    assert.match(get('source-variants').textContent, /Original URL/);
    assert.match(get('source-variants').textContent, /Redirect destination/);
    assert.equal(dom.window.document.activeElement.dataset.source, 'stable-original');
    assert.equal(get('saved-link').hidden, false);
  } finally {dom.window.close();}
});

test('provenance failure preserves the saved link and supports retry', async () => {
  let attempts = 0;
  const deferred = {...entry, origin_pending:true};
  const {dom, get} = await app(url => {
    if (url.startsWith('/api/entry-origin/')) {
      if (!attempts++) return {ok:false, json:async()=>({error:'Temporary failure'})};
      return {ok:true, json:async()=>({origin_pending:false, origin, document_origin:origin, observation_count:1, origin_next:null})};
    }
    return {ok:true, json:async()=>url.startsWith('/api/entry/') ? deferred : evidence};
  });
  try {
    assert.equal(get('saved-link').hidden, false);
    assert.match(get('origin').textContent, /could not be loaded/);
    get('origin').querySelector('button').click(); await flush(); await flush();
    assert.equal(attempts,2);
    assert.doesNotMatch(get('origin').textContent, /could not be loaded/);
    assert.equal(get('saved-link').hidden, false);
  } finally {dom.window.close();}
});

test('late provenance cannot overwrite another selected source', async () => {
  let finishOrigin;
  const pending = new Promise(resolve => {finishOrigin=resolve;});
  const {dom, get} = await app(url => {
    if (url.startsWith('/api/entry-origin/')) return pending;
    const selected=url.includes('stable-original') ? {...entry, record:{...record,source_id:'stable-original'}, origin:{...origin,pages:[]}} : {...entry,origin_pending:true};
    return {ok:true,json:async()=>url.startsWith('/api/entry/') ? selected : evidence};
  });
  try {
    get('source-variants').querySelectorAll('button')[1].click();await flush();
    assert.equal(get('detail').dataset.row,'stable-original');
    finishOrigin({ok:true,json:async()=>({origin_pending:false,origin:{...origin,pages:[{urls:['https://wrong.test/'],titles:['Stale page'],link_labels:[],link_urls:[],relationship:'Linked from'}]},document_origin:origin})});
    await flush();await flush();
    assert.doesNotMatch(get('origin').textContent,/Stale page|wrong.test/);
    assert.equal(get('detail').dataset.row,'stable-original');
  } finally {dom.window.close();}
});

for(const status of ['candidate_applied','annotation_only_unsupported_forms']) {
 test('complete review shows whole packet and withdraws explicitly: '+status,async()=>{
  const review={status,baseline:{document_kind:['amendment']},selected:{document_kind:status==='candidate_applied'?['letter']:['amendment']},
   review:{primary_forms:['letter'],component_forms:status==='candidate_applied'?[]:['tax-return'],body_observation:{pages:2,
    notes:'Literal <script>unsafe()</script>',observations:['Filename differs from body'],
    source_completeness_observations:[{pdf_pages:[2],observation:'Original filing incomplete'}],
    page_sections:[{first_page:1,last_page:2,observed_form:'letter',description:'Retained pages'}]}}};
  const {dom,w,get,requests}=await app(async url=>({ok:true,json:async()=>url.startsWith('/api/review/')?
   (url.includes('selection=baseline')?{...review,status:'withdrawn',selected:review.baseline}:review):url.startsWith('/api/entry/')?entry:evidence}),{complete_body_reviews:true});
  try {
   const panel=get('complete-body-review');
   assert.match(panel.textContent,/Original categoryAmendment/);
   assert.match(panel.textContent,/Original filing incomplete/);
   assert.match(panel.textContent,/Pages 1–2: Letter/);
   assert.equal(panel.querySelector('script'),null);
   assert.equal([...panel.querySelectorAll('a')].find(a=>a.textContent==='Download the exact reviewed PDF').getAttribute('target'),null);
   assert.ok([...panel.querySelectorAll('a')].some(a=>a.href.endsWith('kind=page&page=2')));
   if(status==='annotation_only_unsupported_forms')assert.match(panel.textContent,/outside the supported categories/);
   panel.querySelector('button').click();await flush();await flush();
   assert.match(panel.textContent,/Review withdrawn/);
   assert.match(panel.textContent,/Preview categoryAmendment/);
   assert.ok(requests.some(url=>url.includes('selection=baseline')));
   panel.querySelector('button').click();await flush();await flush();
   assert.doesNotMatch(panel.textContent,/Review withdrawn/);
   assert.match(panel.textContent,/search and downloads use the original catalog/);
  } finally {dom.window.close();}
 });
}

test('failed verification is visible and is distinct from no review',async()=>{
 for(const failed of [true,false]) {
  const {dom,get}=await app(async url=>url.startsWith('/api/review/')?
   {ok:!failed,json:async()=>failed?{error:'Catalog or review snapshot changed.'}:{status:'no_review'}}:
   {ok:true,json:async()=>url.startsWith('/api/entry/')?entry:evidence},{complete_body_reviews:true});
  try {
   assert.match(get('complete-body-review').textContent,failed?/Review unavailable.*snapshot changed/:/No complete-body review/);
   assert.equal(get('complete-body-review').querySelector('a'),null);
   assert.equal(get('complete-body-review').querySelector('button'),null);
  } finally {dom.window.close();}
 }
});

test('ordinary published viewer does not request optional reviews',async()=>{
 const {dom,get,requests}=await app();
 try {
  assert.equal(get('complete-body-review').hidden,true);
  assert.equal(requests.some(url=>url.startsWith('/api/review/')),false);
 } finally {dom.window.close();}
});

test('late complete-review response cannot replace another selected source',async()=>{
 let resolveReview;
 const delayed=new Promise(resolve=>{resolveReview=resolve;});
 const other=structuredClone(entry);other.record.source_id='stable-original';
 const {dom,get}=await app(async url=>({ok:true,json:async()=>
  url.startsWith('/api/review/stable-final')?delayed:
  url.startsWith('/api/review/')?{status:'no_review'}:
  url.startsWith('/api/entry/stable-original')?other:
  url.startsWith('/api/entry/')?entry:evidence}),{complete_body_reviews:true});
 try {
  get('source-variants').querySelector('[data-source="stable-original"]').click();await flush();await flush();
  assert.match(get('complete-body-review').textContent,/No complete-body review/);
  resolveReview({status:'candidate_applied'});await flush();await flush();
  assert.match(get('complete-body-review').textContent,/No complete-body review/);
  assert.doesNotMatch(get('complete-body-review').textContent,/Review unavailable/);
 } finally {dom.window.close();}
});
