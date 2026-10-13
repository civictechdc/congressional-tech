import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';

const path = `releases/${'a'.repeat(32)}/${'b'.repeat(32)}/viewer-v2/browse.parquet`;
test('only viewer publication paths are readable and writes never reach R2', async () => {
  const env = {PUBLICATIONS: {get() {throw new Error('Archive access attempted');}}};
  for (const value of ['indexes/catalog.json', 'bodies/file', 'receipts/file', 'manifest.json/../indexes/catalog.json', '%2e%2e/indexes/catalog.json']) {
    assert.equal((await worker.fetch(new Request('https://data.test/' + value), env)).status, 404);
  }
  assert.equal((await worker.fetch(new Request('https://data.test/manifest.json', {method: 'PUT', body: 'bad'}), env)).status, 405);
  assert.equal((await worker.fetch(new Request('https://data.test/' + path, {method: 'OPTIONS'}), env)).status, 204);
});
test('range responses stream exact bytes and expose validation headers across origins', async () => {
  const env = {PUBLICATIONS: {async get(key, options) {
    assert.equal(key, 'viewer-publications/' + path);
    assert.equal(options.range.get('Range'), 'bytes=2-4');
    return {body: new Blob(['abc']).stream(), size: 10, range: {offset: 2, length: 3},
      httpEtag: '"digest"', uploaded: new Date('2026-10-13'), writeHttpMetadata(h) {h.set('Content-Type', 'application/octet-stream');}};
  }}};
  const response = await worker.fetch(new Request('https://data.test/' + path, {headers: {Range: 'bytes=2-4'}}), env);
  assert.equal(response.status, 206);
  assert.equal(response.headers.get('Content-Range'), 'bytes 2-4/10');
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), '*');
  assert.match(response.headers.get('Access-Control-Expose-Headers'), /Content-Range/);
  assert.match(response.headers.get('Cache-Control'), /immutable/);
  assert.equal(await response.text(), 'abc');
});
test('latest pointer is never cached, and HEAD does not read a body', async () => {
  const env = {PUBLICATIONS: {async head(key) {
    assert.equal(key, 'viewer-publications/manifest.json');
    return {size: 8, httpEtag: '"id"', uploaded: new Date(), writeHttpMetadata() {}};
  }}};
  const response = await worker.fetch(new Request('https://data.test/manifest.json', {method: 'HEAD'}), env);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(await response.text(), '');
});
