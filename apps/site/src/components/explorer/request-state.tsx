import { useEffect, useState, type DependencyList } from 'react';

export const PAGE_SIZE = 25;
const integer = (value: number) => value.toLocaleString('en-US');
export type RequestState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: T };

/** Each request owns cancellation so an older response cannot replace a new selection. */
export function useRequest<T>(load: (signal: AbortSignal) => Promise<T>, dependencies: DependencyList): [RequestState<T>, () => void] {
  const [state, setState] = useState<RequestState<T>>({ status: 'loading' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    load(controller.signal).then(value => {
      if (!controller.signal.aborted) setState({ status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ status: 'error', message: error instanceof Error ? error.message : String(error) });
    });
    return () => controller.abort();
  }, [...dependencies, retry]);
  return [state, () => setRetry(value => value + 1)];
}

export function RequestMessage({ state, retry, noun = 'records' }: { state: { status: 'loading' } | { status: 'error'; message: string }; retry: () => void; noun?: string }) {
  return state.status === 'loading' ? <p className="explorer-loading" role="status">Loading {noun}…</p> : <div className="explorer-alert" role="alert"><p>Could not load {noun}. {state.message}</p><button className="explorer-button" onClick={retry}>Try again</button></div>;
}

export function Pagination({ total, offset, count, onPage }: { total: number; offset: number; count: number; onPage: (page: number) => void }) {
  return <div className="explorer-pagination"><span>{total ? `${integer(count ? offset + 1 : 0)}–${integer(count ? offset + count : 0)} of ${integer(total)}` : '0 matching records'}</span><div><button className="explorer-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, Math.floor(offset / PAGE_SIZE) - 1))}>← Previous</button><button className="explorer-button" disabled={offset + count >= total} onClick={() => onPage(Math.floor(offset / PAGE_SIZE) + 1)}>Next →</button></div></div>;
}
