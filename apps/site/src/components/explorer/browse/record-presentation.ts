import { filenameManifestUrl } from '../reader/filenames/publication.ts';
import type { CoverageAspect, EvidenceState } from './kinds.ts';

const calendar = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' });

export interface DisplayRow {
  kind?: string;
  id?: string;
  type?: string | null;
  title?: string | null;
  date?: string | null;
  scheduled_at?: string | null;
  status?: string | null;
  source_status?: string | null;
  meeting_status?: string | null;
  recording_url?: string | null;
  evidence_states?: Partial<Record<CoverageAspect, EvidenceState>>;
  files?: readonly { url?: string | null }[] | null;
  committee_level?: string | null;
  committee_type?: string | null;
  committee_types?: readonly (string | null | undefined)[] | null;
  parent_committee_id?: string | null;
  congress?: number | null;
  parent?: { id?: string | null } | null;
  source_document_groups?: readonly string[] | null;
  document_type?: string | null;
  search_text?: string | null;
}

type Phase = 'upcoming' | 'past' | 'today';

export function easternDate(now: Date): string {
  return calendar.format(now);
}

function scheduledInstant(row: DisplayRow): number | undefined {
  const start = row.scheduled_at;
  if (typeof start === 'string' && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(start)) {
    const time = Date.parse(start);
    if (Number.isFinite(time)) return time;
  }
  return undefined;
}

export function sourcePageUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    const event = url.hostname === 'api.congress.gov' && url.pathname.match(/^\/v3\/committee-meeting\/(\d+)\/(house|senate)\/(\d+)\/?$/);
    return event ? `https://www.congress.gov/event/${event[1]}th-congress/${event[2]}-event/${event[3]}` : value;
  } catch {
    return undefined;
  }
}

export function recordingEmbedUrl(row: DisplayRow, now = new Date()): string | undefined {
  if (row.type !== 'recording' || !recordingVisible(row, now) || !row.recording_url) return undefined;
  try {
    const url = new URL(row.recording_url);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined;
    let video: string | undefined;
    if (url.hostname === 'youtu.be') video = url.pathname.slice(1);
    if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)) {
      video = url.pathname === '/watch' ? url.searchParams.get('v') ?? undefined : url.pathname.match(/^\/(?:embed|shorts|live)\/([^/]+)\/?$/)?.[1];
    }
    if (video && /^[\w-]{11}$/.test(video)) return `https://www.youtube.com/embed/${video}`;
    if (['www.senate.gov', 'senate.gov'].includes(url.hostname) && /^\/isvp\/?$/.test(url.pathname)
      && url.searchParams.get('comm') && url.searchParams.get('filename')) {
      url.protocol = 'https:';
      url.searchParams.set('auto_play', 'false');
      return url.href;
    }
  } catch { /* A malformed source URL stays in the raw record. */ }
  return undefined;
}

export function savedCopyHref(file: { saved_copy_sha256?: string | null; saved_filename?: string | null } | null | undefined, manifestUrl = filenameManifestUrl): string | undefined {
  if (!file || typeof file.saved_copy_sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(file.saved_copy_sha256)) return undefined;
  const hash = file.saved_copy_sha256;
  const name = typeof file.saved_filename === 'string' ? file.saved_filename : '';
  const filename = name && !/[/\\]/.test(name) && !/[\u0000-\u001f\u007f]/.test(name) ? name : 'saved-copy';
  try { return new URL(`/saved/${hash}/${encodeURIComponent(filename)}`, manifestUrl).href; }
  catch { return undefined; }
}

const sourceGroupLabels: Record<string, string> = { meetingDocuments: 'Meeting document', witnessDocuments: 'Witness document' };

export function documentSourceLabel(row: DisplayRow): string {
  return (row.source_document_groups || []).map(group => sourceGroupLabels[group] || group).join(' · ');
}

export function parentCommitteeId(row: DisplayRow | null | undefined): string | undefined {
  return row?.parent_committee_id || row?.parent?.id || undefined;
}

export function committeeLevelLabel(row: DisplayRow): string {
  if (row.committee_level === 'full') return 'Full committee';
  if (row.committee_level === 'subcommittee') return 'Subcommittee';
  return '';
}

export function committeeTypeLabel(row: DisplayRow): string {
  const label = (value: string) => value.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
  if (row.committee_type && !['unknown', 'subcommittee'].includes(row.committee_type)) return label(row.committee_type);
  const subcommittee = row.committee_level === 'subcommittee' || row.committee_type === 'subcommittee' || parentCommitteeId(row);
  const inherited = [...new Set(row.committee_types || [])].filter((type): type is string => typeof type === 'string' && !['unknown', 'subcommittee'].includes(type));
  return subcommittee && inherited.length ? `${inherited.map(label).join(', ')} (inherited from parent)` : 'Type unrecorded';
}

function phase(row: DisplayRow, now: Date): Phase | undefined {
  const time = scheduledInstant(row);
  if (time !== undefined) return time > now.getTime() ? 'upcoming' : 'past';
  const date = row.scheduled_at?.slice(0, 10) || row.date;
  if (!date) return undefined;
  const today = easternDate(now);
  return date > today ? 'upcoming' : date < today ? 'past' : 'today';
}

function recordingExpected(row: DisplayRow, when: Phase | undefined): boolean {
  return !['canceled', 'postponed', 'not_held'].includes(row.meeting_status || row.source_status || row.status || '')
    && !['upcoming', 'today'].includes(when || '');
}

export function recordingDue(row: DisplayRow, now = new Date()): boolean {
  return recordingExpected(row, phase(row, now));
}

export function recordingVisible(row: DisplayRow, now?: Date): boolean {
  if (row.type !== 'recording') return true;
  return Boolean(row.recording_url) && recordingDue(row, now || new Date());
}

export function presentRecord<T extends DisplayRow>(row: T, now = new Date()): T {
  if (row.kind === 'meeting') {
    const sourceStatus = row.source_status || row.status;
    const when = phase(row, now);
    const status = ['scheduled', 'rescheduled', 'unknown', null, undefined].includes(sourceStatus) ? when || sourceStatus : sourceStatus;
    const evidence: Partial<Record<CoverageAspect, EvidenceState>> = { ...row.evidence_states };
    if (!recordingExpected(row, when)) {
      evidence.recording = 'not_applicable';
      evidence.captions = 'not_applicable';
    }
    return { ...row, source_status: sourceStatus, status, evidence_states: evidence };
  }
  if (row.type === 'recording' && !recordingVisible(row, now)) return { ...row, files: [], recording_url: null };
  return row;
}

export function nextScheduleChange(rows: readonly DisplayRow[], now: Date): number {
  let until = Infinity;
  const current = now.getTime();
  for (const row of rows) {
    const time = scheduledInstant(row);
    if (time !== undefined && time > current && time < until) until = time;
  }
  return until;
}
