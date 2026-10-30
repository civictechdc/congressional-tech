/** The release reader is shared by the worker, site and publish canary. */
import {parquetMetadataAsync, parquetReadObjects} from 'hyparquet';
import {parquetReadColumn} from 'hyparquet/src/read.js';
import {compressors} from 'hyparquet-compressors';
import readerLimits from '../../../../../../model/registries/reader-limits.json' with {type:'json'};
import {awaitShared, byteCache, retainedBytes} from './cache.ts';
import {withVerifiedBytes} from './startup.ts';
import {rangeFile} from './range-file.ts';
import {yieldToMessages, scanBatchRows} from './cooperative.ts';
import {createArchiveEntities} from './archive-entities.ts';

const hex = (value: Uint8Array) => [...value].map(v=>v.toString(16).padStart(2,'0')).join('');
const digest = async (value: Uint8Array) => hex(new Uint8Array(await crypto.subtle.digest('SHA-256', value)));
const utf8 = new TextEncoder();
const date = (value: any) => value instanceof Date ? value.toISOString().slice(0,10) : value == null ? null : String(value).slice(0,10);
const fields = (metadata: any) => {
  const names: string[] = []; let cursor=1;
  const skip=()=>{const item=metadata.schema[cursor++];for(let i=0;i<(item.num_children??0);i++)skip();};
  for(let i=0;i<metadata.schema[0].num_children;i++){names.push(metadata.schema[cursor].name);skip();}
  return names;
};
export const facetFields = ['document_kind','document_family','committee_keys','chambers','congress','format','saved_kind','meeting_keys'] as const;
const arrayFields = new Set(['document_kind','document_family','committee_keys','chambers','meeting_keys','measure_keys','bioguide_ids','witness_keys','version_keys']);

export function lookupUrl(value: string): string {
  const validated = new URL(value);
  if (!/^https?:$/.test(validated.protocol) || validated.username || validated.password) throw new Error('Enter a public HTTP or HTTPS address.');
  // WHATWG URL resolves dot segments and punycodes hosts; the fixed release key does neither.
  const match = /^([a-zA-Z][a-zA-Z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(\?[^#]*)?(?:#.*)?$/.exec(value);
  if (!match || !match[2]) throw new Error('Enter an absolute public address.');
  const scheme = match[1].toLowerCase();
  let host = match[2].toLowerCase().replace(/^www\./, '');
  if (scheme === 'http') host = host.replace(/:80$/, '');
  if (scheme === 'https') host = host.replace(/:443$/, '');
  return host + match[3].replace(/\/$/, '') + (match[4] ?? '');
}

/** Keep decoded list columns, never a retained catalog of row objects. */
function column(values: any[], isArray: boolean) {
  if (isArray || values.some(value => typeof value === 'string')) {
    const dictionary: any[] = [null], lookup = new Map<any, number>([[null, 0]]);
    const code = (value: any) => { value ??= null; let id = lookup.get(value); if (id === undefined) { id = dictionary.length; dictionary.push(value); lookup.set(value, id); } return id; };
    if (isArray) {
      const offsets = new Uint32Array(values.length + 1); let length = 0;
      for (let i = 0; i < values.length; i++) { offsets[i] = length; length += (values[i] ?? []).length; } offsets[values.length] = length;
      const codes = new Uint32Array(length); let cursor = 0;
      for (const row of values) for (const value of row ?? []) codes[cursor++] = code(value);lookup.clear();
      return { get: (i: number) => Array.from(codes.subarray(offsets[i], offsets[i + 1]), id => dictionary[id]),
        matches: (i: number, wanted: any[]) => { for (let j = offsets[i]; j < offsets[i + 1]; j++) if (wanted.includes(dictionary[codes[j]])) return true; return false; },
        bytes: codes.byteLength + offsets.byteLength + retainedBytes(dictionary) };
    }
    const codes = Uint32Array.from(values, code);lookup.clear();
    return { get: (i: number) => dictionary[codes[i]], matches: (i: number, wanted: any[]) => wanted.includes(dictionary[codes[i]]), bytes: codes.byteLength + retainedBytes(dictionary) };
  }
  if(values.every(value=>typeof value==='boolean')){const codes=Uint8Array.from(values,Number);return {get:(i: number)=>Boolean(codes[i]),matches:(i: number,wanted:any[])=>wanted.includes(Boolean(codes[i])),bytes:codes.byteLength};}
  const dates = values.some(value => value instanceof Date);
  const packed = Float64Array.from(values, value => value == null ? NaN : Number(value));
  const get = (i: number) => Number.isNaN(packed[i]) ? null : dates ? new Date(packed[i]) : packed[i];
  return { get, packed, matches: (i: number, wanted: any[]) => { const v = get(i); return v != null && (wanted.includes(v) || wanted.includes(String(v))); }, bytes: packed.byteLength };
}

export async function openArchive(pointerUrl: string, options: any = {}) {
  const fetcher=options.fetcher??fetch, heapBytes=options.heapBytes??256*1024*1024;
  options.signal?.throwIfAborted();
  const metrics={rangeRequests:0,rangeBytes:0,decodedBytes:0,decodedPeak:0,listColumns:0};
  const retained={entries:new Map<string,any>(),bytes:0,maxBytes:options.indexBytes??32*1024*1024};
  const compressed=byteCache(options.cacheBytes??48*1024*1024,options.cacheBytes??48*1024*1024);
  const pointer=async()=>{
    const response=await fetcher(pointerUrl,{cache:'no-store', signal:options.signal});
    if(!response.ok)throw new Error('Could not read the archive pointer.');
    const value=await response.json();
    if(!/^[a-f0-9]{64}$/.test(value.release_id))throw new Error('Invalid archive release identity.');
    return value;
  };
  const selected=options.releaseId ? {release_id:options.releaseId} : await pointer(), releaseId=selected.release_id;
  if(!/^[a-f0-9]{64}$/.test(releaseId))throw new Error('Invalid archive candidate identity.');
  const base=new URL(`releases/${releaseId}/`,pointerUrl);
  let staleChecked=false;
  const immutableFetch=async(url: string,init: any={})=>{
    const response=await fetcher(url,{...init,signal:options.signal && init.signal ? AbortSignal.any([options.signal,init.signal]) : options.signal??init.signal});
    if(response.status===404){
      if(!staleChecked){staleChecked=true;const latest=await pointer();
        if(latest.release_id!==releaseId){options.reload?.(latest.release_id);throw new Error('Archive release changed; reload the archive.');}}
      throw new Error('Archive file not found.');
    }
    return response;
  };
  const response=await immutableFetch(new URL('manifest.json',base).href);
  if(!response.ok)throw new Error('Could not read the archive manifest.');
  const manifest=await response.json();
  if(!Array.isArray(manifest.files))throw new Error('Invalid archive manifest.');
  // v1 is the first release format. v0 is accepted only with the same required
  // columns; future revisions must add an explicit previous-version decoder.
  if(![0,1].includes(manifest.schema_version))throw new Error('Unsupported archive schema version.');
  const files=new Map<string,any>();
  for(const item of manifest.files){
    if(!/^(?:[a-z_]+|(?:detail|sources)-[0-9]{5})\.(parquet|json)$/.test(item.name)||files.has(item.name)||!Number.isSafeInteger(item.size)||item.size<0||!Number.isSafeInteger(item.rows)||item.rows<0||!/^[a-f0-9]{64}$/.test(item.sha256))throw new Error('Invalid archive file descriptor.');
    if(item.shard!=null){
      const range=item.row_range;
      if(!['detail','sources'].includes(item.shard)||!new RegExp('^'+item.shard+'-[0-9]{5}[.]parquet$').test(item.name)||!Array.isArray(range)||range.length!==2||!range.every(Number.isSafeInteger)||range[0]<0||range[1]<=range[0]||range[1]-range[0]!==item.rows)throw new Error('Invalid archive shard range.');
    }else if(item.row_range!=null||/-[0-9]{5}[.]parquet$/.test(item.name))throw new Error('Invalid archive shard descriptor.');
    files.set(item.name,item);
  }
  const shards=new Map<string,any[]>();
  for(const descriptor of files.values())if(descriptor.shard){const group=shards.get(descriptor.shard)??[];group.push(descriptor);shards.set(descriptor.shard,group);}
  for(const [name,group] of shards){
    group.sort((a,b)=>a.row_range[0]-b.row_range[0]);let end=0;
    if(files.has(name+'.parquet'))throw new Error('Ambiguous archive shards.');
    for(const item of group){if(item.row_range[0]!==end)throw new Error('Archive shard ranges contain a gap or overlap.');end=item.row_range[1];}
  }
  for(const name of ['list.parquet','detail.parquet','links.parquet','urls.parquet','sources.parquet','recoveries.parquet','url_state.parquet','schema.json','capture_scope.json'])if(!files.has(name)&&!shards.has(name.replace('.parquet','')))throw new Error(`Required archive file is missing: ${name}`);
  const identity=[manifest.schema_version,manifest.files.map((f: any)=>[f.name,f.sha256,f.size,f.rows])];
  if(manifest.release_id!==releaseId||await digest(utf8.encode(JSON.stringify(identity)))!==releaseId)throw new Error('Archive release identity failed verification.');
  const verified=async(name: string)=>{
    const descriptor=files.get(name);if(!descriptor)throw new Error(`Archive file not found: ${name}`);
    return withVerifiedBytes({deadlineMs:30_000,maxBytes:heapBytes},'Archive bytes',
      read=>read(immutableFetch,new URL(name,base).href,descriptor.sha256,descriptor.size,name));
  };
  const tables=new Map<string,Promise<any>>();
  async function table(name: string, whole=false){
    if(!tables.has(name)){const pending=(async()=>{
      const descriptor=files.get(name);if(!descriptor)throw new Error(`Archive file not found: ${name}`);
      let file,transport;
      if(whole){const bytes=await verified(name);file={byteLength:bytes.byteLength,slice:async(start: number,end: number)=>bytes.slice(start,end).buffer};}
      else {transport=rangeFile(new URL(name,base).href,descriptor.size,immutableFetch,compressed,metrics,retained);file=transport.file();}
      const metadata=await parquetMetadataAsync(file);
      if(transport){
        const ranges:number[][]=[];
        for(const group of metadata.row_groups)for(const leaf of group.columns){
          for(const prefix of ['offset_index','column_index'])if(leaf[prefix+'_offset']!=null&&leaf[prefix+'_length'])ranges.push([Number(leaf[prefix+'_offset']),Number(leaf[prefix+'_offset'])+leaf[prefix+'_length']]);
          const column=leaf.meta_data;
          if(column?.dictionary_page_offset!=null)ranges.push([Number(column.dictionary_page_offset),Number(column.data_page_offset)]);
        }
        transport.retain(ranges);
      }
      if(Number(metadata.num_rows)!==descriptor.rows)throw new Error('Archive row count failed verification.');
      return {file,metadata,names:fields(metadata)};
    })();tables.set(name,pending);pending.catch(()=>{if(tables.get(name)===pending)tables.delete(name);});}
    return tables.get(name);
  }
  const list=await table('list.parquet',true), columns=new Map<string,any>();
  const count=Number(list.metadata.num_rows);
  if(!count)throw new Error('The archive is empty.');
  if(shards.has('detail')&&shards.get('detail')!.at(-1).row_range[1]!==count)throw new Error('Archive detail shards do not cover the list.');
  for(const name of ['filename','title','hidden','format','document_date','first_captured','date_kind','saved_kind',...arrayFields])if(!list.names.includes(name))throw new Error(`Archive list is missing ${name}.`);
  for(const name of list.names){
    const values=await parquetReadColumn({...list,columns:[name],compressors});
    if(values.length!==count)throw new Error('Archive column row count failed verification.');
    const packed=column(values,arrayFields.has(name));
    metrics.decodedPeak=Math.max(metrics.decodedPeak,metrics.decodedBytes+packed.bytes+retainedBytes(values));
    if(metrics.decodedPeak>heapBytes)throw new Error('Archive list exceeds the configured heap budget.');
    metrics.decodedBytes+=packed.bytes;metrics.listColumns++;columns.set(name,packed);
  }
  tables.delete('list.parquet'); // The compressed list is released after its columns are packed.
  const value=(name: string,i: number)=>columns.get(name)?.get(i);
  const row=(i: number)=>Object.fromEntries([...columns].map(([name,col])=>[name,col.get(i)]).concat([['list_row',i]]));
  async function read(name: string,start?: number,end?: number,filter?: any){
    const group=shards.get(name.replace('.parquet',''));
    if(group){
      if(start===undefined||end===undefined||filter)throw new Error('Archive shards require a row range.');
      if(start<0||end<start||end>group.at(-1).row_range[1])throw new Error('Invalid archive shard row range.');
      const ranges=group.filter(item=>item.row_range[0]<end&&item.row_range[1]>start);
      return (await Promise.all(ranges.map(async item=>{const input=await table(item.name);return parquetReadObjects({...input,compressors,rowStart:Math.max(start!,item.row_range[0])-item.row_range[0],rowEnd:Math.min(end!,item.row_range[1])-item.row_range[0],useOffsetIndex:true});}))).flat();
    }
    const input=await table(name);
    if(start!==undefined&&(start<0||end===undefined||end<start||end>Number(input.metadata.num_rows)))throw new Error('Invalid archive row range.');
    return parquetReadObjects({...input,compressors,rowStart:start,rowEnd:end,filter,useOffsetIndex:true,usePageIndex:Boolean(filter)});
  }
  const entities=new Map<string,Promise<any[]>>();
  const entity=(name: string)=>{
    if(!files.has(name+'.parquet'))return Promise.resolve([]);
    if(!entities.has(name)){const pending=(async()=>{const input=await table(name+'.parquet',true);try{return await parquetReadObjects({...input,compressors});}finally{tables.delete(name+'.parquet');}})();entities.set(name,pending);pending.catch(()=>{if(entities.get(name)===pending)entities.delete(name);});}
    return entities.get(name)!;
  };
  const checkedRow=(index: number)=>{if(!Number.isSafeInteger(index)||index<0||index>=count)throw new Error('Invalid archive list row.');return row(index);};
  const captures=(a: any,b: any)=>(date(b.first_captured)??'').localeCompare(date(a.first_captured)??'')||a.list_row-b.list_row;
  const parseSearchText=(raw: any)=>{
    const text=String(raw??'').normalize('NFKC').toLowerCase().trim();
    if(!text)return {text:'',billSuffix:'',billCongress:'',codeSearch:false};
    const billMatch=/^(?:(\d{2,3})[\s/-]+)?(h\.?\s*r\.?|s\.?|h\.?\s*res\.?|s\.?\s*res\.?|h\.?\s*j\.?\s*res\.?|s\.?\s*j\.?\s*res\.?|h\.?\s*con\.?\s*res\.?|s\.?\s*con\.?\s*res\.?|p\.?\s*n\.?)[\s.-]*([0-9-]+)$/i.exec(text);
    const billType=billMatch?billMatch[2].replace(/[^a-z]/gi,'').toLowerCase():'';
    const billSuffix=billMatch?`-${billType}-${billMatch[3]}`:'';
    const billCongress=billMatch?.[1]??'';
    const codeSearch=Boolean(billSuffix||(/^[0-9a-z_-]+$/.test(text)&&/\d/.test(text)));
    return {text,billSuffix,billCongress,codeSearch};
  };
  const matches=(i: number,query: any,parsed: ReturnType<typeof parseSearchText>,allowedRows: Set<number>|null=null)=>{
    if(allowedRows!==null&&!allowedRows.has(i))return false;
    if(!query.includeHidden&&value('hidden',i))return false;
    if(parsed.text){
      const inLabel=`${value('filename',i)??''} ${value('title',i)??''}`.normalize('NFKC').toLowerCase().includes(parsed.text);
      if(!inLabel){
        let inCodes=false;
        if(parsed.codeSearch){
          const measures:string[]=value('measure_keys',i)??[];
          if(parsed.billSuffix){
            const target=parsed.billCongress?`${parsed.billCongress}${parsed.billSuffix}`:parsed.billSuffix;
            inCodes=measures.some(m=>parsed.billCongress?String(m).toLowerCase()===target:String(m).toLowerCase().endsWith(target));
          }
          if(!inCodes){
            inCodes=measures.some(m=>String(m).toLowerCase().includes(parsed.text))
              ||(value('meeting_keys',i)??[]).some((m:any)=>String(m).toLowerCase()===parsed.text)
              ||(value('committee_keys',i)??[]).some((c:any)=>String(c).toLowerCase()===parsed.text)
              ||(value('bioguide_ids',i)??[]).some((b:any)=>String(b).toLowerCase()===parsed.text)
              ||(value('witness_keys',i)??[]).some((w:any)=>String(w).toLowerCase().includes(parsed.text));
          }
        }
        if(!inCodes)return false;
      }
    }
    for(const [name,wanted] of Object.entries(query) as [string,any][]){
      if(columns.has(name)&&Array.isArray(wanted)&&wanted.length&&!columns.get(name).matches(i,wanted))return false;
    }
    return true;
  };
  const maxPlausibleDateEpoch=1798761599000; // 2026-12-31T23:59:59Z
  const dateRank=(packed: Float64Array,i: number)=>{
    const v=packed[i];
    if(Number.isNaN(v))return -Infinity;
    return v<=maxPlausibleDateEpoch?v:-1e15+v*1e-6;
  };
  const entry=async(index: number,signal?: AbortSignal)=>{
    signal?.throwIfAborted();
    if(!Number.isSafeInteger(index)||index<0||index>=count)throw new Error('Archive document not found.');
    if(!shards.has('sources')&&files.has('sources.parquet'))void table('sources.parquet').catch(()=>{});
    const [detail]=await awaitShared(read('detail.parquet',index,index+1),signal);
    if(!detail)throw new Error('Archive detail not found.');
    for(const name of ['src_start','src_len','rec_start','rec_len'])if(!Number.isSafeInteger(detail[name])||detail[name]<0)throw new Error('Invalid archive attachment range.');
    const [sources,recoveries]=await awaitShared(Promise.all([
      detail.src_len?read('sources.parquet',detail.src_start,detail.src_start+detail.src_len):[],
      detail.rec_len?read('recoveries.parquet',detail.rec_start,detail.rec_start+detail.rec_len):[]]),signal);
    if(sources.some(item=>item.list_row!==index)||recoveries.some(item=>item.list_row!==index))throw new Error('Archive attachment row failed verification.');
    return {document:row(index),detail,sources,recoveries};
  };
  const resolve=async(key: string)=>{
    if(!/^[a-f0-9]{16}$/.test(key))throw new Error('Invalid archive link key.');
    const binary=Uint8Array.from(key.match(/../g)!,v=>parseInt(v,16));
    const rows=await read('links.parquet',undefined,undefined,{link_key:{$eq:binary}});
    if(rows.length>1)throw new Error('Archive link key is not unique.');
    if(rows.length)checkedRow(rows[0].list_row);return rows[0]?.list_row??null;
  };
  const versions=async(index: number,signal?: AbortSignal)=>{
    checkedRow(index);const keys=value('version_keys',index)??[];if(!keys.length)return [];
    const indexes:number[]=[];
    for(let i=0;i<count;i++){if(i%scanBatchRows===0)await yieldToMessages(signal);if(columns.get('version_keys').matches(i,keys))indexes.push(i);}
    // One O(N) scan, then O(V log V) ordering of this address's versions.
    return indexes.map(row).sort(captures);
  };
  const entityStore=createArchiveEntities({count,files,columns,value,row,entity,resolve,entry,versions});

  const reader={releaseId,manifest,metrics,count,
    has:(name: string)=>files.has(name+'.parquet')||shards.has(name),
    async search(rawQuery: any={},signal?: AbortSignal){
      signal?.throwIfAborted();const offset=rawQuery.offset??0,limit=rawQuery.limit??100;
      if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>1000)throw new Error('Invalid archive page.');
      const {query,allowedRows}=await entityStore.prepareQuery(rawQuery);
      const selected:number[]=[];let total=0;
      const dateSorted=query.sort==='document_date'||query.sort==='first_captured';
      const filenameSorted=query.sort==='filename';
      const datePacked:Float64Array|undefined=dateSorted?columns.get(query.sort)?.packed:undefined;
      const targetCount=offset+limit;
      const alphaRows:Array<{i:number;key:string}>=[],punctRows:Array<{i:number;key:string}>=[],fallbackBlank:number[]=[];
      const parsed=parseSearchText(query.text);
      for(let i=0;i<count;i++){
        if(i%scanBatchRows===0)await yieldToMessages(signal);
        if(!matches(i,query,parsed,allowedRows))continue;
        total++;
        if(datePacked){
          const s=dateRank(datePacked,i);
          if(selected.length<targetCount||s>dateRank(datePacked,selected[selected.length-1])){
            let lo=0,hi=selected.length;
            while(lo<hi){const mid=(lo+hi)>>1;if(s>dateRank(datePacked,selected[mid]))hi=mid;else lo=mid+1;}
            selected.splice(lo,0,i);
            if(selected.length>targetCount)selected.pop();
          }
        }else if(filenameSorted){
          const fname=String(value('filename',i)??'').replace(/^[0-9a-f]{64}\./i,'').trim();
          const key=fname.toLowerCase();
          if(/^[a-z]/i.test(fname)){
            if(alphaRows.length<targetCount||key<alphaRows[alphaRows.length-1].key){
              let lo=0,hi=alphaRows.length;
              while(lo<hi){const mid=(lo+hi)>>1;if(key<alphaRows[mid].key)hi=mid;else lo=mid+1;}
              alphaRows.splice(lo,0,{i,key});
              if(alphaRows.length>targetCount)alphaRows.pop();
            }
          }else if(fname||value('title',i)){
            const tKey=key||String(value('title',i)??'').trim().toLowerCase();
            if(punctRows.length<targetCount)punctRows.push({i,key:tKey});
          }else if(fallbackBlank.length<targetCount){
            fallbackBlank.push(i);
          }
        }else if(total>offset&&selected.length<limit){
          selected.push(i);
        }
      }
      if(filenameSorted){
        for(const item of alphaRows){if(selected.length>=targetCount)break;selected.push(item.i);}
        if(selected.length<targetCount){
          punctRows.sort((a,b)=>a.key.localeCompare(b.key)||a.i-b.i);
          for(const item of punctRows){if(selected.length>=targetCount)break;selected.push(item.i);}
        }
        if(selected.length<targetCount){
          for(const idx of fallbackBlank){if(selected.length>=targetCount)break;selected.push(idx);}
        }
      }
      const pageRows=(dateSorted||filenameSorted)?selected.slice(offset,offset+limit):selected;
      return {total,rows:pageRows.map(row),offset,next:offset+limit<total?offset+limit:null};
    },
    async facets(rawQuery: any={},signal?: AbortSignal){
      const {query,allowedRows}=await entityStore.prepareQuery(rawQuery);
      const result=Object.fromEntries(facetFields.map(name=>[name,Object.create(null)])) as Record<string,Record<string,number>>;
      const parsed=parseSearchText(query.text);
      for(let i=0;i<count;i++){
        if(i%scanBatchRows===0)await yieldToMessages(signal);
        if(!matches(i,query,parsed,allowedRows))continue;
        for(const name of facetFields){const current=value(name,i);for(const item of new Set(Array.isArray(current)?current:[current]))if(item!=null){const key=String(item);result[name][key]=(result[name][key]??0)+1;}}
      }
      return result;
    },
    entry,
    resolve,
    async lookup(url: string){
      const binary=new Uint8Array(await crypto.subtle.digest('SHA-256',utf8.encode('lookup:'+lookupUrl(url)))).slice(0,8);
      const rows=await read('urls.parquet',undefined,undefined,{lookup_key:{$eq:binary}});
      return rows.map(item=>checkedRow(item.list_row));
    },
    async lookupRows(url: string,rawQuery: any={},signal?: AbortSignal){
      signal?.throwIfAborted();const offset=rawQuery.offset??0,limit=rawQuery.limit??100;
      if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>1000)throw new Error('Invalid archive page.');
      const {query,allowedRows}=await entityStore.prepareQuery(rawQuery);
      const emptyText=parseSearchText('');
      const found=(await reader.lookup(url)).filter(item=>matches(item.list_row,query,emptyText,allowedRows));
      if(query.sort==='document_date')found.sort((a,b)=>(date(b.document_date)??'').localeCompare(date(a.document_date)??'')||captures(a,b));else found.sort(captures);
      return {total:found.length,rows:found.slice(offset,offset+limit),offset,next:offset+limit<found.length?offset+limit:null};
    },
    async recoveryRange(start: number,length: number,signal?: AbortSignal){if(!Number.isSafeInteger(start)||start<0||!Number.isSafeInteger(length)||length<0)throw new Error('Invalid recovery row range.');return awaitShared(read('recoveries.parquet',start,start+length),signal);},
    versions,
    meetings:()=>entity('meetings'),
    witnesses:()=>entity('witnesses'),
    recordings:()=>entity('recordings'),
    committees:()=>entity('committees'),
    members:()=>entity('members'),
    rosters:()=>entity('rosters'),
    bills:()=>entity('bills'),
    nominations:()=>entity('nominations'),
    urlState:()=>entity('url_state'),
    getMeeting:entityStore.getMeeting,
    getCommittee:entityStore.getCommittee,
    getWitness:entityStore.getWitness,
    getMember:entityStore.getMember,
    getBill:entityStore.getBill,
    getNomination:entityStore.getNomination,
    getSubject:entityStore.getSubject,
    listEntities:entityStore.listEntities,
    openDocument:entityStore.openDocument,
    schema:async()=>JSON.parse(new TextDecoder().decode(await verified('schema.json'))),
    async openSaved(detail: any){
      const saved=savedCopy(detail,options.rawBase??new URL('/',pointerUrl).href);
      if(saved.compressedDownload||detail.saved_suffix!=='.gz')return saved;
      const response=await fetcher(saved.url);if(!response.ok)throw new Error('Saved copy not found.');
      const alreadyDecoded=response.headers.get('Content-Encoding')?.toLowerCase()==='gzip';
      const stream=detail.saved_suffix==='.gz'&&!alreadyDecoded?response.body!.pipeThrough(new DecompressionStream('gzip')):response.body;
      return {...saved,blob:await new Response(stream,{headers:{'Content-Type':detail.saved_media_type}}).blob()};
    }
  };
  return reader;
}

export function savedCopy(detail: any,rawBase: string){
  const body=typeof detail.saved_body==='string'?detail.saved_body:detail.saved_body instanceof Uint8Array?hex(detail.saved_body):'';
  if(!/^[a-f0-9]{64}$/.test(body)||!['','.gz','.pdf'].includes(detail.saved_suffix))throw new Error('Invalid saved copy identity.');
  return {url:new URL(`bodies/sha256/${body.slice(0,2)}/${body}${detail.saved_suffix}`,rawBase).href,
    compressedDownload:detail.saved_suffix==='.gz'&&detail.saved_bytes>readerLimits.max_unpacked_bytes,mediaType:detail.saved_media_type};
}
const dateSourceLabels:Record<string,string>={
  meeting:'hearing date',
  listed_on:'listing page',
  url:'URL',
  content:'document text',
  publisher:'publisher',
};
export function dateLabels(document: any,detail: any){
  const captured=date(document.first_captured),imported=date(detail.in_archive_since),day=date(document.document_date);
  const rawSource=detail.document_date_source?String(detail.document_date_source).trim():'';
  const source=rawSource&&rawSource!=='filename'?` (${dateSourceLabels[rawSource]??rawSource})`:'';
  return {capture:document.date_kind==='captured'&&captured?`Captured ${captured}`:
    document.date_kind==='import_day'&&imported?`In our archive since ${imported} (original capture date not recorded)`:'Capture date not recorded',
    document:day?`${day}${source}`:null,
    removed:detail.removed_on?`Removed from the hearing page by the committee on ${date(detail.removed_on)}`:null};
}
export function recoveryLabel(kind: string){
  return ({recovered_document:'Recovered document',official_substitute:'Official substitute',
    requested_content_in_official_hearing:'Requested content in an official hearing',
    official_updated_revision_available:'Official updated revision available',
    official_introduced_bill_counterpart:'Official introduced bill counterpart',
    official_recorded_votes_available:'Official recorded votes available',
    requested_content_in_official_report:'Requested content in an official report',
    official_complete_statement_text_available:'Official complete statement text available',
    official_alternate_amendment_available:'Official alternate amendment available',
    requested_content_in_official_amendment_packet:'Requested content in an official amendment packet',
    same_article_publisher_text_available:'Publisher text of the same article available',
    official_public_statement_counterpart:'Official public statement counterpart',
    official_report_counterpart_available:'Official report counterpart available',
    related_final_report_available:'Related final report available',
    full_recording_recovered:'Full recording recovered',
    explicit_retained_download_wrapper:'Retained download wrapper'} as Record<string,string>)[kind]??kind;
}
