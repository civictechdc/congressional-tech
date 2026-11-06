/** Exercise maintained lookup with pinned local bytes; used for release qualification. */
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {openArchive} from '../src/components/explorer/reader/archive.ts';

export async function verifyUrlLookups(reader, cases) {
  const results=[];
  for (const item of cases) {
    const before={...reader.metrics}, started=performance.now();
    const rows=(await reader.lookup(item.url)).map(row=>row.list_row).sort((a,b)=>a-b);
    const elapsedMs=performance.now()-started;
    assert.deepEqual(rows,[...item.expected_rows].sort((a,b)=>a-b),JSON.stringify(item));
    if(item.check_page) {
      const page=await reader.lookupRows(item.url,{includeHidden:true,...item.query});
      const expected=item.expected_page_rows??rows;
      assert.equal(page.total,expected.length);
      assert.deepEqual(page.rows.map(row=>row.list_row).sort((a,b)=>a-b),expected);
    }
    results.push({kind:item.kind, url:item.url, rows, elapsedMs,
      rangeRequests:reader.metrics.rangeRequests-before.rangeRequests,
      rangeBytes:reader.metrics.rangeBytes-before.rangeBytes});
  }
  return results;
}

export async function verifyLocalUrlLookups(selection, cases) {
  const manifest=selection.manifest;
  const fetcher=async(url,options={})=>{
    const name=new URL(url).pathname.split('/').at(-1);
    if(name==='manifest.json')return Response.json(new URL(url).pathname==='/manifest.json'
      ? {release_id:manifest.release_id} : manifest);
    const bytes=await readFile(selection.files[name]);
    if(!options.headers?.Range)return new Response(bytes);
    const [start,end]=options.headers.Range.slice(6).split('-').map(Number);
    return new Response(bytes.subarray(start,end+1),{status:206,
      headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
  };
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
  const cold=await verifyUrlLookups(reader,cases);
  const warm=await verifyUrlLookups(reader,cases);
  return {releaseId:reader.releaseId,cold,warm,metrics:reader.metrics};
}

if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const [selectionPath,casesPath,output]=process.argv.slice(2);
  const result=await verifyLocalUrlLookups(JSON.parse(await readFile(selectionPath)),JSON.parse(await readFile(casesPath)));
  if(output)await writeFile(output,JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({releaseId:result.releaseId,cases:result.cold.length,metrics:result.metrics}));
}
