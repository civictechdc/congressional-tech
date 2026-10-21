import { createViewerAdapter } from './filename-adapter.mjs';
import { fieldTextCache } from './filename-detail-state.mjs';
import { evidenceGraph, provenanceUrlKey, mergeOrigin } from './filename-provenance.mjs';
import { positiveInteger, filenameDate } from './filename-rules.mjs';
const $ = id => document.getElementById(id);
const number = n => new Intl.NumberFormat().format(n);
const keys = ['q','field','congress','document_family','document_kind','format','retained','scope','classification'];
const pretty = value => value.replaceAll('-', ' ').replace(/^./, x => x.toUpperCase());
const formatLabel = value => value.includes('/') ? value : value.toUpperCase();
const display = value => value && typeof value === 'object' ? (Array.isArray(value) ? value.map(display).join(' · ') : JSON.stringify(value)) : (value ?? '—');
const savedLabel = row => row.recovery?.recovery_status==='recovered' ? 'Recovered' : !row.retained ? 'No saved response' : row.record_role?.includes('error-response') ? 'Saved failed response' : row.response_usable?.includes('false') || row.response_body_complete?.includes('false') ? 'Saved · needs review' : 'Saved';
let detailEntry, technicalPromise, technicalReady = false, observationData;
const formattedFields = fieldTextCache();
let sourceOffset=0, sourcePageId=null;
let reviewPin = null;
let info, page = 1, pages = 1, rowData, searchController, detailController, detailOpener, timer, searchField = 'filename';
const fieldLabels = {body_key:'Saved file location',filename:'Filename',source_url:'Publisher URL',filename_origins:'Filename obtained from',media_type:'Server-reported type',http_status:'HTTP response',response_usable:'Recorded usability assessment',response_body_complete:'Complete response saved',response_format:'Response format check',response_result:'Response diagnostic',capture_outcome:'Capture result',body_format:'Detected file format',format:'File format',extension:'Filename extension',name_token:'Remaining filename text',date_token:'Date text in filename',date_token_candidates:'Possible filename dates',document_kind:'Document classification',document_family:'Classification family',document_kind_source:'Classification evidence',source_capture_file:'Capture run',source_capture_pointer:'Path within captured record',source_receipt_key:'Receipt file',source_receipt_line:'Receipt line (one-based)',source_occurrences:'Related source observations',source_occurrence_scope:'Observation type',source_id:'Source record ID',document_id:'Grouped document ID',source_associated_url:'Associated original URL',source_association_basis:'URL relationship evidence',source_original_page_url:'Original referring page',source_page_url:'Recorded source page',source_page_title:'Source page title',source_link_label:'Publisher link text',source_link_url:'Recorded link URL',source_capture_url:'Capture request URL',source_chamber:'Chamber from source',source_congress:'Congress from source',source_committee_name:'Committee from source',congress:'Congress from filename',content_document_kind:'Document kind from PDF',content_congress:'Congress from PDF',content_citation:'Publication citation'};
Object.assign(fieldLabels,{state_outcome:'Latest fetch result',state_family:'Capture source family',state_body_key:'Current saved response location',state_checked_at:'Last fetch check',state_retrieved_at:'Response retrieved at',hearing_package_id:'Related hearing package',hearing_resources:'Related hearing resources'});
Object.assign(fieldLabels,{subject_token:'Subject text',committee_code:'Committee code from filename',generic_identifier:'Unclassified identifier',short_date_token:'Unresolved short date',source_meeting_title:'Meeting title from source',source_meeting_date:'Meeting date from source',source_witness_name:'Witness name from source',source_witness_organization:'Witness organization from source',source_witness_position:'Witness position from source',source_document_label:'Document label from source',source_document_type:'Document type from source'});
Object.assign(fieldLabels,{content_document_kind:'Document kind from saved contents',content_congress:'Congress from saved contents'});
fieldLabels.recovery='Recovered copy';
const label = key => (fieldLabels[key] || key.replaceAll('_',' ').replace(/^./, x=>x.toUpperCase())).replace(/\b(url|id|uuid|http|pdf|xml|api)\b/gi,x=>x.toUpperCase());
const present = value => value!==null && value!==undefined && value!=='' && (!Array.isArray(value)||value.length>0);
const friendly = value => String(value).replaceAll('_',' ').replaceAll('-',' ').replace(/^./, x=>x.toUpperCase()).replace(/\b(url|http|pdf|xml|api)\b/gi,x=>x.toUpperCase());
const dateLabel = value => { const date=new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long'}).format(date); };
function node(tag, text, className) { const el=document.createElement(tag); if(text !== undefined) el.textContent=text; if(className) el.className=className; return el; }
function sourceUrl(value) { try { const url=new URL(value); return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password ? url : null; } catch { return null; } }
const adapter = createViewerAdapter({mode: document.body.dataset.filenameMode, workerApi: () => window.filenameViewerApi, fetcher: (...args) => fetch(...args)});
const api = adapter.request;
function currentQuery() { const p=new URLSearchParams(); for(const key of keys) if($(key).value && !(key==='field' && $(key).value==='filename')) p.set(key,$(key).value); if($('classification').value==='reviewed')p.set('review',reviewPin||info.review_sha256||'');if(page>1) p.set('page',page); return p; }
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
 const field=$('field').value==='filename'?'':`Search: ${label($('field').value)}`;
 $('filters-caption').textContent=['More filters',active?`${active} active`:null,field].filter(Boolean).join(' · ');
 $('reset').disabled=!keys.some(key=>$(key).value && !(key==='field' && $(key).value==='filename'));
 $('scope-note').hidden=$('retained').value!=='no';
 $('scope-note').textContent='Only groups with no saved response on any URL.'+($('scope').value===''?' Choose All records to include source/API references.':'');
 $('classification-control').hidden=!info.complete_body_reviews&&!$('classification').value;
 $('classification').querySelector('[value="reviewed"]').disabled=!info.reviewed_search;
 $('classification-note').textContent=$('classification').value==='reviewed'?
  `Using ${number(info.reviewed_groups||0)} assistant-reviewed groups; other categories remain original. Downloads preserve the original catalog.`:
  info.review_error?'Original catalog categories. Reviewed categories unavailable: '+info.review_error:
  'Original catalog categories. Choose reviewed categories to include verified review findings in search.';
}
function reviewModeProblem() {
 if($('classification').value!=='reviewed')return null;
 if(!info.reviewed_search)return info.review_error||'Reviewed-category search is unavailable in this viewer. Choose Original catalog.';
 if(reviewPin&&reviewPin!==info.review_sha256)return 'This search belongs to a different review snapshot. Choose the classification mode again.';
 return null;
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
 reviewPin=p.get('review')||info.review_sha256||null;
 page=positiveInteger(p.get('page')); filterNotes();
 $('secondary-filters').open=secondaryKeys.some(key=>$(key).value)||$('field').value!=='filename';
 return p.has('source')||p.has('row')?{id:p.get('source')||p.get('row'),catalog:p.get('catalog')}:null;
}
function reset() { clearTimeout(timer); reviewPin=null;for(const key of keys.filter(key=>key!=='field')) $(key).value=''; selectField('filename'); $('advanced-field').hidden=true; $('secondary-filters').open=false; changed(); }
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
 if(match[2].length>5)return value+' · Needs review';
 const names={hr:['H.R.','House bill'],s:['S.','Senate bill'],hres:['H.Res.','House resolution'],sres:['S.Res.','Senate resolution'],hjres:['H.J.Res.','House joint resolution'],sjres:['S.J.Res.','Senate joint resolution'],hconres:['H.Con.Res.','House concurrent resolution'],sconres:['S.Con.Res.','Senate concurrent resolution']};
 const [prefix,name]=names[match[1].toLowerCase()]; return `${prefix} ${match[2]} — ${name}`;
}
function identity(row) { return row.video_reference ? `${row.video_reference.provider} video · ${row.video_reference.id}` : row.api_reference?.title || row.filename || '(No filename recorded)'; }
function renderRows(data) {
 const fragment=document.createDocumentFragment();
 for(const row of data.rows) {
  const tr=node('tr'), first=node('td'), button=node('button',identity(row),'filename');
  button.type='button'; button.addEventListener('click',()=>openDetail(row.source_id||row._row)); first.append(button);
  // Optional wrap points preserve common filename tokens before falling back to a long token.
  if(!row.api_reference) { button.replaceChildren(); String(identity(row)).split(/(?<=[_ -])/).forEach(part=>button.append(document.createTextNode(part),node('wbr'))); }
  const url=sourceUrl(row.source_url||row.recovered_source_url?.[0]);
  const meta=node('div',undefined,'source-meta');
  if(url) { const a=link(url.href,url.hostname.replace(/^www\./,'')+' ↗'); a.className='source'; a.title=url.href; meta.append(a); if(!row.source_url) meta.append(node('span','Recovered URL candidate','muted')); }
  const role=row.record_role?.[0];
  if(!row.api_reference&&role&&role!=='document'&&!(role==='error-response'&&row.retained)) first.append(node('div',({'capture-state':'Fetch record','error-response':'Fetch failed'})[role]||pretty(role),'muted'));
  if(row.source_count>1) meta.append(node('span',`${number(row.source_count)} source records`,'muted'));
  first.append(meta);
  const formats=row.format?.map(formatLabel).join(' · ')||'Unknown';
  const format=node('td',formats);
  if(row.format?.length) format.title=row.body_format?.length?'Detected from saved contents':row.media_type?.length?'Reported by the server':'Inferred from filename';
  if(row.recovery?.kind&&!row.format?.includes(row.recovery.kind))format.append(node('div','Recovered: '+formatLabel(row.recovery.kind),'muted'));
  const saved=node('td',savedLabel(row));
  if(row.http_status?.some(value=>Number(value)>=400)) saved.append(node('div',(row.recovery?'Original HTTP ':'HTTP ')+row.http_status.join(' / '),'warning'));
  if(row.response_format?.some(value=>value.includes('missing')||value.includes('invalid'))) saved.append(node('div',row.response_format.join(' · '),'muted'));
  const kindText=row.video_reference?'Video reference':row.api_reference?'Source/API reference':row.document_kind?.map(pretty).join(' · ')||'Unclassified';
  const kind=node('td',kindText);
  const reviewLabel=row._review_status==='candidate_applied'?'Assistant-reviewed category':row._review_status==='annotation_only_unsupported_forms'?'Review notes; original category':'';
  if(reviewLabel)kind.append(node('div',reviewLabel,'muted'));
  if($('document_family').value&&row.document_family?.length) kind.append(node('div','Family: '+row.document_family.map(pretty).join(' · '),'muted'));
  const clues=node('td',undefined,'filename-clues'), warning=congressIssue(row.congress,row.source_congress);
  const mobile=node('div',undefined,'mobile-meta'); mobile.append(node('span',kindText+' · '+formats),node('span',savedLabel(row)));
  if(reviewLabel)mobile.append(node('span',reviewLabel));
  const extra=[row.congress?.length?'Filename Congress '+display(row.congress)+(warning?' · Needs review':''):null,row.committee_code?.length?'Committee '+display(row.committee_code):null,row.measure_references?.map(measureLabel).join(' · ')].filter(Boolean);
  if(extra.length) { mobile.append(node('span',extra.join(' · '),'mobile-clues')); for(const clue of extra) clues.append(node('div',clue)); } else clues.append(node('span','—','muted'));
  if(warning) { clues.classList.add('warning'); clues.title=warning; }
  first.append(mobile);
  tr.append(first,kind,format,clues,saved); fragment.append(tr);
 }
 $('rows').replaceChildren(fragment); $('empty').hidden=data.total!==0; page=data.page; pages=data.pages;
 $('result-count').textContent=data.total?`${number((page-1)*data.limit+1)}–${number(Math.min(page*data.limit,data.total))} of ${number(data.total)} ${data.total===1?'entry':'entries'}`:'0 matching entries';
 $('page-number').value=page; $('page-number').max=Math.max(1,pages); $('page-status').textContent=`of ${number(pages)}`;
 document.querySelector('.pager').hidden=!data.total;
 $('previous').disabled=page<=1; $('next').disabled=page>=pages;
}
async function load() {
 searchController?.abort(); const controller=searchController=new AbortController(); $('results').setAttribute('aria-busy','true'); $('results').inert=true; document.querySelector('.pager').inert=true; $('result-count').textContent='Searching…'; $('error').hidden=true; $('empty').hidden=true; $('previous').disabled=$('next').disabled=true;
 try { const problem=reviewModeProblem();if(problem)throw new Error(problem);const data=await api('/api/rows?'+currentQuery(),controller.signal); if(controller!==searchController) return; renderRows(data); saveUrl(); }
 catch(error) { if(error.name!=='AbortError'&&controller===searchController) { $('error-message').textContent=error.message; $('error').hidden=false; $('result-count').textContent='Results unavailable'; document.querySelector('.pager').hidden=true; $('rows').replaceChildren(); } }
 finally { if(controller===searchController) { $('results').setAttribute('aria-busy','false'); $('results').inert=false; document.querySelector('.pager').inert=false; } }
}
function closeDetail(update=true) {
 detailController?.abort(); detailController=null; detailEntry=null; rowData=null; technicalPromise=null; technicalReady=false; observationData=null; formattedFields.clear(); const wasOpen=$('detail').open; $('detail').close();
 delete $('detail').dataset.row; delete $('detail').dataset.catalog;
 for(const section of ['detail-data','source-variants','origin','document-summary','complete-body-review','filename-findings','saved-evidence'])$(section).replaceChildren();
 if(wasOpen) (detailOpener?.isConnected&&detailOpener!==document.body?detailOpener:$('q')).focus();
 if(update) saveUrl();
}
function resetDetail(id,catalog) {
 detailController?.abort(); detailController=new AbortController(); rowData=null; detailEntry=null; formattedFields.clear(); sourceOffset=0; sourcePageId=null; technicalPromise=null; technicalReady=false; observationData=null; $('detail').dataset.row=String(id); $('detail').dataset.catalog=catalog || info.catalog_id; setDetailTitle('Loading…'); $('detail-data').replaceChildren(); $('field-count').textContent=''; $('field-search').value=''; $('show-empty').checked=false; $('copy').disabled=true; $('share').disabled=true; $('source-link').hidden=true; $('saved-link').hidden=true; $('detail-selected').hidden=true; $('copy-status').textContent=''; $('share-status').textContent='';
 for(const section of ['document-summary','complete-body-review','origin','filename-findings','saved-evidence']) { $(section).replaceChildren(); $(section).hidden=true; }
 document.querySelector('.detail-secondary').hidden=true;
 $('technical').open=false; $('technical').hidden=true; $('detail').setAttribute('aria-busy','true'); $('source-history').hidden=true; $('source-history').querySelector('details').open=false; $('detail').scrollTop=0;
 $('source-variants').replaceChildren(); $('source-variants').hidden=true;
 return detailController;
}
async function openDetail(id, update=true, catalog=info.catalog_id) {
 if(!$('detail').open) detailOpener=document.activeElement;
 const controller=resetDetail(id,catalog);
 if(!$('detail').open) $('detail').showModal(); if(update) saveUrl('pushState');
 try { const problem=reviewModeProblem();if(problem)throw new Error(problem);const entry=await api('/api/entry/'+encodeURIComponent(id)+'?catalog='+encodeURIComponent(catalog || info.catalog_id),controller.signal); if(controller!==detailController) return; const data=entry.record; rowData=data; detailEntry=entry; $('detail').dataset.row=data.source_id; $('detail').dataset.catalog=entry.catalog_id; saveUrl(); setDetailTitle(identity({...data,filename:entry.filename,api_reference:entry.api_reference,video_reference:entry.video_reference}),entry.api_reference||entry.video_reference?'title':'filename'); $('copy').disabled=false; $('share').disabled=false;
 if(data.filename!==entry.filename) { $('detail-selected').hidden=false; $('detail-selected').textContent='Selected source filename: '+(data.filename || 'Not recorded'); }
 const url=sourceUrl(data.source_url); if(url) {
  $('source-link').href=url.href; $('source-link').replaceChildren(node('span',entry.video_reference?'Watch video ↗':entry.api_reference?'Open API record ↗':'Open original URL ↗'),node('span',url.hostname.replace(/^www\./,''),'link-caption')); $('source-link').hidden=false;
 }
 const savedUrl=adapter.savedUrl(entry);
 if(savedUrl) {
  const recovered=(data.recovery||entry.recovery)?.recovery_status==='recovered',failed=!recovered&&data.record_role?.includes('error-response');
  const savedFormats=recovered?[(data.recovery||entry.recovery).kind]:(data.body_format?.length?data.body_format:data.format)||[];
  const webpage=!failed&&savedFormats.some(value=>['html','text/html','application/xhtml+xml'].includes(value?.toLowerCase()));
  const caption=[webpage&&entry.video_reference?'Webpage only':null,recovered?(data.recovery?'Recovered copy':'Recovered via related URL'):failed?'Failed response':null,entry.published_only?'R2 archive':'Saved in archive'].filter(Boolean).join(' · ');
  $('saved-link').hidden=false; $('saved-link').replaceChildren(node('span',failed?'Open saved response ↗':webpage?'Open saved webpage ↗':entry.video_reference?'Open saved response ↗':'Open saved copy ↗'),node('span',caption,'link-caption')); $('saved-link').href=savedUrl;
 }
 renderSummary(entry); renderFilename(entry); renderSources(entry); renderCurrentOrigin();
 if(info.complete_body_reviews)loadCompleteReview(entry,controller);
 $('technical').hidden=false; document.querySelector('.detail-secondary').hidden=false; loadEvidence(entry,controller); if(entry.origin_pending)loadEntryOrigin(entry,controller); }
 catch(error) { if(error.name!=='AbortError'&&controller===detailController) { setDetailTitle('Record unavailable'); $('document-summary').hidden=false; $('document-summary').append(node('p',error.message)); const retry=node('button','Retry this record','outline');retry.addEventListener('click',()=>openDetail(id,false,catalog));$('document-summary').append(retry); } }
 finally { if(controller===detailController)$('detail').setAttribute('aria-busy','false'); }
}
function renderSources(entry, focusPage) {
 const active=$('source-variants').contains(document.activeElement)?document.activeElement:null;
 const focused=active?.dataset.source;
 focusPage=focusPage||(active?.tagName==='BUTTON'&&!focused?active.textContent:null);
 $('source-variants').replaceChildren();
 if(entry.sources.length>1) {
  const pageSize=20;
  if(sourcePageId!==entry.record.source_id) {
   sourcePageId=entry.record.source_id;
   sourceOffset=Math.floor(Math.max(0,entry.sources.findIndex(source=>source.source_id===sourcePageId))/pageSize)*pageSize;
  }
  $('source-history').hidden=false; $('source-variants-caption').textContent=`${entry.sources.length} source records in this group`;
  $('source-variants').hidden=false;
  $('source-variants').append(node('p',entry.sources_share_saved_file?'These records share one saved file. Select a record to inspect it.':'Select a source record to inspect its own metadata.'));
  const redirects=entry.document_origin?.redirects || entry.origin.redirects;
  const originals=new Set(redirects.map(row=>row.original)), finals=new Set(redirects.map(row=>row.final));
  for(const source of entry.sources.slice(sourceOffset,sourceOffset+pageSize)) {
   const role=!source.source_url?'Source record':entry.origin_pending?'Source URL':originals.has(source.source_url)?'Original URL':finals.has(source.source_url)?'Redirect destination':'Alternate source URL';
   const caption=[role,source.format?.map(formatLabel).join(' · ') || 'Unknown format',savedLabel(source)].join(' · ');
   const button=node('button',caption,'outline'); button.dataset.source=source.source_id; button.setAttribute('aria-pressed',String(source.source_id===entry.record.source_id));
   button.append(node('span',source.source_url || source.filename || 'No URL or filename recorded','source'));
   button.addEventListener('click',()=>openDetail(source.source_id)); $('source-variants').append(button);
   if(focused===source.source_id)button.focus({preventScroll:true});
  }
  if(entry.sources.length>pageSize) {
   $('source-variants').append(node('p',`${number(sourceOffset+1)}–${number(Math.min(sourceOffset+pageSize,entry.sources.length))} of ${number(entry.sources.length)} source records`,'section-note'));
   const navigation=node('div',undefined,'actions');
   for(const [caption,delta] of [['Previous sources',-pageSize],['Next sources',pageSize]]) {
    const button=node('button',caption,'outline');button.type='button';button.disabled=sourceOffset+delta<0||sourceOffset+delta>=entry.sources.length;
    button.addEventListener('click',()=>{sourceOffset+=delta;renderSources(entry,caption);});navigation.append(button);
   }
   $('source-variants').append(navigation);
   if(focusPage) {const preferred=[...navigation.children].find(button=>button.textContent===focusPage);(preferred?.disabled?$('source-variants').querySelector('button[data-source]'):preferred)?.focus({preventScroll:true});}
  }
 }
}
async function loadEntryOrigin(entry, controller) {
 try {
  const context=await api(detailUrl('entry-origin'),controller.signal);
  if(controller!==detailController||controller.signal.aborted)return;
  Object.assign(entry,context);renderCurrentOrigin();renderSources(entry);
 } catch(error) {
  if(controller!==detailController||controller.signal.aborted||error.name==='AbortError')return;
  const el=section('origin','Source pages');el.append(node('p','Source pages could not be loaded. '+error.message,'warning'));
  const retry=node('button','Retry source pages','outline');retry.addEventListener('click',()=>{retry.disabled=true;loadEntryOrigin(entry,controller);});el.append(retry);
 }
}
function link(value, text) { const url=sourceUrl(value); if(!url) return node('span',value || 'Not recorded'); const a=node('a',text || url.href); a.href=url.href; a.target='_blank'; a.rel='noopener noreferrer'; return a; }
function fact(dl, title, value, note) { dl.append(node('dt',title)); const dd=node('dd'); dd.append(value instanceof Node ? value : node('span',String(value))); if(note) dd.append(node('span',note,'fact-note')); dl.append(dd); }
function section(id, title) { const el=$(id); el.hidden=false; el.replaceChildren(node('h3',title)); return el; }
function recordedList(values, caption) {
 const details=node('details'),list=node('ul');details.append(node('summary',caption),list);
 values.forEach(value=>list.append(node('li',value)));return details;
}
async function loadCompleteReview(entry, controller, withdrawn=false) {
 const el=section('complete-body-review','Complete document review');
 el.append(node('p','Checking review…','section-note'));
 try {
  const result=await api(detailUrl('review',withdrawn?'&selection=baseline':''),controller.signal);
  if(controller!==detailController||controller.signal.aborted)return;
  el.replaceChildren(node('h3','Complete document review'));
  if(result.status==='no_review') {el.append(node('p','No complete-body review in this bundle. The catalog classification is unchanged.'));return;}
  const labels={candidate_applied:'Reviewed classification preview',annotation_only_unsupported_forms:'Findings retained; classification unchanged',withdrawn:'Review withdrawn from this preview'};
  el.append(node('p',labels[result.status]||result.status,'review-note'));
  el.append(node('p','Assistant-reviewed findings; not independently confirmed. '+($('classification').value==='reviewed'?
   'Search uses reviewed categories. Withdrawal here affects only this panel; choose Original catalog in search to restore original search categories. Downloads preserve the original catalog.':
   'This preview affects this panel only; search and downloads use the original catalog.'),'section-note'));
  const dl=node('dl',undefined,'facts'),review=result.review,observed=review.body_observation;
  const kinds=values=>values?.map(friendly).join(' · ')||'Unclassified';
  fact(dl,'Original category',kinds(result.baseline.document_kind));
  fact(dl,'Preview category',kinds(result.selected.document_kind));
  fact(dl,'Primary forms',kinds(review.primary_forms));
  if(review.component_forms.length)fact(dl,'Additional forms',kinds(review.component_forms));
  fact(dl,'Pages reviewed',observed.pages);el.append(dl);
  if(result.status==='annotation_only_unsupported_forms')el.append(node('p','This packet includes forms outside the supported categories. All findings are retained together; none changes the catalog classification.','warning'));
  const toggle=node('button',withdrawn?'Restore reviewed preview':'Withdraw review from preview','outline');
  toggle.addEventListener('click',()=>{toggle.disabled=true;loadCompleteReview(entry,controller,!withdrawn);});el.append(toggle);
  const evidenceUrl=(kind,page)=>adapter.reviewEvidence(entry,result,kind,page);
  const pdf=node('p'),pdfLink=link(new URL(evidenceUrl('body'),location.href).href,'Download the exact reviewed PDF');
  pdfLink.removeAttribute('target');pdfLink.download='reviewed-document.pdf';pdf.append(pdfLink);el.append(pdf);
  for(const [kind,field,caption] of [['text','text_path','Saved extracted text'],['native-text','native_text_path','Saved native text']])if(observed[field]) {
   const text=node('p');text.append(link(new URL(evidenceUrl(kind),location.href).href,caption+' ↗'));el.append(text);
  }
  if(observed.notes)el.append(node('p',observed.notes));
  for(const observation of observed.observations||[])el.append(node('p',typeof observation==='string'?observation:JSON.stringify(observation)));
  for(const observation of observed.source_completeness_observations||[])el.append(node('p',typeof observation==='string'?observation:
   (observation.pdf_pages?.length?'PDF pages '+observation.pdf_pages.join(', ')+': ':'')+(observation.observation||JSON.stringify(observation)),'warning'));
  if(observed.page_sections?.length) {
   const list=node('ul');
   for(const part of observed.page_sections)list.append(node('li',`Pages ${part.first_page}–${part.last_page}: ${part.observed_form.split('|').map(friendly).join(' · ')}${part.description?' — '+part.description:''}`));
   el.append(list);
  }
  const pages=node('details'),links=node('p');pages.append(node('summary','Reviewed page images'),links);
  for(let page=1;page<=observed.pages;page++) {links.append(link(new URL(evidenceUrl('page',page),location.href).href,'Page '+page),document.createTextNode(' · '));}
  el.append(pages);
 } catch(error) {
  if(controller!==detailController||controller.signal.aborted||error.name==='AbortError')return;
  el.replaceChildren(node('h3','Complete document review'),node('p','Review unavailable. The catalog classification remains unchanged. '+error.message,'warning'));
 }
}
function renderSummary(entry) {
 const el=$('document-summary'), row=entry.document, source=entry.record, dl=node('dl',undefined,'facts');
 el.hidden=false; el.replaceChildren();
 if(entry.api_reference) fact(dl,'Entry type','Source/API reference','Identified from the Congress.gov API URL. Published role: '+(source.record_role?.map(friendly).join(' · ')||'Not recorded')+'.');
 const filenameKind=row.document_kind_source?.length===1&&row.document_kind_source[0]==='filename', groupKind=source.source_id!==row.source_id;
 const multipleKinds=row.document_kind?.length>1;
 if(!entry.video_reference && multipleKinds) {
  const kinds=node('div','Multiple recorded kinds');
  const readings=recordedList(row.document_kind.map(friendly),'Review classifications');
  readings.append(node('p',(groupKind?'From the grouped records.':'From this source record.')+(row.document_kind_source?.length?' Based on '+row.document_kind_source.map(value=>friendly(value).toLowerCase()).join(' · ')+'.':''),'section-note'));
  if(source.source_document_type?.length)readings.append(node('p',(source.source_document_type_basis?.some(value=>/inference|parser/.test(value))?'Inferred source-page readings: ':'Source-page readings: ')+source.source_document_type.map(friendly).join(' · '),'section-note'));
  kinds.append(readings);fact(dl,'Document kind',kinds);
 } else if(!entry.video_reference) fact(dl,groupKind?'Group kind':filenameKind?'Filename kind':'Document kind',row.document_kind?.map(friendly).join(' · ')||'Unclassified',filenameKind&&groupKind?'From the group’s filename.':row.document_kind?.length&&!filenameKind?(row.document_kind_source?.length?'Based on '+row.document_kind_source.map(value=>friendly(value).toLowerCase()).join(' · ')+'.':'Classification evidence not recorded.'):null);
 if(!entry.video_reference && !multipleKinds && source.source_document_type?.length && source.source_document_type.some(value=>!row.document_kind?.includes(value))) {
  const inferred=source.source_document_type_basis?.some(value=>/inference|parser/.test(value));
  fact(dl,'Source-page kind',source.source_document_type.map(friendly).join(' · '),inferred?'Inferred from page metadata.':null);
 }
 const formats=source.format?.map(formatLabel).join(' · ');
 const formatValue=node('span',formats||'Unknown');
 if(formats)formatValue.append(node('span',' · '+(source.body_format?.length?'saved bytes':source.media_type?.length?'server-reported':'filename only'),'inline-note'));
 if(!entry.video_reference||source.body_key) fact(dl,entry.video_reference?'Saved format':'Format',formatValue);
 const recovery=source.recovery||entry.recovery, recovered=recovery?.recovery_status==='recovered';
 const savedNotes=[(source.body_key||recovered)&&entry.published_only&&!entry.saved_file_url?'Stored in R2; file access unavailable here.':null,!recovered&&!source.record_role?.includes('error-response')&&source.response_usable?.includes('false')?'The saved response was marked unusable.':!recovered&&entry.facts?.completeness_conflict?'Recorded completeness assessments disagree.':!recovered&&source.response_body_complete?.includes('false')?'The saved response is incomplete.':null].filter(Boolean);
 if(!(entry.saved_file_available||sourceUrl(entry.saved_file_url))||savedNotes.length)fact(dl,'Saved response',recovered?(source.recovery?'Recovered':'Recovered on another URL in this group'):source.body_key?(source.record_role?.includes('error-response')?'Marked failed':entry.published_only?'Saved':'Available'):entry.sources.some(item=>item.retained)?'Saved on another URL in this group':'None recorded',savedNotes.join(' '));
 if(recovered&&recovery.kind&&!(source.format?.length===1&&source.format[0]===recovery.kind))fact(dl,'Recovered format',formatLabel(recovery.kind));
 if(source.state_outcome?.some(value=>!['saved','retained','html'].includes(value))) fact(dl,recovered?'Original URL fetch':'Recorded fetch',source.state_outcome.map(friendly).join(' · '),source.state_checked_at?.length===1?'Recorded '+dateLabel(source.state_checked_at[0]):null);
 if(source.source_committee_name?.length) fact(dl,'Committee',source.source_committee_name.length>1?recordedList(source.source_committee_name,number(source.source_committee_name.length)+' recorded committees'):source.source_committee_name[0]);
 if(!source.congress?.length&&source.source_congress?.length) fact(dl,'Source Congress',source.source_congress.join(' · '));
 if(source.congress?.length) {
  const warning=congressIssue(source.congress,source.source_congress),value=node('span','Filename: '+display(source.congress));
  if(source.source_congress?.length) value.append(node('span','Source: '+display(source.source_congress),'fact-note'));
  fact(dl,'Congress'+(warning?' · Review':''),value,congressIssue(source.congress)+(source.source_congress?.length&&!source.congress.some(value=>source.source_congress.includes(value))?' Filename and source values disagree.':''));if(warning)dl.lastElementChild.classList.add('warning');
 }
 el.append(dl);
 const content=node('div'); content.id='content-summary';
 content.hidden=!entry.saved_file_available; content.append(node('p','Checking saved contents…','section-note')); el.append(content);
}
function referenceRole(value) {
 const url=sourceUrl(value); if(!url) return 'Source reference';
 if(url.hostname==='api.congress.gov') return 'API record';
 if(/rss|feed/i.test(url.pathname)) return 'Feed';
 if(/\.xml(?:$|[?&])/i.test(url.pathname+url.search)) return 'XML source';
 if(/\.json$/i.test(url.pathname)) return 'JSON source';
 return 'Website page';
}
function pageLink(value,title) {
 const url=sourceUrl(value), block=node('div',undefined,'page-link');
 if(!url)return node('span','Source URL not available','muted');
 const a=link(value,(title||url.hostname.replace(/^www\./,''))+' ↗'); a.title=url.href;
 block.append(a);
 if(title) block.append(node('p',url.hostname.replace(/^www\./,''),'link-caption'));
 else if(url.pathname!=='/'||url.search) block.append(node('p',url.pathname+url.search,'link-caption url-path'));
 return block;
}
function renderOrigin(origin,apiReference,observationCount,recovery) {
 const el=section('origin','Where it came from'), linkEvidence=[], covered=new Set();
 const urlKey=provenanceUrlKey, graph=evidenceGraph(origin);
 for(const {root,path} of graph.paths) {
  const group=node('div',undefined,'source-path'),list=node('ol',undefined,'source-chain');
  group.append(node('p',(root.types||[]).some(type=>/hearing/i.test(type))?'Associated hearing':'Related source','link-caption'));
  for(const edge of path) if(edge.page) {
   const page=edge.page,value=page.urls[0],item=node('li');covered.add(urlKey(value));
   const observed=graph.referenceByKey.get(urlKey(value)).pages.filter(page=>page.urls.length===1);
   const titles=[...new Set(observed.flatMap(page=>page.titles))], dates=[...new Set(observed.flatMap(page=>page.dates||[]))];
   item.append(pageLink(value,titles.length===1?titles[0]:null));
   if(dates.length===1)item.append(node('p',filenameDate(dates[0]),'link-caption'));
   const labels=new Set(observed.filter(page=>page.link_urls.length===1&&sourceUrl(page.link_urls[0])?.href===edge.to).flatMap(page=>page.link_labels));
   for(const text of labels)linkEvidence.push({from:sourceUrl(value).hostname.replace(/^www\./,''),text});
   list.append(item);
  }
  list.append(node('li','This file','chain-current'));group.append(list);el.append(group);
 }
 const references=graph.references, human=references.filter(item=>referenceRole(item.url)==='Website page');
 const machine=references.filter(item=>referenceRole(item.url)!=='Website page');
 function destination(value,title,caption) {
  const block=node('div',undefined,'provenance-item'),url=sourceUrl(value);
  block.append(link(value,title+' ↗'),node('p',caption||url.hostname.replace(/^www\./,''),'link-caption'));
  return block;
 }
 let previousCaption;
 for(const item of human) {
  if(covered.has(urlKey(item.url)))continue;
  // A single observed page/title pair can name the link. Multi-page
  // observations stay intact in technical details and never supply a label.
  const titles=[...new Set(item.pages.filter(page=>page.urls.length===1&&page.titles.length===1).map(page=>page.titles[0]))];
  const relationships=new Set(item.pages.map(page=>page.relationship));
  const caption=relationships.has('Linked from')?'Found on':relationships.has('Linked through')?'Related source':relationships.has('Recorded source page')?'Source page':'Possible source page';
  const block=node('div',undefined,'provenance-item');
  if(caption!==previousCaption)block.append(node('p',caption,'link-caption'));
  previousCaption=caption;block.append(pageLink(item.url,titles.length===1?titles[0]:null));
  const dates=[...new Set(item.pages.filter(page=>page.urls.length===1).flatMap(page=>page.dates||[]))];
  if(dates.length===1)block.append(node('p','Recorded date: '+filenameDate(dates[0]),'link-caption'));
  el.append(block);
 }
 if(!human.length) {
  if(origin.file_url&&!(recovery?.recovery_status==='recovered'&&sourceUrl(recovery.recovered_url)?.hostname===sourceUrl(origin.file_url)?.hostname))el.append(node('p',(apiReference?'API host: ':'Source host: ')+sourceUrl(origin.file_url).hostname,'link-caption'));
  el.append(node('p',origin.pages.length?'No referring website page recorded.':'Referring page not recorded for this source.','empty-state'));
 }
 const labels=[...new Set(origin.pages.filter(page=>page.relationship!=='Linked through'&&!page.urls.some(value=>covered.has(urlKey(value)))).flatMap(page=>page.link_labels).filter(present))];
 const supporting=node('details',undefined,'supporting-links');supporting.append(node('summary','Source evidence'));
 for(const {from,text} of linkEvidence) {
  const block=node('div',undefined,'publisher-label');block.append(node('p','Link text on '+from,'link-caption'),node('blockquote',text));supporting.append(block);
 }
 if(labels.length) {
  const block=node('div',undefined,'publisher-label');
  block.append(node('p',labels.length===1?'Publisher’s link text':'Publisher’s link text · '+labels.length+' versions','link-caption'));
  labels.forEach(value=>block.append(node('blockquote',value)));supporting.append(block);
 }
 for(const item of machine) {
  const url=sourceUrl(item.url),match=/^\/v3\/([^/]+)\/(\d+)\/(house|senate)\/([^/]+)/.exec(url.pathname);
  const title=match?`${pretty(match[3])} ${match[1].replaceAll('-',' ')} ${match[4]}`:referenceRole(item.url);
  supporting.append(destination(item.url,title,url.hostname+(match?' · Congress '+match[2]:'')));
 }
 const shown=new Set([...references.map(item=>urlKey(item.url)),urlKey(origin.file_url)]);
 // The destination is already available through Open original URL. Only
 // additional original or recovered URLs belong in this disclosure.
 for(const redirect of origin.redirects) if(!shown.has(urlKey(redirect.original))) {
  shown.add(urlKey(redirect.original));supporting.append(destination(redirect.original,'Original download link','Redirects to the publisher file'));
 }
 for(const value of origin.recovered_urls) if(!shown.has(urlKey(value))&&!(recovery?.recovery_status==='recovered'&&urlKey(value)===urlKey(recovery.recovered_url))) {
  shown.add(urlKey(value));supporting.append(destination(value,'Recovered URL candidate','Referring-page relationship not established'));
 }
 if(recovery?.recovery_status==='recovered') {
  const block=node('div',undefined,'provenance-item recovery-source');
  block.append(node('p',[recovery.original_url,recovery.recovered_url].includes(origin.file_url)?'Saved copy recovered from':'Saved copy recovered through another URL in this group','link-caption'),pageLink(recovery.recovered_url));
  if(recovery.original_url!==origin.file_url&&!shown.has(urlKey(recovery.original_url)))supporting.append(destination(recovery.original_url,'Original URL before recovery',sourceUrl(recovery.original_url)?.hostname));
  el.append(block);
 }
 if(observationCount) {
  const button=node('button',`View ${number(observationCount)} source observation${observationCount===1?'':'s'}`,'quiet evidence-link');button.type='button';button.setAttribute('aria-controls','technical');
  button.addEventListener('click',()=>{$('technical').open=true;$('field-search').value='source_occurrences';ensureTechnical();$('technical').scrollIntoView({block:'start'});$('technical').querySelector('summary').focus({preventScroll:true});});supporting.append(button);
 }
 if(supporting.childElementCount>1)el.append(supporting);
}

const nonFilename = new Set(['body_key','filename','source_url','filename_origins','media_type','http_status','response_usable','response_body_complete','response_format','response_result','body_format','capture_outcome','record_role','source_id','document_id','format','cache_marker_state','recovered_filename','recovered_source_url','document_kind','document_kind_source','document_family','state_outcome','state_family','state_body_key','state_checked_at','state_retrieved_at','hearing_package_id','hearing_resources']);
nonFilename.add('recovery');
function filenameFields(record) { return Object.entries(record).filter(([key,value])=>present(value)&&!key.startsWith('source_')&&!key.startsWith('content_')&&!nonFilename.has(key)); }
// Parser fragments remain searchable in All recorded fields. The reading
// surface shows descriptive results, without promoting unmatched text to facts.
function isFilenameFragment(key) {
 return (/(?:^|_)(?:token|marker|wording|prefix|suffix|placeholder|remainder)(?:_|$)/.test(key) || /^(?:opaque|local|generic|ambiguous)_/.test(key) || /^(?:extension|embedded_extension|label|name_token)$/.test(key) || /_code$/.test(key));
}
function showFields(query) {
 $('technical').open=true; $('field-search').value=query; ensureTechnical();
 $('technical').scrollIntoView({block:'start'}); $('field-search').focus({preventScroll:true});
}
function renderFilename(entry) {
 if(entry.video_reference) { $('filename-findings').hidden=true; return; }
 const el=section('filename-findings','Filename clues'), row=entry.record, reading=adapter.reading(entry), dl=node('dl',undefined,'facts'), consumed=new Set(['extension']);
 el.classList.remove('compact');
 consumed.add('congress');
 if(row.measure_references?.length) {
  const unusual=row.measure_references.some(value=>/\d{6,}$/.test(value));
  fact(dl,unusual?'Possible measure':'Measure',row.measure_references.map(measureLabel).join(' · '),unusual?'This number may be a publisher identifier.':null); consumed.add('measure_references');
  const parsed=row.measure_references.map(value=>/^([a-z]+)(\d+)$/i.exec(value)).filter(Boolean),types=parsed.map(match=>match[1].toLowerCase()),numbers=parsed.map(match=>match[2]);
  if(row.measure_number?.every(value=>numbers.includes(value)))consumed.add('measure_number');
  for(const key of ['measure_token','measure_token_code','measure_type']) if(row[key]?.every(value=>types.includes(value.toLowerCase())))consumed.add(key);
  if(consumed.has('measure_token'))consumed.add('measure_token_label');
 }
 if(row.date_token_candidates?.length) { fact(dl,'Possible date',row.date_token_candidates.map(filenameDate).join(' · '),'Date role unknown; may differ from the hearing or publication date.');consumed.add('date_token');consumed.add('date_token_candidates'); }
 const fields=filenameFields(row);
 for(const [key,value] of fields) {
  if(consumed.has(key)||isFilenameFragment(key)||key.endsWith('_label')&&present(row[key.slice(0,-6)])) continue;
  const pairedLabel=row[key+'_label'], notes=reading?.observations.filter(f=>f.name===key&&f.note&&[].concat(value).includes(f.raw)).map(f=>f.note)||[];
  if([].concat(pairedLabel||value).every(item=>entry.document.document_kind?.some(kind=>friendly(kind).toLowerCase()===friendly(item).toLowerCase())))continue;
  fact(dl,label(key),display(pairedLabel||value),[...new Set(notes)].join(' '));
 }
 const hasFindings=dl.childElementCount>0;
 if(hasFindings)el.append(node('p','Unverified filename interpretations.','section-note'),dl);
 else {el.replaceChildren();el.classList.add('compact');}
 const support=node('details');support.append(node('summary',hasFindings?'How this filename was read':'Filename analysis'));
 if(entry.filename_field_count||fields.length) { const inspect=node('button','Inspect filename fields','quiet evidence-link');inspect.type='button';inspect.addEventListener('click',()=>showFields('Filename interpretations'));support.append(inspect); }
 if(adapter.published(entry)) support.append(node('p',`Published house-naming results · version ${info.house_naming_version}. This page reads the catalog snapshot; it does not rerun the naming rules.`,'section-note'));
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
 const el=node('div'), offset=observationData?.offset || 0;
 if(observationData) {
  const total=observationData.total;
  el.append(node('p',total?`${number(offset+1)}–${number(offset+occurrences.length)} of ${number(total)} observations`:'No source observations recorded.','section-note'));
 }
 occurrences.forEach((occurrence,index)=>{
  const details=node('details'), scope=occurrence?.source_occurrence_scope?.map(friendly).join(' · ') || 'Source observation';
  details.append(node('summary',`${number(offset+index+1)}. ${scope}`));
  let rendered=false;
  details.addEventListener('toggle',()=>{
   if(!details.open||rendered)return;rendered=true;
   const dl=node('dl',undefined,'facts');
   for(const [key,value] of Object.entries(occurrence||{})) if(present(value)) {
    const values=node('span');[].concat(value).forEach((v,i)=>{if(i)values.append(document.createElement('br'));values.append(webUrlOrText(v));});fact(dl,label(key),values);
   }
   details.append(dl);
  });
  el.append(details);
 });
 if(observationData&&(offset||observationData.next!==null)) {
  const nav=node('div',undefined,'actions');
  for(const [caption,start] of [['Previous observations',offset?Math.max(0,offset-20):null],['Next observations',observationData.next]]) {
   const button=node('button',caption,'outline');button.type='button';button.disabled=start===null;
   button.addEventListener('click',async()=>{const controller=detailController;button.disabled=true;try{await loadObservationPage(start);if(controller!==detailController)return;renderDetails();focusField('source_occurrences');}catch(error){if(error.name!=='AbortError'){button.disabled=false;el.append(node('p',error.message,'warning'));}}});nav.append(button);
  }
  el.append(nav);
 }
 return el;
}

function webUrlOrText(value) { return sourceUrl(value)?link(value):node('span',typeof value==='object'?JSON.stringify(value):String(value)); }
async function loadEvidence(entry,controller) {
 const el=section('saved-evidence','Saved response evidence'), summary=$('content-summary');
 if(adapter.published(entry)) {
  const content=Object.entries(entry.record).filter(([key,value])=>key.startsWith('content_')&&present(value));
  summary.hidden=!content.length;
  summary.replaceChildren(node('p','Saved contents · published findings','link-caption'));
  for(const [key,value] of content) summary.append(node('p',label(key)+': '+display(value)));
  // Archive access is explained once in the summary; object keys remain in
  // All recorded fields. A second section added no action or evidence.
  el.hidden=true;
  return;
 }
 if(!entry.saved_file_available) { el.hidden=true; return; } el.hidden=false;
 el.append(node('p','Reading the saved file and checking its hash…','section-note'));
 try {
  const evidence=await api('/api/evidence/'+encodeURIComponent(entry.record.source_id)+'?catalog='+encodeURIComponent(entry.catalog_id),controller.signal); if(controller!==detailController) return;
  summary.replaceChildren(node('p','Saved contents · checked now','link-caption'));
  const content=evidence.content_fields||{}, kind=content.content_document_kind?.map(friendly).join(' · '), congress=content.content_congress?.join(' · ');
  summary.append(node('p',[kind,congress?'Congress '+congress:null].filter(Boolean).join(' · ')||'No classification found in the inspected contents.',kind||congress?'classification':'section-note'));
  for(const [key,value] of Object.entries(content)) if(!['content_document_kind','content_congress'].includes(key)) summary.append(node('p',label(key)+': '+display(value)));
  if(Object.keys(content).length)summary.append(node('p','Read from the saved file; published metadata is unchanged.','section-note'));
  el.replaceChildren(node('h3','Saved response evidence')); const dl=node('dl',undefined,'facts');
  fact(dl,'Integrity','Saved bytes verified',number(evidence.bytes)+' bytes'+(evidence.page_count?' · '+number(evidence.page_count)+' pages':''));
  if(evidence.receipt) { const receipt=evidence.receipt; fact(dl,'Captured',receipt.retrieved_at?dateLabel(receipt.retrieved_at):'Time not recorded','Download time, separate from the document’s date.'); fact(dl,'Response',receipt.http_status?'HTTP '+receipt.http_status:'Status not recorded',receipt.complete===true?'Complete response saved.':receipt.complete===false?'Incomplete response recorded.':'Completeness not recorded.'); }
  else fact(dl,'Capture details',evidence.receipt_error||'No matching receipt details available');
  el.append(dl);
  if(evidence.note)el.append(node('p',evidence.note,'section-note'));
  for(const page of evidence.pages||[]) {
   const details=node('details'),text=page.text.trim(),pre=node('pre',text||'No text extracted. Open the saved PDF to inspect this page.','pdf-text'),long=text.length>700||text.split('\n').length>12;
   details.append(node('summary','Opening text · page '+page.number),pre);
   if(long) {pre.classList.add('preview'); const button=node('button','Show full page text','quiet');button.type='button';button.setAttribute('aria-expanded','false');button.addEventListener('click',()=>{const expanded=pre.classList.toggle('preview')===false;button.textContent=expanded?'Collapse page text':'Show full page text';button.setAttribute('aria-expanded',String(expanded));});details.append(button);}
   el.append(details);
  }
 } catch(error) { if(error.name==='AbortError'||controller!==detailController)return; summary.replaceChildren(node('p',info.complete_body_reviews?'Original archive access failed. Review evidence is checked separately in Complete document review.':'Saved contents could not be checked. See the access error below.','section-note')); el.replaceChildren(node('h3','Saved response evidence'),node('p',error.message,'empty-state'));const retry=node('button','Retry saved-file access','outline');retry.addEventListener('click',()=>loadEvidence(entry,controller));el.append(retry); }
}
function fieldCategory(key) {
 if(['filename','source_url','source_id','document_id','record_role','filename_origins','recovered_filename','recovered_source_url','document_kind','document_kind_source','document_family','format'].includes(key))return 'Identity and classification';
 if(key.startsWith('source_')||key.startsWith('hearing_'))return 'Source and provenance';
 if(key.startsWith('content_'))return 'Saved content findings';
 if(nonFilename.has(key))return 'Download and storage';
 return 'Filename interpretations';
}
function detailUrl(kind, suffix='') {
 return `/api/${kind}/${encodeURIComponent($('detail').dataset.row)}?catalog=${encodeURIComponent($('detail').dataset.catalog)}${suffix}`;
}
async function loadObservationPage(offset=0) {
 const controller=detailController;
 const result=await api(detailUrl('observations',`&offset=${offset}&limit=20`),controller.signal);
 if(controller!==detailController)return;
 observationData=result;rowData.source_occurrences=result.is_null?null:result.items;
}
async function ensureTechnical() {
 if(!detailEntry||technicalReady){if(technicalReady)renderDetails();return;}
 if(technicalPromise)return technicalPromise;
 const controller=detailController;
 $('detail-data').replaceChildren(node('p','Loading recorded fields…','section-note'));
 technicalPromise=(async()=>{
  if(detailEntry.record_complete===false) {
   const record=await api(detailUrl('technical'),controller.signal);
   if(controller!==detailController)return;
   rowData=record;
   await loadObservationPage();
  }
  if(controller!==detailController)return;
  technicalReady=true;renderDetails();
 })().catch(error=>{
  if(controller===detailController&&error.name!=='AbortError') {
   $('detail-data').replaceChildren(node('p',error.message,'warning'));
   const retry=node('button','Retry recorded fields','outline');retry.addEventListener('click',ensureTechnical);$('detail-data').append(retry);
  }
 }).finally(()=>{if(controller===detailController)technicalPromise=null;});
 return technicalPromise;
}
function renderCurrentOrigin() {
 const entry=detailEntry;
 if(entry.origin_pending) {const el=section('origin','Source pages');el.append(node('p','Loading source pages…','section-note'));return;}
 renderOrigin(entry.origin,entry.api_reference,entry.observation_count??entry.record.source_occurrences?.length??0,entry.record.recovery||entry.recovery);
 if(entry.origin_next!=null) {
  const empty=$('origin').querySelector('.empty-state');if(empty)empty.textContent='More source evidence is available below.';
  const more=node('button','More source pages','quiet evidence-link');more.type='button';
  more.addEventListener('click',async()=>{
   const controller=detailController;more.disabled=true;more.textContent='Loading source pages…';
   try {
    const result=await api(detailUrl('origin',`&offset=${entry.origin_next}&limit=20`),controller.signal);
    if(controller!==detailController)return;
    entry.origin=mergeOrigin(entry.origin,result.origin);entry.origin_next=result.next;renderCurrentOrigin();
   } catch(error) {if(controller===detailController&&error.name!=='AbortError'){more.disabled=false;more.textContent='Retry source pages';more.title=error.message;}}
  });$('origin').append(more);
 }
}
function focusField(key) {
 const heading=[...$('detail-data').querySelectorAll('dt')].find(term=>term.dataset.field===key);
 heading?.focus({preventScroll:true});heading?.scrollIntoView({block:'start'});
}
function renderFieldValues(key, value) {
 const items=Array.isArray(value)?value:[value], el=node('div');let offset=0;
 function draw(focus) {
  el.replaceChildren();
  for(const item of items.slice(offset,offset+20)) {
   if(item&&typeof item==='object')el.append(node('pre',JSON.stringify(item,null,2),'pdf-text'));
   else {const line=node('div');line.append(webUrlOrText(item));el.append(line);}
  }
  if(items.length>20) {
   el.append(node('p',`${number(offset+1)}–${number(Math.min(offset+20,items.length))} of ${number(items.length)} values`,'section-note'));
   const nav=node('div',undefined,'actions');
   for(const [caption,delta] of [['Previous values',-20],['Next values',20]]) {
    const button=node('button',caption,'outline');button.type='button';button.setAttribute('aria-label',caption+' for '+label(key));
    button.disabled=offset+delta<0||offset+delta>=items.length;
    button.addEventListener('click',()=>{offset+=delta;draw(caption);});nav.append(button);
   }
   el.append(nav);
   if(focus)focusField(key);
  }
 }
 draw();return el;
}
function renderDetails() {
 if(!rowData||!technicalReady) return;
 const q=$('field-search').value.toLowerCase(); const populated=Object.values(rowData).filter(v=>v!==null&&v!==''&&(!Array.isArray(v)||v.length)).length;
 const entries=Object.entries(rowData).filter(([key,value])=>($('show-empty').checked || present(value)) && (!q || ([label(key),key,fieldCategory(key)].some(text=>text.toLowerCase().includes(q)) || formattedFields.text(key,value,display).includes(q))));
 $('field-count').textContent=`${entries.length} ${entries.length===1?'field':'fields'} shown · ${populated} with values · ${Object.keys(rowData).length} total`;
 const groups=new Map(['Identity and classification','Source and provenance','Download and storage','Saved content findings','Filename interpretations'].map(title=>[title,[]]));
 for(const entry of entries)groups.get(fieldCategory(entry[0])).push(entry);
 const sections=[];
 for(const [title,values] of groups) {
  if(!values.length)continue;
  const group=node('section',undefined,'field-category'),dl=node('dl',undefined,'field-group');group.append(node('h4',title),dl);
  for(const [key,value] of values) { const entry=node('div',undefined,'entry'); const term=node('dt',label(key)); term.tabIndex=-1;term.dataset.field=key;term.append(node('span',key,'raw-key')); entry.append(term); const dd=node('dd'); if(!present(value)) dd.append(node('span','Not recorded','muted')); else if(key==='source_occurrences'&&Array.isArray(value))dd.append(renderOccurrences(value)); else dd.append(renderFieldValues(key,value)); if(key==='name_token'&&present(value))dd.append(node('span','Unmatched filename text; not a verified person, author, or identifier.','fact-note'));entry.append(dd); dl.append(entry); }
  sections.push(group);
 }
 $('detail-data').replaceChildren(...(entries.length?sections:[node('p','No fields match this search.','muted')]));
}
$('search-form').addEventListener('submit',event=>{event.preventDefault();changed();});
$('q').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>changed('replaceState'),220);});
for(const key of keys.filter(k=>k!=='q'&&k!=='field')) $(key).addEventListener('change',()=>{if(key==='classification')reviewPin=$('classification').value?info.review_sha256:null;changed();});
$('field').addEventListener('change',()=>{if($('field').value==='__advanced__') { $('field').value=searchField; $('advanced-field').hidden=false; renderFieldPicker(); $('field-picker-search').focus(); } else {selectField($('field').value);$('advanced-field').hidden=true;changed();}});
$('field-picker-search').addEventListener('input',renderFieldPicker);
$('close-field-picker').addEventListener('click',()=>{$('advanced-field').hidden=true;$('field').focus();});
$('retry').addEventListener('click',()=>info?load():location.reload());
$('reset').addEventListener('click',reset); $('empty-reset').addEventListener('click',reset);
function goToPage(value) {page=positiveInteger(value,1,pages);saveUrl('pushState');load();$('results-bar').scrollIntoView({block:'start'});}
for(const [id,delta] of [['previous',-1],['next',1]]) $(id).addEventListener('click',()=>goToPage(page+delta));
$('page-form').addEventListener('submit',event=>{event.preventDefault();goToPage($('page-number').value);});
$('back-to-results').addEventListener('click',()=>$('results-bar').scrollIntoView({block:'start'}));
function updateTitleToggle() {
 if($('title-toggle').getAttribute('aria-expanded')!=='true')$('title-toggle').hidden=$('detail-title').scrollHeight<=$('detail-title').clientHeight+1;
}
function setDetailTitle(value,kind='filename') {
 $('detail-title').textContent=value; $('detail-title').classList.remove('expanded');
 $('title-toggle').setAttribute('aria-expanded','false');$('title-toggle').dataset.kind=kind;$('title-toggle').textContent='Full '+kind;$('title-toggle').hidden=true;
 updateTitleToggle();
}
$('title-toggle').addEventListener('click',()=>{const expanded=$('detail-title').classList.toggle('expanded');$('title-toggle').setAttribute('aria-expanded',String(expanded));$('title-toggle').textContent=(expanded?'Collapse ':'Full ')+$('title-toggle').dataset.kind;});
if(window.ResizeObserver)new ResizeObserver(updateTitleToggle).observe($('detail-title'));
$('close-detail').addEventListener('click',()=>closeDetail());
$('detail').addEventListener('cancel',event=>{event.preventDefault();closeDetail();});
$('detail').addEventListener('click',event=>{if(event.target===$('detail') && event.clientX<$('detail').getBoundingClientRect().left) closeDetail();});
$('technical').addEventListener('toggle',()=>{if($('technical').open)ensureTechnical();});
$('field-search').addEventListener('input',renderDetails); $('show-empty').addEventListener('change',renderDetails);
$('copy').addEventListener('click',async()=>{const controller=detailController;$('copy').disabled=true;$('copy-status').textContent='Preparing complete metadata…';try{const record=detailEntry.record_complete===false?await api(detailUrl('full'),controller.signal):rowData;if(controller!==detailController)return;await navigator.clipboard.writeText(JSON.stringify(record,null,2));if(controller===detailController)$('copy-status').textContent='Copied';}catch(error){if(controller===detailController&&error.name!=='AbortError')$('copy-status').textContent='Could not copy complete metadata: '+error.message;}finally{if(controller===detailController)$('copy').disabled=false;}});
$('share').addEventListener('click',async()=>{const controller=detailController;try{saveUrl();await navigator.clipboard.writeText(location.href);if(controller===detailController)$('share-status').textContent='Copied';}catch{if(controller===detailController)$('share-status').textContent='Clipboard unavailable';}});
window.addEventListener('popstate',()=>{if(!info)return;const row=restore();load();if(row!==null)openDetail(row.id,false,row.catalog);else closeDetail(false);});
try {
 info=await api('/api/info');
 $('search-form').inert=false; $('search-form').removeAttribute('inert');
 if(info.downloads) {
  const documents=document.querySelector('a[href="/data.parquet"]'),sources=document.querySelector('a[href="/sources.parquet"]');
  if(info.downloads.catalog) {
   documents.hidden=true;sources.hidden=true;
   const index=link(info.downloads.catalog,'Catalog partitions · JSON ↗');index.className='download';document.querySelector('.downloads').append(index);
   const download=node('button','Download document JSON');download.type='button';download.className='button';
   $('copy').parentElement.append(download);
   download.addEventListener('click',async()=>{
    const controller=detailController;if(!controller || !$('detail').dataset.row)return;
    download.disabled=true;$('copy-status').textContent='Preparing complete document metadata…';
    try{
     const record=await api(detailUrl('document'),controller.signal);if(controller!==detailController)return;
     const asset=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)+'\n'],{type:'application/json'}));
     const a=node('a','');a.href=asset;a.download=record.document_id+'.json';document.body.append(a);a.click();a.remove();
     setTimeout(()=>URL.revokeObjectURL(asset),0);$('copy-status').textContent='Document downloaded';
    }catch(error){if(controller===detailController&&error.name!=='AbortError')$('copy-status').textContent='Could not download document: '+error.message;}
    finally{download.disabled=false;}
   });
  } else {documents.href=info.downloads.documents;sources.href=info.downloads.filenames;}
 }
 if(info.downloads?.recoveries) { const a=link(info.downloads.recoveries,'Recovery status · JSON ↗');a.className='download';document.querySelector('.downloads').append(a,node('p','Recovery status is a separate update; Parquet downloads preserve the original catalog values.','section-note')); }
 $('summary').textContent=`${number(info.documents)} documents · ${number(info.capture_records)} source/capture entries`;
 $('summary').title=`${number(info.rows)} source rows · ${number(info.api_reference_groups||0)} API-only groups identified by URL`;
 $('snapshot').textContent=info.remote_last_modified?'Snapshot '+new Date(info.remote_last_modified).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):'Snapshot date not recorded';
 $('snapshot-detail').textContent=info.remote_last_modified?'Catalog updated '+dateLabel(info.remote_last_modified)+(info.synced_at?' · Local copy synced '+dateLabel(info.synced_at):''):'';
 if(info.published_at) $('snapshot-detail').append(node('p','Viewer data published '+dateLabel(info.published_at)+'. This snapshot contains the catalog’s recorded results; fetches still being processed appear after the next catalog update.'));
 $('snapshot-detail').append(node('p',number(info.rows)+' source rows · '+number(info.api_reference_groups||0)+' API-only groups identified by URL.'));
 const options=commonFields.filter(key=>info.fields.includes(key)).map(key=>{const option=node('option',label(key));option.value=key;return option;});
 const advanced=node('option','Find another field…');advanced.value='__advanced__';$('field').replaceChildren(...options,advanced);
 for(const key of secondaryKeys) { const values=[...(info.review_facets?.[key]||info.facets[key])]; if(key==='congress') values.sort((a,b)=>Number(b)-Number(a));for(const value of values) {const text=key.startsWith('document_')?pretty(value):key==='format'?formatLabel(value):congressIssue([value])?value+' · Needs review':value;const option=node('option',text);option.value=value;$(key).append(option);} }
 const row=restore(); if(row!==null)await openDetail(row.id,false,row.catalog);await load();
} catch(error) { $('error-message').textContent=error.message; $('error').hidden=false; $('summary').textContent='Catalog unavailable'; $('result-count').textContent='Results unavailable'; document.querySelector('.pager').hidden=true; $('results').setAttribute('aria-busy','false'); }
