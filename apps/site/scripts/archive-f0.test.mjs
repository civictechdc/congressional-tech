import {test} from 'node:test';
import assert from 'node:assert/strict';
import {open,readFile,stat} from 'node:fs/promises';
import {join} from 'node:path';
import {asyncBufferFromFile,parquetMetadataAsync} from 'hyparquet';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const folder=process.env.ARCHIVE_F0;
const manifest=JSON.parse(await readFile(join(folder,'manifest.json')));
const requests=[];
async function localFetch(url,options={}){
  const path=new URL(url).pathname;
  if(path==='/manifest.json')return Response.json({release_id:manifest.release_id});
  const file=join(folder,path.split('/').at(-1)),range=options.headers?.Range;
  if(!range)return new Response(await readFile(file));
  const [start,end]=range.slice(6).split('-').map(Number),item={path,start,end,began:performance.now(),ended:0};requests.push(item);
  const handle=await open(file);try{
    const bytes=Buffer.alloc(end-start+1);const result=await handle.read(bytes,0,bytes.length,start);assert.equal(result.bytesRead,bytes.length);
    // Model round trips, retaining real native file bytes and the actual Range protocol.
    await new Promise(resolve=>setTimeout(resolve,5));item.ended=performance.now();
    return new Response(bytes,{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${(await stat(file)).size}`}});
  }finally{await handle.close();}
}
test('F0 indexes retain warm detail reads on different pages under cache pressure',async()=>{
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:localFetch,heapBytes:512*1024*1024,cacheBytes:1024*1024});
  assert.equal(reader.count,manifest.files.find(item=>item.name==='list.parquet').rows);
  assert(reader.count>4096,'The full fixture must cover several native 1024-row pages.');
  await reader.entry(0);
  const metadata=await parquetMetadataAsync(await asyncBufferFromFile(join(folder,'detail.parquet')));
  const dictionaries=metadata.row_groups[0].columns.map(item=>item.meta_data).filter(item=>item.dictionary_page_offset!=null).map(item=>[Number(item.dictionary_page_offset),Number(item.data_page_offset)]);
  for(const index of [2048,4096,0]){
    const before=requests.length;await reader.entry(index);
    const pages=requests.slice(before).filter(item=>item.path.endsWith('/detail.parquet'));
    for(const page of pages)assert(!dictionaries.some(([start,end])=>page.start<end&&page.end+1>start),'A warmed dictionary is never fetched again, including when revisiting page zero.');
    assert(pages.length>0,'A different detail page requires native data bytes.');
    assert(Math.max(...pages.map(item=>item.began))<Math.min(...pages.map(item=>item.ended)),'Warmed detail fetches share one concurrent round trip; indexes and dictionaries stay retained.');
  }
  const versions=await reader.search({text:'hearing',limit:10});assert(versions.total>0);
  console.log(JSON.stringify({releaseId:reader.releaseId,count:reader.count,metrics:reader.metrics}));
});
