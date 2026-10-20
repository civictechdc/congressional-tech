import { useEffect, useRef, useState } from 'react';
import { openPublicationReader, type CoverageSummary, type ExplorerQuery, type ExplorerReader, type ExplorerRecordRef, type QueryInfo, type QueryKind, type QueryResult, type RelatedResult } from './reader/data-source.ts';
import { catalogMatchFiles } from './browse/filename-match.ts';
import { sameRecordedTitle } from './browse/related-materials.ts';
import { RecordDetail, SourceLinkGroups, documentType, enumLabel, fields, publicUrl, recordTitle, type DetailRecord } from './view/RecordDetail';
import { FilenameEvidence } from './view/FilenameEvidence';
import { FilenameFilters, FilenameListing } from './view/FilenameListing';
import Coverage from './view/Coverage';
import RelatedMaterials from './view/RelatedMaterials';
import { PAGE_SIZE, Pagination, RequestMessage, integer, useRequest } from './view/request-state';
import { downloadJson } from './view/download';
import { accessStates, committeeTypes, materialCategories, materialProviders, nextSort, readNavigation, viewNavigation, drillNavigation, type Navigation, type View } from './browse/navigation.ts';
import { issueCategories } from './browse/kinds.ts';
import { filenameRequest } from './reader/filenames/session.ts';
import type { FilenameCatalogInfo } from './reader/filenames/types.ts';
import { categoryNote, committeeKindNote, committeeLevelLabel, committeeLevelNote, committeeSourceNote, committeeTypeLabel, committeeWebsite, coverageDrillNote, dateFilterReason, earlierCommitteeNames, detectedNote, documentSourceLabel, evidenceParts, extraIssueAlternatives, filePartNote, issueNotes, landingPageNote, linkedMeetingIds, listTitle, meetingStatusNote, notableRoles, participationNote, providerLabel, publishedNote, recordedAction, recordedAddressNames, recordedAmendments, recordedFileNames, recordedFormatNote, recordedInstant, recordedMeasureValues, recordedPlace, recordedTitlePreview, recordedVotes, recordedWhen, recordedWitnesses, recordingIdentity, relatedParts, scheduleNote, sourceCountNote, witnessNameList, sourceFacts, sourceLinks, sourcePageUrl, sourceTypeNote, subjectAbsentNote, subjectKindLabel, witnessNotes } from './browse/record-presentation.ts';

const VIEWS = [
  { key: 'meetings', label: 'Meetings', kind: 'meeting' },
  { key: 'committees', label: 'Committees', kind: 'committee_term' },
  { key: 'materials', label: 'Recordings & documents', kind: 'material' },
  { key: 'witnesses', label: 'Witnesses', kind: 'appearance' },
  { key: 'coverage', label: 'Coverage', kind: 'meeting' },
  { key: 'gaps', label: 'Gaps & issues', kind: 'data_issue' },
] as const satisfies readonly { key: View; label: string; kind: QueryKind }[];

/** Keep a recorded calendar day on one line. */
const keepDate = (value: string) => value.replace(/(\d{4})-(\d{2})-(\d{2})/g, '$1\u2011$2\u2011$3');

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

function writeNavigation(nav: Navigation, replace: boolean) {
  const url = new URL(window.location.href);
  url.search = '';
  for (const [key, value] of Object.entries(nav)) if (value !== '' && !(key === 'page' && value === 0)) url.searchParams.set(key, String(value));
  window.history[replace ? 'replaceState' : 'pushState'](nav.kind && nav.id ? { explorerDetail: true } : null, '', url);
}
function toQuery(nav: Navigation, info: QueryInfo): ExplorerQuery {
  const query: ExplorerQuery = {
    kind: VIEWS.find((view) => view.key === nav.view)!.kind,
    congress: nav.congress === 'all' ? 'all' : Number(nav.congress),
    chamber: nav.chamber || undefined, q: nav.q || undefined, dateFrom: nav.view === 'committees' ? undefined : nav.from || undefined, dateTo: nav.view === 'committees' ? undefined : nav.to || undefined,
    type: nav.type || undefined, status: nav.status || undefined,
    category: nav.view === 'gaps' ? nav.category || undefined : nav.view === 'materials' && nav.scope === '' ? nav.materialCategory || undefined : undefined,
    severity: nav.view === 'gaps' ? nav.severity || undefined : undefined,
    participation: nav.view === 'witnesses' ? nav.participation || undefined : undefined,
    provider: nav.view === 'materials' && nav.scope === '' ? nav.provider || undefined : undefined,
    history: nav.view === 'gaps' ? nav.history || undefined : undefined,
    committeeId: nav.committee || undefined, month: nav.month || undefined,
    committeeLevel: info.supported_filters?.includes('committeeLevel') ? nav.committeeLevel || undefined : undefined,
    committeeType: info.supported_filters?.includes('committeeType') ? nav.committeeType || undefined : undefined,
    access: info.supported_filters?.includes('access') && (nav.view === 'meetings' || nav.view === 'coverage') ? nav.access || undefined : undefined,
    aspect: nav.aspect || undefined, evidence: nav.evidence || undefined,
    offset: nav.page * PAGE_SIZE, limit: PAGE_SIZE,
    sort: nav.view === 'materials' && nav.scope !== '' ? undefined : nav.sort || undefined,
    direction: nav.view === 'materials' && nav.scope !== '' ? undefined : nav.sort ? nav.direction || 'asc' : undefined,
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
    update({ kind: ref.kind, id: ref.id }, Boolean(nav.kind && nav.id));
    headingRef.current?.focus({ preventScroll: true });
    headingRef.current?.scrollIntoView({ block: 'start', behavior: 'instant' });
  };
  const query = toQuery(nav, info);
  const selection = nav.kind && nav.id ? { kind: nav.kind, id: nav.id } : null;
  const changeView = (view: View) => update(viewNavigation(nav, view));
  const drill = (patch: ExplorerQuery) => update(drillNavigation(nav, patch));
  const reset = () => { const next: Navigation = { view: nav.view, congress: String(info.default_congress), chamber: '', q: '', from: '', to: '', type: '', status: '', category: '', severity: '', materialCategory: '', participation: '', provider: '', history: '', access: '', page: 0, kind: '', id: '', committee: '', committeeLevel: '', committeeType: '', month: '', aspect: '', evidence: '', measure: 'transcript', grouping: 'congress', scope: nav.view === 'materials' ? nav.scope : '', retained: '', document_family: '', document_kind: '', format: '', field: '', classification: '', review: '', catalog: '', sort: '', direction: '' }; writeNavigation(next, false); setNav(next); setQueryText(''); };
  const captured = nav.view === 'materials' && nav.scope !== '';
  const dateError = !captured && nav.view !== 'committees' && nav.from && nav.to && nav.from > nav.to;
  const hasDrill = nav.committee || nav.month || nav.aspect || nav.evidence;
  const [filenameInfo, retryFilename] = useRequest(signal => nav.view === 'materials' ? filenameRequest<FilenameCatalogInfo>('/api/info', signal) : Promise.resolve(undefined), [nav.view === 'materials']);
  const catalogInfo = filenameInfo.status === 'ready' ? filenameInfo.value : undefined;
  const openFilename = (id: string) => update({ kind: 'filename_entry', id, catalog: nav.catalog || catalogInfo?.catalog_id || '' }, nav.kind === 'filename_entry');
  const namingVersion = catalogInfo?.house_naming_version;
  const closeDetail = () => {
    if (window.history.state && (window.history.state as { explorerDetail?: boolean }).explorerDetail) window.history.back();
    else update({ kind: '', id: '' }, true);
    headingRef.current?.focus({ preventScroll: true });
  };
  return <div className="explorer">
    <div className="explorer-publication"><span>Export generated {String(reader.publication.generated_at || 'date not recorded').replace('T', ' ').replace('Z', ' UTC')}</span><span>Snapshot <code>{String(reader.publication.publication_id || '').slice(0, 16)}</code></span>{captured && catalogInfo ? <span>Filename catalog <code>{catalogInfo.catalog_id.slice(0, 16)}</code></span> : null}</div>
    <nav className="explorer-tabs" aria-label="Explorer workspaces">{VIEWS.map((view) => <button key={view.key} aria-current={nav.view === view.key ? 'page' : undefined} aria-label={`${view.label}. ${view.key === 'coverage' ? 'Counts of recorded evidence for the current selection.' : VIEW_NOTES[view.key]}`} onClick={() => changeView(view.key)}>{view.label}</button>)}</nav>
    <form className="explorer-filters" aria-label="Filter committee records" onSubmit={(event) => { event.preventDefault(); filter({ q: queryText }); }}>
      <div className="explorer-search"><label><span>Search this workspace</span><span className="explorer-field-reason">{captured ? 'Find a filename or the page it was captured from.' : 'Find a title, vote, note, or other recorded text in this workspace.'}</span><input type="search" value={queryText} onChange={(event) => setQueryText(event.target.value)} placeholder={captured ? 'Filename or source URL' : 'Title or recorded text'} /></label><button type="submit" className="explorer-button" aria-label="Search this workspace with the text in the box">Search</button></div>
      <label><span>Congress</span><span className="explorer-field-reason">Keep one Congress, or search every retained Congress.</span><select value={nav.congress} onChange={(event) => filter({ congress: event.target.value })}><option value="all">All Congresses</option>{info.congresses.map((value) => <option key={value} value={value}>{value}th Congress</option>)}</select></label>
      {nav.view === 'materials' ? <label className="explorer-scope"><span>Show</span><span className="explorer-field-reason">Meeting-linked materials, or the captured-file catalog.</span><select value={nav.scope} onChange={event => { const scope = event.target.value; filter(scope === 'documents' || scope === 'capture-records' || scope === 'all' ? { scope, sort: '', direction: '' } : { scope: '', retained: '', document_family: '', document_kind: '', format: '', field: '', classification: '', review: '', sort: '', direction: '' }); }}><option value="">Committee materials, linked to meetings</option><option value="documents">Captured files from committee sites</option><option value="capture-records">Source and capture records</option><option value="all">All captured records</option></select></label> : null}
      {captured && catalogInfo ? <FilenameFilters nav={nav} info={catalogInfo} onChange={filter} /> : null}
      {captured ? null : <label><span>Chamber</span><span className="explorer-field-reason">House, Senate, joint, or a chamber the source did not record.</span><select value={nav.chamber} onChange={(event) => filter({ chamber: event.target.value })}><option value="">All chambers</option><option value="house">House</option><option value="senate">Senate</option><option value="joint">Joint</option><option value="unknown">Unknown</option></select></label>}
      {!captured && info.supported_filters?.includes('committeeLevel') ? <label><span>Committee level</span><span className="explorer-field-reason">Choose full committees when subcommittee records and unknown levels should drop out.</span><select value={nav.committeeLevel} onChange={event => filter({ committeeLevel: event.target.value === 'full' ? 'full' : '' })}><option value="">Include subcommittees</option><option value="full">Full committees only</option></select></label> : null}
      {!captured && info.supported_filters?.includes('committeeType') ? <label><span>Committee type</span><span className="explorer-field-reason">Standing, select, and the other types recorded for the committee.</span><select value={nav.committeeType} onChange={event => filter({committeeType: event.target.value})}><option value="">All committee types</option>{committeeTypes.map(value => <option key={value} value={value}>{enumLabel(value)}</option>)}</select></label> : null}
      {!captured && nav.view !== 'committees' ? <><label><span>From date</span><span className="explorer-field-reason">{dateFilterReason(nav.view, 'from')}</span><input type="date" value={nav.from} onChange={(event) => filter({ from: event.target.value })} /></label>
      <label><span>Through date</span><span className="explorer-field-reason">{dateFilterReason(nav.view, 'through')}</span><input type="date" value={nav.to} onChange={(event) => filter({ to: event.target.value })} /></label></> : null}
      {nav.view === 'materials' && !captured ? <><label><span>Material type</span><span className="explorer-field-reason">Documents, recordings, or text products linked to a meeting.</span><select value={nav.type} onChange={(event) => filter({ type: event.target.value })}><option value="">All types</option><option value="document">Document</option><option value="recording">Recording</option><option value="text">Text product</option></select></label>
      <label><span>Document category</span><span className="explorer-field-reason">Statement, amendment, transcript, and the other recorded categories. Records without that category, including most recordings, drop out.</span><select value={nav.materialCategory} onChange={event => filter({ materialCategory: event.target.value })}><option value="">All categories</option>{materialCategories.map(value => <option key={value} value={value}>{enumLabel(value)}</option>)}</select></label>
      <label><span>Provider</span><span className="explorer-field-reason">YouTube, Senate.gov, C-SPAN, and the other sites that published the file. Records from other providers drop out.</span><select value={nav.provider} onChange={event => filter({ provider: event.target.value })}><option value="">All providers</option>{materialProviders.map(value => <option key={value} value={value}>{providerLabel(value)}</option>)}</select></label></> : null}
      {nav.view === 'meetings' || nav.view === 'coverage' ? <label><span>Meeting type</span><span className="explorer-field-reason">Hearing, markup, business meeting, and the other recorded types.</span><select value={nav.type} onChange={event => filter({type: event.target.value})}><option value="">All types</option><option value="hearing">Hearing</option><option value="markup">Markup</option><option value="business">Business meeting</option><option value="meeting">Meeting</option><option value="briefing">Briefing</option><option value="roundtable">Roundtable</option><option value="field_hearing">Field hearing</option><option value="other">Other</option><option value="unknown">Unknown</option></select></label> : null}
      {info.supported_filters?.includes('access') && (nav.view === 'meetings' || nav.view === 'coverage') ? <label><span>Access</span><span className="explorer-field-reason">Whether the meeting was recorded as open, closed, or partly closed.</span><select value={nav.access} onChange={event => filter({access: event.target.value})}><option value="">All access states</option>{accessStates.map(value => <option key={value} value={value}>{enumLabel(value)}</option>)}</select></label> : null}
      {nav.view === 'meetings' || nav.view === 'coverage' ? <label><span>Meeting status</span><span className="explorer-field-reason">Upcoming, past, and today come from the schedule. Canceled and postponed stay as recorded.</span><select value={nav.status} onChange={event => filter({ status: event.target.value })}><option value="">All statuses</option><option value="upcoming">Upcoming</option><option value="past">Past</option><option value="today">Today</option><option value="postponed">Postponed</option><option value="canceled">Canceled</option></select></label> : null}
      {nav.view === 'witnesses' ? <label><span>Participation</span><span className="explorer-field-reason">Testified means the record says the witness testified. Listed is everyone else on the witness list.</span><select value={nav.participation} onChange={event => filter({ participation: event.target.value === 'testified' || event.target.value === 'listed' ? event.target.value : '' })}><option value="">All participation</option><option value="testified">Testified</option><option value="listed">Listed</option></select></label> : null}
      {nav.view === 'gaps' ? <><label><span>Issue status</span><span className="explorer-field-reason">Open issues still need work. Resolved and dismissed are closed.</span><select value={nav.status} onChange={(event) => filter({ status: event.target.value })}><option value="">All statuses</option><option value="open">Open</option><option value="resolved">Resolved</option><option value="dismissed">Dismissed</option></select></label>
      <label><span>Issue history</span><span className="explorer-field-reason">Retained history comes from an earlier input and is not in the latest inputs. Current issues are.</span><select value={nav.history} onChange={event => filter({ history: event.target.value === 'current' || event.target.value === 'retained' ? event.target.value : '' })}><option value="">All issues</option><option value="current">Current</option><option value="retained">Retained history</option></select></label>
      <label><span>Issue category</span><span className="explorer-field-reason">Unlinked has no meeting match. Unverified and conflicting describe the recorded comparison. Duplicate and incorrect name a repeated or wrong recorded value.</span><select value={nav.category} onChange={event => filter({ category: event.target.value })}><option value="">All categories</option>{issueCategories.map(category => <option key={category} value={category}>{enumLabel(category)}</option>)}</select></label>
      <label><span>Severity</span><span className="explorer-field-reason">Affects interpretation changes how a record should be read. Informational does not.</span><select value={nav.severity} onChange={event => filter({ severity: event.target.value })}><option value="">All severities</option><option value="affects_interpretation">Affects interpretation</option><option value="informational">Informational</option></select></label></> : null}
      <button type="button" className="explorer-text-button" aria-label="Reset every filter to this workspace’s defaults" onClick={reset}>Reset</button>
    </form>
    {hasDrill ? <div className="explorer-subheading"><p className="explorer-note">{coverageDrillNote({ committee: nav.committee ? info.committee_labels?.[nav.committee] || 'the selected committee' : '', month: nav.month, aspect: nav.aspect, evidence: nav.evidence })}</p><button className="explorer-text-button" aria-label="Remove the committee, month, and evidence limits that came from a coverage chart" onClick={() => filter({ committee: '', month: '', aspect: '', evidence: '' })}>Clear chart filters</button></div> : null}
    {nav.congress === 'all' && !captured ? <p className="explorer-note">All-Congress queries search the full retained archive and may take longer.</p> : null}
    {nav.view === 'gaps' && nav.congress !== 'all' ? <p className="explorer-note">Issues with no recorded Congress are listed under All Congresses.</p> : null}
    {nav.view === 'materials' && nav.scope === '' && nav.congress !== 'all' ? <p className="explorer-note">Recordings and documents with no recorded Congress are listed under All Congresses.</p> : null}
    {!captured && nav.view !== 'committees' && (nav.from || nav.to) ? <p className="explorer-note">{nav.view === 'gaps' ? 'Issues with no date are left out of this range. The detected day on a row does not keep it.' : nav.view === 'witnesses' ? 'Witnesses with no date are left out of this range.' : 'A record with no date stays in this range when its scheduled day does. Records with neither are left out.'}</p> : null}
    {captured && catalogInfo ? <CapturedCatalogNote info={catalogInfo} /> : null}
    {query.committeeLevel === 'full' ? <p className="explorer-note">Full committees only excludes subcommittee records and records whose committee level is unknown.</p> : null}
    <section ref={headingRef} tabIndex={-1} className="explorer-workspace" aria-label="Explorer results">
      {dateError ? <p className="explorer-alert" role="alert">The start date must be on or before the end date.</p> : selection?.kind === 'filename_entry' ? <FilenameInspector id={selection.id} catalog={nav.catalog} namingVersion={namingVersion} onOpen={openFilename} onClose={closeDetail} /> : selection ? <Inspector key={`${selection.kind}/${selection.id}`} reader={reader} selected={selection} onSelect={select} onOpenFilename={openFilename} namingVersion={namingVersion} committeeLabels={info.committee_labels} onClose={closeDetail} /> : nav.view === 'coverage' ? <CoverageView reader={reader} query={query} onDrill={drill} measure={nav.measure} grouping={nav.grouping} onSettings={update} /> : captured ? (catalogInfo ? <FilenameListing nav={nav} info={catalogInfo} onOpen={row => openFilename(row.source_id || (row._row == null ? '' : String(row._row)))} onPage={page => update({ page })} onSort={patch => update({ ...patch, page: 0 })} /> : <RequestMessage state={filenameInfo.status === 'ready' ? { status: 'error', message: 'The filename catalog did not load.' } : filenameInfo} retry={retryFilename} noun="the filename catalog" />) : <Listing reader={reader} query={query} view={nav.view} info={info} nav={nav} onSelect={select} onPage={(page) => update({ page })} onSort={patch => update({ ...patch, page: 0 })} />}
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
      return <tr key={index}><th scope="row">{String(scope.provider)}{group.length > 1 ? <span className="explorer-row-meta">{integer(group.length)} scopes</span> : null}</th><td>{enumLabel(scope.status)}</td><td>{group.length === 1 ? enumLabel(scope.scope) : `${integer(group.length)} source scopes`}<span className="explorer-row-meta">{String(scope.explanation)}</span>
        <details><summary>{group.length > 1 ? `Show all ${integer(group.length)} exact scopes` : 'Scope details'}<span className="explorer-field-reason">The exact source scope, subject dates, and input snapshots.</span></summary><ul className="explorer-values">{group.map((item, itemIndex) => <li key={itemIndex}><strong>{String(item.scope)}</strong><span className="explorer-row-meta">Subject dates: {fields(item.coverage).start || fields(item.coverage).end ? `${String(fields(item.coverage).start || 'Unknown')} to ${String(fields(item.coverage).end || 'Unknown')}` : 'Not recorded'}</span><span className="explorer-row-meta">Input snapshots: {Array.isArray(item.input_snapshot_ids) && item.input_snapshot_ids.length ? item.input_snapshot_ids.join(', ') : 'None recorded'}</span></li>)}</ul></details>
      </td></tr>;
    })}</tbody></table></div> : <p className="explorer-note">Collection scope has not been described for this publication.</p>}
    {limitations.length ? <ul className="explorer-note">{limitations.map((limitation, index) => <li key={index}>{String(limitation)}</li>)}</ul> : null}
    <details><summary>Input freshness and collection attempts<span className="explorer-field-reason">When each input was observed, attempted, and imported.</span></summary><p className="explorer-note">Import and export times do not establish when a source was fetched or last checked. An unrecorded observation date stays unknown.</p>
      <div className="explorer-table-scroll"><table className="explorer-table explorer-input-freshness"><thead><tr><th scope="col">Input</th><th scope="col">Last source observation</th><th scope="col">Last attempt</th><th scope="col">Import time</th></tr></thead><tbody>{inputs.map((input, index) => <tr key={index}><th scope="row">{String(input.provider)}<span className="explorer-row-meta">{Array.isArray(input.limitations) ? input.limitations.join(' ') : ''}</span></th><td data-label="Last source observation">{input.last_observed_at ? recordedInstant(String(input.last_observed_at)) : 'Not recorded'}</td><td data-label="Last attempt">{enumLabel(input.last_attempt_status) || 'Unknown'}<span className="explorer-row-meta">{input.last_attempt_at ? recordedInstant(String(input.last_attempt_at)) : 'Date not recorded'}</span></td><td data-label="Import time">{input.imported_at ? recordedInstant(String(input.imported_at)) : 'Not recorded'}</td></tr>)}</tbody></table></div>
    </details>
  </section>;
}

function listingColumns(view: Exclude<View, 'coverage'>, groupedCommittees: boolean): readonly (readonly [Navigation['sort'], string, string])[] {
  const record: readonly [Navigation['sort'], string, string] = ['record', view === 'witnesses' ? 'Recorded name' : view === 'gaps' ? 'Known issue' : 'Record', 'the record name'];
  const when: readonly [Navigation['sort'], string, string] = view === 'committees'
    ? ['congress', 'Congress', 'Congress']
    : ['date', view === 'witnesses' ? 'Date / Congress' : 'Date / status', 'the recorded date'];
  const detail: readonly [Navigation['sort'], string, string] = view === 'committees'
    ? ['kind', groupedCommittees ? 'Latest type / level' : 'Type / level', 'committee type']
    : view === 'witnesses'
      ? ['kind', 'Position / organization', 'position or organization']
      : view === 'gaps'
        ? ['kind', 'Category / severity', 'issue category and severity']
        : ['congress', 'Congress / type', 'Congress'];
  return [record, when, detail];
}

const VIEW_NOTES: Record<Exclude<View, 'coverage'>, string> = {
  meetings: 'Committee meetings, including scheduled, postponed and canceled entries.',
  committees: 'Browse each committee’s documents, recordings and meetings by Congress.',
  materials: 'Documents and recordings from collected sources, including items without a matched meeting.',
  witnesses: 'Witnesses listed by meeting. A listing does not confirm attendance.',
  gaps: 'Known collection and matching issues. Coverage shows which material remains unchecked.',
};

const subjectKinds = new Set(['meeting', 'material', 'appearance', 'committee_term']);

function useWitnessLines(reader: ExplorerReader, rows: readonly { id: string; title?: string | null; search_text?: string | null }[]): ReadonlyMap<string, readonly string[]> {
  const key = rows.map(row => row.id).sort().join('|');
  const [state] = useRequest(signal => key ? reader.listWitnesses(rows.map(row => row.id), { signal }) : Promise.resolve([]), [reader, key]);
  const lines = new Map<string, readonly string[]>();
  if (state.status === 'ready') {
    const names = new Map<string, string[]>();
    for (const witness of state.value) names.set(witness.meeting_id, [...(names.get(witness.meeting_id) || []), witness.title]);
    for (const row of rows) lines.set(row.id, witnessNameList(recordedWitnesses(row), names.get(row.id) || []));
  }
  return lines;
}

function useSubjectTitles(reader: ExplorerReader, rows: readonly { subject_kind?: string | null; subject_id?: string | null }[]): ReadonlyMap<string, string> {
  const cache = useRef(new Map<string, string>());
  const [, refresh] = useState(0);
  const missing = rows.flatMap(row => {
    const kind = row.subject_kind || '';
    const id = row.subject_id || '';
    return kind && id && subjectKinds.has(kind) && !cache.current.has(`${kind}/${id}`) ? [{ kind, id }] : [];
  });
  const key = missing.map(ref => `${ref.kind}/${ref.id}`).sort().join('|');
  const [state] = useRequest(signal => key ? reader.getRecords(missing, { signal }) : Promise.resolve([]), [reader, key]);
  useEffect(() => {
    if (state.status !== 'ready' || !state.value) return;
    let changed = false;
    state.value.forEach((record, index) => {
      const ref = missing[index];
      if (!ref) return;
      const id = `${ref.kind}/${ref.id}`;
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

function RecordedNote({ text, summary, reason }: { text: string; summary: string; reason: string }) {
  const note = recordedTitlePreview(text);
  return <span><span className="explorer-row-meta explorer-recorded-lines">{note.preview}</span><RemainingNotes values={note.rest} noun="line" reason={reason} limit={0} plain summary={summary} /></span>;
}

function RemainingNotes({ values, noun, reason, limit, label, summary, plain = false }: { values: readonly string[]; noun: string; reason: string; limit: number; label?: string; summary?: string; plain?: boolean }) {
  if (!values.length) return null;
  const rest = values.slice(limit);
  const className = plain ? 'explorer-row-meta explorer-recorded-lines' : 'explorer-row-meta explorer-clamp';
  return <>
    {label ? <span className="explorer-row-meta">{label}</span> : null}
    {values.slice(0, limit).map((value, index) => <span className={className} title={value} key={index}>{value}</span>)}
    {rest.length ? <details className="explorer-row-meta"><summary>{summary || `${rest.length} more recorded ${rest.length === 1 ? noun : noun.endsWith('s') ? `${noun}es` : `${noun}s`}`}<span className="explorer-field-reason">{reason}</span></summary>{rest.map((value, index) => <span className={className} title={value} key={index}>{value}</span>)}</details> : null}
  </>;
}

function Listing({ reader, query, view, info, nav, onSelect, onPage, onSort }: { reader: ExplorerReader; query: ExplorerQuery; view: Exclude<View, 'coverage'>; info: QueryInfo; nav: Navigation; onSelect: (ref: ExplorerRecordRef) => void; onPage: (page: number) => void; onSort: (patch: Pick<Navigation, 'sort' | 'direction'>) => void }) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<QueryResult>((signal) => reader.search(query, { signal }), [reader, key]);
  const shown = useRef<{ view: typeof view; value: QueryResult } | null>(null);
  if (state.status === 'ready') shown.current = { view, value: state.value };
  const visible = shown.current?.view === view ? shown.current.value : null;
  const title = VIEWS.find((item) => item.key === view)!.label;
  const groupedCommittees = view === 'committees' && query.congress === 'all';
  const subjectTitles = useSubjectTitles(reader, view === 'gaps' && visible ? visible.rows : []);
  const meetingLookups = (view === 'witnesses' || view === 'materials') && visible ? visible.rows.flatMap(row => linkedMeetingIds(row).map(id => ({ subject_kind: 'meeting', subject_id: id }))) : [];
  const seenMeetings = new Set<string>();
  const meetingRefs = meetingLookups.filter(ref => seenMeetings.has(ref.subject_id) ? false : seenMeetings.add(ref.subject_id));
  const meetingTitles = useSubjectTitles(reader, meetingRefs);
  const witnessLines = useWitnessLines(reader, view === 'meetings' && visible ? visible.rows : []);
  const noun = view === 'committees' ? (visible?.total === 1 ? 'committee' : 'committees') : view === 'witnesses' ? (visible?.total === 1 ? 'appearance' : 'appearances') : (visible?.total === 1 ? 'record' : 'records');
  return <>
    <div className="explorer-subheading"><h2>{title}</h2>{visible ? <><span className="explorer-muted">{state.status === 'loading' ? 'Updating the list' : `${integer(visible.total)} ${noun}`}</span>{state.status === 'ready' ? <button className="explorer-text-button" aria-label="Download the rows on this page as JSON. This is not the full result." onClick={() => downloadJson(`committee-explorer-${view}-page-${Math.floor(visible.offset / PAGE_SIZE) + 1}.json`, { scope: 'selection', publication_id: reader.publication.publication_id, schema_version: reader.publication.schema_version, filters: query, total: visible.total, offset: visible.offset, rows: visible.rows })}>Download this page (JSON)</button> : null}</> : null}</div>
    <p className="explorer-note">{groupedCommittees ? 'Each committee appears once. Choose a Congress to see its name, classification and records for that term.' : VIEW_NOTES[view]} Column headings sort this full selection. {view === 'committees' ? 'A third click restores the original list order.' : 'A third click restores newest recorded date first.'}</p>
    {state.status === 'error' ? <RequestMessage state={state} retry={retry} /> : null}
    {state.status === 'loading' && !visible ? <RequestMessage state={state} retry={retry} /> : null}
    {visible?.rows.length ? <>
      {state.status === 'loading' ? <p className="explorer-note" role="status">Updating the list.</p> : null}
      <div className="explorer-table-scroll"><table className="explorer-table" aria-busy={state.status === 'loading'}><thead><tr>
        {listingColumns(view, groupedCommittees).map(([column, label, reason]) => {
          const direction = nav.sort === column ? nav.direction : '';
          const restore = view === 'committees' ? 'restore the original list order' : 'restore newest recorded date first';
          return <th key={column} scope="col" aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'}><button type="button" className="explorer-sort" data-direction={direction} onClick={() => onSort(nextSort(nav, column))} aria-label={direction === 'asc' ? `Sort by ${reason}, ascending. Activate to sort descending.` : direction === 'desc' ? `Sort by ${reason}, descending. Activate to ${restore}.` : `Sort by ${reason}`}>{label}</button></th>;
        })}
      </tr></thead><tbody>
        {visible.rows.map(row => {
          const filenames = view === 'materials' ? recordedFileNames(row.files) : [];
          const addresses = view === 'materials' ? recordedAddressNames(row) : [];
          const formats = view === 'materials' ? recordedFormatNote(row.files) : '';
          const filename = filenames[0] || '';
          const action = view === 'materials' ? recordedAction(row).split(' · ').filter(part => !filename.toLowerCase().includes(part.toLowerCase())).join(' · ') : '';
          const recording = view === 'materials' && !filename ? recordingIdentity(row.recording_url) : '';
          const provider = providerLabel(row.provider);
          const shownProvider = provider && !recording.toLowerCase().includes(provider.toLowerCase()) ? provider : '';
          const parent = view === 'committees' && row.parent_committee_id ? info.committee_labels?.[row.parent_committee_id] || '' : '';
          const label = (view === 'materials' && listTitle(row)) || recordTitle(row);
          const subjectKey = view === 'gaps' && row.subject_kind && row.subject_id ? `${row.subject_kind}/${row.subject_id}` : '';
          const subjectKnown = Boolean(subjectKey && subjectTitles.has(subjectKey));
          const about = subjectKnown ? subjectTitles.get(subjectKey) || '' : '';
          const absentSubject = subjectKnown && !about ? subjectAbsentNote(row.subject_kind) : '';
          const unnamedSubject = view === 'gaps' && !subjectKnown && !about ? subjectKindLabel(row.subject_kind) : '';
          const website = view === 'committees' ? publicUrl(committeeWebsite(row)) : '';
          const earlierNames = view === 'committees' ? earlierCommitteeNames(row.terms, label) : [];
          const votes = view === 'meetings' ? recordedVotes(row) : [];
          const amendments = view === 'meetings' ? recordedAmendments(row) : [];
          const measures = view === 'meetings' ? recordedMeasureValues(row) : [];
          const recordedNames = view === 'meetings' ? recordedWitnesses(row) : '';
          const witnesses = view === 'meetings' ? witnessLines.get(row.id) || (recordedNames ? [recordedNames] : []) : [];
          const committeeKind = view === 'committees' ? '' : [committeeKindNote(row, info.committee_labels), committeeLevelNote(row, info.committee_labels)].filter(Boolean).join(' · ');
          const roleNote = view === 'witnesses' ? notableRoles(row).join(', ') : '';
          const participation = view === 'witnesses' ? participationNote(row) : '';
          const materialType = view === 'materials' ? documentType(row) || [row.type, row.category].filter((value, index, list) => value && value !== 'unknown' && list.indexOf(value) === index).map(enumLabel).join(' · ') : '';
          const materialCategory = view === 'materials' && documentType(row) ? categoryNote(row) : '';
          const materialPart = view === 'materials' ? filePartNote(row) : '';
          const materialSource = view === 'materials' ? documentSourceLabel(row) : '';
          const history = row.selection === 'retained_history' ? <span className="explorer-row-meta">Retained from an earlier input. Not present in the latest inputs.</span> : null;
          const meetings = (view === 'witnesses' || view === 'materials') ? linkedMeetingIds(row).flatMap(id => {
            const title = meetingTitles.get(`meeting/${id}`) || '';
            return title && !sameRecordedTitle(title, label) ? [[id, title] as const] : [];
          }) : [];
          const titlePreview = recordedTitlePreview(label);
          return <tr key={`${row.kind}/${row.id}`}>
          <td className="explorer-title-cell"><button className="explorer-text-button" title={about ? `${label} — ${about}` : absentSubject ? `${label} — ${absentSubject}` : unnamedSubject ? `${label} — about a ${unnamedSubject}` : label} aria-label={about ? `Open ${label}, about ${about}` : absentSubject ? `Open ${label}. ${absentSubject}` : unnamedSubject ? `Open ${label}, about a ${unnamedSubject}` : `Open ${label}`} onClick={() => onSelect(row)}>{titlePreview.preview}</button>
            <RemainingNotes values={titlePreview.rest} noun="line" reason="The rest of the title, in the order it was recorded." limit={0} plain summary={titlePreview.continued ? 'Rest of the recorded title' : titlePreview.rest.length === 1 ? '1 more line of the recorded title' : `${titlePreview.rest.length} more lines of the recorded title`} />
            {about ? <RecordedNote text={`About ${about}`} summary="Rest of the subject title" reason="The rest of the title of the record this issue describes." /> : absentSubject ? <span className="explorer-row-meta">{absentSubject}</span> : unnamedSubject ? <span className="explorer-row-meta">About a {unnamedSubject}</span> : null}
            {view === 'gaps' ? issueNotes(row).map((note, index) => <RecordedNote text={note} summary="Rest of the issue note" reason="The rest of this issue note, in the order it was recorded." key={index} />) : null}
            {view === 'gaps' ? <RemainingNotes values={extraIssueAlternatives(row)} noun="alternative" reason="Other recorded values compared with the selected value." limit={0} /> : null}
            {meetings.map(([id, title]) => {
              const meetingTitle = recordedTitlePreview(title);
              return <span key={id}><span className="explorer-row-meta explorer-recorded-lines" title={title}>{meetingTitle.preview}</span><RemainingNotes values={meetingTitle.rest} noun="line" reason="The rest of the meeting title, in the order it was recorded." limit={0} plain summary={meetingTitle.continued ? 'Rest of the meeting title' : meetingTitle.rest.length === 1 ? '1 more line of the meeting title' : `${meetingTitle.rest.length} more lines of the meeting title`} /></span>;
            })}
            {view === 'committees' ? <RemainingNotes values={earlierNames} noun="name" reason="Names recorded for this committee in another Congress." limit={0} summary={earlierNames.length === 1 ? '1 earlier recorded name' : `${earlierNames.length} earlier recorded names`} /> : null}
            {view === 'committees' && row.explanation ? <RecordedNote text={row.explanation} summary="Rest of the committee note" reason="The rest of the committee note, in the order it was recorded." /> : null}
            {website ? <a className="explorer-row-meta" href={website} target="_blank" rel="noreferrer">{website.replace(/^https?:\/\//, '')}</a> : null}
            {filename && filename !== label ? <span className="explorer-row-meta">{filename}</span> : null}
            {addresses.map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
            {filenames.slice(1).map(name => <span className="explorer-row-meta" key={name}>{name}</span>)}
            {formats ? <span className="explorer-row-meta">{formats}</span> : null}
            {view === 'materials' && landingPageNote(row) ? <span className="explorer-row-meta">{landingPageNote(row)}</span> : null}
            {action ? <span className="explorer-row-meta">{action}</span> : null}
            {recording ? <span className="explorer-row-meta">{recording}</span> : null}
            <span className="explorer-row-meta">{[enumLabel(row.chamber), ...(view === 'committees' ? [] : row.committee_ids || []).map(id => info.committee_labels?.[id]).filter(Boolean), committeeKind, view === 'meetings' && row.access && row.access !== 'unknown' ? enumLabel(row.access) : '', shownProvider].filter(Boolean).join(' · ')}</span>
            {view === 'meetings' && recordedPlace(row) ? <span className="explorer-row-meta explorer-place">{recordedPlace(row)}</span> : null}
            {view === 'meetings' ? <RemainingNotes values={witnesses} noun="witness" reason="People listed for this meeting. A listing does not confirm attendance." limit={4} label={witnesses.length ? 'Witnesses' : undefined} /> : null}
            {view === 'meetings' ? <RemainingNotes values={measures} noun="measure" reason="Bills, resolutions, treaties, and nominations recorded for this meeting." limit={4} /> : null}
            {view === 'meetings' && evidenceParts(row.evidence_states).length ? <span className="explorer-evidence">{evidenceParts(row.evidence_states).map(item => <span key={item}>{item}</span>)}</span> : null}
            {view === 'meetings' ? <RemainingNotes values={votes} noun="vote" reason="Roll-call and voice-vote results recorded for this meeting." limit={2} /> : null}
            {view === 'meetings' ? <RemainingNotes values={amendments} noun="amendment" reason="Amendment outcomes recorded for this meeting." limit={2} /> : null}
            {view === 'materials' && row.explanation ? <RecordedNote text={row.explanation} summary="Rest of the recorded note" reason="The rest of the note, in the order it was recorded." /> : null}
          </td>
          <td>{view !== 'committees' ? (keepDate((row.date || '').slice(0, 10)) || ((view === 'materials' || view === 'meetings') && scheduleNote(row) ? null : <span className="explorer-unknown">Date unrecorded</span>)) : null}{view !== 'committees' && (row.date || '').slice(0, 10) && recordedWhen(row).time ? <span className="explorer-row-meta">{recordedWhen(row).time}</span> : null}{(view === 'materials' || view === 'meetings') && scheduleNote(row) ? <span className="explorer-row-meta">{keepDate(scheduleNote(row))}</span> : null}{view === 'materials' && publishedNote(row) ? <span className="explorer-row-meta">{keepDate(publishedNote(row))}</span> : null}{view === 'materials' && meetingStatusNote(row) ? <span className="explorer-row-meta">{meetingStatusNote(row)}</span> : null}{view === 'gaps' && detectedNote(row) ? <span className="explorer-row-meta explorer-nowrap">{keepDate(detectedNote(row))}</span> : null}<span className={view === 'committees' ? undefined : 'explorer-row-meta'}>{view === 'committees' && row.terms ? <span className="explorer-congress-terms">{row.terms.map(term => <button key={term.id} className="explorer-text-button" title={`${term.title} — ${term.congress}th Congress. Open this committee’s term.`} aria-label={`View ${term.title}, ${term.congress}th Congress`} onClick={() => onSelect(term)}>{term.congress}th</button>)}</span> : view === 'committees' || view === 'witnesses' ? row.congress ? <span className="explorer-nowrap">{row.congress}th Congress</span> : 'Congress unrecorded' : <>{row.status ? <span className="explorer-status">{enumLabel(row.status)}</span> : null}{row.source_status && row.source_status !== row.status ? <span className="explorer-row-meta">Recorded as {enumLabel(row.source_status)}</span> : null}</>}</span>{row.issue_count ? <span className="explorer-row-meta">{integer(row.issue_count)} known {row.issue_count === 1 ? 'issue' : 'issues'}</span> : null}{sourceCountNote(row) ? <span className="explorer-row-meta explorer-nowrap">{sourceCountNote(row)}</span> : null}</td>
          <td>{view === 'committees' ? <>{committeeTypeLabel(row)}<span className="explorer-row-meta">{[committeeLevelLabel(row) || 'Level unrecorded', row.committee_code].filter(Boolean).join(' · ')}</span>{committeeSourceNote(row) ? <span className="explorer-row-meta">{committeeSourceNote(row)}</span> : null}{parent ? <span className="explorer-row-meta">Subcommittee of {parent}</span> : null}</> : view === 'witnesses' ? <>{row.position || row.roles?.map(enumLabel).join(', ') || 'Position unrecorded'}{row.organization ? <span className="explorer-row-meta">{row.organization}</span> : null}{witnessNotes(row).map(note => <span className="explorer-row-meta" key={note}>{note}</span>)}{roleNote ? <span className="explorer-row-meta">{roleNote}</span> : null}{participation ? <span className="explorer-row-meta">{participation}</span> : null}</> : view === 'materials' ? <>{materialType || 'Type unrecorded'}{materialCategory ? <span className="explorer-row-meta">{materialCategory}</span> : null}{materialPart ? <span className="explorer-row-meta">{materialPart}</span> : null}{materialSource ? <span className="explorer-row-meta">{materialSource}</span> : null}<span className="explorer-row-meta">{row.congress ? `${row.congress}th Congress` : 'Congress unrecorded'}</span>{history}</> : view === 'gaps' ? <>{enumLabel(row.category) || enumLabel(row.type) || 'Category unrecorded'}{row.severity ? <span className="explorer-row-meta">{enumLabel(row.severity)}</span> : null}<span className="explorer-row-meta">{row.congress ? `${row.congress}th Congress` : 'Congress unrecorded'}</span>{history}</> : <>{row.congress ? `${row.congress}th Congress` : 'Congress unrecorded'}<span className="explorer-row-meta">{[documentType(row) || [row.type, row.category].filter((value, index, list) => value && value !== 'unknown' && list.indexOf(value) === index).map(enumLabel).join(' · '), documentSourceLabel(row)].filter(Boolean).join(' · ')}</span>{history}{view === 'meetings' && sourceTypeNote(row) ? <span className="explorer-row-meta">{sourceTypeNote(row)}</span> : null}</>}          </td>
        </tr>;
        })}
      </tbody></table></div><Pagination total={visible.total} offset={visible.offset} count={visible.rows.length} onPage={onPage} />
    </> : state.status === 'ready' ? <div className="explorer-alert"><p>{state.value.total ? 'This page is beyond the available results. Return to the first page to continue.' : 'No records match this selection. Broaden the filters. This does not establish that no such records exist at the source.'}</p>{query.offset ? <button className="explorer-button" aria-label="This page is past the last result. Return to the first page." onClick={() => onPage(0)}>Return to first page</button> : null}</div> : null}
  </>;
}

function CoverageView({ reader, query, onDrill, measure, grouping, onSettings }: { reader: ExplorerReader; query: ExplorerQuery; onDrill: (query: ExplorerQuery) => void; measure: Navigation['measure']; grouping: Navigation['grouping']; onSettings: (patch: Partial<Navigation>) => void }) {
  const key = JSON.stringify(query);
  const [state, retry] = useRequest<CoverageSummary>((signal) => reader.getCoverage({ filters: query, signal }), [reader, key]);
  const shown = useRef<CoverageSummary | null>(null);
  if (state.status === 'ready') shown.current = state.value;
  const summary = state.status === 'ready' ? state.value : shown.current;
  return summary ? <>{state.status === 'loading' ? <p className="explorer-note" role="status">Updating coverage.</p> : null}{state.status === 'error' ? <RequestMessage state={state} retry={retry} noun="coverage for this selection" /> : null}<Coverage summary={summary} onDrill={onDrill} aspect={measure} grouping={grouping} onAspect={measure => onSettings({measure})} onGrouping={grouping => onSettings({grouping})} /></> : <RequestMessage state={state.status === 'ready' ? { status: 'loading' } : state} retry={retry} noun="coverage for this selection" />;
}

function CapturedCatalogNote({ info }: { info: FilenameCatalogInfo }) {
  const filenames = info.downloads?.filenames;
  const documents = info.downloads?.documents;
  return <>
    <p className="explorer-note">These files may not be matched to a meeting.</p>
    {filenames || documents ? <p className="explorer-file-links">{filenames ? <a className="explorer-nowrap" href={filenames}>Download filename catalog</a> : null}{documents ? <a className="explorer-nowrap" href={documents}>Download document catalog</a> : null}</p> : null}
    <details><summary>Catalog snapshot<span className="explorer-field-reason">The catalog identifier for this filename publication.</span></summary><p className="explorer-note">Filename catalog {info.catalog_id}{info.recovery_sha256 ? <> · recovery {info.recovery_sha256}</> : ''}</p></details>
  </>;
}

function FilenameInspector({ id, catalog, namingVersion, onOpen, onClose }: { id: string; catalog: string; namingVersion?: string; onOpen: (id: string) => void; onClose: () => void }) {
  return <article className="explorer-detail"><div className="explorer-subheading"><button className="explorer-text-button" aria-label="Back to the list. Filters stay as they are." onClick={onClose}>← Back to results</button></div>
    <FilenameEvidence entryId={id} catalog={catalog} namingVersion={namingVersion} onOpen={onOpen} />
  </article>;
}

function NamedMeeting({ reader, meetingId, onSelect }: { reader: ExplorerReader; meetingId: string; onSelect: (ref: ExplorerRecordRef) => void }) {
  const [state] = useRequest(signal => reader.getRecord({ kind: 'meeting', id: meetingId }, { signal }), [reader, meetingId]);
  const title = state.status === 'ready' && state.value ? recordTitle(state.value) : '';
  return <p><button className="explorer-text-button" aria-label={title ? `Open the meeting ${title}` : 'Open the meeting this record belongs to'} onClick={() => onSelect({ kind: 'meeting', id: meetingId })}>{title ? `View ${title} →` : 'View meeting →'}</button></p>;
}

function IssueSubject({ reader, record, onSelect }: { reader: ExplorerReader; record: DetailRecord; onSelect: (ref: ExplorerRecordRef) => void }) {
  const row = fields(record);
  const affected = ['meeting', 'material', 'appearance', 'committee_term', 'source_record'].includes(String(row.subject_kind))
    ? { kind: String(row.subject_kind), id: String(row.subject_id) }
    : row.meeting_id ? { kind: 'meeting', id: String(row.meeting_id) } : null;
  const [state] = useRequest(signal => affected ? reader.getRecord(affected, { signal }) : Promise.resolve(undefined), [reader, affected?.kind, affected?.id]);
  if (!affected) return null;
  const title = state.status === 'ready' && state.value ? recordTitle(state.value) : '';
  return <p><button className="explorer-text-button" aria-label={title ? `Open ${title}. This is the record the issue describes.` : 'Open the record this issue describes'} onClick={() => onSelect(affected)}>{title ? `View ${title} →` : 'View affected record →'}</button></p>;
}

function Inspector({ reader, selected, onSelect, onOpenFilename, namingVersion, committeeLabels, onClose }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void; onOpenFilename: (id: string) => void; namingVersion?: string; committeeLabels?: Readonly<Record<string, string>>; onClose: () => void }) {
  const [state, retry] = useRequest<DetailRecord | undefined>((signal) => reader.getRecord(selected, { signal }), [reader, selected.kind, selected.id]);
  return <article className="explorer-detail"><div className="explorer-subheading"><button className="explorer-text-button" aria-label="Back to the list. Filters stay as they are." onClick={onClose}>← Back to results</button>{state.status === 'ready' && state.value ? <button className="explorer-text-button" aria-label="Download this record’s published fields as JSON" onClick={() => downloadJson(`committee-explorer-${selected.kind}-${selected.id}.json`, { scope: 'record', publication_id: reader.publication.publication_id, schema_version: reader.publication.schema_version, record: state.value })}>Download record (JSON)</button> : null}</div>
    {state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun="record details" /> : state.value ? <><RecordDetail record={state.value} onSelect={onSelect} committeeLabels={committeeLabels} affectedAction={state.value.kind === 'data_issue' ? <IssueSubject reader={reader} record={state.value} onSelect={onSelect} /> : undefined} meetingAction={fields(state.value).meeting_id && !['meeting', 'material', 'data_issue'].includes(state.value.kind) ? <NamedMeeting reader={reader} meetingId={String(fields(state.value).meeting_id)} onSelect={onSelect} /> : undefined} catalogEvidence={state.value.kind === 'material' ? <FilenameEvidence files={catalogMatchFiles(state.value)} namingVersion={namingVersion} onOpen={onOpenFilename} /> : null} sourceEvidence={<SourceEvidence reader={reader} record={state.value} />} /><Related key={`${selected.kind}/${selected.id}`} reader={reader} selected={selected} onSelect={onSelect} /></> : <p className="explorer-alert">This record is not present in the selected publication. Its absence does not establish that it was removed at the source.</p>}
  </article>;
}

function SourceEvidence({ reader, record }: { reader: ExplorerReader; record: DetailRecord }) {
  const [open, setOpen] = useState(false);
  const ids = fields(record).source_ids;
  if (!Array.isArray(ids) || !ids.length) return null;
  return <details className="explorer-detail-section" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Source evidence ({ids.length})<span className="explorer-field-reason">The source observations this record was built from.</span></summary>
    {open ? <SourceRecords reader={reader} ids={ids.map(String)} focusName={record.kind === 'appearance' ? recordTitle(record) : ''} /> : null}
  </details>;
}

function FactValue({ label, value }: { label: string; value: string }) {
  const lines = value.split('\n');
  const proseName = label === 'Description' ? 'description' : label === 'Match note' ? 'match note' : label === 'Explanation' ? 'explanation' : label === 'Note' ? 'note' : '';
  if (!proseName) return <>{lines.map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</>;
  const note = recordedTitlePreview(value);
  const name = proseName;
  return <>
    <span>{note.preview}</span>
    {note.rest.length ? <details><summary>Rest of the {name}<span className="explorer-field-reason">The rest of the recorded {name}.</span></summary>{note.rest.map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</details> : null}
  </>;
}

function sourceFocus(name: string): string {
  return name.replace(/^(?:honorable|hon|mr|ms|mrs|dr|miss)\.?\s+/i, '').trim().split(/\s+/).at(-1)?.toLowerCase() || '';
}

function SourceRecords({ reader, ids, focusName = '' }: { reader: ExplorerReader; ids: string[]; focusName?: string }) {
  const [state, retry] = useRequest(signal => reader.getRecords(ids.map(id => ({kind: 'source_record', id})), {signal}), [reader, ids.join(',')]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="source evidence" />;
  const focus = sourceFocus(focusName);
  return <>{state.value.map((source, index) => {
    if (!source) return <p className="explorer-note" key={ids[index]}>Source {index + 1} is unavailable in this publication.</p>;
    const url = publicUrl(sourcePageUrl(fields(source).url));
    const facts = sourceFacts(source);
    const recorded = sourceLinks(source);
    const links = focus.length >= 3 ? [...recorded.links].sort((left, right) => Number(`${right.label} ${right.href}`.toLowerCase().includes(focus)) - Number(`${left.label} ${left.href}`.toLowerCase().includes(focus))) : recorded.links;
    return <div key={source.id}>
      <div className="explorer-subheading"><h4>Source {index + 1}: {recordTitle(source)}</h4>{url ? <a href={url} target="_blank" rel="noreferrer">Open original source ↗</a> : null}</div>
      {facts.length ? <dl className="explorer-facts">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd><FactValue label={label} value={value} /></dd></div>)}</dl> : null}
      <SourceLinkGroups links={links} />
      <SourcePayload source={source} />
    </div>;
  })}</>;
}

function SourcePayload({ source }: { source: object }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>Published source response<span className="explorer-field-reason">The stored source record, including the original payload.</span></summary>
    {open ? <pre><code>{JSON.stringify(source, null, 2)}</code></pre> : null}</details>;
}

function Related({ reader, selected, onSelect }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void }) {
  const sections: Record<string, string[]> = {meeting: ['material', 'appearance', 'data_issue'], appearance: ['material', 'data_issue'], material: ['meeting', 'appearance', 'data_issue'], committee_term: ['committee_term', 'material', 'meeting', 'data_issue']};
  return <div className="explorer-related">{(sections[selected.kind] || []).map(kind => kind === 'material'
    ? <RelatedMaterials key={kind} reader={reader} selected={selected} onSelect={onSelect} />
    : <RelatedSection key={kind} kind={kind} reader={reader} selected={selected} onSelect={onSelect} />)}</div>;
}

function RelatedSection({ reader, selected, onSelect, kind }: { reader: ExplorerReader; selected: ExplorerRecordRef; onSelect: (ref: ExplorerRecordRef) => void; kind: string }) {
  const [page, setPage] = useState(0);
  const [state, retry] = useRequest(signal => reader.getRelated(selected, { kind, offset: page * PAGE_SIZE, limit: PAGE_SIZE, signal }), [reader, selected.kind, selected.id, kind, page]);
  const identity = `${selected.kind}/${selected.id}/${kind}`;
  const shown = useRef<{ identity: string; value: RelatedResult } | null>(null);
  if (state.status === 'ready') shown.current = { identity, value: state.value };
  const visible = shown.current?.identity === identity ? shown.current.value : null;
  const labels: Record<string, string> = { material: 'Documents & recordings', appearance: 'Witnesses', meeting: 'Meetings', committee_term: 'Subcommittees', data_issue: 'Known issues' };
  const witnessLines = useWitnessLines(reader, kind === 'meeting' && visible ? visible.records : []);
  if (!visible) return state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun={labels[kind].toLowerCase()} /> : null;
  if (!visible.records.length) return null;
  return <section className="explorer-detail-section" aria-busy={state.status === 'loading'}>
    {state.status === 'loading' ? <p className="explorer-note" role="status">Updating the list.</p> : null}
    {state.status === 'error' ? <RequestMessage state={state} retry={retry} noun={labels[kind].toLowerCase()} /> : null}
    <h3>{labels[kind]} <span className="explorer-muted">({integer(visible.total)})</span></h3><ul className="explorer-related-list">{visible.records.map(record => {
        const row = fields(record);
        const parts = relatedParts(kind, row);
        const measures = kind === 'meeting' ? recordedMeasureValues(row) : [];
        const votes = kind === 'meeting' ? recordedVotes(row) : [];
        const amendments = kind === 'meeting' ? recordedAmendments(row) : [];
        const alternatives = kind === 'data_issue' ? extraIssueAlternatives(row) : [];
        const loadedWitnesses = kind === 'meeting' ? witnessLines.get(record.id) : undefined;
        const witnessNames = kind === 'meeting' ? loadedWitnesses || (recordedWitnesses(row) ? [recordedWitnesses(row)] : []) : [];
        const title = recordTitle(record);
        const titlePreview = recordedTitlePreview(title);
        return <li key={record.id}>
          <button className="explorer-text-button" aria-label={`Open ${title}`} onClick={() => onSelect(record)}>{titlePreview.preview}</button>
          <RemainingNotes values={titlePreview.rest} noun="line" reason="The rest of the title, in the order it was recorded." limit={0} plain summary={titlePreview.continued ? 'Rest of the recorded title' : titlePreview.rest.length === 1 ? '1 more line of the recorded title' : `${titlePreview.rest.length} more lines of the recorded title`} />
          {parts.length ? <span className="explorer-evidence">{parts.map((part, index) => <span key={`${part.role || 'fact'}-${index}`} className={part.role === 'place' ? 'explorer-place' : part.role === 'status' ? 'explorer-status' : part.role === 'note' ? 'explorer-issue-note' : undefined}>{part.text}</span>)}</span> : null}
          {typeof row.issue_count === 'number' && row.issue_count > 0 ? <span className="explorer-row-meta">{integer(row.issue_count)} known {row.issue_count === 1 ? 'issue' : 'issues'}</span> : null}
          <RemainingNotes values={witnessNames} noun="witness" reason="People listed for this meeting. A listing does not confirm attendance." limit={4} label={witnessNames.length ? 'Witnesses' : undefined} />
          <RemainingNotes values={measures} noun="measure" reason="Bills, resolutions, treaties, and nominations recorded for this meeting." limit={4} />
          <RemainingNotes values={votes} noun="vote" reason="Roll-call and voice-vote results recorded for this meeting." limit={2} />
          <RemainingNotes values={amendments} noun="amendment" reason="Amendment outcomes recorded for this meeting." limit={2} />
          <RemainingNotes values={alternatives} noun="alternative" reason="Other recorded values compared with the selected value." limit={0} />
        </li>;
      })}</ul>
    {visible.total > PAGE_SIZE ? <Pagination total={visible.total} offset={visible.offset} count={visible.records.length} onPage={setPage} /> : null}
  </section>;
}
