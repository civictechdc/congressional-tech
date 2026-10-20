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

/** The recorded calendar day, plus a clock time and its source offset when one was stored. */
export function recordedWhen(row: { date?: string | null; scheduled_at?: string | null }): { date: string; time: string } {
  const scheduled = row.scheduled_at || '';
  const scheduledDay = /^\d{4}-\d{2}-\d{2}/.test(scheduled) ? scheduled.slice(0, 10) : '';
  const date = (row.date || '').slice(0, 10) || scheduledDay;
  const sameDay = Boolean(scheduledDay) && date === scheduledDay;
  const clock = sameDay && scheduled.includes('T') ? scheduled.slice(11, 16) : '';
  const zone = sameDay ? scheduled.match(/(?:Z|[+-]\d{2}:\d{2})$/)?.[0] || '' : '';
  const time = /^\d{2}:\d{2}$/.test(clock) && clock !== '00:00' ? `${clock}${zone === 'Z' ? ' UTC' : zone ? ` ${zone}` : ''}` : '';
  return { date, time };
}

/** A scheduled instant that is not already the record’s own date. */
export function scheduleNote(row: { date?: string | null; scheduled_at?: string | null }): string {
  const scheduled = row.scheduled_at || '';
  if (!/^\d{4}-\d{2}-\d{2}T/.test(scheduled)) return '';
  const date = (row.date || '').slice(0, 10);
  if (date && date === scheduled.slice(0, 10)) return '';
  const when = recordedWhen({ scheduled_at: scheduled });
  return `Scheduled ${[when.date, when.time].filter(Boolean).join(' ')}`;
}

function parsed(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  if (!text.startsWith('{') && !text.startsWith('[')) return value;
  try { return JSON.parse(text) as unknown; } catch { return value; }
}

function addressLine(location: unknown): string {
  const record = parsed(location);
  if (typeof record === 'string') return record.trim();
  if (!record || typeof record !== 'object' || Array.isArray(record)) return '';
  const address = parsed((record as { address?: unknown }).address ?? record);
  if (typeof address === 'string') return address.trim();
  if (!address || typeof address !== 'object' || Array.isArray(address)) return '';
  const place = address as Record<string, unknown>;
  return ['building_name', 'building', 'room', 'street-address', 'street_address', 'city', 'state', 'region', 'postal_code']
    .map(key => typeof place[key] === 'string' ? place[key].trim() : '').filter(Boolean).join(', ');
}

function identifierLine(value: unknown): string {
  const record = parsed(value);
  if (typeof record === 'string') return record.trim();
  if (!record || typeof record !== 'object' || Array.isArray(record)) return '';
  const identifier = record as { scheme?: unknown; value?: unknown };
  return [identifier.scheme, identifier.value].filter((item): item is string => typeof item === 'string' && item.trim() !== '').join(' · ');
}

/** The source's own meeting type, when it names a different kind than the normalized type. */
export function sourceTypeNote(row: { type?: string | null; facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  const source = (row.facts || []).find(fact => fact.label === 'Source type')?.value?.trim() || '';
  if (!source || !row.type || row.type === 'unknown') return '';
  const kind = source.toLowerCase().replaceAll(/\b(open|closed|joint)\b/g, ' ').replaceAll(/\bsession\b/g, ' ').replaceAll(/\s+/g, ' ').trim();
  const displayed = row.type === 'business' ? 'business meeting' : row.type.replaceAll('_', ' ');
  if (!kind || kind === displayed) return '';
  return `Source type ${source}`;
}

/** The recorded place, preferring the full address over the separate building and city. */
export function recordedPlace(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  const facts = row.facts || [];
  const value = (label: string) => facts.find(fact => fact.label?.toLowerCase() === label)?.value?.trim() || '';
  const place = value('place') || value('label') || [value('building'), value('city'), value('region')].filter(Boolean).join(', ');
  const room = value('room');
  if (!room || place.toLowerCase().includes(room.toLowerCase())) return place;
  return place ? `${place}, room ${room}` : `Room ${room}`;
}

const measureLabels = ['Related bill', 'Related resolution', 'Related treaty', 'Related nomination'];

/** An amendment or vote identifier the document title does not already state. */
export function recordedAction(row: { title?: string | null; facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  const facts = row.facts || [];
  const title = (row.title || '').toLowerCase();
  const values = (label: string) => {
    const seen = new Set<string>();
    const found: string[] = [];
    for (const fact of facts) {
      const value = fact.label === label ? fact.value?.trim() || '' : '';
      const key = value.toLowerCase();
      if (!value || title.includes(key) || seen.has(key)) continue;
      seen.add(key);
      found.push(value);
    }
    return found;
  };
  const parts: string[] = [];
  const amendments = values('Amendment number');
  const votes = values('Vote number');
  if (amendments.length) parts.push(...amendments.map(value => `Amendment ${value}`));
  else if (votes.length) parts.push(...votes.map(value => `Vote ${value}`));
  parts.push(...values('Regarding'));
  parts.push(...values('Sponsor'));
  parts.push(...values('Sponsor Bioguide ID'));
  parts.push(...values('En bloc group').map(value => `En bloc ${value}`));
  parts.push(...values('Vote question'));
  parts.push(...values('Amendment description'));
  return parts.join(' · ');
}

/** Witness display names stored after the meeting title. Names stay in recorded order. */
export function recordedWitnesses(row: { title?: string | null; search_text?: string | null }): string {
  const title = row.title?.trim() || '';
  const text = row.search_text?.trim() || '';
  if (!title || !text.startsWith(title)) return '';
  return text.slice(title.length).trim();
}

/** Put the recorded witness names back into separate names when each name is known. */
export function separateWitnesses(recorded: string, names: readonly string[]): string {
  let cursor = recorded.trim();
  if (!cursor) return '';
  const known = [...new Set(names.map(name => name.trim()).filter(Boolean))].sort((left, right) => right.length - left.length);
  if (!known.length) return cursor;
  const found: string[] = [];
  while (cursor) {
    const match = known.find(name => cursor === name || cursor.startsWith(`${name} `));
    if (!match) return recorded.trim();
    found.push(match);
    cursor = cursor.slice(match.length).trim();
  }
  return found.join(' · ');
}

/** Witness names in recorded order, including people listed on the meeting who are absent from the search text. */
export function witnessNameList(recorded: string, names: readonly string[]): string[] {
  const known = [...new Set(names.map(name => name.trim()).filter(Boolean))];
  const text = recorded.trim();
  if (!known.length) return text ? [text] : [];
  const separated = separateWitnesses(text, known);
  const aligned = separated.includes(' · ') || known.some(name => name === separated);
  if (!aligned) return known;
  const listed = separated.includes(' · ') ? separated.split(' · ') : separated ? [separated] : [];
  for (const name of known) {
    const key = name.toLowerCase();
    if (listed.some(item => { const text = item.toLowerCase(); return text === key || text.startsWith(`${key} `); })) continue;
    listed.push(name);
  }
  return listed;
}

/** A file publication date that is not the record’s own date. */
export function publishedNote(row: { date?: string | null; files?: readonly { published_at?: string | null }[] | null }): string {
  const recorded = (row.date || '').slice(0, 10);
  const dates = [...new Set((row.files || []).map(file => (file.published_at || '').slice(0, 10)).filter(date => date && date !== recorded))];
  if (!dates.length) return '';
  return `Published ${dates.join(' · ')}`;
}

/** Every bill, resolution, treaty, and nomination recorded for a meeting. */
export function recordedMeasureValues(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const fact of row.facts || []) {
    const value = fact.value?.trim() || '';
    if (!value || !measureLabels.includes(fact.label || '') || seen.has(value)) continue;
    seen.add(value);
    values.push(value);
  }
  return values;
}

/** Bills, resolutions, treaties, and nominations recorded for a meeting. */
export function recordedMeasures(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  const values = recordedMeasureValues(row);
  const shown = values.slice(0, 4);
  const rest = values.length - shown.length;
  return rest ? `${shown.join(' · ')} and ${rest} more` : shown.join(' · ');
}

const evidenceAspects = [['recording', 'Recording'], ['transcript', 'Transcript'], ['documents', 'Documents'], ['witnesses', 'Witness list'], ['captions', 'Captions']] as const;
const evidenceStateWords: Record<string, string> = { not_found_in_checked_scope: 'not found', error: 'check failed', blocked: 'check blocked', not_applicable: 'not applicable' };

/** The recorded evidence state for each meeting aspect. */
export function evidenceParts(states: { [key: string]: string | null | undefined } | null | undefined): string[] {
  if (!states) return [];
  return evidenceAspects.flatMap(([key, label]) => {
    const state = states[key];
    if (!state) return [];
    const word = evidenceStateWords[state] || state.replaceAll('_', ' ');
    return [`${label} ${word}`];
  });
}

/** The recorded evidence state for each meeting aspect, in one line. */
export function evidenceLine(states: { [key: string]: string | null | undefined } | null | undefined): string {
  return evidenceParts(states).join(' · ');
}

/** A location's recorded "label" is the place, when the same record also names a building or city. */
export function factLabel(label: string, siblingLabels: readonly string[]): string {
  const names = siblingLabels.map(item => item.toLowerCase());
  if (label.toLowerCase() === 'label' && names.some(item => item === 'building' || item === 'city')) return 'Place';
  return label;
}

/** Recorded roll-call or voice-vote results, in the order they were stored. */
export function recordedVotes(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  return (row.facts || []).flatMap(fact => /^vote \d+$/i.test(fact.label || '') && fact.value?.trim() ? [fact.value.trim()] : []);
}

/** Recorded amendment outcomes, in the order they were stored. */
export function recordedAmendments(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  return (row.facts || []).flatMap(fact => {
    const label = fact.label || '';
    const value = fact.value?.trim() || '';
    if (!/^amendment( \d+)?$/i.test(label) || !value) return [];
    return [value.toLowerCase().includes(label.toLowerCase()) ? value : `${label}: ${value}`];
  });
}

/** The official site recorded for a committee term. */
export function committeeWebsite(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  return (row.facts || []).find(fact => fact.label === 'Official website or archive')?.value?.trim() || '';
}

/** Meetings recorded on a witness or document. A list of ids wins over the single id. */
export function linkedMeetingIds(row: { meeting_id?: string | null; meeting_ids?: readonly string[] | null }): string[] {
  const listed = (row.meeting_ids || []).map(id => id.trim()).filter(Boolean);
  const ids = listed.length ? listed : row.meeting_id ? [row.meeting_id] : [];
  return [...new Set(ids)];
}

const locationParts = new Set(['building', 'city', 'region', 'room']);

/** Drop a place part when the full address already includes it. */
export function distinctRecordedFacts(facts: readonly { label?: string | null; value?: string | null }[] | null | undefined): [string, string][] {
  const rows = (facts || []).flatMap(fact => {
    const label = fact.label?.trim() || '';
    const value = fact.value?.trim() || '';
    return label && value ? [[label, value] as [string, string]] : [];
  });
  const place = (rows.find(([label]) => ['label', 'place'].includes(label.toLowerCase()))?.[1] || '').toLowerCase();
  let absorbed = false;
  const kept = rows.filter(([label, value]) => {
    const part = place && locationParts.has(label.toLowerCase()) && place.includes(value.toLowerCase());
    if (part) absorbed = true;
    return !part;
  });
  const shown = absorbed ? kept.map(([label, value]) => [label.toLowerCase() === 'label' ? 'Place' : label, value] as [string, string]) : kept;
  return shown.map(([label, value]) => {
    if (label.toLowerCase() === 'field path') {
      const field = value.split('/').filter(Boolean).map(part => phrase(part) || part).join(' / ');
      return ['Compared field', field || value];
    }
    if (label.toLowerCase() === 'detected at') return ['Detected', recordedInstant(value)];
    return [label, value];
  });
}

/** A stored instant without the fractional seconds. Offsets are converted to UTC. */
export function recordedInstant(value: string): string {
  const trimmed = value.trim();
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.exec(trimmed);
  if (!match) return value;
  const offset = match[3];
  if (!offset || offset === 'Z' || offset === '+00:00' || offset === '-00:00') return `${match[1]} ${match[2]} UTC`;
  const parsed = Date.parse(trimmed);
  if (Number.isNaN(parsed)) return value;
  const utc = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/.exec(new Date(parsed).toISOString());
  return utc ? `${utc[1]} ${utc[2]} UTC` : value;
}

/** One row per label, with every distinct value kept. */
export function collapseRepeatedFacts(facts: readonly (readonly [unknown, unknown])[]): [string, string][] {
  const grouped: [string, string[]][] = [];
  for (const [label, value] of facts) {
    const name = String(label);
    const text = String(value);
    const existing = grouped.find(item => item[0] === name);
    if (!existing) grouped.push([name, [text]]);
    else if (!existing[1].includes(text)) existing[1].push(text);
  }
  return grouped.map(([name, values]) => [name, values.join('\n')]);
}

const sourceEnvelope = [['provider', 'Provider'], ['retrieved_at', 'Retrieved'], ['imported_at', 'Imported'], ['source_modified_at', 'Source modified'], ['input_snapshot_id', 'Input snapshot'], ['retained_uri', 'Retained copy'], ['retained_sha256', 'Retained SHA-256']] as const;
const sourceLinkGroups = [['meetingDocuments', 'Meeting document'], ['witnessDocuments', 'Witness document'], ['videos', 'Video']] as const;

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : typeof value === 'number' ? String(value) : '';
}

function objectRow(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function rowsOf(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.flatMap(item => { const row = objectRow(item); return row ? [row] : []; }) : [];
}

function payloadOf(value: object): Record<string, unknown> | null {
  return objectRow((value as { payload?: unknown }).payload);
}

/** A source document that names what it is but has no file address. */
function unlinkedDocumentNotes(value: unknown): string[] {
  const notes: string[] = [];
  for (const item of rowsOf(value)) {
    if (/^https?:\/\//i.test(text(item.url))) continue;
    const description = text(item.description) || text(item.name);
    if (!description) continue;
    const kind = text(item.documentType);
    const line = kind && !description.toLowerCase().includes(kind.toLowerCase()) ? `${kind}: ${description}` : description;
    if (!notes.includes(line)) notes.push(line);
  }
  return notes;
}

function relatedLines(value: unknown): string {
  const record = objectRow(value);
  if (!record) return '';
  const lines: string[] = [];
  for (const [family, items] of Object.entries(record)) {
    for (const item of rowsOf(items)) {
      const part = text(item.part);
      const designation = [text(item.type), text(item.number), part && part !== '00' ? `part ${part}` : ''].filter(Boolean).join(' ');
      const congress = congressName(item.congress);
      const line = [family.replaceAll('_', ' '), designation, congress].filter(Boolean).join(' · ');
      if (line) lines.push(line);
    }
  }
  return lines.join('\n');
}

/** Envelope fields and the recorded place, witnesses, and related items from a source observation. */
export function sourceFacts(value: object): [string, string][] {
  const row = value as Record<string, unknown>;
  const facts: [string, string][] = [];
  for (const [key, label] of sourceEnvelope) if (typeof row[key] === 'string' && row[key].trim()) facts.push([label, ['Retrieved', 'Imported', 'Source modified'].includes(label) ? recordedInstant(row[key].trim()) : row[key].trim()]);
  const identifier = identifierLine(row.identifier);
  if (identifier) facts.push(['Identifier', identifier]);
  const payload = payloadOf(value);
  if (!payload) return facts;
  const place = addressLine(payload.location);
  if (place) facts.push(['Place', place]);
  for (const [key, label] of [['meetingStatus', 'Source status'], ['type', 'Source type'], ['eventId', 'Event ID'], ['updateDate', 'Source updated']] as const) {
    const recorded = key === 'updateDate' ? recordedInstant(text(payload[key])) : text(payload[key]);
    if (recorded) facts.push([label, recorded]);
  }
  const committees = rowsOf(payload.committees).map(item => [text(item.name), text(item.systemCode)].filter(Boolean).join(' · ')).filter(Boolean);
  if (committees.length) facts.push(['Source committees', committees.join('\n')]);
  const witnesses = [...rowsOf(payload.witnesses), ...rowsOf(payload.people)].map(witnessLine).filter(Boolean);
  if (witnesses.length) facts.push(['Source witnesses', [...new Set(witnesses)].join('\n')]);
  if (payload.absent === true) facts.push(['Listing', 'Recorded as absent']);
  const related = relatedLines(payload.relatedItems);
  if (related) facts.push(['Related items', related]);
  const transcripts = rowsOf(payload.hearingTranscript).map(item => text(item.jacketNumber)).filter(Boolean).map(jacket => `Jacket ${jacket}`);
  if (transcripts.length) facts.push(['Hearing transcript', transcripts.join('\n')]);
  const sittings = [...new Set([...rowsOf(payload.continuations).map(item => text(item.continuationDate)).filter(Boolean), ...extraHearingDates(payload)])];
  if (sittings.length) facts.push(['Additional sitting', sittings.join('\n')]);
  const documents = [...unlinkedDocumentNotes(payload.meetingDocuments), ...unlinkedDocumentNotes(payload.witnessDocuments)];
  if (documents.length) facts.push(['Recorded document', documents.join('\n')]);
  facts.push(...payloadIdentity(payload));
  facts.push(...committeeDetail(payload));
  facts.push(...decisionFacts(payload));
  facts.push(...reviewFacts(payload));
  return mergeFacts(facts);
}

function mergeFacts(facts: [string, string][]): [string, string][] {
  const merged: [string, string][] = [];
  for (const [label, value] of facts) {
    const existing = merged.find(item => item[0] === label);
    const lines = value.split('\n');
    if (!existing) { merged.push([label, value]); continue; }
    const seen = new Set(existing[1].split('\n'));
    const extra = lines.filter(line => !seen.has(line));
    if (extra.length) existing[1] = `${existing[1]}\n${extra.join('\n')}`;
  }
  return merged;
}

function witnessLine(item: Record<string, unknown>): string {
  const honorific = text(item.honorific);
  const recorded = text(item.name);
  const built = [text(item.first), text(item.middle), text(item.last), text(item.suffix)].filter(Boolean).join(' ');
  const name = recorded || built;
  const titled = honorific && !name.toLowerCase().startsWith(honorific.toLowerCase()) ? `${honorific} ${name}` : name;
  const organization = text(item.organization);
  const covered = `${name} ${organization}`.toLowerCase();
  const location = text(item.location);
  const behalf = text(item.behalf_of);
  const page = text(item.page);
  const bioguide = text(item.bioguide_id);
  return [titled, text(item.position), organization, location && !covered.includes(location.toLowerCase()) ? location : '', behalf && !covered.includes(behalf.toLowerCase()) ? `On behalf of ${behalf}` : '', text(item.witness_type), text(item.panel) ? `Panel ${text(item.panel)}` : '', page && !/^https?:\/\//i.test(page) ? `Page ${page}` : '', testifiedNote(text(item.testified)), bioguide ? `Bioguide ${bioguide}` : ''].filter(Boolean).join(' · ');
}

/** Hearing days recorded besides the held date. */
function extraHearingDates(payload: Record<string, unknown>): string[] {
  const held = text(payload.held_date).slice(0, 10);
  return [...new Set(text(payload.hearing_dates).split(/[;,]/).map(part => part.trim().slice(0, 10)).filter(day => /^\d{4}-\d{2}-\d{2}$/.test(day) && day !== held))];
}

function witnessListNote(value: string): string {
  if (value === 'present') return 'Recorded';
  if (value === 'absent') return 'Not recorded';
  if (value === 'unfetched') return 'Not retrieved';
  return value;
}

function captionKindNote(value: string): string {
  if (value === 'auto') return 'Automatic';
  if (value === 'manual') return 'Manual';
  if (value === 'webvtt') return 'WebVTT';
  if (value === 'none') return 'None recorded';
  return '';
}

function testifiedNote(value: string): string {
  if (!value) return '';
  if (/^yes$/i.test(value)) return 'Testified';
  if (/^no$/i.test(value)) return 'Did not testify';
  return value;
}

function clockDuration(value: unknown): string {
  const seconds = typeof value === 'number' ? value : typeof value === 'string' && /^\d+$/.test(value.trim()) ? Number(value.trim()) : Number.NaN;
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}` : `${minutes}:${String(secs).padStart(2, '0')}`;
}

const videoMatchStatus: Record<string, string> = {
  full_recording: 'Full recording',
  full_recording_offsite: 'Full recording outside the tracked channel',
  before_channel: 'Before the committee channel',
  clips_only: 'Clips only',
  no_video_found: 'No video found',
  committee_not_tracked: 'Committee not tracked',
  not_public: 'Not public',
};

/** Identity fields from YouTube, GovInfo, House, and Senate payloads. */
function payloadIdentity(payload: Record<string, unknown>): [string, string][] {
  const facts: [string, string][] = [];
  const push = (label: string, value: unknown) => {
    const recorded = text(value);
    if (recorded) facts.push([label, recorded]);
  };
  const title = text(payload.title);
  const description = text(payload.description);
  push('Recorded title', payload.title);
  push('Video ID', payload.videoId);
  const duration = clockDuration(payload.duration);
  if (duration) facts.push(['Duration', duration]);
  if (typeof payload.caption === 'boolean') facts.push(['Captions', payload.caption ? 'Recorded' : 'Not recorded']);
  if (description && description.toLowerCase() !== title.toLowerCase()) facts.push(['Description', description]);
  push('Published', recordedInstant(text(payload.publishedAt)));
  push('Package', payload.package_id);
  push('Committee', payload.committee_name);
  push('Committee code', payload.committee_code);
  push('Subcommittee', payload.subcommittees);
  push('Held', payload.held_date);
  push('Serial', payload.serial);
  const witnesses = text(payload.witness_count);
  if (witnesses && witnesses !== '0') facts.push(['Witnesses in package', witnesses]);
  const congress = congressName(payload.congress);
  if (congress) facts.push(['Congress', congress]);
  const chamber = text(payload.chamber);
  if (chamber) facts.push(['Chamber', phrase(chamber) || chamber]);
  const status = text(payload.status);
  if (videoMatchStatus[status]) facts.push(['Video match', videoMatchStatus[status]]);
  const witnessList = witnessListNote(text(payload.witness_status));
  if (witnessList) facts.push(['Witness list', witnessList]);
  const captionKind = captionKindNote(text(payload.kind));
  if (captionKind && typeof payload.caption !== 'boolean') facts.push(['Captions', captionKind]);
  push('Checked', recordedInstant(text(payload.checked) || text(payload.details_checked_at)));
  push('Version', recordedInstant(text(payload.version)));
  push('XML updated', recordedInstant(text(payload.xml_update)));
  const events = Array.isArray(payload.events) ? payload.events.map(text).filter(Boolean) : [];
  if (events.length) facts.push(['Event ID', events.join('\n')]);
  if (!text(payload.eventId)) push('Event ID', payload.event_id);
  const witness = [text(payload.name), text(payload.position), text(payload.organization)].filter(Boolean).join(' · ');
  if (witness && !rowsOf(payload.witnesses).length) facts.push(['Witness', witness]);
  push('From package', payload.from);
  push('Channel', payload.channelTitle);
  push('Citation', payload.preferred_citation);
  const length = minuteLength(text(payload.video_minutes));
  if (length) facts.push(['Video length', length]);
  push('Matched channels', payload.channels);
  const recordType = text(payload.record_type);
  if (recordType && recordType.toLowerCase() !== 'hearing') facts.push(['Record type', recordType]);
  push('Package updated', recordedInstant(text(payload.last_modified)));
  const ingested = text(payload.date_ingested).slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(ingested)) facts.push(['Ingested', ingested]);
  if (payload.available === false) facts.push(['Availability', 'Not available']);
  const note = text(payload.note);
  if (note) facts.push([videoMatchStatus[text(payload.status)] || text(payload.video_minutes) || text(payload.channels) ? 'Match note' : 'Note', note]);
  return facts;
}

function committeeDetail(payload: Record<string, unknown>): [string, string][] {
  const committee = objectRow(payload.committee);
  const detail = objectRow(payload.detail);
  if (!committee && !detail) return [];
  const facts: [string, string][] = [];
  const name = text(committee?.name);
  if (name) facts.push(['Committee', name]);
  const type = text(detail?.type) || text(committee?.committeeTypeCode);
  if (type) facts.push(['Committee type', type]);
  const chamber = text(committee?.chamber);
  if (chamber) facts.push(['Chamber', phrase(chamber) || chamber]);
  if (typeof detail?.isCurrent === 'boolean') facts.push(['Committee status', detail.isCurrent ? 'Current' : 'Former']);
  const subcommittees = rowsOf(detail?.subcommittees || committee?.subcommittees).map(item => text(item.name)).filter(Boolean);
  if (subcommittees.length) facts.push(['Subcommittees', [...new Set(subcommittees)].join('\n')]);
  const history = rowsOf(detail?.history).map(historyLine).filter(Boolean);
  if (history.length) facts.push(['Name history', [...new Set(history)].join('\n')]);
  return facts;
}

function historyLine(item: Record<string, unknown>): string {
  const name = text(item.officialName) || text(item.libraryOfCongressName);
  if (!name) return '';
  const start = text(item.startDate).slice(0, 10);
  const end = text(item.endDate).slice(0, 10);
  const span = start && end ? `${start} to ${end}` : start ? `From ${start}` : end ? `Through ${end}` : '';
  return [name, span, text(item.establishingAuthority)].filter(Boolean).join(' · ');
}

function decisionFacts(payload: Record<string, unknown>): [string, string][] {
  const explanation = text(payload.explanation);
  const decided = text(payload.decided_at).slice(0, 10);
  const status = text(payload.status);
  if (!explanation || !/^\d{4}-\d{2}-\d{2}$/.test(decided) || !status || videoMatchStatus[status]) return [];
  return [['Decision', phrase(status) || status], ['Decided', decided], ['Explanation', explanation]];
}

function reviewFacts(payload: Record<string, unknown>): [string, string][] {
  const values = objectRow(payload.values);
  const facts: [string, string][] = [];
  const name = text(values?.name);
  if (name) facts.push(['Committee', name]);
  const type = text(values?.committee_type);
  if (type) facts.push(['Committee type', phrase(type) || type]);
  const explanation = text(payload.explanation);
  const decided = text(payload.decided_at).slice(0, 10);
  const status = text(payload.status);
  if (explanation && !(/^\d{4}-\d{2}-\d{2}$/.test(decided) && status && !videoMatchStatus[status])) facts.push(['Explanation', explanation]);
  const found = text(payload.found_by);
  if (found) facts.push(['Found', phrase(found) || found]);
  const first = congressName(payload.first_congress);
  if (first) facts.push(['First Congress', first]);
  const last = congressName(payload.last_congress);
  if (last) facts.push(['Last Congress', last]);
  const terminated = text(payload.terminated).slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(terminated)) facts.push(['Terminated', terminated]);
  const added = Array.isArray(payload.add_congresses) ? payload.add_congresses.map(congressName).filter(Boolean) : [];
  if (added.length) facts.push(['Also recorded', added.join('\n')]);
  const documentType = text(payload.source_document_type);
  if (documentType) facts.push(['Document type', documentType]);
  const category = text(payload.category);
  if (category) facts.push(['Document category', phrase(category) || category]);
  return facts;
}

export function congressName(value: unknown): string {
  const raw = typeof value === 'number' && Number.isInteger(value) ? String(value) : text(value);
  if (!/^\d+$/.test(raw)) return '';
  const congress = Number(raw);
  const mod100 = congress % 100;
  const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[congress % 10] || 'th';
  return `${congress}${suffix} Congress`;
}

function minuteLength(value: string): string {
  if (!/^\d+$/.test(value)) return '';
  const total = Number(value);
  if (!total) return '';
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (!hours) return `${total} min`;
  return minutes ? `${hours} hr ${minutes} min` : `${hours} hr`;
}

export interface SourceLink { group: string; label: string; href: string }

/** Documents and videos the source recorded with an http(s) URL. */
export function sourceLinks(value: object): { links: SourceLink[] } {
  const payload = payloadOf(value);
  if (!payload) return { links: [] };
  const links: SourceLink[] = [];
  const sourceHref = sourcePageUrl((value as { url?: unknown }).url);
  for (const [key, group] of sourceLinkGroups) {
    for (const item of rowsOf(payload[key])) {
      const href = text(item.url);
      if (!/^https?:\/\//i.test(href)) continue;
      if (group === 'Video' && sameRecordedPage(href, sourceHref)) continue;
      const recordedGroup = group === 'Video' && congressEventPage(href) ? 'Event page' : group;
      const named = text(item.name) || text(item.title) || text(item.documentType) || (recordedGroup === 'Video' ? 'Recording' : 'Document');
      const filename = linkFilename(href);
      links.push({ group: recordedGroup, href, label: filename && filename !== named ? `${named} · ${filename}` : named });
    }
  }
  for (const [key, group] of [['html_url', 'Printed hearing'], ['pdf_url', 'Printed hearing']] as const) {
    const href = text(payload[key]);
    if (/^https?:\/\//i.test(href)) links.push({ group, href, label: linkFilename(href) || group });
  }
  links.push(...tupleLinks(payload.documents, 'Document'));
  for (const item of rowsOf(payload.amendments)) {
    const href = text(item.url);
    if (!/^https?:\/\//i.test(href)) continue;
    const sponsor = text(item.sponsor_bioguide);
    const existing = links.find(link => link.href === href);
    if (existing) {
      if (sponsor && !existing.label.includes(`Sponsor ${sponsor}`)) existing.label = `${existing.label} · Sponsor ${sponsor}`;
      continue;
    }
    const named = [text(item.bill), text(item.number) ? `Amendment ${text(item.number)}` : '', text(item.description), sponsor ? `Sponsor ${sponsor}` : ''].filter(Boolean).join(' · ') || 'Amendment';
    const filename = linkFilename(href);
    links.push({ group: 'Amendment', href, label: filename && !named.includes(filename) ? `${named} · ${filename}` : named });
  }
  for (const token of text(payload.video_ids).split(/\s+/).filter(Boolean)) {
    if (/^https?:\/\//i.test(token)) links.push({ group: 'Matched video', href: token, label: linkFilename(token) || linkLocator(token) || 'Matched video' });
    else if (/^[A-Za-z0-9_-]{11}$/.test(token)) links.push({ group: 'Matched video', href: `https://www.youtube.com/watch?v=${token}`, label: token });
  }
  const channelId = text(payload.channelId);
  if (/^UC[\w-]{20,}$/.test(channelId)) links.push({ group: 'Channel', href: `https://www.youtube.com/channel/${channelId}`, label: text(payload.channelTitle) || channelId });
  const website = text(objectRow(payload.detail)?.committeeWebsiteUrl) || text(objectRow(payload.values)?.website);
  if (/^https?:\/\//i.test(website)) links.push({ group: 'Committee website', href: website, label: siteLabel(website) });
  const recording = text(payload.recording) || text(payload.recording_id);
  const recordingHref = /^https?:\/\//i.test(recording) ? recording : /^[A-Za-z0-9_-]{11}$/.test(recording) ? `https://www.youtube.com/watch?v=${recording}` : '';
  if (recordingHref && !links.some(link => link.href === recordingHref)) links.push({ group: 'Recording', href: recordingHref, label: /^https?:\/\//i.test(recording) ? linkFilename(recording) || linkLocator(recording) || 'Recording' : recording });
  for (const href of recordedUrls(payload.urls).concat(recordedUrls(payload.source_urls))) {
    if (links.some(link => link.href === href)) continue;
    const filename = linkFilename(href) || linkLocator(href);
    links.push({ group: href.includes('/isvp') ? 'Recording' : filename.endsWith('.xml') ? 'Meeting record' : 'Source', href, label: filename || siteLabel(href) });
  }
  const cited = objectRow(payload.cited_evidence);
  const citedHref = text(cited?.url);
  if (/^https?:\/\//i.test(citedHref) && !links.some(link => link.href === citedHref)) links.push({ group: 'Cited evidence', href: citedHref, label: text(cited?.description) || siteLabel(citedHref) });
  for (const item of rowsOf(payload.witnesses)) {
    const href = text(item.page);
    if (!/^https?:\/\//i.test(href)) continue;
    links.push({ group: 'Witness page', href, label: text(item.name) || 'Witness page' });
  }
  const counts = new Map<string, number>();
  for (const link of links) counts.set(`${link.group}\0${link.label}`, (counts.get(`${link.group}\0${link.label}`) || 0) + 1);
  for (const link of links) {
    if ((counts.get(`${link.group}\0${link.label}`) || 0) < 2) continue;
    const locator = linkLocator(link.href);
    if (locator && !link.label.includes(locator)) link.label = `${link.label} · ${locator}`;
  }
  return { links };
}

function sameRecordedPage(left: string | undefined, right: string | undefined): boolean {
  if (!left || !right) return false;
  try {
    const a = new URL(left);
    const b = new URL(right);
    return a.host === b.host && a.pathname.replace(/\/$/, '').toLowerCase() === b.pathname.replace(/\/$/, '').toLowerCase() && a.search === b.search;
  } catch {
    return false;
  }
}

function congressEventPage(href: string): boolean {
  try {
    const url = new URL(href);
    return /(^|\.)congress\.gov$/i.test(url.hostname) && /^\/event\/\d+(?:st|nd|rd|th)-congress\/(?:house|senate)-event\/\d+\/?$/i.test(url.pathname);
  } catch {
    return false;
  }
}

function tupleLinks(value: unknown, fallback: string): SourceLink[] {
  if (!Array.isArray(value)) return [];
  const links: SourceLink[] = [];
  for (const item of value) {
    if (!Array.isArray(item)) continue;
    const parts = item.map(part => text(part));
    const href = parts.find(part => /^https?:\/\//i.test(part));
    if (!href) continue;
    const group = parts.find(part => part && part !== href) || fallback;
    const named = parts.filter(part => part && part !== href && part !== group).join(' · ') || group;
    const filename = linkFilename(href);
    links.push({ group: group.charAt(0).toUpperCase() + group.slice(1), href, label: filename && !named.includes(filename) ? `${named} · ${filename}` : named });
  }
  return links;
}

function siteLabel(href: string): string {
  try {
    const url = new URL(href);
    const path = url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '');
    return `${url.host}${path}`;
  } catch {
    return href;
  }
}

function recordedUrls(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(item => text(item)).filter(href => /^https?:\/\//i.test(href));
}

function linkFilename(href: string): string {
  try {
    const base = decodeURIComponent(new URL(href).pathname.split('/').pop() || '');
    return base.includes('.') ? base : '';
  } catch {
    return '';
  }
}

/** A short recorded token that separates two links with the same name. */
function linkLocator(href: string): string {
  try {
    const url = new URL(href);
    const token = url.searchParams.get('v') || url.searchParams.get('filename');
    if (token) return token;
    const segment = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '');
    return segment.includes('.') ? '' : segment;
  } catch {
    return '';
  }
}

function jsonRecord(value: string): unknown {
  const text = value.trim();
  if (!text.startsWith('{') && !text.startsWith('[')) return undefined;
  try { return JSON.parse(text) as unknown; } catch { return undefined; }
}

function recordLeaves(value: unknown, prefix = ''): Map<string, string> {
  const leaves = new Map<string, string>();
  if (Array.isArray(value)) {
    leaves.set(prefix || 'value', value.length ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item ?? 'none')).join(', ') : 'none');
    return leaves;
  }
  if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      const path = [prefix, key.replaceAll('_', ' ')].filter(Boolean).join(' · ');
      if (item && typeof item === 'object') {
        for (const [child, childValue] of recordLeaves(item, path)) leaves.set(child, childValue);
      } else leaves.set(path, item == null || item === '' ? 'none' : String(item));
    }
    return leaves;
  }
  leaves.set(prefix || 'value', value == null || value === '' ? 'none' : String(value));
  return leaves;
}

function readablePath(path: string): string {
  return path.split(' · ').map(part => part.toLowerCase() === 'id' ? 'ID' : phrase(part) || part).join(' ');
}

function readableValue(value: string): string {
  if (value === 'none') return 'nothing recorded';
  if (value === 'unknown') return 'Unknown';
  if (/^[0-9a-f-]{32,}$/i.test(value)) return value;
  return phrase(value) || value;
}

/** A channel kind that only repeats the field name is not a separate difference. */
function collapsedLeaves(changes: readonly string[], base: ReadonlyMap<string, string>, alt: ReadonlyMap<string, string>): { path: string; selected: string; alternative: string }[] {
  const grouped = new Map<string, string[]>();
  for (const path of changes) {
    const parts = path.split(' · ');
    const parent = parts.length > 1 ? parts.slice(0, -1).join(' · ') : '';
    grouped.set(parent, [...(grouped.get(parent) || []), path]);
  }
  const kept: { path: string; selected: string; alternative: string }[] = [];
  for (const [parent, paths] of grouped) {
    const leaf = (name: string) => paths.find(path => path.endsWith(` · ${name}`));
    const kind = leaf('kind');
    const id = leaf('id');
    const parentName = parent.split(' · ').pop()?.toLowerCase() || '';
    const echoes = (path: string | undefined) => path !== undefined && [base.get(path) ?? 'none', alt.get(path) ?? 'none'].every(value => value === 'none' || value.toLowerCase() === parentName);
    if (parent && kind && id && paths.length === 2 && echoes(kind)) {
      kept.push({ path: parent, selected: base.get(id) ?? 'none', alternative: alt.get(id) ?? 'none' });
      continue;
    }
    for (const path of paths) kept.push({ path, selected: base.get(path) ?? 'none', alternative: alt.get(path) ?? 'none' });
  }
  return kept;
}

function identifierDifference(path: string, value: string, where: string): string {
  return value === 'none' ? `Nothing recorded ${where}` : `${readablePath(path)} ${where}\n${value}`;
}

function differenceLine(path: string, selected: string, alternative: string, index: number): string {
  const identifier = /^[0-9a-f-]{32,}$/i.test(selected) || /^[0-9a-f-]{32,}$/i.test(alternative);
  if (identifier) return `${identifierDifference(path, selected, 'on the selected record')}\n${identifierDifference(path, alternative, `on alternative ${index}`)}`;
  return `${readablePath(path)}: ${readableValue(selected)} on the selected record; ${readableValue(alternative)} on alternative ${index}`;
}

/** The fields that differ between a selected JSON value and its recorded alternatives. */
export function disagreementSummary(selected: string, alternatives: readonly string[]): string[] | null {
  const chosen = jsonRecord(selected);
  const others = alternatives.map(jsonRecord);
  if (chosen === undefined || others.some(item => item === undefined)) return null;
  const base = recordLeaves(chosen);
  const lines: string[] = [];
  others.forEach((other, index) => {
    const alt = recordLeaves(other);
    const changes = [...new Set([...base.keys(), ...alt.keys()])].filter(key => (base.get(key) ?? 'none') !== (alt.get(key) ?? 'none'));
    if (!changes.length) lines.push(`Alternative ${index + 1} matches the selected value.`);
    else for (const change of collapsedLeaves(changes, base, alt)) lines.push(differenceLine(change.path, change.selected, change.alternative, index + 1));
  });
  return lines;
}

/** What an issue list row can show from the recorded explanation and compared values. */
/** A subject the explorer cannot open by title: source record, committee, or person. */
export function subjectKindLabel(kind: string | null | undefined): string {
  if (kind === 'source_record') return 'source record';
  if (kind === 'committee') return 'committee';
  if (kind === 'person') return 'person';
  return '';
}

/** A linked record the publication does not contain. */
export function subjectAbsentNote(kind: string | null | undefined): string {
  const names: Record<string, string> = { material: 'document or recording', meeting: 'meeting', appearance: 'witness', committee_term: 'committee' };
  const name = kind ? names[kind] : '';
  return name ? `The ${name} this issue describes is not in this publication.` : '';
}

/** How many source observations a record was built from, when there is more than one. */
export function sourceCountNote(row: { source_ids?: readonly string[] | null }): string {
  const count = row.source_ids?.length || 0;
  if (count < 2) return '';
  return `${count} source records`;
}

/** When the issue was detected, if that day is not already the row date. */
export function detectedNote(row: { date?: string | null; facts?: readonly { label?: string | null; value?: string | null }[] | null }): string {
  const detected = (row.facts || []).find(fact => fact.label === 'detected at')?.value?.trim() || '';
  const day = detected.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return '';
  if ((row.date || '').slice(0, 10) === day) return '';
  return `Detected ${day}`;
}

function plainIssueValues(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const facts = row.facts || [];
  const selected = facts.find(fact => fact.label === 'Selected value')?.value?.trim() || '';
  const alternatives = facts.filter(fact => /^alternative \d+$/i.test(fact.label || '')).map(fact => fact.value || '');
  const plain = (value: string) => Boolean(value) && value.length <= 240 && !value.startsWith('{') && !value.startsWith('[');
  if (!plain(selected) || (alternatives.length && disagreementSummary(selected, alternatives))) return [];
  return alternatives.filter(value => value !== selected && plain(value));
}

/** Plain alternatives after the first one shown on an issue row. */
export function extraIssueAlternatives(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  return plainIssueValues(row).slice(1);
}

export function issueNotes(row: { title?: string | null; explanation?: string | null; facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const facts = row.facts || [];
  const values = (label: string) => facts.filter(fact => fact.label === label).map(fact => fact.value?.trim() || '').filter(Boolean);
  const notes: string[] = [];
  const path = values('field path')[0];
  const field = path ? path.split('/').filter(Boolean).map(part => phrase(part) || part).join(' / ') : '';
  if (field) notes.push(`Compared field: ${field}`);
  const selected = values('Selected value')[0] || '';
  const alternatives = facts.filter(fact => /^alternative \d+$/i.test(fact.label || '')).map(fact => fact.value || '');
  const summary = selected && alternatives.length ? disagreementSummary(selected, alternatives) : null;
  const plain = (value: string) => Boolean(value) && value.length <= 240 && !value.startsWith('{') && !value.startsWith('[');
  if (summary?.length) notes.push(...summary.slice(0, 2));
  else if (plain(selected)) {
    notes.push(selected);
    const first = plainIssueValues(row)[0];
    if (first) notes.push(`Alternative: ${first}`);
  }
  const reason = values('Selection reason')[0];
  if (reason) notes.push(reason);
  const resolution = values('Resolution')[0];
  const explanation = (row.explanation || '').trim();
  if (resolution && resolution !== (row.title || '').trim() && resolution !== explanation) notes.push(resolution);
  if (explanation && explanation !== (row.title || '').trim()) notes.push(explanation);
  return notes;
}

/** Lines of a title that was recorded with line breaks. Blank lines are spacing, not text. */
export function recordedTitleLines(title: string): string[] {
  const lines = title.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  return lines.length ? lines : [title.trim()].filter(Boolean);
}

const titleLineLimit = 3;
const titleLineChars = 240;

/** The title lines a list can show, plus any recorded text past that. */
export function recordedTitlePreview(title: string): { preview: string; rest: string[]; continued: boolean } {
  const lines = recordedTitleLines(title);
  const shown: string[] = [];
  const rest: string[] = [];
  let continued = false;
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (shown.length >= titleLineLimit) { rest.push(line); continue; }
    if (line.length <= titleLineChars) { shown.push(line); continue; }
    const boundary = line.lastIndexOf(' ', titleLineChars);
    const at = boundary > 80 ? boundary : titleLineChars;
    shown.push(line.slice(0, at).trimEnd());
    const tail = line.slice(at).trim();
    if (tail) rest.push(tail);
    rest.push(...lines.slice(index + 1));
    continued = true;
    break;
  }
  return { preview: shown.join('\n'), rest, continued };
}

/** The name to show when a document title only repeats its type. */
export function listTitle(row: { title?: string | null; document_type?: string | null; files?: readonly { saved_filename?: string | null; url?: string | null }[] | null }): string {
  const title = typeof row.title === 'string' ? row.title.trim() : '';
  const filename = recordedFileNames(row.files)[0] || '';
  const type = typeof row.document_type === 'string' ? row.document_type.trim() : '';
  if (filename && type && title.toLowerCase() === type.toLowerCase()) return filename;
  return title;
}

const filePartWords: Record<string, string> = { ERRATA: 'Errata', OTHERPART: 'Other part', FIRSTPART: 'First part' };

/** A hearing-volume part recorded on the file label when the title does not already say it. */
export function filePartNote(row: { title?: string | null; files?: readonly { label?: string | null }[] | null }): string {
  const title = (row.title || '').toLowerCase();
  const notes: string[] = [];
  for (const file of row.files || []) {
    const match = / — (ERRATA|OTHERPART|FIRSTPART) — /i.exec(file.label || '');
    const note = match ? filePartWords[match[1].toUpperCase()] : '';
    if (!note || title.includes(note.toLowerCase()) || notes.includes(note)) continue;
    notes.push(note);
  }
  return notes.join(' · ');
}

/** A committee page recorded with the downloaded file. Its address has no filename of its own. */
export function landingPageNote(row: { files?: readonly { role?: string | null }[] | null }): string {
  return (row.files || []).some(file => file.role === 'landing') ? 'Committee page' : '';
}

type NamedFile = { saved_filename?: string | null; url?: string | null };

function fileStem(name: string): string {
  return name.replace(/\.[^.]+$/, '').toLowerCase();
}

/** Put a PDF ahead of the HTML twin of the same file. Other recorded files keep their order. */
export function orderRecordedFiles<T extends NamedFile>(files: readonly T[]): T[] {
  const html = (name: string) => /\.html?$/i.test(name);
  const ranked = files.map(file => ({ file, name: recordedFileName(file) }));
  const result: typeof ranked = [];
  for (const item of ranked) {
    const stem = fileStem(item.name);
    const earlier = stem ? result.findIndex(existing => fileStem(existing.name) === stem && html(existing.name) && item.name && !html(item.name)) : -1;
    if (earlier >= 0) result.splice(earlier, 0, item);
    else result.push(item);
  }
  return result.map(item => item.file);
}

const formatNames: Record<string, string> = { pdf: 'PDF', html: 'HTML', htm: 'HTML', doc: 'Word', docx: 'Word', xml: 'XML' };

/** Every saved format when a document was kept as more than one, such as PDF and HTML. */
export function recordedFormatNote(files: readonly (NamedFile & { label?: string | null })[] | null | undefined): string {
  const names: string[] = [];
  for (const file of orderRecordedFiles(files || [])) {
    const token = (file.label || '').split('—')[0].trim().toLowerCase();
    const name = formatNames[token];
    if (name && !names.includes(name)) names.push(name);
  }
  if (names.length < 2) return '';
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(', ')}, and ${names.at(-1)}`;
}

/** One recorded filename per file, preferring the PDF over its HTML twin. */
export function recordedFileNames(files: readonly NamedFile[] | null | undefined): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const name of orderRecordedFiles(files || []).map(recordedFileName).filter(Boolean)) {
    const stem = fileStem(name);
    if (seen.has(stem)) continue;
    seen.add(stem);
    names.push(name);
  }
  return names;
}

const genericSegments = new Set(['public', 'download', 'watch', 'isvp', 'index', 'default', 'aspx']);
const formatLabel = /^(pdf|html|htm|docx?|xml|download|unknown)$/i;
const uuidSegment = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function pathSegment(url: string): string {
  try {
    return decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() || '');
  } catch {
    return '';
  }
}

function compactText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '');
}

/** A URL path name that is not a file extension, a generic folder, or an opaque id. */
function addressSegment(url: string): string {
  const segment = pathSegment(url);
  if (!segment || segment.includes('.') || genericSegments.has(segment.toLowerCase()) || /^\d+$/.test(segment) || uuidSegment.test(segment)) return '';
  return segment;
}

/** The recorded file name, from the saved copy or the URL path. */
export function recordedFileName(file: { saved_filename?: string | null; url?: string | null } | null | undefined): string {
  const saved = typeof file?.saved_filename === 'string' ? file.saved_filename.trim() : '';
  if (saved) return saved;
  if (typeof file?.url !== 'string') return '';
  const name = pathSegment(file.url);
  return name.includes('.') ? name : '';
}

/** Path names with no extension, when the title does not already spell them out. */
export function recordedAddressNames(row: { title?: unknown; files?: unknown }): string[] {
  const title = compactText(typeof row.title === 'string' ? row.title : '');
  const names: string[] = [];
  for (const file of Array.isArray(row.files) ? row.files : []) {
    if (!file || typeof file !== 'object') continue;
    const item = file as { url?: string | null; saved_filename?: string | null };
    if (recordedFileName(item)) continue;
    const name = addressSegment(typeof item.url === 'string' ? item.url : '');
    if (!name || title.includes(compactText(name)) || names.includes(name)) continue;
    names.push(name);
  }
  return names;
}

/** Link text for a saved file: a real label, otherwise the recorded path name. */
export function fileLinkName(file: { label?: string | null; role?: string | null; url?: string | null; saved_filename?: string | null } | null | undefined): string {
  if (file?.role === 'player' || file?.role === 'stream') return 'Watch recording';
  if (file?.role === 'landing') return 'Committee page';
  const label = typeof file?.label === 'string' ? file.label.trim() : '';
  const [head, ...rest] = label.split('—');
  const descriptive = formatLabel.test(head.trim()) ? rest.join('—').trim() : label;
  const named = descriptive.replaceAll('_', ' ');
  const filename = recordedFileName(file) || addressSegment(typeof file?.url === 'string' ? file.url : '');
  if (named && filename && !named.toLowerCase().includes(filename.toLowerCase())) return `${named} · ${filename}`;
  return named || filename || 'Open file';
}

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

function youtubeId(url: URL): string | undefined {
  if (url.hostname === 'youtu.be') return url.pathname.slice(1);
  if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'www.youtube-nocookie.com'].includes(url.hostname)) {
    return url.pathname === '/watch' ? url.searchParams.get('v') ?? undefined : url.pathname.match(/^\/(?:embed|shorts|live|v)\/([^/]+)\/?$/)?.[1];
  }
  return undefined;
}

/** The recorded video id when the URL has no filename. */
const meetingStatusNotes: Record<string, string> = {
  canceled: 'Meeting canceled',
  postponed: 'Meeting postponed',
  not_held: 'Meeting not held',
  rescheduled: 'Meeting rescheduled',
  unknown: 'Meeting status unknown',
};

/** A meeting status worth showing beside a document. Scheduled is the ordinary recorded value. */
export function meetingStatusNote(row: { meeting_status?: string | null }): string {
  return meetingStatusNotes[row.meeting_status || ''] || '';
}

export function recordingIdentity(url: string | null | undefined): string {
  if (!url) return '';
  try {
    const parsed = new URL(url);
    const video = youtubeId(parsed);
    if (video && /^[\w-]{11}$/.test(video)) return `YouTube ${video}`;
    if (['www.senate.gov', 'senate.gov'].includes(parsed.hostname) && /^\/isvp\/?$/.test(parsed.pathname)) return parsed.searchParams.get('filename') || '';
  } catch { /* A malformed source URL stays in the raw record. */ }
  return '';
}

export function recordingEmbedUrl(row: DisplayRow, now = new Date()): string | undefined {
  if (row.type !== 'recording' || !recordingVisible(row, now) || !row.recording_url) return undefined;
  try {
    const url = new URL(row.recording_url);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return undefined;
    const video = youtubeId(url);
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

const categoryCues: Record<string, readonly string[]> = {
  supporting: ['support'],
  disclosure: ['disclosure', 'truth in testimony'],
  bill_text: ['bill'],
  questions_for_record: ['question'],
  hearing_record: ['hearing'],
  biography: ['biograph'],
  witness_list: ['witness list'],
  committee_print: ['print'],
};

const providerLabels: Record<string, string> = {
  youtube: 'YouTube',
  senate: 'Senate',
  'www.senate.gov': 'Senate.gov',
  'www.c-span.org': 'C-SPAN',
  'www.facebook.com': 'Facebook',
  'www-senate-gov-msl3archive.akamaized.net': 'Senate video archive',
  'web.archive.org': 'Internet Archive',
  'www.jec.senate.gov': 'Joint Economic Committee',
  'www.dvidshub.net': 'DVIDS',
};

/** The publishing site in words. An unrecognized host keeps its recorded name. */
export function providerLabel(value: string | null | undefined): string {
  if (!value) return '';
  return providerLabels[value] || value.replace(/^www\./, '');
}

/** The recorded category when the document type does not already say it. */
export function categoryNote(row: { category?: string | null; document_type?: string | null }): string {
  const category = (row.category || '').trim();
  if (!category || category === 'unknown') return '';
  const stated = (row.document_type || '').toLowerCase();
  const cues = categoryCues[category] || [category.replaceAll('_', ' ')];
  if (stated && cues.some(cue => stated.includes(cue))) return '';
  return phrase(category);
}

export function parentCommitteeId(row: DisplayRow | null | undefined): string | undefined {
  return row?.parent_committee_id || row?.parent?.id || undefined;
}

const committeeKindLabels: Record<string, string> = {
  select: 'Select',
  special: 'Special',
  joint: 'Joint',
  task_force: 'Task force',
  commission_or_caucus: 'Commission or caucus',
};

/** A committee classification the committee name does not already state. */
export function committeeKindNote(row: { committee_types?: readonly (string | null | undefined)[] | null; committee_ids?: readonly string[] | null }, labels: Readonly<Record<string, string>> = {}): string {
  const names = (row.committee_ids || []).map(id => labels[id] || '').join(' ').toLowerCase();
  const notes: string[] = [];
  for (const type of row.committee_types || []) {
    if (!type || type === 'standing' || type === 'unknown' || type === 'other') continue;
    const label = committeeKindLabels[type];
    if (!label || notes.includes(label)) continue;
    const probes = type === 'commission_or_caucus' ? ['commission', 'caucus'] : [label.toLowerCase()];
    if (probes.some(word => names.includes(word))) continue;
    notes.push(label);
  }
  return notes.join(' · ');
}

/** Subcommittee, when none of the linked committee names already say so. */
export function committeeLevelNote(row: { committee_level?: string | null; committee_ids?: readonly string[] | null }, labels: Readonly<Record<string, string>> = {}): string {
  if (row.committee_level !== 'subcommittee') return '';
  const names = (row.committee_ids || []).map(id => labels[id] || '').join(' ').toLowerCase();
  return names.includes('sub') ? '' : 'Subcommittee';
}

export function committeeLevelLabel(row: DisplayRow): string {
  if (row.committee_level === 'full') return 'Full committee';
  if (row.committee_level === 'subcommittee') return 'Subcommittee';
  return '';
}

function phrase(value: unknown): string {
  if (value === 'business') return 'Business meeting';
  if (typeof value !== 'string' || !value || value === 'unknown') return '';
  const text = value.replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type RelatedRow = DisplayRow & {
  position?: string | null;
  organization?: string | null;
  roles?: readonly string[] | null;
  category?: string | null;
  severity?: string | null;
  chamber?: string | null;
  committee_code?: string | null;
  participation?: string | null;
};

/** A witness's recorded representative and city, when they add to the organization line. */
export function witnessNotes(row: { organization?: string | null; facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const facts = row.facts || [];
  const value = (label: string) => facts.find(fact => fact.label?.toLowerCase() === label)?.value?.trim() || '';
  const organization = (row.organization || '').trim().toLowerCase();
  const behalf = value('on behalf of');
  const notes: string[] = [];
  if (behalf && behalf.toLowerCase() !== 'themselves' && behalf.toLowerCase() !== organization) notes.push(`On behalf of ${behalf}`);
  const location = value('location');
  if (location) notes.push(location);
  return notes;
}

/** Roles other than the ordinary witness role, when the position line does not already state them. */
export function notableRoles(row: { position?: string | null; roles?: readonly (string | null)[] | null }): string[] {
  const position = (row.position || '').toLowerCase();
  const notes: string[] = [];
  for (const role of row.roles || []) {
    if (!role || role === 'witness' || role === 'unknown') continue;
    const label = phrase(role);
    if (!label || position.includes(label.toLowerCase()) || notes.includes(label)) continue;
    notes.push(label);
  }
  return notes;
}

/** Attendance the record distinguishes from a listing. */
export function participationNote(row: { participation?: string | null }): string {
  if (!row.participation || row.participation === 'unknown' || row.participation === 'listed') return '';
  return phrase(row.participation);
}

export interface RelatedPart { text: string; role?: 'place' | 'status' | 'note' }

/** Recorded facts a related-record row can show beside its title. */
export function relatedParts(kind: string, value: object): RelatedPart[] {
  const row = value as RelatedRow;
  const when = recordedWhen(row);
  const ownDay = (row.date || '').slice(0, 10);
  const clock = ownDay ? [when.date, when.time].filter(Boolean).join(' ') : '';
  const congress = congressName(row.congress);
  const recordedLabel = row.source_status === 'unknown' ? 'Unknown' : phrase(row.source_status);
  const recorded = row.source_status && row.source_status !== row.status && recordedLabel ? `Recorded as ${recordedLabel}` : '';
  const place = recordedPlace(row);
  const status = phrase(row.status);
  const notes = kind === 'data_issue' ? issueNotes(row) : [];
  const parts: RelatedPart[] = (kind === 'appearance'
    ? [row.position, row.organization, ...witnessNotes(row), ...notableRoles(row), participationNote(row), clock]
    : kind === 'meeting'
      ? [phrase(row.type), sourceTypeNote(row), clock, scheduleNote(row), congress, phrase(row.chamber), place, status, recorded]
      : kind === 'data_issue'
        ? [phrase(row.category), phrase(row.severity), phrase(row.status), when.date, detectedNote(row), ...notes]
        : kind === 'committee_term'
          ? [committeeTypeLabel(row) === 'Type unrecorded' ? '' : committeeTypeLabel(row), committeeLevelLabel(row), row.committee_code || '', congress]
          : [clock, scheduleNote(row), status]
  ).filter(Boolean).map(text => ({ text, role: notes.includes(text) ? 'note' as const : kind === 'meeting' && place && text === place ? 'place' as const : (kind === 'meeting' || kind === 'data_issue') && status && text === status ? 'status' as const : undefined }));
  const sources = sourceCountNote(row);
  if (!sources) return parts;
  const noteIndex = parts.findIndex(part => part.role === 'note');
  return noteIndex < 0 ? [...parts, { text: sources }] : [...parts.slice(0, noteIndex), { text: sources }, ...parts.slice(noteIndex)];
}

export function relatedMeta(kind: string, value: object): string {
  return relatedParts(kind, value).map(part => part.text).join(' · ');
}

/** Names this committee used in another Congress, with the Congresses that used each name. */
export function earlierCommitteeNames(terms: readonly { title?: string | null; congress?: number | null }[] | null | undefined, current: string): string[] {
  const names = new Map<string, number[]>();
  for (const term of terms || []) {
    const title = term.title?.trim() || '';
    if (!title || title === current) continue;
    const congresses = names.get(title) || [];
    if (typeof term.congress === 'number') congresses.push(term.congress);
    names.set(title, congresses);
  }
  return [...names].map(([title, congresses]) => {
    const years = [...new Set(congresses)].sort((left, right) => right - left);
    if (!years.length) return title;
    const consecutive = years.length > 2 && years.every((year, index) => index === 0 || year === years[index - 1] - 1);
    const span = consecutive ? `${years[years.length - 1]}th–${years[0]}th` : years.map(year => `${year}th`).join(', ');
    return `${title} · ${span} Congress`;
  });
}

/** The source's committee type when it names a different type than the normalized one. */
export function committeeSourceNote(row: { committee_type?: string | null; source_committee_type?: string | null }): string {
  const source = (row.source_committee_type || '').trim();
  const type = (row.committee_type || '').trim();
  if (!source || !type) return '';
  if (source.toLowerCase().replaceAll(' ', '_') === type) return '';
  return `Source recorded ${source}`;
}

const coverageAspectWords: Record<string, string> = {
  recording: 'recording',
  transcript: 'transcript',
  documents: 'document',
  witnesses: 'witness list',
  captions: 'caption',
};

/** What a coverage-chart drill is keeping, in the order the chart recorded it. */
export function coverageDrillNote(limits: { committee?: string; month?: string; aspect?: string; evidence?: string }): string {
  const notes: string[] = [];
  if (limits.committee) notes.push(`Only meetings of ${limits.committee}.`);
  if (limits.month === 'unknown') notes.push('Only meetings with no recorded month.');
  else if (limits.month) notes.push(`Only meetings in ${limits.month}.`);
  if (limits.aspect && limits.evidence) {
    const aspect = coverageAspectWords[limits.aspect] || limits.aspect.replaceAll('_', ' ');
    notes.push(`Only meetings whose ${aspect} evidence is ${phrase(limits.evidence) || limits.evidence}.`);
  }
  return notes.length ? `These limits came from a coverage chart. ${notes.join(' ')}` : '';
}

/** Which day a date filter uses, and which records that day leaves out. */
export function dateFilterReason(view: string, edge: 'from' | 'through'): string {
  const bound = edge === 'from' ? 'on or after' : 'on or before';
  if (view === 'gaps') return `Keep issues ${bound} this day. This uses the issue date. The detected day shown on a row does not keep it in the range. An issue with no date drops out.`;
  if (view === 'witnesses') return `Keep witnesses ${bound} this day. A witness with no date drops out.`;
  return `Keep records ${bound} this day. A record with no date uses its scheduled day. Records with neither drop out.`;
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
