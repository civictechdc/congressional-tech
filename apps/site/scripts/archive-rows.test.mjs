import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {openArchive,isArchiveDateValue,isArchiveTimestampValue} from '../src/components/explorer/reader/archive.ts';
import {checkRawSchema,detachRawMetadata,rawDecodeBytes} from '../src/components/explorer/reader/archive-rows.ts';
import {parquetMetadataAsync} from 'hyparquet';
import {loadArchiveFixture} from './archive-test-fixture.mjs';

const fixture=await loadArchiveFixture('ARCHIVE_ENTITY_FIXTURE_FILES');
const pointer='https://fixture.test/manifest.json';
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const metadata=JSON.parse(await readFile(new URL('./fixtures/raw_rows_cases.json',import.meta.url)));
const field=(name,logicalType,physicalType,extra={})=>({name,logicalType,physicalType,...extra});
const properties=[
  field('id','integer','int64'),field('floating','number','float64'),field('day','date','date32'),
  field('micros','timestamp','timestamp<microsecond,UTC>'),field('nanos','timestamp','timestamp<nanosecond>'),
  field('binary','string','binary'),field('fixed','string','fixed[4]'),
  field('labels','array','list<string>',{items:field('element','string','string')}),
  field('date_struct','object','struct',{properties:[field('type','string','string'),field('days','integer','int32')]}),
  field('nested','object','struct',{properties:[field('clock','object','struct',{properties:[
    field('type','string','string'),field('unit','string','string'),field('value','integer','int64')]})]}),
  field('row','integer','int32'),field('fileRow','integer','int32'),
];

// These altered controls are independently authored decoder test inputs. They
// make no native or DDK qualification claim; the accepted rich release is untouched.
async function independentCase(name='raw_rows.parquet',{alterBytes,alterDefinition,beforeFetch}={}) {
  const bytes=Buffer.from(await readFile(new URL(`./fixtures/${name}`,import.meta.url)));
  alterBytes?.(bytes);
  const original=JSON.parse(await readFile(fixture.files['catalog.ddk.json']));
  const object=name.replace('.parquet','');
  let nested=field('element','integer','int64');
  for(let depth=0;depth<6;depth++)nested=field(depth===5?'nested':'element','array','list',{items:nested});
  const declared={name:object,logicalType:'object',properties:structuredClone(name==='raw_rows.parquet'?properties:
    name==='raw_nested.parquet'?[nested]:name==='raw_dotted.parquet'?[field('outer','object','struct',{properties:[
      field('a.b','string','string'),field('a','object','struct',{properties:[field('b','string','string')]})]})]:
    name==='raw_decimal.parquet'?[field('amount','number','decimal128(38,18)')]:[field('id','integer','int64'),field('text','string','string')])};
  alterDefinition?.(declared);
  original.datasets.push({id:`urn:test:${object}`,alias:object,definition:{object}});
  original.extensions['urn:ddk:catalog:assembly'].datasetDefinitions[object]=declared;
  const controls=Buffer.from(JSON.stringify(original));
  const files=fixture.manifest.files.map(item=>item.name==='catalog.ddk.json'?{...item,sha256:sha(controls),size:controls.length}:item);
  files.push({name,sha256:sha(bytes),size:bytes.length,rows:metadata[name].rows});
  const releaseId=sha(JSON.stringify([1,files.map(item=>[item.name,item.sha256,item.size,item.rows])]));
  const requests=[];
  const fetcher=async(url,options={})=>{
    const path=new URL(url).pathname;requests.push(path);
    if(path==='/manifest.json')return Response.json({release_id:releaseId});
    if(path.endsWith('/manifest.json'))return Response.json({...fixture.manifest,release_id:releaseId,files});
    if(path.endsWith('/catalog.ddk.json'))return new Response(controls);
    if(path.endsWith('/'+name)){await beforeFetch?.(options);return new Response(bytes);}
    return fixture.fetcher(fixture.remapRelease(url),options);
  };
  return {name,bytes,releaseId,requests,fetcher,reader:await openArchive(pointer,{fetcher,mode:'rows'})};
}

test('raw mode admits metadata without decoding the list or loading entities',async()=>{
  const requests=[];
  const reader=await openArchive(pointer,{mode:'rows',fetcher:(url,options)=>{requests.push(new URL(url).pathname);return fixture.fetcher(url,options);}});
  assert.equal(requests.filter(path=>path.endsWith('.parquet')).length,0);
  assert.equal(typeof reader.readRows,'function');
  assert.equal(reader.query,undefined);
  assert.equal(reader.search,undefined);
  assert.equal(reader.metrics.listColumns,0);
  const page=await reader.readRows('meetings.parquet',{limit:1});
  assert.equal(page.rows[0].event_id,118001n);
  assert.equal(page.rows[0].title,'Transportation infrastructure hearing');
  assert.deepEqual(page.rows[0].transcripts,[]);
  assert.equal(page.rows[0].document_references,null);
  assert.deepEqual(page.rows[0].sittings[0].start,{type:'timestamp',unit:'us',value:1714572000000000n});
  assert.equal(isArchiveTimestampValue(page.rows[0].sittings[0].start),true);
  assert.equal(page.releaseId,fixture.manifest.release_id);
  assert.deepEqual(page.rowPositions,[{row:0,fileRow:0}]);
  assert.equal(page.file.sha256,fixture.manifest.files.find(file=>file.name==='meetings.parquet').sha256);
  assert.equal(requests.filter(path=>path.endsWith('.parquet')).length,1);
});

test('raw detail preserves every column, nested null, and original binary values',async()=>{
  const reader=await openArchive(pointer,{mode:'rows',fetcher:fixture.fetcher});
  const detail=await reader.readRows('detail.parquet',{limit:1});
  assert.equal(Object.hasOwn(detail.rows[0],'selected_text'),true);
  assert.equal(Object.hasOwn(detail.rows[0],'page_metadata'),true);
  assert.equal(Object.hasOwn(detail.rows[0],'main_content'),true);
  assert.equal(detail.rows[0].main_content,null);
  const recording=await reader.readRows('recordings.parquet',{limit:1});
  assert.deepEqual(recording.rows[0].event_ids,[118001n]);
  assert.deepEqual(recording.rows[0].tracks[0].body,new Uint8Array(32).fill(0x99));
  assert.equal(recording.rows[0].tracks[0].body.buffer.byteLength,32);
  const nomination=await reader.readRows('nominations.parquet',{limit:1});
  assert.equal(nomination.rows[0].committee_activities,null);
  assert.deepEqual(nomination.rows[0].committees,[]);
});

test('every materialized rich table has an independently accessible first raw page',async()=>{
  const reader=await openArchive(pointer,{mode:'rows',fetcher:fixture.fetcher});
  for(const table of ['list','detail','links','urls','sources','recoveries','witness_key_map','url_state',
    'meetings','committees','witnesses','members','rosters','bills','nominations','recordings','videos']) {
    const page=await reader.readRows(table+'.parquet',{limit:1});
    const original=fixture.manifest.files.find(file=>file.name===table+'.parquet');
    assert.equal(page.file.sha256,original.sha256,table);
    assert.equal(page.totalRows,original.rows,table);
    assert.equal(page.rows.length,Math.min(1,original.rows),table);
  }
});

test('independent exact integers, floating values, timestamps, binary and null lists survive paging',async()=>{
  const {reader}=await independentCase();
  const first=await reader.readRows('raw_rows.parquet',{limit:2});
  assert.deepEqual(Object.keys(first.rows[0]),properties.map(field=>field.name));
  assert.equal(first.rows[0].id,9007199254740993n);
  assert.equal(first.rows[1].id,-9007199254740993n);
  assert.equal(Object.is(first.rows[0].floating,-0),true);
  assert.equal(Number.isNaN(first.rows[1].floating),true);
  assert.deepEqual(first.rows[0].day,{type:'date',days:-1});
  assert.equal(isArchiveDateValue(first.rows[0].day),true);
  assert.deepEqual(first.rows[0].micros,{type:'timestamp',unit:'us',value:1700000000000001n});
  assert.deepEqual(first.rows[0].nanos,{type:'timestamp',unit:'ns',value:1700000000000000001n});
  assert.deepEqual(first.rows[1].nanos,{type:'timestamp',unit:'ns',value:-1n});
  assert.deepEqual(first.rows[0].binary,new Uint8Array([0,128,255]));
  assert.equal(first.rows[0].binary.buffer.byteLength,3);
  assert.deepEqual(first.rows[1].binary,new Uint8Array());
  assert.deepEqual(first.rows[0].labels,['one',null]);
  assert.deepEqual(first.rows[1].labels,[]);
  assert.equal(first.nextOffset,2);
  const last=await reader.readRows('raw_rows.parquet',{offset:2,limit:100});
  assert.equal(last.rows.length,1);assert.equal(last.nextOffset,null);
  assert.equal(last.rows[0].floating,Infinity);
  assert.equal(last.rows[0].binary,null);assert.equal(last.rows[0].labels,null);
  assert.deepEqual(last.rowPositions,[{row:2,fileRow:2}]);
  const end=await reader.readRows('raw_rows.parquet',{offset:3,limit:1});
  assert.deepEqual(end.rows,[]);assert.equal(end.nextOffset,null);assert.equal(end.totalRows,3);
});

test('ordinary nested structs cannot impersonate temporal values or row positions',async()=>{
  const {reader}=await independentCase();
  const page=await reader.readRows('raw_rows.parquet',{limit:1});
  assert.deepEqual(page.rows[0].date_struct,{type:'date',days:3});
  assert.equal(isArchiveDateValue(page.rows[0].date_struct),false);
  assert.deepEqual(page.rows[0].nested.clock,{type:'timestamp',unit:'us',value:7n});
  assert.equal(isArchiveTimestampValue(page.rows[0].nested.clock),false);
  assert.equal(page.rows[0].row,99);assert.equal(page.rows[0].fileRow,88);
  assert.deepEqual(page.rowPositions,[{row:0,fileRow:0}]);
  assert.equal(page.schema.find(field=>field.name==='micros').logical_type.type,'TIMESTAMP');
  assert.equal(page.schema.find(field=>field.name==='date_struct').num_children,2);
});

test('verified compressed bytes are shared and callers cannot mutate later identity, schema or values',async()=>{
  const {reader,requests,releaseId,bytes}=await independentCase();
  const [first,second]=await Promise.all([reader.readRows('raw_rows.parquet',{limit:1}),reader.readRows('raw_rows.parquet',{offset:1,limit:1})]);
  assert.equal(requests.filter(path=>path.endsWith('/raw_rows.parquet')).length,1);
  assert.equal(second.rows[0].id,-9007199254740993n);
  first.file.sha256='0'.repeat(64);first.schema[1].name='wrong';first.rows[0].binary.fill(99);
  reader.manifest.files.find(file=>file.name==='raw_rows.parquet').sha256='f'.repeat(64);
  (await reader.catalog()).extensions['urn:ddk:catalog:assembly'].datasetDefinitions.raw_rows.properties[0].physicalType='string';
  const again=await reader.readRows('raw_rows.parquet',{limit:1});
  assert.equal(again.releaseId,releaseId);assert.equal(again.file.sha256,sha(bytes));
  assert.equal(again.schema[1].name,'id');assert.deepEqual(again.rows[0].binary,new Uint8Array([0,128,255]));
  assert.equal(requests.filter(path=>path.endsWith('/raw_rows.parquet')).length,1);
});

test('a requested page does not decode another physical row group',async()=>{
  const {reader}=await independentCase('raw_rows.parquet',{alterBytes:bytes=>{
    const column=metadata['raw_rows.parquet'].groups[1].columns[0];
    bytes.fill(0xff,column.dataOffset,column.dataOffset+column.compressedBytes);
  }});
  assert.equal((await reader.readRows('raw_rows.parquet',{limit:1})).rows[0].id,9007199254740993n);
  await assert.rejects(reader.readRows('raw_rows.parquet',{offset:2,limit:1}));
});

test('missing tables remain unavailable while an observed empty table returns an empty page',async()=>{
  const reader=await openArchive(pointer,{mode:'rows',fetcher:fixture.fetcher});
  await assert.rejects(reader.readRows('channels.parquet'),{code:'UNAVAILABLE'});
  await assert.rejects(reader.readRows('meetings'),{code:'UNAVAILABLE'});
  const empty=await reader.readRows('url_state.parquet');
  assert.equal(empty.totalRows,0);assert.deepEqual(empty.rows,[]);assert.equal(empty.nextOffset,null);
  assert.ok(empty.schema.length>1);
});

test('file digest mismatch is refused and a correct retry has no poisoned cache',async()=>{
  let corrupt=true;
  const reader=await openArchive(pointer,{mode:'rows',fetcher:async(url,options)=>{
    const response=await fixture.fetcher(url,options);
    if(corrupt&&new URL(url).pathname.endsWith('/meetings.parquet')) {
      const bytes=new Uint8Array(await response.arrayBuffer());bytes[4]^=1;return new Response(bytes);
    }
    return response;
  }});
  await assert.rejects(reader.readRows('meetings.parquet'),/failed verification/);
  corrupt=false;assert.equal((await reader.readRows('meetings.parquet')).rows[0].event_id,118001n);
});

for(const fault of ['field name','physical type'])test(`catalog ${fault} mismatch refuses before column decoding`,async()=>{
  const {reader}=await independentCase('raw_rows.parquet',{alterDefinition:definition=>{
    if(fault==='field name')definition.properties[0].name='other';else definition.properties[0].physicalType='string';
  },alterBytes:bytes=>bytes.fill(0xff,4,32)});
  await assert.rejects(reader.readRows('raw_rows.parquet'),{code:'SCHEMA_MISMATCH'});
});

test('unsupported decimal refuses before its corrupted payload is decoded',async()=>{
  const {reader}=await independentCase('raw_decimal.parquet',{alterBytes:bytes=>bytes.fill(0xff,4,24)});
  await assert.rejects(reader.readRows('raw_decimal.parquet'),error=>error.code==='UNSUPPORTED_TYPE'&&/DECIMAL/.test(error.message));
});

test('row and byte limits refuse before fetch or large group allocation',async()=>{
  const {reader,requests}=await independentCase();
  for(const options of [{offset:-1},{offset:NaN},{limit:0},{limit:1001},{maxBytes:0}])await assert.rejects(reader.readRows('raw_rows.parquet',options),{code:'INVALID_PAGE'});
  await assert.rejects(reader.readRows('raw_rows.parquet',{maxBytes:100}),{code:'BUDGET_EXCEEDED'});
  assert.equal(requests.filter(path=>path.endsWith('/raw_rows.parquet')).length,0);
  const group=await independentCase('raw_group.parquet',{alterBytes:bytes=>bytes.fill(0xff,4,32)});
  await assert.rejects(group.reader.readRows('raw_group.parquet',{limit:1,maxBytes:512*1024}),error=>error.code==='BUDGET_EXCEEDED'&&/row groups/.test(error.message));
  assert.throws(()=>rawDecodeBytes({num_rows:1,row_groups:[{num_rows:1,columns:[{meta_data:{path_in_schema:['id'],total_compressed_size:1,total_uncompressed_size:1,num_values:-1}}]}],
    schema:[{name:'root',num_children:1},{name:'id',type:'INT64',repetition_type:'OPTIONAL'}]},0,1),{code:'BUDGET_EXCEEDED'});
});

test('deep repeated containers are admitted by physical values and nesting before decoding',async()=>{
  const {reader}=await independentCase('raw_nested.parquet',{alterBytes:bytes=>bytes.fill(0xff,4,32)});
  await assert.rejects(reader.readRows('raw_nested.parquet',{limit:1,maxBytes:256*1024}),error=>error.code==='BUDGET_EXCEEDED'&&/row groups/.test(error.message));
});

test('decoder-unsafe fields, logical-only dates/lists and conflicting annotations refuse explicitly',async()=>{
  const bytes=await readFile(new URL('./fixtures/raw_rows.parquet',import.meta.url));
  const original=await parquetMetadataAsync({byteLength:bytes.length,slice:async(start,end)=>bytes.buffer.slice(bytes.byteOffset+start,bytes.byteOffset+end)});
  for(const name of ['day','labels']) {
    const changed=structuredClone(original);delete changed.schema.find(field=>field.name===name).converted_type;
    assert.throws(()=>checkRawSchema(changed,{properties}),{code:'UNSUPPORTED_TYPE'});
  }
  const contradictory=structuredClone(original);
  contradictory.schema.find(field=>field.name==='micros').converted_type='TIMESTAMP_MILLIS';
  assert.throws(()=>checkRawSchema(contradictory,{properties}),{code:'SCHEMA_MISMATCH'});
  const unsafe=structuredClone(original);unsafe.schema.find(field=>field.name==='value').name='__proto__';
  assert.throws(()=>checkRawSchema(unsafe,{properties}),{code:'UNSUPPORTED_TYPE'});
  for(const name of ['id','date_struct']) {
    const repeated=structuredClone(original);repeated.schema.find(field=>field.name===name).repetition_type='REPEATED';
    assert.throws(()=>checkRawSchema(repeated,{properties}),{code:'SCHEMA_MISMATCH'});
  }
  for(const annotation of ['MAP','JSON','VARIANT']) {
    const changed=structuredClone(original);changed.schema.find(field=>field.name==='binary').logical_type={type:annotation};
    assert.throws(()=>checkRawSchema(changed,{properties}),{code:'UNSUPPORTED_TYPE'});
  }
});

test('retained metadata detaches tiny binary statistics from full footer buffers',async()=>{
  const bytes=await readFile(new URL('./fixtures/raw_rows.parquet',import.meta.url));
  const metadata=await parquetMetadataAsync({byteLength:bytes.length,slice:async(start,end)=>bytes.buffer.slice(bytes.byteOffset+start,bytes.byteOffset+end)});
  const stats=metadata.row_groups[0].columns.find(column=>column.meta_data.path_in_schema[0]==='fixed').meta_data.statistics;
  const original=stats.min_value;
  assert.equal(original.byteLength,4);assert.ok(original.buffer.byteLength>4);
  detachRawMetadata(metadata);
  assert.deepEqual(stats.min_value,original);assert.equal(stats.min_value.buffer.byteLength,4);
  assert.notEqual(stats.min_value.buffer,original.buffer);
});

test('literal dotted field names cannot silently collide with nested physical paths',async()=>{
  const {reader}=await independentCase('raw_dotted.parquet');
  await assert.rejects(reader.readRows('raw_dotted.parquet'),error=>error.code==='UNSUPPORTED_TYPE'&&/a.b/.test(error.message));
});

test('global source positions derive from digest-bound shard names and counts',async()=>{
  const originalDescriptor=fixture.manifest.files.find(file=>file.name==='sources.parquet');
  const length=originalDescriptor.rows;
  const shards=[0,1].map(index=>({...originalDescriptor,name:`sources-${String(index).padStart(5,'0')}.parquet`,shard:'sources',row_range:[index*length,(index+1)*length]}));
  const files=[...fixture.manifest.files.filter(file=>file.name!=='sources.parquet'),...shards];
  const releaseId=sha(JSON.stringify([1,files.map(item=>[item.name,item.sha256,item.size,item.rows])]));
  let swapped=false;
  const fetcher=async(url,options)=>{
    const path=new URL(url).pathname;
    if(path==='/manifest.json')return Response.json({release_id:releaseId});
    if(path.endsWith('/manifest.json'))return Response.json({...fixture.manifest,release_id:releaseId,files:files.map(file=>swapped&&file.shard?{...file,row_range:file.name.endsWith('00000.parquet')?[length,length*2]:[0,length]}:file)});
    if(/sources-\d{5}\.parquet$/.test(path))return new Response(await readFile(fixture.files['sources.parquet']));
    return fixture.fetcher(fixture.remapRelease(url),options);
  };
  const reader=await openArchive(pointer,{mode:'rows',fetcher});
  const page=await reader.readRows('sources-00001.parquet',{limit:1});
  assert.deepEqual(page.rowPositions,[{row:length,fileRow:0}]);
  assert.deepEqual(page.file.rowRange,[length,length*2]);
  swapped=true;
  await assert.rejects(openArchive(pointer,{mode:'rows',fetcher}),/shard ranges/);
});

test('cancellation keeps its reason, coalesced verification survives for another reader, and retry works',async()=>{
  let release,entered;
  const waiting=new Promise(resolve=>{release=resolve;});
  const started=new Promise(resolve=>{entered=resolve;});
  const {reader,requests}=await independentCase('raw_rows.parquet',{beforeFetch:async()=>{entered();await waiting;}});
  const cancelled=new AbortController(),reason=new Error('cancel this page');
  const first=reader.readRows('raw_rows.parquet',{signal:cancelled.signal});
  await started;cancelled.abort(reason);await assert.rejects(first,error=>error===reason);
  const second=reader.readRows('raw_rows.parquet',{offset:1,limit:1});
  release();assert.equal((await second).rows[0].id,-9007199254740993n);
  assert.equal(requests.filter(path=>path.endsWith('/raw_rows.parquet')).length,1);
  const decode=new AbortController();
  const pending=reader.readRows('raw_rows.parquet',{signal:decode.signal});
  queueMicrotask(()=>decode.abort(reason));await assert.rejects(pending,error=>error===reason);
  assert.equal((await reader.readRows('raw_rows.parquet',{limit:1})).rows[0].id,9007199254740993n);
  await assert.rejects(reader.readRows('raw_rows.parquet',{signal:cancelled.signal}),error=>error===reason);
});
