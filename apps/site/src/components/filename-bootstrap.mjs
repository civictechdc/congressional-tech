import reviewDescriptor from '../../document-review-publication.json';
import { reviewPublicationUrl, filenameManifestUrl, watchPublication, showPublicationUpdate } from './filename-publication.mjs';
const manifest = import.meta.env.PUBLIC_FILENAME_MANIFEST_URL || filenameManifestUrl;
const snapshot = new URLSearchParams(location.search).get('catalog');
const worker = new Worker(new URL('./filename-worker.mjs', import.meta.url), { type: 'module' });
let stopWatching;
const pending = new Map(); let sequence = 0;
worker.onmessage = ({ data }) => {
  const call = pending.get(data.id); if (!call) return;
  if (data.error && snapshot && !stopWatching) {
    showPublicationUpdate({message: 'This review snapshot could not be loaded.'});
  }
  if (data.result?.catalog_id && !stopWatching) {
    stopWatching = watchPublication({url: manifest, current: data.result.catalog_id, currentRecovery: data.result.recovery_sha256, onUpdate: latest => {
      showPublicationUpdate({catalogId: latest.catalog_id});
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
  worker.postMessage({ id, url, manifest: new URL(manifest, location.origin).href, snapshot, reviewPublication: {...reviewDescriptor, url: reviewPublicationUrl(import.meta.env.BASE_URL, location.origin)} });
});
await import('../../../../docs/youtube-coverage/research/filename-viewer.mjs');
