// One event-loop yield per bounded batch lets worker cancel messages run.
export const scanBatchRows = 512;

const waiters: Array<() => void> = [];
const channel = typeof MessageChannel === 'function' ? new MessageChannel() : null;
if (channel) {
  channel.port1.onmessage = () => {
    const resolve = waiters.shift();
    if (!waiters.length) channel.port1.unref?.();
    resolve?.();
  };
  channel.port1.unref?.();
  channel.port2.unref?.();
}

export async function yieldToMessages(signal?: AbortSignal, metrics: { scanYields?: number } = {}): Promise<void> {
  signal?.throwIfAborted();
  metrics.scanYields = (metrics.scanYields || 0) + 1;
  if (channel) await new Promise<void>(resolve => { channel.port1.ref?.(); waiters.push(resolve); channel.port2.postMessage(null); });
  else await new Promise(resolve => setTimeout(resolve, 0));
  signal?.throwIfAborted();
}
