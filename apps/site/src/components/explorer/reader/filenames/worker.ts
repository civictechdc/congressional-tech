import { createFilenameCatalog } from './catalog.ts';

interface WorkerRequest {
  id?: number;
  url?: string;
  manifest?: string;
  snapshot?: string | null;
  reviewPublication?: unknown;
  cancel?: number;
}

let catalog: ReturnType<typeof createFilenameCatalog> | null = null;
const requests = new Map<number, AbortController>();

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const data = event.data;
  if (data.cancel) { requests.get(data.cancel)?.abort(); return; }
  const { id, url, manifest, snapshot, reviewPublication } = data;
  if (id == null || !url || !manifest) return;
  const controller = new AbortController();
  requests.set(id, controller);
  try {
    const pending = catalog ||= createFilenameCatalog(manifest, fetch, snapshot, reviewPublication).catch((error: unknown) => { catalog = null; throw error; });
    const reader = await pending;
    controller.signal.throwIfAborted();
    const request = new URL(url, manifest);
    const query = Object.fromEntries(request.searchParams);
    const identity = decodeURIComponent(request.pathname.split('/').at(-1) || '');
    let result: unknown;
    if (request.pathname === '/api/info') result = reader.info;
    else if (request.pathname === '/api/rows') result = await reader.search(query, controller.signal);
    else if (request.pathname.startsWith('/api/document/')) result = await reader.documentRecord(identity, query.catalog, controller.signal);
    else if (request.pathname === '/api/match') {
      if (!reader.matchUrls) throw new Error('URL matching is unavailable for this catalog.');
      result = await reader.matchUrls(JSON.parse(query.payload || '{}'), controller.signal);
    }
    else if (request.pathname.startsWith('/api/review/')) {
      if (!reader.review) throw new Error('Document reviews are unavailable for this catalog.');
      result = await reader.review(identity, query.catalog, controller.signal, query.selection === 'baseline');
    }
    else if (request.pathname.startsWith('/api/entry-origin/')) {
      if (!reader.entryOrigin) throw new Error('Entry origins are unavailable for this catalog.');
      result = await reader.entryOrigin(identity, query.catalog, controller.signal);
    }
    else if (request.pathname.startsWith('/api/source-identity/')) {
      if (!reader.sourceIdentity) throw new Error('Source identity is unavailable for this catalog.');
      result = await reader.sourceIdentity(identity, query.catalog, controller.signal);
    }
    else if (request.pathname.startsWith('/api/technical/') || request.pathname.startsWith('/api/full/')) {
      if (!reader.technical) throw new Error('Technical records are unavailable for this catalog.');
      result = await reader.technical(identity, query.catalog, controller.signal, request.pathname.startsWith('/api/full/'));
    }
    else if (request.pathname.startsWith('/api/observations/') || request.pathname.startsWith('/api/origin/')) {
      const origin = request.pathname.startsWith('/api/origin/');
      const page = await reader.observationPage(identity, query.catalog, { ...query, origin }, controller.signal);
      if (origin) {
        if (!reader.technicalOrigin) throw new Error('Technical origins are unavailable for this catalog.');
        const record = await reader.technicalOrigin(identity, query.catalog, controller.signal);
        result = { origin: reader.sourceContext({ ...record, source_occurrences: page.items.filter(Boolean) }), next: page.next };
      } else result = page;
    } else result = await reader.entry(identity, query.catalog, controller.signal, { deferOrigin: true });
    if (!controller.signal.aborted) self.postMessage({ id, result });
  } catch (error) {
    if (!controller.signal.aborted) self.postMessage({ id, error: error instanceof Error ? error.message : String(error) });
  } finally {
    controller.abort();
    requests.delete(id);
  }
};
