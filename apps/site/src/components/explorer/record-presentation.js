/** Date-aware display rules, shared by search, detail and coverage. */
const calendar = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });

/** Keep the API locator in the record, but send readers to its public event page. */
export function sourcePageUrl(value) {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    const event = url.hostname === 'api.congress.gov' && url.pathname.match(/^\/v3\/committee-meeting\/(\d+)\/(house|senate)\/(\d+)\/?$/);
    return event ? `https://www.congress.gov/event/${event[1]}th-congress/${event[2]}-event/${event[3]}` : value;
  } catch { return undefined; }
}

/** Embed only known player endpoints; other recordings retain their external link. */
export function recordingEmbedUrl(row, now = new Date()) {
  if (row.type !== 'recording' || !recordingVisible(row, now)) return undefined;
  try {
    const url = new URL(row.recording_url);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined;
    let video;
    if (url.hostname === 'youtu.be') video = url.pathname.slice(1);
    if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)) {
      video = url.pathname === '/watch' ? url.searchParams.get('v') : url.pathname.match(/^\/(?:embed|shorts|live)\/([^/]+)\/?$/)?.[1];
    }
    if (video && /^[\w-]{11}$/.test(video)) return `https://www.youtube.com/embed/${video}`;
    if (['www.senate.gov', 'senate.gov'].includes(url.hostname) && /^\/isvp\/?$/.test(url.pathname)
      && url.searchParams.get('comm') && url.searchParams.get('filename')) {
      url.protocol = 'https:';
      url.searchParams.set('auto_play', 'false');
      return url.href;
    }
  } catch { /* A malformed source URL still appears in the raw record. */ }
  return undefined;
}

export function documentSourceLabel(row) {
  const labels = { meetingDocuments: 'Meeting document', witnessDocuments: 'Witness document' };
  return (row.source_document_groups || []).map(group => labels[group] || group).join(' · ');
}
/** The committee's category and its organizational level are separate facts. */
export function committeeTypeLabel(row) {
  const label = value => value.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
  if (row.committee_type && !['unknown', 'subcommittee'].includes(row.committee_type)) return label(row.committee_type);
  const subcommittee = row.committee_level === 'subcommittee' || row.committee_type === 'subcommittee' || row.parent_committee_id || row.parent?.id;
  const inherited = [...new Set(row.committee_types || [])].filter(type => type && !['unknown', 'subcommittee'].includes(type));
  return subcommittee && inherited.length ? `${inherited.map(label).join(', ')} (inherited from parent)` : 'Type unrecorded';
}
function phase(row, now) {
  const start = row.scheduled_at;
  if (typeof start === 'string' && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(start)) {
    const time = Date.parse(start);
    if (Number.isFinite(time)) return time > now.getTime() ? 'upcoming' : 'past';
  }
  const date = start?.slice(0, 10) || row.date;
  if (!date) return undefined;
  const today = calendar.format(now);
  return date > today ? 'upcoming' : date < today ? 'past' : 'today';
}

export function recordingDue(row, now = new Date()) {
  return !['canceled', 'postponed', 'not_held'].includes(row.meeting_status || row.source_status || row.status)
    && !['upcoming', 'today'].includes(phase(row, now));
}

export function recordingVisible(row, now = new Date()) {
  return row.type !== 'recording' || (Boolean(row.recording_url) && recordingDue(row, now));
}

export function presentRecord(row, now = new Date()) {
  if (row.kind === 'meeting') {
    const sourceStatus = row.source_status || row.status;
    const when = phase(row, now);
    const status = ['scheduled', 'rescheduled', 'unknown', null, undefined].includes(sourceStatus) ? when || sourceStatus : sourceStatus;
    const evidence = { ...row.evidence_states };
    if (!recordingDue(row, now)) {
      evidence.recording = 'not_applicable'; evidence.captions = 'not_applicable';
    }
    return { ...row, source_status: sourceStatus, status, evidence_states: evidence };
  }
  if (row.type === 'recording' && !recordingVisible(row, now)) return { ...row, files: [], recording_url: null };
  return row;
}
