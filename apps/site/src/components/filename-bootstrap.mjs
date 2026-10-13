const worker = new Worker(new URL('./filename-worker.mjs', import.meta.url), { type: 'module' });
const pending = new Map(); let sequence = 0;
worker.onmessage = ({ data }) => { const call = pending.get(data.id); if (!call) return; call.finish(); data.error ? call.reject(new Error(data.error)) : call.resolve(data.result); };
worker.onerror = () => { for (const call of [...pending.values()]) { call.finish(); call.reject(new Error('The catalog reader could not start. Reload this page to retry.')); } };
window.filenameViewerApi = (url, signal) => new Promise((resolve, reject) => {
  signal?.throwIfAborted();
  const id = ++sequence;
  const abort = () => { worker.postMessage({ cancel: id }); finish(); reject(signal.reason); };
  const finish = () => { pending.delete(id); signal?.removeEventListener('abort', abort); };
  pending.set(id, { resolve, reject, finish }); signal?.addEventListener('abort', abort, { once: true });
  worker.postMessage({ id, url, manifest: new URL(`${import.meta.env.BASE_URL.replace(/\/$/, "")}/data/filenames/manifest.json`, location.origin).href });
});
await import('../../../../docs/youtube-coverage/research/filename-viewer.mjs');
