// The mutable pointer is tiny. All large reads use one immutable release.
export const filenameManifestUrl = 'https://congressional-viewer-data.mdeeb.workers.dev/manifest.json';

async function read(url, fetcher) {
  const response = await fetcher(url, {cache: 'no-store'});
  if (!response.ok) throw new Error('This catalog snapshot is not available. Open the latest catalog to continue.');
  return response.json();
}

export async function loadPublication(url, fetcher = fetch, catalogId) {
  let manifest = await read(url, fetcher);
  let recovery;
  if (manifest.version === 1 && manifest.manifest) {
    if (catalogId && catalogId !== manifest.catalog_id) {
      if (!/^[a-f0-9]{32}$/.test(catalogId)) throw new Error('Invalid catalog snapshot.');
      manifest = await read(new URL(`catalogs/${catalogId}.json`, url), fetcher);
      if (manifest.catalog_id !== catalogId) throw new Error('Catalog locator identity mismatch.');
    }
    if (!/^releases\/[a-f0-9]{32}\/manifest\.json$/.test(manifest.manifest)) throw new Error('Invalid publication location.');
    if (manifest.recovery) {
      if (!/^releases\/[a-f0-9]{32}\/[a-f0-9]{32}\/viewer-v2\/recovery-status\.json$/.test(manifest.recovery.path)) throw new Error('Invalid recovery status location.');
      recovery = {...manifest.recovery, url: new URL(manifest.recovery.path, url).href};
    }
    const identity = manifest.catalog_id;
    url = new URL(manifest.manifest, url).href;
    manifest = await read(url, fetcher);
    if (manifest.info?.catalog_id !== identity) throw new Error('Catalog publication identity mismatch.');
  }
  return {manifest, url, recovery};
}

export async function latestPublication(url, fetcher = fetch) {
  const value = await read(url, fetcher);
  return {catalog_id: value.catalog_id || value.info?.catalog_id, published_at: value.published_at, recovery_sha256: value.recovery?.sha256};
}

export function watchPublication({url, current, currentRecovery, onUpdate, onError = () => {}, fetcher = fetch,
                                  window: win = window, document: doc = document}) {
  let pending = false, stopped = false;
  async function check() {
    if (pending || stopped || doc.visibilityState === 'hidden') return;
    pending = true;
    try {
      const latest = await latestPublication(url, fetcher);
      if (!stopped && latest.catalog_id && (latest.catalog_id !== current || latest.recovery_sha256 !== currentRecovery)) onUpdate(latest);
    } catch (error) { if (!stopped) onError(error); }
    finally { pending = false; }
  }
  win.addEventListener('focus', check);
  doc.addEventListener('visibilitychange', check);
  const timer = win.setInterval(check, 60_000);
  check();
  return () => { stopped = true; win.clearInterval(timer); win.removeEventListener('focus', check); doc.removeEventListener('visibilitychange', check); };
}

export function latestReviewUrl(href, catalogId) {
  const url = new URL(href);
  // Stable source IDs can be resolved in the new snapshot; positional rows cannot.
  url.searchParams.delete('row');
  if (url.searchParams.has('source') && catalogId) url.searchParams.set('catalog', catalogId);
  else url.searchParams.delete('catalog');
  return url.href;
}

// Show the same action in the workspace and inside its modal inspector.
export function showPublicationUpdate({catalogId, message = 'New data available.',
                                       document: doc = document, location: loc = location} = {}) {
  for (const notice of doc.querySelectorAll('[data-catalog-update]')) {
    notice.hidden = false;
    notice.querySelector('span').textContent = message;
    const link = notice.querySelector('a');
    const refresh = () => { link.href = latestReviewUrl(loc.href, catalogId); };
    refresh();
    link.onclick = refresh;
    link.onfocus = refresh;
    link.onpointerdown = refresh;
  }
}
