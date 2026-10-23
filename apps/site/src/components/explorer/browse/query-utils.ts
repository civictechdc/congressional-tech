import { committeeSourceNote, committeeWebsite, documentSourceLabel, easternDate, filePartNote, detectedNote, issueNotes, landingPageNote, meetingStatusNote, nextScheduleChange, notableRoles, participationNote, plainLegislativeNote, providerLabel, publishedNote, recordedAction, recordedAmendments, recordedFileName, recordedMeasureValues, recordedPlace, recordedVotes, recordedWhen, recordingVisible, scheduleNote, sourceCountNote, sourceTypeNote, subjectKindLabel, witnessNotes } from './record-presentation.ts';
import { coverageAspects, evidenceStates, isEvidenceState } from './kinds.ts';
import type { CoverageAspect, CoverageGroup, CoverageSummary, EvidenceCounts, EvidenceState, ExplorerQuery, QueryInfo, QueryRow } from '../reader/types.ts';

export { coverageAspects } from './kinds.ts';

export const PAGE_SIZE = 25;

const wordsCache = new WeakMap<object, string[]>();
const textCache = new WeakMap<object, string>();
const identityFields = ['kind', 'congress', 'q', 'chamber', 'dateFrom', 'dateTo', 'month', 'type', 'status', 'category', 'severity', 'participation', 'provider', 'history', 'access', 'committeeId', 'committeeLevel', 'committeeType', 'aspect', 'evidence'] as const;

/** A comparable instant. A recorded clock breaks ties on the same day; a missing date stays blank. */
export function recordedSortKey(row: { date?: string | null; scheduled_at?: string | null }): string {
  const date = row.date || '';
  const scheduled = row.scheduled_at || '';
  const instant = scheduled && (!date || scheduled.slice(0, 10) === date.slice(0, 10)) ? Date.parse(scheduled) : Number.NaN;
  if (Number.isFinite(instant)) return String(instant).padStart(16, '0');
  if (!date) return '';
  const day = Date.parse(`${date.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(day) ? String(day).padStart(16, '0') : date;
}

/** Newest recorded date first. A record with no date stays after every dated record. */
export function compareRecordedDate(a: { date?: string | null; scheduled_at?: string | null }, b: { date?: string | null; scheduled_at?: string | null }): number {
  const left = recordedSortKey(a);
  const right = recordedSortKey(b);
  if (Boolean(left) !== Boolean(right)) return left ? -1 : 1;
  return right.localeCompare(left);
}

export function compareSearchRows(a: QueryRow, b: QueryRow): number {
  return compareRecordedDate(a, b) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id);
}

/** Reorder a filtered selection. Empty values stay last in both directions, and the default date order is left untouched. */
export function orderSearchRows(rows: readonly QueryRow[], sort: ExplorerQuery['sort'], direction: ExplorerQuery['direction']): QueryRow[] {
  if (sort !== 'record' && sort !== 'date' && sort !== 'congress' && sort !== 'kind') return [...rows];
  const sign = direction === 'desc' ? -1 : 1;
  const valueOf = (row: QueryRow): string => {
    if (sort === 'record') return [row.title || '', (row.files || []).map(recordedFileName).find(Boolean) || ''].filter(Boolean).join('\n');
    if (sort === 'date') return recordedSortKey(row);
    if (sort === 'congress') return row.congress == null ? '' : String(row.congress).padStart(3, '0');
    if (row.kind === 'appearance') return row.position || row.organization || (row.roles || []).join(' ');
    if (row.kind === 'committee_term') return row.committee_type || '';
    if (row.kind === 'data_issue') return [row.category, row.severity].filter(Boolean).join(' ');
    return row.document_type || row.type || row.category || '';
  };
  return rows.map((row, index) => ({ row, index, value: valueOf(row).toLocaleLowerCase() })).sort((a, b) => {
    if (!a.value !== !b.value) return a.value ? -1 : 1;
    const compared = a.value.localeCompare(b.value);
    return compared ? compared * sign : a.index - b.index;
  }).map(item => item.row);
}

function wordsOf(query: ExplorerQuery): string[] {
  const cached = wordsCache.get(query);
  if (cached) return cached;
  const words = plainLegislativeNote(String(query.q || '').trim()).toLocaleLowerCase().split(/\s+/).filter(Boolean);
  wordsCache.set(query, words);
  return words;
}

function searchBlob(row: QueryRow): string {
  const cached = textCache.get(row);
  if (cached !== undefined) return cached;
  const savedIssue = row.kind === 'data_issue' ? [row.explanation || '', ...(row.facts || []).map(fact => fact.value)].filter(Boolean).join(' ') : '';
  const issueText = row.kind === 'data_issue' ? [issueNotes(row).join(' '), savedIssue, detectedNote(row), subjectKindLabel(row.subject_kind)].filter(Boolean).join(' ') : '';
  const committeeText = row.kind === 'committee_term' ? [row.explanation || '', committeeWebsite(row), committeeSourceNote(row)].filter(Boolean).join(' ') : '';
  const materialNote = row.kind === 'material' ? row.explanation || '' : '';
  const level = row.committee_level === 'subcommittee' ? 'Subcommittee' : '';
  const categoryText = row.category && row.category !== 'unknown' ? row.category.replaceAll('_', ' ') : '';
  const severityText = row.severity && row.severity !== 'unknown' ? row.severity.replaceAll('_', ' ') : '';
  const statusText = [row.status, row.source_status, meetingStatusNote(row)].filter(value => value && value !== 'unknown').join(' ');
  const providerText = [row.provider || '', providerLabel(row.provider)].filter(Boolean).join(' ');
  const partText = [filePartNote(row), landingPageNote(row)].filter(Boolean).join(' ');
  const sourceType = sourceTypeNote(row);
  const sourceCount = sourceCountNote(row);
  const text = `${row.title} ${row.position || ''} ${row.organization || ''} ${row.committee_code || ''} ${(row.files || []).map(recordedFileName).filter(Boolean).join(' ')} ${recordedPlace(row)} ${scheduleNote(row)} ${recordedMeasureValues(row).join(' ')} ${recordedAction(row)} ${publishedNote(row)} ${recordedVotes(row).join(' ')} ${recordedAmendments(row).join(' ')} ${level} ${witnessNotes(row).join(' ')} ${notableRoles(row).join(' ')} ${participationNote(row)} ${issueText} ${committeeText} ${materialNote} ${row.search_text || ''} ${row.document_type || ''} ${categoryText} ${severityText} ${statusText} ${providerText} ${partText} ${sourceType} ${sourceCount} ${documentSourceLabel(row)} ${(row.source_document_groups || []).join(' ')}`.toLocaleLowerCase();
  textCache.set(row, text);
  return text;
}

export function searchIdentity(query: ExplorerQuery): string {
  return JSON.stringify(identityFields.map(field => query[field] ?? null));
}

export function matches(row: QueryRow, query: ExplorerQuery): boolean {
  const words = wordsOf(query);
  if (words.length && !words.every(word => searchBlob(row).includes(word))) return false;
  const day = recordedWhen(row).date;
  return (!query.chamber || query.chamber === 'all' || row.chamber === query.chamber)
    && (!query.dateFrom || Boolean(day && day >= query.dateFrom))
    && (!query.dateTo || Boolean(day && day <= query.dateTo))
    && (!query.month || (query.month === 'unknown' ? !day : Boolean(day.startsWith(query.month))))
    && (!query.type || query.type === 'all' || row.type === query.type)
    && (!query.status || query.status === 'all' || row.status === query.status)
    && (!query.category || row.category === query.category)
    && (!query.severity || row.severity === query.severity)
    && (!query.participation || row.participation === query.participation)
    && (!query.provider || row.provider === query.provider)
    && (!query.history || (query.history === 'retained' ? row.selection === 'retained_history' : !row.selection))
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

function committeeGroupKey(row: QueryRow): string {
  return row.committee_code && row.chamber ? `${row.chamber}/${row.committee_code.toLowerCase()}` : row.id;
}

export function selectSearchRows(source: readonly QueryRow[], query: ExplorerQuery, now: Date, options: { present?: (row: QueryRow, now: Date) => QueryRow; hideRecordings?: boolean } = {}): PreparedSearch {
  const membershipUsesPresentation = Boolean(options.present) && ((query.status && query.status !== 'all') || Boolean(query.aspect && query.evidence));
  const prepare = (raw: QueryRow) => membershipUsesPresentation && options.present ? options.present(raw, now) : raw;
  const matched: QueryRow[] = [];
  for (const raw of source) {
    const row = prepare(raw);
    if (options.hideRecordings && !recordingVisible(row, now)) continue;
    if (matches(row, query)) matched.push(row);
  }
  let grouped = matched;
  if (query.kind === 'committee_term' && query.congress === 'all' && wordsOf(query).length) {
    const keys = new Set(matched.map(committeeGroupKey));
    const asideFromText = { ...query, q: '' };
    grouped = [];
    for (const raw of source) {
      const row = prepare(raw);
      if (options.hideRecordings && !recordingVisible(row, now)) continue;
      if (keys.has(committeeGroupKey(row)) && matches(row, asideFromText)) grouped.push(row);
    }
  }
  const rows = groupCommitteeTerms(grouped, query);
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
    const key = committeeGroupKey(row);
    const terms = groups.get(key);
    if (terms) terms.push(row);
    else groups.set(key, [row]);
  }
  return [...groups.values()].map(terms => {
    terms.sort((a, b) => (b.congress || 0) - (a.congress || 0) || a.id.localeCompare(b.id));
    const latest = terms[0];
    const explanation = terms.map(term => term.explanation?.trim()).find(Boolean) || null;
    const website = terms.map(committeeWebsite).find(Boolean) || '';
    const facts = website && !committeeWebsite(latest) ? [...(latest.facts || []), { label: 'Official website or archive', value: website }] : latest.facts;
    return {
      ...latest,
      explanation,
      facts,
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
    rule: 'Each meeting has one saved result for this count. Every check stays on the meeting record.',
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
  const total = emptyGroup('all', 'Selected meetings');
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
    population: 'Meetings from Congress.gov and official committee sites that match the filters above, including every recorded status. The counts describe what was saved here for this selection.',
    limitations: ['A statement from the source, or a likely match, means the meeting was noted that way. It does not by itself mean the web address was checked, the text was saved, or the record is complete.', 'Not recorded and not checked leave the material unsettled in this collection. A failed check stays visible even when another source has the material.', 'A joint meeting is listed under each committee that held it. Committee totals overlap.'],
  };
}
