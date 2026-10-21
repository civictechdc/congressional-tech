import { useEffect, useRef, useState, type ReactNode } from 'react';
import { captureNotes, checkedAtNote, congressLabel, contentAddressedFilename, contentCongressLabel, contentCongressNote, congressWarning, contentKindNote, documentKindLabel, documentKindName, fieldLabel, filenameIdentity, filenameOriginLabel, filenameReadings, formatLabel, httpStatusNote, kindBasis, listedKindLines, measureLabel, pretty, readableValue, recordLabel, recoveredSourceHost, recoveredSourceUrl, repeatsShownRecord, responseCheckNote, retrievedAtNote, savedBodyNote, savedResponseLabel, serverTypeNote, sourceCommitteeNote, sourceCongressNote, sourceDocumentBasis, sourceDocumentTypeNote, type ShownRecord } from '../browse/filename-presentation.ts';
import { recordedTitlePreview } from '../browse/record-presentation.ts';
import { filenameDate } from '../browse/filename-rules.ts';
import { appendOriginPage, evidenceGraph, provenanceUrlKey, type ProvenancePage, type ProvenanceEdge, type SourceContext } from '../browse/provenance.ts';
import { filenameRequest } from '../reader/filenames/session.ts';
import type { FilenameEntry, FilenameMatchResult, FilenameRecord, FilenameReview } from '../reader/filenames/types.ts';
import { CopyIcon, ExternalIcon, LinkIcon } from './icons';
import { publicUrl } from './RecordDetail';
import { RequestMessage, integer, useRequest } from './request-state';
import { downloadJson } from './download';

function catalogQuery(catalog?: string): string {
  return catalog ? `catalog=${encodeURIComponent(catalog)}` : '';
}

function entryPath(kind: string, id: string, catalog?: string, extra = ''): string {
  const query = [catalogQuery(catalog), extra].filter(Boolean).join('&');
  return `/api/${kind}/${encodeURIComponent(id)}${query ? `?${query}` : ''}`;
}

const emptyOrigin: SourceContext = { file_url: null, recovered_urls: [], pages: [], redirects: [] };

export function FilenameEvidence({ entryId, catalog, files, onOpen, namingVersion, alreadyShown }: {
  entryId?: string;
  catalog?: string;
  files?: readonly { url?: unknown; saved_copy_sha256?: unknown }[];
  onOpen?: (id: string) => void;
  namingVersion?: string;
  alreadyShown?: ShownRecord;
}) {
  if (entryId) return <EntryPanel key={`${entryId}:${catalog ?? ''}`} id={entryId} catalog={catalog} onOpen={onOpen} namingVersion={namingVersion} />;
  const urls = (files || []).map(file => typeof file.url === 'string' ? file.url : '').filter(Boolean);
  const sha256s = (files || []).map(file => typeof file.saved_copy_sha256 === 'string' ? file.saved_copy_sha256 : '').filter(Boolean);
  if (!urls.length && !sha256s.length) return null;
  return <MatchedFiles urls={urls} sha256s={sha256s} onOpen={onOpen} namingVersion={namingVersion} alreadyShown={alreadyShown} />;
}

function MatchedFiles({ urls, sha256s, onOpen, namingVersion, alreadyShown }: { urls: string[]; sha256s: string[]; onOpen?: (id: string) => void; namingVersion?: string; alreadyShown?: ShownRecord }) {
  const key = JSON.stringify({ urls, sha256s });
  const [picked, setPicked] = useState('');
  const [state, retry] = useRequest(signal => filenameRequest<FilenameMatchResult>(`/api/match?payload=${encodeURIComponent(JSON.stringify({ urls, sha256s }))}`, signal), [key]);
  if (state.status !== 'ready') return <>
    <RequestMessage state={state} retry={retry} noun="matching captured files" />
    {state.status === 'loading' ? <p className="explorer-note">Looking up this document’s web address in the captured files. The rest of this record stays available.</p> : null}
  </>;
  if (!state.value.matches.length) return null;
  const selected = state.value.matches.find(match => match.source_id === picked) || state.value.matches[0];
  return <section className="explorer-detail-section">
    <h3>Matching captured file</h3>
    {state.value.matches.length > 1 ? <label><span>Matched file</span><span className="explorer-field-reason">This committee record matches more than one captured file. Choose which one to read.</span><select aria-label="Matched file. This committee record matches more than one captured file." value={selected.source_id} onChange={event => setPicked(event.target.value)}>{state.value.matches.map((match, index) => <option key={match.source_id} value={match.source_id}>{match.url || (match.sha256 ? `Saved copy ${index + 1}` : `Captured file ${index + 1}`)}</option>)}</select></label> : null}
    {state.value.truncated ? <p className="explorer-note">More than 24 captured files match. Showing the first 24.</p> : null}
    <EntryPanel key={`${selected.source_id}:`} id={selected.source_id} onOpen={onOpen} namingVersion={namingVersion} alreadyShown={alreadyShown} embedded />
  </section>;
}

function EntryPanel({ id, catalog, onOpen, embedded = false, namingVersion, alreadyShown }: { id: string; catalog?: string; onOpen?: (id: string) => void; embedded?: boolean; namingVersion?: string; alreadyShown?: ShownRecord }) {
  const [state, retry] = useRequest(signal => filenameRequest<FilenameEntry>(entryPath('entry', id, catalog), signal), [id, catalog || '']);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="filename details" />;
  return <ReadyEntry entry={state.value} id={id} catalog={catalog} onOpen={onOpen} embedded={embedded} namingVersion={namingVersion} alreadyShown={alreadyShown} />;
}

const identityFields = ['source_chamber', 'source_committee_code', 'source_meeting_type', 'source_meeting_title', 'source_page_title', 'source_page_url'] as const;

function ReadyEntry({ entry, id, catalog, onOpen, embedded, namingVersion, alreadyShown }: { entry: FilenameEntry; id: string; catalog?: string; onOpen?: (id: string) => void; embedded: boolean; namingVersion?: string; alreadyShown?: ShownRecord }) {
  const record = entry.record;
  const missingIdentity = identityFields.some(name => !(name in record));
  const [identity] = useRequest(signal => missingIdentity ? filenameRequest<FilenameRecord>(entryPath('source-identity', id, catalog), signal) : Promise.resolve({} as FilenameRecord), [id, catalog || '', missingIdentity]);
  const sourceRecord = { ...record, ...(identity.status === 'ready' ? identity.value : {}) };
  const saved = publicUrl(entry.saved_file_url);
  const source = publicUrl(sourceRecord.source_url);
  const recovered = publicUrl(recoveredSourceUrl(sourceRecord));
  const title = filenameIdentity({ ...sourceRecord, filename: entry.filename || sourceRecord.filename, api_reference: entry.api_reference, video_reference: entry.video_reference });
  const kind = recordLabel({ ...sourceRecord, document_kind: entry.document.document_kind, video_reference: entry.video_reference, api_reference: entry.api_reference });
  const shownKind = documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: entry.document.document_kind });
  return <>
    {embedded || kind === shownKind ? null : <p className="explorer-record-kind">{kind === 'No category' ? 'Document' : kind}</p>}
    <FilenameHeading title={title} embedded={embedded} />
    {source || recovered || saved || !embedded ? <div className="explorer-actions">{saved ? <a href={saved} target="_blank" rel="noreferrer">Open saved copy <ExternalIcon /></a> : null}{source ? <a href={source} target="_blank" rel="noreferrer">{entry.video_reference ? 'Watch video' : entry.api_reference ? 'Open the official record' : 'Open original source'} <ExternalIcon /></a> : recovered ? <a href={recovered} target="_blank" rel="noreferrer">{recoveredSourceHost(sourceRecord)} <ExternalIcon /></a> : null}{embedded ? null : <EntryActions id={sourceRecord.source_id || id} catalog={entry.catalog_id} documentDownload={entry.document_download_available} />}</div> : null}
    <Summary entry={{ ...entry, record: sourceRecord }} alreadyShown={embedded ? alreadyShown : undefined} />
    <ReviewSection id={record.source_id || id} catalog={entry.catalog_id} />
    <Clues entry={entry} namingVersion={namingVersion} />
    <OriginSection entry={entry} id={record.source_id || id} catalog={entry.catalog_id} />
    <Sources entry={entry} onOpen={onOpen} />
    <TechnicalFields id={record.source_id || id} catalog={entry.catalog_id} />
  </>;
}

function FilenameHeading({ title, embedded }: { title: string; embedded: boolean }) {
  const name = contentAddressedFilename(title)?.name || title;
  return embedded ? <h3>{name}</h3> : <h2>{name}</h2>;
}

function RecordedPreview({ text, name }: { text: string; name: string }) {
  const note = recordedTitlePreview(text);
  return <>
    <span>{note.preview}</span>
    {note.rest.length ? <details><summary>Rest of the {name}<span className="explorer-field-reason">The rest of the recorded {name}.</span></summary>{note.rest.map((line, index) => <span key={index}>{line}</span>)}</details> : null}
  </>;
}

function Summary({ entry, alreadyShown }: { entry: FilenameEntry; alreadyShown?: ShownRecord }) {
  const row = entry.document;
  const source = entry.record;
  const recovery = source.recovery || entry.recovery;
  const warning = congressWarning(source.congress, source.source_congress);
  const committee = sourceCommitteeNote(source);
  const readings = filenameReadings(source);
  const version = readings.find(reading => reading.label === 'Legislative stage');
  const filenameCommittee = readings.find(reading => reading.label === 'Committee');
  const committeeText = committee.text.toLowerCase();
  const meetingType = (source.source_meeting_type || []).map(type => type.toLowerCase());
  const kindLabel = documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: row.document_kind }).toLowerCase();
  const summaryReadings = readings.filter(reading => ['Meeting wording', 'Draft', 'En bloc', 'Nomination', 'Subcommittee', 'Stage', 'Amendment degree', 'Abbreviation', 'Collection', 'Mark', 'Wording', 'Role', 'Context', 'Relation'].includes(reading.label) && !(reading.label === 'Meeting wording' && meetingType.includes(reading.value.toLowerCase())) && !(reading.label === 'Wording' && kindLabel.includes(reading.value.toLowerCase())));
  const measures = (source.measure_references || []).map(measureLabel).filter(Boolean);
  const kindLines = listedKindLines({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: row.document_kind, record_role: source.record_role, filename: source.filename, source_record_type: source.source_record_type, format: source.format });
  const kindText = kindLines.join(' · ');
  const repeated = (label: string, value: string, extra = false) => Boolean(alreadyShown) && !extra && repeatsShownRecord(label, value, alreadyShown || {});
  const documentRows = [
    kindText && !repeated('Document kind', kindText) ? <div key="kind"><dt>Document kind</dt><dd>{kindText}{kindBasis(row) ? <span className="explorer-row-meta">{kindBasis(row)}</span> : row.document_kind_source?.length ? <span className="explorer-row-meta">Based on the filename</span> : null}</dd></div> : null,
    measures.length ? <div key="bill"><dt>Bill or resolution</dt><dd>{measures.join(' · ')}</dd></div> : null,
    <div key="format"><dt>Format</dt><dd>{source.format?.map(formatLabel).join(' · ') || 'Not recorded'}{savedBodyNote(source) ? <span className="explorer-row-meta">{savedBodyNote(source)}</span> : null}{serverTypeNote(source) ? <span className="explorer-row-meta">{serverTypeNote(source)}</span> : null}</dd></div>,
    version ? <div key="stage"><dt>Legislative stage</dt><dd>{version.value}</dd></div> : null,
    ...summaryReadings.map(reading => <div key={reading.label}><dt>{reading.label}</dt><dd>{reading.value}</dd></div>),
  ];
  const congressValue = congressLabel(source.congress) || congressLabel(source.source_congress) || contentCongressLabel(source);
  const congressSource = sourceCongressNote(source.congress, source.source_congress);
  const chamberText = (source.source_chamber || []).map(value => value === 'unknown' ? 'Chamber not recorded' : pretty(value)).filter(Boolean).join(' · ');
  const foundRows = [
    congressValue && !repeated('Congress', congressValue, Boolean(congressSource || warning || contentCongressNote(source) || contentCongressLabel(source))) ? <div key="congress"><dt>Congress</dt><dd>{congressValue}{congressSource ? <span className="explorer-row-meta">{congressSource}</span> : null}{!source.congress?.length && source.source_congress?.length ? <span className="explorer-row-meta">Recorded by the source</span> : null}{contentCongressLabel(source) ? <span className="explorer-row-meta">From the saved contents</span> : null}{contentCongressNote(source) ? <span className="explorer-row-meta">{contentCongressNote(source)}</span> : null}{warning ? <span className="explorer-row-meta">{warning}</span> : null}</dd></div> : null,
    chamberText && !repeated('Chamber', chamberText) ? <div key="chamber"><dt>Chamber</dt><dd>{chamberText}</dd></div> : null,
    committee.text && !repeated('Committee', committee.text) ? <div key="committee"><dt>Committee</dt><dd>{committee.text}{committee.code ? <span className="explorer-row-meta">{committee.code}</span> : null}</dd></div> : null,
    filenameCommittee && !committeeText.includes(filenameCommittee.value.toLowerCase()) ? <div key="filename-committee"><dt>{committee.text ? 'Committee in the filename' : 'Committee'}</dt><dd>{filenameCommittee.value}</dd></div> : null,
    source.source_meeting_title?.length ? <div key="meeting"><dt>Meeting</dt><dd><RecordedPreview text={source.source_meeting_title.join(' · ')} name="meeting title" /></dd></div> : null,
    source.source_meeting_type?.length ? <div key="meeting-type"><dt>Meeting type</dt><dd>{source.source_meeting_type.join(' · ')}</dd></div> : null,
    source.source_page_title?.length ? <div key="page"><dt>Page title</dt><dd><RecordedPreview text={source.source_page_title.join(' · ')} name="page title" /></dd></div> : null,
    source.source_record_type?.length ? <div key="source-type"><dt>Type at the source</dt><dd>{source.source_record_type.map(pretty).join(' · ')}</dd></div> : null,
    sourceDocumentTypeNote(source) ? <div key="page-type"><dt>Document type on the page</dt><dd>{sourceDocumentTypeNote(source)}{sourceDocumentBasis(source) ? <span className="explorer-row-meta">{sourceDocumentBasis(source)}</span> : null}</dd></div> : null,
  ];
  const copyKept = Boolean(source.body_key || source.retained || recovery?.recovery_status === 'recovered');
  const websiteReply = httpStatusNote({ http_status: source.http_status, retained: copyKept });
  const savedRows = [
    <div key="saved"><dt>Status</dt><dd>{[savedResponseLabel({ ...source, retained: copyKept, recovery }), responseCheckNote(source), ...captureNotes(source), checkedAtNote(source), retrievedAtNote(source)].filter(Boolean).map((note, index) => <span className={index ? 'explorer-row-meta' : undefined} key={`${index}-${note}`}>{note}</span>)}</dd></div>,
    websiteReply ? <div key="reply"><dt>Website reply</dt><dd>{websiteReply}</dd></div> : null,
    contentKindNote(source) ? <div key="contents"><dt>Saved contents</dt><dd>{contentKindNote(source)}</dd></div> : null,
  ];
  return <>
    <FactGroup title="What it is" rows={documentRows} embedded={Boolean(alreadyShown)} />
    <FactGroup title="Found on" rows={foundRows} />
    <FactGroup title="The copy" rows={savedRows} />
  </>;
}

function FactGroup({ title, rows, embedded = false }: { title: string; rows: ReactNode[]; embedded?: boolean }) {
  const visible = rows.filter(Boolean);
  if (!visible.length) return null;
  const heading = embedded && title === 'What it is' ? '' : title;
  return <section className="explorer-fact-group">{heading ? <h3>{heading}</h3> : null}<dl className="explorer-facts">{visible}</dl></section>;
}

function EntryActions({ id, catalog, documentDownload }: { id: string; catalog: string; documentDownload?: boolean }) {
  const [copyStatus, setCopyStatus] = useState('');
  const [linkStatus, setLinkStatus] = useState('');
  const [downloadStatus, setDownloadStatus] = useState('');
  const [downloading, setDownloading] = useState(false);
  async function downloadMetadata(kind: 'full' | 'document') {
    setDownloading(true);
    setDownloadStatus('Preparing complete metadata…');
    try {
      const record = await filenameRequest<unknown>(entryPath(kind, id, catalog), new AbortController().signal);
      downloadJson(`${kind === 'document' ? 'document' : 'source'}-${id}.json`, record);
      setDownloadStatus(kind === 'document' ? 'Document downloaded' : 'Source downloaded');
    } catch (error) {
      setDownloadStatus(error instanceof Error ? error.message : 'Could not download complete metadata');
    } finally { setDownloading(false); }
  }
  async function copyJson() {
      setCopyStatus('Preparing the saved record…');
    try {
      const record = await filenameRequest<unknown>(entryPath('full', id, catalog), new AbortController().signal);
      await navigator.clipboard.writeText(JSON.stringify(record, null, 2));
      setCopyStatus('Copied');
    } catch (error) {
      setCopyStatus(error instanceof Error ? error.message : 'Could not copy the saved record');
    }
  }
  async function copyLink() {
    const url = new URL(location.href);
    url.searchParams.set('view', 'materials');
    url.searchParams.set('kind', 'filename_entry');
    url.searchParams.set('id', id);
    if (catalog) url.searchParams.set('catalog', catalog);
    url.searchParams.delete('source');
    url.searchParams.delete('row');
    try {
      await navigator.clipboard.writeText(url.href);
      setLinkStatus('Copied link');
    } catch {
      setLinkStatus('Could not copy the link');
    }
  }
  return <>
    <button className="explorer-icon-button" type="button" aria-label="Copy the saved details for this file. The file itself stays where it is." title="Copy the saved details" onClick={() => void copyJson()}><CopyIcon /></button>
    <button className="explorer-icon-button" type="button" aria-label="Copy a link that opens this file" title="Copy link to this file" onClick={() => void copyLink()}><LinkIcon /></button>
    <button className="explorer-text-button" type="button" disabled={downloading} onClick={() => void downloadMetadata('full')}>Download source JSON</button>
    {documentDownload ? <button className="explorer-text-button" type="button" disabled={downloading} onClick={() => void downloadMetadata('document')}>Download document JSON</button> : null}
    {downloadStatus ? <span className="explorer-row-meta" role="status">{downloadStatus}</span> : null}
    {copyStatus ? <span className="explorer-row-meta">{copyStatus}</span> : null}
    {linkStatus ? <span className="explorer-row-meta">{linkStatus}</span> : null}
  </>;
}

function Clues({ entry, namingVersion }: { entry: FilenameEntry; namingVersion?: string }) {
  const row = entry.record;
  if (entry.video_reference) return null;
  const dates = row.date_token_candidates?.map(filenameDate) || [];
  const readings = filenameReadings(row).filter(reading => !['Legislative stage', 'Meeting wording', 'Draft', 'En bloc', 'Nomination', 'Committee', 'Subcommittee', 'Stage', 'Amendment degree', 'Abbreviation', 'Collection', 'Mark', 'Wording', 'Role', 'Context', 'Relation'].includes(reading.label));
  if (!dates.length && !readings.length && !row.committee_code?.length && !row.filename_origins?.length && !namingVersion) return null;
  return <details className="explorer-detail-section"><summary>What the filename says<span className="explorer-field-reason">Readings taken from the filename. They are not a confirmed category.</span></summary>
    {entry.filename_field_count ? <p className="explorer-note">{integer(entry.filename_field_count)} readings were saved.</p> : null}
    {namingVersion ? <p className="explorer-note">Read with the House filename guide ({namingVersion}).</p> : null}
    <dl className="explorer-facts">
      {readings.map(reading => <div key={reading.label}><dt>{reading.label}</dt><dd>{reading.value}</dd></div>)}
      {dates.length ? <div><dt>Possible date</dt><dd>{dates.join(' · ')}</dd></div> : null}
      {row.committee_code?.length ? <div><dt>Committee code</dt><dd>{row.committee_code.join(' · ')}</dd></div> : null}
      {row.filename_origins?.length ? <div><dt>Filename obtained from</dt><dd>{row.filename_origins.map(filenameOriginLabel).join(' · ')}</dd></div> : null}
    </dl>
  </details>;
}

function ReviewSection({ id, catalog }: { id: string; catalog: string }) {
  const [withdrawn, setWithdrawn] = useState(false);
  const [state, retry] = useRequest(signal => filenameRequest<FilenameReview>(entryPath('review', id, catalog, withdrawn ? 'selection=baseline' : ''), signal), [id, catalog, withdrawn]);
  if (state.status === 'error' && /not configured/i.test(state.message)) return null;
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="the document review" />;
  const review = state.value;
  if (review.status === 'no_review') return null;
  const observed = review.review?.body_observation;
  const labels: Record<string, string> = { candidate_applied: 'A later review suggests a different category', annotation_only_unsupported_forms: 'A later review left the category unchanged', withdrawn: 'The later review is hidden' };
  const body = review.evidence?.body;
  return <details className="explorer-detail-section"><summary>Complete document review<span className="explorer-field-reason">Assistant findings for this file. They are not independently confirmed.</span></summary>
    <p className="explorer-note">{labels[review.status] || review.status}.</p>
    <dl className="explorer-facts">
      <div><dt>Category before review</dt><dd>{review.baseline?.document_kind?.map(documentKindName).join(' · ') || 'No category'}</dd></div>
      <div><dt>Suggested category</dt><dd>{review.selected?.document_kind?.map(documentKindName).join(' · ') || 'No category'}</dd></div>
      {review.review?.primary_forms?.length ? <div><dt>Main kinds found</dt><dd>{review.review.primary_forms.map(documentKindName).join(' · ')}</dd></div> : null}
      {observed?.pages ? <div><dt>Pages reviewed</dt><dd>{integer(observed.pages)}</dd></div> : null}
    </dl>
    <p><button className="explorer-text-button" type="button" aria-label={withdrawn ? 'Show the suggested category again' : 'Hide the suggested category and show the earlier one'} onClick={() => setWithdrawn(value => !value)}>{withdrawn ? 'Show the suggested category' : 'Hide the suggested category'}</button></p>
    {body ? <p><a href={body} download="reviewed-document.pdf">Download the reviewed PDF</a></p> : null}
    {observed?.text_path && review.evidence?.text ? <p><a href={review.evidence.text} target="_blank" rel="noreferrer">Text copied from the file <ExternalIcon /></a></p> : null}
    {observed?.native_text_path && review.evidence?.['native-text'] ? <p><a href={review.evidence['native-text']} target="_blank" rel="noreferrer">Text the file already contained <ExternalIcon /></a></p> : null}
    {review.evidence?.pages && Object.keys(review.evidence.pages).length ? <ul className="explorer-note">{Object.entries(review.evidence.pages).map(([page, href]) => <li key={page}><a href={href} target="_blank" rel="noreferrer">Page {page} image <ExternalIcon /></a></li>)}</ul> : null}
    {observed?.notes ? <p className="explorer-note">{observed.notes}</p> : null}
    {observed?.page_sections?.length ? <ul className="explorer-note">{observed.page_sections.map(part => <li key={`${part.first_page}-${part.last_page}`}>Pages {part.first_page}–{part.last_page}: {part.observed_form.split('|').map(documentKindName).join(' · ')}{part.description ? ` — ${part.description}` : ''}</li>)}</ul> : null}
  </details>;
}

function OriginSection({ entry, id, catalog }: { entry: FilenameEntry; id: string; catalog: string }) {
  const [pages, setPages] = useState<{ origin: SourceContext; next: number | null } | null>(null);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);
  const [state, retry] = useRequest(signal => entry.origin_pending ? filenameRequest<{ origin: SourceContext; next?: number | null }>(entryPath('entry-origin', id, catalog), signal) : Promise.resolve({ origin: entry.origin || emptyOrigin, next: entry.origin_next ?? null }), [id, catalog, entry.origin_pending]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="source pages" />;
  const view = pages || { origin: state.value.origin, next: state.value.next ?? null };
  return <details className="explorer-detail-section"><summary>Where this file came from<span className="explorer-field-reason">Pages that linked to this file, as recorded.</span></summary><OriginGraph origin={view.origin} recoveryUrl={entry.record.recovery?.recovered_url || entry.recovery?.recovered_url} />
    {view.next != null ? <button className="explorer-text-button" type="button" aria-label="Load the next recorded referring pages" onClick={() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const offset = view.next;
      void filenameRequest<{ origin: SourceContext; next?: number | null }>(entryPath('origin', id, catalog, `offset=${offset}&limit=20`), controller.signal).then(page => {
        if (controller.signal.aborted) return;
        setPages(current => appendOriginPage(current || { origin: state.value.origin, next: state.value.next ?? null }, page));
        setError('');
      }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Could not load more source pages'); });
    }}>More source pages</button> : null}
    {error ? <p className="explorer-alert" role="alert">{error}</p> : null}
  </details>;
}

function OriginGraph({ origin, recoveryUrl }: { origin: SourceContext; recoveryUrl?: string }) {
  const graph = evidenceGraph(origin);
  if (!graph.paths.length && !graph.references.length) return <p className="explorer-note">No page that linked to this file was recorded.</p>;
  return <>
    {graph.paths.map((item, index) => <ol key={index}>{item.path.map((edge: ProvenanceEdge, edgeIndex) => <li key={edgeIndex}>{edge.page ? <PageLink pageUrl={edge.page.urls[0]} title={typeof edge.page.titles[0] === 'string' ? edge.page.titles[0] : undefined} /> : edge.redirect ? 'The link was sent somewhere else' : 'Related page'}</li>)}<li>This file</li></ol>)}
    <ReferenceList references={graph.references} />
    <PublisherLabels origin={origin} shown={shownReferenceNames(graph)} />
    {recoveryUrl && publicUrl(recoveryUrl) ? <p className="explorer-note">The saved copy came from <a href={recoveryUrl} target="_blank" rel="noreferrer">{recoveryUrl} <ExternalIcon /></a></p> : null}
  </>;
}

function pageText(pages: ProvenancePage[] | undefined, key: 'titles' | 'link_labels'): string {
  const value = (pages || []).flatMap(page => page[key]).find((item): item is string => typeof item === 'string' && item.trim().length > 0);
  return value?.trim() || '';
}

function referenceName(pages: ProvenancePage[] | undefined): string {
  return pageText(pages, 'link_labels') || pageText(pages, 'titles');
}

function shownReferenceNames(graph: ReturnType<typeof evidenceGraph>): Set<string> {
  const names = graph.references.map(reference => referenceName(reference.pages).toLowerCase());
  for (const item of graph.paths) for (const edge of item.path) {
    if (typeof edge.page?.titles[0] === 'string') names.push(edge.page.titles[0].trim().toLowerCase());
  }
  return new Set(names.filter(Boolean));
}

function ReferenceList({ references }: { references: { url: unknown; pages: ProvenancePage[] }[] }) {
  const item = (entry: { url: unknown; pages: ProvenancePage[] }) => {
    const href = typeof entry.url === 'string' ? entry.url : '';
    const name = referenceName(entry.pages);
    const key = provenanceUrlKey(entry.url) || href;
    return <li key={key}>{publicUrl(href) ? <a href={href} target="_blank" rel="noreferrer">{name || href} <ExternalIcon /></a> : href || 'Web address not recorded'}{name && href ? <span className="explorer-row-meta">{href}</span> : null}</li>;
  };
  const shown = references.slice(0, 12);
  const rest = references.slice(12);
  return <>
    <ul className="explorer-origin-list">{shown.map(item)}</ul>
    {rest.length ? <details><summary>{rest.length} more referring {rest.length === 1 ? 'page' : 'pages'}<span className="explorer-field-reason">Every other recorded web address for this file.</span></summary><ul className="explorer-origin-list">{rest.map(item)}</ul></details> : null}
  </>;
}

function PublisherLabels({ origin, shown }: { origin: SourceContext; shown: Set<string> }) {
  const labels = [...new Set(origin.pages.flatMap(page => page.link_labels.filter((value): value is string => typeof value === 'string' && value.trim().length > 0 && !shown.has(value.trim().toLowerCase()))))];
  if (!labels.length) return null;
  const visible = labels.slice(0, 12);
  const rest = labels.slice(12);
  return <div>{visible.map(label => <blockquote key={label}>{label}</blockquote>)}{rest.length ? <details><summary>{rest.length} more link {rest.length === 1 ? 'label' : 'labels'}<span className="explorer-field-reason">The other words the source page used for this file.</span></summary>{rest.map(label => <blockquote key={label}>{label}</blockquote>)}</details> : null}</div>;
}

function PageLink({ pageUrl, title }: { pageUrl: unknown; title?: string }) {
  const href = typeof pageUrl === 'string' ? publicUrl(pageUrl) : undefined;
  if (!href) return <span>Web address not recorded</span>;
  return <a href={href} target="_blank" rel="noreferrer">{title || href} <ExternalIcon /></a>;
}

function sourceLabel(source: FilenameRecord): string {
  const format = source.format?.map(formatLabel).join(' · ');
  const saved = contentAddressedFilename(source.filename || '');
  return [saved?.name || source.filename, format].filter(Boolean).join(' · ');
}

function Sources({ entry, onOpen }: { entry: FilenameEntry; onOpen?: (id: string) => void }) {
  const [offset, setOffset] = useState(0);
  if (entry.sources.length < 2 || !onOpen) return null;
  const page = entry.sources.slice(offset, offset + 20);
  return <details className="explorer-detail-section"><summary>Other web addresses for this file ({integer(entry.sources.length)})<span className="explorer-field-reason">Other saved addresses grouped with this file.</span></summary>
    <p className="explorer-note">{entry.sources_share_saved_file ? 'These addresses share one saved file.' : 'Each address keeps its own notes.'}</p>
    <ul className="explorer-related-list">{page.map(source => {
      const label = sourceLabel(source);
      const href = source.source_url || '';
      return <li key={source.source_id || href || source.filename}>
        {label && source.source_id ? <button className="explorer-text-button" type="button" aria-label={`Open the captured file ${source.filename || label}`} onClick={() => onOpen(source.source_id!)}>{label}</button> : <span>{label || 'No web address or filename recorded'}</span>}
        {href ? <span className="explorer-row-meta">{href}</span> : null}
        {savedResponseLabel(source) ? <span className="explorer-row-meta">{savedResponseLabel(source)}</span> : null}
      </li>;
    })}</ul>
    <p>{offset ? <button className="explorer-text-button" type="button" aria-label="Previous page of web addresses for this file" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous addresses</button> : null}{offset + 20 < entry.sources.length ? <button className="explorer-text-button" type="button" aria-label="Next page of web addresses for this file" onClick={() => setOffset(value => value + 20)}>Next addresses</button> : null}</p>
  </details>;
}

function TechnicalFields({ id, catalog }: { id: string; catalog: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  return <details className="explorer-detail-section" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>See everything saved<span className="explorer-field-reason">The complete saved file record, including codes used to check it. You do not need it to read this page.</span></summary>
    {open ? <TechnicalBody id={id} catalog={catalog} query={query} onQuery={setQuery} /> : null}
  </details>;
}

function TechnicalBody({ id, catalog, query, onQuery }: { id: string; catalog: string; query: string; onQuery: (value: string) => void }) {
  const [offset, setOffset] = useState(0);
  const [state, retry] = useRequest(signal => filenameRequest<FilenameRecord>(entryPath('technical', id, catalog), signal), [id, catalog]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="recorded fields" />;
  const needle = query.toLowerCase();
  const entries = Object.entries(state.value).filter(([key, value]) => value != null && value !== '' && (!Array.isArray(value) || value.length > 0) && (!needle || `${fieldLabel(key)} ${key} ${JSON.stringify(value)}`.toLowerCase().includes(needle)));
  const shown = entries.slice(offset, offset + 80);
  return <>
    <label><span>Find a saved detail</span><span className="explorer-field-reason">Narrow this list by name or value.</span><input type="search" value={query} onChange={event => { onQuery(event.target.value); setOffset(0); }} placeholder="Name or value" /></label>
    <p className="explorer-note">{integer(shown.length ? offset + 1 : 0)}–{integer(offset + shown.length)} of {integer(entries.length)} saved details</p>
    <dl className="explorer-facts">{shown.map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{readableValue(value).split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</dd></div>)}</dl>
    <p>{offset ? <button className="explorer-text-button" type="button" aria-label="Previous page of saved details" onClick={() => setOffset(value => Math.max(0, value - 80))}>Previous details</button> : null}{offset + 80 < entries.length ? <button className="explorer-text-button" type="button" aria-label="Next page of saved details" onClick={() => setOffset(value => value + 80)}>Next details</button> : null}</p>
    <Observations id={id} catalog={catalog} />
  </>;
}

function ObservationItem({ item, number }: { item: unknown; number: number }) {
  const [open, setOpen] = useState(false);
  const fields = item && typeof item === 'object' ? Object.entries(item as Record<string, unknown>).filter(([, value]) => value != null && value !== '' && (!Array.isArray(value) || value.length > 0)) : [];
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Sighting {number}<span className="explorer-field-reason">One recorded time this file was seen.</span></summary>
    {open ? <dl className="explorer-facts">{fields.map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{readableValue(value).split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</dd></div>)}</dl> : null}
  </details>;
}

function Observations({ id, catalog }: { id: string; catalog: string }) {
  const [offset, setOffset] = useState(0);
  const [state, retry] = useRequest(signal => filenameRequest<{ items: unknown[]; total: number; next: number | null }>(entryPath('observations', id, catalog, `offset=${offset}&limit=20`), signal), [id, catalog, offset]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="times this file was seen" />;
  if (!state.value.total) return <p className="explorer-note">No other sightings were recorded.</p>;
  return <div>
    <h4>Times this file was seen</h4>
    <p className="explorer-note">{integer(offset + 1)}–{integer(offset + state.value.items.length)} of {integer(state.value.total)} sightings</p>
    {state.value.items.map((item, index) => <ObservationItem key={offset + index} item={item} number={offset + index + 1} />)}
    <p>{offset ? <button className="explorer-button" type="button" data-field="source_occurrences" aria-label="Previous page of times this file was seen" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous sightings</button> : null}{state.value.next != null ? <button className="explorer-button" type="button" data-field="source_occurrences" aria-label="Next page of times this file was seen" onClick={() => setOffset(state.value.next || 0)}>Next sightings</button> : null}</p>
  </div>;
}
