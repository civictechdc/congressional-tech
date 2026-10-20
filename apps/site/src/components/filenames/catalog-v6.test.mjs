import {createHash} from 'node:crypto';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtemp,readFile,open,stat,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {createFilenameCatalog} from './catalog.mjs';
import {compareBrowseKeys} from './catalog-v6.mjs';

async function localFetch(url,options={}) {
  options.signal?.throwIfAborted();
  if(!options.headers?.Range)return new Response(await readFile(new URL(url)));
  const [start,end]=options.headers.Range.slice(6).split('-').map(Number), handle=await open(new URL(url));
  try{const bytes=Buffer.alloc(end-start+1);await handle.read(bytes,0,bytes.length,start);return new Response(bytes,{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${(await stat(new URL(url))).size}`}});}finally{await handle.close();}
}
const comparable = rows => rows.map(row=>{
  const result={...row};for(const name of ['_row','source_id','document_id'])delete result[name];return result;
});

test('stable browser agrees with maintained search and preserves complete original records',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-viewer-'));
  try{
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../tests/native_viewer_fixture.py',import.meta.url)),folder]);
    const old=await createFilenameCatalog(pathToFileURL(join(folder,'public/manifest.json')),localFetch),requests=[];
    const reader=await createFilenameCatalog(pathToFileURL(join(folder,'native-public/manifest.json')),(url,options)=>{requests.push(String(url));return localFetch(url,options);});
    assert.equal(requests.length,3,'startup only reads manifest and two bounded proof pages');
    const expected=JSON.parse(await readFile(join(folder,'expected.json')));
    for(const {query}of expected){
      const before=await old.search(query),after=await reader.search(query);
      assert.deepEqual({...after,rows:comparable(after.rows)},{...before,rows:comparable(before.rows)},JSON.stringify(query));
      assert(after.rows.every(row=>row._row===row.source_id),'new results use stable source IDs');
    }
    const originals=JSON.parse(await readFile(join(folder,'source-records.json')));
    const documents=JSON.parse(await readFile(join(folder,'document-records.json')));
    for(const source of originals){
      assert.deepEqual(await reader.documentRecord(source.source_id),documents.find(row=>row.document_id===source.document_id));
      assert.deepEqual(await reader.technical(source.source_id,undefined,undefined,true),source);
      const entry=await reader.entry(source.source_id),historical=await old.entry(source.source_id);
      assert.deepEqual(entry.record,historical.record);
      assert.deepEqual(entry.facts,historical.facts);
      assert.deepEqual(entry.sources,historical.sources);
      assert.deepEqual(entry.origin,historical.origin);
      assert.deepEqual(entry.document_origin,historical.document_origin);
      assert.equal(entry.filename,historical.filename);
    }
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
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../tests/native_viewer_fixture.py',import.meta.url)),folder],
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
  }finally{await rm(folder,{recursive:true,force:true});}
});


test('stable filename order follows Arrow code points, including supplementary Unicode',()=>{
  assert(compareBrowseKeys([false,'\ue000.pdf','a'],[false,'🏛️.pdf','b'])<0);
  assert(compareBrowseKeys([false,'A.pdf','a'],[false,'a.pdf','b'])<0);
  assert(compareBrowseKeys([false,'a.pdf','a'],[true,'','b'])<0);
});

test('nullable schema additions preserve reused document assets and declare missing values as null',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'stable-schema-'));
  try{
    execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../tests/native_viewer_fixture.py',import.meta.url)),folder],
      {env:{...process.env,FILENAME_FIXTURE_SCHEMA_ADDITION:'1'}});
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
