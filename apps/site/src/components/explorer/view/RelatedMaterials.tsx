import { useEffect, useId, useRef, useState } from 'react';
import type { ExplorerReader, ExplorerRecordRef, RelatedResult } from '../reader/data-source.ts';
import { fields, FileLinks, publicUrl, recordFiles, recordTitle, RecordingPlayer, type DetailRecord } from './RecordDetail';
import { categoryNote, documentSourceLabel, filePartNote, linkedMeetingIds, meetingStatusNote, publishedNote, recordedAddressNames, recordedFileNames, recordedTitlePreview, recordedWhen, recordingIdentity, scheduleNote, sourceCountNote } from '../browse/record-presentation.ts';
import { materialCategory, relatedMaterialTitle, sameRecordedTitle } from '../browse/related-materials.ts';
import { PAGE_SIZE, Pagination, RequestMessage, integer, useRequest } from './request-state';
import './RelatedMaterials.css';

type Props = { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void };

/** Recordings and documents keep independent filters and pages. */
export default function RelatedMaterials(props: Props) {
  return <>{(['recording', 'document'] as const).map(materialType => <MaterialSection key={`${props.selected.kind}/${props.selected.id}/${materialType}`} {...props} materialType={materialType} />)}</>;
}

function useRelatedMeetingTitles(reader: ExplorerReader, records: readonly DetailRecord[], currentMeetingId: string): ReadonlyMap<string, string> {
  const cache = useRef(new Map<string, string>());
  const [, refresh] = useState(0);
  const missing = [...new Set(records.flatMap(record => linkedMeetingIds(fields(record))))].filter(id => id !== currentMeetingId && !cache.current.has(id));
  const key = missing.slice().sort().join('|');
  const [state] = useRequest(signal => key ? reader.getRecords(missing.map(id => ({ kind: 'meeting', id })), { signal }) : Promise.resolve([]), [reader, key]);
  useEffect(() => {
    if (state.status !== 'ready' || !state.value) return;
    let changed = false;
    state.value.forEach((record, index) => {
      const id = missing[index];
      if (!id) return;
      const title = record ? recordTitle(record) : '';
      if (cache.current.get(id) !== title) {
        cache.current.set(id, title);
        changed = true;
      }
    });
    if (changed) refresh(value => value + 1);
  }, [state]);
  return cache.current;
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
  const currentMeetingId = selected.kind === 'meeting' ? selected.id : '';
  const meetingTitles = useRelatedMeetingTitles(reader, result?.records || [], currentMeetingId);
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
    {materialType === 'document' && categories.length > 1 ? <label className="explorer-related-filter"><span>Document category</span><span className="explorer-field-reason">Show one document category from this meeting.</span>
      <select aria-label="Document category. Show one document category from this meeting." value={filter.category} onChange={event => setFilter({ category: event.target.value, page: 0 })}>
        <option value="">All categories ({integer(allCount)})</option>
        {categories.map(category => <option key={category.label} value={category.label}>{category.label} ({integer(category.count)})</option>)}
      </select>
    </label> : null}
    {state.status === 'error' ? <RequestMessage state={state} retry={retry} noun={label.toLowerCase()} /> : null}
    {state.status === 'loading' ? <p className="explorer-note" role="status">Updating the list.</p> : null}
    <div aria-busy={state.status === 'loading'}>{[...groups].map(([category, items]) => <div className="explorer-material-group" key={category}>
      {materialType === 'document' ? <h4>{category} <span className="explorer-muted">({integer(categories.find(item => item.label === category)?.count || items.length)})</span></h4> : null}
      <ul className="explorer-related-list">{items.map(record => <MaterialRow key={record.id} record={record} onSelect={onSelect} meetingTitles={meetingTitles} currentMeetingId={currentMeetingId} />)}</ul>
    </div>)}
    {!records.length ? <p>No documents match this category.</p> : null}
    {total > PAGE_SIZE ? <Pagination total={total} offset={offset} count={records.length} onPage={page => setFilter(current => ({ ...current, page }))} /> : null}</div>
  </section>;
}

function MaterialRow({ record, onSelect, meetingTitles, currentMeetingId }: { record: DetailRecord; onSelect: Props['onSelect']; meetingTitles: ReadonlyMap<string, string>; currentMeetingId: string }) {
  const row = fields(record), files = recordFiles(record);
  const filenames = recordedFileNames(files);
  const filename = filenames[0] || '';
  const category = materialCategory(record);
  const title = relatedMaterialTitle(row, category, filename);
  const day = (typeof row.date === 'string' ? row.date : '').slice(0, 10);
  const when = [day ? [day, recordedWhen(row).time].filter(Boolean).join(' ') : '', scheduleNote(row)].filter(Boolean).join(' · ');
  const meetings = linkedMeetingIds(row).flatMap(id => {
    if (id === currentMeetingId) return [];
    const meeting = meetingTitles.get(id) || '';
    return meeting && !sameRecordedTitle(meeting, title) ? [meeting] : [];
  });
  const titlePreview = recordedTitlePreview(title);
  const titleRest = titlePreview.rest;
  const identity = row.type === 'recording' ? recordingIdentity(typeof row.recording_url === 'string' ? row.recording_url : '') : '';
  const titleText = String(row.title || '').toLowerCase();
  const recordedFacts = Array.isArray(row.facts) ? row.facts.map(fields).flatMap(fact => {
    const label = String(fact.label || '').trim();
    const value = String(fact.value || '').trim();
    if (!label || !value || ['medium', 'coverage', 'production', 'hierarchy definition'].includes(label.toLowerCase()) || value.toLowerCase() === 'unknown') return [];
    if (titleText.includes(value.toLowerCase())) return [];
    return [`${label}: ${value}`];
  }) : [];
  return <li>
    {files.length ? <a className="explorer-recorded-lines" href={publicUrl(files[0].url)} target="_blank" rel="noreferrer" title={title}>{titlePreview.preview} ↗</a> : <span className="explorer-recorded-lines" title={title}>{titlePreview.preview}</span>}
    {titleRest.length ? <details className="explorer-row-meta"><summary>{titlePreview.continued ? 'Rest of the recorded title' : titleRest.length === 1 ? '1 more line of the recorded title' : `${titleRest.length} more lines of the recorded title`}<span className="explorer-field-reason">The rest of the title, in the order it was recorded.</span></summary>{titleRest.map(line => <span className="explorer-row-meta explorer-recorded-lines" key={line}>{line}</span>)}</details> : null}
    {when ? <span className="explorer-row-meta">{when}</span> : null}
    {meetings.map(meeting => {
      const meetingTitle = recordedTitlePreview(meeting);
      return <span key={meeting}><span className="explorer-row-meta explorer-recorded-lines" title={meeting}>{meetingTitle.preview}</span>{meetingTitle.rest.length ? <details className="explorer-row-meta"><summary>{meetingTitle.continued ? 'Rest of the meeting title' : meetingTitle.rest.length === 1 ? '1 more line of the meeting title' : `${meetingTitle.rest.length} more lines of the meeting title`}<span className="explorer-field-reason">The rest of the meeting title, in the order it was recorded.</span></summary>{meetingTitle.rest.map(line => <span className="explorer-row-meta explorer-recorded-lines" key={line}>{line}</span>)}</details> : null}</span>;
    })}
    {filename && filename !== title ? <span className="explorer-row-meta">{filename}</span> : null}
    {recordedAddressNames(row).map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
    {filenames.slice(1).map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
    {identity ? <span className="explorer-row-meta">{identity}</span> : null}
    {files.length > 1 ? <FileLinks record={record} /> : null}
    {documentSourceLabel(row) ? <span className="explorer-row-meta">{documentSourceLabel(row)}</span> : null}
    {categoryNote(row) ? <span className="explorer-row-meta">{categoryNote(row)}</span> : null}
    {filePartNote(row) ? <span className="explorer-row-meta">{filePartNote(row)}</span> : null}
    {meetingStatusNote(row) ? <span className="explorer-row-meta">{meetingStatusNote(row)}</span> : null}
    {publishedNote(row) ? <span className="explorer-row-meta">{publishedNote(row)}</span> : null}
    {sourceCountNote(row) ? <span className="explorer-row-meta">{sourceCountNote(row)}</span> : null}
    {typeof row.issue_count === 'number' && row.issue_count > 0 ? <span className="explorer-row-meta">{integer(row.issue_count)} known {row.issue_count === 1 ? 'issue' : 'issues'}</span> : null}
    {recordedFacts.length ? <span className="explorer-evidence">{recordedFacts.map(fact => <span key={fact}>{fact}</span>)}</span> : null}
    <button className="explorer-text-button explorer-row-meta" aria-label={`Open the full record for ${title}, including source evidence`} onClick={() => onSelect(record)}>Details & source</button>
    <RecordingPlayer record={record} />
  </li>;
}
