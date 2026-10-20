// One event-loop yield per bounded batch lets worker cancel messages run.
export const scanBatchRows = 512;
export async function yieldToMessages(signal, metrics = {}) {
  signal?.throwIfAborted();
  metrics.scanYields = (metrics.scanYields || 0) + 1;
  await new Promise(resolve => setTimeout(resolve, 0));
  signal?.throwIfAborted();
}
