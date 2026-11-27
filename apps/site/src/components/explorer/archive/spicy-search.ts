import {SPICYENGINE_SEARCH_ORIGIN} from './search-config.ts';

export interface PassageHit {
  id: string;
  linkKey: string | null;
  title: string;
  url: string;
  path: string | null;
  crumb: string | null;
  kind: string | null;
  snippet: string;
  passage: {start_char?: number; end_char?: number} | null;
  publisherUrl: string | null;
  sourceUrl: string | null;
}

export interface PassageSearchResponse {
  state: 'ready' | 'unavailable';
  origin: string;
  query: string;
  mode: 'hybrid' | 'fulltext';
  releaseId: string | null;
  releaseMismatch: boolean;
  total: number;
  hasMore: boolean;
  tookMs: number | null;
  results: PassageHit[];
  reason?: string;
}

export function extractLinkKeyFromHitId(id: any): string | null {
  const clean = String(id ?? '').trim();
  const match = /^archive-documents:([a-f0-9]{16})$/i.exec(clean);
  if (match) return match[1].toLowerCase();
  if (/^[a-f0-9]{16}$/i.test(clean)) return clean.toLowerCase();
  return null;
}

export function resolveOriginUrl(origin: string, pathOrUrl: any): string | null {
  const raw = String(pathOrUrl ?? '').trim();
  if (!raw) return null;
  try {
    const base = origin.endsWith('/') ? origin : `${origin}/`;
    const parsed = raw.startsWith('/') ? new URL(raw, base) : new URL(raw);
    if (!/^https?:$/i.test(parsed.protocol)) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

export async function searchSpicyPassages(
  query: string,
  options: {
    origin?: string;
    mode?: 'hybrid' | 'fulltext';
    limit?: number;
    expectedReleaseId?: string | null;
    fetcher?: typeof fetch;
    signal?: AbortSignal;
  } = {},
): Promise<PassageSearchResponse> {
  const trimmed = String(query ?? '').trim();
  const origin = (options.origin || SPICYENGINE_SEARCH_ORIGIN).replace(/\/+$/, '');
  const mode = options.mode ?? 'hybrid';
  const limit = Math.min(10, Math.max(1, Number(options.limit) || 10));
  const fetcher = options.fetcher ?? fetch;

  if (!trimmed) {
    return {
      state: 'ready',
      origin,
      query: '',
      mode,
      releaseId: options.expectedReleaseId ?? null,
      releaseMismatch: false,
      total: 0,
      hasMore: false,
      tookMs: null,
      results: [],
    };
  }

  let response: Response;
  try {
    response = await fetcher(`${origin}/v1/search`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({q: trimmed, mode, limit}),
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    return {
      state: 'unavailable',
      origin,
      query: trimmed,
      mode,
      releaseId: null,
      releaseMismatch: false,
      total: 0,
      hasMore: false,
      tookMs: null,
      results: [],
      reason: error instanceof Error && error.message ? error.message : 'Network or cross-origin (CORS) request blocked',
    };
  }

  if (!response.ok) {
    return {
      state: 'unavailable',
      origin,
      query: trimmed,
      mode,
      releaseId: null,
      releaseMismatch: false,
      total: 0,
      hasMore: false,
      tookMs: null,
      results: [],
      reason: `Search service returned HTTP ${response.status}`,
    };
  }

  let payload: any;
  try {
    payload = await response.json();
  } catch {
    return {
      state: 'unavailable',
      origin,
      query: trimmed,
      mode,
      releaseId: null,
      releaseMismatch: false,
      total: 0,
      hasMore: false,
      tookMs: null,
      results: [],
      reason: 'Search service returned an unreadable response',
    };
  }

  const releaseId = typeof payload?.release_id === 'string' ? payload.release_id : null;
  const expected = options.expectedReleaseId || null;
  const releaseMismatch = Boolean(expected && releaseId && releaseId !== expected);
  const rawResults: any[] = Array.isArray(payload?.results) ? payload.results : [];
  const results: PassageHit[] = rawResults.map((hit: any) => ({
    id: String(hit?.id ?? ''),
    linkKey: extractLinkKeyFromHitId(hit?.id),
    title: String(hit?.title ?? '').trim() || 'Archived congressional document',
    url: resolveOriginUrl(origin, hit?.url) ?? `${origin}/`,
    path: typeof hit?.path === 'string' ? hit.path : null,
    crumb: typeof hit?.crumb === 'string' ? hit.crumb : null,
    kind: typeof hit?.kind === 'string' ? hit.kind : null,
    snippet: String(hit?.snippet ?? ''),
    passage: hit?.passage && typeof hit.passage === 'object' ? hit.passage : null,
    publisherUrl: resolveOriginUrl(origin, hit?.publisher_url),
    sourceUrl: resolveOriginUrl(origin, hit?.source_url),
  }));

  return {
    state: 'ready',
    origin,
    query: trimmed,
    mode: payload?.mode === 'fulltext' ? 'fulltext' : mode,
    releaseId,
    releaseMismatch,
    total: Number.isFinite(Number(payload?.total)) ? Number(payload.total) : results.length,
    hasMore: Boolean(payload?.hasMore),
    tookMs: Number.isFinite(Number(payload?.tookMs)) ? Number(payload.tookMs) : null,
    results,
  };
}

export async function readSpicySection(
  sectionUrl: string,
  options: {
    origin?: string;
    fetcher?: typeof fetch;
    signal?: AbortSignal;
  } = {},
): Promise<{state: 'ready' | 'unavailable'; content?: string; title?: string; crumb?: string | null; reason?: string}> {
  const origin = (options.origin || SPICYENGINE_SEARCH_ORIGIN).replace(/\/+$/, '');
  const fetcher = options.fetcher ?? fetch;
  let path = sectionUrl;
  if (sectionUrl.startsWith(origin + '/')) {
    path = '/' + sectionUrl.slice(origin.length + 1);
  }
  try {
    const response = await fetcher(`${origin}/v1/section?url=${encodeURIComponent(path)}`, {
      signal: options.signal,
    });
    if (!response.ok) {
      return {state: 'unavailable', reason: `Passage reader returned HTTP ${response.status}`};
    }
    const payload: any = await response.json();
    return {
      state: 'ready',
      content: typeof payload?.content === 'string' ? payload.content : '',
      title: typeof payload?.title === 'string' ? payload.title : undefined,
      crumb: typeof payload?.crumb === 'string' ? payload.crumb : null,
    };
  } catch (error) {
    if (options.signal?.aborted) throw error;
    return {
      state: 'unavailable',
      reason: error instanceof Error && error.message ? error.message : 'Unable to reach passage reader',
    };
  }
}
