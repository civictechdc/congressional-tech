import { useState } from 'react';
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
function RawRecord({ record }: { record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>View record data</summary>
    {open ? <pre><code>{JSON.stringify(record, null, 2)}</code></pre> : null}</details>;
}

/** A short fact sheet; source evidence is an optional disclosure. */
export function RecordDetail({ record, onSelect }: { record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void }) {
  const row = fields(record);
  const facts = [
    ['Date', row.date], ['Congress', row.congress], ['Chamber', row.chamber],
    ['Type', row.type || row.meeting_type], ['Status', row.status], ['Category', row.category],
    ['Position', row.position], ['Organization', row.organization], ['Participation', row.participation],
    ['Provider', row.provider], ['Retrieved', row.retrieved_at],
    ...(Array.isArray(row.facts) ? row.facts.map(fact => [fields(fact).label, fields(fact).value]) : []),
  ].filter(([, value]) => value !== null && value !== undefined && value !== '' && value !== 'unknown');
  const sourceIds = Array.isArray(row.source_ids) ? row.source_ids : [];
  const files = Array.isArray(row.files) ? row.files : [];
  const sourceUrl = publicUrl(row.url);
  return <>
    <p className="explorer-record-kind">{LABELS[record.kind] || words(record.kind)}</p>
    <h2 id="explorer-detail-title">{recordTitle(record)}</h2>
    <FileLinks record={record} />
    {sourceUrl ? <p><a href={sourceUrl} target="_blank" rel="noreferrer">Open original source ↗</a></p> : null}
    {facts.length ? <dl className="explorer-facts">{facts.map(([label, value], i) => <div key={i}><dt>{String(label)}</dt><dd>{typeof value === 'string' ? words(value) : String(value)}</dd></div>)}</dl> : null}
    {record.kind === 'meeting' ? Object.entries(fields(row.evidence_states)).filter(([, state]) => ['inferred', 'error', 'blocked', 'not_found_in_checked_scope'].includes(String(state))).map(([aspect, state]) => <p className="explorer-note" key={aspect}>{words(aspect)}: {state === 'inferred' ? 'inferred match; needs verification' : state === 'not_found_in_checked_scope' ? 'not found in the sources checked' : state === 'error' ? 'source check failed' : 'source check blocked'}.</p>) : null}
    {row.explanation ? <p className="explorer-note">{String(row.explanation)}</p> : null}
    {record.kind === 'material' && !files.length ? <p className="explorer-note">{row.type === 'recording' ? 'No recording is available to display for this meeting yet.' : 'No file link in the collected sources.'}</p> : null}
    {row.meeting_id && record.kind !== 'meeting' ? <p><button className="explorer-text-button" onClick={() => onSelect({ kind: 'meeting', id: String(row.meeting_id) })}>View meeting →</button></p> : null}
    {record.kind === 'data_issue' && ['meeting', 'material', 'appearance', 'committee_term'].includes(String(row.subject_kind)) ? <p><button className="explorer-text-button" onClick={() => onSelect({ kind: String(row.subject_kind), id: String(row.subject_id) })}>View affected record →</button></p> : null}
    {sourceIds.length ? <details className="explorer-detail-section"><summary>Source evidence ({sourceIds.length})</summary>
      <ul className="explorer-values">{sourceIds.map((id, i) => <li key={String(id)}><button className="explorer-text-button" onClick={() => onSelect({ kind: 'source_record', id: String(id) })}>View source {i + 1} →</button></li>)}</ul>
    </details> : null}
    <RawRecord key={`${record.kind}/${record.id}`} record={record} />
  </>;
}
