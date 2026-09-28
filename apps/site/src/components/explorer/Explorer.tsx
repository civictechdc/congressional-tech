import { useEffect, useRef, useState, type DependencyList } from 'react';
import { openPublicationReader, type CoverageSummary, type ExplorerQuery, type ExplorerReader, type ExplorerRecordRef, type QueryInfo, type QueryResult } from './data-source';
import { RecordDetail, RecordingPlayer, documentType, enumLabel, fields, FileLinks, publicUrl, recordFiles, recordTitle, words, type DetailRecord } from './RecordDetail';
import Coverage from './Coverage';
import { downloadJson } from './download';
import { readNavigation, viewNavigation, drillNavigation } from './navigation.js';
import { documentSourceLabel, sourcePageUrl } from './record-presentation.js';

const VIEWS = [
  { key: 'meetings', label: 'Meetings', kind: 'meeting' },
  { key: 'committees', label: 'Committees', kind: 'committee_term' },
  { key: 'materials', label: 'Recordings & documents', kind: 'material' },
  { key: 'witnesses', label: 'Witnesses', kind: 'appearance' },
  { key: 'coverage', label: 'Coverage', kind: 'meeting' },
  { key: 'gaps', label: 'Gaps & issues', kind: 'data_issue' },
] as const;
type View = typeof VIEWS[number]['key'];
const PAGE_SIZE = 25;
const integer = (value: number) => value.toLocaleString('en-US');
type RequestState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; value: T };

/** Each request owns its cancellation; replacing filters cannot paint an older result. */
function useRequest<T>(load: (signal: AbortSignal) => Promise<T>, dependencies: DependencyList): [RequestState<T>, () => void] {
  const [state, setState] = useState<RequestState<T>>({ status: 'loading' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    load(controller.signal).then((value) => {
      if (!controller.signal.aborted) setState({ status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({ status: 'error', message: error instanceof Error ? error.message : String(error) });
    });
    return () => controller.abort();
  }, [...dependencies, retry]);
  return [state, () => setRetry((value) => value + 1)];
}

function RequestMessage({ state, retry, noun = 'records' }: { state: { status: 'loading' } | { status: 'error'; message: string }; retry: () => void; noun?: string }) {
  return state.status === 'loading' ? <p className="explorer-loading" role="status">Loading {noun}…</p> : <div className="explorer-alert" role="alert"><p>Could not load {noun}. {state.message}</p><button className="explorer-button" onClick={retry}>Try again</button></div>;
}

/** Composition root: only this adapter choice knows a publication URL. */
export default function Explorer({ pointerUrl }: { pointerUrl: string }) {
  const [state, retry] = useRequest((signal) => openPublicationReader({ pointerUrl, signal }), [pointerUrl]);
  return state.status === 'ready' ? <CommitteeExplorer reader={state.value} /> : <div className="explorer"><RequestMessage state={state} retry={retry} noun="the published archive" /></div>;
}

/** The application accepts domain queries; JSON, Parquet and transport stay in the reader. */
export function CommitteeExplorer({ reader }: { reader: ExplorerReader }) {
  const [state, retry] = useRequest((signal) => reader.getQueryInfo({ signal }), [reader]);
  return state.status === 'ready' ? <Workspace reader={reader} info={state.value} /> : <div className="explorer"><RequestMessage state={state} retry={retry} noun="archive metadata" /></div>;
}

export interface Navigation {
  view: View; congress: string; chamber: string; q: string; from: string; to: string;
  type: string; status: string; page: number; kind: string; id: string;
  committee: string; month: string; aspect: string; evidence: string;
  measure: import('./data-source').CoverageAspect; grouping: 'congress' | 'month';
}
function writeNavigation(nav: Navigation, replace: boolean) {
  const url = new URL(window.location.href);
  url.search = '';
  for (const [key, value] of Object.entries(nav)) if (value !== '' && !(key === 'page' && value === 0)) url.searchParams.set(key, String(value));
  window.history[replace ? 'replaceState' : 'pushState'](null, '', url);
}
function toQuery(nav: Navigation): ExplorerQuery {
  const query: ExplorerQuery = {
    kind: VIEWS.find((view) => view.key === nav.view)!.kind,
    congress: nav.congress === 'all' ? 'all' : Number(nav.congress),
    chamber: nav.chamber || undefined, q: nav.q || undefined, dateFrom: nav.view === 'committees' ? undefined : nav.from || undefined, dateTo: nav.view === 'committees' ? undefined : nav.to || undefined,
    type: nav.type || undefined, status: nav.status || undefined, committeeId: nav.committee || undefined, month: nav.month || undefined,
    aspect: nav.aspect as ExplorerQuery['aspect'] || undefined, evidence: nav.evidence as ExplorerQuery['evidence'] || undefined,
    offset: nav.page * PAGE_SIZE, limit: PAGE_SIZE,
  };
  return query;
}

function Workspace({ reader, info }: { reader: ExplorerReader; info: QueryInfo }) {
  const [nav, setNav] = useState(() => readNavigation(window.location.search, info.default_congress));
  const [queryText, setQueryText] = useState(nav.q);
  const headingRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const pop = () => { const next = readNavigation(window.location.search, info.default_congress); setNav(next); setQueryText(next.q); };
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, [info.default_congress]);
  const update = (patch: Partial<Navigation>, replace = false) => {
    const next = { ...nav, ...patch };
    writeNavigation(next, replace); setNav(next);
    if (patch.q !== undefined) setQueryText(patch.q);
  };
  const filter = (patch: Partial<Navigation>) => update({ ...patch, page: 0, kind: '', id: '' });
  const select = (ref: ExplorerRecordRef) => {
    update({ kind: ref.kind, id: ref.id });
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
  };
  const query = toQuery(nav);
  const selection = nav.kind && nav.id ? { kind: nav.kind, id: nav.id } : null;
  const changeView = (view: View) => update(viewNavigation(nav, view));
  const drill = (patch: ExplorerQuery) => update(drillNavigation(nav, patch));
  const reset = () => { const next: Navigation = { view: nav.view, congress: String(info.default_congress), chamber: '', q: '', from: '', to: '', type: '', status: '', page: 0, kind: '', id: '', committee: '', month: '', aspect: '', evidence: '', measure: 'transcript', grouping: 'congress' }; writeNavigation(next, false); setNav(next); setQueryText(''); };
  const dateError = nav.view !== 'committees' && nav.from && nav.to && nav.from > nav.to;
  const hasDrill = nav.committee || nav.month || nav.aspect || nav.evidence;
  return <div className="explorer">
    <div className="explorer-publication"><span>Export generated {String(reader.publication.generated_at || 'date not recorded').replace('T', ' ').replace('Z', ' UTC')}</span><span>Snapshot <code>{String(reader.publication.publication_id || '').slice(0, 16)}</code></span></div>
    <nav className="explorer-tabs" aria-label="Explorer workspaces">{VIEWS.map((view) => <button key={view.key} aria-current={nav.view === view.key ? 'page' : undefined} onClick={() => changeView(view.key)}>{view.label}</button>)}</nav>
    <form className="explorer-filters" aria-label="Filter committee records" onSubmit={(event) => { event.preventDefault(); filter({ q: queryText }); }}>
      <label>Search this workspace<input type="search" value={queryText} onChange={(event) => setQueryText(event.target.value)} placeholder="Title or recorded name" /></label>
      <button type="submit" className="explorer-button">Search</button>
      <label>Congress<select value={nav.congress} onChange={(event) => filter({ congress: event.target.value })}><option value="all">All Congresses</option>{info.congresses.map((value) => <option key={value} value={value}>{value}th Congress</option>)}</select></label>
      <label>Chamber<select value={nav.chamber} onChange={(event) => filter({ chamber: event.target.value })}><option value="">All chambers</option><option value="house">House</option><option value="senate">Senate</option><option value="joint">Joint</option><option value="unknown">Unknown</option></select></label>
      {nav.view !== 'committees' ? <><label>From date<input aria-label="From date" type="date" value={nav.from} onChange={(event) => filter({ from: event.target.value })} /></label>
      <label>Through date<input aria-label="Through date" type="date" value={nav.to} onChange={(event) => filter({ to: event.target.value })} /></label></> : null}
      {nav.view === 'materials' ? <label>Material type<select value={nav.type} onChange={(event) => filter({ type: event.target.value })}><option value="">All types</option><option value="document">Document</option><option value="recording">Recording</option><option value="text">Text product</option></select></label> : null}
      {nav.view === 'meetings' || nav.view === 'coverage' ? <label>Meeting type<select value={nav.type} onChange={event => filter({type: event.target.value})}><option value="">All types</option><option value="hearing">Hearing</option><option value="markup">Markup</option><option value="business">Business meeting</option><option value="meeting">Meeting</option><option value="briefing">Briefing</option><option value="field_hearing">Field hearing</option><option value="other">Other</option><option value="unknown">Unknown</option></select></label> : null}
      {nav.view === 'gaps' ? <label>Issue status<select value={nav.status} onChange={(event) => filter({ status: event.target.value })}><option value="">All statuses</option><option value="open">Open</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option></select></label> : null}
      <button type="button" className="explorer-text-button" onClick={reset}>Reset</button>
    </form>
    {hasDrill ? <div className="explorer-subheading"><p className="explorer-note">From coverage: {[nav.committee ? info.committee_labels?.[nav.committee] || 'selected committee' : '', nav.month, words(nav.aspect), words(nav.evidence)].filter(Boolean).join(' · ')}</p><button className="explorer-text-button" onClick={() => filter({ committee: '', month: '', aspect: '', evidence: '' })}>Clear chart filters</button></div> : null}
    {nav.congress === 'all' ? <p className="explorer-note">All-Congress queries search the full retained archive and may take longer.</p> : null}
    {nav.view !== 'committees' && (nav.from || nav.to) ? <p className="explorer-note">Date filters exclude records without a recorded date in this index.</p> : null}
    <section ref={headingRef} tabIndex={-1} className="explorer-workspace" aria-label="Explorer results">
      {dateError ? <p className="explorer-alert" role="alert">The start date must be on or before the end date.</p> : selection ? <Inspector key={`${selection.kind}/${selection.id}`} reader={reader} selected={selection} onSelect={select} onClose={() => { update({ kind: '', id: '' }); headingRef.current?.focus({preventScroll: true}); }} /> : nav.view === 'coverage' ? <CoverageView reader={reader} query={query} onDrill={drill} measure={nav.measure} grouping={nav.grouping} onSettings={update} /> : <Listing reader={reader} query={query} view={nav.view} info={info} onSelect={select} onPage={(page) => update({ page })} />}
    </section>
    {!selection && (nav.view === 'coverage' || nav.view === 'gaps') ? <PublicationScope publication={reader.publication} /> : null}
  </div>;
}

function PublicationScope({ publication }: { publication: Readonly<Record<string, unknown>> }) {
  const scopes = Array.isArray(publication.source_scopes) ? publication.source_scopes.map(fields) : [];
  const inputs = Array.isArray(publication.inputs) ? publication.inputs.map(fields) : [];
  const limitations = Array.isArray(publication.limitations) ? publication.limitations : [];
  const grouped = new Map<string, typeof scopes>();
  for (const scope of scopes) {
    const key = JSON.stringify([scope.provider, scope.status, scope.explanation]);
    const group = grouped.get(key) || [];
    group.push(scope); grouped.set(key, group);
  }
  return <section className="explorer-detail-section"><h3>Source coverage and limits</h3>
    <p className="explorer-note">These collection boundaries describe the entire publication, independently of the filters above. An included source is not a claim that every record or attachment was captured.</p>
    {scopes.length ? <div className="explorer-table-scroll"><table className="explorer-table"><thead><tr><th scope="col">Source family</th><th scope="col">Collection status</th><th scope="col">Scope and limitations</th></tr></thead><tbody>{[...grouped.values()].map((group, index) => {
      const scope = group[0];
      return <tr key={index}><th scope="row">{String(scope.provider)}{group.length > 1 ? <span className="explorer-row-meta">{integer(group.length)} scopes</span> : null}</th><td>{words(scope.status)}</td><td>{group.length === 1 ? String(scope.scope) : `${integer(group.length)} source scopes`}<span className="explorer-row-meta">{String(scope.explanation)}</span>
        <details><summary>{group.length > 1 ? `Show all ${integer(group.length)} exact scopes` : 'Scope details'}</summary><ul className="explorer-values">{group.map((item, itemIndex) => <li key={itemIndex}><strong>{String(item.scope)}</strong><span className="explorer-row-meta">Subject dates: {fields(item.coverage).start || fields(item.coverage).end ? `${String(fields(item.coverage).start || 'Unknown')} to ${String(fields(item.coverage).end || 'Unknown')}` : 'Not recorded'}</span><span className="explorer-row-meta">Input snapshots: {Array.isArray(item.input_snapshot_ids) && item.input_snapshot_ids.length ? item.input_snapshot_ids.join(', ') : 'None recorded'}</span></li>)}</ul></details>
      </td></tr>;
    })}</tbody></table></div> : <p className="explorer-note">Collection scope has not been described for this publication.</p>}
    {limitations.length ? <ul className="explorer-note">{limitations.map((limitation, index) => <li key={index}>{String(limitation)}</li>)}</ul> : null}
    <details><summary>Input freshness and collection attempts</summary><p className="explorer-note">Import and export times do not establish when a source was fetched or last checked. An unrecorded observation date stays unknown.</p>
      <div className="explorer-table-scroll"><table className="explorer-table"><thead><tr><th scope="col">Input</th><th scope="col">Last source observation</th><th scope="col">Last attempt</th><th scope="col">Import time</th></tr></thead><tbody>{inputs.map((input, index) => <tr key={index}><th scope="row">{String(input.provider)}<span className="explorer-row-meta">{Array.isArray(input.limitations) ? input.limitations.join(' ') : ''}</span></th><td>{String(input.last_observed_at || 'Not recorded')}</td><td>{words(input.last_attempt_status) || 'Unknown'}<span className="explorer-row-meta">{String(input.last_attempt_at || 'Date not recorded')}</span></td><td>{String(input.imported_at || 'Not recorded')}</td></tr>)}</tbody></table></div>
    </details>
  </section>;
}

function Pagination({ total, offset, count, onPage }: { total: number; offset: number; count: number; onPage: (page: number) => void }) {
  return <div className="explorer-pagination"><span>{total ? `${integer(count ? offset + 1 : 0)}–${integer(count ? offset + count : 0)} of ${integer(total)}` : '0 matching records'}</span><div><button className="explorer-button" disabled={offset === 0} onClick={() => onPage(Math.max(0, Math.floor(offset / PAGE_SIZE) - 1))}>← Previous</button><button className="explorer-button" disabled={offset + count >= total} onClick={() => onPage(Math.floor(offset / PAGE_SIZE) + 1)}>Next →</button></div></div>;
}

const VIEW_NOTES: Record<Exclude<View, 'coverage'>, string> = {
  meetings: 'Committee meetings, including scheduled, postponed and canceled entries.',
  committees: 'Browse each committee’s meetings by Congress.',
  materials: 'Documents and recordings from collected sources, including items without a matched meeting.',
  witnesses: 'Witnesses listed by meeting. A listing does not confirm attendance.',
  gaps: 'Known collection and matching issues. Coverage shows which material remains unchecked.',
};

function Listing({ reader, query, view, info, onSelect, onPage }: { reader: ExplorerReader; query: ExplorerQuery; view: Exclude<View, 'coverage'>; info: QueryInfo; onSelect: (ref: ExplorerRecordRef) => void; onPage: (page: number) => void }) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<QueryResult>((signal) => reader.search(query, { signal }), [reader, key]);
  const title = VIEWS.find((item) => item.key === view)!.label;
  return <>
    <div className="explorer-subheading"><h2>{title}</h2>{state.status === 'ready' ? <><span className="explorer-muted">{integer(state.value.total)} {view === 'witnesses' ? (state.value.total === 1 ? 'appearance' : 'appearances') : (state.value.total === 1 ? 'record' : 'records')}</span><button className="explorer-text-button" onClick={() => downloadJson(`committee-explorer-${view}-page-${Math.floor(state.value.offset / PAGE_SIZE) + 1}.json`, { scope: 'selection', publication_id: reader.publication.publication_id, schema_version: reader.publication.schema_version, filters: query, total: state.value.total, offset: state.value.offset, rows: state.value.rows })}>Download this page (JSON)</button></> : null}</div>
    <p className="explorer-note">{VIEW_NOTES[view]}</p>
    {state.status !== 'ready' ? <RequestMessage state={state} retry={retry} /> : state.value.rows.length ? <>
      <div className="explorer-table-scroll"><table className="explorer-table"><thead><tr>
        <th scope="col">{view === 'witnesses' ? 'Recorded name' : view === 'gaps' ? 'Known issue' : 'Record'}</th>
        <th scope="col">{view === 'committees' ? 'Congress' : view === 'witnesses' ? 'Date / Congress' : 'Date / status'}</th>
        {view !== 'committees' ? <th scope="col">{view === 'witnesses' ? 'Position / organization' : view === 'gaps' ? 'Congress / category' : 'Congress / type'}</th> : null}
        {view !== 'committees' && view !== 'gaps' ? <th scope="col" className="explorer-number">Open issues</th> : null}
      </tr></thead><tbody>
        {state.value.rows.map(row => <tr key={`${row.kind}/${row.id}`}>
          <td className="explorer-title-cell"><button className="explorer-text-button" title={row.title} onClick={() => onSelect(row)}>{recordTitle(row)}</button>
            <span className="explorer-row-meta">{[enumLabel(row.chamber), ...(view === 'committees' ? [] : row.committee_ids || []).map(id => info.committee_labels?.[id]).filter(Boolean), row.provider].filter(Boolean).join(' · ')}</span>
          </td>
          <td>{view !== 'committees' ? row.date || <span className="explorer-unknown">Date unrecorded</span> : null}<span className={view === 'committees' ? undefined : 'explorer-row-meta'}>{view === 'committees' || view === 'witnesses' ? row.congress ? `${row.congress}th Congress` : 'Congress unrecorded' : enumLabel(row.status)}</span></td>
          {view !== 'committees' ? <td>{view === 'witnesses' ? <>{row.position || row.roles?.map(enumLabel).join(', ') || 'Position unrecorded'}{row.organization ? <span className="explorer-row-meta">{row.organization}</span> : null}</> : <>{row.congress ? `${row.congress}th Congress` : 'Congress unrecorded'}<span className="explorer-row-meta">{[documentType(row) || [row.type, row.category].filter((value, index, list) => value && value !== 'unknown' && list.indexOf(value) === index).map(enumLabel).join(' · '), documentSourceLabel(row)].filter(Boolean).join(' · ')}</span>{row.selection === 'retained_history' ? <span className="explorer-row-meta">Retained issue history · not present in latest inputs</span> : null}</>}</td> : null}
          {view !== 'committees' && view !== 'gaps' ? <td className="explorer-number">{row.issue_count === undefined ? '—' : integer(row.issue_count)}</td> : null}
        </tr>)}
      </tbody></table></div><Pagination total={state.value.total} offset={state.value.offset} count={state.value.rows.length} onPage={onPage} />
    </> : <div className="explorer-alert"><p>{state.value.total ? 'This page is beyond the available results. Return to the first page to continue.' : 'No records match this selection. Broaden the filters. This does not establish that no such records exist at the source.'}</p>{query.offset ? <button className="explorer-button" onClick={() => onPage(0)}>Return to first page</button> : null}</div>}
  </>;
}

function CoverageView({ reader, query, onDrill, measure, grouping, onSettings }: { reader: ExplorerReader; query: ExplorerQuery; onDrill: (query: ExplorerQuery) => void; measure: Navigation['measure']; grouping: Navigation['grouping']; onSettings: (patch: Partial<Navigation>) => void }) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<CoverageSummary>((signal) => reader.getCoverage({ filters: query, signal }), [reader, key]);
  return state.status === 'ready' ? <Coverage summary={state.value} onDrill={onDrill} aspect={measure} grouping={grouping} onAspect={measure => onSettings({measure})} onGrouping={grouping => onSettings({grouping})} /> : <RequestMessage state={state} retry={retry} noun="coverage for this selection" />;
}

function Inspector({ reader, selected, onSelect, onClose }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void; onClose: () => void }) {
  const [state, retry] = useRequest<DetailRecord | undefined>((signal) => reader.getRecord(selected, { signal }), [reader, selected.kind, selected.id]);
  return <article className="explorer-detail"><div className="explorer-subheading"><button className="explorer-text-button" onClick={onClose}>← Back to results</button>{state.status === 'ready' && state.value ? <button className="explorer-text-button" onClick={() => downloadJson(`committee-explorer-${selected.kind}-${selected.id}.json`, { scope: 'record', publication_id: reader.publication.publication_id, schema_version: reader.publication.schema_version, record: state.value })}>Download record (JSON)</button> : null}</div>
    {state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun="record details" /> : state.value ? <><RecordDetail record={state.value} onSelect={onSelect} sourceEvidence={<SourceEvidence reader={reader} record={state.value} />} /><Related key={`${selected.kind}/${selected.id}`} reader={reader} selected={selected} onSelect={onSelect} /></> : <p className="explorer-alert">This record is not present in the selected publication. Its absence does not establish that it was removed at the source.</p>}
  </article>;
}

function SourceEvidence({ reader, record }: { reader: ExplorerReader; record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  const ids = fields(record).source_ids;
  if (!Array.isArray(ids) || !ids.length) return null;
  return <details className="explorer-detail-section" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Source evidence ({ids.length})</summary>
    {open ? <SourceRecords reader={reader} ids={ids.map(String)} /> : null}
  </details>;
}

function SourceRecords({ reader, ids }: { reader: ExplorerReader; ids: string[] }) {
  const [state, retry] = useRequest(signal => reader.getRecords(ids.map(id => ({kind: 'source_record', id})), {signal}), [reader, ids.join(',')]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="source evidence" />;
  return <>{state.value.map((source, index) => {
    if (!source) return <p className="explorer-note" key={ids[index]}>Source {index + 1} is unavailable in this publication.</p>;
    const url = publicUrl(sourcePageUrl(fields(source).url));
    return <div key={source.id}>
      <div className="explorer-subheading"><h4>Source {index + 1}: {recordTitle(source)}</h4>{url ? <a href={url} target="_blank" rel="noreferrer">Open original source ↗</a> : null}</div>
      <pre><code>{JSON.stringify(source, null, 2)}</code></pre>
    </div>;
  })}</>;
}

function Related({ reader, selected, onSelect }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void }) {
  const sections: Record<string, string[]> = {meeting: ['material', 'appearance', 'data_issue'], appearance: ['material', 'data_issue'], material: ['meeting', 'data_issue'], committee_term: ['meeting', 'data_issue']};
  return <div className="explorer-related">{(sections[selected.kind] || []).map(kind => <RelatedSection key={kind} kind={kind} reader={reader} selected={selected} onSelect={onSelect} />)}</div>;
}

function RelatedSection({ reader, selected, onSelect, kind }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void; kind: string }) {
  const [page, setPage] = useState(0);
  const [state, retry] = useRequest(signal => reader.getRelated(selected, { kind, offset: page * PAGE_SIZE, limit: PAGE_SIZE, signal }), [reader, selected.kind, selected.id, kind, page]);
  const labels: Record<string, string> = { material: 'Documents & recordings', appearance: 'Witnesses', meeting: 'Meetings', data_issue: 'Known issues' };
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun={labels[kind].toLowerCase()} />;
  if (!state.value.records.length) return null;
  return <section className="explorer-detail-section"><h3>{labels[kind]} <span className="explorer-muted">({integer(state.value.total)})</span></h3><ul className="explorer-related-list">{state.value.records.map(record => {
        const row = fields(record), files = recordFiles(record);
        const title = row.type === 'recording' ? 'Watch recording' : recordTitle(record);
        return <li key={record.id}>
          {kind === 'material' ? <>
            {files.length ? <a href={publicUrl(files[0].url)} target="_blank" rel="noreferrer">{title} ↗</a> : <span>{title}</span>}
            {files.length > 1 ? <FileLinks record={record} /> : null}
            {documentType(record) || documentSourceLabel(row) ? <span className="explorer-row-meta">{[documentType(record), documentSourceLabel(row)].filter(Boolean).join(' · ')}</span> : null}
            {Array.isArray(row.facts) ? <span className="explorer-row-meta">{row.facts.map(fields).filter(f => !['medium', 'coverage', 'production'].includes(String(f.label))).map(f => `${f.label}: ${f.value}`).join(' · ')}</span> : null}
            <button className="explorer-text-button explorer-row-meta" onClick={() => onSelect(record)}>Details & source</button>
            <RecordingPlayer record={record} />
          </> : <>
            <button className="explorer-text-button" onClick={() => onSelect(record)}>{title}</button>
            <span className="explorer-row-meta">{[row.position, row.organization, row.date, row.status].filter(Boolean).map(words).join(' · ')}</span>
          </>}
        </li>;
      })}</ul>
    {state.value.total > PAGE_SIZE ? <Pagination total={state.value.total} offset={state.value.offset} count={state.value.records.length} onPage={setPage} /> : null}
  </section>;
}
