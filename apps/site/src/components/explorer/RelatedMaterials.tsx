import { useId, useRef, useState } from 'react';
import type { ExplorerReader, ExplorerRecordRef, RelatedResult } from './data-source';
import { fields, FileLinks, publicUrl, recordFiles, recordTitle, RecordingPlayer, type DetailRecord } from './RecordDetail';
import { documentSourceLabel } from './record-presentation.js';
import { materialCategory } from './related-materials.js';
import { PAGE_SIZE, Pagination, RequestMessage, useRequest } from './request-state';
import './RelatedMaterials.css';

type Props = { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void };
const integer = (value: number) => value.toLocaleString('en-US');

/** Recordings and documents keep independent filters and pages. */
export default function RelatedMaterials(props: Props) {
  return <>{(['recording', 'document'] as const).map(materialType => <MaterialSection key={`${props.selected.kind}/${props.selected.id}/${materialType}`} {...props} materialType={materialType} />)}</>;
}

function MaterialSection({ reader, selected, onSelect, materialType }: Props & { materialType: 'document' | 'recording' }) {
  const [filter, setFilter] = useState({ category: '', page: 0 });
  const id = useId();
  const label = materialType === 'recording' ? 'Recordings' : 'Documents';
  const [state, retry] = useRequest<RelatedResult>(signal => reader.getRelated(selected, {
    kind: 'material', materialType, category: filter.category, offset: filter.page * PAGE_SIZE, limit: PAGE_SIZE, signal,
  }), [reader, selected.kind, selected.id, materialType, filter.category, filter.page]);
  // Keep the filter mounted while loading so keyboard focus stays on it.
  const lastResult = useRef<RelatedResult | null>(null);
  if (state.status === 'ready') lastResult.current = state.value;
  const result = lastResult.current;
  if (!result) return state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun={label.toLowerCase()} /> : null;
  const { records, total, offset, categories = [] } = result;
  const allCount = categories.reduce((sum, category) => sum + category.count, 0);
  if (!allCount && !total && !filter.category) return null;
  const groups = new Map<string, DetailRecord[]>();
  for (const record of records) {
    const category = materialCategory(record);
    groups.set(category, [...(groups.get(category) || []), record]);
  }
  return <section className="explorer-detail-section" aria-labelledby={id}>
    <h3 id={id}>{label} <span className="explorer-muted">({integer(allCount || total)})</span></h3>
    {materialType === 'document' && categories.length > 1 ? <label className="explorer-related-filter">Document category
      <select value={filter.category} onChange={event => setFilter({ category: event.target.value, page: 0 })}>
        <option value="">All categories ({integer(allCount)})</option>
        {categories.map(category => <option key={category.label} value={category.label}>{category.label} ({integer(category.count)})</option>)}
      </select>
    </label> : null}
    {state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun={label.toLowerCase()} /> : <>{[...groups].map(([category, items]) => <div className="explorer-material-group" key={category}>
      {materialType === 'document' ? <h4>{category} <span className="explorer-muted">({integer(categories.find(item => item.label === category)?.count || items.length)})</span></h4> : null}
      <ul className="explorer-related-list">{items.map(record => <MaterialRow key={record.id} record={record} onSelect={onSelect} />)}</ul>
    </div>)}
    {!records.length ? <p>No documents match this category.</p> : null}
    {total > PAGE_SIZE ? <Pagination total={total} offset={offset} count={records.length} onPage={page => setFilter(current => ({ ...current, page }))} /> : null}</>}
  </section>;
}

function MaterialRow({ record, onSelect }: { record: DetailRecord; onSelect: Props['onSelect'] }) {
  const row = fields(record), files = recordFiles(record);
  const title = row.type === 'recording' ? 'Watch recording' : recordTitle(record);
  return <li>
    {files.length ? <a href={publicUrl(files[0].url)} target="_blank" rel="noreferrer">{title} ↗</a> : <span>{title}</span>}
    {files.length > 1 ? <FileLinks record={record} /> : null}
    {documentSourceLabel(row) ? <span className="explorer-row-meta">{documentSourceLabel(row)}</span> : null}
    {Array.isArray(row.facts) ? <span className="explorer-row-meta">{row.facts.map(fields).filter(fact => !['medium', 'coverage', 'production'].includes(String(fact.label))).map(fact => `${fact.label}: ${fact.value}`).join(' · ')}</span> : null}
    <button className="explorer-text-button explorer-row-meta" onClick={() => onSelect(record)}>Details & source</button>
    <RecordingPlayer record={record} />
  </li>;
}
