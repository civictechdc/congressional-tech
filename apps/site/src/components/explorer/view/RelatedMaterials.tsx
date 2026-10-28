import { useEffect, useId, useRef, useState } from 'react';
import { ExternalIcon, ForwardIcon } from './icons';
import type { ExplorerReader, ExplorerRecordRef, RelatedResult } from '../reader/data-source.ts';
import { enumLabel, fields, FileLinks, publicUrl, recordFiles, recordTitle, RecordingPlayer, type DetailRecord } from './RecordDetail';
import { categoryNote, documentSourceInContext, filePartNote, issueNotes, issueStatusLabel, linkedMeetingIds, listedWhen, meetingStatusNote, publishedNote, recordedAddressNames, recordedFileNames, recordedTitlePreview, repeatsRecordedWhen, recordingIdentity, sourceCountNote } from '../browse/record-presentation.ts';
import { groupByMeeting, materialCategory, meetingGroupLabel, relatedMaterialTitle, sameRecordedTitle, sharedText, titleInContext } from '../browse/related-materials.ts';
import { PAGE_SIZE, Pagination, RequestMessage, integer, useRequest } from './request-state';
import './RelatedMaterials.css';

type Props = { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void; contextTitle?: string; contextWhen?: string };

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

function MaterialSection({ reader, selected, onSelect, materialType, contextTitle = '', contextWhen = '' }: Props & { materialType: 'document' | 'recording' }) {
  const [filter, setFilter] = useState({ category: '', page: 0 });
  const id = useId();
  const label = materialType === 'recording' ? 'Recordings' : 'Documents';
  const categoryScope = selected.kind === 'committee_term' ? 'this committee' : selected.kind === 'appearance' ? 'this witness' : 'this meeting';
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
    <h3 id={id}>{label} <span className="explorer-muted" role={state.status === 'loading' ? 'status' : undefined}>{state.status === 'loading' ? 'Updating' : `(${integer(allCount || total)})`}</span></h3>
    {materialType === 'document' && categories.length > 1 ? <label className="explorer-related-filter"><span>Document category</span><span className="explorer-field-reason">Show one document category from {categoryScope}.</span>
      <select aria-label={`Document category. Show one document category from ${categoryScope}.`} value={filter.category} onChange={event => setFilter({ category: event.target.value, page: 0 })}>
        <option value="">All categories ({integer(allCount)})</option>
        {categories.map(category => <option key={category.label} value={category.label}>{category.label} ({integer(category.count)})</option>)}
      </select>
    </label> : null}
    {state.status === 'error' ? <RequestMessage state={state} retry={retry} noun={label.toLowerCase()} /> : null}
    <div aria-busy={state.status === 'loading'}>{[...groups].map(([category, items]) => <div className="explorer-material-group" key={category}>
      {materialType === 'document' ? <h4>{category} <span className="explorer-muted">({integer(categories.find(item => item.label === category)?.count || items.length)})</span></h4> : null}
      {documentGroups(items, materialType, currentMeetingId).map(group => {
        const sharedWhen = sharedText(group.items.map(record => recordedWhenLine(fields(record))));
        const meetingTitle = group.meetingId ? titleInContext(meetingTitles.get(group.meetingId) || '', contextTitle) : '';
        const heading = meetingGroupLabel(meetingTitle, sharedWhen);
        return <div key={group.meetingId || category}>
          {heading && group.meetingId ? <p className="explorer-meeting-group"><button className="explorer-text-button" aria-label={`Open the meeting ${meetingTitle}`} onClick={() => onSelect({ kind: 'meeting', id: group.meetingId })}>{heading} <ForwardIcon /></button></p> : null}
          <ul className="explorer-related-list">{group.items.map(record => <MaterialRow key={record.id} record={record} reader={reader} onSelect={onSelect} meetingTitles={meetingTitles} currentMeetingId={currentMeetingId} contextTitle={contextTitle} groupedMeeting={meetingTitle} sharedWhen={heading ? sharedWhen : ''} meetingWhen={currentMeetingId ? contextWhen : ''} />)}</ul>
        </div>;
      })}
    </div>)}
    {!records.length ? <p>No documents match this category.</p> : null}
    {total > PAGE_SIZE ? <Pagination total={total} offset={offset} count={records.length} onPage={page => setFilter(current => ({ ...current, page }))} /> : null}</div>
  </section>;
}

function documentGroups(items: readonly DetailRecord[], materialType: 'document' | 'recording', currentMeetingId: string) {
  if (materialType !== 'document' || currentMeetingId) return [{ meetingId: '', items: [...items] }];
  const groups = groupByMeeting(items, record => linkedMeetingIds(fields(record))[0] || '');
  return groups.some(group => group.meetingId) ? groups : [{ meetingId: '', items: [...items] }];
}

function recordedWhenLine(row: ReturnType<typeof fields>): string {
  return listedWhen(row);
}

/** The open-issue count expands to every saved issue, including dismissed ones. */
export function OpenIssues({ reader, record, count, onSelect }: { reader: ExplorerReader; record: { kind: string; id: string }; count: number; onSelect: (ref: ExplorerRecordRef) => void }) {
  const [open, setOpen] = useState(false);
  const label = `${integer(count)} ${count === 1 ? 'issue' : 'issues'} still open`;
  return <details className="explorer-row-meta" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary title="Show each saved issue. Dismissed issues are included. The count is only the ones still open.">{label}</summary>
    {open ? <OpenIssueList reader={reader} record={record} onSelect={onSelect} /> : null}
  </details>;
}

function OpenIssueList({ reader, record, onSelect }: { reader: ExplorerReader; record: { kind: string; id: string }; onSelect: (ref: ExplorerRecordRef) => void }) {
  const [state, retry] = useRequest(signal => reader.getRelated(record, { kind: 'data_issue', signal }), [reader, record.kind, record.id]);
  if (state.status === 'error') return <RequestMessage state={state} retry={retry} noun="issues" />;
  if (state.status !== 'ready' || !state.value) return <p className="explorer-note">Loading the issues.</p>;
  return <>
    <p className="explorer-field-reason">The count is the issues still open. Dismissed issues are included here.</p>
    <ul className="explorer-values">{state.value.records.map(issue => {
      const recordedStatus = fields(issue).status;
      const status = issueStatusLabel(typeof recordedStatus === 'string' ? recordedStatus : undefined) || enumLabel(recordedStatus);
      const notes = issueNotes(fields(issue)).slice(0, 2);
      return <li key={issue.id}><button className="explorer-text-button" aria-label={`Open the issue ${recordTitle(issue)}`} onClick={() => onSelect(issue)}>{recordTitle(issue)}</button>{status ? <span className="explorer-row-meta">{status}</span> : null}{notes.map(note => <span className="explorer-row-meta" key={note}>{note}</span>)}</li>;
    })}</ul>
  </>;
}

function MaterialRow({ record, reader, onSelect, meetingTitles, currentMeetingId, contextTitle = '', groupedMeeting = '', sharedWhen = '', meetingWhen = '' }: { record: DetailRecord; reader: ExplorerReader; onSelect: Props['onSelect']; meetingTitles: ReadonlyMap<string, string>; currentMeetingId: string; contextTitle?: string; groupedMeeting?: string; sharedWhen?: string; meetingWhen?: string }) {
  const row = fields(record), files = recordFiles(record);
  const filenames = recordedFileNames(files);
  const filename = filenames[0] || '';
  const category = materialCategory(record);
  const notedCategory = categoryNote(row);
  const title = relatedMaterialTitle(row, category, filename);
  const when = recordedWhenLine(row);
  const meetings = linkedMeetingIds(row).flatMap(id => {
    if (id === currentMeetingId) return [];
    const meeting = meetingTitles.get(id) || '';
    const shown = titleInContext(meeting, contextTitle);
    return shown && !sameRecordedTitle(shown, title) ? [shown] : [];
  });
  const titlePreview = recordedTitlePreview(title);
  const titleRest = titlePreview.rest;
  const sourcePile = documentSourceInContext(row, Boolean(currentMeetingId));
  const identity = row.type === 'recording' ? recordingIdentity(typeof row.recording_url === 'string' ? row.recording_url : '') : '';
  const titleText = String(row.title || '').toLowerCase();
  const recordedFacts = Array.isArray(row.facts) ? row.facts.map(fields).flatMap(fact => {
    const label = String(fact.label || '').trim();
    const value = String(fact.value || '').trim();
    if (!label || !value || ['medium', 'coverage', 'production', 'hierarchy definition'].includes(label.toLowerCase()) || value.toLowerCase() === 'unknown') return [];
    const compact = (text: string) => text.toLowerCase().replaceAll(/[^a-z0-9]/g, '');
    const foldedValue = compact(value);
    if (titleText.includes(value.toLowerCase()) || (foldedValue.length >= 4 && compact(titleText).includes(foldedValue))) return [];
    if (label === 'Sponsor Bioguide ID') return [`Member number ${value}`];
    return [`${label}: ${value}`];
  }) : [];
  return <li>
    <span className="explorer-related-lead">
      {files.length ? <a className="explorer-recorded-lines" href={publicUrl(files[0].url)} target="_blank" rel="noreferrer" title={title}>{titlePreview.preview} <ExternalIcon /></a> : <span className="explorer-recorded-lines" title={title}>{titlePreview.preview}</span>}
      <button className="explorer-icon-button" type="button" aria-label={`Open the full record for ${title}, including source evidence`} title="Open record" onClick={() => onSelect(record)}><ForwardIcon /></button>
    </span>
    {titleRest.length ? <details className="explorer-row-meta"><summary>{titlePreview.continued ? 'Rest of the recorded title' : titleRest.length === 1 ? '1 more line of the recorded title' : `${titleRest.length} more lines of the recorded title`}<span className="explorer-field-reason">The rest of the title, in the order it was recorded.</span></summary>{titleRest.map(line => <span className="explorer-row-meta explorer-recorded-lines" key={line}>{line}</span>)}</details> : null}
    {when && when !== sharedWhen && !repeatsRecordedWhen(when, meetingWhen) ? <span className="explorer-row-meta">{when}</span> : null}
    {meetings.filter(meeting => meeting !== groupedMeeting).map(meeting => {
      const meetingTitle = recordedTitlePreview(meeting);
      return <span key={meeting}><span className="explorer-row-meta explorer-recorded-lines" title={meeting}>{meetingTitle.preview}</span>{meetingTitle.rest.length ? <details className="explorer-row-meta"><summary>{meetingTitle.continued ? 'Rest of the meeting title' : meetingTitle.rest.length === 1 ? '1 more line of the meeting title' : `${meetingTitle.rest.length} more lines of the meeting title`}<span className="explorer-field-reason">The rest of the meeting title, in the order it was recorded.</span></summary>{meetingTitle.rest.map(line => <span className="explorer-row-meta explorer-recorded-lines" key={line}>{line}</span>)}</details> : null}</span>;
    })}
    {filename && filename !== title ? <span className="explorer-row-meta">{filename}</span> : null}
    {recordedAddressNames(row).map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
    {filenames.slice(1).map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
    {identity ? <span className="explorer-row-meta" title={identity.startsWith('YouTube ') ? identity : undefined}>{identity.startsWith('YouTube ') ? 'YouTube' : identity}</span> : null}
    {files.length > 1 ? <FileLinks record={record} /> : null}
    {sourcePile ? <span className="explorer-row-meta">{sourcePile}</span> : null}
    {notedCategory && notedCategory.toLowerCase() !== category.toLowerCase() ? <span className="explorer-row-meta">{notedCategory}</span> : null}
    {filePartNote(row) ? <span className="explorer-row-meta">{filePartNote(row)}</span> : null}
    {meetingStatusNote(row) ? <span className="explorer-row-meta">{meetingStatusNote(row)}</span> : null}
    {publishedNote(row) ? <span className="explorer-row-meta">{publishedNote(row)}</span> : null}
    {sourceCountNote(row) ? <span className="explorer-row-meta">{sourceCountNote(row)}</span> : null}
    {typeof row.issue_count === 'number' && row.issue_count > 0 ? <OpenIssues reader={reader} record={record} count={row.issue_count} onSelect={onSelect} /> : null}
    {recordedFacts.length ? <span className="explorer-evidence">{recordedFacts.map(fact => <span key={fact}>{fact}</span>)}</span> : null}
    <RecordingPlayer record={record} />
  </li>;
}
