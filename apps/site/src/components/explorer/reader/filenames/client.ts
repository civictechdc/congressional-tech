export interface CatalogWorker {
  postMessage(message: unknown): void;
  terminate(): void;
  onmessage: ((event: { data: { id?: number; result?: unknown; error?: string; releaseId?: string } }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessageerror: ((event: unknown) => void) | null;
}

/** Own transport cleanup; each reader supplies its identity policy. */
export function createWorkerClient({createWorker, context, validate = () => {}, onResult = () => {}, onError = () => {}, unavailableMessage = 'The file list stopped loading. Try again or reload this page.'}: {
  createWorker: () => CatalogWorker;
  context: () => Record<string, unknown>;
  validate?: (url: string, data: any) => void;
  onResult?: (value: any) => void;
  onError?: (error: string) => void;
  unavailableMessage?: string;
}) {
  const pending = new Map<number, {url: string; settle: (error: unknown, value?: unknown) => void}>();
  let worker: CatalogWorker | undefined, sequence = 0, disposed = false;
  const unavailable = () => new Error(unavailableMessage);
  function fail(current: CatalogWorker) {
    if (current !== worker) return;
    worker = undefined; current.terminate();
    for (const call of [...pending.values()]) call.settle(unavailable());
  }
  function reader() {
    if (disposed) throw unavailable();
    if (worker) return worker;
    const current = worker = createWorker();
    current.onmessage = ({data}) => {
      if (current !== worker) return;
      const call = pending.get(data.id ?? -1); if (!call) return;
      try {
        if (data.error) throw new Error(data.error);
        validate(call.url, data);
        call.settle(null, data.result); onResult(data.result);
      } catch (error) {call.settle(error); onError(error instanceof Error ? error.message : String(error));}
    };
    current.onerror = current.onmessageerror = () => fail(current);
    return current;
  }
  function request(url: string, signal?: AbortSignal, payload?: unknown): Promise<any> {
    return new Promise((resolve, reject) => {
      signal?.throwIfAborted(); const current = reader(), id = ++sequence;
      const settle = (error: unknown, value?: unknown) => {
        if (!pending.delete(id)) return;
        signal?.removeEventListener('abort', abort); error ? reject(error) : resolve(value);
      };
      const abort = () => {
        settle(signal?.reason || new DOMException('Aborted', 'AbortError'));
        try {current.postMessage({cancel: id});} catch {fail(current);}
      };
      pending.set(id, {url, settle}); signal?.addEventListener('abort', abort, {once: true});
      try {current.postMessage({id, url, ...context(), ...(payload===undefined?{}:{payload})});} catch (error) {settle(error); fail(current);}
    });
  }
  return {request, get pendingCount() {return pending.size;}, dispose() {disposed = true; if (worker) fail(worker);}};
}

export function createFilenameClient({createWorker, context, onResult, onError}: {
  createWorker: () => CatalogWorker;
  context: {manifest: string; snapshot?: string | null; reviewPublication?: unknown};
  onResult?: (value: unknown) => void;
  onError?: (error: string) => void;
}) {
  let snapshot = context.snapshot || null;
  return createWorkerClient({createWorker, context: () => ({...context, snapshot}), onResult, onError,
    validate(url, data) {
      if (url !== '/api/info' && !url.startsWith('/api/entry/')) return;
      const identity = data.result?.catalog_id;
      if (typeof identity !== 'string' || !/^[a-f0-9]{32}$/.test(identity)) throw new Error('The file list did not identify itself. Reload this page.');
      if (snapshot && identity !== snapshot) throw new Error('The file list changed while this page was open. Reload this page and try again.');
      snapshot = identity;
    }});
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
