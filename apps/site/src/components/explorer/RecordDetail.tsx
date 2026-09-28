import { useState } from 'react';
import type { ExplorerRecord, ExplorerRecordRef, ExplorerSourceRecord } from './data-source';

export type DetailRecord = ExplorerRecord | ExplorerSourceRecord;
type Fields = Record<string, unknown>;
const OMIT_FIELDS = new Set(['id', 'kind', 'provenance', 'field_evidence', 'payload', 'identifiers']);

export function fields(value: unknown): Fields {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Fields : {};
}
export function words(value: unknown): string {
  return typeof value === 'string' ? value.replaceAll('_', ' ') : '';
}
export function recordTitle(value: unknown): string {
  const row = fields(value);
  for (const key of ['title', 'summary', 'label', 'designation', 'question', 'description']) {
    if (typeof row[key] === 'string' && row[key]) return row[key];
  }
  if (typeof row.name === 'string' && row.name) return row.name;
  if (typeof fields(row.name).display === 'string') return fields(row.name).display as string;
  if (row.kind === 'source_record') return `${String(row.provider)} · ${String(fields(row.identifier).value ?? 'source observation')}`;
  if (row.kind === 'assessment') return `${words(row.aspect)} · ${words(row.status)}`;
  if (row.kind === 'material_link') return `${words(row.role) || 'Material'} association · ${words(row.coverage) || 'unknown'} coverage`;
  if (row.kind === 'occurrence') return `${String(fields(row.actual_start).date || fields(row.scheduled_start).date || 'Date unrecorded')} · ${words(row.status) || 'status unknown'}`;
  if (row.kind === 'representation') return String(row.format_label || row.media_type || 'File or player');
  if (row.kind === 'material_version') return `Edition or revision${fields(row.published_at).date ? ` · ${String(fields(row.published_at).date)}` : ''}`;
  if (row.kind === 'material') {
    const details = fields(row.details);
    const description = words(details.category && details.category !== 'unknown' ? details.category : details.type) || 'Material';
    return `${description[0].toUpperCase()}${description.slice(1)} (title unrecorded)`;
  }
  return `${words(row.kind) || 'Record'}${row.number ? ` ${String(row.number)}` : ''}`;
}
export function publicUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined;
  } catch { return undefined; }
}

function Value({ value, onSelect, depth = 0 }: { value: unknown; onSelect: (ref: ExplorerRecordRef) => void; depth?: number }) {
  if (value === null || value === undefined) return <span className="explorer-unknown">Not established</span>;
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  if (typeof value === 'string' || typeof value === 'number') {
    const url = publicUrl(value);
    return url ? <a href={url} target="_blank" rel="noreferrer">{String(value)}</a> : <>{String(value)}</>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="explorer-unknown">None recorded</span>;
    return <ul className="explorer-values">{value.map((item, index) => <li key={index}><Value value={item} onSelect={onSelect} depth={depth + 1} /></li>)}</ul>;
  }
  const obj = fields(value);
  if (typeof obj.kind === 'string' && typeof obj.id === 'string') {
    return <button className="explorer-text-button" onClick={() => onSelect({ kind: String(obj.kind), id: String(obj.id) })}>Open {words(obj.kind)} →</button>;
  }
  if (typeof obj.date === 'string') {
    return <>{obj.approximate ? 'About ' : ''}{obj.date}{obj.time ? ` ${String(obj.time)}` : ''}{obj.timezone ? ` (${String(obj.timezone)})` : obj.time ? ' (time zone unrecorded)' : ''}</>;
  }
  if (Array.isArray(obj.citations) && typeof obj.basis === 'string') {
    return <details><summary>{words(obj.basis)} evidence and sources</summary><dl className="explorer-nested">{Object.entries(obj).filter(([key, item]) => key !== 'basis' && item !== null && item !== undefined && item !== '').map(([key, item]) => <div key={key}><dt>{words(key)}</dt><dd><Value value={item} onSelect={onSelect} depth={depth + 1} /></dd></div>)}</dl></details>;
  }
  if (fields(obj.source).kind === 'source_record' && typeof fields(obj.source).id === 'string') {
    return <><button className="explorer-text-button" onClick={() => onSelect({ kind: 'source_record', id: String(fields(obj.source).id) })}>Open source observation →</button>{obj.selector ? <span className="explorer-row-meta">{words(obj.selector_type)}: {String(obj.selector)}</span> : null}{obj.quote ? <blockquote>{String(obj.quote)}</blockquote> : null}</>;
  }
  if (depth > 4) return <span>See record data below</span>;
  return <dl className="explorer-nested">{Object.entries(obj).map(([key, item]) => <div key={key}><dt>{words(key)}</dt><dd><Value value={item} onSelect={onSelect} depth={depth + 1} /></dd></div>)}</dl>;
}

function RawRecord({ record }: { record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Record data and exact identifiers</summary>
    {open ? <pre><code>{JSON.stringify(record, null, 2)}</code></pre> : null}
  </details>;
}

/** Human-readable domain fields. Serialization and source retrieval stay in the injected reader. */
export function RecordDetail({ record, onSelect }: { record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void }) {
  const row = fields(record);
  const provenance = fields(row.provenance);
  const citations = Array.isArray(provenance.citations) ? provenance.citations : [];
  const fieldEvidence = Array.isArray(row.field_evidence) ? row.field_evidence : [];
  const identifiers = Array.isArray(row.identifiers) ? row.identifiers : [];
  return <>
    <p className="explorer-record-kind">{words(record.kind)}{provenance.basis ? ` · ${words(provenance.basis)} evidence` : ''}</p>
    <h2 id="explorer-detail-title">{recordTitle(record)}</h2>
    {record.kind === 'appearance' ? <p className="explorer-note">A source-listed appearance. A listed name does not establish testimony or a shared identity with people in other meetings.</p> : null}
    {record.kind === 'meeting' ? <p className="explorer-note">A source entry can describe a scheduled, postponed or canceled proceeding. Check the dated occurrences below before treating it as a hearing held.</p> : null}
    {record.kind === 'material' || record.kind === 'representation' ? <p className="explorer-note">A published link does not establish accessible or retained bytes. Associations and their coverage are recorded separately.</p> : null}
    {record.kind === 'source_record' ? <p className="explorer-note">This retained observation preserves the supplied evidence. Import time is not a live source check.</p> : null}
    <dl className="explorer-facts">{Object.entries(row).filter(([key]) => !OMIT_FIELDS.has(key)).map(([key, value]) => <div key={key}>
      <dt>{words(key)}</dt><dd><Value value={value} onSelect={onSelect} /></dd>
    </div>)}</dl>
    {identifiers.length ? <section className="explorer-detail-section"><h3>Provider identifiers</h3><Value value={identifiers} onSelect={onSelect} /></section> : null}
    {citations.length ? <section className="explorer-detail-section"><h3>Evidence and sources</h3>
      {typeof provenance.explanation === 'string' ? <p>{provenance.explanation}</p> : null}
      {provenance.method ? <p className="explorer-muted">Method: {String(fields(provenance.method).name)} · {String(fields(provenance.method).version)}</p> : null}
      <ul className="explorer-citations">{citations.map((citation, index) => {
        const item = fields(citation); const source = fields(item.source);
        return <li key={index}><button className="explorer-text-button" onClick={() => onSelect({ kind: String(source.kind), id: String(source.id) })}>Source observation {index + 1} →</button>
          {item.selector ? <span className="explorer-muted">{words(item.selector_type)}: {String(item.selector)}</span> : null}
          {item.quote ? <blockquote>{String(item.quote)}</blockquote> : null}</li>;
      })}</ul>
    </section> : null}
    {fieldEvidence.length ? <section className="explorer-detail-section"><h3>Field decisions and alternative values</h3><Value value={fieldEvidence} onSelect={onSelect} /></section> : null}
    <RawRecord key={`${record.kind}/${record.id}`} record={record} />
  </>;
}
