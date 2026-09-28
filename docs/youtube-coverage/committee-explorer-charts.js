// Preview-only summaries. Production charts consume published, reconciled metrics.
export const measures = {
  transcript: { label: 'Printed text', listed: 'Text linked', center: 'have linked text', note: 'A listed text source may cover only part of a meeting. It does not establish retained or searchable text.' },
  recording: { label: 'Recordings', listed: 'Recording linked', center: 'have a recording link', note: 'Only meeting-linked recordings count here. Unmatched archive recordings remain visible in Recordings & documents.' },
  witnesses: { label: 'Witness lists', listed: 'List recorded', center: 'have a witness list', note: 'A recorded witness list establishes neither attendance nor a verified person identity.' },
};

const states = ['listed', 'not_found', 'unknown'];
const colors = { listed: '#104378', not_found: '#eec05e', unknown: '#c7cdd5' };
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const labels = measure => ({ listed: measures[measure].listed, not_found: 'Not found in checked scope', unknown: 'Not established' });
const same = (ref, record) => ref?.kind === record.kind && ref?.id === record.id;

export function evidenceState(meeting, measure, records) {
  const direct = records.filter(r => r.provenance?.basis !== 'inferred');
  const found = measure === 'witnesses'
    ? direct.some(r => r.kind === 'appearance' && same(r.meeting, meeting))
    : direct.some(r => r.kind === 'material_link' && same(r.subject, meeting) && r.role === measure);
  if (found) return 'listed';
  // A failed request, an undated negative or an inference is never an absence finding.
  const checked = direct.some(r => r.kind === 'assessment' && same(r.subject, meeting)
    && r.aspect === measure && r.status === 'not_found' && r.observed_at && r.scope);
  return checked ? 'not_found' : 'unknown';
}

export function summarize(meetings, measure, records) {
  const totals = { listed: 0, not_found: 0, unknown: 0, total: meetings.length };
  for (const meeting of meetings) totals[evidenceState(meeting, measure, records)]++;
  return totals;
}

// One meeting, one first reported occurrence date; multiple sittings do not inflate totals.
export function meetingWeek(meeting, records) {
  const dates = records.filter(r => r.kind === 'occurrence' && same(r.meeting, meeting))
    .map(r => (r.actual_start || r.scheduled_start)?.date).filter(Boolean).sort();
  if (!dates.length) return 'undated';
  const day = new Date(dates[0] + 'T12:00:00Z');
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
  return day.toISOString().slice(0, 10);
}

export function weekLabel(week) {
  if (week === 'undated') return 'Date unknown';
  return new Date(week + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

function legend(measure) {
  return `<ul class="chart-legend">${states.map(s => `<li><span class="chart-swatch ${s}" aria-hidden="true"></span>${escape(labels(measure)[s])}</li>`).join('')}</ul>`;
}

function table(groups, measure, route, dimension) {
  return `<details class="chart-table"><summary>View ${dimension} data as a table</summary><div class="chart-table-scroll"><table><caption class="sr-only">${escape(measures[measure].label)} by ${dimension}; counts of meetings</caption><thead><tr><th scope="col">${dimension === 'week' ? 'Week beginning' : 'Committee'}</th>${states.map(s => `<th scope="col">${escape(labels(measure)[s])}</th>`).join('')}<th scope="col">Total</th></tr></thead><tbody>${groups.map(g => `<tr><th scope="row">${escape(g.label)}</th>${states.map(s => `<td>${g[s] ? `<a data-route href="${escape(route({ view: 'meetings', evidence: s, [dimension === 'week' ? 'period' : 'committee']: g.id, kind: '', id: '', version: '' }))}">${g[s]}<span class="sr-only"> ${escape(labels(measure)[s])} in ${escape(g.label)}</span></a>` : '0'}</td>`).join('')}<td>${g.total}</td></tr>`).join('')}</tbody></table></div></details>`;
}

function donut(totals, measure, route) {
  const circumference = 2 * Math.PI * 76;
  let offset = 0;
  const segments = states.map(s => {
    const length = totals[s] / totals.total * circumference;
    const arc = length ? `<circle cx="100" cy="100" r="76" fill="none" stroke="${s === 'unknown' ? 'url(#coverage-unknown)' : colors[s]}" stroke-width="25" stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 100 100)"><title>${escape(labels(measure)[s])}: ${totals[s]} meetings</title></circle>` : '';
    offset += length;
    return arc;
  }).join('');
  return `<div class="chart-donut"><svg viewBox="0 0 200 200" role="img" aria-label="${totals.listed} of ${totals.total} meetings ${escape(measures[measure].center)}; ${totals.not_found} not found in checked scope; ${totals.unknown} not established"><defs><pattern id="coverage-unknown" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#e1e5ea"/><line x1="0" x2="0" y1="0" y2="6" stroke="#b6bfca" stroke-width="2"/></pattern></defs>${segments}<text x="100" y="98" text-anchor="middle" class="chart-percent">${Math.round(totals.listed / totals.total * 100)}%</text><text x="100" y="122" text-anchor="middle" class="chart-ring-caption">${escape(measures[measure].center)}</text></svg><dl class="chart-figures">${states.map(s => `<div><dt><span class="chart-swatch ${s}" aria-hidden="true"></span>${escape(labels(measure)[s])}</dt><dd>${totals[s] ? `<a data-route href="${escape(route({ view: 'meetings', evidence: s, committee: '', period: '', kind: '', id: '', version: '' }))}" aria-label="Show ${totals[s]} meeting${totals[s] === 1 ? '' : 's'}: ${escape(labels(measure)[s])}">${totals[s]}</a>` : '0'}</dd></div>`).join('')}</dl></div>`;
}

function columns(groups, measure) {
  const max = Math.max(...groups.map(g => g.total), 1), width = 600, height = 240;
  const left = 30, top = 24, bottom = 191, plotHeight = bottom - top;
  const band = (width - left - 12) / groups.length, barWidth = Math.min(46, band * .6);
  const step = Math.max(1, Math.ceil(max / 4));
  const ticks = Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step);
  const grid = ticks.map(n => `<line x1="${left}" x2="${width - 12}" y1="${bottom - n / max * plotHeight}" y2="${bottom - n / max * plotHeight}" stroke="#dce1e7"/><text x="${left - 8}" y="${bottom - n / max * plotHeight + 4}" text-anchor="end" class="chart-axis">${n}</text>`).join('');
  const bars = groups.map((g, i) => {
    const x = left + band * i + (band - barWidth) / 2;
    let y = bottom;
    const segments = states.map(s => {
      const h = g[s] / max * plotHeight;
      y -= h;
      return h ? `<rect x="${x}" y="${y}" width="${barWidth}" height="${h}" fill="${s === 'unknown' ? 'url(#column-unknown)' : colors[s]}"><title>Week of ${escape(g.label)} · ${escape(labels(measure)[s])}: ${g[s]} meetings</title></rect>` : '';
    }).join('');
    return `${segments}<text x="${x + barWidth / 2}" y="${y - 8}" text-anchor="middle" class="chart-total">${g.total}</text><text x="${x + barWidth / 2}" y="${bottom + 23}" text-anchor="middle" class="chart-axis">${escape(g.label)}</text>`;
  }).join('');
  return `<svg class="chart-columns" viewBox="0 0 ${width} ${height}" role="img" aria-label="Meetings by week of first occurrence, split by ${escape(measures[measure].label.toLowerCase())} evidence. Exact counts and links follow in the table."><defs><pattern id="column-unknown" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#e1e5ea"/><line x1="0" x2="0" y1="0" y2="6" stroke="#b6bfca" stroke-width="2"/></pattern></defs>${grid}${bars}</svg>`;
}

export function renderCoverage({ meetings, records, measure, route }) {
  if (!meetings.length) return '<div class="empty"><h2>No meetings match these filters</h2><p class="muted">Clear the filters to see coverage. An empty population has no coverage percentage.</p></div>';
  const totals = summarize(meetings, measure, records);
  const weeks = [...new Set(meetings.map(m => meetingWeek(m, records)))].sort();
  // Show zero-count weeks inside the observed range; never imply coverage outside it.
  const dated = weeks.filter(w => w !== 'undated');
  if (dated.length) for (const cursor = new Date(dated[0] + 'T12:00:00Z'); cursor.toISOString().slice(0, 10) < dated.at(-1); cursor.setUTCDate(cursor.getUTCDate() + 7)) {
    const key = cursor.toISOString().slice(0, 10);
    if (!weeks.includes(key)) weeks.push(key);
  }
  weeks.sort();
  const weekly = weeks.map(id => ({ id, label: weekLabel(id), ...summarize(meetings.filter(m => meetingWeek(m, records) === id), measure, records) }));
  const committees = records.filter(r => r.kind === 'committee_term').map(c => ({ id: c.id, label: c.name, ...summarize(meetings.filter(m => m.committees.some(link => same(link.committee, c))), measure, records) })).filter(g => g.total).sort((a, b) => b.total - a.total || a.label.localeCompare(b.label));
  const maximum = Math.max(...committees.map(g => g.total), 1);
  return `<div class="coverage-heading"><div><h2>Coverage & what remains unknown</h2><p class="coverage-intro">${meetings.length} synthetic meetings · Congress 119 · All meeting statuses included.<br>Each meeting counts once per measure. This is recorded evidence, not a completeness score.</p></div><a class="link-button" href="https://civictechdc.github.io/congressional-tech/dashboard/" target="_blank" rel="noopener">Original YouTube report ↗</a></div>
  <div class="chart-summary"><div><span>Meetings in this slice</span><strong>${totals.total}</strong></div><div><span>${escape(measures[measure].listed)}</span><strong>${totals.listed}<small> / ${totals.total}</small></strong></div><div><span>Not found in checked scope</span><strong>${totals.not_found}</strong></div><div><span>Not established</span><strong>${totals.unknown}</strong></div></div>
  <div class="chart-grid"><section class="chart-section" aria-labelledby="coverage-chart-title"><h3 id="coverage-chart-title">${escape(measures[measure].label)} coverage</h3><p class="chart-description">${escape(measures[measure].note)}</p>${donut(totals, measure, route)}<p class="chart-footnote">Select a count to inspect its records. Gray hatching means no supported positive link or dated negative check for this measure.</p></section>
  <section class="chart-section" aria-labelledby="weekly-chart-title"><h3 id="weekly-chart-title">By meeting week</h3><p class="chart-description">Meetings grouped by their first actual or scheduled date. This shows the archive's distribution, not improvement over time.</p>${legend(measure)}${columns(weekly, measure)}${table(weekly, measure, route, 'week')}</section></div>
  <section class="chart-section chart-committees" aria-labelledby="committee-chart-title"><div class="chart-section-heading"><div><h3 id="committee-chart-title">By committee</h3><p class="chart-description">Same counting rule and scale across committees. Shared meetings appear under each host; these rows are not additive.</p></div>${legend(measure)}</div><ol class="chart-board">${committees.map(g => `<li><a class="chart-committee-name" data-route href="${escape(route({ view: 'meetings', evidence: '', committee: g.id, period: '', kind: '', id: '', version: '' }))}">${escape(g.label)}</a><span class="chart-board-track" aria-hidden="true">${states.map(s => g[s] ? `<span class="${s}" style="width:${g[s] / maximum * 100}%" title="${escape(labels(measure)[s])}: ${g[s]}"></span>` : '').join('')}</span><span class="chart-board-value">${g.listed} / ${g.total}<small>${escape(measures[measure].listed.toLowerCase())}</small></span></li>`).join('')}</ol>${table(committees, measure, route, 'committee')}</section>
  <div class="notice"><strong>A check has a scope and a date</strong><p>“Not found” means a particular search did not find the material. Scheduled, canceled and postponed meetings remain visible; no missing-item finding is inferred from their status. Source conflicts and corrections are tracked separately in <a data-route href="${escape(route({ view: 'gaps', evidence: '', committee: '', period: '', kind: '', id: '', q: '', status: 'open' }))}">Gaps & issues</a>.</p></div><p class="scope-note">These charts adapt the original dashboard’s donut, columns and committee bars. The production YouTube Event ID report keeps its own video denominator and Congress/party filters; synthetic meeting counts never replace it.</p>`;
}
