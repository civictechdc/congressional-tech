import { useState, type ReactNode } from 'react';
import { committeeTypeLabel, documentSourceLabel, recordingEmbedUrl, sourcePageUrl } from './record-presentation.js';
import type { ExplorerRecord, ExplorerRecordRef, ExplorerSourceRecord } from './data-source';

export type DetailRecord = ExplorerRecord | ExplorerSourceRecord;
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
  if (row.kind === 'source_record') return String(row.provider || 'Source evidence');
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

export function recordFiles(record: unknown): Fields[] {
  const row = fields(record);
  if (row.type === 'recording') return publicUrl(row.recording_url) ? [{url: row.recording_url, role: 'player'}] : [];
  const files = row.files;
  if (!Array.isArray(files)) return [];
  const seen = new Set<string>();
  return files.map(fields).filter(file => {
    const url = publicUrl(file.url);
    if (!url || seen.has(url)) return false;
    seen.add(url); return true;
  });
}
export function FileLinks({ record }: { record: unknown }) {
  const files = recordFiles(record);
  if (!files.length) return null;
  return <div className="explorer-file-links">{files.map(file => <a key={String(file.url)} href={publicUrl(file.url)} target="_blank" rel="noreferrer">{file.role === 'player' || file.role === 'stream' ? 'Watch recording' : (file.label !== 'unknown' && words(file.label)) || 'Open file'} ↗</a>)}</div>;
}
export function RecordingPlayer({ record }: { record: unknown }) {
  const url = recordingEmbedUrl(fields(record));
  if (!url) return null;
  return <iframe className="explorer-recording-player" src={url} title={`Recording: ${recordTitle(record)}`}
    loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowFullScreen
    referrerPolicy="strict-origin-when-cross-origin" />;
}
function RawRecord({ record }: { record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>View record data</summary>
    {open ? <pre><code>{JSON.stringify(record, null, 2)}</code></pre> : null}</details>;
}

/** A short fact sheet; source evidence is an optional disclosure. */
export function RecordDetail({ record, onSelect, sourceEvidence }: { record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void; sourceEvidence?: ReactNode }) {
  const row = fields(record);
  const facts = [
    ['Date', row.date], ['Congress', row.congress], ['Chamber', row.chamber], ['Access', row.access],
    ['Committee type', row.kind === 'committee_term' ? committeeTypeLabel(row) : null],
    ['Source committee type', row.source_committee_type && (String(row.source_committee_type).toLowerCase().replaceAll(' ', '_') !== row.committee_type || row.committee_type === 'subcommittee') ? row.source_committee_type : null],
    ['Committee level', row.committee_level === 'full' ? 'Full committee' : row.committee_level === 'subcommittee' ? 'Subcommittee' : null],
    [documentType(record) ? 'Document type' : 'Type', row.kind === 'committee_term' ? null : documentType(record) || row.type || row.meeting_type], ['Status', row.status], ['Category', documentType(record) ? null : row.category],
    ['Source collection', Array.isArray(row.source_document_groups) && row.source_document_groups.length ? `${documentSourceLabel(row)} (${row.source_document_groups.join(', ')})` : null],
    ['Position', row.position], ['Organization', row.organization], ['Participation', row.participation],
    ['Provider', row.provider], ['Retrieved', row.retrieved_at],
    ['Active from', fields(row.active).start], ['Active through', fields(row.active).end],
    ['Official website or archive', row.website],
    ...(Array.isArray(row.facts) ? row.facts.filter(fact => !['Committee hierarchy', 'Hierarchy definition'].includes(String(fields(fact).label))).map(fact => [fields(fact).label, fields(fact).value]) : []),
  ].filter(([, value]) => value !== null && value !== undefined && value !== '' && value !== 'unknown');
  const files = Array.isArray(row.files) ? row.files : [];
  const explanation = row.explanation || fields(row.provenance).explanation;
  const sourceUrl = publicUrl(sourcePageUrl(row.url));
  const affected = record.kind !== 'data_issue' ? null
    : ['meeting', 'material', 'appearance', 'committee_term', 'source_record'].includes(String(row.subject_kind))
      ? {kind: String(row.subject_kind), id: String(row.subject_id)}
      : row.meeting_id ? {kind: 'meeting', id: String(row.meeting_id)} : null;
  return <>
    <p className="explorer-record-kind">{LABELS[record.kind] || words(record.kind)}</p>
    <h2 id="explorer-detail-title">{recordTitle(record)}</h2>
    <RecordingPlayer record={record} />
    <FileLinks record={record} />
    {sourceUrl ? <p><a href={sourceUrl} target="_blank" rel="noreferrer">Open original source ↗</a></p> : null}
    {facts.length ? <dl className="explorer-facts">{facts.map(([label, value], i) => <div key={i}><dt>{String(label)}</dt><dd>{label === 'Official website or archive' && publicUrl(value)
      ? <a href={publicUrl(value)} target="_blank" rel="noreferrer">Visit website or archive ↗</a>
      : ['Type', 'Status', 'Category', 'Chamber', 'Participation', 'medium', 'coverage', 'production', 'Access'].includes(String(label)) ? enumLabel(value) : String(value)}</dd></div>)}</dl> : null}
    {record.kind === 'meeting' ? Object.entries(fields(row.evidence_states)).filter(([, state]) => ['inferred', 'error', 'blocked', 'not_found_in_checked_scope'].includes(String(state))).map(([aspect, state]) => <p className="explorer-note" key={aspect}>{words(aspect)}: {state === 'inferred' ? 'inferred match; needs verification' : state === 'not_found_in_checked_scope' ? 'not found in the sources checked' : state === 'error' ? 'source check failed' : 'source check blocked'}.</p>) : null}
    {explanation ? <p className="explorer-note">{String(explanation)}</p> : null}
    {record.kind === 'committee_term' && (row.parent_committee_id || fields(row.parent).id) ? <p><button className="explorer-text-button" onClick={() => onSelect({kind: 'committee_term', id: String(row.parent_committee_id || fields(row.parent).id)})}>View parent committee →</button></p> : null}
    {record.kind === 'material' && !files.length ? <p className="explorer-note">{row.type === 'recording' ? 'No recording is available in the collected sources.' : 'No file link in the collected sources.'}</p> : null}
    {row.meeting_id && !['meeting', 'material', 'data_issue'].includes(record.kind) ? <p><button className="explorer-text-button" onClick={() => onSelect({ kind: 'meeting', id: String(row.meeting_id) })}>View meeting →</button></p> : null}
    {affected ? <p><button className="explorer-text-button" onClick={() => onSelect(affected)}>View affected record →</button></p> : null}
    {sourceEvidence}
    <RawRecord key={`${record.kind}/${record.id}`} record={record} />
  </>;
}
