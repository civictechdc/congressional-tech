/** Date-aware display rules, shared by search, detail and coverage. */
const calendar = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });
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
