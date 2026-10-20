/** Stable-ID reader for the selected native catalog's bounded delivery assets. */
import {decodeDetailRecord} from './detail-record.mjs';
import {parquetMetadataAsync, parquetReadObjects} from 'hyparquet';
import {compressors} from 'hyparquet-compressors';
import {byteCache, sharedLoad} from './cache.mjs';
import {withVerifiedJson, canonicalJson} from './startup.mjs';
import {observationReader} from './observations.mjs';
import {loadReviews, reviewedMode} from './reviews.mjs';
import {loadRecoveries} from './recoveries.mjs';
import {positiveInteger} from '../../../../../docs/youtube-coverage/research/filename-rules.mjs';
import {yieldToMessages} from './cooperative.mjs';
import {rangeFile, sourceContext, savedCopyUrl, apiReference, videoReference} from './catalog-v5.mjs';

const filters = ['congress','document_kind','document_family','format'];
const origins = ['source_association_basis','source_associated_url','source_original_page_url','source_page_url','source_page_title','source_link_label','source_link_url','source_occurrence_scope','source_page_type','source_page_date'];
const normalize = value => value == null ? null : value instanceof Date ? value.toISOString() : Array.isArray(value) ? value.map(normalize) : typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k,v])=>[k,normalize(v)])) : value;
const values = value => Array.isArray(value) ? value : value == null ? [] : [value];
const text = value => (Array.isArray(value) ? value.map(item=>typeof item === 'object' ? JSON.stringify(item) : item).join(' | ') : value ?? '').toString().toLowerCase();
const same = (a,b) => canonicalJson(a) === canonicalJson(b);
const hash = async value => [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('');
const sourceId = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function compareText(a,b) {
  // Arrow/Python compare Unicode code points; JS's default UTF-16 order differs
  // for supplementary characters beside private-use BMP characters.
  const left=a[Symbol.iterator](),right=b[Symbol.iterator]();
  while(true){const x=left.next(),y=right.next();if(x.done||y.done)return x.done===y.done?0:x.done?-1:1;
    const difference=x.value.codePointAt(0)-y.value.codePointAt(0);if(difference)return difference;}
}
export const compareBrowseKeys = (a,b) => a[0] !== b[0] ? a[0] ? 1 : -1 : compareText(a[1],b[1]) || compareText(a[2],b[2]);
const compare=compareBrowseKeys;
const key = row => [row.filename == null,row.filename ?? '',row.document_id];

export async function createStableFilenameCatalog(publication, fetcher, reviewPublication, options = {}) {
  const {manifest, recovery: recoveryDescriptor} = publication;
  const base = /\/releases\/[a-f0-9]{32}\/manifest\.json$/.test(new URL(publication.url).pathname)
    ? new URL('../../',publication.url) : new URL('./',publication.url);
  const url = path => new URL(path,base).href;
  const metrics = {metadataReads:0,sourceScanVisits:0,groupScanVisits:0,decodedRows:0,tableLoads:0,normalizationValues:0};
  const compressed = byteCache(options.compressedBytes ?? 48*1024*1024, options.rangeEntryBytes ?? 32*1024*1024);
  const decoded = byteCache(options.decodedBytes ?? 64*1024*1024);
  const loads = new Map();
  const cached = (name,load,signal) => {
    signal?.throwIfAborted(); const retained = decoded.get(name);
    return retained ? Promise.resolve(retained) : sharedLoad(loads,name,async()=>{const value=await load();decoded.set(name,value);return value;},signal);
  };
  function valid(ref, names = ['page.json']) {
    if (!ref || !/^[a-f0-9]{64}$/.test(ref.sha256) || !Number.isSafeInteger(ref.bytes) || ref.bytes < 1 ||
        !names.some(name=>ref.path===`releases/${ref.sha256.slice(0,32)}/${ref.sha256.slice(32)}/viewer-v2/${name}`)) throw new Error('Invalid immutable catalog asset.');
  }
  const node = (ref,signal) => {
    valid(ref);
    return cached(ref.path,()=>withVerifiedJson({deadlineMs:30_000,maxBytes:1024*1024},'Catalog page',async verified=>{
      metrics.metadataReads++; return verified(fetcher,url(ref.path),ref.sha256,ref.bytes,'catalog page');
    }),signal);
  };
  const proof = await node(manifest.proof), selected = await node(manifest.source_selection);
  const basis = Object.fromEntries(['version','source_manifest','source_identity','source_selection','requirements','roots','files'].map(k=>[k,manifest[k]]));
  basis.info = Object.fromEntries(Object.entries(manifest.info).filter(([k])=>k!=='publication_version'));
  if (!same(proof,{version:1,kind:'viewer-proof',publication:basis}) ||
      !same(manifest.source_manifest,{version:2,selection:manifest.source_identity?.selected_ref}) ||
      manifest.source_selection.sha256 !== manifest.source_identity?.selected_ref?.sha256 ||
      await hash(canonicalJson(manifest.source_manifest)) !== manifest.source_identity.selector_sha256) throw new Error('Catalog roots belong to a different selected snapshot.');
  const {roots} = manifest, info = {...manifest.info};
  for (const [name,native] of [['sources',selected.dependency.source_root],['components',selected.components]]) {
    if ((roots[name]?.native_sha256 ?? null) !== (native?.sha256 ?? null)) throw new Error('Catalog root differs from the selected native root.');
  }
  if (info.rows !== selected.counts.source_rows || info.entries !== selected.counts.document_rows ||
      (roots.browse?.rows ?? 0) !== info.entries || (roots.sources?.stats.rows ?? 0) !== info.rows ||
      (roots.components?.stats.entries ?? 0) !== info.entries || (roots.components?.stats.source_rows ?? 0) !== info.rows) throw new Error('Catalog selection counts disagree.');
  const recovery = await loadRecoveries(recoveryDescriptor, info, fetcher, {sourceIdentity:manifest.source_identity});
  const reviews = await loadReviews(reviewPublication,manifest,fetcher,base.href);
  Object.assign(info,reviews.info);
  const ranged = ref => rangeFile(url(ref.path),ref.bytes,fetcher,compressed,metrics);
  async function table(part,signal) {
    valid(part,['filenames.parquet','details.parquet','documents.parquet']);
    return cached(`table:${part.path}`,async()=>{
      metrics.tableLoads++; const buffer=ranged(part), metadata=await parquetMetadataAsync(buffer.file());
      if (Number(metadata.num_rows)!==part.rows) throw new Error('Parquet row count differs from its selected partition.');
      return {buffer,metadata};
    },signal);
  }
  async function read(part,start,end,columns,signal) {
    const {buffer,metadata}=await table(part,signal);
    if (columns?.length===0) return Array.from({length:end-start},()=>({}));
    const rows=await parquetReadObjects({file:buffer.file(signal),metadata,compressors,columns,rowStart:start,rowEnd:end});
    signal?.throwIfAborted(); metrics.decodedRows+=rows.length; return rows.map(normalize);
  }
  async function route(root,id,kind,signal) {
    let current=root,prefix=''; const digest=await hash(id);
    while(current) {
      const value=await node(current,signal);
      if(value.version!==1 || value.prefix!==prefix || value.native_sha256!==current.native_sha256) throw new Error('Invalid selected catalog route.');
      if(value.kind===`${kind}-leaf`) return value;
      if(value.kind!==`${kind}-branch` || prefix.length>=64 || Object.keys(value.children).some(k=>!/^[a-f0-9]$/.test(k))) throw new Error('Invalid selected catalog branch.');
      const next=digest[prefix.length];prefix+=next;current=value.children[next];
    }
    return null;
  }
  async function component(id,signal) {
    const value=(await route(roots.components,id,'component',signal))?.members[id];
    if(!value) throw new Error('Document is not present in this catalog.');
    return value;
  }
  async function* bundles(root=roots.sources,signal) {
    if(!root)return;
    const value=await node(root,signal);
    if(value.kind==='source-leaf')yield value.source;
    else if(value.kind==='source-branch')for(const child of Object.values(value.children))yield* bundles(child,signal);
    else throw new Error('Invalid source partition page.');
  }
  function checkCatalog(catalog) {
    if(catalog && catalog!==info.catalog_id)throw new Error('This link belongs to a different catalog snapshot.');
  }
  async function resolve(id,catalog,signal) {
    checkCatalog(catalog); if(!sourceId(id))throw new Error('Source record is not present in this catalog.');
    return cached(`source:${id}`,async()=>{
      const bundle=(await route(roots.sources,id,'source'))?.source;
      if(!bundle)throw new Error('Source record is not present in this catalog.');
      const ids=await read(bundle.files.filenames,0,bundle.rows,['source_id','document_id']);
      const row=ids.findIndex(value=>value.source_id===id);
      if(row<0 || ids.findIndex((value,index)=>index!==row && value.source_id===id)>=0)throw new Error('Source record is not present uniquely in this catalog.');
      return {bundle,row,documentId:ids[row].document_id};
    },signal);
  }
  async function observations(bundle,signal) {
    if(!bundle.files.observation_index)return {read:async()=>null,page:async(_,{offset=0}={})=>({items:[],total:0,offset,next:null,is_null:true}),matchingSources:async function*(){}};
    return cached(`observations:${bundle.files.observation_index.path}`,async()=>{
      const index=await withVerifiedJson({deadlineMs:30_000,maxBytes:1024*1024},'Observation index',async verified=>{
        const ref=bundle.files.observation_index;valid(ref,['observation_index.json']);
        return verified(fetcher,url(ref.path),ref.sha256,ref.bytes,'observation index');
      });
      if(index.references.rows!==bundle.rows)throw new Error('Observation partition counts disagree.');
      // Each reader's decoded block keys are local to its source partition.
      const prefix=`observations:${bundle.files.observation_index.path}:`;
      const cache={get stats(){return decoded.stats;},get:key=>decoded.get(prefix+key),set:(key,value,size)=>decoded.set(prefix+key,value,size)};
      return observationReader(index,ranged(bundle.files.observations),ranged(bundle.files.observation_rows),{metrics,cache});
    },signal);
  }
  async function technical(id,catalog,signal,full=false) {
    const {bundle,row}=await resolve(id,catalog,signal), fields=info.fields.filter(k=>k!=='source_occurrences'), record={};
    for(let offset=0;offset<fields.length;offset+=8)Object.assign(record,(await read(bundle.files.filenames,row,row+1,fields.slice(offset,offset+8),signal))[0]);
    if(full && info.fields.includes('source_occurrences'))record.source_occurrences=await(await observations(bundle,signal)).read(row,signal);
    const output=Object.fromEntries(info.fields.filter(k=>full || k!=='source_occurrences').map(k=>[k,record[k]]));
    if(recovery.sources.has(id))output.recovery=recovery.sources.get(id);
    return output;
  }
  async function observationPage(id,catalog,query={},signal) {
    const {bundle,row}=await resolve(id,catalog,signal);
    return (await observations(bundle,signal)).page(row,{offset:positiveInteger(query.offset,0),limit:positiveInteger(query.limit,20,100),...(query.origin?{columns:origins}:{})},signal);
  }
  async function technicalOrigin(id,catalog,signal) {
    const {bundle,row}=await resolve(id,catalog,signal);
    return (await read(bundle.files.details,row,row+1,['source_url','recovered_source_url',...origins].filter(k=>info.fields.includes(k)),signal))[0];
  }
  async function* memberIds(entry,signal) {
    async function* walk(ref) {
      const value=await node(ref,signal);
      if(value.kind==='member-leaf' && value.ids.length===ref.rows && value.ids.length<=64)yield*value.ids;
      else if(value.kind==='member-branch' && value.children.length<=16 && value.children.reduce((n,c)=>n+c.rows,0)===ref.rows)for(const child of value.children)yield*walk(child);
      else throw new Error('Invalid stable document membership.');
    }
    let count=0;
    for await(const id of entry.members.ids ?? walk(entry.members.root)) {if(!sourceId(id))throw new Error('Invalid stable source member.');count++;yield id;}
    if(count!==entry.source_rows || count!==entry.members.rows)throw new Error('Document membership count differs.');
  }
  async function browseNode(ref,signal) {
    const value=await node(ref,signal); let rows,first,last,height,flags={};
    if(value.kind==='browse-leaf' && value.records.length>0 && value.records.length<=64) {
      const keys=value.records.map(key);if(keys.some((k,i)=>i && compare(keys[i-1],k)>=0))throw new Error('Invalid browse row order.');
      rows=keys.length;first=keys[0];last=keys.at(-1);height=0;
      for(const row of value.records)flags[row._flags??0]=(flags[row._flags??0]||0)+1;
    }else if(value.kind==='browse-branch' && value.children.length>0 && value.children.length<=16) {
      const children=value.children;
      if(children.some((c,i)=>i && (compare(children[i-1].last,c.first)>=0 || c.height!==children[0].height)))throw new Error('Invalid browse child order.');
      rows=children.reduce((n,c)=>n+c.rows,0);first=children[0].first;last=children.at(-1).last;height=children[0].height+1;
      for(const child of children)for(const [flag,count]of Object.entries(child.flags))flags[flag]=(flags[flag]||0)+count;
    }else throw new Error('Invalid browse page.');
    if(!same({rows,first,last,height,flags},{rows:ref.rows,first:ref.first,last:ref.last,height:ref.height,flags:ref.flags}))throw new Error('Browse page count or bounds differ.');
    return value;
  }
  async function* browseRows(ref=roots.browse,signal,offset=0,limit=Infinity) {
    if(!ref || !limit)return;
    const value=await browseNode(ref,signal);
    if(value.kind==='browse-leaf')yield*value.records.slice(offset,Number.isFinite(limit)?offset+limit:undefined);
    else for(const child of value.children) {
      if(offset>=child.rows){offset-=child.rows;continue;}
      const take=Math.min(limit,child.rows-offset);yield* browseRows(child,signal,offset,take);limit-=take;offset=0;if(!limit)break;
    }
  }
  const flaggedCount = (ref,accept) => Object.entries(ref?.flags??{}).reduce((sum,[flag,count])=>sum+(accept(Number(flag))?count:0),0);
  async function* flaggedRows(ref,accept,offset,limit,signal) {
    if(!ref||!limit)return;
    const value=await browseNode(ref,signal);
    if(value.kind==='browse-leaf')yield*value.records.filter(row=>accept(row._flags)).slice(offset,offset+limit);
    else for(const child of value.children) {
      const count=flaggedCount(child,accept);if(offset>=count){offset-=count;continue;}
      const take=Math.min(limit,count-offset);yield*flaggedRows(child,accept,offset,take,signal);limit-=take;offset=0;if(!limit)break;
    }
  }
  async function document(id,entry,signal) {
    let current=roots.browse;
    while(current) {
      const value=await browseNode(current,signal);
      if(value.kind==='browse-leaf') {const row=value.records.find(row=>row.document_id===id);if(row)return structuredClone(row);break;}
      current=value.children.find(child=>compare(child.first,entry.key)<=0 && compare(entry.key,child.last)<=0);
    }
    throw new Error('Document browse row differs from selected membership.');
  }
  function present(row,reviewed) {
    const output=structuredClone(row), flag=output._flags;delete output._flags;
    output._row=output.source_id;output.api_reference=flag&16?apiReference(output.source_url):null;output.video_reference=flag&32?videoReference(output.source_url):null;
    const recovered=recovery.groups.get(output.document_id);
    if(recovered)Object.assign(output,{retained:true,recovery:recovered[0],recoveries:recovered});
    const review=reviewed && reviews.groups.get(output.document_id);
    if(review){output._review_status=review.status;if(review.status==='candidate_applied'){output.catalog_document_kind=output.document_kind;Object.assign(output,structuredClone(review.selected));}}
    return output;
  }
  async function search(query,signal) {
    signal?.throwIfAborted();const reviewed=reviewedMode(query,info), limit=positiveInteger(query.limit,50,100), requested=positiveInteger(query.page);
    let field=query.field||'filename';if(field==='publication_code_code'&&!info.fields.includes(field))field='publication_type';
    if(!info.fields.includes(field))throw new Error('Unknown search field.');
    if(!['','yes','no'].includes(query.retained||'')||!['','all','capture-records'].includes(query.scope||''))throw new Error('Unknown catalog filter.');
    const selectedFilters=filters.filter(k=>query[k]&&query[k]!=='__null__');
    for(const name of selectedFilters)if(!(info.review_facets?.[name]||info.facets[name]).includes(query[name]))throw new Error(`Unknown ${name} filter.`);
    const needle=(query.q||'').slice(0,2000).toLowerCase(); let matches=null;
    if(needle || selectedFilters.length) {
      matches=new Set();const stream=needle&&field==='source_occurrences';
      const columns=[...new Set(['source_id','document_id',...selectedFilters,...(needle&&!stream?[field,...(field==='filename'&&info.fields.includes('recovered_filename')?['recovered_filename']:[])]:[])])];
      for await(const bundle of bundles(roots.sources,signal)) {
        let observed=null;if(stream){observed=new Set();for await(const row of(await observations(bundle,signal)).matchingSources(needle,signal))observed.add(row);}
        // One selected physical source partition at a time; no full source columns.
        const rows=await read(bundle.files.filenames,0,bundle.rows,columns,signal);
        for(const [index,row]of rows.entries()) {
          metrics.sourceScanVisits++;
          const review=reviewed&&reviews.sources.get(row.source_id);
          const value=name=>review?.status==='candidate_applied'&&name in review.selected?review.selected[name]:row[name];
          if((!needle || (stream?observed.has(index):text(value(field)).includes(needle)||field==='filename'&&text(row.recovered_filename).includes(needle))) &&
              selectedFilters.every(k=>values(value(k)).some(v=>(k==='format'?v.toLowerCase():v)===query[k])))matches.add(row.document_id);
        }
        await yieldToMessages(signal,metrics);
      }
    }
    if(!matches && !(query.retained && recovery.groups.size) && !(reviewed && ['document_kind','document_family'].some(k=>query[k]==='__null__'))) {
      const accept=flag=>(!query.retained || !!(flag&1)===(query.retained==='yes')) &&
        (query.scope==='all' || (query.scope==='capture-records'?!(flag&2):!!(flag&2))) &&
        (query.document_kind!=='__null__'||!!(flag&4)) && (query.document_family!=='__null__'||!!(flag&8));
      const total=flaggedCount(roots.browse,accept),pages=Math.max(1,Math.ceil(total/limit)),page=Math.min(requested,pages),rows=[];
      for await(const row of flaggedRows(roots.browse,accept,(page-1)*limit,limit,signal))rows.push(present(row,reviewed));
      return {rows,total,page,pages,limit};
    }
    const wanted=(requested-1)*limit;let total=0,chosen=[],last=[];
    for await(const row of browseRows(roots.browse,signal)) {
      metrics.groupScanVisits++;if(metrics.groupScanVisits%2048===0)await yieldToMessages(signal,metrics);
      const rendered=present(row,reviewed),flag=row._flags;
      if(matches&&!matches.has(row.document_id)||query.retained&&rendered.retained!==(query.retained==='yes')||
          !query.scope&&!(flag&2)||query.scope==='capture-records'&&(flag&2)||
          ['document_kind','document_family'].some(k=>query[k]==='__null__'&&rendered[k]?.length))continue;
      if(total%limit===0)last=[];last.push(rendered);if(total>=wanted&&total<wanted+limit)chosen.push(rendered);total++;
    }
    const pages=Math.max(1,Math.ceil(total/limit)),page=Math.min(requested,pages);if(page!==requested)chosen=last;
    return {rows:chosen,total,page,pages,limit};
  }
  async function detail(id,catalog,signal) {
    const {bundle,row}=await resolve(id,catalog,signal);
    const data=(await read(bundle.files.details,row,row+1,undefined,signal))[0];
    const value=decodeDetailRecord(data);
    if(recovery.sources.has(id))value.record.recovery=recovery.sources.get(id);
    return value;
  }
  async function entryOrigin(id,catalog,signal,known) {
    const record=known?.record??await technicalOrigin(id,catalog,signal), part=await observationPage(id,catalog,{limit:20,origin:true},signal);
    const origin=sourceContext({...record,source_occurrences:part.items.filter(Boolean)});
    const member=known?.member??await component((await resolve(id,catalog,signal)).documentId,signal);
    let preferred=origin;
    if(member.source_id!==id){const canonical=await technicalOrigin(member.source_id,catalog,signal), evidence=await observationPage(member.source_id,catalog,{limit:20,origin:true},signal);preferred=sourceContext({...canonical,source_occurrences:evidence.items.filter(Boolean)});}
    return {origin_pending:false,origin,document_origin:{redirects:preferred.redirects},observation_count:part.total,origin_next:part.next};
  }
  async function entry(id,catalog,signal,query={}) {
    const value=await detail(id,catalog,signal),{record}=value,documentId=(await resolve(id,catalog,signal)).documentId,member=await component(documentId,signal),sources=[],bodies=[];
    for await(const source of memberIds(member,signal)) {
      const located=await resolve(source,catalog,signal), row=(await read(located.bundle.files.details,located.row,located.row+1,['filename','source_url','source_id','body_key','format','record_role','fact_alternatives'],signal))[0];
      row.record_role=row.fact_alternatives?.find(item=>item.field==='record_role')?.values??(row.record_role==null?null:[row.record_role]);delete row.fact_alternatives;
      bodies.push(row.body_key);row.retained=row.body_key!=null;delete row.body_key;
      if(recovery.sources.has(source))Object.assign(row,{retained:true,recovery:recovery.sources.get(source)});sources.push(row);
    }
    const doc=present(await document(documentId,member,signal),false),recovered=recovery.groups.get(documentId);
    const context=query.deferOrigin?{origin_pending:true,origin:sourceContext(record),document_origin:{redirects:[]}}:await entryOrigin(id,catalog,signal,{record,member});
    return {...value,document:doc,filename:doc.filename,sources,catalog_id:info.catalog_id,api_reference:apiReference(record.source_url),video_reference:videoReference(record.source_url),
      ...(recovered?{recovery:recovered[0],recoveries:recovered}:{}),...context,record_complete:false,reading:null,saved_file_available:false,saved_file_url:savedCopyUrl(record,recovered?.[0],publication.url),published_only:true,
      sources_share_saved_file:!!bodies[0]&&bodies.every(v=>v===bodies[0])};
  }
  async function documentRecord(id,catalog,signal) {
    const {documentId}=await resolve(id,catalog,signal),member=await component(documentId,signal);
    // A physical document asset can be shared with unselected historical members.
    // Only the exact current logical member escapes this bounded read.
    const rows=await read(member.document_file,0,member.document_file.rows,undefined,signal);
    const selected=rows.filter(row=>row.document_id===documentId);
    if(selected.length!==1)throw new Error('Document is not present uniquely in its selected partition.');
    return Object.fromEntries(info.document_fields.map(name=>[name,selected[0][name]??null]));
  }
  async function review(id,catalog,signal,withdrawn=false) {
    if(info.review_error)throw new Error(info.review_error);if(!info.complete_body_reviews)throw new Error('Document reviews are not configured.');
    await resolve(id,catalog,signal);const value=reviews.sources.get(id);return value?structuredClone({...value,status:withdrawn?'withdrawn':value.status,selected:withdrawn?value.baseline:value.selected}):{status:'no_review'};
  }
  return {info:{...info,recovery_sha256:recoveryDescriptor?.sha256,downloads:{catalog:publication.url,recoveries:recoveryDescriptor?.url},published_at:manifest.published_at},
    diagnostics:()=>({...metrics,compressed:compressed.stats,decoded:decoded.stats}),search,entry,entryOrigin,technical,technicalOrigin,observationPage,documentRecord,review,sourceContext};
}
