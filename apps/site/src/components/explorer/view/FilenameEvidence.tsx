import { useEffect, useRef, useState } from 'react';
import { congressLabel, congressWarning, documentKindLabel, fieldLabel, filenameIdentity, formatLabel, measureLabel, pretty, savedResponseLabel } from '../browse/filename-presentation.ts';
import { filenameDate } from '../browse/filename-rules.ts';
import { appendOriginPage, evidenceGraph, provenanceUrlKey, type ProvenanceEdge, type SourceContext } from '../browse/provenance.ts';
import { filenameRequest } from '../reader/filenames/session.ts';
import type { FilenameEntry, FilenameMatchResult, FilenameRecord, FilenameReview } from '../reader/filenames/types.ts';
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

export function FilenameEvidence({ entryId, catalog, files, onOpen, namingVersion }: {
  entryId?: string;
  catalog?: string;
  files?: readonly { url?: unknown; saved_copy_sha256?: unknown }[];
  onOpen?: (id: string) => void;
  namingVersion?: string;
}) {
  if (entryId) return <EntryPanel key={`${entryId}:${catalog ?? ''}`} id={entryId} catalog={catalog} onOpen={onOpen} namingVersion={namingVersion} />;
  const urls = (files || []).map(file => typeof file.url === 'string' ? file.url : '').filter(Boolean);
  const sha256s = (files || []).map(file => typeof file.saved_copy_sha256 === 'string' ? file.saved_copy_sha256 : '').filter(Boolean);
  if (!urls.length && !sha256s.length) return null;
  return <MatchedFiles urls={urls} sha256s={sha256s} onOpen={onOpen} namingVersion={namingVersion} />;
}

function MatchedFiles({ urls, sha256s, onOpen, namingVersion }: { urls: string[]; sha256s: string[]; onOpen?: (id: string) => void; namingVersion?: string }) {
  const key = JSON.stringify({ urls, sha256s });
  const [picked, setPicked] = useState('');
  const [state, retry] = useRequest(signal => filenameRequest<FilenameMatchResult>(`/api/match?payload=${encodeURIComponent(JSON.stringify({ urls, sha256s }))}`, signal), [key]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="filename catalog matches" />;
  if (!state.value.matches.length) return null;
  const selected = state.value.matches.find(match => match.source_id === picked) || state.value.matches[0];
  return <section className="explorer-detail-section">
    <h3>Matching captured file</h3>
    {state.value.matches.length > 1 ? <label>Matched file<select value={selected.source_id} onChange={event => setPicked(event.target.value)}>{state.value.matches.map(match => <option key={match.source_id} value={match.source_id}>{match.url || match.sha256 || match.source_id}</option>)}</select></label> : <p className="explorer-note">This committee record matches a file captured from a committee site.</p>}
    {state.value.truncated ? <p className="explorer-note">More than 24 catalog records match. Showing the first 24.</p> : null}
    <EntryPanel key={`${selected.source_id}:`} id={selected.source_id} onOpen={onOpen} namingVersion={namingVersion} embedded />
  </section>;
}

function EntryPanel({ id, catalog, onOpen, embedded = false, namingVersion }: { id: string; catalog?: string; onOpen?: (id: string) => void; embedded?: boolean; namingVersion?: string }) {
  const [state, retry] = useRequest(signal => filenameRequest<FilenameEntry>(entryPath('entry', id, catalog), signal), [id, catalog || '']);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="filename details" />;
  const entry = state.value;
  const record = entry.record;
  const saved = publicUrl(entry.saved_file_url);
  const source = publicUrl(record.source_url);
  const title = filenameIdentity({ ...record, filename: entry.filename || record.filename, api_reference: entry.api_reference, video_reference: entry.video_reference });
  const kind = documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: entry.document.document_kind });
  return <>
    {embedded ? <h3>{title}</h3> : <><p className="explorer-record-kind">{kind === 'Unclassified' ? 'Document' : kind}</p><h2>{title}</h2></>}
    <p>{source ? <a href={source} target="_blank" rel="noreferrer">{entry.video_reference ? 'Watch video' : entry.api_reference ? 'Open API record' : 'Open original source'} ↗</a> : null}{saved ? <> <a href={saved} target="_blank" rel="noreferrer">Open saved copy ↗</a></> : null}</p>
    {embedded ? null : <EntryActions id={record.source_id || id} catalog={entry.catalog_id} documentDownload={entry.document_download_available} />}
    <Summary entry={entry} />
    <ReviewSection id={record.source_id || id} catalog={entry.catalog_id} />
    <Clues entry={entry} namingVersion={namingVersion} />
    <OriginSection entry={entry} id={record.source_id || id} catalog={entry.catalog_id} />
    <Sources entry={entry} onOpen={onOpen} />
    <TechnicalFields id={record.source_id || id} catalog={entry.catalog_id} />
  </>;
}

function Summary({ entry }: { entry: FilenameEntry }) {
  const row = entry.document;
  const source = entry.record;
  const recovery = source.recovery || entry.recovery;
  const warning = congressWarning(source.congress, source.source_congress);
  return <dl className="explorer-facts">
    <div><dt>Document kind</dt><dd>{documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: row.document_kind })}{row.document_kind_source?.length ? <span className="explorer-row-meta">Based on {row.document_kind_source.map(value => pretty(value).toLowerCase()).join(' · ')}</span> : null}</dd></div>
    <div><dt>Format</dt><dd>{source.format?.map(formatLabel).join(' · ') || 'Unknown'}</dd></div>
    <div><dt>Saved copy</dt><dd>{savedResponseLabel({ ...source, retained: source.body_key ? true : source.retained, recovery })}{recovery?.recovery_status === 'recovered' && recovery.kind ? <span className="explorer-row-meta">Recovered format {formatLabel(recovery.kind)}</span> : null}</dd></div>
    {source.congress?.length ? <div><dt>Congress</dt><dd>{congressLabel(source.congress)}{source.source_congress?.length ? <span className="explorer-row-meta">Source: {congressLabel(source.source_congress)}</span> : null}{warning ? <span className="explorer-row-meta">{warning}</span> : null}</dd></div> : null}
    {source.source_committee_name?.length ? <div><dt>Committee</dt><dd>{source.source_committee_name.join(' · ')}</dd></div> : null}
  </dl>;
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
    setCopyStatus('Preparing complete metadata…');
    try {
      const record = await filenameRequest<unknown>(entryPath('full', id, catalog), new AbortController().signal);
      await navigator.clipboard.writeText(JSON.stringify(record, null, 2));
      setCopyStatus('Copied source JSON');
    } catch (error) {
      setCopyStatus(error instanceof Error ? error.message : 'Could not copy source JSON');
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
      setLinkStatus('Clipboard unavailable');
    }
  }
  return <p>
    <button className="explorer-text-button" type="button" onClick={() => void copyJson()}>Copy source JSON</button>{' '}
    <button className="explorer-text-button" type="button" onClick={() => void copyLink()}>Copy link to this file</button>{' '}
    <button className="explorer-text-button" type="button" disabled={downloading} onClick={() => void downloadMetadata('full')}>Download source JSON</button>{' '}
    {documentDownload ? <button className="explorer-text-button" type="button" disabled={downloading} onClick={() => void downloadMetadata('document')}>Download document JSON</button> : null}
    {downloadStatus ? <span className="explorer-row-meta" role="status">{downloadStatus}</span> : null}
    {copyStatus ? <span className="explorer-row-meta">{copyStatus}</span> : null}
    {linkStatus ? <span className="explorer-row-meta">{linkStatus}</span> : null}
  </p>;
}

function Clues({ entry, namingVersion }: { entry: FilenameEntry; namingVersion?: string }) {
  const row = entry.record;
  if (entry.video_reference) return null;
  const measures = row.measure_references?.map(measureLabel) || [];
  const dates = row.date_token_candidates?.map(filenameDate) || [];
  if (!measures.length && !dates.length && !row.committee_code?.length && !row.filename_origins?.length && !namingVersion) return null;
  return <details className="explorer-detail-section"><summary>Filename clues</summary>
    <p className="explorer-note">Unverified filename interpretations{entry.filename_field_count ? ` · ${integer(entry.filename_field_count)} filename fields` : ''}.</p>
    {namingVersion ? <p className="explorer-note">House-naming version {namingVersion}.</p> : null}
    <dl className="explorer-facts">
      {measures.length ? <div><dt>Measure</dt><dd>{measures.join(' · ')}</dd></div> : null}
      {dates.length ? <div><dt>Possible date</dt><dd>{dates.join(' · ')}</dd></div> : null}
      {row.committee_code?.length ? <div><dt>Committee code</dt><dd>{row.committee_code.join(' · ')}</dd></div> : null}
      {row.filename_origins?.length ? <div><dt>Filename obtained from</dt><dd>{row.filename_origins.map(pretty).join(' · ')}</dd></div> : null}
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
  const labels: Record<string, string> = { candidate_applied: 'Reviewed classification preview', annotation_only_unsupported_forms: 'Findings retained; classification unchanged', withdrawn: 'Review withdrawn from this preview' };
  const body = review.evidence?.body;
  return <details className="explorer-detail-section"><summary>Complete document review</summary>
    <p className="explorer-note">{labels[review.status] || review.status}. Assistant-reviewed findings; not independently confirmed.</p>
    <dl className="explorer-facts">
      <div><dt>Original category</dt><dd>{review.baseline?.document_kind?.map(pretty).join(' · ') || 'Unclassified'}</dd></div>
      <div><dt>Preview category</dt><dd>{review.selected?.document_kind?.map(pretty).join(' · ') || 'Unclassified'}</dd></div>
      {review.review?.primary_forms?.length ? <div><dt>Primary forms</dt><dd>{review.review.primary_forms.map(pretty).join(' · ')}</dd></div> : null}
      {observed?.pages ? <div><dt>Pages reviewed</dt><dd>{integer(observed.pages)}</dd></div> : null}
    </dl>
    <p><button className="explorer-text-button" type="button" onClick={() => setWithdrawn(value => !value)}>{withdrawn ? 'Restore reviewed preview' : 'Hide reviewed preview'}</button></p>
    {body ? <p><a href={body} download="reviewed-document.pdf">Download the exact reviewed PDF</a></p> : null}
    {observed?.text_path && review.evidence?.text ? <p><a href={review.evidence.text} target="_blank" rel="noreferrer">Saved extracted text ↗</a></p> : null}
    {observed?.native_text_path && review.evidence?.['native-text'] ? <p><a href={review.evidence['native-text']} target="_blank" rel="noreferrer">Saved native text ↗</a></p> : null}
    {review.evidence?.pages && Object.keys(review.evidence.pages).length ? <ul className="explorer-note">{Object.entries(review.evidence.pages).map(([page, href]) => <li key={page}><a href={href} target="_blank" rel="noreferrer">Page {page} image ↗</a></li>)}</ul> : null}
    {observed?.notes ? <p className="explorer-note">{observed.notes}</p> : null}
    {observed?.page_sections?.length ? <ul className="explorer-note">{observed.page_sections.map(part => <li key={`${part.first_page}-${part.last_page}`}>Pages {part.first_page}–{part.last_page}: {part.observed_form.split('|').map(pretty).join(' · ')}{part.description ? ` — ${part.description}` : ''}</li>)}</ul> : null}
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
  return <details className="explorer-detail-section"><summary>Where this file came from</summary><OriginGraph origin={view.origin} recoveryUrl={entry.record.recovery?.recovered_url || entry.recovery?.recovered_url} />
    {view.next != null ? <button className="explorer-text-button" type="button" onClick={() => {
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
  if (!graph.paths.length && !graph.references.length) return <p className="explorer-note">Referring page not recorded for this source.</p>;
  return <>
    {graph.paths.map((item, index) => <ol key={index}>{item.path.map((edge: ProvenanceEdge, edgeIndex) => <li key={edgeIndex}>{edge.page ? <PageLink pageUrl={edge.page.urls[0]} title={typeof edge.page.titles[0] === 'string' ? edge.page.titles[0] : undefined} /> : edge.redirect ? 'Redirect' : 'Related source'}</li>)}<li>This file</li></ol>)}
    <ul className="explorer-note">{graph.references.slice(0, 12).map(item => {
      const href = typeof item.url === 'string' ? item.url : '';
      return <li key={provenanceUrlKey(item.url) || href}>{publicUrl(href) ? <a href={href} target="_blank" rel="noreferrer">{href} ↗</a> : href || 'Source URL not available'}</li>;
    })}</ul>
    <PublisherLabels origin={origin} />
    {recoveryUrl && publicUrl(recoveryUrl) ? <p className="explorer-note">Saved copy recovered through <a href={recoveryUrl} target="_blank" rel="noreferrer">{recoveryUrl} ↗</a></p> : null}
  </>;
}

function PublisherLabels({ origin }: { origin: SourceContext }) {
  const labels = [...new Set(origin.pages.flatMap(page => page.link_labels.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)))].slice(0, 12);
  if (!labels.length) return null;
  return <div>{labels.map(label => <blockquote key={label}>{label}</blockquote>)}</div>;
}

function PageLink({ pageUrl, title }: { pageUrl: unknown; title?: string }) {
  const href = typeof pageUrl === 'string' ? publicUrl(pageUrl) : undefined;
  if (!href) return <span>Source URL not available</span>;
  return <a href={href} target="_blank" rel="noreferrer">{title || href} ↗</a>;
}

function sourceLabel(source: FilenameRecord): string {
  const format = source.format?.map(formatLabel).join(' · ');
  return [source.filename, format].filter(Boolean).join(' · ');
}

function Sources({ entry, onOpen }: { entry: FilenameEntry; onOpen?: (id: string) => void }) {
  const [offset, setOffset] = useState(0);
  if (entry.sources.length < 2 || !onOpen) return null;
  const page = entry.sources.slice(offset, offset + 20);
  return <details className="explorer-detail-section"><summary>Other URLs in this group ({integer(entry.sources.length)})</summary>
    <p className="explorer-note">{entry.sources_share_saved_file ? 'These records share one saved file.' : 'Each source record keeps its own metadata.'}</p>
    <ul className="explorer-related-list">{page.map(source => {
      const label = sourceLabel(source);
      const href = source.source_url || '';
      return <li key={source.source_id || href || source.filename}>
        {label && source.source_id ? <button className="explorer-text-button" type="button" onClick={() => onOpen(source.source_id!)}>{label}</button> : <span>{label || 'No URL or filename recorded'}</span>}
        <span className="explorer-row-meta">{[href, savedResponseLabel(source)].filter(Boolean).join(' · ')}</span>
      </li>;
    })}</ul>
    <p>{offset ? <button className="explorer-text-button" type="button" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous URLs</button> : null}{offset + 20 < entry.sources.length ? <button className="explorer-text-button" type="button" onClick={() => setOffset(value => value + 20)}>Next URLs</button> : null}</p>
  </details>;
}

function TechnicalFields({ id, catalog }: { id: string; catalog: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  return <details className="explorer-detail-section" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>All recorded fields</summary>
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
    <label>Find a field<input type="search" value={query} onChange={event => { onQuery(event.target.value); setOffset(0); }} placeholder="Label, field name, or value" /></label>
    <p className="explorer-note">{integer(shown.length ? offset + 1 : 0)}–{integer(offset + shown.length)} of {integer(entries.length)} fields</p>
    <dl className="explorer-facts">{shown.map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{Array.isArray(value) ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join(' · ') : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
    <p>{offset ? <button className="explorer-text-button" type="button" onClick={() => setOffset(value => Math.max(0, value - 80))}>Previous fields</button> : null}{offset + 80 < entries.length ? <button className="explorer-text-button" type="button" onClick={() => setOffset(value => value + 80)}>Next fields</button> : null}</p>
    <Observations id={id} catalog={catalog} />
  </>;
}

function Observations({ id, catalog }: { id: string; catalog: string }) {
  const [offset, setOffset] = useState(0);
  const [state, retry] = useRequest(signal => filenameRequest<{ items: unknown[]; total: number; next: number | null }>(entryPath('observations', id, catalog, `offset=${offset}&limit=20`), signal), [id, catalog, offset]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="source observations" />;
  if (!state.value.total) return <p className="explorer-note">No source observations recorded.</p>;
  return <div>
    <h4>Source observations</h4>
    <p className="explorer-note">{integer(offset + 1)}–{integer(offset + state.value.items.length)} of {integer(state.value.total)}</p>
    {state.value.items.map((item, index) => <pre key={offset + index}><code>{JSON.stringify(item, null, 2)}</code></pre>)}
    <p>{offset ? <button className="explorer-button" type="button" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous observations</button> : null}{state.value.next != null ? <button className="explorer-button" type="button" onClick={() => setOffset(state.value.next || 0)}>Next observations</button> : null}</p>
  </div>;
}
