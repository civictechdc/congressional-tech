import reviewDescriptor from '../../../../../document-review-publication.json';
import { createFilenameClient, publicationLifecycle, type CatalogWorker } from './client.ts';
import { filenameManifestUrl, reviewPublicationUrl, showPublicationUpdate, watchPublication } from './publication.ts';

export type FilenameApi = (url: string, signal?: AbortSignal) => Promise<unknown>;

declare global {
  interface Window {
    filenameViewerApi?: FilenameApi;
  }
}

const manifest = import.meta.env.PUBLIC_FILENAME_MANIFEST_URL || filenameManifestUrl;

/** One worker for the page. The dashboard bootstrap mounts it; Explorer calls through the same global. */
export function mountFilenameCatalog(): void {
  if (typeof window === 'undefined' || window.filenameViewerApi) return;
  const snapshot = new URLSearchParams(location.search).get('catalog');
  const lifecycle = publicationLifecycle({
    window,
    start: (info: { catalog_id: string; recovery_sha256?: string }) => watchPublication({
      url: manifest,
      current: info.catalog_id,
      currentRecovery: info.recovery_sha256,
      onUpdate: latest => showPublicationUpdate({ catalogId: latest.catalog_id }),
    }),
  });
  const client = createFilenameClient({
    createWorker: () => new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' }) as CatalogWorker,
    context: {
      manifest: new URL(manifest, location.origin).href,
      snapshot,
      reviewPublication: { ...reviewDescriptor, url: reviewPublicationUrl(import.meta.env.BASE_URL, location.origin) },
    },
    onResult: value => lifecycle.accept(value as { catalog_id: string; recovery_sha256?: string }),
    onError: () => { if (snapshot) showPublicationUpdate({ message: 'This review snapshot could not be loaded.' }); },
  });
  window.addEventListener('pagehide', event => { if (!event.persisted) client.dispose(); });
  window.filenameViewerApi = (url, signal) => client.request(url, signal);
  void client.request('/api/info');
}

const resultCache = new Map<string, unknown>();

export async function filenameRequest<T = unknown>(url: string, signal?: AbortSignal): Promise<T> {
  const cached = resultCache.get(url);
  if (cached !== undefined) return cached as T;
  const value = await callFilenameApi(url, signal);
  if (url.startsWith('/api/rows') || url.startsWith('/api/match') || url.startsWith('/api/source-identity')) {
    resultCache.set(url, value);
    while (resultCache.size > 8) resultCache.delete(resultCache.keys().next().value!);
  }
  return value as T;
}

function callFilenameApi(url: string, signal?: AbortSignal): Promise<unknown> {
  const ready = window.filenameViewerApi;
  if (ready) return ready(url, signal);
  return new Promise((resolve, reject) => {
    const started = performance.now();
    const timer = window.setInterval(() => {
      if (signal?.aborted) {
        window.clearInterval(timer);
        reject(signal.reason || new DOMException('Aborted', 'AbortError'));
        return;
      }
      if (window.filenameViewerApi) {
        window.clearInterval(timer);
        window.filenameViewerApi(url, signal).then(resolve, reject);
      } else if (performance.now() - started > 8000) {
        window.clearInterval(timer);
        reject(new Error('The filename catalog reader is unavailable. Reload this page to retry.'));
      }
    }, 16);
  });
}
