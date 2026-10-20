import { useState, type ReactNode } from 'react';
import { filenameManifestUrl } from '../reader/filenames/publication.ts';
import { contentHash } from '../browse/filename-presentation.ts';
import { categoryNote, collapseRepeatedFacts, committeeLevelLabel, committeeTypeLabel, congressName, disagreementSummary, distinctRecordedFacts, documentSourceLabel, factLabel, fileLinkName, filePartNote, meetingStatusNote, orderRecordedFiles, parentCommitteeId, providerLabel, recordedTitlePreview, recordedWhen, recordingEmbedUrl, recordingIdentity, savedCopyHref, scheduleNote, sourceFacts, sourceLinks, sourcePageUrl, sourceTypeNote, type SourceLink } from '../browse/record-presentation.ts';
import type { ExplorerRecordRef, LoadedRecord } from '../reader/data-source.ts';

export type DetailRecord = LoadedRecord;
type Fields = Record<string, unknown>;
export function fields(value: unknown): Fields {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Fields : {};
}
export function words(value: unknown): string {
  if (value === 'business') return 'Business meeting';
  return typeof value === 'string' ? value.replaceAll('_', ' ') : '';
}
export function enumLabel(value: unknown): string {
  const text = words(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}
export function documentType(record: unknown): string {
  const row = fields(record);
  return typeof row.document_type === 'string' ? row.document_type : '';
}
export function recordTitle(value: unknown): string {
  const row = fields(value);
  if (row.kind === 'source_record') {
    const recorded = fields(row.payload).title;
    if (typeof recorded === 'string' && recorded.trim()) return recorded.trim();
    return String(row.provider || 'Source evidence');
  }
  const title = row.title || row.summary || fields(row.name).display || row.name;
  if (title && title !== '(Untitled source record)') return String(title);
  const label = words(row.category && row.category !== 'unknown' ? row.category : row.type || row.kind);
  return label ? label[0].toUpperCase() + label.slice(1) : 'Untitled record';
}
export function publicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
const LABELS: Record<string, string> = { meeting: 'Meeting', committee_term: 'Committee', material: 'Document or recording', appearance: 'Witness', data_issue: 'Known issue', source_record: 'Source evidence' };

function kindLabel(record: DetailRecord): string {
  const row = fields(record);
  if (record.kind === 'material') {
    const typed = documentType(record);
    if (typed) return typed;
    if (row.type === 'recording') return 'Recording';
    if (row.type === 'text') return 'Text product';
    if (row.type === 'document') return 'Document';
  }
  if (record.kind === 'meeting' && row.type && row.type !== 'unknown') return enumLabel(row.type);
  if (record.kind === 'data_issue' && row.category && row.category !== 'unknown') return enumLabel(row.category);
  return LABELS[record.kind] || words(record.kind);
}

export function recordFiles(record: unknown): Fields[] {
  const row = fields(record);
  if (row.type === 'recording') {
    const url = publicUrl(row.recording_url);
    if (!url) return [];
    const files = Array.isArray(row.files) ? row.files.map(fields) : [];
    const identity = recordingIdentity(url);
    const match = files.find(file => publicUrl(file.url) === url) || files.find(file => identity && recordingIdentity(String(file.url || '')) === identity) || {};
    return [{ ...match, url, role: 'player' }];
  }
  const files = row.files;
  if (!Array.isArray(files)) return [];
  const seen = new Set<string>();
  const listed = files.map(fields).filter(file => {
    const url = publicUrl(file.url);
    if (!url || seen.has(url)) return false;
    seen.add(url); return true;
  });
  return orderRecordedFiles(listed);
}
const savedCopyManifest = import.meta.env.PUBLIC_FILENAME_MANIFEST_URL || filenameManifestUrl;

export function FileLinks({ record }: { record: unknown }) {
  const files = recordFiles(record);
  if (!files.length) return null;
  return <div className="explorer-file-links">{files.map(file => {
    const saved = savedCopyHref(file, savedCopyManifest);
    const label = fileLinkName(file);
    const savedLabel = file.label && file.label !== 'unknown' ? ` (${words(file.label)})` : '';
    const hash = contentHash(typeof file.saved_copy_sha256 === 'string' ? file.saved_copy_sha256 : typeof file.sha256 === 'string' ? file.sha256 : '');
    const meta = [file.version && file.version !== 'unknown' ? words(file.version) : '', typeof file.published_at === 'string' ? file.published_at : '', typeof file.media_type === 'string' ? file.media_type : '', hash ? `SHA-256 ${hash}` : ''].filter(Boolean).join(' · ');
    return <span key={String(file.url)}>
      <a href={publicUrl(file.url)} target="_blank" rel="noreferrer">{label} ↗</a>
      {saved ? <> <a href={saved}>Open saved copy{savedLabel}</a></> : null}
      {meta ? <span className="explorer-row-meta">{meta}</span> : null}
    </span>;
  })}</div>;
}
export function RecordingPlayer({ record }: { record: unknown }) {
  const url = recordingEmbedUrl(fields(record));
  if (!url) return null;
  return <iframe className="explorer-recording-player" src={url} title={`Recording: ${recordTitle(record)}`}
    loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowFullScreen
    referrerPolicy="strict-origin-when-cross-origin" />;
}
const evidenceLabels: Record<string, string> = {
  observed: 'Observed in a checked source',
  reported: 'Reported by the source',
  curated: 'Curated in this archive',
  derived: 'Derived from other recorded fields',
  inferred: 'Inferred match; needs verification',
  not_found_in_checked_scope: 'Not found in the sources checked',
  error: 'Source check failed',
  blocked: 'Source check blocked',
  not_applicable: 'Not applicable to this meeting',
  unknown: 'Unknown',
  unchecked: 'Not checked',
};

function EvidenceNotes({ states }: { states: Fields }) {
  const entries = Object.entries(states).filter(([, state]) => state);
  if (!entries.length) return null;
  return <dl className="explorer-facts" aria-label="Recorded evidence">{entries.map(([aspect, state]) => <div key={aspect}><dt>{words(aspect)}</dt><dd>{evidenceLabels[String(state)] || words(state)}</dd></div>)}</dl>;
}

function RawRecord({ record }: { record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>View every published field<span className="explorer-field-reason">Includes fields left off the summary above.</span></summary>
    {open ? <pre><code>{JSON.stringify(record, null, 2)}</code></pre> : null}</details>;
}

export function SourceLinkGroups({ links }: { links: readonly SourceLink[] }) {
  const groups: { name: string; links: SourceLink[] }[] = [];
  for (const link of links) {
    const group = groups.find(item => item.name === link.group);
    if (group) group.links.push(link);
    else groups.push({ name: link.group, links: [link] });
  }
  if (!groups.length) return null;
  return <div className="explorer-link-groups">{groups.map(group => <section className="explorer-link-group" key={group.name}><h5>{group.name}</h5><ul className="explorer-related-list">{group.links.map((link, linkIndex) => {
    const href = publicUrl(link.href);
    return <li key={`${link.href}/${linkIndex}`}>{href ? <a href={href} target="_blank" rel="noreferrer">{link.label} ↗</a> : <span>{link.label}</span>}</li>;
  })}</ul></section>)}</div>;
}

function FactLines({ label, value }: { label: string; value: string }) {
  const prose = label === 'Description' || label === 'Match note' || label === 'Explanation' || label === 'Note';
  if (!prose) return <>{value.split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</>;
  const note = recordedTitlePreview(value);
  const name = label.toLowerCase();
  return <>
    <span>{note.preview}</span>
    {note.rest.length ? <details><summary>Rest of the {name}<span className="explorer-field-reason">The rest of the recorded {name}.</span></summary>{note.rest.map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</details> : null}
  </>;
}

/** A short fact sheet; source evidence is an optional disclosure. */
export function RecordDetail({ record, onSelect, sourceEvidence, catalogEvidence, committeeLabels, affectedAction, meetingAction }: { record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void; sourceEvidence?: ReactNode; catalogEvidence?: ReactNode; committeeLabels?: Readonly<Record<string, string>>; affectedAction?: ReactNode; meetingAction?: ReactNode }) {
  const row = fields(record);
  const when = recordedWhen(row);
  const committees = (Array.isArray(row.committee_ids) ? row.committee_ids : []).map(id => committeeLabels?.[String(id)]).filter(Boolean);
  const facts = [
    ['Date', (row.date || '').slice(0, 10) || null], ['Scheduled time', (row.date || '').slice(0, 10) && when.time ? when.time : null], ['Meeting schedule', scheduleNote(row).replace(/^Scheduled /, '') || null], ['Congress', congressName(row.congress) || null], ['Chamber', row.chamber],
    ['Committees', committees.length ? committees.join(' · ') : null],
    ['Known issues', typeof row.issue_count === 'number' && row.issue_count > 0 ? row.issue_count : null],
    ['Access', row.access],
    ['Recorded status', row.source_status && row.source_status !== row.status ? row.source_status : null],
    ['Committee type', row.kind === 'committee_term' ? committeeTypeLabel(row) : null],
    ['Source committee type', row.source_committee_type && (String(row.source_committee_type).toLowerCase().replaceAll(' ', '_') !== row.committee_type || row.committee_type === 'subcommittee') ? row.source_committee_type : null],
    ['Committee level', committeeLevelLabel(row) || null],
    [documentType(record) ? 'Document type' : 'Type', row.kind === 'committee_term' ? null : documentType(record) || row.type || row.meeting_type], ['Status', row.status], ['Category', row.kind === 'material' ? categoryNote(row) || null : row.category],
    ['Source collection', Array.isArray(row.source_document_groups) && row.source_document_groups.length ? documentSourceLabel(row) : null],
    ['Volume part', filePartNote(row) || null],
    ['Committee code', row.committee_code],
    ['Position', row.position], ['Organization', row.organization], ['Participation', row.participation],
    ['Roles', Array.isArray(row.roles) && row.roles.length ? row.roles.map(role => enumLabel(role)).join(' · ') : null],
    ['Meeting status', meetingStatusNote(row) ? row.meeting_status : null],
    ['Severity', row.severity],
    ['Issue history', row.selection === 'retained_history' ? 'Retained from an earlier input. Not present in the latest inputs.' : null],
    ['Provider', providerLabel(typeof row.provider === 'string' ? row.provider : '') || null], ['Retrieved', row.retrieved_at],
    ['Active from', fields(row.active).start], ['Active through', fields(row.active).end],
    ['Official website or archive', row.website],
    ...distinctRecordedFacts(Array.isArray(row.facts) ? row.facts as { label?: string | null; value?: string | null }[] : []).filter(([label, value]) => label !== 'Hierarchy definition' && !(label === 'medium' && value === 'video' && row.type === 'recording') && !(label === 'Source type' && !sourceTypeNote(row))),
  ].filter(([label, value]) => value !== null && value !== undefined && value !== '' && (value !== 'unknown' || label === 'Meeting status'));
  if (record.kind === 'source_record') {
    const seen = new Set(facts.map(([label]) => String(label).toLowerCase()));
    for (const [label, value] of sourceFacts(record)) if (!seen.has(label.toLowerCase())) facts.push([label, value]);
  }
  const shownFacts: [unknown, unknown][] = [];
  for (let index = 0; index < facts.length; index++) {
    const [label, value] = facts[index];
    if (String(label).toLowerCase() !== 'selected value') { shownFacts.push([label, value]); continue; }
    const alternatives: string[] = [];
    let next = index + 1;
    while (next < facts.length && /^alternative \d+$/i.test(String(facts[next][0]))) { alternatives.push(String(facts[next][1])); next++; }
    const summary = disagreementSummary(String(value), alternatives);
    if (!summary) { shownFacts.push([label, value]); continue; }
    shownFacts.push(['Recorded difference', summary.join('\n')]);
    index = next - 1;
  }
  const factNames = shownFacts.map(([label]) => String(label));
  for (let index = 0; index < shownFacts.length; index++) shownFacts[index] = [factLabel(String(shownFacts[index][0]), factNames), shownFacts[index][1]];
  const collapsedFacts = collapseRepeatedFacts(shownFacts);
  const files = Array.isArray(row.files) ? row.files : [];
  const explanation = row.explanation || fields(row.provenance).explanation;
  const sourceUrl = publicUrl(sourcePageUrl(row.url));
  const parentId = record.kind === 'committee_term' ? parentCommitteeId(row) : '';
  const parentName = parentId ? committeeLabels?.[parentId] || '' : '';
  const affected = record.kind !== 'data_issue' ? null
    : ['meeting', 'material', 'appearance', 'committee_term', 'source_record'].includes(String(row.subject_kind))
      ? {kind: String(row.subject_kind), id: String(row.subject_id)}
      : row.meeting_id ? {kind: 'meeting', id: String(row.meeting_id)} : null;
  return <>
    <p className="explorer-record-kind">{kindLabel(record)}</p>
    <h2 id="explorer-detail-title">{recordTitle(record)}</h2>
    <RecordingPlayer record={record} />
    <FileLinks record={record} />
    {sourceUrl ? <p><a href={sourceUrl} target="_blank" rel="noreferrer">Open original source ↗</a></p> : null}
    {collapsedFacts.length ? <dl className="explorer-facts">{collapsedFacts.map(([label, value], i) => <div key={i}><dt>{String(label)}</dt><dd>{label === 'Official website or archive' && publicUrl(value)
      ? <a href={publicUrl(value)} target="_blank" rel="noreferrer">Visit website or archive ↗</a>
      : ['Type', 'Status', 'Recorded status', 'Meeting status', 'Severity', 'Category', 'Chamber', 'Participation', 'medium', 'coverage', 'production', 'Access'].includes(String(label)) ? enumLabel(value) : <FactLines label={String(label)} value={String(value)} />}</dd></div>)}</dl> : null}
    {record.kind === 'meeting' ? <EvidenceNotes states={fields(row.evidence_states)} /> : null}
    {record.kind === 'source_record' ? <SourceLinkGroups links={sourceLinks(record).links} /> : null}
    {explanation ? <p className="explorer-note">{String(explanation)}</p> : null}
    {parentId ? <p><button className="explorer-text-button" aria-label={parentName ? `Open the parent committee ${parentName}` : 'Open the parent committee recorded for this subcommittee'} onClick={() => onSelect({kind: 'committee_term', id: parentId})}>{parentName ? `Subcommittee of ${parentName} →` : 'View parent committee →'}</button></p> : null}
    {record.kind === 'material' && !files.length ? <p className="explorer-note">{row.type === 'recording' ? 'No recording is available in the collected sources.' : 'No file link in the collected sources.'}</p> : null}
    {meetingAction !== undefined ? meetingAction : row.meeting_id && !['meeting', 'material', 'data_issue'].includes(record.kind) ? <p><button className="explorer-text-button" aria-label="Open the meeting this record belongs to" onClick={() => onSelect({ kind: 'meeting', id: String(row.meeting_id) })}>View meeting →</button></p> : null}
    {affectedAction !== undefined ? affectedAction : affected ? <p><button className="explorer-text-button" aria-label="Open the record this issue describes" onClick={() => onSelect(affected)}>View affected record →</button></p> : null}
    {catalogEvidence}
    {sourceEvidence}
    <RawRecord key={`${record.kind}/${record.id}`} record={record} />
  </>;
}
