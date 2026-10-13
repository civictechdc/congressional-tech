// This endpoint serves published viewer files only. It cannot list or write R2.
const publicationPath = /^(?:manifest\.json|catalogs\/[a-f0-9]{32}\.json|releases\/[a-f0-9]{32}\/(?:manifest\.json|[a-f0-9]{32}\/viewer-v2\/(?:[a-z_-]+\.(?:parquet|bin|json)|ids\/[a-f0-9]{2}\.bin)))$/;
const prefix = 'viewer-publications/';

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
    if (!publicationPath.test(path)) return new Response('Not found', {status: 404, headers});
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers});
    if (!['GET', 'HEAD'].includes(request.method)) {
      headers.set('Allow', 'GET, HEAD, OPTIONS');
      return new Response('Read only', {status: 405, headers});
    }
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
