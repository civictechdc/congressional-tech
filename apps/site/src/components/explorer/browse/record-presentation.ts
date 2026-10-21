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

type WhenOptions = { timeZone?: string; locale?: string };

/** Format a stored instant with the browser’s locale and timezone (or an explicit zone for tests). */
function browserInstant(value: string, options: WhenOptions = {}): { date: string; time: string } | null {
  if (!/^\d{4}-\d{2}-\d{2}T/.test(value)) return null;
  // Date-only midnights are stored as midnight UTC; do not invent a clock time.
  if (/T00:00:00(?:\.\d+)?(?:Z|[+-]00:00)$/.test(value)) return { date: value.slice(0, 10), time: '' };
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return null;
  const instant = new Date(ms);
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: options.timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(instant);
  const time = new Intl.DateTimeFormat(options.locale, { timeZone: options.timeZone, hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(instant);
  return { date, time };
}

/** The recorded calendar day, plus a clock time in the viewer’s local zone when a scheduled instant was stored. */
export function recordedWhen(row: { date?: string | null; scheduled_at?: string | null }, options: WhenOptions = {}): { date: string; time: string } {
  const scheduled = row.scheduled_at || '';
  const scheduledDay = /^\d{4}-\d{2}-\d{2}/.test(scheduled) ? scheduled.slice(0, 10) : '';
  const date = (row.date || '').slice(0, 10) || scheduledDay;
  const sameDay = Boolean(scheduledDay) && date === scheduledDay;
  if (!sameDay || !scheduled.includes('T')) return { date, time: '' };
  const local = browserInstant(scheduled, options);
  return { date, time: local?.time || '' };
}

/** The date and time a related row would show, including a schedule that falls on another day. */
export function listedWhen(row: { date?: unknown; scheduled_at?: unknown }, options: WhenOptions = {}): string {
  const dated = { date: typeof row.date === 'string' ? row.date : '', scheduled_at: typeof row.scheduled_at === 'string' ? row.scheduled_at : '' };
  const day = dated.date.slice(0, 10);
  const clock = day ? [day, recordedWhen(dated, options).time].filter(Boolean).join(' ') : '';
  return [clock, scheduleNote(dated, options)].filter(Boolean).join(' · ');
}

/** True when a related row’s time only repeats the meeting already open. A different day or a more specific time stays. */
export function repeatsRecordedWhen(value: string, meetingWhen: string): boolean {
  const when = value.trim();
  const meeting = meetingWhen.trim();
  if (!when || !meeting) return false;
  if (when === meeting) return true;
  const day = meeting.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) && when === day && meeting.startsWith(`${day} `);
}

/** A scheduled instant that is not already the record’s own date. */
export function scheduleNote(row: { date?: string | null; scheduled_at?: string | null }, options: WhenOptions = {}): string {
  const scheduled = row.scheduled_at || '';
  if (!/^\d{4}-\d{2}-\d{2}T/.test(scheduled)) return '';
  const date = (row.date || '').slice(0, 10);
  if (date && date === scheduled.slice(0, 10)) return '';
  const local = browserInstant(scheduled, options);
  if (!local) return '';
  return `Scheduled ${[local.date, local.time].filter(Boolean).join(' ')}`;
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

function plainSourceId(value: string): string {
  const parts = value.split('|').map(part => part.trim()).filter(Boolean);
  const chamber = parts.length >= 3 ? { house: 'House', senate: 'Senate', joint: 'Joint' }[parts[2].toLowerCase()] : '';
  if (parts.length >= 4 && /^\d+$/.test(parts[1]) && chamber) return `${congressName(parts[1])}, ${chamber}, event ${parts.slice(3).join(' ')}`;
  if (parts.length === 3 && /^\d+$/.test(parts[1]) && parts[2]) return `${congressName(parts[1])}, event ${parts[2]}`;
  return '';
}

function identifierLine(value: unknown): string {
  const record = parsed(value);
  if (typeof record === 'string') return plainSourceId(record.trim()) || record.trim();
  if (!record || typeof record !== 'object' || Array.isArray(record)) return '';
  const identifier = record as { scheme?: unknown; value?: unknown };
  const id = typeof identifier.value === 'string' ? identifier.value.trim() : '';
  return plainSourceId(id) || [identifier.scheme, id].filter(Boolean).join(' · ');
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
  parts.push(...values('Sponsor Bioguide ID').map(value => `Member number ${value}`));
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

/** Ordinary bill numbers and vote notes. Catalog codes such as HR 2625 become H.R. 2625. */
export function plainLegislativeNote(value: string): string {
  return value
    .replace(/\s*\(no attached file\)\s*$/i, '')
    .replace(/\bH\.?\s*Con\.?\s*Res\.?\s*(\d+)\b/gi, 'H.Con.Res. $1')
    .replace(/\bS\.?\s*Con\.?\s*Res\.?\s*(\d+)\b/gi, 'S.Con.Res. $1')
    .replace(/\bH\.?\s*J\.?\s*Res\.?\s*(\d+)\b/gi, 'H.J.Res. $1')
    .replace(/\bS\.?\s*J\.?\s*Res\.?\s*(\d+)\b/gi, 'S.J.Res. $1')
    .replace(/\bH\.?\s*Res\.?\s*(\d+)\b/gi, 'H.Res. $1')
    .replace(/\bS\.?\s*Res\.?\s*(\d+)\b/gi, 'S.Res. $1')
    .replace(/\bH\.?R\.?\s*(\d+)\b/gi, 'H.R. $1')
    .replace(/\bS\.?\s*(\d+)\b/g, 'S. $1')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Every bill, resolution, treaty, and nomination recorded for a meeting. */
export function recordedMeasureValues(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const seen = new Set<string>();
  const values: string[] = [];
  for (const fact of row.facts || []) {
    const value = plainLegislativeNote(fact.value?.trim() || '');
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
export const evidenceStateLabels: Record<string, string> = {
  observed: 'Seen in a checked source',
  reported: 'Stated by the source',
  curated: 'Entered in this archive',
  derived: 'Worked out from other facts',
  inferred: 'Likely match, needs a check',
  not_found_in_checked_scope: 'Not found where we looked',
  error: 'Check failed',
  blocked: 'Check blocked',
  not_applicable: 'Outside this meeting',
  unknown: 'Not recorded',
  unchecked: 'Not checked',
};

/** The recorded evidence state for each meeting aspect. */
export function evidenceParts(states: { [key: string]: string | null | undefined } | null | undefined): string[] {
  if (!states) return [];
  return evidenceAspects.flatMap(([key, label]) => {
    const state = states[key];
    if (!state) return [];
    const word = evidenceStateLabels[state] || state.replaceAll('_', ' ');
    return [`${label} ${word.charAt(0).toLowerCase()}${word.slice(1)}`];
  });
}

/** The recorded evidence state for each meeting aspect, in one line. */
export function evidenceLine(states: { [key: string]: string | null | undefined } | null | undefined): string {
  return evidenceParts(states).join(' · ');
}

const quietEvidence = new Set(['unchecked', 'unknown', 'not_applicable']);

/** Evidence a meeting row can show. Not checked, not recorded, and does not apply stay on the record. */
export function listedEvidence(states: { [key: string]: string | null | undefined } | null | undefined, options: { omit?: readonly string[] } = {}): string[] {
  if (!states) return [];
  const omit = new Set(options.omit || []);
  return evidenceAspects.flatMap(([key]) => omit.has(key) || quietEvidence.has(states[key] || '') ? [] : evidenceParts({ [key]: states[key] }));
}

/** How many people the meeting list should mention without naming them. */
export function listedWitnessCount(count: number): string {
  if (count <= 0) return '';
  return count === 1 ? '1 witness' : `${count} witnesses`;
}

/** A location's recorded "label" is the place, when the same record also names a building or city. */
export function factLabel(label: string, siblingLabels: readonly string[]): string {
  const names = siblingLabels.map(item => item.toLowerCase());
  if (label.toLowerCase() === 'label' && names.some(item => item === 'building' || item === 'city')) return 'Place';
  return label;
}

/** Recorded roll-call or voice-vote results, in the order they were stored. */
export function recordedVotes(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  return numberedFactValues(row.facts, 'vote');
}

/** Recorded amendment outcomes, in the order they were stored. */
export function recordedAmendments(row: { facts?: readonly { label?: string | null; value?: string | null }[] | null }): string[] {
  const numbered = (row.facts || []).flatMap(fact => {
    const label = fact.label || '';
    const value = fact.value?.trim() || '';
    const match = /^amendment (\d+)$/i.exec(label);
    const note = plainLegislativeNote(value);
    if (!match || !note) return [];
    const text = note.toLowerCase().includes(label.toLowerCase()) ? note : `${label}: ${note}`;
    return [{ n: Number(match[1]), text }];
  }).sort((a, b) => a.n - b.n).map(item => item.text);
  const plain = (row.facts || []).flatMap(fact => {
    const label = fact.label || '';
    const note = plainLegislativeNote(fact.value?.trim() || '');
    if (label.toLowerCase() !== 'amendment' || !note) return [];
    return [note.toLowerCase().includes(label.toLowerCase()) ? note : `${label}: ${note}`];
  });
  return [...numbered, ...plain];
}

function numberedFactValues(facts: readonly { label?: string | null; value?: string | null }[] | null | undefined, name: string): string[] {
  return (facts || []).flatMap(fact => {
    const match = new RegExp(`^${name} (\\d+)$`, 'i').exec(fact.label || '');
    const value = plainLegislativeNote(fact.value?.trim() || '');
    return match && value ? [{ n: Number(match[1]), text: value }] : [];
  }).sort((a, b) => a.n - b.n).map(item => item.text);
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
    if (label.toLowerCase() === 'selection reason') return ['Why this version', plainRecordedNote(value)];
    if (label.toLowerCase() === 'resolution') return ['What was decided', plainRecordedNote(value)];
    if (measureLabels.includes(label) || /^(vote|amendment)(?: \d+)?$/i.test(label)) return [label, plainLegislativeNote(value)];
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

const sourceEnvelope = [['provider', 'Source'], ['retrieved_at', 'Fetched'], ['imported_at', 'Added here'], ['source_modified_at', 'Changed at the source'], ['retained_uri', 'Saved original']] as const;
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
  for (const [key, label] of sourceEnvelope) {
    if (typeof row[key] !== 'string' || !row[key].trim()) continue;
    const recorded = row[key].trim();
    if (label === 'Saved original' && !/^https?:\/\//i.test(recorded)) continue;
    facts.push([label, ['Fetched', 'Added here', 'Changed at the source'].includes(label) ? recordedInstant(recorded) : recorded]);
  }
  const identifier = identifierLine(row.identifier);
  if (identifier) facts.push(['Record number', identifier]);
  const payload = payloadOf(value);
  if (!payload) return facts;
  const place = addressLine(payload.location);
  if (place) facts.push(['Place', place]);
  for (const [key, label] of [['meetingStatus', 'Status at the source'], ['type', 'Type at the source'], ['eventId', 'Event number'], ['updateDate', 'Updated at the source']] as const) {
    const recorded = key === 'updateDate' ? recordedInstant(text(payload[key])) : text(payload[key]);
    if (recorded) facts.push([label, recorded]);
  }
  const committees = rowsOf(payload.committees).map(item => text(item.name) || (text(item.systemCode) ? `Committee code ${text(item.systemCode)}` : '')).filter(Boolean);
  if (committees.length) facts.push(['Committees', committees.join('\n')]);
  const witnesses = [...rowsOf(payload.witnesses), ...rowsOf(payload.people)].map(witnessLine).filter(Boolean);
  if (witnesses.length) facts.push(['Source witnesses', [...new Set(witnesses)].join('\n')]);
  if (payload.absent === true) facts.push(['Listing', 'Recorded as absent']);
  const related = relatedLines(payload.relatedItems);
  if (related) facts.push(['Related items', related]);
  const transcripts = rowsOf(payload.hearingTranscript).map(item => text(item.jacketNumber)).filter(Boolean).map(jacket => `Transcript number ${jacket}`);
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
  return [titled, text(item.position), organization, location && !covered.includes(location.toLowerCase()) ? location : '', behalf && !covered.includes(behalf.toLowerCase()) ? `On behalf of ${behalf}` : '', text(item.witness_type), text(item.panel) ? `Panel ${text(item.panel)}` : '', page && !/^https?:\/\//i.test(page) ? `Page ${page}` : '', testifiedNote(text(item.testified)), bioguide ? `Member number ${bioguide}` : ''].filter(Boolean).join(' · ');
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
  if (value === 'webvtt') return 'Web captions';
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
  push('YouTube video', payload.videoId);
  const duration = clockDuration(payload.duration);
  if (duration) facts.push(['Duration', duration]);
  if (typeof payload.caption === 'boolean') facts.push(['Captions', payload.caption ? 'Recorded' : 'Not recorded']);
  if (description && description.toLowerCase() !== title.toLowerCase()) facts.push(['Description', description]);
  push('Published', recordedInstant(text(payload.publishedAt)));
  push('GovInfo number', payload.package_id);
  push('Committee', payload.committee_name);
  push('Committee code', payload.committee_code);
  push('Subcommittee', payload.subcommittees);
  push('Held', payload.held_date);
  push('Serial', payload.serial);
  const witnesses = text(payload.witness_count);
  if (witnesses && witnesses !== '0') facts.push(['Witnesses listed', witnesses]);
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
  push('File dated', recordedInstant(text(payload.version)));
  push('Meeting file updated', recordedInstant(text(payload.xml_update)));
  const events = Array.isArray(payload.events) ? payload.events.map(text).filter(Boolean) : [];
  if (events.length) facts.push(['Event number', events.join('\n')]);
  if (!text(payload.eventId)) push('Event number', payload.event_id);
  const witness = [text(payload.name), text(payload.position), text(payload.organization)].filter(Boolean).join(' · ');
  if (witness && !rowsOf(payload.witnesses).length) facts.push(['Witness', witness]);
  push('Part of', payload.from);
  push('Channel', payload.channelTitle);
  push('Citation', payload.preferred_citation);
  const length = minuteLength(text(payload.video_minutes));
  if (length) facts.push(['Video length', length]);
  push('Matched channels', payload.channels);
  const recordType = text(payload.record_type);
  if (recordType && recordType.toLowerCase() !== 'hearing') facts.push(['Record type', recordType]);
  push('Last changed', recordedInstant(text(payload.last_modified)));
  const ingested = text(payload.date_ingested).slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(ingested)) facts.push(['Added at the source', ingested]);
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
      if (sponsor && !existing.label.includes(`Member number ${sponsor}`)) existing.label = `${existing.label} · Member number ${sponsor}`;
      continue;
    }
    const named = [text(item.bill), text(item.number) ? `Amendment ${text(item.number)}` : '', text(item.description), sponsor ? `Member number ${sponsor}` : ''].filter(Boolean).join(' · ') || 'Amendment';
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

function tupleParts(item: unknown[]): string[] {
  return item.flatMap(part => Array.isArray(part) ? part.flatMap(text).filter(Boolean) : text(part) ? [text(part)] : []);
}

function tupleLinks(value: unknown, fallback: string): SourceLink[] {
  if (!Array.isArray(value)) return [];
  const links: SourceLink[] = [];
  for (const item of value) {
    if (!Array.isArray(item)) continue;
    const parts = tupleParts(item);
    const href = parts.find(part => /^https?:\/\//i.test(part));
    const recorded = parts.find(part => part.includes('://') || /^mailto:/i.test(part));
    const address = href || recorded;
    if (!address) continue;
    const group = parts.find(part => part !== address && !part.includes('://') && !/^mailto:/i.test(part) && !part.includes('.')) || fallback;
    const named = parts.filter(part => part && part !== address && part !== group).join(' · ') || group;
    const filename = href ? linkFilename(href) : '';
    const label = href
      ? filename && !named.includes(filename) ? `${named} · ${filename}` : named
      : `${named} · Not a web link. The saved address has extra “mailto:” text in front of ${address.replace(/^mailto:/i, '')}`;
    links.push({ group: group.charAt(0).toUpperCase() + group.slice(1), href: address, label });
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
  const parts = path.split(' · ').filter(part => part.toLowerCase() !== 'details');
  return (parts.length ? parts : path.split(' · ')).map(part => part.toLowerCase() === 'id' ? 'ID' : phrase(part) || part).join(' ');
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

function versionName(index: number): string {
  return index === 1 ? 'another recorded version' : `recorded version ${index}`;
}

function differenceLine(path: string, selected: string, alternative: string, index: number): string {
  const name = readablePath(path);
  const other = versionName(index);
  const identifier = /^[0-9a-f-]{32,}$/i.test(selected) || /^[0-9a-f-]{32,}$/i.test(alternative);
  if (identifier) {
    const otherLabel = `${other[0].toUpperCase()}${other.slice(1)}`;
    if (selected === 'none') return `${name}: not recorded on this version. ${otherLabel} has one.`;
    if (alternative === 'none') return `${name}: recorded on this version. ${otherLabel} does not have one.`;
    return `${name}: the two versions name different values.`;
  }
  return `${name}: ${readableValue(selected)} on this record; ${readableValue(alternative)} on ${other}`;
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

const recordedPhrases: Record<string, string> = {
  'The original video publication time is not established by this cache.': 'The original time this video was published is not known from the saved copy.',
  'This recording has no verified meeting association.': 'This recording is not matched to a meeting.',
  'This package has no verified meeting association.': 'This set of published files is not matched to a meeting.',
  'The retained decision aggregates its recording evidence.': 'This result combines several recordings and is not split among them.',
  'This document has no supported meeting association.': 'This document is not matched to a meeting.',
  'Sources disagree about label': 'Sources disagree about the label.',
  'Package-level recordings cannot yet be assigned to individual meetings.': 'These recordings belong to a whole volume and are not assigned to one meeting.',
  'The caption observation has no supported observation date.': 'These captions have no saved date for when they were seen.',
  'Legacy House state omits alternate file URLs and source ownership': 'An older House record does not include other file addresses or who provided the file.',
  'Sources disagree about name': 'Sources disagree about the name.',
  'This page has no retained live retrieval receipt.': 'This page has no saved record of a live download.',
  'The probe has no supported live check date.': 'There is no saved date for a live check of this page.',
  'This committee/day probe has no known recording association.': 'No recording is matched to this committee on this day.',
  'Sources disagree about participation': 'Sources disagree about how the person took part.',
  'The retained witness source has no supported live retrieval check.': 'This witness record has no saved live check.',
  'This retained committee page has no supported meeting association.': 'This committee page is not matched to a meeting.',
  'Sources disagree about title': 'Sources disagree about the title.',
  'Witness rows have no meeting ownership in this source record.': 'These witnesses are not matched to a meeting in this source.',
  'The retained clips_only verdict omits the clip identifiers.': 'This result says there are clips, but the clip names were not saved.',
  'This caption observation has no known recording identity.': 'These captions are not matched to a recording.',
  'Same-name witness rows need identity review': 'Witnesses with the same name still need to be checked.',
  'Sources disagree about proceeding_dates': 'Sources disagree about the dates.',
  "The reported held date differs from the transcript's retained day headers.": 'The reported date differs from the dates in the transcript.',
  'Sources disagree about role': 'Sources disagree about the role.',
  'Same-name House witnesses need correspondence review': 'House witnesses with the same name still need to be checked as one person.',
  'Source repeats the same convening committee': 'The source lists the same committee more than once.',
  'A House source file URL is malformed': 'A House file address is not a usable download link.',
  'Sources disagree about meeting_type': 'Sources disagree about the kind of meeting.',
  'This retained page may contain binary document data decoded as text.': 'This page may be a document that was saved as unreadable text.',
  'Sources disagree about chamber': 'Sources disagree about the chamber.',
  'Later record in deterministic source order; alternatives retained.': 'The later source was kept. The other version is still saved.',
  'Use the retained transcript day headers when supplied; otherwise use the native held dates.': 'The date comes from the transcript when it has one. Otherwise it is the date the meeting was held.',
  'The retained publishedAt field is the playlist-item timestamp. It remains in the source record.': 'The published date is the time this item was added to the playlist. That time is still saved with the original source.',
  'Retained as a document. A title, committee code or hearing date alone does not establish meeting identity.': 'Kept as a document. A title, a committee, or a hearing date is not enough to name the meeting.',
  'Its method, maximum score, channels and total minutes cannot be assigned to each video. The score is a matcher rank, not a probability; the producer revision and original check time are unavailable.': 'This result covers more than one video, so it is not split across them. The ranking is not a chance of being right, and the original check time was not saved.',
  'The containing page has no unambiguous saved meeting match.': 'The page this came from does not match one saved meeting.',
  'There is no single supported meeting and date combination. Shared or multiple-date volume results are retained at package level without distributing recordings across meetings.': 'These recordings belong to a volume that covers more than one meeting or date, so they stay with the volume.',
  'Index-only observations remain undated. Import time and file modification time are not capture times.': 'Only an index entry was saved, so there is no capture date. When the file was imported or last changed is not when it was captured.',
  'The saved checked day may be a cache import or scheduling date. It does not establish when the source was observed.': 'The saved check date may be when the file was imported or scheduled. It is not when the source was seen.',
  "Research HEAD cache dates come from the imported file's modification time. They are not source observation times.": 'The saved date is when the imported file was last changed. It is not when the source was seen.',
  'Its source scope is retained. A committee and date alone do not establish a meeting identity.': 'A committee and a date are not enough to name the meeting. The original scope is still saved.',
  'Its checked day and any import time are preserved in the payload and are not promoted to retrieval timestamps.': 'The date this was checked, and the date it was imported, stay with the original source. They are not used as the date the record was retrieved.',
  'Documents remain discoverable. Witness rows remain in the source payload until their meeting is established.': 'The documents can still be found. The witness list stays with the original source until the meeting is identified.',
  'A recovered row with an explicit, unique event association is required before creating an appearance.': 'A witness is recorded only when the file points to one specific event.',
  'The file appears on more than five pages and may be site-wide content.': 'This file appears on more than five pages and may belong to the whole site.',
  'No clip resources or full-recording coverage were created from this aggregate verdict.': 'No clips or full-recording coverage were saved from this combined result.',
  'Both dates remain available; neither establishes a new meeting or proves the other is incorrect.': 'Both dates are saved. Neither one creates a new meeting or shows that the other date is wrong.',
  'The selected meeting association is listed once; the raw repeated entries remain in evidence.': 'The meeting is listed once. The repeated entries are still saved.',
  'The original value remains in source evidence. It cannot be offered as an absolute HTTP(S) download URL without a verified correction.': 'The original address is saved. It cannot be offered as a download until it is corrected.',
  'The URL ends in .pdf, the title is empty, and retained lines contain replacement or control characters. Original response bytes and MIME type are not retained, so the input format remains unverified.': 'The address ends in .pdf, the title is empty, and the saved text contains unreadable characters. The original file was not kept, so its format is not confirmed.',
  'The existing print matcher supplied a supported association; its method and evidence remain on the link.': 'A match to a printed hearing was saved with this link.',
  'Original bytes and acquisition metadata; cached replay is not a new upstream retrieval.': 'The original file and the notes about how it was collected are saved. Reading the saved copy again is not a new download.',
  'Retained supplemental source records; uncollected meetings and unsupported layouts are not covered.': 'Extra source records are saved. Meetings that were not collected, and page layouts this archive does not read, are not included.',
  'Cited corrections preserve original source names and classifications.': 'Corrections keep the original names and categories.',
  'Existing matcher decisions computed from all supplied native/GPO context before applying the export selection.': 'Matches were decided from the full source material before this export chose what to include.',
  'Retained metadata only; caption availability and reachability have not been checked by this export.': 'Only the description is saved. This export did not check whether captions exist or whether the page still opens.',
  'Original notes and discovery method retained; links do not prove full coverage or current reachability.': 'The original notes and how the file was found are saved. A link does not mean the whole site was collected or that the page still opens.',
  'Aggregate matcher evidence retained; only single-meeting, single-date package associations create meeting links.': 'The match notes are saved. A package is linked to a meeting only when it belongs to one meeting on one date.',
  'Unsupported ownership and cache-derived dates remain explicit issues; no caption content is invented.': 'Unclear ownership and dates taken from a saved copy stay listed as issues. Caption text is not made up.',
  'Unique explicit event associations supply listed appearances; title-derived nominees remain inferred. Unique matching originating appearances retain their identity and richer fields.': 'A witness is listed when the file names one specific event. A person guessed from a title stays marked as a guess. A witness who matches one earlier record keeps that identity and its extra details.',
  'No body artifacts were supplied; metadata links do not establish captured or searchable text.': 'The text of the document was not included. A link in the description does not mean the text was captured or can be searched.',
  'Legacy native records lack per-record retrieval timestamps.': 'Older records do not say when each one was downloaded.',
  'Legacy checked dates may reflect seed import; live retrieval is established only by explicit receipts.': 'An older check date may be when the file was first imported. A live download is recorded only when there is a receipt for it.',
  'CSV does not preserve all raw MODS metadata or downloaded transcript bytes.': 'The spreadsheet does not keep every original catalog field or the downloaded transcript.',
  'Derived offline from retained meeting and GPO inputs, using existing matcher rules.': 'Worked out from the saved meetings and Government Publishing Office files, using the existing match rules.',
  'Offline export: import time is not a source check.': 'This is a saved export. The time it was imported is not the time a source was checked.',
  'Existing print matching rules run offline with explanations; video matching heuristics are not rerun.': 'Printed-hearing matches were made from the saved files, with an explanation. Video matches were not run again.',
  'Historical issue evidence may refer to records outside the current selection; meeting index describes the current selection.': 'An older issue may point at a record that is not in this selection. The meeting index describes only this selection.',
  'Retained committee meeting records, all statuses': 'Saved committee meeting records, including every status',
  'Official Congress-scoped committee lists': 'Official committee lists for each Congress',
  'Retained MODS and transcript observations': 'Saved catalog records and transcript notes',
  'House parsed source state': 'House records as read from the source',
  'Senate parsed source state': 'Senate records as read from the source',
  'Reviewed committee metadata corrections': 'Reviewed corrections to committee records',
  'Print-to-meeting associations': 'Links from printed hearings to meetings',
  'Retained GPO package metadata': 'Saved Government Publishing Office package descriptions',
  'Retained manual meeting-recording associations': 'Saved links between meetings and recordings that were entered by hand',
  'Retained package recording decisions': 'Saved decisions about which recording belongs to a package',
  'Retained caption, archive and witness observations': 'Saved notes on captions, archives, and witnesses',
  'Retained recovered witness rows': 'Saved witness rows that were recovered',
  'Retained transcript bodies': 'Saved transcript text',
};

const collectionNames: Record<string, string> = { congress: 'Congress', meetings: 'meetings', committees: 'committee', youtube: 'YouTube' };

function plainSentence(text: string): string {
  const known = recordedPhrases[text] || recordedPhrases[text.charAt(0).toUpperCase() + text.slice(1)];
  if (known) return known;
  if (text.startsWith('Collectors assigned different internal edition labels.')) return 'The sources used different edition labels. That is not a disagreement about the content.';
  const importedAll = /^Imported (\d+) of (\d+) retained records\. Retention is not proof of complete upstream coverage\.?$/.exec(text);
  if (importedAll) return `All ${Number(importedAll[1]).toLocaleString('en-US')} of ${Number(importedAll[2]).toLocaleString('en-US')} saved records were included. Saving a record does not mean every source was collected.`;
  const committees = /^Imported (\d+) retained committee records; committees with no retained meetings may also appear\.?$/.exec(text);
  if (committees) return `${Number(committees[1]).toLocaleString('en-US')} saved committee records were included. A committee with no saved meetings can still appear.`;
  const packages = /^Imported (\d+) packages; explicit committee IDs and cited document reviews establish committee ownership\. Explicit event IDs and existing print matching rules separately supply meeting associations\.?$/.exec(text);
  if (packages) return `${Number(packages[1]).toLocaleString('en-US')} published packages were included. A committee is named only when the package or a document review says so. A meeting is named only when the package names one event, or an existing printed-hearing match does.`;
  const job = /^Collection job ([a-z0-9_.:-]+) concluded (success|failure); this job-level receipt does not establish individual source acquisition outcomes\.?$/i.exec(text);
  if (job) {
    const name = collectionNames[job[1].toLowerCase()] || job[1];
    return `The ${name} collection ${job[2].toLowerCase() === 'success' ? 'reported success' : 'reported a failure'}. That does not show the result for each source.`;
  }
  const browserCopy = /^Browser distribution: original publication [0-9a-f]+\. Complete Catalog and legacy meeting index are excluded; query pages retain browse coverage\.?$/i.exec(text);
  if (browserCopy) return 'This copy is for the browser. The full catalog and the older meeting index are left out. Browsing still covers the records in this selection.';
  return text;
}

/** A saved issue sentence in ordinary words. The exact saved text stays in the full record. */
export function plainRecordedNote(value: string): string {
  const text = value.trim();
  const direct = plainSentence(text);
  if (direct !== text) return direct;
  const parts = text.split(/(?<=\.)\s+/);
  if (parts.length < 2) return text;
  const plain = parts.map(plainSentence);
  return plain.some((part, index) => part !== parts[index]) ? plain.join(' ') : text;
}

const sourceNames: Record<string, string> = {
  'congress.gov': 'Congress.gov',
  'congress.gov:committees': 'Congress.gov committees',
  'govinfo:upstream': 'GovInfo files',
  docs: 'House docs',
  'docs.house.gov': 'House docs',
  'senate.committees': 'Senate committees',
  'committee-review': 'Committee review',
  'gpo.committee-review': 'Committee review',
  'congress_api.inventory.prints': 'Printed hearings',
  govinfo: 'GovInfo',
  youtube: 'YouTube',
  'curated-recordings': 'Curated recordings',
  'curated-issue-decisions': 'Curated issue decisions',
  'gpo-video-matches': 'Printed-hearing video matches',
  'meeting-inventory': 'Meeting inventory',
  'recovered-witnesses': 'Recovered witnesses',
  'transcript-artifact': 'Transcripts',
};

/** A source name a reader can recognize. An unknown source keeps its saved name. */
export function sourceName(value: string): string {
  return sourceNames[value] || value;
}

/** A subject the explorer cannot open by title: source record, committee, or person. */
export function subjectKindLabel(kind: string | null | undefined): string {
  if (kind === 'source_record') return 'source record';
  if (kind === 'committee') return 'committee';
  if (kind === 'person') return 'person';
  return '';
}

/** A linked record the publication does not contain. */
export function subjectAbsentNote(kind: string | null | undefined): string {
  const names: Record<string, string> = { material: 'document or recording', meeting: 'meeting', appearance: 'witness', committee_term: 'committee', source_record: 'original source' };
  const name = kind ? names[kind] : '';
  return name ? `The ${name} this issue describes is not in this publication.` : '';
}

/** How many source observations a record was built from, when there is more than one. */
export function sourceCountNote(row: { source_ids?: readonly string[] | null }): string {
  const count = row.source_ids?.length || 0;
  if (count < 2) return '';
  return `Built from ${count} original pages`;
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
  const selected = values('Selected value')[0] || '';
  const alternatives = facts.filter(fact => /^alternative \d+$/i.test(fact.label || '')).map(fact => fact.value || '');
  const summary = selected && alternatives.length ? disagreementSummary(selected, alternatives) : null;
  if (field && !summary?.length) notes.push(`Compared field: ${field}`);
  const plain = (value: string) => Boolean(value) && value.length <= 240 && !value.startsWith('{') && !value.startsWith('[');
  if (summary?.length) notes.push(...summary.slice(0, 2));
  else if (plain(selected)) {
    notes.push(selected);
    const first = plainIssueValues(row)[0];
    if (first) notes.push(`Alternative: ${first}`);
  }
  const heading = plainRecordedNote((row.title || '').trim());
  const add = (value: string) => {
    const plain = plainRecordedNote(value);
    if (plain && plain !== heading && !notes.includes(plain)) notes.push(plain);
  };
  const reason = values('Selection reason')[0];
  if (reason) add(reason);
  const resolution = values('Resolution')[0];
  const explanation = (row.explanation || '').trim();
  if (resolution && resolution !== (row.title || '').trim() && resolution !== explanation) add(resolution);
  if (explanation && explanation !== (row.title || '').trim()) add(explanation);
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
  if (filename && type && (title.toLowerCase() === type.toLowerCase() || listedDocumentType(title).toLowerCase() === listedDocumentType(type).toLowerCase())) return filename;
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

const formatNames: Record<string, string> = { pdf: 'PDF', html: 'web page', htm: 'web page', doc: 'Word', docx: 'Word', xml: 'XML file' };

/** Every saved format when a document was kept as more than one, such as PDF and a web page. */
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

const documentTypeNames: Record<string, string> = {
  'Generic Document': 'Document',
  'Support Document': 'Supporting document',
  'Witness Biography': 'Witness biography',
  'Witness Statement': 'Witness statement',
  'Witness List': 'Witness list',
  'Witness Support Document': 'Supporting document for a witness',
  'Witness Truth in Testimony': 'Truth in testimony',
  'Truth in Testimony': 'Truth in testimony',
  'Bills and Resolutions': 'Bills and resolutions',
  'Member Roster': 'Member roster',
  'Hearing: Transcript': 'Transcript',
  'Hearing: Witness List': 'Witness list',
  'Hearing: Questions for the Record': 'Questions for the record',
  'Hearing: Member Roster': 'Member roster',
  'Hearing: Cover Page': 'Cover page',
  'Hearing: Table of Contents': 'Table of contents',
  'COMMITTEE PRINT': 'Committee print',
};

/** The recorded document type in ordinary words. Catalog prefixes such as “Hearing:” stay in the saved record. */
export function listedDocumentType(value: string): string {
  return documentTypeNames[value] || value;
}

/** The source pile, omitted when the document type already says the same thing. */
export function listedSourcePile(row: DisplayRow, documentType: string): string {
  return documentSourceLabel(row).split(' · ').filter(part => {
    if (part === 'Witness document' && documentType.toLowerCase().includes('witness')) return false;
    if (part === 'Meeting document' && documentType) return false;
    return true;
  }).join(' · ');
}

/** On the meeting itself, “Meeting document” only repeats the documents list. A witness document still says so. */
export function documentSourceInContext(row: DisplayRow, onMeeting: boolean): string {
  return documentSourceLabel(row).split(' · ').filter(part => !(onMeeting && part === 'Meeting document')).join(' · ');
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
  senate: 'Senate.gov',
  'www.senate.gov': 'Senate.gov',
  'www.c-span.org': 'C-SPAN',
  'www.facebook.com': 'Facebook',
  'www-senate-gov-msl3archive.akamaized.net': 'Senate video archive',
  'web.archive.org': 'Internet Archive',
  'www.jec.senate.gov': 'Joint Economic Committee',
  'www.dvidshub.net': 'Defense media library',
};

/** The publishing site in words. An unrecognized host keeps its recorded name. */
const severityLabels: Record<string, string> = {
  affects_interpretation: 'Changes how to read it',
  informational: 'For information only',
};

export function severityLabel(value: string | null | undefined): string {
  if (!value) return '';
  return severityLabels[value] || phrase(value);
}

/** Issue workflow status in ordinary words. */
export function issueStatusLabel(value: string | null | undefined): string {
  if (!value) return '';
  if (value === 'open') return 'Still open';
  return phrase(value);
}

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

/** A hierarchy note that only restates the level, the code, or the parent link. */
export function committeeHierarchyNote(value: string): string {
  const text = value.trim();
  if (text === 'The source identifies a parent committee.') return '';
  if (/^Congress\.gov systemCode \S+: final two digits 00 identify a full committee; other digits identify a subcommittee\.$/.test(text)) return '';
  return text;
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
  const recorded = listedSourceStatus(row);
  const typeLabel = phrase(row.type);
  const typeText = typeLabel && (row.title || '').toLowerCase().includes(typeLabel.toLowerCase()) ? '' : typeLabel;
  const place = recordedPlace(row);
  const status = phrase(row.status);
  const notes = kind === 'data_issue' ? issueNotes(row) : [];
  const parts: RelatedPart[] = (kind === 'appearance'
    ? [row.position, row.organization, ...witnessNotes(row), ...notableRoles(row), participationNote(row), clock]
    : kind === 'meeting'
      ? [typeText, sourceTypeNote(row), clock, scheduleNote(row), congress, phrase(row.chamber), place, status, recorded]
      : kind === 'data_issue'
        ? [phrase(row.category), severityLabel(row.severity), issueStatusLabel(row.status), when.date, detectedNote(row), ...notes]
        : kind === 'committee_term'
          ? [committeeTypeLabel(row) === 'Type not recorded' ? '' : committeeTypeLabel(row), (row.title || '').toLowerCase().includes(committeeLevelLabel(row).toLowerCase()) ? '' : committeeLevelLabel(row), congress]
          : [clock, scheduleNote(row), status]
  ).filter(Boolean).map(text => ({ text, role: notes.includes(text) ? 'note' as const : kind === 'meeting' && place && text === place ? 'place' as const : (kind === 'meeting' || kind === 'data_issue') && status && text === status ? 'status' as const : undefined }));
  const sources = sourceCountNote(row);
  if (!sources) return parts;
  const noteIndex = parts.findIndex(part => part.role === 'note');
  return noteIndex < 0 ? [...parts, { text: sources }] : [...parts.slice(0, noteIndex), { text: sources }, ...parts.slice(noteIndex)];
}

/** Hide a time that only repeats the meeting already open. */
export function omitRepeatedWhen(parts: readonly RelatedPart[], meetingWhen: string): RelatedPart[] {
  if (!meetingWhen.trim()) return [...parts];
  return parts.filter(part => !repeatsRecordedWhen(part.text, meetingWhen));
}

/** Hide a Congress line that only repeats the committee term already open. */
export function omitRepeatedCongress(parts: readonly RelatedPart[], congress: unknown): RelatedPart[] {
  const name = congressName(congress);
  if (!name) return [...parts];
  return parts.filter(part => part.text !== name);
}

/** Hide a chamber line when the place already names that chamber. A room such as “Capitol, room S-219” keeps it. */
export function omitRepeatedChamber(parts: readonly RelatedPart[], chamber: unknown): RelatedPart[] {
  const name = phrase(chamber);
  if (!name) return [...parts];
  const place = parts.find(part => part.role === 'place')?.text || '';
  if (!place.toLowerCase().includes(name.toLowerCase())) return [...parts];
  return parts.filter(part => part.role === 'place' || part.text.toLowerCase() !== name.toLowerCase());
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
    const result = evidenceStateLabels[limits.evidence] || phrase(limits.evidence) || limits.evidence;
    notes.push(`Only meetings whose ${aspect} result is ${result.charAt(0).toLowerCase()}${result.slice(1)}.`);
  }
  return notes.length ? `These limits came from a coverage chart. ${notes.join(' ')}` : '';
}

/** Which day a date filter uses, and which records stay in that range. */
export function dateFilterReason(view: string, edge: 'from' | 'through'): string {
  const bound = edge === 'from' ? 'on or after' : 'on or before';
  if (view === 'gaps') return `Keep issues ${bound} this day. This uses the issue date, not the detected day shown on a row. Issues with a date in range stay in.`;
  if (view === 'witnesses') return `Keep witnesses ${bound} this day. Witnesses with a date in range stay in.`;
  return `Keep records ${bound} this day. A record with no date uses its scheduled day when it has one.`;
}

export function committeeTypeLabel(row: DisplayRow): string {
  const label = (value: string) => value.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
  if (row.committee_type && !['unknown', 'subcommittee'].includes(row.committee_type)) return label(row.committee_type);
  const subcommittee = row.committee_level === 'subcommittee' || row.committee_type === 'subcommittee' || parentCommitteeId(row);
  const inherited = [...new Set(row.committee_types || [])].filter((type): type is string => typeof type === 'string' && !['unknown', 'subcommittee'].includes(type));
  return subcommittee && inherited.length ? `${inherited.map(label).join(', ')}, like the parent committee` : 'Type not recorded';
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

/** A source status worth a second line. Upcoming already means the source said scheduled. */
export function listedSourceStatus(row: { status?: string | null; source_status?: string | null }): string {
  const source = row.source_status || '';
  if (!source || source === row.status) return '';
  if (source === 'unknown') return 'Status at the source not recorded';
  if (['upcoming', 'today'].includes(row.status || '') && ['scheduled', 'rescheduled'].includes(source)) return '';
  const label = phrase(source);
  return label ? `The source still says ${label.toLowerCase()}` : '';
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
