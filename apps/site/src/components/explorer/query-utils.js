import { documentSourceLabel } from './record-presentation.js';

export function matches(row, query) {
    const words = String(query.q || '').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    const text = `${row.title} ${row.search_text || ''} ${row.document_type || ''} ${documentSourceLabel(row)} ${(row.source_document_groups || []).join(' ')}`.toLocaleLowerCase();
    return (!query.chamber || query.chamber === 'all' || row.chamber === query.chamber)
      && (!query.dateFrom || (row.date && row.date >= query.dateFrom))
      && (!query.dateTo || (row.date && row.date <= query.dateTo))
      && (!query.month || (query.month === 'unknown' ? !row.date : row.date?.startsWith(query.month)))
      && (!query.type || query.type === 'all' || row.type === query.type)
      && (!query.status || query.status === 'all' || row.status === query.status)
      && (!query.access || row.access === query.access)
      && (!query.committeeId || row.committee_ids?.includes(query.committeeId))
      && (!query.committeeLevel || row.committee_level === query.committeeLevel)
      && (!query.committeeType || row.committee_types?.includes(query.committeeType))
      && (!query.aspect || !query.evidence || row.evidence_states?.[query.aspect] === query.evidence)
      && words.every(word => text.includes(word));
  }
export function pageBounds(options) {
    return { offset: Math.max(0, Math.floor(Number(options.offset) || 0)), limit: Math.min(100, Math.max(1, Math.floor(Number(options.limit) || 25))) };
  }

export function summarizeCoverage(info, rows) {
    const aspects = ['recording', 'transcript', 'documents', 'witnesses', 'captions'];
    const states = ['observed', 'reported', 'curated', 'derived', 'inferred', 'error', 'blocked', 'not_found_in_checked_scope', 'not_applicable', 'unknown', 'unchecked'];
    function group(key, label) {
      return { key, label, denominator: 0, state_breakdown: Object.fromEntries(aspects.map(aspect => [aspect, {
        unit: 'meeting', denominator: 0, states: Object.fromEntries(states.map(state => [state, 0])),
        rule: 'One published evidence state per retained meeting entry. All checks remain in the record.',
      }])) };
    }
    function add(group, row) {
      group.denominator++;
      for (const aspect of aspects) {
        const state = row.evidence_states?.[aspect];
        if (!states.includes(state)) throw new Error('Meeting query index lacks a supported coverage state.');
        group.state_breakdown[aspect].denominator++;
        group.state_breakdown[aspect].states[state]++;
      }
    }
    const total = group('all', 'Selected meeting entries');
    const groups = { congress: new Map(), committee: new Map(), month: new Map() };
    for (const row of rows) {
      add(total, row);
      const entries = [
        ['congress', String(row.congress), `${row.congress}th Congress`],
        ['month', row.date?.slice(0, 7) || 'unknown', row.date?.slice(0, 7) || 'Date unknown'],
        ...(row.committee_ids || []).map(id => ['committee', id, info.committee_labels?.[id] || id]),
      ];
      for (const [kind, key, label] of entries) {
        if (!groups[kind].has(key)) groups[kind].set(key, group(key, label));
        add(groups[kind].get(key), row);
      }
    }
    return {
      state_breakdown: total.state_breakdown,
      groups: Object.fromEntries(Object.entries(groups).map(([kind, values]) => [kind, [...values.values()].sort((a, b) => kind === 'committee' ? b.denominator - a.denominator || a.label.localeCompare(b.label) : a.key.localeCompare(b.key))])),
      population: 'Retained Congress.gov meeting entries in the selected filters, all included statuses. This is evidence coverage, not an expected-publication score.',
      limitations: ['Reported and inferred evidence does not establish checked URLs, captured text, or complete coverage.', 'Unknown and unchecked do not mean absent. Failed checks remain visible even when another source supplies positive evidence.', 'Joint meetings appear for each convening committee; committee rows are not additive.'],
    };
}
