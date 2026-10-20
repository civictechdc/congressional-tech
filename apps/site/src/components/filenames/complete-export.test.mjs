import {test} from 'node:test';
import assert from 'node:assert/strict';
import {brotliCompressSync} from 'node:zlib';
import {observationReader} from './observations.mjs';

function packed(rows) {
  const raw=Buffer.from(JSON.stringify(rows)),bytes=brotliCompressSync(raw);
  return {descriptor:{rows:rows.length,blocks:[{start:0,count:rows.length,parts:[[0,bytes.length,raw.length]]}]},
    file:{slice:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)}};
}

test('observation allocation failure rejects exact read with Parquet recovery and retries without truncation',async()=>{
  const data=packed([{label:['José 🏛️'],empty:[]},null,{}]),refs=packed([[0,0,1,2],[],null]);
  const slice=data.file.slice;let fail=true;
  data.file.slice=async(...args)=>{if(fail)throw new RangeError('Injected allocation failure');return slice(...args);};
  const reader=observationReader({version:1,max_part_bytes:1024,fields:['label','empty','missing'],observations:data.descriptor,references:refs.descriptor},data.file,refs.file);
  await assert.rejects(reader.read(0),/exceeds available browser memory.*Download the source Parquet/);
  fail=false;
  const full=await reader.read(0);
  assert.deepEqual(full,[{label:['José 🏛️'],empty:[],missing:null},{label:['José 🏛️'],empty:[],missing:null},null,{label:null,empty:null,missing:null}]);
  assert.strictEqual(full[0],full[1]);assert.deepEqual(await reader.read(1),[]);assert.equal(await reader.read(2),null);
});
