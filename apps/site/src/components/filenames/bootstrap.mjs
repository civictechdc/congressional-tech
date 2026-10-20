import reviewDescriptor from '../../../document-review-publication.json';
import { reviewPublicationUrl, filenameManifestUrl, watchPublication, showPublicationUpdate } from './publication.mjs';
import { createFilenameClient, publicationLifecycle } from './client.mjs';
const manifest = import.meta.env.PUBLIC_FILENAME_MANIFEST_URL || filenameManifestUrl;
const snapshot = new URLSearchParams(location.search).get('catalog');
const lifecycle = publicationLifecycle({window, start: info => watchPublication({
  url: manifest, current: info.catalog_id, currentRecovery: info.recovery_sha256,
  onUpdate: latest => showPublicationUpdate({catalogId: latest.catalog_id})
})});
const client = createFilenameClient({
  createWorker: () => new Worker(new URL('./worker.mjs', import.meta.url), {type: 'module'}),
  context: {manifest: new URL(manifest, location.origin).href, snapshot,
    reviewPublication: {...reviewDescriptor, url: reviewPublicationUrl(import.meta.env.BASE_URL, location.origin)}},
  onResult: value => lifecycle.accept(value),
  onError: () => { if (snapshot) showPublicationUpdate({message: 'This review snapshot could not be loaded.'}); }
});
window.addEventListener('pagehide', event => { if (!event.persisted) client.dispose(); });
window.filenameViewerApi = client.request;
await import('../../../../../docs/youtube-coverage/research/filename-viewer.mjs');
