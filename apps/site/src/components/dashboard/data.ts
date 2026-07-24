/** CSV parsing + aggregation for the YouTube coverage dashboard. */

export interface ReportRow {
  committee: string;
  handle: string;
  totalVideos: number;
  missing: number;
  congress: number;
  control: string;
  chamber: string;
}

export interface CongressInfo {
  start: string;
  end: string;
  senate: string;
  house: string;
}

/** Minimal quote-aware CSV parser (handles quoted commas and "" escapes). */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else if (c !== '\r') {
      field += c;
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function toReportRows(csv: string): ReportRow[] {
  const [header, ...body] = parseCsv(csv);
  if (!header) return [];
  const col = (name: string) => header.indexOf(name);
  const committee = col('committee_name');
  const handle = col('handle');
  const total = col('total_videos');
  const missing = col('missing_event_id');
  const congress = col('congress_number');
  const control = col('control');
  const chamber = col('chamber');
  return body
    .filter((cells) => cells.length >= header.length)
    .map((cells) => ({
      committee: cells[committee] ?? '',
      handle: cells[handle] ?? '',
      totalVideos: Number(cells[total] ?? 0),
      missing: Number(cells[missing] ?? 0),
      congress: Number(cells[congress] ?? 0),
      control: cells[control] ?? '',
      chamber: cells[chamber] ?? '',
    }))
    .filter((row) => row.committee !== '' && Number.isFinite(row.congress));
}

export interface Totals {
  total: number;
  missing: number;
  withId: number;
}

export function sumTotals(rows: ReportRow[]): Totals {
  const total = rows.reduce((acc, r) => acc + r.totalVideos, 0);
  const missing = rows.reduce((acc, r) => acc + r.missing, 0);
  return { total, missing, withId: total - missing };
}

export function groupBy<K extends string | number>(
  rows: ReportRow[],
  key: (row: ReportRow) => K,
): Map<K, ReportRow[]> {
  const out = new Map<K, ReportRow[]>();
  for (const row of rows) {
    const k = key(row);
    const bucket = out.get(k);
    if (bucket) bucket.push(row);
    else out.set(k, [row]);
  }
  return out;
}

export const formatInt = new Intl.NumberFormat('en-US');

export function pct(part: number, whole: number): number {
  return whole === 0 ? 0 : (part / whole) * 100;
}

/** "106" → "106th" */
export function ordinal(n: number): string {
  const rem10 = n % 10;
  const rem100 = n % 100;
  if (rem10 === 1 && rem100 !== 11) return `${n}st`;
  if (rem10 === 2 && rem100 !== 12) return `${n}nd`;
  if (rem10 === 3 && rem100 !== 13) return `${n}rd`;
  return `${n}th`;
}
