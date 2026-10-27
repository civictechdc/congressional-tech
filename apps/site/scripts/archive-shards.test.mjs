import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const folder=process.env.ARCHIVE_FIXTURE,manifest=JSON.parse(await readFile(join(folder,'manifest.json')));
const fetcher=async(url,options={})=>{
  if(new URL(url).pathname==='/manifest.json')return Response.json({release_id:manifest.release_id});
  const bytes=await readFile(join(folder,new URL(url).pathname.split('/').at(-1))),range=options.headers?.Range;
  if(!range)return new Response(bytes);const [start,end]=range.slice(6).split('-').map(Number);
  return new Response(bytes.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
};
test('native nonzero detail shards and cross-shard source ranges preserve attachments',async()=>{
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
  const entry=await reader.entry(4);assert.equal(entry.document.filename,'Record.pdf');assert.equal(entry.sources.length,2);assert(entry.sources.every(source=>source.list_row===4));
  const cross=await reader.entry(1);assert.equal(cross.sources.length,2);assert.deepEqual(cross.sources.map(source=>source.ordinal),[0,1]);assert(cross.sources.every(source=>source.list_row===1));
});
