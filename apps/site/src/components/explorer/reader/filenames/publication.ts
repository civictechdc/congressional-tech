// The mutable pointer is tiny. All large reads use one immutable release.
export const filenameManifestUrl = 'https://congressional-viewer-data.mdeeb.workers.dev/manifest.json';

export type CatalogFetcher = (url: string, init?: RequestInit) => Promise<Response>;

interface PublicationWindow {
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
  setInterval(handler: () => void, timeout: number): number;
  clearInterval(handle: number): void;
}

interface PublicationDocument {
  visibilityState: DocumentVisibilityState | string;
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
  querySelectorAll?(selectors: string): Iterable<Element> | NodeListOf<Element>;
}

async function read(url: string, fetcher: CatalogFetcher, signal?: AbortSignal, immutable = false): Promise<Record<string, unknown>> {
  const response = await fetcher(url, { cache: immutable ? 'force-cache' : 'no-store', signal });
  if (!response.ok) throw new Error('This file list is not available. Open the current file list to continue.');
  return response.json() as Promise<Record<string, unknown>>;
}

export async function loadPublication(url: string, fetcher: CatalogFetcher = fetch, catalogId?: string | null) {
  let manifest = await read(url, fetcher);
  let recovery: Record<string, unknown> | undefined;
  if (manifest.version === 1 && manifest.manifest) {
    if (catalogId && catalogId !== manifest.catalog_id) {
      if (!/^[a-f0-9]{32}$/.test(catalogId)) throw new Error('This file list link is not valid.');
      manifest = await read(new URL(`catalogs/${catalogId}.json`, url).href, fetcher, undefined, true);
      if (manifest.catalog_id !== catalogId) throw new Error('Catalog locator identity mismatch.');
    }
    if (typeof manifest.manifest !== 'string' || !/^releases\/[a-f0-9]{32}\/manifest\.json$/.test(manifest.manifest)) throw new Error('Invalid publication location.');
    const recoveryPointer = manifest.recovery as { path?: string } | undefined;
    if (recoveryPointer) {
      if (!recoveryPointer.path || !/^releases\/[a-f0-9]{32}\/[a-f0-9]{32}\/viewer-v2\/recovery-status\.json$/.test(recoveryPointer.path)) throw new Error('Invalid recovery status location.');
      recovery = { ...recoveryPointer, url: new URL(recoveryPointer.path, url).href };
    }
    const identity = manifest.catalog_id;
    url = new URL(manifest.manifest, url).href;
    manifest = await read(url, fetcher, undefined, true);
    const info = manifest.info as { catalog_id?: string } | undefined;
    if (info?.catalog_id !== identity) throw new Error('Catalog publication identity mismatch.');
  }
  return { manifest, url, recovery };
}

export async function latestPublication(url: string, fetcher: CatalogFetcher = fetch, signal?: AbortSignal) {
  const value = await read(url, fetcher, signal);
  const recovery = value.recovery as { sha256?: string } | undefined;
  return { catalog_id: (value.catalog_id || (value.info as { catalog_id?: string } | undefined)?.catalog_id) as string | undefined, published_at: value.published_at, recovery_sha256: recovery?.sha256 };
}

export function watchPublication({ url, current, currentRecovery, onUpdate, onError = () => {}, fetcher = fetch, window: win = window, document: doc = document }: {
  url: string;
  current: string;
  currentRecovery?: string;
  onUpdate: (latest: { catalog_id?: string; published_at?: unknown; recovery_sha256?: string }) => void;
  onError?: (error: unknown) => void;
  fetcher?: CatalogFetcher;
  window?: PublicationWindow;
  document?: PublicationDocument;
}) {
  let pending = false, stopped = false;
  const controller = new AbortController();
  async function check() {
    if (pending || stopped || doc.visibilityState === 'hidden') return;
    pending = true;
    try {
      const latest = await latestPublication(url, fetcher, controller.signal);
      if (!stopped && latest.catalog_id && (latest.catalog_id !== current || latest.recovery_sha256 !== currentRecovery)) onUpdate(latest);
    } catch (error) { if (!stopped) onError(error); }
    finally { pending = false; }
  }
  win.addEventListener('focus', check);
  doc.addEventListener('visibilitychange', check);
  const timer = win.setInterval(check, 60_000);
  void check();
  return () => {
    stopped = true;
    controller.abort();
    win.clearInterval(timer);
    win.removeEventListener('focus', check);
    doc.removeEventListener('visibilitychange', check);
  };
}

export function latestReviewUrl(href: string, catalogId?: string): string {
  const url = new URL(href);
  // Stable source IDs can be resolved in the new snapshot; positional rows cannot.
  url.searchParams.delete('row');
  const id = url.searchParams.get('id') || '';
  const positional = /^\d{1,11}$/.test(id);
  const pinned = url.searchParams.has('source') || url.searchParams.get('kind') === 'filename_entry';
  if (positional) {
    url.searchParams.delete('id');
    if (url.searchParams.get('kind') === 'filename_entry') url.searchParams.delete('kind');
    url.searchParams.delete('catalog');
  } else if (pinned && catalogId) url.searchParams.set('catalog', catalogId);
  else url.searchParams.delete('catalog');
  return url.href;
}

/** Show the same action in the workspace and inside its inspector. */
export function showPublicationUpdate({ catalogId, message = 'New data available.', document: doc = document, location: loc = location }: {
  catalogId?: string;
  message?: string;
  document?: Document;
  location?: Location;
} = {}) {
  for (const notice of doc.querySelectorAll('[data-catalog-update]')) {
    const element = notice as HTMLElement;
    element.hidden = false;
    const span = element.querySelector('span');
    const link = element.querySelector('a') as HTMLAnchorElement | null;
    if (!span || !link) continue;
    span.textContent = message;
    const refresh = () => { link.href = latestReviewUrl(loc.href, catalogId); };
    refresh();
    link.onclick = refresh;
    link.onfocus = refresh;
    link.onpointerdown = refresh;
  }
}

export function reviewPublicationUrl(base: string, origin: string): string {
  return new URL('data/document-reviews/reviews.json', new URL(base.replace(/\/?$/, '/'), origin)).href;
}
