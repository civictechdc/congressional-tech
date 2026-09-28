import { toReportRows, type ReportRow } from './data.ts';

/** Data-source port for the legacy video population, separate from meeting records. */
export interface CoverageReportSource {
  load(options?: { signal?: AbortSignal }): Promise<ReportRow[]>;
}

export function createCsvReportSource({
  url,
  fetcher = globalThis.fetch,
}: {
  url: string | URL;
  fetcher?: typeof fetch;
}): CoverageReportSource {
  return {
    async load({ signal } = {}) {
      signal?.throwIfAborted();
      const response = await fetcher(url, { signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rows = toReportRows(await response.text());
      signal?.throwIfAborted();
      return rows;
    },
  };
}
