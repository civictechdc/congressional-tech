import { filenameManifestUrl, watchPublication, latestReviewUrl } from './filename-publication.mjs';
const manifest = import.meta.env.PUBLIC_FILENAME_MANIFEST_URL || filenameManifestUrl;
const snapshot = new URLSearchParams(location.search).get('catalog');
const worker = new Worker(new URL('./filename-worker.mjs', import.meta.url), { type: 'module' });
let stopWatching;
const pending = new Map(); let sequence = 0;
worker.onmessage = ({ data }) => {
  const call = pending.get(data.id); if (!call) return;
  if (data.error && snapshot && !stopWatching) {
    const notice = document.getElementById('catalog-update');
    notice.hidden = false;
    notice.firstChild.textContent = 'This review snapshot could not be loaded. ';
    const link = document.getElementById('catalog-update-link');
    link.href = latestReviewUrl(location.href);
  }
  if (data.result?.catalog_id && !stopWatching) {
    stopWatching = watchPublication({url: manifest, current: data.result.catalog_id, onUpdate: latest => {
      const notice = document.getElementById('catalog-update');
      const link = document.getElementById('catalog-update-link');
      notice.hidden = false;
      link.href = latestReviewUrl(location.href, latest.catalog_id);
      link.onclick = () => { link.href = latestReviewUrl(location.href, latest.catalog_id); };
    }});
  }
  call.finish(); data.error ? call.reject(new Error(data.error)) : call.resolve(data.result);
};
window.addEventListener('pagehide', () => stopWatching?.(), {once: true});
worker.onerror = () => { for (const call of [...pending.values()]) { call.finish(); call.reject(new Error('The catalog reader could not start. Reload this page to retry.')); } };
window.filenameViewerApi = (url, signal) => new Promise((resolve, reject) => {
  signal?.throwIfAborted();
  const id = ++sequence;
  const abort = () => { worker.postMessage({ cancel: id }); finish(); reject(signal.reason); };
  const finish = () => { pending.delete(id); signal?.removeEventListener('abort', abort); };
  pending.set(id, { resolve, reject, finish }); signal?.addEventListener('abort', abort, { once: true });
  worker.postMessage({ id, url, manifest: new URL(manifest, location.origin).href, snapshot });
});
await import('../../../../docs/youtube-coverage/research/filename-viewer.mjs');
