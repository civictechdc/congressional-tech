import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {loadRecoveries, recoveryStartupPolicy} from './recoveries.ts';

const info = {catalog_id: 'pair', rows: 3, entries: 2};
const fixture = () => ({version: 1, ...info, recoveries: [{recovery_status: 'recovered', original_url: 'https://source.test/a.pdf'}], sources: [[1, 0]], groups: [[0, [0]]]});
function input(data = fixture()) {
  const bytes = Buffer.from(JSON.stringify(data));
  return {bytes, descriptor: {url: 'https://data.test/recovery', bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')}};
}
const load = ({descriptor, bytes}, fetcher = async () => new Response(bytes), policy) => loadRecoveries(descriptor, info, fetcher, policy);
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('absent recovery is valid without fetching; present recovery preserves exact maps', async () => {
  assert.deepEqual(await loadRecoveries(null, info, () => assert.fail('unexpected fetch')), {sources: new Map(), groups: new Map()});
  const result = await load(input());
  assert.deepEqual([...result.sources.keys()], [1]);
  assert.deepEqual([...result.groups.keys()], [0]);
  assert.equal(result.sources.get(1), result.groups.get(0)[0]);
  assert.deepEqual(result.sources.get(1), fixture().recoveries[0]);
});

test('descriptor byte admission rejects invalid and excessive lengths before fetch', async () => {
  for (const bytes of [0, -1, 1.5, NaN, Number.MAX_SAFE_INTEGER + 1, recoveryStartupPolicy.maxBytes + 1]) {
    const value = input(); value.descriptor.bytes = bytes;
    await assert.rejects(load(value, () => assert.fail('inadmissible descriptor fetched')), /byte limit/);
  }
  await assert.rejects(load(input(), undefined, {deadlineMs: 0}), /startup policy/);
});

test('exact decoded bytes remain authority for encoded and CORS headers', async () => {
  for (const variant of ['gzip', 'cors-hidden-encoding', 'cors-no-length', 'identity']) {
    const value = input();
    const result = await load(value, async () => {
      const headers = variant === 'cors-no-length' ? {} : {'Content-Length': variant === 'identity' ? String(value.bytes.length) : '12'};
      if (variant === 'gzip') headers['Content-Encoding'] = 'gzip';
      const response = new Response(value.bytes, {headers});
      return variant.startsWith('cors') ? {type: 'cors', ok: true, headers: response.headers, body: response.body} : response;
    });
    assert.equal(result.sources.size, 1, variant);
  }
});

test('identity header mismatch and HTTP failure cancel without waiting on cleanup', async () => {
  for (const status of [200, 503]) {
    let cancels = 0;
    const response = new Response(new ReadableStream({cancel() { cancels++; return new Promise(() => {}); }}),
      {status, headers: {'Content-Length': String(recoveryStartupPolicy.maxBytes + 1)}});
    await assert.rejects(load(input(), async () => response), status === 200 ? /unexpected response length/ : /Could not load/);
    assert.equal(cancels, 1);
  }
});

test('stream overrun consumes only the failing chunk, cancels and releases its reader', async () => {
  const value = input(); let reads = 0, cancels = 0;
  const response = new Response(new ReadableStream({
    pull(controller) { reads++; controller.enqueue(new Uint8Array(value.bytes.length + 1)); },
    cancel() { cancels++; return new Promise(() => {}); },
  }, {highWaterMark: 0}));
  await assert.rejects(load(value, async () => response), /expected response length/);
  assert.equal(reads, 1); assert.equal(cancels, 1); assert.equal(response.body.locked, false);
});

test('short, corrupt, malformed and mismatched recovery input always rejects', async () => {
  const value = input();
  await assert.rejects(load(value, async () => new Response(value.bytes.subarray(1))), /failed verification/);
  value.descriptor.sha256 = '0'.repeat(64);
  await assert.rejects(load(value), /failed verification/);
  const malformed = input(); malformed.bytes = Buffer.from('{');
  malformed.descriptor.bytes = 1; malformed.descriptor.sha256 = createHash('sha256').update(malformed.bytes).digest('hex');
  await assert.rejects(load(malformed), SyntaxError);
  for (const change of [data => data.catalog_id = 'other', data => data.rows++, data => data.entries++, data => data.version++,
    data => data.sources.push([1, 0]), data => data.sources[0][0] = 3, data => data.groups[0][0] = -1,
    data => data.groups[0][1] = [], data => data.sources[0][1] = 99, data => data.recoveries[0].recovery_status = 'pending']) {
    const data = fixture(); change(data); await assert.rejects(load(input(data)));
  }
});

test('deadline settles ignored fetch abort and cancels a late response', async () => {
  let finish, signal, cancels = 0;
  const started = performance.now();
  await assert.rejects(load(input(), (_url, options) => {
    signal = options.signal; return new Promise(resolve => { finish = resolve; });
  }, {deadlineMs: 15}), /startup deadline/);
  assert.equal(signal.aborted, true); assert.ok(performance.now() - started < 500);
  finish(new Response(new ReadableStream({cancel() { cancels++; }})));
  await tick(); assert.equal(cancels, 1);
});

test('deadline settles a hung read even when cancellation never finishes', async () => {
  let signal, cancels = 0;
  const response = new Response(new ReadableStream({cancel() { cancels++; return new Promise(() => {}); }}));
  await assert.rejects(load(input(), (_url, options) => { signal = options.signal; return response; }, {deadlineMs: 15}), /startup deadline/);
  assert.equal(signal.aborted, true); assert.equal(cancels, 1); assert.equal(response.body.locked, false);
});

test('caller cancellation propagates its reason and clears transport ownership', async () => {
  const caller = new AbortController(), reason = new Error('caller canceled recovery');
  let signal, cancels = 0;
  const response = new Response(new ReadableStream({cancel() { cancels++; }}));
  const pending = load(input(), (_url, options) => { signal = options.signal; return response; }, {signal: caller.signal});
  await tick(); caller.abort(reason);
  await assert.rejects(pending, error => error === reason);
  assert.equal(signal.aborted, true); assert.equal(cancels, 1); assert.equal(response.body.locked, false);
  await assert.rejects(load(input(), () => assert.fail('already-canceled fetch'), {signal: caller.signal}), error => error === reason);
});

test('the real worker reports mandatory recovery initialization failure', {timeout: 2000}, async () => {
  const {Worker} = await import('node:worker_threads');
  const workerUrl = new URL('./worker.ts', import.meta.url).href;
  const sidecar = input(), sha256 = '0'.repeat(64);
  const pointer = {version: 1, catalog_id: info.catalog_id, manifest: `releases/${'a'.repeat(32)}/manifest.json`,
    recovery: {...sidecar.descriptor, sha256, path: `releases/${sha256.slice(0,32)}/${sha256.slice(32)}/viewer-v2/recovery-status.json`}};
  const worker = new Worker(new URL('data:text/javascript,' + encodeURIComponent(`
    import {parentPort} from 'node:worker_threads';
    globalThis.self=globalThis;self.postMessage=value=>parentPort.postMessage(value);
    globalThis.fetch=async url=>{
      if(String(url)==='https://data.test/manifest.json')return Response.json(${JSON.stringify(pointer)});
      if(String(url).endsWith('/recovery-status.json'))return new Response(${JSON.stringify(sidecar.bytes.toString())});
      return Response.json({version:2,info:${JSON.stringify(info)},files:{}});
    };
    await import(${JSON.stringify(workerUrl)});
    parentPort.on('message',data=>self.onmessage({data}));parentPort.postMessage({ready:true});
  `)), {type: 'module'});
  try {
    await new Promise((resolve,reject)=>{worker.once('message',resolve);worker.once('error',reject);});
    const reply = new Promise((resolve,reject)=>{worker.once('message',resolve);worker.once('error',reject);});
    worker.postMessage({id:1,url:'/api/info',manifest:'https://data.test/manifest.json'});
    const result=await reply;
    assert.equal(result.id,1);assert.match(result.error,/failed verification/);assert.equal('result' in result,false);
  } finally {await worker.terminate();}
});

test('stable recovery maps bind exact selection and complete source/document membership',async()=>{
  const identity={selector_sha256:'a'.repeat(64),selected_ref:{key:'selected',sha256:'b'.repeat(64),bytes:50}},source='c'.repeat(64);
  const stable={...fixture(),version:2,source_identity:identity,sources:[[source,'document',0]],groups:[['document',[0]]]};
  const value=input(stable),result=await load(value,undefined,{sourceIdentity:{selected_ref:identity.selected_ref,selector_sha256:identity.selector_sha256}});
  assert.deepEqual([...result.sources.keys()],[source]);assert.deepEqual([...result.groups.keys()],['document']);
  for(const damage of [data=>data.source_identity={...identity,selector_sha256:'wrong'},data=>data.sources[0][1]='other',data=>data.sources.push(data.sources[0]),data=>data.groups[0][1]=[0,0]]){
    const data=structuredClone(stable);damage(data);await assert.rejects(load(input(data),undefined,{sourceIdentity:identity}),/snapshot|membership|position|group/);
  }
  await assert.rejects(load(value),/different catalog/,'historical publications require their positional v1 status');
});
