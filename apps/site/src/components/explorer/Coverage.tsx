import { useState, type CSSProperties } from 'react';
import type { CoverageAspect, CoverageGroup, CoverageSummary, EvidenceCounts, EvidenceState, ExplorerQuery } from './data-source';

const ASPECTS: readonly [CoverageAspect, string][] = [['recording', 'Recordings'], ['transcript', 'Transcripts'], ['documents', 'Documents'], ['witnesses', 'Witness lists'], ['captions', 'Captions']];
const STATES: readonly [EvidenceState, string][] = [['observed', 'Observed'], ['reported', 'Reported'], ['curated', 'Curated'], ['derived', 'Derived'], ['inferred', 'Inferred'], ['not_found_in_checked_scope', 'Not found in checked scope'], ['error', 'Check failed'], ['blocked', 'Check blocked'], ['not_applicable', 'Not applicable'], ['unknown', 'Unknown'], ['unchecked', 'Unchecked']];
const BANDS: readonly { label: string; color: string; states: readonly EvidenceState[] }[] = [
  { label: 'Observed / reported / curated / derived', color: '#104378', states: ['observed', 'reported', 'curated', 'derived'] },
  { label: 'Inferred', color: '#7c9bbb', states: ['inferred'] },
  { label: 'Not found in checked scope', color: '#eec05e', states: ['not_found_in_checked_scope'] },
  { label: 'Failed / blocked check', color: '#7a6040', states: ['error', 'blocked'] },
  { label: 'Unknown / unchecked', color: '#c7cdd4', states: ['unknown', 'unchecked'] },
  { label: 'Not applicable', color: '#eef0f3', states: ['not_applicable'] },
];
const integer = (value: number) => value.toLocaleString('en-US');
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
    <svg viewBox="0 0 160 160" role="img" aria-label={`Evidence distribution for ${integer(counts.denominator)} meeting entries. Exact counts follow in the evidence table.`}>
      <circle cx="80" cy="80" r="62" fill="none" stroke="#eef0f3" strokeWidth="21" />
      {segments.filter((segment) => segment.fraction > 0).map((segment) => <circle key={segment.label} cx="80" cy="80" r="62" fill="none" stroke={segment.color} strokeWidth="21" pathLength="1" strokeDasharray={`${segment.fraction} ${1 - segment.fraction}`} strokeDashoffset={-segment.offset} transform="rotate(-90 80 80)" />)}
      <text x="80" y="79" textAnchor="middle">{integer(counts.denominator)}</text><text x="80" y="99" textAnchor="middle" style={{ fontSize: '11px', fontWeight: 400 }}>meeting entries</text>
    </svg>
    <ul className="explorer-legend">{BANDS.map((band) => <li key={band.label}><span className="explorer-swatch" style={colorStyle(band.color)} /><span>{band.label}<br /><strong>{integer(bandCount(counts, band.states))}</strong></span></li>)}</ul>
  </div>;
}

function Bars({ groups, aspect, onGroup, limit = 12 }: { groups: readonly CoverageGroup[]; aspect: CoverageAspect; onGroup: (key: string) => void; limit?: number }) {
  const visible = groups.slice(0, limit);
  const max = Math.max(0, ...visible.map((group) => group.denominator));
  return <div className="explorer-bars">{visible.map((group) => <div className="explorer-bar-row" key={group.key}>
    <button className="explorer-text-button" onClick={() => onGroup(group.key)}>{group.label}</button>
    <div className="explorer-bar-track" role="img" aria-label={`${group.label}: ${integer(group.denominator)} meeting entries. Open to inspect this group.`}>
      {BANDS.map((band) => <span key={band.label} style={{ ...colorStyle(band.color), width: `${max ? 100 * bandCount(group.state_breakdown[aspect], band.states) / max : 0}%` }} />)}
    </div><span className="explorer-bar-total">{integer(group.denominator)}</span>
  </div>)}{groups.length > limit ? <p className="explorer-note">Showing {limit} of {integer(groups.length)} groups. All counts are available in the table below.</p> : null}</div>;
}

function EvidenceTable({ counts, aspect, onDrill }: { counts: EvidenceCounts; aspect: CoverageAspect; onDrill: (query: ExplorerQuery) => void }) {
  return <table className="explorer-table explorer-coverage-table"><thead><tr><th scope="col">Evidence state</th><th scope="col" className="explorer-number">Meeting entries</th><th scope="col" className="explorer-number">Share of selection</th></tr></thead>
    <tbody>{STATES.map(([state, label]) => <tr key={state}><th scope="row">{label}</th><td className="explorer-number"><button className="explorer-text-button" disabled={!counts.states[state]} onClick={() => onDrill({ aspect, evidence: state })}>{integer(counts.states[state] || 0)}</button></td><td className="explorer-number">{counts.denominator ? `${((counts.states[state] || 0) / counts.denominator * 100).toFixed(1)}%` : '—'}</td></tr>)}</tbody>
  </table>;
}

function GroupTable({ groups, aspect, onDrill, field }: { groups: readonly CoverageGroup[]; aspect: CoverageAspect; onDrill: (query: ExplorerQuery) => void; field: 'congress' | 'committeeId' | 'month' }) {
  return <details><summary>Table of all {field === 'committeeId' ? 'committee' : field} counts</summary><div className="explorer-table-scroll"><table className="explorer-table">
    <thead><tr><th scope="col">Group</th>{STATES.map(([state, label]) => <th scope="col" key={state}>{label}</th>)}<th scope="col">Total</th></tr></thead>
    <tbody>{groups.map((group) => <tr key={group.key}><th scope="row">{group.label}</th>{STATES.map(([state]) => <td key={state}><button className="explorer-text-button" disabled={!group.state_breakdown[aspect].states[state]} onClick={() => onDrill({ [field]: field === 'congress' ? Number(group.key) : group.key, aspect, evidence: state })}>{integer(group.state_breakdown[aspect].states[state] || 0)}</button></td>)}<td>{integer(group.denominator)}</td></tr>)}</tbody>
  </table></div></details>;
}

export default function Coverage({ summary, onDrill }: { summary: CoverageSummary; onDrill: (query: ExplorerQuery) => void }) {
  const [aspect, setAspect] = useState<CoverageAspect>('transcript');
  const [grouping, setGrouping] = useState<'congress' | 'month'>('congress');
  const counts = summary.state_breakdown[aspect];
  const positive = bandCount(counts, ['observed', 'reported', 'curated', 'derived']);
  const unresolved = bandCount(counts, ['unknown', 'unchecked', 'error', 'blocked']);
  const committees = [...summary.groups.committee].sort((a, b) => b.denominator - a.denominator);
  return <section aria-labelledby="coverage-title">
    <div className="explorer-subheading"><h2 id="coverage-title">Coverage of this selection</h2><label className="explorer-measure">Measure<select value={aspect} onChange={(event) => setAspect(event.target.value as CoverageAspect)}>{ASPECTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
    <p className="explorer-note">{summary.population}</p>
    <div className="explorer-stats"><div className="explorer-stat"><strong>{integer(counts.denominator)}</strong><span>meeting entries</span></div><div className="explorer-stat"><strong>{integer(positive)}</strong><span>with evidence beyond inference</span></div><div className="explorer-stat"><strong>{integer(counts.states.inferred || 0)}</strong><span>supported by inference only</span></div><div className="explorer-stat"><strong>{integer(unresolved)}</strong><span>unknown or not established</span></div></div>
    <div className="explorer-coverage-grid"><section><h3>Evidence states</h3><Donut counts={counts} /></section><section><div className="explorer-subheading"><h3>Meeting entries by {grouping === 'congress' ? 'Congress' : 'scheduled month'}</h3><label className="explorer-measure">Group by<select value={grouping} onChange={(event) => setGrouping(event.target.value as 'congress' | 'month')}><option value="congress">Congress</option><option value="month">Month</option></select></label></div><Bars groups={summary.groups[grouping]} aspect={aspect} onGroup={(key) => onDrill(grouping === 'congress' ? { congress: Number(key) } : { month: key })} /><p className="explorer-note">Counts use a common scale. Meeting dates do not measure improvement in collection over time.</p></section></div>
    <EvidenceTable counts={counts} aspect={aspect} onDrill={onDrill} />
    <GroupTable groups={summary.groups[grouping]} aspect={aspect} onDrill={onDrill} field={grouping} />
    <section className="explorer-detail-section"><h3>Meeting entries by committee</h3><p className="explorer-note">A jointly convened meeting appears under each associated committee. Committee totals overlap.</p><Bars groups={committees} aspect={aspect} onGroup={(key) => onDrill({ committeeId: key })} /><GroupTable groups={committees} aspect={aspect} onDrill={onDrill} field="committeeId" /></section>
    <details><summary>Counting rule and known limits</summary><p className="explorer-note">{counts.rule}</p><ul>{summary.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></details>
  </section>;
}
