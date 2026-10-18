import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createFilenameClient, publicationLifecycle} from './filename-client.mjs';
import {positiveInteger, filenameDate} from '../../../../docs/youtube-coverage/research/filename-rules.mjs';

function harness() {
  const workers = [];
  const client = createFilenameClient({context: {snapshot: 'pinned'}, createWorker() {
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
