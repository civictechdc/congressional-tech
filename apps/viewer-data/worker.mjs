// Read-only access to viewer publications and content-addressed saved copies.
const publicationPath = /^(?:manifest\.json|catalogs\/[a-f0-9]{32}\.json|releases\/[a-f0-9]{32}\/(?:manifest\.json|[a-f0-9]{32}\/viewer-v2\/(?:[a-z_-]+\.(?:parquet|bin|json)|ids\/[a-f0-9]{2}\.bin)))$/;
const prefix = 'viewer-publications/';

async function savedCopy(request, env, headers, match) {
  const [, hash, encodedName] = match;
  let name;
  try { name = decodeURIComponent(encodedName).replace(/[\x00-\x1f\x7f/\\]/g, '_').slice(0, 200); }
  catch { return new Response('Invalid filename', {status: 400, headers}); }
  // Hashes are already published. This route never serves receipts or indexes.
  const object = await env.PUBLICATIONS.get(`bodies/sha256/${hash.slice(0, 2)}/${hash}.gz`);
  if (!object) return new Response('Saved copy not found', {status: 404, headers});
  headers.set('ETag', object.httpEtag);
  headers.set('Last-Modified', object.uploaded.toUTCString());
  headers.set('Cache-Control', 'public, max-age=31536000, immutable');
  // Compressed-storage offsets do not describe offsets in the decoded file.
  headers.set('Accept-Ranges', 'none');
  if (request.headers.get('If-None-Match') === object.httpEtag) {
    await object.body.cancel();
    return new Response(null, {status: 304, headers});
  }
  const reader = object.body.pipeThrough(new DecompressionStream('gzip')).getReader();
  const initial = []; let signature = '';
  try {
    while (signature.length < 5) {
      const {value, done} = await reader.read();
      if (done) break;
      initial.push(value);
      signature += new TextDecoder().decode(value.subarray(0, 5 - signature.length));
    }
  } catch {
    await reader.cancel().catch(() => {});
    headers.set('Cache-Control', 'no-store');
    return new Response('Saved copy could not be decoded', {status: 502, headers});
  }
  const pdf = signature === '%PDF-';
  // Sandboxing a PDF response prevents Chromium's built-in reader from opening.
  if (!pdf) headers.set('Content-Security-Policy', "sandbox; default-src 'none'");
  headers.set('Content-Type', pdf ? 'application/pdf' : 'application/octet-stream');
  const filename = encodeURIComponent(name || (pdf ? 'saved-copy.pdf' : 'saved-copy')).replace(/['()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
  headers.set('Content-Disposition', `${pdf ? 'inline' : 'attachment'}; filename*=UTF-8''${filename}`);
  if (request.method === 'HEAD') {
    await reader.cancel();
    return new Response(null, {headers});
  }
  const body = new ReadableStream({
    async pull(controller) {
      if (initial.length) { controller.enqueue(initial.shift()); return; }
      const {value, done} = await reader.read();
      if (done) controller.close(); else controller.enqueue(value);
    },
    cancel(reason) { return reader.cancel(reason); },
  });
  return new Response(body, {headers});
}

export default {
  async fetch(request, env) {
    const headers = new Headers({
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
      'Access-Control-Allow-Headers': 'Range, If-None-Match, Cache-Control',
      'Access-Control-Expose-Headers': 'Content-Range, Content-Length, ETag, Last-Modified',
      'Access-Control-Max-Age': '86400',
      'X-Content-Type-Options': 'nosniff',
      'Cache-Control': 'no-store',
    });
    const path = new URL(request.url).pathname.slice(1);
    const saved = /^saved\/([a-f0-9]{64})\/([^/]+)$/.exec(path);
    if (!saved && !publicationPath.test(path)) return new Response('Not found', {status: 404, headers});
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers});
    if (!['GET', 'HEAD'].includes(request.method)) {
      headers.set('Allow', 'GET, HEAD, OPTIONS');
      return new Response('Read only', {status: 405, headers});
    }
    if (saved) return savedCopy(request, env, headers, saved);
    const range = request.headers.get('Range');
    if (range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(range);
      if (!match || !Number.isSafeInteger(Number(match[1])) ||
          (match[2] && (!Number.isSafeInteger(Number(match[2])) || Number(match[2]) < Number(match[1])))) {
        return new Response('Invalid range', {status: 416, headers});
      }
    }
    const object = request.method === 'HEAD'
      ? await env.PUBLICATIONS.head(prefix + path)
      : await env.PUBLICATIONS.get(prefix + path, {range: request.headers, onlyIf: request.headers});
    if (!object) return new Response('Not found', {status: 404, headers});
    object.writeHttpMetadata(headers);
    // Current and per-catalog pointers always revalidate; release objects never change.
    headers.set('Cache-Control', path.startsWith('releases/') ? 'public, max-age=31536000, immutable' : 'no-store');
    headers.set('ETag', object.httpEtag);
    headers.set('Last-Modified', object.uploaded.toUTCString());
    headers.set('Accept-Ranges', 'bytes');
    if (request.headers.get('If-None-Match') === object.httpEtag) return new Response(null, {status: 304, headers});
    if (request.method === 'GET' && !('body' in object)) return new Response(null, {status: 412, headers});
    let status = 200, length = object.size;
    if (request.method === 'GET' && range && object.range) {
      const start = object.range.offset ?? 0;
      length = object.range.length;
      headers.set('Content-Range', `bytes ${start}-${start + length - 1}/${object.size}`);
      status = 206;
    }
    headers.set('Content-Length', String(length));
    return new Response(request.method === 'HEAD' ? null : object.body, {status, headers});
  },
};
