import { createFilenameCatalog } from './filename-catalog.mjs';
let catalog;
const requests = new Map();
self.onmessage = async ({ data }) => {
  if (data.cancel) { requests.get(data.cancel)?.abort(); return; }
  const { id, url, manifest, snapshot, reviewPublication } = data, controller = new AbortController();
  requests.set(id, controller);
  try {
    catalog ||= createFilenameCatalog(manifest, fetch, snapshot, reviewPublication).catch(error => { catalog = null; throw error; });
    const reader = await catalog;
    controller.signal.throwIfAborted();
    const request = new URL(url, manifest), query = Object.fromEntries(request.searchParams);
    const identity = decodeURIComponent(request.pathname.split('/').at(-1));
    let result;
    if (request.pathname === '/api/info') result = reader.info;
    else if (request.pathname === '/api/rows') result = await reader.search(query, controller.signal);
    else if (request.pathname.startsWith('/api/document/')) result = await reader.documentRecord(identity, query.catalog, controller.signal);
    else if (request.pathname.startsWith('/api/review/')) result = await reader.review(identity, query.catalog, controller.signal, query.selection === 'baseline');
    else if (request.pathname.startsWith('/api/entry-origin/')) result = await reader.entryOrigin(identity, query.catalog, controller.signal);
    else if (request.pathname.startsWith('/api/technical/') || request.pathname.startsWith('/api/full/')) result = await reader.technical(identity, query.catalog, controller.signal, request.pathname.startsWith('/api/full/'));
    else if (request.pathname.startsWith('/api/observations/') || request.pathname.startsWith('/api/origin/')) {
      const origin = request.pathname.startsWith('/api/origin/');
      result = await reader.observationPage(identity, query.catalog, {...query, origin}, controller.signal);
      if (origin) {
        const record = await reader.technicalOrigin(identity, query.catalog, controller.signal);
        result = {origin: reader.sourceContext({...record, source_occurrences: result.items.filter(Boolean)}), next: result.next};
      }
    } else result = await reader.entry(identity, query.catalog, controller.signal, {deferOrigin: true});
    if (!controller.signal.aborted) self.postMessage({ id, result });
  } catch (error) { if (!controller.signal.aborted) self.postMessage({ id, error: error.message }); }
  finally { controller.abort(); requests.delete(id); }
};
