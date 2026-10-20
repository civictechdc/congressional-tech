// Both status loaders verify decoded JSON bytes. Their callers own whether a
// failure is mandatory and choose independent byte and startup-time policies.
function cancel(stream) {
  // A broken transport can ignore abort or leave cancel() pending forever.
  // Request cleanup without allowing that promise to block the caller.
  try { Promise.resolve(stream?.cancel()).catch(() => {}); } catch {}
}

export async function withVerifiedJson(policy, label, run, callerSignal) {
  if (!Number.isFinite(policy.deadlineMs) || policy.deadlineMs <= 0 || !Number.isSafeInteger(policy.maxBytes) || policy.maxBytes < 1) throw new Error(`Invalid ${label.toLowerCase()} startup policy.`);
  const controller = new AbortController(), {signal} = controller;
  const abort = () => controller.abort(callerSignal.reason);
  callerSignal?.addEventListener('abort', abort, {once: true});
  if (callerSignal?.aborted) abort();
  const deadlineError = new Error(`${label} exceeded the startup deadline.`);
  const expires = performance.now() + policy.deadlineMs;
  const timer = setTimeout(() => controller.abort(deadlineError), policy.deadlineMs);
  const check = () => {
    if (performance.now() >= expires) controller.abort(deadlineError);
    signal.throwIfAborted();
  };
  const wait = async promise => {
    let interrupted;
    const stopped = new Promise((_, reject) => {
      interrupted = () => reject(signal.reason);
      if (signal.aborted) interrupted();
      else signal.addEventListener('abort', interrupted, {once: true});
    });
    try { return await Promise.race([promise, stopped]); }
    finally { signal.removeEventListener('abort', interrupted); }
  };
  const verified = async (fetcher, url, sha256, length, name) => {
    if (!Number.isSafeInteger(length) || length < 1 || length > policy.maxBytes) throw new Error(`${name} exceeds the startup byte limit.`);
    check();
    const pending = Promise.resolve(fetcher(url, {signal}));
    // A fetch implementation may resolve only after its caller has timed out.
    pending.then(response => { if (signal.aborted) cancel(response.body); }, () => {});
    const response = await wait(pending);
    if (!response.ok) { cancel(response.body); throw new Error(`Could not load the ${name}.`); }
    const declared = response.headers.get('Content-Length');
    // Fetch exposes decoded bytes; encoded or CORS-hidden headers may describe
    // the compressed transfer. The descriptor always binds decoded bytes.
    const encoding = response.headers.get('Content-Encoding');
    if (declared !== null && response.type !== 'cors' && (!encoding || encoding.toLowerCase() === 'identity') && Number(declared) !== length) {
      cancel(response.body); throw new Error(`${name} has an unexpected response length.`);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error(`Could not read the ${name}.`);
    const bytes = new Uint8Array(length);
    let offset = 0;
    try {
      while (true) {
        check();
        const {value, done} = await wait(reader.read());
        if (done) break;
        if (offset + value.byteLength > length) throw new Error(`${name} exceeds its expected response length.`);
        bytes.set(value, offset); offset += value.byteLength;
      }
      if (offset !== length) throw new Error(`${name[0].toUpperCase()}${name.slice(1)} failed verification.`);
      const hash = [...new Uint8Array(await wait(crypto.subtle.digest('SHA-256', bytes)))].map(value => value.toString(16).padStart(2, '0')).join('');
      if (hash !== sha256) throw new Error(`${name[0].toUpperCase()}${name.slice(1)} failed verification.`);
      return JSON.parse(new TextDecoder().decode(bytes));
    } catch (error) { cancel(reader); throw error; }
    finally { reader.releaseLock(); }
  };
  try {
    const result = await wait(Promise.resolve().then(() => run(verified)));
    check();
    return result;
  }
  finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', abort);
    controller.abort();
  }
}

// Compare parsed control data independently of object key insertion order.
export function canonicalJson(value) {
  const ordered = value => Array.isArray(value) ? value.map(ordered) : value && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key=>[key,ordered(value[key])])) : value;
  return JSON.stringify(ordered(value));
}
