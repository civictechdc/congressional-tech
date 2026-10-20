import { useEffect, useRef, useState, type DependencyList } from 'react';
import { PAGE_SIZE } from '../browse/query-utils.ts';
import { BackIcon, ForwardIcon } from './icons';

export { PAGE_SIZE };
export const integer = (value: number) => value.toLocaleString('en-US');
export type RequestState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: T };

/** Each request owns cancellation so an older response cannot replace a new selection. */
export function useRequest<T>(load: (signal: AbortSignal) => Promise<T>, dependencies: DependencyList): [RequestState<T>, () => void] {
  const [state, setState] = useState<RequestState<T>>({ status: 'loading' });
  const [retry, setRetry] = useState(0);
  const request = [...dependencies, retry];
  const previous = useRef(request);
  const same = previous.current.length === request.length && previous.current.every((item, index) => Object.is(item, request[index]));
  if (!same) {
    previous.current = request;
    setState({ status: 'loading' });
  }
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
  return [same ? state : { status: 'loading' }, () => setRetry(value => value + 1)];
}

export function RequestMessage({ state, retry, noun = 'records' }: { state: { status: 'loading' } | { status: 'error'; message: string }; retry: () => void; noun?: string }) {
  return state.status === 'loading' ? <p className="explorer-loading" role="status">Loading {noun}…</p> : <div className="explorer-alert" role="alert"><p>Could not load {noun}. {state.message}</p><button className="explorer-button" aria-label={`Try loading ${noun} again`} onClick={retry}>Try again</button></div>;
}

/** Keep a two-part column name on one line until the column is too narrow to hold the slash. */
export function SortLabel({ label }: { label: string }) {
  const parts = label.split(' / ');
  if (parts.length < 2) return label;
  return <>{parts[0]}<span className="explorer-sort-join"> / </span><span className="explorer-sort-rest">{parts.slice(1).join(' / ')}</span></>;
}

export function Pagination({ total, offset, count, onPage }: { total: number; offset: number; count: number; onPage: (page: number) => void }) {
  return <div className="explorer-pagination"><span>{total ? `${integer(count ? offset + 1 : 0)}–${integer(count ? offset + count : 0)} of ${integer(total)}` : '0 matching records'}</span><div><button className="explorer-button" aria-label="Previous page of this selection" disabled={offset === 0} onClick={() => onPage(Math.max(0, Math.floor(offset / PAGE_SIZE) - 1))}><BackIcon /> Previous</button><button className="explorer-button" aria-label="Next page of this selection" disabled={offset + count >= total} onClick={() => onPage(Math.floor(offset / PAGE_SIZE) + 1)}>Next <ForwardIcon /></button></div></div>;
}
