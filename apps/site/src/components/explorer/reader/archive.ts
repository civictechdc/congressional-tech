/** The release reader is shared by the worker, site and publish canary. */
import {parquetMetadataAsync, parquetReadObjects} from 'hyparquet';
import {parquetReadColumn} from 'hyparquet/src/read.js';
import {compressors} from 'hyparquet-compressors';
import readerLimits from '../../../../../../model/registries/reader-limits.json' with {type:'json'};
import {byteCache, retainedBytes} from './filenames/cache.ts';
import {withVerifiedBytes} from './filenames/startup.ts';
import {rangeFile} from './range-file.ts';
import {awaitShared} from './filenames/cache.ts';
import {yieldToMessages, scanBatchRows} from './filenames/cooperative.ts';

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
  const invertedColumns=new Map<string,Map<string,number[]>>();
  const rowsForColumn=(colName: string,key: any): number[]=>{
    if(key==null||!columns.has(colName))return [];
    let indexMap=invertedColumns.get(colName);
    if(!indexMap){
      indexMap=new Map<string,number[]>();
      for(let i=0;i<count;i++){
        const current=value(colName,i);
        const items=Array.isArray(current)?current:current!=null?[current]:[];
        for(const item of items){
          if(item==null)continue;
          const k=String(item).toLowerCase();
          let listRows=indexMap.get(k);
          if(!listRows){listRows=[];indexMap.set(k,listRows);}
          listRows.push(i);
        }
      }
      invertedColumns.set(colName,indexMap);
    }
    return indexMap.get(String(key).toLowerCase())??[];
  };
  const uniqueInts=(items: Iterable<any>): number[]=>{
    const seen=new Set<number>();
    for(const item of items){
      const n=Number(item);
      if(Number.isSafeInteger(n)&&n>=0&&n<count)seen.add(n);
    }
    return [...seen].sort((a,b)=>a-b);
  };
  const normalizeMeeting=(m: any)=>{
    const eventKey=String(m.event_id??m.meeting_key??'');
    const transcriptRows=Array.isArray(m.transcripts)?m.transcripts.map((t: any)=>t?.list_row).filter((r: any)=>r!=null):[];
    const listRows=uniqueInts([
      ...(Array.isArray(m.list_rows)?m.list_rows:[]),
      ...rowsForColumn('meeting_keys',eventKey),
      ...transcriptRows,
    ]);
    const committeeObjs=Array.isArray(m.committees)?m.committees.map((c: any)=>typeof c==='string'?{system_code:c,committee_key:c}:{...c,system_code:c.system_code??c.committee_key,committee_key:c.committee_key??c.system_code}):[];
    const committeeKeys=Array.isArray(m.committee_keys)&&m.committee_keys.length
      ?m.committee_keys.map((k: any)=>String(k).toLowerCase())
      :committeeObjs.map((c: any)=>String(c.committee_key??c.system_code??'').toLowerCase()).filter(Boolean);
    const subjectKeys=Array.isArray(m.subject_keys)?m.subject_keys.map(String):Array.isArray(m.measure_keys)?m.measure_keys.map(String):[];
    return {
      ...m,
      event_id:eventKey,
      congress:m.congress!=null?Number(m.congress):null,
      session:m.session!=null?Number(m.session):null,
      meeting_key:eventKey,
      meeting_date:date(m.meeting_date),
      committees:committeeObjs,
      committee_keys:committeeKeys,
      subject_keys:subjectKeys,
      sittings:Array.isArray(m.sittings)?m.sittings:[],
      transcripts:Array.isArray(m.transcripts)?m.transcripts.map((t: any)=>({...t,list_row:t?.list_row!=null?Number(t.list_row):null})):[],
      videos:Array.isArray(m.videos)?m.videos.map((v: any)=>({...v,title:v?.title??v?.name??null,name:v?.name??v?.title??null})):[],
      witnesses:Array.isArray(m.witnesses)?m.witnesses:[],
      list_rows:listRows,
    };
  };
  const normalizeWitness=(w: any)=>{
    const wKey=w.witness_key instanceof Uint8Array?hex(w.witness_key):String(w.witness_key??w.name_key??'');
    const inferredEventId=w.event_id!=null?String(w.event_id):(typeof w.occasion==='string'&&w.occasion.startsWith('meeting:')?w.occasion.slice(8):null);
    const colRows=rowsForColumn('witness_keys',wKey);
    const rawAppearances=Array.isArray(w.appearances)
      ?w.appearances
      :(inferredEventId||w.occasion||w.package_id||w.page_url)
        ?[{
            event_id:inferredEventId,
            occasion:w.occasion??null,
            package_id:w.package_id??null,
            page_url:w.page_url??null,
            position:w.position??null,
            organization:w.organization??null,
            on_behalf_of:w.on_behalf_of??null,
            location:w.location??null,
            panel:w.panel??null,
            panel_order:w.panel_order!=null?Number(w.panel_order):null,
            display_order:w.display_order!=null?Number(w.display_order):null,
            witness_type:w.witness_type??null,
            testified:w.testified??null,
            list_rows:colRows,
          }]
        :[];
    const appearances=rawAppearances.map((a: any)=>({
      ...a,
      event_id:a.event_id!=null?String(a.event_id):null,
      congress:a.congress!=null?Number(a.congress):null,
      panel:a.panel!=null?(typeof a.panel==='number'||/^\d+$/.test(String(a.panel))?Number(a.panel):a.panel):null,
      panel_order:a.panel_order!=null?Number(a.panel_order):(typeof a.panel==='number'||/^\d+$/.test(String(a.panel))?Number(a.panel):null),
      display_order:a.display_order!=null?Number(a.display_order):null,
      meeting_date:date(a.meeting_date),
      list_rows:uniqueInts(Array.isArray(a.list_rows)?a.list_rows:[]),
    }));
    const organizations=Array.isArray(w.organizations)&&w.organizations.length
      ?w.organizations.map(String)
      :[...new Set([w.organization,...appearances.map((a: any)=>a.organization)].filter(Boolean).map(String))];
    const positions=Array.isArray(w.positions)&&w.positions.length
      ?w.positions.map(String)
      :[...new Set([w.position,...appearances.map((a: any)=>a.position)].filter(Boolean).map(String))];
    const listRows=uniqueInts([
      ...(Array.isArray(w.list_rows)?w.list_rows:[]),
      ...colRows,
      ...appearances.flatMap((a: any)=>a.list_rows??[]),
    ]);
    return {
      ...w,
      witness_key:wKey,
      name_key:w.name_key??wKey,
      event_id:inferredEventId,
      panel_order:w.panel_order!=null?Number(w.panel_order):null,
      display_order:w.display_order!=null?Number(w.display_order):null,
      organization:w.organization??organizations[0]??null,
      organizations,
      position:w.position??positions[0]??null,
      positions,
      appearances,
      list_rows:listRows,
    };
  };
  const normalizeRecording=(r: any)=>{
    const rawEventIds=Array.isArray(r.event_ids)?r.event_ids:Array.isArray(r.meeting_keys)?r.meeting_keys:[];
    const eventIds=rawEventIds.map(String);
    const meetingKeys=Array.isArray(r.meeting_keys)?r.meeting_keys.map(String):eventIds;
    const tracks=(Array.isArray(r.tracks)?r.tracks:Array.isArray(r.transcripts)?r.transcripts:[]).map((t: any)=>({
      ...t,
      sha256:t?.sha256??(t?.body instanceof Uint8Array?hex(t.body):typeof t?.body==='string'?t.body:null),
    }));
    return {
      ...r,
      congress:r.congress!=null?Number(r.congress):null,
      duration_s:r.duration_s!=null?Number(r.duration_s):null,
      event_ids:eventIds,
      meeting_keys:meetingKeys,
      tracks,
      transcripts:Array.isArray(r.transcripts)?r.transcripts:tracks,
    };
  };
  const normalizeCommittee=(c: any)=>{
    const key=String(c.committee_key??c.system_code??'').toLowerCase();
    const parentKey=c.parent_key??c.parent_system_code??null;
    const names=(Array.isArray(c.names)?c.names:Array.isArray(c.histories)?c.histories:[]).map((n: any)=>({
      ...n,
      start:date(n.start??n.start_date),
      end:date(n.end??n.end_date),
      start_date:date(n.start_date??n.start),
      end_date:date(n.end_date??n.end),
    }));
    const currentName=String(c.current_name??c.name??names.at(-1)?.name??'');
    const docRows=rowsForColumn('committee_keys',key);
    return {
      ...c,
      committee_key:key,
      system_code:String(c.system_code??key).toLowerCase(),
      parent_key:parentKey?String(parentKey).toLowerCase():null,
      parent_system_code:parentKey?String(parentKey).toLowerCase():null,
      system_codes:Array.isArray(c.system_codes)?c.system_codes.map((s: any)=>String(s).toLowerCase()):[key].filter(Boolean),
      gpo_codes:Array.isArray(c.gpo_codes)?c.gpo_codes:[],
      type:c.type??c.committee_type??null,
      committee_type:c.committee_type??c.type??null,
      current_name:currentName,
      name:String(c.name??currentName),
      names,
      histories:names,
      url:c.url??c.website??null,
      website:c.website??c.url??null,
      subcommittees:Array.isArray(c.subcommittees)?c.subcommittees:[],
      doc_count:c.doc_count!=null?Number(c.doc_count):docRows.length,
      hearing_count:c.hearing_count!=null?Number(c.hearing_count):0,
    };
  };
  const normalizeMember=(m: any)=>{
    const bio=String(m.bioguide_id??'');
    const appearances=Array.isArray(m.appearances)?m.appearances.map((a: any)=>({...a,meeting_date:date(a.meeting_date)})):[];
    const listRows=uniqueInts([
      ...(Array.isArray(m.list_rows)?m.list_rows:[]),
      ...rowsForColumn('bioguide_ids',bio),
      ...appearances.flatMap((a: any)=>Array.isArray(a.list_rows)?a.list_rows:[]),
    ]);
    return {
      ...m,
      bioguide_id:bio,
      terms:Array.isArray(m.terms)?m.terms:[],
      committees:Array.isArray(m.committees)?m.committees:[],
      appearances,
      list_rows:listRows,
    };
  };
  const normalizeRoster=(r: any)=>{
    const key=String(r.committee_key??r.system_code??'').toLowerCase();
    return {
      ...r,
      committee_key:key,
      system_code:key,
      congress:r.congress!=null?Number(r.congress):null,
      role:r.role??r.title??'Member',
      title:r.title??r.role??'Member',
      rank_in_party:r.rank_in_party!=null?Number(r.rank_in_party):r.rank!=null?Number(r.rank):null,
      rank:r.rank!=null?Number(r.rank):r.rank_in_party!=null?Number(r.rank_in_party):null,
      start_date:date(r.start_date),
      end_date:date(r.end_date),
      subcommittee_keys:Array.isArray(r.subcommittee_keys)?r.subcommittee_keys.map((s: any)=>String(s).toLowerCase()):[],
    };
  };
  const normalizeBill=(b: any)=>{
    const subjectKey=String(b.subject_key??b.bill_id??'');
    const votes=Array.isArray(b.votes)?b.votes:Array.isArray(b.floor_votes)?b.floor_votes:[];
    const listRows=uniqueInts([
      ...(Array.isArray(b.list_rows)?b.list_rows:[]),
      ...rowsForColumn('measure_keys',subjectKey),
    ]);
    const activities=Array.isArray(b.committee_activities)?b.committee_activities:[];
    const meetingKeys=Array.isArray(b.meeting_keys)
      ?b.meeting_keys.map(String)
      :[...new Set(activities.flatMap((a: any)=>a.event_id!=null?[String(a.event_id)]:Array.isArray(a.meeting_keys)?a.meeting_keys.map(String):[]))];
    return {
      ...b,
      kind:'bill' as const,
      subject_key:subjectKey,
      bill_id:String(b.bill_id??subjectKey),
      congress:b.congress!=null?Number(b.congress):null,
      bill_number:b.bill_number!=null?Number(b.bill_number):null,
      introduced_date:date(b.introduced_date??b.introduced),
      introduced:date(b.introduced??b.introduced_date),
      latest_action_date:date(b.latest_action_date),
      status:b.status??b.stage??null,
      stage:b.stage??b.status??null,
      subjects:Array.isArray(b.subjects)?b.subjects:[],
      laws:Array.isArray(b.laws)?b.laws:[],
      committees:Array.isArray(b.committees)?b.committees:[],
      committee_activities:activities,
      related_bills:Array.isArray(b.related_bills)?b.related_bills:[],
      cbo_estimates:Array.isArray(b.cbo_estimates)?b.cbo_estimates:[],
      amendments:Array.isArray(b.amendments)?b.amendments:[],
      amendment_count:b.amendment_count!=null?Number(b.amendment_count):(Array.isArray(b.amendments)?b.amendments.length:0),
      votes,
      floor_votes:Array.isArray(b.floor_votes)?b.floor_votes:votes,
      meeting_keys:meetingKeys,
      list_rows:listRows,
    };
  };
  const normalizeNomination=(n: any)=>{
    const subjectKey=String(n.subject_key??n.nomination_id??'');
    const votes=Array.isArray(n.votes)?n.votes:Array.isArray(n.floor_votes)?n.floor_votes:[];
    const transcripts=Array.isArray(n.transcripts)?n.transcripts:[];
    const listRows=uniqueInts([
      ...(Array.isArray(n.list_rows)?n.list_rows:[]),
      ...rowsForColumn('measure_keys',subjectKey),
      ...transcripts.map((t: any)=>t?.list_row).filter((r: any)=>r!=null),
    ]);
    const meetingKeys=Array.isArray(n.meeting_keys)?n.meeting_keys.map(String):[];
    return {
      ...n,
      kind:'nomination' as const,
      subject_key:subjectKey,
      nomination_id:String(n.nomination_id??subjectKey),
      congress:n.congress!=null?Number(n.congress):null,
      received_date:date(n.received_date??n.received),
      received:date(n.received??n.received_date),
      latest_action_date:date(n.latest_action_date),
      nominees:Array.isArray(n.nominees)?n.nominees:[],
      committees:Array.isArray(n.committees)?n.committees:[],
      transcripts,
      votes,
      floor_votes:Array.isArray(n.floor_votes)?n.floor_votes:votes,
      meeting_keys:meetingKeys,
      list_rows:listRows,
    };
  };
  const toFilterList=(val: any): string[]=>{
    if(val==null||val==='')return [];
    if(Array.isArray(val))return val.flatMap(v=>v!=null&&v!==''?[String(v)]:[]);
    return [String(val)];
  };
  const prepareQuery=async(rawQuery: any)=>{
    const query={...rawQuery};
    const committeeWanted=[
      ...toFilterList(query.committee_keys),
      ...toFilterList(query.committee_key),
      ...toFilterList(query.committee),
    ].map(v=>v.toLowerCase());
    if(committeeWanted.length)query.committee_keys=[...new Set(committeeWanted)];
    delete query.committee_key;delete query.committee;

    const meetingWanted=[
      ...toFilterList(query.meeting_keys),
      ...toFilterList(query.event_id),
      ...toFilterList(query.hearing),
      ...toFilterList(query.meeting),
    ];
    delete query.event_id;delete query.hearing;delete query.meeting;

    const subjectWanted=[
      ...toFilterList(query.measure_keys),
      ...toFilterList(query.subject_keys),
      ...toFilterList(query.subject_key),
      ...toFilterList(query.subject),
      ...toFilterList(query.bill),
      ...toFilterList(query.nomination),
    ];
    delete query.subject_keys;delete query.subject_key;delete query.subject;delete query.bill;delete query.nomination;

    const witnessWanted=[
      ...toFilterList(query.witness_keys),
      ...toFilterList(query.witness_key),
      ...toFilterList(query.witness),
    ];
    delete query.witness_keys;delete query.witness_key;delete query.witness;

    const memberWanted=[
      ...toFilterList(query.bioguide_ids),
      ...toFilterList(query.bioguide_id),
      ...toFilterList(query.member),
    ];
    delete query.bioguide_ids;delete query.bioguide_id;delete query.member;

    const entitySets: Set<number>[]=[];
    if(committeeWanted.length){
      const wantedLower=new Set(committeeWanted.map(v=>v.toLowerCase()));
      const rowSet=new Set<number>();
      for(const key of wantedLower)for(const r of rowsForColumn('committee_keys',key))rowSet.add(r);
      if(!rowSet.size&&files.has('meetings.parquet')){
        for(const raw of await entity('meetings')){
          const norm=normalizeMeeting(raw);
          if(norm.committee_keys.some((k: string)=>wantedLower.has(k.toLowerCase()))){
            for(const r of norm.list_rows)rowSet.add(r);
          }
        }
      }
      delete query.committee_keys;
      entitySets.push(rowSet);
    }
    if(meetingWanted.length){
      const wantedLower=new Set(meetingWanted.map(v=>v.toLowerCase()));
      const rowSet=new Set<number>();
      for(const key of wantedLower)for(const r of rowsForColumn('meeting_keys',key))rowSet.add(r);
      if(files.has('meetings.parquet')){
        for(const raw of await entity('meetings')){
          if(wantedLower.has(String(raw.event_id??raw.meeting_key??'').toLowerCase())){
            const norm=normalizeMeeting(raw);
            for(const r of norm.list_rows)rowSet.add(r);
          }
        }
      }
      delete query.meeting_keys;
      entitySets.push(rowSet);
    }
    if(subjectWanted.length){
      const wantedLower=new Set(subjectWanted.map(v=>v.toLowerCase()));
      const rowSet=new Set<number>();
      for(const key of wantedLower)for(const r of rowsForColumn('measure_keys',key))rowSet.add(r);
      if(files.has('bills.parquet')){
        for(const raw of await entity('bills')){
          const key=String(raw.subject_key??raw.bill_id??'').toLowerCase();
          if(wantedLower.has(key))for(const r of normalizeBill(raw).list_rows)rowSet.add(r);
        }
      }
      if(files.has('nominations.parquet')){
        for(const raw of await entity('nominations')){
          const key=String(raw.subject_key??raw.nomination_id??'').toLowerCase();
          const cit=String(raw.citation??'').toLowerCase();
          if(wantedLower.has(key)||(cit&&wantedLower.has(cit)))for(const r of normalizeNomination(raw).list_rows)rowSet.add(r);
        }
      }
      delete query.measure_keys;
      entitySets.push(rowSet);
    }
    if(witnessWanted.length){
      const wantedLower=new Set(witnessWanted.map(v=>v.toLowerCase()));
      const rowSet=new Set<number>();
      for(const key of wantedLower)for(const r of rowsForColumn('witness_keys',key))rowSet.add(r);
      if(files.has('witnesses.parquet')){
        for(const raw of await entity('witnesses')){
          const wk=String(raw.witness_key??'').toLowerCase();
          const nk=String(raw.name_key??'').toLowerCase();
          if(wantedLower.has(wk)||(nk&&wantedLower.has(nk))){
            for(const r of normalizeWitness(raw).list_rows)rowSet.add(r);
          }
        }
      }
      entitySets.push(rowSet);
    }
    if(memberWanted.length){
      const wantedLower=new Set(memberWanted.map(v=>v.toLowerCase()));
      const rowSet=new Set<number>();
      for(const key of wantedLower)for(const r of rowsForColumn('bioguide_ids',key))rowSet.add(r);
      if(files.has('members.parquet')){
        for(const raw of await entity('members')){
          if(wantedLower.has(String(raw.bioguide_id??'').toLowerCase())){
            for(const r of normalizeMember(raw).list_rows)rowSet.add(r);
          }
        }
      }
      if(files.has('witnesses.parquet')){
        for(const raw of await entity('witnesses')){
          if(raw.bioguide_id&&wantedLower.has(String(raw.bioguide_id).toLowerCase())){
            for(const r of normalizeWitness(raw).list_rows)rowSet.add(r);
          }
        }
      }
      entitySets.push(rowSet);
    }
    let allowedRows: Set<number>|null=null;
    for(const set of entitySets){
      if(allowedRows===null)allowedRows=set;
      else allowedRows=new Set([...allowedRows].filter(r=>set.has(r)));
    }
    return {query,allowedRows};
  };
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
  const resolveCommitteeHistoricalName=(committee: any,dateOrCongress?: any): string=>{
    if(!committee)return '';
    const history=Array.isArray(committee.names)?committee.names:Array.isArray(committee.histories)?committee.histories:[];
    if(dateOrCongress!=null&&history.length){
      const raw=String(dateOrCongress).trim();
      if(/^\d{1,3}$/.test(raw)){
        const cong=Number(raw);
        for(const h of history){
          if(h?.congress!=null&&Number(h.congress)===cong&&h.name)return String(h.name);
        }
        const startYear=`${1789+(cong-1)*2}-01-03`,endYear=`${1789+cong*2}-01-03`;
        for(const h of history){
          const s=date(h?.start??h?.start_date),e=date(h?.end??h?.end_date);
          if((!s||s<endYear)&&(!e||e>startYear)&&h?.name)return String(h.name);
        }
      }else{
        const target=date(dateOrCongress);
        if(target){
          for(const h of history){
            const s=date(h?.start??h?.start_date),e=date(h?.end??h?.end_date);
            if((!s||target>=s)&&(!e||target<e)&&h?.name)return String(h.name);
          }
        }
      }
    }
    return String(committee.current_name??committee.name??history.at(-1)?.name??'');
  };
  const reader={releaseId,manifest,metrics,count,
    has:(name: string)=>files.has(name+'.parquet')||shards.has(name),
    async search(rawQuery: any={},signal?: AbortSignal){
      signal?.throwIfAborted();const offset=rawQuery.offset??0,limit=rawQuery.limit??100;
      if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>1000)throw new Error('Invalid archive page.');
      const {query,allowedRows}=await prepareQuery(rawQuery);
      const selected:number[]=[];let total=0;
      const dateSorted=query.sort==='document_date'||query.sort==='first_captured';
      const filenameSorted=query.sort==='filename';
      const datePacked:Float64Array|undefined=dateSorted?columns.get(query.sort)?.packed:undefined;
      const targetCount=offset+limit;
      const fallbackTitled:number[]=[],fallbackBlank:number[]=[];
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
          const fname=String(value('filename',i)??'');
          if(/^[0-9a-z]/i.test(fname)){
            if(selected.length<targetCount)selected.push(i);
          }else if(fname||value('title',i)){
            if(fallbackTitled.length<targetCount)fallbackTitled.push(i);
          }else if(fallbackBlank.length<targetCount){
            fallbackBlank.push(i);
          }
        }else if(total>offset&&selected.length<limit){
          selected.push(i);
        }
      }
      if(filenameSorted&&selected.length<targetCount){
        for(const idx of fallbackTitled){if(selected.length>=targetCount)break;selected.push(idx);}
        for(const idx of fallbackBlank){if(selected.length>=targetCount)break;selected.push(idx);}
      }
      const pageRows=(dateSorted||filenameSorted)?selected.slice(offset,offset+limit):selected;
      return {total,rows:pageRows.map(row),offset,next:offset+limit<total?offset+limit:null};
    },
    async facets(rawQuery: any={},signal?: AbortSignal){
      const {query,allowedRows}=await prepareQuery(rawQuery);
      const result=Object.fromEntries(facetFields.map(name=>[name,Object.create(null)])) as Record<string,Record<string,number>>;
      const parsed=parseSearchText(query.text);
      for(let i=0;i<count;i++){
        if(i%scanBatchRows===0)await yieldToMessages(signal);
        if(!matches(i,query,parsed,allowedRows))continue;
        for(const name of facetFields){const current=value(name,i);for(const item of new Set(Array.isArray(current)?current:[current]))if(item!=null){const key=String(item);result[name][key]=(result[name][key]??0)+1;}}
      }
      return result;
    },
    async entry(index: number,signal?: AbortSignal){
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
    },
    async resolve(key: string){
      if(!/^[a-f0-9]{16}$/.test(key))throw new Error('Invalid archive link key.');
      const binary=Uint8Array.from(key.match(/../g)!,v=>parseInt(v,16));
      const rows=await read('links.parquet',undefined,undefined,{link_key:{$eq:binary}});
      if(rows.length>1)throw new Error('Archive link key is not unique.');
      if(rows.length)checkedRow(rows[0].list_row);return rows[0]?.list_row??null;
    },
    async lookup(url: string){
      const binary=new Uint8Array(await crypto.subtle.digest('SHA-256',utf8.encode('lookup:'+lookupUrl(url)))).slice(0,8);
      const rows=await read('urls.parquet',undefined,undefined,{lookup_key:{$eq:binary}});
      return rows.map(item=>checkedRow(item.list_row));
    },
    async lookupRows(url: string,rawQuery: any={},signal?: AbortSignal){
      signal?.throwIfAborted();const offset=rawQuery.offset??0,limit=rawQuery.limit??100;
      if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(limit)||limit<1||limit>1000)throw new Error('Invalid archive page.');
      const {query,allowedRows}=await prepareQuery(rawQuery);
      const emptyText=parseSearchText('');
      const found=(await reader.lookup(url)).filter(item=>matches(item.list_row,query,emptyText,allowedRows));
      if(query.sort==='document_date')found.sort((a,b)=>(date(b.document_date)??'').localeCompare(date(a.document_date)??'')||captures(a,b));else found.sort(captures);
      return {total:found.length,rows:found.slice(offset,offset+limit),offset,next:offset+limit<found.length?offset+limit:null};
    },
    async recoveryRange(start: number,length: number,signal?: AbortSignal){if(!Number.isSafeInteger(start)||start<0||!Number.isSafeInteger(length)||length<0)throw new Error('Invalid recovery row range.');return awaitShared(read('recoveries.parquet',start,start+length),signal);},
    async versions(index: number,signal?: AbortSignal){
      checkedRow(index);const keys=value('version_keys',index)??[];if(!keys.length)return [];
      const indexes:number[]=[];
      for(let i=0;i<count;i++){if(i%scanBatchRows===0)await yieldToMessages(signal);if(columns.get('version_keys').matches(i,keys))indexes.push(i);}
      // One O(N) scan, then O(V log V) ordering of this address's versions.
      return indexes.map(row).sort(captures);
    },
    meetings:()=>entity('meetings'),
    witnesses:()=>entity('witnesses'),
    recordings:()=>entity('recordings'),
    committees:()=>entity('committees'),
    members:()=>entity('members'),
    rosters:()=>entity('rosters'),
    bills:()=>entity('bills'),
    nominations:()=>entity('nominations'),
    urlState:()=>entity('url_state'),
    async getMeeting(chamberOrEventId: any,maybeEventId?: any,signal?: AbortSignal){
      const actualSignal=maybeEventId instanceof AbortSignal?maybeEventId:signal;
      actualSignal?.throwIfAborted();
      const hasChamber=maybeEventId!==undefined&&!(maybeEventId instanceof AbortSignal);
      const chamberFilter=hasChamber?String(chamberOrEventId??'').trim().toLowerCase():null;
      const eventKey=String(hasChamber?maybeEventId:chamberOrEventId).trim();
      if(!eventKey)return null;
      const [rawMeetings,rawRecordings,rawCommittees,rawWitnesses,rawBills,rawNominations]=await Promise.all([
        entity('meetings'),
        entity('recordings'),
        entity('committees'),
        entity('witnesses'),
        entity('bills'),
        entity('nominations'),
      ]);
      const found=rawMeetings.find((m: any)=>
        String(m.event_id??m.meeting_key??'')===eventKey
        &&(!chamberFilter||String(m.chamber??'').toLowerCase()===chamberFilter));
      const docRows=rowsForColumn('meeting_keys',eventKey);
      if(!found&&!docRows.length)return null;
      const baseMeeting=normalizeMeeting(found??{
        event_id:eventKey,
        meeting_key:eventKey,
        chamber:chamberFilter??(docRows.length?value('chambers',docRows[0])?.[0]??null:null),
        congress:docRows.length?value('congress',docRows[0]):null,
        title:`Hearing ${eventKey}`,
        committee_keys:docRows.length?value('committee_keys',docRows[0])??[]:[],
        subject_keys:docRows.length?value('measure_keys',docRows[0])??[]:[],
        list_rows:docRows,
      });
      const recordings=rawRecordings
        .map(normalizeRecording)
        .filter((r: any)=>r.meeting_keys.includes(eventKey));
      const allVideos=[
        ...recordings,
        ...baseMeeting.videos.filter((v: any)=>!recordings.some((r: any)=>
          (v.video_id&&r.video_id===v.video_id)||(v.url&&r.url===v.url))),
      ];
      const normCommittees=rawCommittees.map(normalizeCommittee);
      const committeeByCode=new Map<string,any>();
      for(const c of normCommittees){
        committeeByCode.set(c.committee_key,c);
        for(const s of c.system_codes)committeeByCode.set(s,c);
      }
      const enrichedCommittees=(baseMeeting.committee_keys.length?baseMeeting.committee_keys:baseMeeting.committees.map((c: any)=>c.committee_key??c.system_code)).map((code: string)=>{
        const lower=String(code??'').toLowerCase();
        const cat=committeeByCode.get(lower);
        const inline=baseMeeting.committees.find((c: any)=>String(c.committee_key??c.system_code??'').toLowerCase()===lower);
        const resolvedName=cat?resolveCommitteeHistoricalName(cat,baseMeeting.meeting_date??baseMeeting.congress):(inline?.name??lower.toUpperCase());
        return {
          ...(cat??{}),
          ...(inline??{}),
          committee_key:lower,
          system_code:lower,
          name:inline?.name||resolvedName,
          resolved_name:resolvedName,
        };
      });
      const normWitnesses=rawWitnesses.map(normalizeWitness);
      const witnessMap=new Map<string,any>();
      for(const w of normWitnesses){
        if(w.witness_key)witnessMap.set(w.witness_key.toLowerCase(),w);
        if(w.name_key)witnessMap.set(String(w.name_key).toLowerCase(),w);
      }
      const witnessesFromTable=normWitnesses.filter((w: any)=>
        w.appearances.some((a: any)=>String(a.event_id??a.meeting_key??'')===eventKey));
      const mergedWitnesses: any[]=[];
      const seenWitnessKeys=new Set<string>();
      for(const inlineW of baseMeeting.witnesses){
        const wKey=String(inlineW.witness_key??inlineW.name_key??inlineW.name??'').toLowerCase();
        const catW=witnessMap.get(wKey);
        const app=catW?.appearances?.find((a: any)=>String(a.event_id??a.meeting_key??'')===eventKey);
        const listRows=uniqueInts([
          ...(Array.isArray(inlineW.list_rows)?inlineW.list_rows:[]),
          ...(Array.isArray(app?.list_rows)?app.list_rows:[]),
          ...(catW?catW.list_rows.filter((r: number)=>(value('meeting_keys',r)??[]).map(String).includes(eventKey)):[]),
        ]);
        if(wKey)seenWitnessKeys.add(wKey);
        if(catW?.witness_key)seenWitnessKeys.add(catW.witness_key.toLowerCase());
        mergedWitnesses.push({
          ...(catW??{}),
          ...inlineW,
          witness_key:inlineW.witness_key??catW?.witness_key??null,
          bioguide_id:inlineW.bioguide_id??catW?.bioguide_id??null,
          organization:inlineW.organization??catW?.organization??null,
          position:inlineW.position??catW?.position??null,
          panel:inlineW.panel??app?.panel??null,
          panel_order:inlineW.panel_order??inlineW.panel??app?.panel??null,
          display_order:inlineW.display_order??null,
          list_rows:listRows,
          documents:listRows.map(row),
        });
      }
      for(const catW of witnessesFromTable){
        if(seenWitnessKeys.has(catW.witness_key.toLowerCase()))continue;
        const app=catW.appearances.find((a: any)=>String(a.event_id??a.meeting_key??'')===eventKey);
        const listRows=uniqueInts([
          ...(Array.isArray(app?.list_rows)?app.list_rows:[]),
          ...catW.list_rows.filter((r: number)=>(value('meeting_keys',r)??[]).map(String).includes(eventKey)),
        ]);
        mergedWitnesses.push({
          ...catW,
          ...(app??{}),
          witness_key:catW.witness_key,
          name:catW.name,
          organization:app?.organization??catW.organization,
          position:app?.position??catW.position,
          panel:app?.panel??catW.panel??null,
          panel_order:app?.panel_order??app?.panel??null,
          list_rows:listRows,
          documents:listRows.map(row),
        });
      }
      mergedWitnesses.sort((a,b)=>{
        const pa=Number(a.panel_order??a.panel??999),pb=Number(b.panel_order??b.panel??999);
        if(Number.isFinite(pa)&&Number.isFinite(pb)&&pa!==pb)return pa-pb;
        const da=Number(a.display_order??999),db=Number(b.display_order??999);
        if(Number.isFinite(da)&&Number.isFinite(db)&&da!==db)return da-db;
        return String(a.name??'').localeCompare(String(b.name??''));
      });
      const allSubjectKeys=[...new Set([
        ...baseMeeting.subject_keys,
        ...baseMeeting.list_rows.flatMap((r: number)=>value('measure_keys',r)??[]),
      ].map(String).filter(Boolean))];
      const billMap=new Map(rawBills.map(normalizeBill).map((b: any)=>[b.subject_key.toLowerCase(),b]));
      const nomMap=new Map(rawNominations.map(normalizeNomination).map((n: any)=>[n.subject_key.toLowerCase(),n]));
      const subjects=allSubjectKeys.map(sk=>{
        const lower=sk.toLowerCase();
        return billMap.get(lower)??nomMap.get(lower)??{
          kind:/^(?:\d+-)?pn-/i.test(sk)?'nomination':'bill',
          subject_key:sk,
          title:null,
          list_rows:rowsForColumn('measure_keys',sk),
        };
      });
      return {
        ...baseMeeting,
        subject_keys:allSubjectKeys,
        subjects,
        committees:enrichedCommittees,
        recordings,
        videos:allVideos,
        witnesses:mergedWitnesses,
        documents:baseMeeting.list_rows.map(row),
      };
    },
    async getCommittee(committeeKey: string,options: any={},signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(committeeKey??'').trim().toLowerCase();
      if(!clean)return null;
      const [rawCommittees,rawRosters,rawMeetings]=await Promise.all([
        entity('committees'),
        entity('rosters'),
        entity('meetings'),
      ]);
      const normCommittees=rawCommittees.map(normalizeCommittee);
      const found=normCommittees.find((c: any)=>
        c.committee_key===clean
        ||c.system_code===clean
        ||String(c.thomas_id??'').toLowerCase()===clean
        ||String(c.house_committee_id??'').toLowerCase()===clean
        ||String(c.senate_code??'').toLowerCase()===clean
        ||c.system_codes.includes(clean));
      const canonicalKey=found?.committee_key??clean;
      const subcommittees=normCommittees.filter((c: any)=>c.parent_key===canonicalKey&&c.committee_key!==canonicalKey);
      const explicitSubs=Array.isArray(found?.subcommittees)&&found.subcommittees.length
        ?found.subcommittees
        :subcommittees;
      const relatedKeys=new Set([canonicalKey,...subcommittees.map((s: any)=>s.committee_key)]);
      const docRows=uniqueInts([...relatedKeys].flatMap(k=>rowsForColumn('committee_keys',k)));
      const normMeetings=rawMeetings.map(normalizeMeeting).filter((m: any)=>
        m.committee_keys.some((k: string)=>relatedKeys.has(k.toLowerCase())));
      normMeetings.sort((a: any,b: any)=>(b.meeting_date??'').localeCompare(a.meeting_date??'')||String(b.event_id).localeCompare(String(a.event_id)));
      const normRosters=rawRosters.map(normalizeRoster).filter((r: any)=>
        r.committee_key===canonicalKey||r.subcommittee_keys.includes(canonicalKey));
      normRosters.sort((a: any,b: any)=>
        (Number(b.congress??0)-Number(a.congress??0))
        ||((a.majority===true?0:a.majority===false?1:2)-(b.majority===true?0:b.majority===false?1:2))
        ||((a.rank_in_party??999)-(b.rank_in_party??999))
        ||String(a.name??'').localeCompare(String(b.name??'')));
      const congresses=[...new Set(normRosters.map((r: any)=>r.congress).filter((c: any)=>c!=null))].sort((a: any,b: any)=>b-a);
      const activeCongress=options?.congress!=null?Number(options.congress):(congresses[0]??null);
      const activeRoster=activeCongress!=null?normRosters.filter((r: any)=>r.congress===activeCongress):normRosters;
      const parent=found?.parent_key?normCommittees.find((c: any)=>c.committee_key===found.parent_key)??null:null;
      if(!found&&!docRows.length&&!normMeetings.length&&!normRosters.length)return null;
      const base=found??normalizeCommittee({
        committee_key:canonicalKey,
        system_code:canonicalKey,
        name:canonicalKey.toUpperCase(),
        current_name:canonicalKey.toUpperCase(),
      });
      const resolvedName=resolveCommitteeHistoricalName(base,options?.date??options?.congress);
      return {
        ...base,
        resolved_name:resolvedName||base.current_name,
        parent,
        subcommittees:explicitSubs,
        roster:activeRoster,
        all_rosters:normRosters,
        roster_congresses:congresses,
        active_congress:activeCongress,
        hearings:normMeetings,
        hearing_count:base.hearing_count||normMeetings.length,
        doc_count:docRows.length||base.doc_count,
        list_rows:docRows,
        documents:docRows.slice(0,100).map(row),
      };
    },
    async getWitness(witnessKey: string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(witnessKey??'').trim().toLowerCase();
      if(!clean)return null;
      const [rawWitnesses,rawMeetings,rawMembers]=await Promise.all([
        entity('witnesses'),
        entity('meetings'),
        entity('members'),
      ]);
      const normWitnesses=rawWitnesses.map(normalizeWitness);
      let found=normWitnesses.find((w: any)=>
        w.witness_key.toLowerCase()===clean||String(w.name_key??'').toLowerCase()===clean);
      const normMeetings=rawMeetings.map(normalizeMeeting);
      if(!found){
        const matchingMeetings=normMeetings.filter((m: any)=>
          m.witnesses.some((w: any)=>String(w.witness_key??w.name_key??w.name??'').toLowerCase()===clean));
        const colRows=rowsForColumn('witness_keys',clean);
        if(!matchingMeetings.length&&!colRows.length)return null;
        const sampleW=matchingMeetings[0]?.witnesses?.find((w: any)=>String(w.witness_key??w.name_key??w.name??'').toLowerCase()===clean)??{};
        found=normalizeWitness({
          ...sampleW,
          witness_key:sampleW.witness_key??witnessKey,
          name:sampleW.name??witnessKey,
          appearances:matchingMeetings.map((m: any)=>({
            event_id:m.event_id,
            chamber:m.chamber,
            congress:m.congress,
            meeting_date:m.meeting_date,
            title:m.title,
            list_rows:m.list_rows.filter((r: number)=>(value('witness_keys',r)??[]).map((k: any)=>String(k).toLowerCase()).includes(clean)),
          })),
          list_rows:colRows,
        });
      }
      const meetingByEvent=new Map(normMeetings.map((m: any)=>[String(m.event_id),m]));
      const enrichedAppearances=found.appearances.map((a: any)=>{
        const m=meetingByEvent.get(String(a.event_id??a.meeting_key??''));
        return {
          ...(m?{title:m.title,meeting_date:m.meeting_date,chamber:m.chamber,congress:m.congress,committee_keys:m.committee_keys}:{}),
          ...a,
          meeting_title:a.title??m?.title??null,
          committee_keys:a.committee_keys??m?.committee_keys??[],
        };
      });
      const member=found.bioguide_id
        ?rawMembers.map(normalizeMember).find((m: any)=>m.bioguide_id.toLowerCase()===String(found.bioguide_id).toLowerCase())??null
        :null;
      return {
        ...found,
        appearances:enrichedAppearances,
        hearings:enrichedAppearances,
        member,
        documents:found.list_rows.map(row),
      };
    },
    async getMember(bioguideId: string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(bioguideId??'').trim().toLowerCase();
      if(!clean)return null;
      const [rawMembers,rawRosters,rawWitnesses,rawMeetings,rawBills]=await Promise.all([
        entity('members'),
        entity('rosters'),
        entity('witnesses'),
        entity('meetings'),
        entity('bills'),
      ]);
      const normMembers=rawMembers.map(normalizeMember);
      const found=normMembers.find((m: any)=>m.bioguide_id.toLowerCase()===clean);
      const rosterEntries=rawRosters.map(normalizeRoster).filter((r: any)=>String(r.bioguide_id??'').toLowerCase()===clean);
      const witnessRecords=rawWitnesses.map(normalizeWitness).filter((w: any)=>String(w.bioguide_id??'').toLowerCase()===clean);
      const sponsoredBills=rawBills.map(normalizeBill).filter((b: any)=>String(b.sponsor_bioguide_id??'').toLowerCase()===clean);
      const colRows=rowsForColumn('bioguide_ids',clean);
      if(!found&&!rosterEntries.length&&!witnessRecords.length&&!colRows.length&&!sponsoredBills.length)return null;
      const base=found??normalizeMember({
        bioguide_id:bioguideId.toUpperCase(),
        name:rosterEntries[0]?.name??witnessRecords[0]?.name??bioguideId.toUpperCase(),
        party:rosterEntries[0]?.party??null,
        state:rosterEntries[0]?.state??null,
        committees:rosterEntries.map((r: any)=>({
          committee_key:r.committee_key,
          system_code:r.system_code,
          congress:r.congress,
          role:r.role,
          rank_in_party:r.rank_in_party,
        })),
        appearances:witnessRecords.flatMap((w: any)=>w.appearances),
        list_rows:uniqueInts([...colRows,...witnessRecords.flatMap((w: any)=>w.list_rows)]),
      });
      const allListRows=uniqueInts([...base.list_rows,...witnessRecords.flatMap((w: any)=>w.list_rows)]);
      const meetingByEvent=new Map(rawMeetings.map(normalizeMeeting).map((m: any)=>[String(m.event_id),m]));
      const rawApps=[...base.appearances,...witnessRecords.flatMap((w: any)=>w.appearances)];
      const seenEvents=new Set<string>();
      const hearings: any[]=[];
      for(const app of rawApps){
        const ev=String(app.event_id??app.meeting_key??'');
        if(ev&&seenEvents.has(ev))continue;
        if(ev)seenEvents.add(ev);
        const m=meetingByEvent.get(ev);
        hearings.push({
          ...(m??{}),
          ...app,
          title:app.title??m?.title??null,
        });
      }
      return {
        ...base,
        roster_entries:rosterEntries,
        witness_records:witnessRecords,
        sponsored_bills:sponsoredBills,
        hearings,
        list_rows:allListRows,
        documents:allListRows.map(row),
      };
    },
    async getBill(subjectKey: string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(subjectKey??'').trim().toLowerCase();
      if(!clean)return null;
      const [rawBills,rawMeetings]=await Promise.all([entity('bills'),entity('meetings')]);
      const found=rawBills.map(normalizeBill).find((b: any)=>
        b.subject_key.toLowerCase()===clean||b.bill_id.toLowerCase()===clean);
      if(!found)return null;
      const normMeetings=rawMeetings.map(normalizeMeeting).filter((m: any)=>
        m.subject_keys.some((k: string)=>k.toLowerCase()===clean)
        ||found.meeting_keys.includes(String(m.event_id)));
      const meetingKeys=[...new Set([...found.meeting_keys,...normMeetings.map((m: any)=>String(m.event_id))])];
      return {
        ...found,
        meeting_keys:meetingKeys,
        hearings:normMeetings,
        documents:found.list_rows.map(row),
      };
    },
    async getNomination(subjectKey: string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(subjectKey??'').trim().toLowerCase();
      if(!clean)return null;
      const [rawNominations,rawMeetings]=await Promise.all([entity('nominations'),entity('meetings')]);
      const found=rawNominations.map(normalizeNomination).find((n: any)=>
        n.subject_key.toLowerCase()===clean
        ||n.nomination_id.toLowerCase()===clean
        ||String(n.citation??'').toLowerCase()===clean);
      if(!found)return null;
      const canonical=found.subject_key.toLowerCase();
      const normMeetings=rawMeetings.map(normalizeMeeting).filter((m: any)=>
        m.subject_keys.some((k: string)=>k.toLowerCase()===canonical||k.toLowerCase()===clean)
        ||found.meeting_keys.includes(String(m.event_id)));
      const meetingKeys=[...new Set([...found.meeting_keys,...normMeetings.map((m: any)=>String(m.event_id))])];
      return {
        ...found,
        meeting_keys:meetingKeys,
        hearings:normMeetings,
        documents:found.list_rows.map(row),
      };
    },
    async getSubject(subjectKey: string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const clean=String(subjectKey??'').trim();
      if(!clean)return null;
      const bill=await reader.getBill(clean,signal);
      if(bill)return bill;
      const nomination=await reader.getNomination(clean,signal);
      if(nomination)return nomination;
      const lower=clean.toLowerCase();
      const docRows=rowsForColumn('measure_keys',lower);
      const rawMeetings=await entity('meetings');
      const hearings=rawMeetings.map(normalizeMeeting).filter((m: any)=>
        m.subject_keys.some((k: string)=>k.toLowerCase()===lower)
        ||m.list_rows.some((r: number)=>docRows.includes(r)));
      if(!docRows.length&&!hearings.length)return null;
      const isNom=/^(?:\d+-)?pn-/i.test(clean);
      const congMatch=/^(\d+)-/.exec(clean);
      return {
        kind:isNom?('nomination' as const):('bill' as const),
        subject_key:clean,
        bill_id:isNom?undefined:clean,
        nomination_id:isNom?clean:undefined,
        congress:congMatch?Number(congMatch[1]):(docRows.length?value('congress',docRows[0]):null),
        title:null,
        status:null,
        committees:[...new Set(docRows.flatMap(r=>value('committee_keys',r)??[]))],
        committee_activities:[],
        cbo_estimates:[],
        votes:[],
        floor_votes:[],
        amendments:[],
        amendment_count:0,
        related_bills:[],
        nominees:[],
        meeting_keys:hearings.map((m: any)=>String(m.event_id)),
        hearings,
        list_rows:docRows,
        documents:docRows.map(row),
      };
    },
    async listEntities(kind: string,options: any={},signal?: AbortSignal){
      signal?.throwIfAborted();
      const offset=options.offset??0,limit=options.limit??100;
      const text=String(options.text??'').trim().toLowerCase();
      const congressFilter=options.congress!=null?Number(options.congress):null;
      const chamberFilter=options.chamber?String(options.chamber).toLowerCase():null;
      const committeeFilter=options.committee?String(options.committee).toLowerCase():null;
      let items: any[]=[];
      switch(kind){
        case 'meetings':items=(await entity('meetings')).map(normalizeMeeting);break;
        case 'witnesses':items=(await entity('witnesses')).map(normalizeWitness);break;
        case 'recordings':items=(await entity('recordings')).map(normalizeRecording);break;
        case 'committees':items=(await entity('committees')).map(normalizeCommittee);break;
        case 'members':items=(await entity('members')).map(normalizeMember);break;
        case 'rosters':items=(await entity('rosters')).map(normalizeRoster);break;
        case 'bills':items=(await entity('bills')).map(normalizeBill);break;
        case 'nominations':items=(await entity('nominations')).map(normalizeNomination);break;
        case 'subjects':{
          const [b,n]=await Promise.all([entity('bills'),entity('nominations')]);
          items=[...b.map(normalizeBill),...n.map(normalizeNomination)];
          break;
        }
        default:throw new Error(`Unknown archive entity kind: ${kind}`);
      }
      const filtered=items.filter((item: any)=>{
        if(congressFilter!=null&&item.congress!=null&&Number(item.congress)!==congressFilter)return false;
        if(chamberFilter&&item.chamber&&String(item.chamber).toLowerCase()!==chamberFilter)return false;
        if(committeeFilter){
          const keys=[
            item.committee_key,
            item.system_code,
            ...(Array.isArray(item.committee_keys)?item.committee_keys:[]),
            ...(Array.isArray(item.committees)?item.committees.map((c: any)=>typeof c==='string'?c:(c?.committee_key??c?.system_code)):[]),
          ].filter(Boolean).map((k: any)=>String(k).toLowerCase());
          if(!keys.includes(committeeFilter))return false;
        }
        if(text){
          const hay=[
            item.title,
            item.short_title,
            item.name,
            item.current_name,
            item.organization,
            item.subject_key,
            item.bill_id,
            item.nomination_id,
            item.citation,
            item.bioguide_id,
            item.committee_key,
            item.event_id,
          ].filter(Boolean).join(' ').toLowerCase();
          if(!hay.includes(text))return false;
        }
        return true;
      });
      return {
        total:filtered.length,
        rows:filtered.slice(offset,offset+limit),
        offset,
        next:offset+limit<filtered.length?offset+limit:null,
      };
    },
    async openDocument(indexOrKey: number|string,signal?: AbortSignal){
      signal?.throwIfAborted();
      const index=typeof indexOrKey==='string'&&!/^\d+$/.test(indexOrKey)
        ?await reader.resolve(indexOrKey)
        :Number(indexOrKey);
      if(index===null||!Number.isSafeInteger(index)||index<0||index>=count)throw new Error('Archive document not found.');
      const [entry,versions,rawMeetings,rawRecordings,rawCommittees,rawWitnesses,rawMembers,rawBills,rawNominations]=await Promise.all([
        reader.entry(index,signal),
        reader.versions(index,signal),
        entity('meetings'),
        entity('recordings'),
        entity('committees'),
        entity('witnesses'),
        entity('members'),
        entity('bills'),
        entity('nominations'),
      ]);
      const doc=entry.document;
      const docMeetingKeys=new Set((doc.meeting_keys??[]).map(String));
      const recordingsByEvent=new Map<string,any[]>();
      for(const r of rawRecordings.map(normalizeRecording)){
        for(const ev of r.meeting_keys){
          const list=recordingsByEvent.get(ev)??[];
          list.push(r);
          recordingsByEvent.set(ev,list);
        }
      }
      const docMeetings=rawMeetings.map(normalizeMeeting).filter((m: any)=>
        docMeetingKeys.has(String(m.event_id))||m.list_rows.includes(index)).map((m: any)=>({
          ...m,
          recordings:recordingsByEvent.get(String(m.event_id))??[],
        }));
      const docCommitteeKeys=new Set([
        ...(doc.committee_keys??[]).map((k: any)=>String(k).toLowerCase()),
        ...docMeetings.flatMap((m: any)=>(m.committee_keys??[]).map((k: any)=>String(k).toLowerCase())),
      ]);
      const docCommittees=rawCommittees.map(normalizeCommittee).filter((c: any)=>
        docCommitteeKeys.has(c.committee_key)||c.system_codes.some((s: string)=>docCommitteeKeys.has(s))).map((c: any)=>({
          ...c,
          resolved_name:resolveCommitteeHistoricalName(c,doc.document_date??doc.congress),
        }));
      const docSubjectKeys=new Set([
        ...(doc.measure_keys??[]).map((k: any)=>String(k).toLowerCase()),
        ...docMeetings.flatMap((m: any)=>(m.subject_keys??[]).map((k: any)=>String(k).toLowerCase())),
      ]);
      const docSubjects=[
        ...rawBills.map(normalizeBill).filter((b: any)=>docSubjectKeys.has(b.subject_key.toLowerCase())||b.list_rows.includes(index)),
        ...rawNominations.map(normalizeNomination).filter((n: any)=>docSubjectKeys.has(n.subject_key.toLowerCase())||n.list_rows.includes(index)),
      ];
      const docWitnessKeys=new Set((doc.witness_keys??[]).map((k: any)=>String(k).toLowerCase()));
      const docWitnesses=rawWitnesses.map(normalizeWitness).filter((w: any)=>
        docWitnessKeys.has(w.witness_key.toLowerCase())
        ||(w.name_key&&docWitnessKeys.has(String(w.name_key).toLowerCase()))
        ||w.list_rows.includes(index));
      const docBioguides=new Set((doc.bioguide_ids??[]).map((k: any)=>String(k).toLowerCase()));
      const docMembers=rawMembers.map(normalizeMember).filter((m: any)=>
        docBioguides.has(m.bioguide_id.toLowerCase())||m.list_rows.includes(index));
      return {
        ...entry,
        versions,
        meetings:docMeetings,
        committees:docCommittees,
        subjects:docSubjects,
        witnesses:docWitnesses,
        members:docMembers,
      };
    },
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
export function dateLabels(document: any,detail: any){
  const captured=date(document.first_captured),imported=date(detail.in_archive_since),day=date(document.document_date);
  const source=detail.document_date_source&&detail.document_date_source!=='filename'?` (${detail.document_date_source})`:'';
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
