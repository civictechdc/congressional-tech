// Pure provenance assembly. Display URL grouping may prefer HTTPS; graph edges
// retain the exact protocol and only explicit single-page relationships connect.

export interface ProvenancePage {
  urls: unknown[];
  titles: unknown[];
  link_labels: unknown[];
  link_urls: unknown[];
  relationship: string;
  types?: unknown[];
  dates?: unknown[];
}

export interface SourceContext {
  file_url: string | null;
  recovered_urls: unknown[];
  pages: ProvenancePage[];
  redirects: { original: string; final: string }[];
}

export interface ProvenanceEdge {
  to: string;
  page?: ProvenancePage;
  redirect?: boolean;
}

export interface EvidenceGraph {
  paths: { root: ProvenancePage; path: ProvenanceEdge[] }[];
  references: { url: unknown; pages: ProvenancePage[] }[];
  referenceByKey: Map<string | null, { url: unknown; pages: ProvenancePage[] }>;
  metrics: Record<string, number>;
}

interface LooseRecord {
  source_url?: unknown;
  recovered_source_url?: unknown;
  source_occurrences?: LooseRecord[] | null;
  source_association_basis?: unknown;
  source_associated_url?: unknown;
  source_page_title?: unknown;
  source_link_label?: unknown;
  source_link_url?: unknown;
  source_occurrence_scope?: unknown;
  source_page_type?: unknown;
  source_page_date?: unknown;
  [key: string]: unknown;
}

const values = (value: unknown): unknown[] => Array.isArray(value) ? value : value == null ? [] : [value];
const presentList = (value: unknown): boolean => Array.isArray(value) ? value.length > 0 : typeof value === 'string' && value.length > 0;

export function validUrl(value: unknown): URL | null {
  if (typeof value !== 'string' && !(value instanceof URL)) return null;
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export const provenanceUrlKey = (value: unknown): string | null => {
  const url = validUrl(value);
  return url ? url.host + url.pathname + url.search + url.hash : null;
};

export function appendOriginPage(current: { origin: SourceContext; next: number | null }, page: { origin: SourceContext; next?: number | null }): { origin: SourceContext; next: number | null } {
  return { origin: mergeOrigin(current.origin, page.origin), next: page.next ?? null };
}

export function mergeOrigin(previous: SourceContext, added: SourceContext): SourceContext {
  const unique = <T,>(items: T[], key: (item: T) => string): T[] => [...new Map(items.map(item => [key(item), item])).values()];
  return {
    ...previous,
    pages: unique([...previous.pages, ...added.pages], page => JSON.stringify(page)),
    redirects: unique([...previous.redirects, ...added.redirects], row => JSON.stringify([row.original, row.final])),
    recovered_urls: [...new Set([...previous.recovered_urls, ...(added.recovered_urls || [])])],
  };
}

export function evidenceGraph(input: SourceContext): EvidenceGraph {
  const origin = mergeOrigin({ pages: [], redirects: [], recovered_urls: [], file_url: null }, input);
  const edges = new Map<string, ProvenanceEdge[]>();
  const ancestors: ProvenancePage[] = [];
  const targets = new Set<string | undefined>();
  const unique = new Map<string | null, { url: unknown; pages: ProvenancePage[] }>();
  const exact = (value: unknown) => validUrl(value)?.href;
  const metrics: Record<string, number> = { edgeVisits: 0, queueVisits: 0, pathEdges: 0, pathCopies: 0 };
  for (const page of origin.pages) {
    if (page.urls.length === 1 && page.link_urls.length === 1 && page.relationship !== 'Possible source page') {
      const from = exact(page.urls[0]);
      const to = exact(page.link_urls[0]);
      if (from && to && from !== to) {
        if (!edges.has(from)) edges.set(from, []);
        edges.get(from)!.push({ page, to });
        if (page.relationship === 'Linked through') { ancestors.push(page); targets.add(to); }
      }
    }
    for (const value of page.urls) {
      const url = validUrl(value);
      if (!url) continue;
      const key = provenanceUrlKey(value);
      if (!unique.has(key)) unique.set(key, { url: value, pages: [] });
      const item = unique.get(key)!;
      item.pages.push(page);
      if (url.protocol === 'https:') item.url = value;
    }
  }
  for (const redirect of origin.redirects) {
    const from = exact(redirect.original);
    const to = exact(redirect.final);
    if (!from || !to) continue;
    if (!edges.has(from)) edges.set(from, []);
    edges.get(from)!.push({ to, redirect: true });
  }
  const roots = ancestors.filter(page => !targets.has(exact(page.urls[0])) || (page.types || []).some(type => /hearing/i.test(String(type))));
  const paths: EvidenceGraph['paths'] = [];
  const rendered = new Set<string | undefined>();
  const target = exact(input.file_url);
  const incoming = new Map<string | undefined, string[]>();
  for (const [from, outgoing] of edges) for (const edge of outgoing) {
    if (!incoming.has(edge.to)) incoming.set(edge.to, []);
    incoming.get(edge.to)!.push(from);
  }
  const distance = new Map<string | undefined, number>([[target, 0]]);
  const queue: (string | undefined)[] = [target];
  for (let i = 0; i < queue.length; i++) {
    const to = queue[i];
    metrics.queueVisits++;
    for (const from of incoming.get(to) || []) {
      metrics.edgeVisits++;
      if (!distance.has(from)) { distance.set(from, distance.get(to)! + 1); queue.push(from); }
    }
  }
  for (const root of roots) {
    const start = exact(root.urls[0]);
    if (rendered.has(start) || !distance.has(start)) continue;
    const path: ProvenanceEdge[] = [];
    for (let current = start; current !== target;) {
      const edge = edges.get(current!)!.find(candidate => {
        metrics.edgeVisits++;
        return distance.get(candidate.to) === distance.get(current)! - 1;
      });
      path.push(edge!);
      metrics.pathEdges++;
      current = edge!.to;
    }
    rendered.add(start);
    paths.push({ root, path });
  }
  const covered = new Set(paths.flatMap(({ path }) => path.filter(edge => edge.page).map(edge => provenanceUrlKey(edge.page!.urls[0]))));
  metrics.pathPageLinks = paths.reduce((count, { path }) => count + path.filter(edge => edge.page).length, 0);
  metrics.uncoveredReferences = [...unique.keys()].filter(key => !covered.has(key)).length;
  return { paths, references: [...unique.values()], referenceByKey: unique, metrics };
}

export function sourceContext(record: LooseRecord): SourceContext {
  const file_url = typeof record.source_url === 'string' && validUrl(record.source_url) ? record.source_url : null;
  const recovered_urls = values(record.recovered_source_url).filter(value => validUrl(value));
  const pages: ProvenancePage[] = [];
  const redirects: SourceContext['redirects'] = [];
  const seen = new Set<string>();
  const redirectKeys = new Set<unknown>();
  const recovered = new Set<unknown>(recovered_urls);
  const observations = record.source_occurrences?.length ? record.source_occurrences : [record];
  for (const observation of observations) {
    const basis = values(observation.source_association_basis);
    if (basis.includes('publisher_redirect') && !basis.includes('linked_page') && file_url) for (const original of values(observation.source_associated_url)) {
      if (validUrl(original) && original !== file_url && !redirectKeys.has(original)) {
        redirects.push({ original: String(original), final: file_url });
        redirectKeys.add(original);
      }
    }
    const urls = [...new Set(['source_original_page_url', 'source_page_url'].flatMap(key => values(observation[key])))].filter(value => validUrl(value) && value !== file_url && !recovered.has(value));
    if (!urls.length) continue;
    const page: ProvenancePage = {
      urls,
      titles: values(observation.source_page_title),
      link_labels: values(observation.source_link_label),
      link_urls: values(observation.source_link_url).filter(value => validUrl(value)),
      relationship: basis.some(value => !['publisher_redirect', 'retained_html_link', 'linked_page'].includes(String(value))) ? 'Possible source page' : basis.includes('linked_page') ? 'Linked through' : JSON.stringify(observation.source_occurrence_scope) === '["anchor"]' ? 'Linked from' : 'Recorded source page',
    };
    if (presentList(observation.source_page_type)) page.types = values(observation.source_page_type);
    if (presentList(observation.source_page_date)) page.dates = values(observation.source_page_date);
    const key = JSON.stringify(page);
    if (!seen.has(key)) { pages.push(page); seen.add(key); }
  }
  return { file_url, recovered_urls, pages, redirects };
}
