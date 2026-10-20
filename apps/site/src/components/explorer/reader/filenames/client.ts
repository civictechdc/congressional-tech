export interface CatalogWorker {
  postMessage(message: unknown): void;
  terminate(): void;
  onmessage: ((event: { data: { id?: number; result?: unknown; error?: string } }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessageerror: ((event: unknown) => void) | null;
}

interface ClientContext {
  manifest: string;
  snapshot?: string | null;
  reviewPublication?: unknown;
}

interface PendingCall {
  settle: (error: unknown, value?: unknown) => void;
  catalogResult: boolean;
}

/** Own request cleanup and recreate a failed reader on the next request. */
export function createFilenameClient({ createWorker, context, onResult = () => {}, onError = () => {} }: {
  createWorker: () => CatalogWorker;
  context: ClientContext;
  onResult?: (value: unknown) => void;
  onError?: (error: string) => void;
}) {
  const pending = new Map<number, PendingCall>();
  let worker: CatalogWorker | undefined;
  let sequence = 0;
  let disposed = false;
  let snapshot = context.snapshot || null;
  const unavailable = () => new Error('The catalog reader stopped. Retry the request or reload this page.');
  function fail(current: CatalogWorker) {
    if (current !== worker) return;
    worker = undefined;
    current.terminate();
    for (const call of [...pending.values()]) call.settle(unavailable());
  }
  function reader() {
    if (disposed) throw unavailable();
    if (worker) return worker;
    const current = worker = createWorker();
    current.onmessage = ({ data }) => {
      if (current !== worker) return;
      const call = pending.get(data.id ?? -1);
      if (!call) return;
      let error = data.error;
      if (!error && call.catalogResult) {
        const identity = (data.result as { catalog_id?: unknown } | undefined)?.catalog_id;
        if (typeof identity !== 'string' || !/^[a-f0-9]{32}$/.test(identity)) error = 'The catalog reader returned an invalid catalog identity.';
        else if (snapshot && identity !== snapshot) error = 'The catalog reader returned a different catalog snapshot. Retry the request or reload this page.';
        else snapshot = identity;
      }
      if (error) { call.settle(new Error(error)); onError(error); }
      else { call.settle(null, data.result); onResult(data.result); }
    };
    current.onerror = current.onmessageerror = () => fail(current);
    return current;
  }
  function request(url: string, signal?: AbortSignal): Promise<unknown> {
    return new Promise((resolve, reject) => {
      signal?.throwIfAborted();
      const current = reader();
      const id = ++sequence;
      const settle = (error: unknown, value?: unknown) => {
        if (!pending.delete(id)) return;
        signal?.removeEventListener('abort', abort);
        error ? reject(error) : resolve(value);
      };
      const abort = () => {
        settle(signal?.reason || new DOMException('Aborted', 'AbortError'));
        try { current.postMessage({ cancel: id }); } catch { fail(current); }
      };
      pending.set(id, { settle, catalogResult: url === '/api/info' || url.startsWith('/api/entry/') });
      signal?.addEventListener('abort', abort, { once: true });
      try { current.postMessage({ id, url, ...context, snapshot }); }
      catch (error) { settle(error); fail(current); }
    });
  }
  return {
    request,
    get pendingCount() { return pending.size; },
    dispose() {
      disposed = true;
      if (worker) fail(worker);
    },
  };
}

interface LifecycleWindow {
  addEventListener(type: string, listener: (event: { persisted?: boolean }) => void): void;
  removeEventListener(type: string, listener: (event: { persisted?: boolean }) => void): void;
}

/** A bfcache suspension releases polling; restoration starts exactly one poller. */
export function publicationLifecycle<T extends { catalog_id?: string }>({ window: win, start }: {
  window: LifecycleWindow;
  start: (info: T) => (() => void) | void;
}) {
  let identity: T | undefined;
  let stop: (() => void) | void;
  let suspended = false;
  let disposed = false;
  function resume() { suspended = false; if (!disposed && identity && !stop) stop = start(identity); }
  function pause() { suspended = true; stop?.(); stop = undefined; }
  function hide(event: { persisted?: boolean }) { if (event.persisted) pause(); else dispose(); }
  function dispose() { disposed = true; pause(); win.removeEventListener('pagehide', hide); win.removeEventListener('pageshow', resume); }
  win.addEventListener('pagehide', hide);
  win.addEventListener('pageshow', resume);
  return { accept(value: T | undefined) { if (!identity && value?.catalog_id) identity = value; if (!suspended) resume(); }, dispose };
}
