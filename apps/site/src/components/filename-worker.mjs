import { createFilenameCatalog } from './filename-catalog.mjs';
let catalog;
const requests = new Map();
self.onmessage = async ({ data }) => {
  if (data.cancel) { requests.get(data.cancel)?.abort(); return; }
  const { id, url, manifest } = data, controller = new AbortController();
  requests.set(id, controller);
  try {
    catalog ||= createFilenameCatalog(manifest).catch(error => { catalog = null; throw error; });
    const reader = await catalog;
    controller.signal.throwIfAborted();
    const request = new URL(url, manifest), query = Object.fromEntries(request.searchParams);
    const result = request.pathname === '/api/info' ? reader.info : request.pathname === '/api/rows' ? await reader.search(query, controller.signal)
      : await reader.entry(decodeURIComponent(request.pathname.split('/').at(-1)), query.catalog, controller.signal);
    if (!controller.signal.aborted) self.postMessage({ id, result });
  } catch (error) { if (!controller.signal.aborted) self.postMessage({ id, error: error.message }); }
  finally { controller.abort(); requests.delete(id); }
};
