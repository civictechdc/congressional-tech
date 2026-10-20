import { documentSourceLabel, easternDate, nextScheduleChange, recordingVisible } from './record-presentation.ts';
import { coverageAspects, evidenceStates, isEvidenceState } from './kinds.ts';
import type { CoverageAspect, CoverageGroup, CoverageSummary, EvidenceCounts, EvidenceState, ExplorerQuery, QueryInfo, QueryRow } from '../reader/types.ts';

export { coverageAspects } from './kinds.ts';

export const PAGE_SIZE = 25;

const wordsCache = new WeakMap<object, string[]>();
const textCache = new WeakMap<object, string>();
const identityFields = ['kind', 'congress', 'q', 'chamber', 'dateFrom', 'dateTo', 'month', 'type', 'status', 'access', 'committeeId', 'committeeLevel', 'committeeType', 'aspect', 'evidence'] as const;

export function compareSearchRows(a: QueryRow, b: QueryRow): number {
  return (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
}

function wordsOf(query: ExplorerQuery): string[] {
  const cached = wordsCache.get(query);
  if (cached) return cached;
  const words = String(query.q || '').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  wordsCache.set(query, words);
  return words;
}

function searchBlob(row: QueryRow): string {
  const cached = textCache.get(row);
  if (cached !== undefined) return cached;
  const text = `${row.title} ${row.search_text || ''} ${row.document_type || ''} ${documentSourceLabel(row)} ${(row.source_document_groups || []).join(' ')}`.toLocaleLowerCase();
  textCache.set(row, text);
  return text;
}

export function searchIdentity(query: ExplorerQuery): string {
  return JSON.stringify(identityFields.map(field => query[field] ?? null));
}

export function matches(row: QueryRow, query: ExplorerQuery): boolean {
  const words = wordsOf(query);
  if (words.length && !words.every(word => searchBlob(row).includes(word))) return false;
  return (!query.chamber || query.chamber === 'all' || row.chamber === query.chamber)
    && (!query.dateFrom || Boolean(row.date && row.date >= query.dateFrom))
    && (!query.dateTo || Boolean(row.date && row.date <= query.dateTo))
    && (!query.month || (query.month === 'unknown' ? !row.date : Boolean(row.date?.startsWith(query.month))))
    && (!query.type || query.type === 'all' || row.type === query.type)
    && (!query.status || query.status === 'all' || row.status === query.status)
    && (!query.access || row.access === query.access)
    && (!query.committeeId || Boolean(row.committee_ids?.includes(query.committeeId)))
    && (!query.committeeLevel || row.committee_level === query.committeeLevel)
    && (!query.committeeType || Boolean(row.committee_types?.includes(query.committeeType)))
    && (!query.aspect || !query.evidence || row.evidence_states?.[query.aspect as CoverageAspect] === query.evidence);
}

export interface PreparedSearch {
  rows: QueryRow[];
  until: number;
  presentPage: boolean;
}

export function selectSearchRows(source: readonly QueryRow[], query: ExplorerQuery, now: Date, options: { present?: (row: QueryRow, now: Date) => QueryRow; hideRecordings?: boolean } = {}): PreparedSearch {
  const membershipUsesPresentation = Boolean(options.present) && ((query.status && query.status !== 'all') || Boolean(query.aspect && query.evidence));
  const matched: QueryRow[] = [];
  for (const raw of source) {
    const row = membershipUsesPresentation && options.present ? options.present(raw, now) : raw;
    if (options.hideRecordings && !recordingVisible(row, now)) continue;
    if (matches(row, query)) matched.push(row);
  }
  const rows = groupCommitteeTerms(matched, query);
  rows.sort(compareSearchRows);
  return { rows, until: nextScheduleChange(source, now), presentPage: Boolean(options.present) && !membershipUsesPresentation };
}

export function createSearchMemo(): { get(query: ExplorerQuery, now: Date): (PreparedSearch & { key: string; day: string }) | undefined; set(query: ExplorerQuery, now: Date, selected: PreparedSearch): PreparedSearch & { key: string; day: string } } {
  let memo: (PreparedSearch & { key: string; day: string }) | undefined;
  return {
    get(query, now) {
      if (!memo || memo.key !== searchIdentity(query) || memo.day !== easternDate(now) || now.getTime() >= memo.until) return undefined;
      return memo;
    },
    set(query, now, selected) {
      memo = { key: searchIdentity(query), day: easternDate(now), until: selected.until, rows: selected.rows, presentPage: selected.presentPage };
      return memo;
    },
  };
}

export function pageBounds(options: { offset?: number; limit?: number }): { offset: number; limit: number } {
  return { offset: Math.max(0, Math.floor(Number(options.offset) || 0)), limit: Math.min(100, Math.max(1, Math.floor(Number(options.limit) || PAGE_SIZE))) };
}

export function groupCommitteeTerms(rows: QueryRow[], query: ExplorerQuery): QueryRow[] {
  if (query.kind !== 'committee_term' || query.congress !== 'all') return rows;
  const groups = new Map<string, QueryRow[]>();
  for (const row of rows) {
    const key = row.committee_code && row.chamber ? `${row.chamber}/${row.committee_code.toLowerCase()}` : row.id;
    const terms = groups.get(key);
    if (terms) terms.push(row);
    else groups.set(key, [row]);
  }
  return [...groups.values()].map(terms => {
    terms.sort((a, b) => (b.congress || 0) - (a.congress || 0) || a.id.localeCompare(b.id));
    const latest = terms[0];
    return {
      ...latest,
      terms: terms.map(({ kind, id, title, congress }) => ({ kind, id, title, congress })),
      issue_count: terms.reduce((count, term) => count + (term.issue_count || 0), 0),
    };
  });
}

function emptyCounts(): EvidenceCounts {
  return {
    unit: 'meeting',
    denominator: 0,
    states: Object.fromEntries(evidenceStates.map(state => [state, 0])) as Record<EvidenceState, number>,
    rule: 'One published evidence state per retained meeting entry. All checks remain in the record.',
  };
}

function emptyGroup(key: string, label: string): CoverageGroup {
  return {
    key,
    label,
    denominator: 0,
    state_breakdown: Object.fromEntries(coverageAspects.map(aspect => [aspect, emptyCounts()])) as Record<CoverageAspect, EvidenceCounts>,
  };
}

export function summarizeCoverage(info: QueryInfo, rows: readonly QueryRow[]): CoverageSummary {
  function add(group: CoverageGroup, row: QueryRow): void {
    group.denominator++;
    for (const aspect of coverageAspects) {
      const state = row.evidence_states?.[aspect];
      if (!state || !isEvidenceState(state)) throw new Error('Meeting query index lacks a supported coverage state.');
      const counts = group.state_breakdown[aspect];
      counts.denominator++;
      counts.states[state]++;
    }
  }
  const total = emptyGroup('all', 'Selected meeting entries');
  const groups = { congress: new Map<string, CoverageGroup>(), committee: new Map<string, CoverageGroup>(), month: new Map<string, CoverageGroup>() };
  for (const row of rows) {
    add(total, row);
    const entries: [keyof typeof groups, string, string][] = [
      ['congress', String(row.congress), `${row.congress}th Congress`],
      ['month', row.date?.slice(0, 7) || 'unknown', row.date?.slice(0, 7) || 'Date unknown'],
      ...(row.committee_ids || []).map(id => ['committee', id, info.committee_labels?.[id] || id] as [keyof typeof groups, string, string]),
    ];
    for (const [kind, key, label] of entries) {
      let group = groups[kind].get(key);
      if (!group) groups[kind].set(key, group = emptyGroup(key, label));
      add(group, row);
    }
  }
  return {
    state_breakdown: total.state_breakdown,
    groups: {
      congress: [...groups.congress.values()].sort((a, b) => a.key.localeCompare(b.key)),
      committee: [...groups.committee.values()].sort((a, b) => b.denominator - a.denominator || a.label.localeCompare(b.label)),
      month: [...groups.month.values()].sort((a, b) => a.key.localeCompare(b.key)),
    },
    population: 'Collected Congress.gov and official committee meeting entries in the selected filters, all included statuses. The collection may omit meetings. This measures retained evidence, not expected publication.',
    limitations: ['Reported and inferred evidence does not establish checked URLs, captured text, or complete coverage.', 'Unknown and unchecked do not mean absent. Failed checks remain visible even when another source supplies positive evidence.', 'Joint meetings appear for each convening committee; committee rows are not additive.'],
  };
}
