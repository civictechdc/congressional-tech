/** Own request cleanup and recreate a failed reader on the next request. */
export function createFilenameClient({createWorker, context, onResult = () => {}, onError = () => {}}) {
  const pending = new Map();
  let worker, sequence = 0, disposed = false;
  const unavailable = () => new Error('The catalog reader stopped. Retry the request or reload this page.');
  function fail(current) {
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
      const call = pending.get(data.id);
      if (!call) return;
      if (data.error) { call.settle(new Error(data.error)); onError(data.error); }
      else { call.settle(null, data.result); onResult(data.result); }
    };
    current.onerror = current.onmessageerror = () => fail(current);
    return current;
  }
  function request(url, signal) {
    return new Promise((resolve, reject) => {
      signal?.throwIfAborted();
      const current = reader(), id = ++sequence;
      const settle = (error, value) => {
        if (!pending.delete(id)) return;
        signal?.removeEventListener('abort', abort);
        error ? reject(error) : resolve(value);
      };
      const abort = () => {
        settle(signal.reason || new DOMException('Aborted', 'AbortError'));
        try { current.postMessage({cancel: id}); } catch { fail(current); }
      };
      pending.set(id, {settle});
      signal?.addEventListener('abort', abort, {once: true});
      try { current.postMessage({id, url, ...context}); }
      catch (error) { settle(error); fail(current); }
    });
  }
  return {request, get pendingCount() { return pending.size; }, dispose() {
    disposed = true;
    if (worker) fail(worker);
  }};
}

/** A bfcache suspension releases polling; restoration starts exactly one poller. */
export function publicationLifecycle({window: win, start}) {
  let identity, stop, suspended = false, disposed = false;
  function resume() { suspended = false; if (!disposed && identity && !stop) stop = start(identity); }
  function pause() { suspended = true; stop?.(); stop = undefined; }
  function hide(event) { if (event.persisted) pause(); else dispose(); }
  function dispose() { disposed = true; pause(); win.removeEventListener('pagehide', hide); win.removeEventListener('pageshow', resume); }
  win.addEventListener('pagehide', hide); win.addEventListener('pageshow', resume);
  return {accept(value) { if (!identity && value?.catalog_id) identity = value; if (!suspended) resume(); }, dispose};
}
