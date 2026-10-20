import { useState, type CSSProperties, type ReactNode } from 'react';
import type { CoverageAspect, CoverageGroup, CoverageSummary, EvidenceCounts, EvidenceState, ExplorerQuery } from '../reader/data-source.ts';
import { integer } from './request-state';
import { coverageAspects } from '../browse/query-utils.ts';
import { evidenceStateLabels } from '../browse/record-presentation.ts';

const aspectLabels: Record<CoverageAspect, string> = { recording: 'Recordings', transcript: 'Transcripts', documents: 'Documents', witnesses: 'Witness lists', captions: 'Captions' };
const STATES: readonly [EvidenceState, string][] = (['observed', 'reported', 'curated', 'derived', 'inferred', 'not_found_in_checked_scope', 'error', 'blocked', 'not_applicable', 'unknown', 'unchecked'] as const).map(state => [state, evidenceStateLabels[state]]);
const BANDS: readonly { label: string; color: string; states: readonly EvidenceState[] }[] = [
  { label: 'Something recorded', color: '#104378', states: ['observed', 'reported', 'curated', 'derived'] },
  { label: 'Likely matches', color: '#7c9bbb', states: ['inferred'] },
  { label: 'Not found where we looked', color: '#eec05e', states: ['not_found_in_checked_scope'] },
  { label: 'Check failed or was blocked', color: '#7a6040', states: ['error', 'blocked'] },
  { label: 'Not recorded or not checked', color: '#c7cdd4', states: ['unknown', 'unchecked'] },
  { label: 'Outside this meeting', color: '#eef0f3', states: ['not_applicable'] },
];
const bandCount = (counts: EvidenceCounts, states: readonly EvidenceState[]) => states.reduce((sum, state) => sum + (counts.states[state] || 0), 0);
const colorStyle = (color: string): CSSProperties => ({ '--state-color': color } as CSSProperties);

function Donut({ counts }: { counts: EvidenceCounts }) {
  let offset = 0;
  const segments = BANDS.map((band) => {
    const fraction = counts.denominator ? bandCount(counts, band.states) / counts.denominator : 0;
    const segment = { ...band, fraction, offset };
    offset += fraction;
    return segment;
  });
  return <div className="explorer-donut">
    <svg viewBox="0 0 160 160" role="img" aria-label={`How the evidence was recorded for ${integer(counts.denominator)} meetings. Exact counts follow in the table.`}>
      <circle cx="80" cy="80" r="62" fill="none" stroke="#eef0f3" strokeWidth="21" />
      {segments.filter((segment) => segment.fraction > 0).map((segment) => <circle key={segment.label} cx="80" cy="80" r="62" fill="none" stroke={segment.color} strokeWidth="21" pathLength="1" strokeDasharray={`${segment.fraction} ${1 - segment.fraction}`} strokeDashoffset={-segment.offset} transform="rotate(-90 80 80)" />)}
      <text x="80" y="79" textAnchor="middle">{integer(counts.denominator)}</text><text x="80" y="99" textAnchor="middle" style={{ fontSize: '11px', fontWeight: 400 }}>meetings</text>
    </svg>
    <ul className="explorer-legend">{BANDS.filter(band => bandCount(counts, band.states) > 0).map((band) => <li key={band.label}><span className="explorer-swatch" style={colorStyle(band.color)} /><span>{band.label}<br /><strong>{integer(bandCount(counts, band.states))}</strong></span></li>)}</ul>
  </div>;
}

function Bars({ groups, aspect, onGroup, limit = 12 }: { groups: readonly CoverageGroup[]; aspect: CoverageAspect; onGroup: (key: string) => void; limit?: number }) {
  const visible = groups.slice(0, limit);
  const max = Math.max(0, ...visible.map((group) => group.denominator));
  return <div className="explorer-bars">{visible.map((group) => <div className="explorer-bar-row" key={group.key}>
    <button className="explorer-text-button" aria-label={`Open the meetings counted for ${group.label}`} onClick={() => onGroup(group.key)}>{group.label}</button>
    <div className="explorer-bar-track" role="img" aria-label={`${group.label}: ${integer(group.denominator)} meetings. Open to inspect this group.`}>
      {BANDS.map((band) => <span key={band.label} style={{ ...colorStyle(band.color), width: `${max ? 100 * bandCount(group.state_breakdown[aspect], band.states) / max : 0}%` }} />)}
    </div><span className="explorer-bar-total">{integer(group.denominator)}</span>
  </div>)}{groups.length > limit ? <p className="explorer-note">Showing {limit} of {integer(groups.length)} groups. All counts are available in the table below.</p> : null}</div>;
}

function EvidenceTable({ counts, aspect, onDrill }: { counts: EvidenceCounts; aspect: CoverageAspect; onDrill: (query: ExplorerQuery) => void }) {
  return <table className="explorer-table explorer-coverage-table"><thead><tr><th scope="col">Result</th><th scope="col" className="explorer-number">Meetings</th><th scope="col" className="explorer-number">Share of selection</th></tr></thead>
    <tbody>{STATES.map(([state, label]) => <tr key={state}><th scope="row">{label}</th><td className="explorer-number"><button className="explorer-text-button" aria-label={`List meetings whose ${aspectLabels[aspect]} evidence is ${label}`} disabled={!counts.states[state]} onClick={() => onDrill({ aspect, evidence: state })}>{integer(counts.states[state] || 0)}</button></td><td className="explorer-number">{counts.denominator ? `${((counts.states[state] || 0) / counts.denominator * 100).toFixed(1)}%` : '—'}</td></tr>)}</tbody>
  </table>;
}

function OpenDetails({ summary, reason, children }: { summary: string; reason: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>{summary}<span className="explorer-field-reason">{reason}</span></summary>{open ? children : null}</details>;
}

function GroupTable({ groups, aspect, onDrill, field }: { groups: readonly CoverageGroup[]; aspect: CoverageAspect; onDrill: (query: ExplorerQuery) => void; field: 'congress' | 'committeeId' | 'month' }) {
  return <OpenDetails summary={`Table of all ${field === 'committeeId' ? 'committee' : field === 'congress' ? 'Congress' : 'month'} counts`} reason="Every group in the selection, including those beyond the chart."><div className="explorer-table-scroll"><table className="explorer-table">
    <thead><tr><th scope="col">Group</th>{STATES.map(([state, label]) => <th scope="col" key={state}>{label}</th>)}<th scope="col">Total</th></tr></thead>
    <tbody>{groups.map((group) => <tr key={group.key}><th scope="row">{group.label}</th>{STATES.map(([state, label]) => <td key={state}><button className="explorer-text-button" aria-label={`List ${group.label} meetings whose ${aspectLabels[aspect]} evidence is ${label}`} disabled={!group.state_breakdown[aspect].states[state]} onClick={() => onDrill({ [field]: field === 'congress' ? Number(group.key) : group.key, aspect, evidence: state })}>{integer(group.state_breakdown[aspect].states[state] || 0)}</button></td>)}<td>{integer(group.denominator)}</td></tr>)}</tbody>
  </table></div></OpenDetails>;
}

export default function Coverage({ summary, onDrill, aspect, grouping, onAspect, onGrouping }: { summary: CoverageSummary; onDrill: (query: ExplorerQuery) => void; aspect: CoverageAspect; grouping: 'congress' | 'month'; onAspect: (value: CoverageAspect) => void; onGrouping: (value: 'congress' | 'month') => void }) {
  const counts = summary.state_breakdown[aspect];
  const positive = bandCount(counts, ['observed', 'reported', 'curated', 'derived']);
  const failed = bandCount(counts, ['error', 'blocked']);
  const unresolved = bandCount(counts, ['unknown', 'unchecked', 'error', 'blocked']);
  const committees = [...summary.groups.committee].sort((a, b) => b.denominator - a.denominator);
  return <section aria-labelledby="coverage-title">
    <div className="explorer-subheading"><h2 id="coverage-title">Coverage of this selection</h2><label className="explorer-measure"><span>Measure</span><span className="explorer-field-reason">Which recorded evidence the counts describe.</span><select aria-label="Coverage measure. Which recorded evidence the counts describe." value={aspect} onChange={(event) => onAspect(event.target.value as CoverageAspect)}>{coverageAspects.map(value => <option key={value} value={value}>{aspectLabels[value as CoverageAspect] ?? value}</option>)}</select></label></div>
    <p className="explorer-note">{summary.population}</p>
    <div className="explorer-stats"><div className="explorer-stat"><strong>{integer(counts.denominator)}</strong><span>meetings</span></div><div className="explorer-stat"><strong>{integer(positive)}</strong><span>with something recorded</span></div><div className="explorer-stat"><strong>{integer(counts.states.inferred || 0)}</strong><span>likely matches</span></div><div className="explorer-stat"><strong>{integer(unresolved)}</strong><span>{failed ? 'not checked or failed' : 'not recorded or not checked'}</span></div></div>
    <div className="explorer-coverage-grid"><section><h3>What was recorded</h3><Donut counts={counts} /></section><section><div className="explorer-subheading"><h3>Meetings by {grouping === 'congress' ? 'Congress' : 'scheduled month'}</h3><label className="explorer-measure"><span>Group by</span><span className="explorer-field-reason">Split the same counts by Congress or by month.</span><select aria-label="Coverage grouping. Split the same counts by Congress or by month." value={grouping} onChange={(event) => onGrouping(event.target.value as 'congress' | 'month')}><option value="congress">Congress</option><option value="month">Month</option></select></label></div><Bars groups={summary.groups[grouping]} aspect={aspect} onGroup={(key) => onDrill(grouping === 'congress' ? { congress: Number(key) } : { month: key })} /><p className="explorer-note">Counts use a common scale. Meeting dates show when meetings were scheduled, not whether collection got better over time.</p></section></div>
    <OpenDetails summary="Counts for each result" reason="How many meetings have each result."><div className="explorer-table-scroll"><EvidenceTable counts={counts} aspect={aspect} onDrill={onDrill} /></div></OpenDetails>
    <GroupTable groups={summary.groups[grouping]} aspect={aspect} onDrill={onDrill} field={grouping} />
    <section className="explorer-detail-section"><h3>Meetings by committee</h3><p className="explorer-note">A jointly convened meeting appears under each associated committee. Committee totals overlap.</p><Bars groups={committees} aspect={aspect} onGroup={(key) => onDrill({ committeeId: key })} /><GroupTable groups={committees} aspect={aspect} onDrill={onDrill} field="committeeId" /></section>
    <details><summary>Counting rule and known limits<span className="explorer-field-reason">How these counts were produced, and the limits of what they show.</span></summary><p className="explorer-note">{counts.rule}</p><ul>{summary.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></details>
  </section>;
}
