import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createFilenameClient, publicationLifecycle} from './client.mjs';
import {positiveInteger, filenameDate} from '../../../../../docs/youtube-coverage/research/filename-rules.mjs';

function harness(context = {snapshot: 'pinned'}, onResult = () => {}) {
  const workers = [];
  const client = createFilenameClient({context, onResult, createWorker() {
    const worker = {messages: [], postMessage(value) { this.messages.push(value); }, terminate() { this.dead = true; }};
    workers.push(worker); return worker;
  }});
  return {client, workers};
}
test('worker failure settles pending calls and retries on a fresh worker', async () => {
  const {client, workers} = harness();
  const one = client.request('/api/info'), two = client.request('/api/rows');
  const rejected = Promise.all([assert.rejects(one,/reader stopped/), assert.rejects(two,/reader stopped/)]);
  workers[0].onerror(); await rejected; assert.equal(client.pendingCount,0);
  const retry = client.request('/api/rows');
  assert.equal(workers.length,2); assert.equal(workers[1].messages[0].snapshot,'pinned');
  workers[0].onmessage({data:{id:3,result:'stale'}});
  workers[1].onmessage({data:{id:3,result:'success'}});
  assert.equal(await retry,'success'); assert.equal(client.pendingCount,0);
  client.dispose(); await assert.rejects(client.request('/api/info'),/reader stopped/);
});
test('ordinary accepted catalog survives pointer advancement and worker recreation', async () => {
  const accepted = 'a'.repeat(32), latest = 'b'.repeat(32), results = [];
  const context = {snapshot: null};
  const {client, workers} = harness(context, result => results.push(result));
  let pointer = accepted;
  const info = client.request('/api/info');
  workers[0].onmessage({data:{id:1,result:{catalog_id:pointer}}});
  assert.equal((await info).catalog_id,accepted);
  pointer = latest;
  workers[0].onerror();
  const retry = client.request('/api/rows');
  const selected = workers[1].messages[0].snapshot || pointer;
  assert.equal(selected,accepted);
  assert.equal(context.snapshot,null,'the caller context remains unchanged');
  workers[0].onmessage({data:{id:2,result:{catalog_id:latest}}});
  workers[1].onmessage({data:{id:2,result:{rows:[selected]}}});
  assert.deepEqual(await retry,{rows:[accepted]});
  const conflict = client.request('/api/info');
  const rejected = assert.rejects(conflict,/different catalog/);
  workers[1].onmessage({data:{id:3,result:{catalog_id:latest}}});
  await rejected;
  assert.equal(results.length,2,'conflicting results never reach the UI');
  const same = client.request('/api/info');
  assert.equal(workers[1].messages.at(-1).snapshot,accepted);
  workers[1].onmessage({data:{id:4,result:{catalog_id:accepted}}});
  await same; client.dispose();
});
test('aborted, stale, missing and malformed catalog replies cannot establish a pin', async () => {
  const accepted='a'.repeat(32), ignored='b'.repeat(32);
  const {client,workers}=harness({snapshot:null});
  const controller=new AbortController(),aborted=client.request('/api/info',controller.signal);
  controller.abort();await assert.rejects(aborted,{name:'AbortError'});
  workers[0].onmessage({data:{id:1,result:{catalog_id:ignored}}});
  for(const identity of [undefined,123,'',ignored.toUpperCase(),'not-a-catalog']) {
    const call=client.request('/api/info');
    const request=workers[0].messages.at(-1);
    assert.equal(request.snapshot,null);
    const rejected=assert.rejects(call,/invalid catalog/);
    workers[0].onmessage({data:{id:request.id,result:{catalog_id:identity}}});
    await rejected;
  }
  workers[0].onerror();
  const info=client.request('/api/info'),request=workers[1].messages[0];
  workers[0].onmessage({data:{id:request.id,result:{catalog_id:ignored}}});
  assert.equal(request.snapshot,null);
  workers[1].onmessage({data:{id:request.id,result:{catalog_id:accepted}}});
  await info;
  const rows=client.request('/api/rows');
  assert.equal(workers[1].messages.at(-1).snapshot,accepted);
  workers[1].onmessage({data:{id:workers[1].messages.at(-1).id,result:{rows:[]}}});
  await rows;client.dispose();
});
test('an explicit catalog remains fixed when a current worker replies with a conflicting identity', async () => {
  const explicit='a'.repeat(32),other='b'.repeat(32);
  const {client,workers}=harness({snapshot:explicit});
  const info=client.request('/api/info'),rejected=assert.rejects(info,/different catalog/);
  workers[0].onmessage({data:{id:1,result:{catalog_id:other}}});
  await rejected;workers[0].onerror();
  const retry=client.request('/api/info');
  assert.equal(workers[1].messages[0].snapshot,explicit);
  workers[1].onmessage({data:{id:2,result:{catalog_id:explicit}}});
  await retry;client.dispose();
});
test('cancel, late replies and throwing postMessage release requests exactly once', async () => {
  const {client,workers} = harness(); const controller = new AbortController();
  const request = client.request('/api/rows',controller.signal);
  controller.abort(); await assert.rejects(request,{name:'AbortError'});
  workers[0].onmessage({data:{id:1,result:'late'}}); assert.equal(client.pendingCount,0);
  workers[0].postMessage=()=>{throw new Error('clone failed');};
  await assert.rejects(client.request('/api/rows'),/clone failed/); assert.equal(client.pendingCount,0);
  const retry=client.request('/api/info');workers[1].onmessage({data:{id:3,error:'unavailable'}});
  await assert.rejects(retry,/unavailable/);assert.equal(client.pendingCount,0);
});
test('persisted restore owns one watcher and permanent unload disposes it', () => {
  const win=new EventTarget();let starts=0,stops=0;
  const lifecycle=publicationLifecycle({window:win,start:identity=>{assert.equal(identity.catalog_id,'pinned');starts++;return ()=>stops++;}});
  lifecycle.accept({catalog_id:'pinned'});lifecycle.accept({catalog_id:'pinned'});assert.equal(starts,1);
  win.dispatchEvent(Object.assign(new Event('pagehide'),{persisted:true}));assert.equal(stops,1);
  win.dispatchEvent(new Event('pageshow'));win.dispatchEvent(new Event('pageshow'));assert.equal(starts,2);
  win.dispatchEvent(Object.assign(new Event('pagehide'),{persisted:false}));assert.equal(stops,2);
  win.dispatchEvent(new Event('pageshow'));assert.equal(starts,2);
});
test('page and limit share a positive finite floor-and-clamp rule',()=>{
  for(const value of ['NaN','Infinity',Infinity,-1,0,'',null])assert.equal(positiveInteger(value,50,100),50);
  assert.equal(positiveInteger('2.9'),2);assert.equal(positiveInteger(1e30,1,100),100);
  assert.equal(filenameDate('2023-02-29'),'2023-02-29');assert.equal(filenameDate('2024-02-30'),'2024-02-30');
  assert.match(filenameDate('2024-02-29'),/February 29, 2024/);assert.match(filenameDate('2024-01-01'),/January 1, 2024/);
});
