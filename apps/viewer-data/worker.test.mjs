import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker from './worker.mjs';
import {gzipSync} from 'node:zlib';

const path = `releases/${'a'.repeat(32)}/${'b'.repeat(32)}/viewer-v2/browse.parquet`;
test('all published table and navigation filenames are readable', async () => {
  const env = {PUBLICATIONS: {async head() {
    return {size: 8, httpEtag: '"id"', uploaded: new Date(), writeHttpMetadata() {}};
  }}};
  for (const filename of ['browse.parquet', 'documents.parquet', 'filenames.parquet',
    'document-summaries.parquet', 'document_rows.bin', 'flags.bin', 'groups.bin',
    'preferred.bin', 'observation-index.json', 'observation-rows.bin', 'observations.bin',
    'ids/00.bin', 'ids/ff.bin']) {
    const request = new Request('https://data.test/' + path.replace('browse.parquet', filename), {method: 'HEAD'});
    assert.equal((await worker.fetch(request, env)).status, 200, filename);
  }
});
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

const hash = 'a'.repeat(64);
const savedUrl = `https://data.test/saved/${hash}/Testimony.pdf`;
function savedEnv(contents) {
  return {PUBLICATIONS: {async get(key, options) {
    assert.equal(key, `bodies/sha256/aa/${hash}.gz`);
    assert.equal(options, undefined, 'decoded-file ranges must not reach compressed storage');
    return {body: new Blob([gzipSync(contents)]).stream(), httpEtag: '"body"', uploaded: new Date('2026-10-14')};
  }}};
}
test('saved PDFs stream decoded bytes, including when a reader requests a range', async () => {
  const contents = '%PDF-1.7\n' + 'test content'.repeat(20000);
  const response = await worker.fetch(new Request(savedUrl, {headers: {Range: 'bytes=0-99'}}), savedEnv(contents));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Content-Type'), 'application/pdf');
  assert.equal(response.headers.get('Content-Security-Policy'), null);
  assert.match(response.headers.get('Content-Disposition'), /^inline;.*Testimony.pdf$/);
  assert.equal(response.headers.get('Content-Length'), null);
  assert.equal(response.headers.get('Content-Encoding'), null);
  assert.equal(response.headers.get('Accept-Ranges'), 'none');
  assert.equal(await response.text(), contents);
});
test('saved HTML cannot execute on the data host, even with a misleading PDF filename', async () => {
  const contents = '<html><script>alert(1)</script></html>';
  const response = await worker.fetch(new Request(savedUrl), savedEnv(contents));
  assert.equal(response.headers.get('Content-Type'), 'application/octet-stream');
  assert.match(response.headers.get('Content-Disposition'), /^attachment;/);
  assert.match(response.headers.get('Content-Security-Policy'), /sandbox; default-src 'none'/);
  assert.equal(await response.text(), contents);
});
test('saved copies handle HEAD, revalidation, missing objects and malformed paths', async () => {
  const head = await worker.fetch(new Request(savedUrl, {method: 'HEAD'}), savedEnv('%PDF-1.7\n'));
  assert.equal(head.headers.get('Content-Type'), 'application/pdf');
  assert.equal(await head.text(), '');
  const cached = await worker.fetch(new Request(savedUrl, {headers: {'If-None-Match': '"body"'}}), savedEnv('unchanged'));
  assert.equal(cached.status, 304);
  const missing = await worker.fetch(new Request(savedUrl), {PUBLICATIONS: {get: async () => null}});
  assert.equal(missing.status, 404);
  assert.equal(missing.headers.get('Cache-Control'), 'no-store');
  const never = {PUBLICATIONS: {get() {throw new Error('Invalid access');}}};
  for (const path of ['saved/short/file', `saved/${hash}/file/extra`, `saved/${hash}/%FF`, `bodies/sha256/aa/${hash}.gz`]) {
    assert.ok([400, 404].includes((await worker.fetch(new Request('https://data.test/' + path), never)).status));
  }
  assert.equal((await worker.fetch(new Request(savedUrl, {method: 'PUT', body: 'bad'}), never)).status, 405);
});
