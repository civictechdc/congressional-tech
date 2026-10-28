import {createHash} from 'node:crypto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtemp,readFile,open,stat,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createFilenameCatalog, sourceContext} from './catalog.ts';
import {compareBrowseKeys} from './catalog-v6.ts';

async function localFetch(url,options={}) {
  options.signal?.throwIfAborted();
  if(!options.headers?.Range)return new Response(await readFile(new URL(url)));
  const [start,end]=options.headers.Range.slice(6).split('-').map(Number), handle=await open(new URL(url));
  try{const bytes=Buffer.alloc(end-start+1);await handle.read(bytes,0,bytes.length,start);return new Response(bytes,{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${(await stat(new URL(url))).size}`}});}finally{await handle.close();}
}
const comparable = rows => rows.map(row=>{
  const result={...row};
  for(const name of ['_row','source_id','document_id','extension','recovered_filename','response_result'])delete result[name];
  if(!('document_kind_source' in result))result.document_kind_source=null;
  return result;
});

test('stable browser agrees with maintained search and preserves complete original records',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-viewer-'));
  try{
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../../../../../packages/viewer_publication/tests/native_viewer_fixture.py',import.meta.url)),folder]);
    const requests=[];
    const reader=await createFilenameCatalog(pathToFileURL(join(folder,'native-public/manifest.json')),(url,options)=>{requests.push(String(url));return localFetch(url,options);});
    assert.equal(requests.length,3,'startup only reads manifest and two bounded proof pages');
    const expected=JSON.parse(await readFile(join(folder,'expected.json')));
    for(const {query,result}of expected){
      const after=await reader.search(query);
      assert.deepEqual({...after,rows:comparable(after.rows)},{...result,rows:comparable(result.rows)},JSON.stringify(query));
      assert(after.rows.every(row=>row._row===row.source_id),'new results use stable source IDs');
    }
    const originals=JSON.parse(await readFile(join(folder,'source-records.json')));
    const documents=JSON.parse(await readFile(join(folder,'document-records.json')));
    for(const source of originals){
      const doc=documents.find(row=>row.document_id===source.document_id);
      assert.deepEqual(await reader.documentRecord(source.source_id),doc);
      assert.deepEqual(await reader.technical(source.source_id,undefined,undefined,true),source);
      const entry=await reader.entry(source.source_id);
      const isRetained=row=>row.record_role?.[0]==='document'&&row.body_key!=null;
      const expectedRecord=Object.fromEntries(Object.keys(entry.record).map(k=>[k,
        k==='body_key'?isRetained(source)?source.body_key:null:
        k==='state_checked_at'&&source[k]?source[k].map(v=>new Date(v).toISOString()):source[k]]));
      assert.deepEqual(entry.record,expectedRecord);
      assert.deepEqual(entry.sources,originals.filter(row=>row.document_id===source.document_id).map(row=>({
        filename:row.filename,source_url:row.source_url,source_id:row.source_id,format:row.format,record_role:row.record_role,retained:isRetained(row),
      })));
      assert.deepEqual(entry.origin,sourceContext(source));
      const preferred=originals.find(row=>row.source_id===doc.source_id);
      assert.deepEqual(entry.document_origin,{redirects:sourceContext(preferred).redirects});
      assert.equal(entry.filename,doc.filename);
    }
    const typed=await reader.entry(originals[1].source_id);
    assert.equal(typed.facts.http_status,200);assert.equal(typed.facts.response_usable,true);
    assert.equal(typed.facts.response_body_complete,null);assert.equal(typed.facts.completeness_conflict,true);
    assert.equal(typed.facts.state_checked_at,'2026-10-14T13:00:00.000Z');
    assert.deepEqual(await reader.matchUrls({urls:[]}),{matches:[],truncated:false});
    assert.deepEqual(await reader.matchUrls({urls:['https://absent.test/none']}),{matches:[],truncated:false});
    for(const row of originals.filter(row=>row.source_url)){
      assert.deepEqual(await reader.matchUrls({urls:[row.source_url]}),{matches:[{source_id:row.source_id,url:row.source_url}],truncated:false});
    }
    for(const row of originals.filter(row=>/([a-f0-9]{64})\.gz$/.test(row.body_key||''))){
      const sha256=/([a-f0-9]{64})\.gz$/.exec(row.body_key)[1];
      assert.deepEqual(await reader.matchUrls({sha256s:[sha256]}),{matches:[{source_id:row.source_id,sha256}],truncated:false});
    }
    assert.deepEqual(await reader.matchUrls({sha256s:['invalid','a'.repeat(64)]}),{matches:[],truncated:false});
    assert.deepEqual(await reader.matchUrls({urls:['http://archive.test/recovered-unfetched.pdf']}),{matches:[{source_id:originals[2].source_id}],truncated:false});
    const aborted = new AbortController();aborted.abort();
    await assert.rejects(reader.matchUrls({urls:[originals[0].source_url]},aborted.signal),{name:'AbortError'});
    await assert.rejects(reader.entry('0'),/not present/);
    await assert.rejects(reader.entry(originals[0].source_id,'wrong'),/different catalog/);
    const first=await reader.observationPage(originals[2].source_id,undefined,{limit:2});
    assert.deepEqual(first.items,originals[2].source_occurrences.slice(0,2));assert.equal(first.next,2);
    assert.deepEqual((await reader.observationPage(originals[2].source_id,undefined,{offset:2,limit:2})).items,originals[2].source_occurrences.slice(2));
    assert(!requests.some(path=>/\/(groups|preferred|flags)\.bin$|\/ids\//.test(path)));
    const controller=new AbortController();controller.abort();await assert.rejects(reader.search({},controller.signal),{name:'AbortError'});
    const mixed=await readFile(join(folder,'native-public/manifest.json'),'utf8');
    const manifest=JSON.parse(mixed),browsePath=manifest.roots.browse.path;
    for(const stale of [false,true]) {
      const broken=await createFilenameCatalog(pathToFileURL(join(folder,'native-public/manifest.json')),async(url,options)=>{
        if(String(url).endsWith(browsePath))return stale?new Response('{}'):new Response('',{status:404});
        return localFetch(url,options);
      });
      await assert.rejects(broken.search({}),stale?/failed verification/:/Could not load/);
    }
    const body='bodies/sha256/'+'d'.repeat(2)+'/'+'d'.repeat(64)+'.gz';
    const status={version:2,catalog_id:manifest.info.catalog_id,rows:manifest.info.rows,entries:manifest.info.entries,
      source_identity:manifest.source_identity,recoveries:[{recovery_status:'recovered',body_key:body}],
      sources:[[originals[2].source_id,originals[2].document_id,0]],groups:[[originals[2].document_id,[0]]]};
    const raw=JSON.stringify(status),digest=createHash('sha256').update(raw).digest('hex'),statusPath=`releases/${digest.slice(0,32)}/${digest.slice(32)}/viewer-v2/recovery-status.json`;
    const pointer={version:1,catalog_id:manifest.info.catalog_id,manifest:'releases/'+'e'.repeat(32)+'/manifest.json',
      recovery:{path:statusPath,sha256:digest,bytes:Buffer.byteLength(raw)}};
    let pointerReads=0;
    const recovered=await createFilenameCatalog('https://catalog.test/manifest.json',async(url,options)=>{
      const path=new URL(url).pathname.slice(1);
      if(path==='manifest.json'){pointerReads++;return Response.json(pointer);}
      if(path===pointer.manifest)return Response.json(manifest);
      if(path===statusPath)return new Response(raw);
      return localFetch(new URL(path,pathToFileURL(join(folder,'native-public/'))),options);
    });
    assert((await recovered.search({retained:'yes',scope:'all'})).rows.some(row=>row.document_id===originals[2].document_id));
    assert.equal((await recovered.entry(originals[2].source_id)).recovery.body_key,body);
    assert.deepEqual(await recovered.technical(originals[2].source_id,undefined,undefined,true),{...originals[2],recovery:status.recoveries[0]});
    assert.equal(pointerReads,1,'late detail reads stay on their immutable captured generation');
    await assert.rejects(createFilenameCatalog('https://catalog.test/manifest.json',async(url,options)=>{
      if(String(url).endsWith('/manifest.json')){const value=JSON.parse(mixed);value.roots.browse.rows++;return Response.json(value);}
      return localFetch(new URL(new URL(url).pathname.slice(1),pathToFileURL(join(folder,'native-public/'))),options);
    }),/different selected snapshot/);
  }finally{await rm(folder,{recursive:true,force:true});}
});


test('default stable browse downloads only the selected page paths',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-pages-'));
  try{
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../../../../../packages/viewer_publication/tests/native_viewer_fixture.py',import.meta.url)),folder],
      {env:{...process.env,FILENAME_FIXTURE_ROWS:'130'}});
    const requests=[];
    const reader=await createFilenameCatalog(pathToFileURL(join(folder,'native-public/manifest.json')),(url,options)=>{requests.push(String(url));return localFetch(url,options);});
    const result=await reader.search({limit:'2'});
    assert.equal(result.rows.length,2);assert(result.total>2);
    assert(requests.length<=6,`bounded startup + first browse path, got ${requests.length}`);
    assert(!requests.some(url=>url.endsWith('.parquet')),'default browse never opens native source deliveries');
    const last=await reader.search({scope:'all',page:'999',limit:'2'});
    assert.equal(last.page,last.pages);assert.equal(last.total,130);
    assert(!requests.some(url=>url.endsWith('.parquet')));
    const records=JSON.parse(await readFile(join(folder,'source-records.json')));
    const matches=await reader.matchUrls({urls:records.map(row=>row.source_url)});
    assert.equal(matches.matches.length,24);assert.equal(matches.truncated,true);
  }finally{await rm(folder,{recursive:true,force:true});}
});


test('stable filename order follows Arrow code points, including supplementary Unicode',()=>{
  assert(compareBrowseKeys([false,'\ue000.pdf','a'],[false,'🏛️.pdf','b'])<0);
  assert(compareBrowseKeys([false,'A.pdf','a'],[false,'a.pdf','b'])<0);
  assert(compareBrowseKeys([false,'a.pdf','a'],[true,'','b'])<0);
});

for(const occurrences of [false,true])test(`nullable schema additions preserve reused assets${occurrences?' including an absent occurrence field':''}`,async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-schema-'));
  try{
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../../../../../packages/viewer_publication/tests/native_viewer_fixture.py',import.meta.url)),folder],
      {env:{...process.env,FILENAME_FIXTURE_SCHEMA_ADDITION:'1',...(occurrences?{FILENAME_FIXTURE_OCCURRENCE_ADDITION:'1'}:{})}});
    const metrics=JSON.parse(await readFile(join(folder,'nullable-metrics.json')));
    assert.equal(metrics.native_source_leaves_read,1);assert(metrics.source_subtrees_reused>0);
    const reader=await createFilenameCatalog(pathToFileURL(join(folder,'native-expanded/manifest.json')),async(url,options)=>{
      try{return await localFetch(url,options);}catch(error){if(error.code!=='ENOENT')throw error;return localFetch(String(url).replace('/native-expanded/','/native-public/'),options);}
    });
    const sources=JSON.parse(await readFile(join(folder,'expanded-source-records.json'))),documents=JSON.parse(await readFile(join(folder,'expanded-document-records.json')));
    for(const source of sources){
      assert.deepEqual(await reader.technical(source.source_id,undefined,undefined,true),source);
      assert.deepEqual(await reader.documentRecord(source.source_id),documents.find(doc=>doc.document_id===source.document_id));
    }
    const matches=await reader.search({q:'new',field:'source_new_literal',scope:'all'});assert.equal(matches.total,1);
  }finally{await rm(folder,{recursive:true,force:true});}
});


test('split giant document occurrences preserve full values and stay separate from source details',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-giant-document-'));
  try {
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../../../../../packages/viewer_publication/tests/native_viewer_fixture.py',import.meta.url)),folder],
      {env:{...process.env,FILENAME_FIXTURE_GIANT_DOCUMENT:'1'},maxBuffer:1024*1024});
    const sourceRecords=JSON.parse(await readFile(join(folder,'source-records.json')));
    const documentRecords=JSON.parse(await readFile(join(folder,'document-records.json')));
    const expected=documentRecords[0],source=sourceRecords.find(row=>row.document_id===expected.document_id),requests=[];
    const manifestUrl=pathToFileURL(join(folder,'native-public/manifest.json'));
    const reader=await createFilenameCatalog(manifestUrl,(url,options)=>{requests.push(String(url));return localFetch(url,options);});
    await reader.search({scope:'all',limit:'2'});
    await reader.entry(source.source_id);
    assert(!requests.some(path=>path.includes('/documents.parquet')),'ordinary details do not read the complete document');
    const document=await reader.documentRecord(source.source_id);
    assert.deepEqual(document,expected);
    assert.deepEqual(Object.keys(document),Object.keys(expected),'original field order survives reconstruction');
    assert.equal(document.source_occurrences.length,18000);
    assert.deepEqual(await reader.technical(source.source_id,undefined,undefined,true),source);
    const manifest=JSON.parse(await readFile(join(folder,'native-public/manifest.json')));
    const nodes=[];
    async function visit(ref) {
      const node=JSON.parse(await readFile(join(folder,'native-public',ref.path)));
      if(node.kind==='component-leaf')nodes.push(...Object.values(node.members));
      else for(const child of Object.values(node.children??{}))await visit(child);
    }
    await visit(manifest.roots.components);
    const entry=nodes.find(value=>value.key[2]===expected.document_id),files=entry.document_observations.files;
    assert(files.observation_index && files.observations && files.observation_rows);
    assert.equal(files.occurrences,undefined,'document entries use the existing bounded binary observation path');
    const pagedRequests=[];
    const pagedReader=await createFilenameCatalog(manifestUrl,(url,options)=>{pagedRequests.push(String(url));return localFetch(url,options);});
    const docPage=await pagedReader.documentObservationPage(source.source_id,undefined,{offset:0,limit:20});
    assert.equal(docPage.total,18000);
    assert.equal(docPage.items.length,20);
    assert.equal(docPage.next,20);
    assert.equal(docPage.items[0],null);
    assert.deepEqual(docPage.items[1],expected.source_occurrences[1]);
    assert(!pagedRequests.some(path=>path.endsWith('/occurrences.parquet')),'document page uses its existing binary assets');
    assert(pagedReader.diagnostics().maxDecodedPartBytes<=1024*1024,'document observation decode parts remain bounded');
    assert(pagedReader.diagnostics().rangeBytes < 64*1024*1024*0.01,'20-row occurrence slice stays under 1% of 64 MiB worker ceiling');
    const before=requests.length;await reader.documentRecord(source.source_id);
    assert.equal(requests.length,before,'complete repeat reads reuse immutable observation data');
    for(const mode of ['missing','corrupt']) {
      const broken=await createFilenameCatalog(manifestUrl,async(url,options)=>{
        if(String(url).endsWith(files.observations.path)) {
          if(mode==='missing')return new Response('',{status:404});
          return new Response(new Uint8Array(files.observations.bytes),{status:206,
            headers:{'Content-Range':`bytes 0-${files.observations.bytes-1}/${files.observations.bytes}`}});
        }
        return localFetch(url,options);
      });
      await assert.rejects(broken.documentRecord(source.source_id));
      assert((await broken.search({scope:'all'})).rows.length>0,'failed complete read leaves browse usable');
      assert.deepEqual(await broken.technical(source.source_id,undefined,undefined,true),source,'document part failures do not poison source records');
    }
  } finally { await rm(folder,{recursive:true,force:true}); }
});


test('ExportPin manifest serves browse, folded filename_readings, and 33,479-occurrence outlier 20-row page under 1% of 64 MiB ceiling',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'export-pin-viewer-'));
  try {
    const pyScript = `
import hashlib, sys
from pathlib import Path
import pyarrow as pa
from viewer_publication.filename_exports import export_viewer_pins

folder = Path(sys.argv[1])
occ_struct = pa.struct([
    ('source_page_url', pa.list_(pa.string())),
    ('source_page_title', pa.list_(pa.string())),
    ('source_link_label', pa.list_(pa.string())),
    ('source_occurrence_scope', pa.list_(pa.string())),
])
schema = pa.schema([
    ('source_id', pa.string()),
    ('document_id', pa.string()),
    ('filename', pa.string()),
    ('source_url', pa.string()),
    ('body_key', pa.string()),
    ('record_role', pa.list_(pa.string())),
    ('document_kind', pa.list_(pa.string())),
    ('document_family', pa.list_(pa.string())),
    ('format', pa.list_(pa.string())),
    ('congress', pa.list_(pa.string())),
    ('http_status', pa.list_(pa.string())),
    ('response_usable', pa.list_(pa.string())),
    ('raw_leaf', pa.list_(pa.string())),
    ('normalized_leaf', pa.list_(pa.string())),
    ('source_occurrences', pa.list_(occ_struct)),
])
outlier_occs = [
    {
        'source_page_url': [f'https://committee.test/hearing/{i % 100}'],
        'source_page_title': [f'Outlier Hearing Page {i}'],
        'source_link_label': [f'Witness {i}'],
        'source_occurrence_scope': ['anchor'],
    }
    for i in range(33479)
]
s0 = hashlib.sha256(b'outlier-source').hexdigest()
s1 = hashlib.sha256(b'second-source').hexdigest()
rows = [
    {
        'source_id': s0,
        'document_id': 'doc-outlier',
        'filename': 'b_outlier.pdf',
        'source_url': 'https://committee.test/b_outlier.pdf',
        'body_key': None,
        'record_role': ['document'],
        'document_kind': ['witness-statement'],
        'document_family': ['statement'],
        'format': ['pdf'],
        'congress': ['118'],
        'http_status': ['200'],
        'response_usable': ['true'],
        'raw_leaf': ['b_outlier.pdf'],
        'normalized_leaf': ['b_outlier_clean.pdf'],
        'source_occurrences': outlier_occs,
    },
    {
        'source_id': s1,
        'document_id': 'doc-alpha',
        'filename': 'a_first.pdf',
        'source_url': 'https://committee.test/a_first.pdf',
        'body_key': None,
        'record_role': ['document'],
        'document_kind': ['transcript'],
        'document_family': ['hearing'],
        'format': ['pdf'],
        'congress': ['117'],
        'http_status': ['200'],
        'response_usable': ['true'],
        'raw_leaf': ['a_first.pdf'],
        'normalized_leaf': None,
        'source_occurrences': [],
    },
]
table = pa.Table.from_pylist(rows, schema=schema)
export_viewer_pins(table, table, folder, catalog_id='c' * 32)
`;
    execFileSync(process.env.PYTHON||'python3',['-c',pyScript,folder]);
    const manifestJson=JSON.parse(await readFile(join(folder,'manifest.json'),'utf8'));
    assert.equal(manifestJson.exports.sources.child_tables.occurrences.row_slices,undefined,'native ChildTableExport omits row_slices and relies on browse_ranges');
    const requests=[];
    const manifestUrl=pathToFileURL(join(folder,'manifest.json'));
    const reader=await createFilenameCatalog(manifestUrl,(url,options)=>{requests.push(String(url));return localFetch(url,options);});
    const browse=await reader.search({limit:'2'});
    assert.equal(browse.total,2);
    assert.deepEqual(browse.rows.map(r=>r.filename),['a_first.pdf','b_outlier.pdf']);
    const filtered=await reader.search({congress:'118',q:'outlier'});
    assert.equal(filtered.total,1);
    assert.equal(filtered.rows[0].filename,'b_outlier.pdf');
    const outlierId=createHash('sha256').update('outlier-source').digest('hex');
    const detail=await reader.entry(outlierId);
    assert.equal(detail.filename,'b_outlier.pdf');
    assert.equal(detail.observation_count,33479);
    assert.equal(detail.origin_next,20);
    assert.equal(detail.filename_field_count,2);
    assert.deepEqual(detail.record.raw_leaf,['b_outlier.pdf']);
    assert.deepEqual(detail.record.normalized_leaf,['b_outlier_clean.pdf']);
    const page2=await reader.observationPage(outlierId,undefined,{offset:20,limit:20});
    assert.equal(page2.total,33479);
    assert.equal(page2.items.length,20);
    assert.equal(page2.next,40);
    assert.deepEqual(page2.items[0].source_page_title,['Outlier Hearing Page 20']);
    assert(!requests.some(url=>url.endsWith('.bin')),'ExportPin reader never fetches .bin observation files');
    assert(reader.diagnostics().rangeBytes < 64*1024*1024*0.01,`expected < 1% of 64 MiB worker ceiling, got ${reader.diagnostics().rangeBytes} bytes`);
  } finally {
    await rm(folder,{recursive:true,force:true});
  }
});
