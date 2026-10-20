/** Bounded complete-value/Blob comparison through the maintained observation reader. */
import assert from 'node:assert/strict';
import {brotliCompressSync} from 'node:zlib';
import {createHash} from 'node:crypto';
import {readFile, writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {observationReader} from '../../../apps/site/src/components/explorer/reader/filenames/observations.ts';
import {byteCache, retainedBytes} from '../../../apps/site/src/components/explorer/reader/filenames/cache.ts';

const destination = process.argv[2];
if (!destination) throw new Error('Usage: node --expose-gc complete-export-benchmark.mjs OUTPUT');
const sha = value => createHash('sha256').update(value).digest('hex');
const memory = () => {global.gc?.();return process.memoryUsage();};
const fields = ['label', 'empty', 'missing', 'nested'];
function packed(rows) {
  const raw = Buffer.from(JSON.stringify(rows)), parts = [], chunks = [];let offset = 0;
  for(let start = 0;start < raw.length;start += 65537) {
    const piece = raw.subarray(start,start + 65537), compressed = brotliCompressSync(piece);
    parts.push([offset,compressed.length,piece.length]);chunks.push(compressed);offset += compressed.length;
  }
  const bytes = Buffer.concat(chunks);
  return {rawBytes:raw.length,descriptor:{rows:rows.length,blocks:[{start:0,count:rows.length,parts}]},
    file:{slice:async(start,end)=>bytes.buffer.slice(bytes.byteOffset+start,bytes.byteOffset+end)}};
}
function fixture() {
  const text = 'José 🏛️ '.repeat(1_200_000);
  const rows = [{label:[text],empty:[],nested:{z:[null,[],{literal:'é 🏛️'}],a:false}},
    {label:['duplicate'],empty:[],nested:{}}, null, {}];
  const restored = rows.map(row=>row===null?null:Object.fromEntries(fields.map(key=>[key,row[key]??null])));
  const expected = {filename:'exact José 🏛️.json',missing:null,empty:[],source_occurrences:[restored[0],restored[1],restored[1],null,restored[3]]};
  return {data:packed(rows),refs:packed([[0,1,1,2,3],[],null]),expectedSha256:sha(JSON.stringify(expected))};
}
const deadline = setTimeout(()=>{console.error('30 second action deadline exceeded');process.exit(2);},30_000);
const watcher = setInterval(()=>{if(process.memoryUsage().rss>1024**3){console.error('1 GiB RSS ceiling exceeded');process.exit(2);}},20);
const start = performance.now(), input = fixture();
assert(input.data.rawBytes+input.refs.rawBytes<=20*1024**2);
const index = {version:1,max_part_bytes:65537,fields,observations:input.data.descriptor,references:input.refs.descriptor};
const metrics={},cache=byteCache(1024**2),reader=observationReader(index,input.data.file,input.refs.file,{metrics,cache});
const stages={fixture:memory()};
const pageStarted=performance.now(), page=await reader.page(0,{limit:2});
assert.equal(page.total,5);assert.equal(page.next,2);assert.equal(page.items.length,2);
assert(metrics.oversizedLogicalDecodes>0,'16 MiB remains accounting, not rejection');
stages.page=memory();
const fullStarted=performance.now(), observations=await reader.read(0);
assert.deepEqual(await reader.read(1),[]);assert.equal(await reader.read(2),null);
assert.strictEqual(observations[1],observations[2]);assert.equal(observations[3],null);
assert.deepEqual(Object.keys(observations[0]),fields);assert.deepEqual(observations[0].empty,[]);assert.equal(observations[0].missing,null);
const full={filename:'exact José 🏛️.json',missing:null,empty:[],source_occurrences:observations};
assert.equal(sha(JSON.stringify(full)),input.expectedSha256);
stages.full=memory();
const clone=structuredClone(full);assert.deepEqual(clone,full);assert.strictEqual(clone.source_occurrences[1],clone.source_occurrences[2]);
stages.clone=memory();
const formatted=JSON.stringify(clone,null,2);assert.equal(sha(JSON.stringify(JSON.parse(formatted))),input.expectedSha256);
stages.formatted=memory();
const blobStarted=performance.now(), blob=new Blob([formatted],{type:'application/json'});
assert.equal(blob.size,Buffer.byteLength(formatted));
stages.blob=memory();
// The fixture's owner keeps values alive to make coexistence explicit. These
// value models share some strings/objects; do not sum decoder categories as RSS.
const baselineKnownBytes=retainedBytes(full)+retainedBytes(clone)+formatted.length*2;
const candidateKnownBytes=baselineKnownBytes+blob.size;
const report={version:1,head:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,
 sourceSha256:sha(await readFile(new URL('../../../apps/site/src/components/explorer/reader/filenames/observations.ts',import.meta.url))),
 fixture:{serializedBytes:input.data.rawBytes+input.refs.rawBytes,observations:4,sources:3,selectedReferences:5,expectedSha256:input.expectedSha256},
 metrics,retainedCache:cache.stats,stages,estimates:{restoredPage:retainedBytes(page),fullResult:retainedBytes(full),workerClone:retainedBytes(clone),formattedUtf16:formatted.length*2,formattedUtf8:Buffer.byteLength(formatted),blobBytes:blob.size,baselineKnownBytes,candidateKnownBytes,candidateRatio:candidateKnownBytes/baselineKnownBytes},
 elapsedMs:performance.now()-start,phaseStartMarkers:{page:pageStarted-start,full:fullStarted-start,blob:blobStarted-start},peakRssBytes:process.resourceUsage().maxRSS*1024,
 checks:{exactValues:true,fieldOrder:true,nullEmptyNestedUnicode:true,duplicateReferences:true,over16MiBNotRejected:true,noJoinedDecodedBytes:metrics.joinedDecodedBytes===0},
 decision:'retain_exact_copy_and_existing_parquet_recovery',clipboardAllocation:'unknown; no clipboard API invoked'};
assert(report.peakRssBytes<1024**3);assert(report.elapsedMs<30_000);assert(metrics.maxDecodedPartBytes<=65537);assert.equal(metrics.joinedDecodedBytes,0);
clearInterval(watcher);clearTimeout(deadline);
await writeFile(destination,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({elapsedMs:report.elapsedMs,peakRssBytes:report.peakRssBytes,estimates:report.estimates,checks:report.checks}));
