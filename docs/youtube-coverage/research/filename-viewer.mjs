const $ = id => document.getElementById(id);
const number = n => new Intl.NumberFormat().format(n);
const keys = ['q','field','congress','document_family','document_kind','format','retained','scope'];
const pretty = value => value.replaceAll('-', ' ').replace(/^./, x => x.toUpperCase());
const formatLabel = value => value.includes('/') ? value : value.toUpperCase();
const display = value => value && typeof value === 'object' ? (Array.isArray(value) ? value.map(display).join(' · ') : JSON.stringify(value)) : (value ?? '—');
const savedLabel = row => !row.retained ? 'No saved response' : row.record_role?.includes('error-response') ? 'Saved failed response' : 'Saved';
let info, page = 1, pages = 1, rowData, searchController, detailController, detailOpener, timer, searchField = 'filename';
const fieldLabels = {body_key:'Saved file location',filename:'Filename',source_url:'Publisher URL',filename_origins:'Filename obtained from',media_type:'Server-reported type',http_status:'HTTP response',response_usable:'Recorded usability assessment',response_body_complete:'Complete response saved',response_format:'Response format check',response_result:'Response diagnostic',capture_outcome:'Capture result',body_format:'Detected file format',format:'File format',extension:'Filename extension',name_token:'Remaining filename text',date_token:'Date text in filename',date_token_candidates:'Possible filename dates',document_kind:'Document classification',document_family:'Classification family',document_kind_source:'Classification evidence',source_capture_file:'Capture run',source_capture_pointer:'Path within captured record',source_receipt_key:'Receipt file',source_receipt_line:'Receipt line (one-based)',source_occurrences:'Related source observations',source_occurrence_scope:'Observation type',source_id:'Source record ID',document_id:'Grouped document ID',source_associated_url:'Associated original URL',source_association_basis:'URL relationship evidence',source_original_page_url:'Original referring page',source_page_url:'Recorded source page',source_page_title:'Source page title',source_link_label:'Publisher link text',source_link_url:'Recorded link URL',source_capture_url:'Capture request URL',source_chamber:'Chamber from source',source_congress:'Congress from source',source_committee_name:'Committee from source',congress:'Congress from filename',content_document_kind:'Document kind from PDF',content_congress:'Congress from PDF',content_citation:'Publication citation'};
const label = key => fieldLabels[key] || key.replaceAll('_',' ').replace(/^./, x=>x.toUpperCase());
const present = value => value!==null && value!==undefined && value!=='' && (!Array.isArray(value)||value.length>0);
const friendly = value => String(value).replaceAll('_',' ').replaceAll('-',' ').replace(/^./, x=>x.toUpperCase()).replace(/\bUrl\b/g,'URL');
const filenameDate = value => { const date=new Date(value+'T00:00:00Z'); return /^\d{4}-\d{2}-\d{2}$/.test(value)&&!Number.isNaN(date.valueOf()) ? new Intl.DateTimeFormat(undefined,{dateStyle:'long',timeZone:'UTC'}).format(date) : value; };
const dateLabel = value => { const date=new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long'}).format(date); };
function node(tag, text, className) { const el=document.createElement(tag); if(text !== undefined) el.textContent=text; if(className) el.className=className; return el; }
function sourceUrl(value) { try { const url=new URL(value); return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password ? url : null; } catch { return null; } }
async function api(url, signal) { if(window.filenameViewerApi) return window.filenameViewerApi(url,signal); const res=await fetch(url,{signal}); const data=await res.json(); if(!res.ok) throw new Error(data.error || 'Could not read the catalog.'); return data; }
function currentQuery() { const p=new URLSearchParams(); for(const key of keys) if($(key).value && !(key==='field' && $(key).value==='filename')) p.set(key,$(key).value); if(page>1) p.set('page',page); return p; }
function saveUrl(mode='replaceState') { const p=currentQuery(); if($('detail').open && $('detail').dataset.row) { p.set('source',$('detail').dataset.row); p.set('catalog',$('detail').dataset.catalog || info.catalog_id); } history[mode](null,'',`${location.pathname}${p.size?'?'+p:''}`); }
const secondaryKeys = ['congress','document_family','document_kind','format'];
const commonFields = ['filename','source_url','source_page_url','source_link_label','document_kind','congress','source_congress','content_congress'];
function selectField(value) {
 if(!info.fields.includes(value)) value='filename';
 if(![...$('field').options].some(option=>option.value===value)) { const option=node('option',label(value)); option.value=value; $('field').insertBefore(option,$('field').lastElementChild); }
 $('field').value=searchField=value; $('q').placeholder=`Search ${label(value).toLowerCase()}…`;
}
function filterNotes() {
 const active=secondaryKeys.filter(key=>$(key).value).length;
 $('filters-caption').textContent=active?`More filters · ${active} active`:'More filters';
 $('scope-note').hidden=$('retained').value!=='no';
 $('scope-note').textContent='Only groups with no saved response on any URL.'+($('scope').value===''?' Choose All records to include source/API references.':'');
}
function renderFieldPicker() {
 const query=$('field-picker-search').value.toLowerCase();
 const fields=info.fields.filter(key=>(label(key)+' '+key).toLowerCase().includes(query));
 $('field-options').replaceChildren(...fields.map(key=>{const button=node('button',label(key));button.type='button';button.append(node('small',key));button.addEventListener('click',()=>{selectField(key);$('advanced-field').hidden=true;changed();$('q').focus();});return button;}));
 if(!fields.length) $('field-options').append(node('p','No fields match.'));
}
function restore() {
 const p=new URLSearchParams(location.search); selectField(p.get('field')||'filename');
 for(const key of keys.filter(key=>key!=='field')) $(key).value=p.get(key)||(key==='format'?p.get('extension'):'')||'';
 page=Math.max(1,Number(p.get('page'))||1); filterNotes();
 return p.has('source')||p.has('row')?{id:p.get('source')||p.get('row'),catalog:p.get('catalog')}:null;
}
function reset() { clearTimeout(timer); for(const key of keys.filter(key=>key!=='field')) $(key).value=''; selectField('filename'); $('advanced-field').hidden=true; $('secondary-filters').open=false; changed(); }
function changed(mode='pushState') { clearTimeout(timer); page=1; filterNotes(); closeDetail(false); saveUrl(mode); load(); }
function congressIssue(values, source=[]) {
 source=source||[];
 const items=[...new Set(values||[])], maxCongress=Math.floor((new Date().getFullYear()-1789)/2)+1;
 const anomalous=items.filter(value=>!/^\d+$/.test(value)||Number(value)<1||Number(value)>maxCongress+1);
 const notes=[];
 if(anomalous.length) notes.push('Outside the historical/current range: '+anomalous.join(', ')+'.');
 if(items.length>1) notes.push('Competing filename readings; no Congress has been selected.');
 if(items.length&&source.length&&!items.some(value=>source.includes(value))) notes.push('Source context instead records Congress '+source.join(' · ')+'.');
 return notes.join(' ');
}
function measureLabel(value) {
 const match=/^(hconres|sconres|hjres|sjres|hres|sres|hr|s)(\d+)$/i.exec(value);
 if(!match) return value;
 const names={hr:['H.R.','House bill'],s:['S.','Senate bill'],hres:['H.Res.','House resolution'],sres:['S.Res.','Senate resolution'],hjres:['H.J.Res.','House joint resolution'],sjres:['S.J.Res.','Senate joint resolution'],hconres:['H.Con.Res.','House concurrent resolution'],sconres:['S.Con.Res.','Senate concurrent resolution']};
 const [prefix,name]=names[match[1].toLowerCase()]; return `${prefix} ${match[2]} — ${name}`;
}
function identity(row) { return row.api_reference?.title || row.filename || '(No filename recorded)'; }
function renderRows(data) {
 const fragment=document.createDocumentFragment();
 for(const row of data.rows) {
  const tr=node('tr'), first=node('td'), button=node('button',identity(row),'filename');
  button.type='button'; button.addEventListener('click',()=>openDetail(row.source_id||row._row)); first.append(button);
  // Optional wrap points preserve common filename tokens before falling back to a long token.
  if(!row.api_reference) { button.replaceChildren(); String(identity(row)).split(/(?<=[_ -])/).forEach(part=>button.append(document.createTextNode(part),node('wbr'))); }
  const url=sourceUrl(row.source_url||row.recovered_source_url?.[0]);
  if(url) { const a=link(url.href,url.hostname+' ↗'); a.className='source'; a.title=url.href; first.append(a); if(!row.source_url) first.append(node('div','Recovered URL candidate','muted')); }
  if(!row.api_reference&&row.record_role?.[0]&&row.record_role[0]!=='document') first.append(node('div',pretty(row.record_role[0]),'muted'));
  if(row.source_count>1) first.append(node('div',`${row.source_count} source records`,'muted'));
  const formats=row.format?.map(formatLabel).join(' · ')||'Unknown';
  const format=node('td',formats);
  if(row.format?.length) format.append(node('div',row.body_format?.length?'saved contents':row.media_type?.length?'response type':'filename','muted'));
  const saved=node('td',savedLabel(row));
  if(row.http_status?.length) saved.append(node('div','HTTP '+row.http_status.join(' / '),'muted'));
  if(row.response_format?.some(value=>value.includes('missing')||value.includes('invalid'))) saved.append(node('div',row.response_format.join(' · '),'muted'));
  const kindText=row.api_reference?'Source/API reference':row.document_kind?.map(pretty).join(' · ')||'Unclassified';
  const kind=node('td',kindText);
  if($('document_family').value&&row.document_family?.length) kind.append(node('div','Family: '+row.document_family.map(pretty).join(' · '),'muted'));
  const congress=node('td',display(row.congress)), warning=congressIssue(row.congress,row.source_congress);
  if(warning) { congress.append(node('div','Needs review','warning')); congress.title=warning; }
  const mobile=node('div',undefined,'mobile-meta'); mobile.append(node('span',kindText+' · '+formats),node('span',savedLabel(row)));
  const extra=[row.congress?.length?'Filename Congress '+display(row.congress)+(warning?' · Needs review':''):null,row.committee_code?.length?'Committee '+display(row.committee_code):null,row.measure_references?.map(measureLabel).join(' · ')].filter(Boolean);
  if(extra.length) mobile.append(node('span',extra.join(' · '))); first.append(mobile);
  tr.append(first,format,kind,congress,node('td',display(row.committee_code)),node('td',row.measure_references?.map(measureLabel).join(' · ')||'—'),saved); fragment.append(tr);
 }
 $('rows').replaceChildren(fragment); $('empty').hidden=data.total!==0; page=data.page; pages=data.pages;
 $('result-count').textContent=data.total?`${number((page-1)*data.limit+1)}–${number(Math.min(page*data.limit,data.total))} of ${number(data.total)} ${data.total===1?'entry':'entries'}`:'0 matching entries';
 $('page-number').value=page; $('page-number').max=pages; $('page-status').textContent=`of ${number(pages)}`;
 $('previous').disabled=page<=1; $('next').disabled=page>=pages;
}
async function load() {
 searchController?.abort(); const controller=searchController=new AbortController(); $('results').setAttribute('aria-busy','true'); $('result-count').textContent='Searching…'; $('error').hidden=true; $('previous').disabled=$('next').disabled=true;
 try { const data=await api('/api/rows?'+currentQuery(),controller.signal); if(controller!==searchController) return; renderRows(data); saveUrl(); }
 catch(error) { if(error.name!=='AbortError') { $('error').textContent=error.message; $('error').hidden=false; $('result-count').textContent='Could not load rows. Change a filter or retry.'; $('rows').replaceChildren(); } }
 finally { if(controller===searchController) $('results').setAttribute('aria-busy','false'); }
}
function closeDetail(update=true) {
 detailController?.abort(); const wasOpen=$('detail').open; $('detail').close();
 delete $('detail').dataset.row; delete $('detail').dataset.catalog;
 if(wasOpen) (detailOpener?.isConnected&&detailOpener!==document.body?detailOpener:$('q')).focus();
 if(update) saveUrl();
}
async function openDetail(id, update=true, catalog=info.catalog_id) {
 if(!$('detail').open) detailOpener=document.activeElement;
 detailController?.abort(); const controller=detailController=new AbortController(); rowData=null; $('detail').dataset.row=String(id); $('detail').dataset.catalog=catalog || info.catalog_id; $('detail-title').textContent='Loading…'; $('detail-data').replaceChildren(); $('field-count').textContent=''; $('field-search').value=''; $('show-empty').checked=false; $('copy').disabled=true; $('share').disabled=true; $('source-link').hidden=true; $('saved-link').hidden=true; $('detail-selected').hidden=true; $('copy-status').textContent=''; $('share-status').textContent='';
 for(const section of ['document-summary','origin','filename-findings','saved-evidence','occurrences']) $(section).replaceChildren();
 $('technical').open=false; $('source-history').querySelector('details').open=false; $('detail').scrollTop=0;
 $('source-variants').replaceChildren(); $('source-variants').hidden=true;
 if(!$('detail').open) $('detail').showModal(); if(update) saveUrl('pushState');
 try { const entry=await api('/api/entry/'+encodeURIComponent(id)+'?catalog='+encodeURIComponent(catalog || info.catalog_id),controller.signal); if(controller!==detailController) return; const data=entry.record; rowData=data; $('detail').dataset.row=data.source_id; $('detail').dataset.catalog=entry.catalog_id; saveUrl(); $('detail-title').textContent=identity({...data,filename:entry.filename,api_reference:entry.api_reference}); $('copy').disabled=false; $('share').disabled=false;
 if(data.filename!==entry.filename) { $('detail-selected').hidden=false; $('detail-selected').textContent='Selected source filename: '+(data.filename || 'Not recorded'); }
 renderSummary(entry); renderOrigin(entry.origin,entry.api_reference); renderFilename(entry); renderOccurrences(data.source_occurrences || []);
 if(entry.sources.length>1) {
  $('source-variants').hidden=false;
  $('source-variants').append(node('p',entry.sources_share_saved_file?'These URLs share one saved file. Select a URL to inspect its source record.':'These URLs belong to this grouped entry. Select a source to inspect its own metadata.'));
  for(const source of entry.sources) {
   const redirects=entry.document_origin.redirects;
   const role=redirects.some(r=>r.original===source.source_url)?'Original URL':redirects.some(r=>r.final===source.source_url)?'Redirect destination':'Alternate source URL';
   const caption=[role,source.format?.map(formatLabel).join(' · ') || 'Unknown format',savedLabel(source)].join(' · ');
   const button=node('button',caption,'outline'); button.setAttribute('aria-pressed',String(source.source_id===data.source_id));
   button.append(node('span',source.source_url || source.filename,'source'));
   button.addEventListener('click',()=>openDetail(source.source_id)); $('source-variants').append(button);
  }
 }
 const url=sourceUrl(data.source_url); if(url) { $('source-link').href=url.href; $('source-link').textContent=entry.api_reference?'Open API record ↗':'Open publisher copy ↗'; $('source-link').hidden=false; }
 if(entry.saved_file_available) { $('saved-link').hidden=false; $('saved-link').textContent=data.body_format?.includes('pdf')?'Open saved PDF ↗':'Open saved file ↗'; $('saved-link').href='/saved/'+encodeURIComponent(data.source_id)+'?catalog='+encodeURIComponent(entry.catalog_id); }
 renderDetails(); loadEvidence(entry,controller); }
 catch(error) { if(error.name!=='AbortError') { $('detail-title').textContent='Record unavailable'; $('document-summary').append(node('p',error.message)); } }
}
function link(value, text) { const url=sourceUrl(value); if(!url) return node('span',value || 'Not recorded'); const a=node('a',text || url.href); a.href=url.href; a.target='_blank'; a.rel='noopener noreferrer'; return a; }
function fact(dl, title, value, note) { dl.append(node('dt',title)); const dd=node('dd'); dd.append(value instanceof Node ? value : node('span',String(value))); if(note) dd.append(node('span',note,'fact-note')); dl.append(dd); }
function section(id, title) { const el=$(id); el.replaceChildren(node('h3',title)); return el; }
function renderSummary(entry) {
 const el=section('document-summary','At a glance'), row=entry.document, source=entry.record, dl=node('dl',undefined,'facts');
 if(entry.api_reference) fact(dl,'Entry type','Source/API reference','Identified from the Congress.gov API URL. Published role: '+(source.record_role?.map(friendly).join(' · ')||'Not recorded')+'.');
 fact(dl,'Published kind',row.document_kind?.map(friendly).join(' · ')||'Unclassified',row.document_kind?.length?'Evidence: '+(row.document_kind_source?.map(friendly).join(' · ')||'Not recorded'):null);
 const formats=source.format?.map(formatLabel).join(' · ');
 fact(dl,'Format',formats||'Unknown',formats?(source.body_format?.length?'Detected from saved bytes.':source.media_type?.length?'Reported by the server.':'Inferred from filename.'):null);
 fact(dl,'Saved response',source.body_key?(entry.published_only?'Recorded in R2':'Available'):entry.sources.some(item=>item.retained)?'Available on another URL in this group':'None recorded',source.record_role?.includes('error-response')?'The saved response was marked as failed.':source.response_usable?.includes('false')?'The saved response was marked unusable.':null);
 const context=[source.source_committee_name?.join(' · '),!source.congress?.length&&source.source_congress?.length?'Congress '+source.source_congress.join(' · '):null].filter(Boolean);
 if(context.length) fact(dl,'Source context',context.join(' · '));
 if(source.congress?.length) {
  const warning=congressIssue(source.congress,source.source_congress),value=node('span','Filename: '+display(source.congress));
  if(source.source_congress?.length) value.append(node('span','Source: '+display(source.source_congress),'fact-note'));
  fact(dl,'Congress'+(warning?' · Review':''),value,congressIssue(source.congress)+(source.source_congress?.length&&!source.congress.some(value=>source.source_congress.includes(value))?' Filename and source values disagree.':''));if(warning)dl.lastElementChild.classList.add('warning');
 }
 el.append(dl);
 const content=node('div'); content.id='content-summary';
 content.hidden=!entry.saved_file_available; content.append(node('p','Checking saved contents…','section-note')); el.append(content);
 if(source.source_id!==row.source_id) el.append(node('p','Published kind describes the group; other facts describe the selected source URL.','section-note'));
}
function referenceRole(value) {
 const url=sourceUrl(value); if(!url) return 'Source reference';
 if(url.hostname==='api.congress.gov') return 'API record';
 if(/rss|feed/i.test(url.pathname)) return 'Feed';
 if(/\.xml(?:$|[?&])/i.test(url.pathname+url.search)) return 'XML source';
 if(/\.json$/i.test(url.pathname)) return 'JSON source';
 return 'Website page';
}
function renderOrigin(origin,apiReference) {
 const el=section('origin','Where this URL came from'), dl=node('dl',undefined,'facts');
 fact(dl,apiReference?'API endpoint':'Publisher URL',origin.file_url?link(origin.file_url):'No original URL recorded'); el.append(dl);
 const unique=new Map();
 for(const page of origin.pages) for(const url of page.urls) {
  if(!sourceUrl(url)) continue;
  if(!unique.has(url)) unique.set(url,{url,pages:[]}); unique.get(url).pages.push(page);
 }
 const humanGroups=new Map();
 for(const item of [...unique.values()].filter(item=>referenceRole(item.url)==='Website page')) {
  const parsed=sourceUrl(item.url),key=parsed.host+parsed.pathname+parsed.search+parsed.hash;
  if(!humanGroups.has(key)) humanGroups.set(key,[]);humanGroups.get(key).push(item);
 }
 const human=[...humanGroups.values()].map(items=>{
  const preferred=items.find(item=>sourceUrl(item.url).protocol==='https:')||items[0];
  return {...preferred,variants:items.filter(item=>item!==preferred)};
 });
 const machine=[...unique.values()].filter(item=>referenceRole(item.url)!=='Website page');
 const renderReference=item=>{
  const block=node('div',undefined,'provenance-item');
  const paired=[...new Set(item.pages.filter(page=>page.urls.length===1&&page.titles.length===1).map(page=>page.titles[0]))];
  const relationships=[...new Set(item.pages.map(page=>page.relationship))];
  block.append(node('p',referenceRole(item.url)+' · '+relationships.join(' / '),'link-caption'),link(item.url,paired.length===1?paired[0]:item.url));
  if(paired.length===1) block.append(node('p',item.url,'link-caption'));
  if(item.variants?.length) {const variants=node('details');variants.append(node('summary',`${item.variants.length+1} recorded URL forms`),node('p','Same page path recorded with different protocols; no redirect is assumed.','section-note'));for(const variant of item.variants)variants.append(link(variant.url));block.append(variants);}
  return block;
 };
 if(human.length) human.forEach(item=>el.append(renderReference(item)));
 else el.append(node('p',origin.pages.length?'No referring website page recorded. Machine-readable sources are listed below.':'Referring page not recorded for this source.','empty-state'));
 if(machine.length) { const details=node('details');details.append(node('summary',`${machine.length} API, feed or data references`)); machine.forEach(item=>details.append(renderReference(item))); el.append(details); }
 if(origin.pages.some(page=>page.titles.length||page.link_labels.length||page.link_urls.length)) {
  const details=node('details');details.append(node('summary','Recorded page and link associations'));
  for(const page of origin.pages) { const item=node('div',undefined,'provenance-item'); item.append(node('p',page.relationship,'link-caption')); for(const url of page.urls) item.append(link(url)); if(page.titles.length) item.append(node('p','Recorded page titles: '+page.titles.join(' · '))); if(page.link_labels.length) item.append(node('p','Link text: '+page.link_labels.join(' · '))); for(const url of page.link_urls) item.append(link(url)); details.append(item); }
  details.append(node('p','Titles and URLs remain grouped by their original observation; multiple values do not establish a one-to-one pairing.','section-note'));el.append(details);
 }
 if(origin.redirects.length) { const details=node('details');details.append(node('summary','Original URL and publisher redirect'));for(const redirect of origin.redirects) { const item=node('div',undefined,'provenance-item');item.append(node('p','Original URL','link-caption'),link(redirect.original),node('p','Redirected to','link-caption'),link(redirect.final));details.append(item); }el.append(details); }
 if(origin.recovered_urls.length) { const details=node('details');details.append(node('summary','Recovered URL candidates'),node('p','Recovery candidates; no referring-page relationship established.','section-note'));for(const url of origin.recovered_urls)details.append(link(url));el.append(details); }
}
const nonFilename = new Set(['body_key','filename','source_url','filename_origins','media_type','http_status','response_usable','response_body_complete','response_format','response_result','body_format','capture_outcome','record_role','source_id','document_id','format','cache_marker_state','recovered_filename','recovered_source_url','document_kind','document_kind_source','document_family']);
function filenameFields(record) { return Object.entries(record).filter(([key,value])=>present(value)&&!key.startsWith('source_')&&!key.startsWith('content_')&&!nonFilename.has(key)); }
function renderFilename(entry) {
 const el=section('filename-findings','From the filename'), row=entry.record, reading=entry.reading, dl=node('dl',undefined,'facts'), consumed=new Set(['extension']);
 el.append(node('p','Published filename interpretations. Document facts require separate evidence.','section-note'));
 consumed.add('congress');
 if(row.measure_references?.length) {
  fact(dl,'Measure',row.measure_references.map(measureLabel).join(' · ')); consumed.add('measure_references');
  const parsed=row.measure_references.map(value=>/^([a-z]+)(\d+)$/i.exec(value)).filter(Boolean),types=parsed.map(match=>match[1].toLowerCase()),numbers=parsed.map(match=>match[2]);
  if(row.measure_number?.every(value=>numbers.includes(value)))consumed.add('measure_number');
  for(const key of ['measure_token','measure_token_code','measure_type']) if(row[key]?.every(value=>types.includes(value.toLowerCase())))consumed.add(key);
  if(consumed.has('measure_token'))consumed.add('measure_token_label');
 }
 if(present(row.date_token)) { fact(dl,'Date',(row.date_token_candidates||row.date_token).map(filenameDate).join(' · '),'Original text: '+display(row.date_token)+'. Date role unknown; not an established meeting or publication date.');consumed.add('date_token');consumed.add('date_token_candidates'); }
 const fields=filenameFields(row);
 for(const [key,value] of fields) {
  if(consumed.has(key)||key.endsWith('_code')&&present(row[key.slice(0,-5)])||key.endsWith('_label')&&present(row[key.slice(0,-6)])) continue;
  const pairedLabel=row[key+'_label'], notes=reading?.observations.filter(f=>f.name===key&&f.note&&[].concat(value).includes(f.raw)).map(f=>f.note)||[];
  fact(dl,label(key),display(pairedLabel||value),key==='name_token'?'Fallback filename text; not a verified person, author, or identifier.':[...new Set(notes)].join(' '));
 }
 if(!dl.childElementCount) el.append(node('p','No descriptive facts extracted from this filename.','empty-state'));
 else el.append(dl);
 const support=node('details');support.append(node('summary',reading?'Filename origin and reader comparison':'Filename origin'));
 if(entry.published_only) support.append(node('p',`Published house-naming results · version ${info.house_naming_version}. This page reads the catalog snapshot; it does not rerun the naming rules.`,'section-note'));
 if(row.filename_origins?.length) support.append(node('p','Filename obtained from: '+row.filename_origins.map(friendly).join(' · ')));
 if(entry.api_reference) support.append(node('p','Literal URL-derived filename: '+row.filename));
 if(reading) {
  support.append(node('p',reading.recognized_convention?'A supported naming convention matched.':'No supported naming convention matched.'));
  const differences=[...new Set([...fields.map(([key])=>key),...Object.keys(reading.metadata)])].filter(key=>JSON.stringify(reading.metadata[key]||null)!==JSON.stringify(row[key]||null));
  if(differences.length) {
   const table=node('table',undefined,'comparison'),thead=node('thead'),head=node('tr');['Field','Published','Current reader'].forEach(text=>head.append(node('th',text)));thead.append(head);const tbody=node('tbody');
   differences.forEach(key=>{const tr=node('tr');tr.append(node('td',label(key)),node('td',display(row[key])),node('td',display(reading.metadata[key])));tbody.append(tr);});table.append(thead,tbody);support.append(table);
  } else support.append(node('p','Current reader matches the published filename values.','section-note'));
  support.append(node('p',`house-naming versions — published: ${info.house_naming_version}; current: ${reading.version}. Catalog: ${entry.catalog_id}. Build identifiers were not recorded. Equal version labels do not establish identical code or inputs.`,'section-note'));
  if(reading.diagnostics?.length) reading.diagnostics.forEach(text=>support.append(node('p',text,'review-note')));
 }
 el.append(support);
}
function renderOccurrences(occurrences) {
 const el=$('occurrences'); el.replaceChildren();
 occurrences.forEach((occurrence,index)=>{ const details=node('details'), scope=occurrence.source_occurrence_scope?.map(friendly).join(' · ') || 'Source observation'; details.append(node('summary',`${index+1}. ${scope}`)); const dl=node('dl',undefined,'facts'); for(const [key,value] of Object.entries(occurrence)) if(present(value)) { const values=node('span'); [].concat(value).forEach((v,i)=>{if(i)values.append(document.createElement('br'));values.append(webUrlOrText(v));}); fact(dl,label(key),values); } details.append(dl); el.append(details); });
 if(occurrences.length) el.prepend(node('p','Each observation keeps its own page, link, and receipt together. These are evidence records, not independent documents or download counts.','section-note'));
}
function webUrlOrText(value) { return sourceUrl(value)?link(value):node('span',typeof value==='object'?JSON.stringify(value):String(value)); }
async function loadEvidence(entry,controller) {
 const el=section('saved-evidence','Saved response evidence'), summary=$('content-summary');
 if(entry.published_only) {
  const content=Object.entries(entry.record).filter(([key,value])=>key.startsWith('content_')&&present(value));
  summary.hidden=!content.length;
  summary.replaceChildren(node('p','Saved contents · published findings','link-caption'));
  for(const [key,value] of content) summary.append(node('p',label(key)+': '+display(value)));
  el.hidden=!entry.record.body_key;
  if(entry.record.body_key) { el.append(node('p','The catalog records a saved response in R2. This static page does not fetch private archive files or recheck their contents.','section-note')); const dl=node('dl',undefined,'facts'); fact(dl,'R2 object',entry.record.body_key); el.append(dl); }
  return;
 }
 if(!entry.saved_file_available) { el.hidden=true; return; } el.hidden=false;
 el.append(node('p','Reading the saved file and checking its hash…','section-note'));
 try {
  const evidence=await api('/api/evidence/'+encodeURIComponent(entry.record.source_id)+'?catalog='+encodeURIComponent(entry.catalog_id),controller.signal); if(controller!==detailController) return;
  summary.replaceChildren(node('p','Saved contents · checked now','link-caption'));
  const content=evidence.content_fields||{}, kind=content.content_document_kind?.map(friendly).join(' · '), congress=content.content_congress?.join(' · ');
  summary.append(node('p',[kind,congress?'Congress '+congress:null].filter(Boolean).join(' · ')||'Opening pages: no supported classification. Review the PDF or text below.',kind||congress?'classification':'section-note'));
  for(const [key,value] of Object.entries(content)) if(!['content_document_kind','content_congress'].includes(key)) summary.append(node('p',label(key)+': '+display(value)));
  if(Object.keys(content).length)summary.append(node('p','Read from the saved file; published metadata is unchanged.','section-note'));
  el.replaceChildren(node('h3','Saved response evidence')); const dl=node('dl',undefined,'facts');
  fact(dl,'Integrity','Saved bytes verified',number(evidence.bytes)+' bytes'+(evidence.page_count?' · '+number(evidence.page_count)+' pages':''));
  if(evidence.receipt) { const receipt=evidence.receipt; fact(dl,'Captured',receipt.retrieved_at?dateLabel(receipt.retrieved_at):'Time not recorded','Download time, separate from the document’s date.'); fact(dl,'Response',receipt.http_status?'HTTP '+receipt.http_status:'Status not recorded',receipt.complete===true?'Complete response saved.':receipt.complete===false?'Incomplete response recorded.':'Completeness not recorded.'); }
  else fact(dl,'Capture details',evidence.receipt_error||'No matching receipt details available');
  el.append(dl);
  for(const page of evidence.pages||[]) {
   const details=node('details'),text=page.text.trim(),pre=node('pre',text||'No text extracted. Open the saved PDF to inspect this page.','pdf-text'),long=text.length>700||text.split('\n').length>12;
   details.append(node('summary','Opening text · page '+page.number),pre);
   if(long) {pre.classList.add('preview'); const button=node('button','Show full page text','quiet');button.type='button';button.setAttribute('aria-expanded','false');button.addEventListener('click',()=>{const expanded=pre.classList.toggle('preview')===false;button.textContent=expanded?'Collapse page text':'Show full page text';button.setAttribute('aria-expanded',String(expanded));});details.append(button);}
   el.append(details);
  }
 } catch(error) { if(error.name==='AbortError'||controller!==detailController)return; summary.replaceChildren(node('p','Saved contents could not be checked. See the access error below.','section-note')); el.replaceChildren(node('h3','Saved response evidence'),node('p',error.message,'empty-state'));const retry=node('button','Retry saved-file access','outline');retry.addEventListener('click',()=>loadEvidence(entry,controller));el.append(retry); }
}
function renderDetails() {
 if(!rowData) return;
 const q=$('field-search').value.toLowerCase(); const populated=Object.values(rowData).filter(v=>v!==null&&v!==''&&(!Array.isArray(v)||v.length)).length;
 const entries=Object.entries(rowData).filter(([key,value])=>($('show-empty').checked || present(value)) && (!q || label(key).toLowerCase().includes(q)||key.toLowerCase().includes(q)||String(display(value)).toLowerCase().includes(q)));
 $('field-count').textContent=`${populated} populated fields · ${Object.keys(rowData).length} total · ${entries.length} shown`;
 const dl=node('dl',undefined,'field-group'); for(const [key,value] of entries) { const entry=node('div',undefined,'entry'); const term=node('dt',label(key)); term.append(node('span',key,'raw-key')); entry.append(term); const dd=node('dd'); if(!present(value)) dd.append(node('span','Not recorded','muted')); else for(const item of Array.isArray(value)?value:[value]) { if(item && typeof item==='object') dd.append(node('pre',JSON.stringify(item,null,2),'pdf-text')); else { const line=node('div'); line.append(webUrlOrText(item)); dd.append(line); } } entry.append(dd); dl.append(entry); }
 $('detail-data').replaceChildren(entries.length?dl:node('p','No fields match this search.','muted'));
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();changed();});
$('q').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>changed('replaceState'),220);});
for(const key of keys.filter(k=>k!=='q'&&k!=='field')) $(key).addEventListener('change',()=>changed());
$('field').addEventListener('change',()=>{if($('field').value==='__advanced__') { $('field').value=searchField; $('advanced-field').hidden=false; renderFieldPicker(); $('field-picker-search').focus(); } else {selectField($('field').value);$('advanced-field').hidden=true;changed();}});
$('field-picker-search').addEventListener('input',renderFieldPicker);
$('reset').addEventListener('click',reset); $('empty-reset').addEventListener('click',reset);
function goToPage(value) {page=Math.max(1,Math.min(pages,Number(value)||1));saveUrl('pushState');load();$('results-bar').scrollIntoView({block:'start'});}
for(const [id,delta] of [['previous',-1],['next',1]]) $(id).addEventListener('click',()=>goToPage(page+delta));
$('page-form').addEventListener('submit',event=>{event.preventDefault();goToPage($('page-number').value);});
$('back-to-results').addEventListener('click',()=>$('results-bar').scrollIntoView({block:'start'}));
$('close-detail').addEventListener('click',()=>closeDetail());
$('detail').addEventListener('cancel',event=>{event.preventDefault();closeDetail();});
$('detail').addEventListener('click',event=>{if(event.target===$('detail') && event.clientX<$('detail').getBoundingClientRect().left) closeDetail();});
$('field-search').addEventListener('input',renderDetails); $('show-empty').addEventListener('change',renderDetails);
$('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(JSON.stringify(rowData,null,2));$('copy-status').textContent='Copied';}catch{$('copy-status').textContent='Clipboard unavailable';}});
$('share').addEventListener('click',async()=>{try{saveUrl();await navigator.clipboard.writeText(location.href);$('share-status').textContent='Copied';}catch{$('share-status').textContent='Clipboard unavailable';}});
window.addEventListener('popstate',()=>{const row=restore();load();if(row!==null)openDetail(row.id,false,row.catalog);else closeDetail(false);});
try {
 info=await api('/api/info');
 if(info.downloads) { document.querySelector('a[href="/data.parquet"]').href=info.downloads.documents; document.querySelector('a[href="/sources.parquet"]').href=info.downloads.filenames; }
 $('summary').textContent=`${number(info.documents)} documents · ${number(info.capture_records)} source/capture entries`;
 $('summary').title=`${number(info.rows)} source rows · ${number(info.api_reference_groups||0)} API-only groups identified by URL`;
 $('snapshot').textContent=info.remote_last_modified?'Snapshot '+new Date(info.remote_last_modified).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Snapshot date not recorded';
 $('snapshot-detail').textContent=info.remote_last_modified?'Published '+dateLabel(info.remote_last_modified)+(info.synced_at?' · Local copy synced '+dateLabel(info.synced_at):''):'';
 if(info.published_at) $('snapshot-detail').append(node('p','Viewer published '+dateLabel(info.published_at)+'. Downloads preserve every catalog value in browser-optimized Parquet files.'));
 $('snapshot-detail').append(node('p',number(info.rows)+' source rows · '+number(info.api_reference_groups||0)+' API-only groups identified by URL.'));
 const options=commonFields.filter(key=>info.fields.includes(key)).map(key=>{const option=node('option',label(key));option.value=key;return option;});
 const advanced=node('option','Find another field…');advanced.value='__advanced__';$('field').replaceChildren(...options,advanced);
 for(const key of secondaryKeys) { const values=[...info.facets[key]]; if(key==='congress') values.sort((a,b)=>Number(b)-Number(a));for(const value of values) {const text=key.startsWith('document_')?pretty(value):key==='format'?formatLabel(value):congressIssue([value])?value+' · Needs review':value;const option=node('option',text);option.value=value;$(key).append(option);} }
 const row=restore(); if(row!==null)openDetail(row.id,false,row.catalog);await load();
} catch(error) { $('error').textContent=error.message; $('error').hidden=false; $('summary').textContent='Catalog unavailable'; }
