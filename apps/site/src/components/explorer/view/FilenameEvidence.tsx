import { useEffect, useRef, useState } from 'react';
import { captureNotes, checkedAtNote, congressLabel, contentAddressedFilename, contentCongressLabel, contentCongressNote, contentHash, congressWarning, contentKindNote, documentKindLabel, fieldLabel, filenameIdentity, filenameReadings, formatLabel, kindBasis, measureLabel, pretty, readableValue, recordLabel, recordRoleNote, recoveredSourceHost, recoveredSourceUrl, responseCheckNote, retrievedAtNote, savedBodyNote, savedResponseLabel, serverTypeNote, sourceCommitteeNote, sourceDocumentBasis, sourceDocumentTypeNote } from '../browse/filename-presentation.ts';
import { recordedTitlePreview } from '../browse/record-presentation.ts';
import { filenameDate } from '../browse/filename-rules.ts';
import { appendOriginPage, evidenceGraph, provenanceUrlKey, type ProvenancePage, type ProvenanceEdge, type SourceContext } from '../browse/provenance.ts';
import { filenameRequest } from '../reader/filenames/session.ts';
import type { FilenameEntry, FilenameMatchResult, FilenameRecord, FilenameReview } from '../reader/filenames/types.ts';
import { publicUrl } from './RecordDetail';
import { RequestMessage, integer, useRequest } from './request-state';

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
  if (state.status !== 'ready') return <>
    <RequestMessage state={state} retry={retry} noun="filename catalog matches" />
    {state.status === 'loading' ? <p className="explorer-note">Looking up this document’s URL in the captured-file catalog. The rest of this record stays available.</p> : null}
  </>;
  if (!state.value.matches.length) return null;
  const selected = state.value.matches.find(match => match.source_id === picked) || state.value.matches[0];
  return <section className="explorer-detail-section">
    <h3>Matching captured file</h3>
    {state.value.matches.length > 1 ? <label><span>Matched file</span><span className="explorer-field-reason">This committee record matches more than one captured file. Choose which one to read.</span><select aria-label="Matched file. This committee record matches more than one captured file." value={selected.source_id} onChange={event => setPicked(event.target.value)}>{state.value.matches.map(match => <option key={match.source_id} value={match.source_id}>{match.url || match.sha256 || match.source_id}</option>)}</select></label> : <p className="explorer-note">This committee record matches a file captured from a committee site.</p>}
    {state.value.truncated ? <p className="explorer-note">More than 24 catalog records match. Showing the first 24.</p> : null}
    <EntryPanel key={`${selected.source_id}:`} id={selected.source_id} onOpen={onOpen} namingVersion={namingVersion} embedded />
  </section>;
}

function EntryPanel({ id, catalog, onOpen, embedded = false, namingVersion }: { id: string; catalog?: string; onOpen?: (id: string) => void; embedded?: boolean; namingVersion?: string }) {
  const [state, retry] = useRequest(signal => filenameRequest<FilenameEntry>(entryPath('entry', id, catalog), signal), [id, catalog || '']);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="filename details" />;
  return <ReadyEntry entry={state.value} id={id} catalog={catalog} onOpen={onOpen} embedded={embedded} namingVersion={namingVersion} />;
}

const identityFields = ['source_chamber', 'source_committee_code', 'source_meeting_type', 'source_meeting_title', 'source_page_title', 'source_page_url'] as const;

function ReadyEntry({ entry, id, catalog, onOpen, embedded, namingVersion }: { entry: FilenameEntry; id: string; catalog?: string; onOpen?: (id: string) => void; embedded: boolean; namingVersion?: string }) {
  const record = entry.record;
  const missingIdentity = identityFields.some(name => !(name in record));
  const [identity] = useRequest(signal => missingIdentity ? filenameRequest<FilenameRecord>(entryPath('source-identity', id, catalog), signal) : Promise.resolve({} as FilenameRecord), [id, catalog || '', missingIdentity]);
  const sourceRecord = { ...record, ...(identity.status === 'ready' ? identity.value : {}) };
  const saved = publicUrl(entry.saved_file_url);
    const source = publicUrl(sourceRecord.source_url);
    const recovered = publicUrl(recoveredSourceUrl(sourceRecord));
  const title = filenameIdentity({ ...sourceRecord, filename: entry.filename || sourceRecord.filename, api_reference: entry.api_reference, video_reference: entry.video_reference });
  const kind = recordLabel({ ...sourceRecord, document_kind: entry.document.document_kind, video_reference: entry.video_reference, api_reference: entry.api_reference });
  return <>
    {embedded ? null : <p className="explorer-record-kind">{kind === 'Unclassified' ? 'Document' : kind}</p>}
    <FilenameHeading title={title} embedded={embedded} />
    {source || recovered || saved ? <p className="explorer-file-links">{source ? <a href={source} target="_blank" rel="noreferrer">{entry.video_reference ? 'Watch video' : entry.api_reference ? 'Open API record' : 'Open original source'} ↗</a> : recovered ? <a href={recovered} target="_blank" rel="noreferrer">{recoveredSourceHost(sourceRecord)} ↗</a> : null}{saved ? <a href={saved} target="_blank" rel="noreferrer">Open saved copy ↗</a> : null}</p> : null}
    {embedded ? null : <EntryActions id={sourceRecord.source_id || id} catalog={entry.catalog_id} />}
    <Summary entry={{ ...entry, record: sourceRecord }} />
    <ReviewSection id={record.source_id || id} catalog={entry.catalog_id} />
    <Clues entry={entry} namingVersion={namingVersion} />
    <OriginSection entry={entry} id={record.source_id || id} catalog={entry.catalog_id} />
    <Sources entry={entry} onOpen={onOpen} />
    <TechnicalFields id={record.source_id || id} catalog={entry.catalog_id} />
  </>;
}

function FilenameHeading({ title, embedded }: { title: string; embedded: boolean }) {
  const saved = contentAddressedFilename(title);
  const name = saved?.name || title;
  const hash = saved ? <span className="explorer-filename-hash">{saved.hash}.</span> : null;
  return embedded ? <h3>{name}{hash}</h3> : <h2>{name}{hash}</h2>;
}

function RecordedPreview({ text, name }: { text: string; name: string }) {
  const note = recordedTitlePreview(text);
  return <>
    <span>{note.preview}</span>
    {note.rest.length ? <details><summary>Rest of the {name}<span className="explorer-field-reason">The rest of the recorded {name}.</span></summary>{note.rest.map((line, index) => <span key={index}>{line}</span>)}</details> : null}
  </>;
}

function Summary({ entry }: { entry: FilenameEntry }) {
  const row = entry.document;
  const source = entry.record;
  const recovery = source.recovery || entry.recovery;
  const warning = congressWarning(source.congress, source.source_congress);
  const committee = sourceCommitteeNote(source);
  const readings = filenameReadings(source);
  const version = readings.find(reading => reading.label === 'Version');
  const filenameCommittee = readings.find(reading => reading.label === 'Committee');
  const committeeText = committee.text.toLowerCase();
  const meetingType = (source.source_meeting_type || []).map(type => type.toLowerCase());
  const kindLabel = documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: row.document_kind }).toLowerCase();
  const summaryReadings = readings.filter(reading => ['Meeting wording', 'Draft', 'En bloc', 'Nomination', 'Subcommittee', 'Stage', 'Amendment degree', 'Abbreviation', 'Collection', 'Mark', 'Wording', 'Role', 'Context', 'Relation'].includes(reading.label) && !(reading.label === 'Meeting wording' && meetingType.includes(reading.value.toLowerCase())) && !(reading.label === 'Wording' && kindLabel.includes(reading.value.toLowerCase())));
  const measures = (source.measure_references || []).map(measureLabel).filter(Boolean);
  return <dl className="explorer-facts">
    <div><dt>Document kind</dt><dd>{documentKindLabel({ video_reference: entry.video_reference, api_reference: entry.api_reference, document_kind: row.document_kind })}{kindBasis(row) ? <span className="explorer-row-meta">{kindBasis(row)}</span> : row.document_kind_source?.length ? <span className="explorer-row-meta">Based on the filename</span> : null}{recordRoleNote(source) ? <span className="explorer-row-meta">{recordRoleNote(source)}</span> : null}</dd></div>
    {measures.length ? <div><dt>Measure</dt><dd>{measures.join(' · ')}<span className="explorer-row-meta">Read from the filename.</span></dd></div> : null}
    <div><dt>Format</dt><dd>{source.format?.map(formatLabel).join(' · ') || 'Unknown'}{savedBodyNote(source) ? <span className="explorer-row-meta">{savedBodyNote(source)}</span> : null}{serverTypeNote(source) ? <span className="explorer-row-meta">{serverTypeNote(source)}</span> : null}</dd></div>
    <div><dt>Saved copy</dt><dd>{[savedResponseLabel({ ...source, retained: source.body_key ? true : source.retained, recovery }), responseCheckNote(source), ...captureNotes(source), checkedAtNote(source), retrievedAtNote(source)].filter(Boolean).map((note, index) => <span className={index ? 'explorer-row-meta' : undefined} key={`${index}-${note}`}>{note}</span>)}{recovery?.recovery_status === 'recovered' && recovery.kind ? <span className="explorer-row-meta">Recovered format {formatLabel(recovery.kind)}</span> : null}{contentHash(source.body_key || recovery?.body_key) ? <span className="explorer-row-meta">SHA-256 {contentHash(source.body_key || recovery?.body_key)}</span> : null}</dd></div>
    {sourceDocumentTypeNote(source) ? <div><dt>Source document type</dt><dd>{sourceDocumentTypeNote(source)}{sourceDocumentBasis(source) ? <span className="explorer-row-meta">{sourceDocumentBasis(source)}</span> : null}</dd></div> : null}
    {contentKindNote(source) ? <div><dt>Saved contents</dt><dd>{contentKindNote(source)}</dd></div> : null}
    {source.http_status?.length ? <div><dt>HTTP response</dt><dd>{source.http_status.map(String).join(' · ')}</dd></div> : null}
    {source.congress?.length || source.source_congress?.length || contentCongressLabel(source) ? <div><dt>Congress</dt><dd>{congressLabel(source.congress) || congressLabel(source.source_congress) || contentCongressLabel(source)}{source.congress?.length && source.source_congress?.length ? <span className="explorer-row-meta">Source: {congressLabel(source.source_congress)}</span> : null}{!source.congress?.length && source.source_congress?.length ? <span className="explorer-row-meta">From the source record</span> : null}{contentCongressLabel(source) ? <span className="explorer-row-meta">From the saved contents</span> : null}{contentCongressNote(source) ? <span className="explorer-row-meta">{contentCongressNote(source)}</span> : null}{warning ? <span className="explorer-row-meta">{warning}</span> : null}</dd></div> : null}
    {source.source_chamber?.length ? <div><dt>Chamber</dt><dd>{source.source_chamber.join(' · ')}</dd></div> : null}
    {committee.text ? <div><dt>Committee</dt><dd>{committee.text}{committee.code ? <span className="explorer-row-meta">{committee.code}</span> : null}</dd></div> : null}
    {filenameCommittee && !committeeText.includes(filenameCommittee.value.toLowerCase()) ? <div><dt>{committee.text ? 'Filename committee' : 'Committee'}</dt><dd>{filenameCommittee.value}<span className="explorer-row-meta">Read from the filename.</span></dd></div> : null}
    {source.source_meeting_title?.length ? <div><dt>Meeting</dt><dd><RecordedPreview text={source.source_meeting_title.join(' · ')} name="meeting title" /></dd></div> : null}
    {source.source_meeting_type?.length ? <div><dt>Meeting type</dt><dd>{source.source_meeting_type.join(' · ')}</dd></div> : null}
    {source.source_page_title?.length ? <div><dt>Page title</dt><dd><RecordedPreview text={source.source_page_title.join(' · ')} name="page title" /></dd></div> : null}
    {source.source_record_type?.length ? <div><dt>Source record type</dt><dd>{source.source_record_type.map(pretty).join(' · ')}</dd></div> : null}
    {version ? <div><dt>Version</dt><dd>{version.value}<span className="explorer-row-meta">Read from the filename.</span></dd></div> : null}
    {summaryReadings.map(reading => <div key={reading.label}><dt>{reading.label}</dt><dd>{reading.value}<span className="explorer-row-meta">Read from the filename.</span></dd></div>)}
  </dl>;
}

function EntryActions({ id, catalog }: { id: string; catalog: string }) {
  const [copyStatus, setCopyStatus] = useState('');
  const [linkStatus, setLinkStatus] = useState('');
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
  return <p className="explorer-file-links">
    <button className="explorer-text-button" type="button" aria-label="Copy the published fields for this file. This does not download the saved file." onClick={() => void copyJson()}>Copy source JSON</button>
    <button className="explorer-text-button" type="button" aria-label="Copy a link that opens this file in the explorer" onClick={() => void copyLink()}>Copy link to this file</button>
    {copyStatus ? <span className="explorer-row-meta">{copyStatus}</span> : null}
    {linkStatus ? <span className="explorer-row-meta">{linkStatus}</span> : null}
  </p>;
}

function Clues({ entry, namingVersion }: { entry: FilenameEntry; namingVersion?: string }) {
  const row = entry.record;
  if (entry.video_reference) return null;
  const dates = row.date_token_candidates?.map(filenameDate) || [];
  const readings = filenameReadings(row).filter(reading => !['Version', 'Meeting wording', 'Draft', 'En bloc', 'Nomination', 'Committee', 'Subcommittee', 'Stage', 'Amendment degree', 'Abbreviation', 'Collection', 'Mark', 'Wording', 'Role', 'Context', 'Relation'].includes(reading.label));
  if (!dates.length && !readings.length && !row.committee_code?.length && !row.filename_origins?.length && !namingVersion) return null;
  return <details className="explorer-detail-section"><summary>Filename clues<span className="explorer-field-reason">Unverified readings of the filename. They are not a classification.</span></summary>
    <p className="explorer-note">Unverified filename interpretations{entry.filename_field_count ? ` · ${integer(entry.filename_field_count)} filename fields` : ''}.</p>
    {namingVersion ? <p className="explorer-note">House-naming version {namingVersion}.</p> : null}
    <dl className="explorer-facts">
      {readings.map(reading => <div key={reading.label}><dt>{reading.label}</dt><dd>{reading.value}</dd></div>)}
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
  return <details className="explorer-detail-section"><summary>Complete document review<span className="explorer-field-reason">Assistant findings for this file. They are not independently confirmed.</span></summary>
    <p className="explorer-note">{labels[review.status] || review.status}. Assistant-reviewed findings; not independently confirmed.</p>
    <dl className="explorer-facts">
      <div><dt>Original category</dt><dd>{review.baseline?.document_kind?.map(pretty).join(' · ') || 'Unclassified'}</dd></div>
      <div><dt>Preview category</dt><dd>{review.selected?.document_kind?.map(pretty).join(' · ') || 'Unclassified'}</dd></div>
      {review.review?.primary_forms?.length ? <div><dt>Primary forms</dt><dd>{review.review.primary_forms.map(pretty).join(' · ')}</dd></div> : null}
      {observed?.pages ? <div><dt>Pages reviewed</dt><dd>{integer(observed.pages)}</dd></div> : null}
    </dl>
    <p><button className="explorer-text-button" type="button" aria-label={withdrawn ? 'Show the assistant-reviewed category again' : 'Show the original classification instead of the assistant preview'} onClick={() => setWithdrawn(value => !value)}>{withdrawn ? 'Restore reviewed preview' : 'Hide reviewed preview'}</button></p>
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
  if (!graph.paths.length && !graph.references.length) return <p className="explorer-note">Referring page not recorded for this source.</p>;
  return <>
    {graph.paths.map((item, index) => <ol key={index}>{item.path.map((edge: ProvenanceEdge, edgeIndex) => <li key={edgeIndex}>{edge.page ? <PageLink pageUrl={edge.page.urls[0]} title={typeof edge.page.titles[0] === 'string' ? edge.page.titles[0] : undefined} /> : edge.redirect ? 'Redirect' : 'Related source'}</li>)}<li>This file</li></ol>)}
    <ReferenceList references={graph.references} />
    <PublisherLabels origin={origin} shown={shownReferenceNames(graph)} />
    {recoveryUrl && publicUrl(recoveryUrl) ? <p className="explorer-note">Saved copy recovered through <a href={recoveryUrl} target="_blank" rel="noreferrer">{recoveryUrl} ↗</a></p> : null}
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
    return <li key={key}>{publicUrl(href) ? <a href={href} target="_blank" rel="noreferrer">{name || href} ↗</a> : href || 'Source URL not available'}{name && href ? <span className="explorer-row-meta">{href}</span> : null}</li>;
  };
  const shown = references.slice(0, 12);
  const rest = references.slice(12);
  return <>
    <ul className="explorer-origin-list">{shown.map(item)}</ul>
    {rest.length ? <details><summary>{rest.length} more referring {rest.length === 1 ? 'page' : 'pages'}<span className="explorer-field-reason">Every other recorded URL for this file.</span></summary><ul className="explorer-origin-list">{rest.map(item)}</ul></details> : null}
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
  if (!href) return <span>Source URL not available</span>;
  return <a href={href} target="_blank" rel="noreferrer">{title || href} ↗</a>;
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
  return <details className="explorer-detail-section"><summary>Other URLs in this group ({integer(entry.sources.length)})<span className="explorer-field-reason">Other captures grouped with this file.</span></summary>
    <p className="explorer-note">{entry.sources_share_saved_file ? 'These records share one saved file.' : 'Each source record keeps its own metadata.'}</p>
    <ul className="explorer-related-list">{page.map(source => {
      const label = sourceLabel(source);
      const href = source.source_url || '';
      return <li key={source.source_id || href || source.filename}>
        {label && source.source_id ? <button className="explorer-text-button" type="button" aria-label={`Open the captured file ${source.filename || label}`} onClick={() => onOpen(source.source_id!)}>{label}</button> : <span>{label || 'No URL or filename recorded'}</span>}
        {href ? <span className="explorer-row-meta">{href}</span> : null}
        {savedResponseLabel(source) ? <span className="explorer-row-meta">{savedResponseLabel(source)}</span> : null}
      </li>;
    })}</ul>
    <p>{offset ? <button className="explorer-text-button" type="button" aria-label="Previous page of URLs in this group" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous URLs</button> : null}{offset + 20 < entry.sources.length ? <button className="explorer-text-button" type="button" aria-label="Next page of URLs in this group" onClick={() => setOffset(value => value + 20)}>Next URLs</button> : null}</p>
  </details>;
}

function TechnicalFields({ id, catalog }: { id: string; catalog: string }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  return <details className="explorer-detail-section" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>All recorded fields<span className="explorer-field-reason">Every published field, including ones left off the summary.</span></summary>
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
    <label><span>Find a field</span><span className="explorer-field-reason">Narrow this list by label, field name, or value.</span><input type="search" value={query} onChange={event => { onQuery(event.target.value); setOffset(0); }} placeholder="Label, field name, or value" /></label>
    <p className="explorer-note">{integer(shown.length ? offset + 1 : 0)}–{integer(offset + shown.length)} of {integer(entries.length)} fields</p>
    <dl className="explorer-facts">{shown.map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{readableValue(value).split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</dd></div>)}</dl>
    <p>{offset ? <button className="explorer-text-button" type="button" aria-label="Previous page of recorded fields" onClick={() => setOffset(value => Math.max(0, value - 80))}>Previous fields</button> : null}{offset + 80 < entries.length ? <button className="explorer-text-button" type="button" aria-label="Next page of recorded fields" onClick={() => setOffset(value => value + 80)}>Next fields</button> : null}</p>
    <Observations id={id} catalog={catalog} />
  </>;
}

function ObservationItem({ item, number }: { item: unknown; number: number }) {
  const [open, setOpen] = useState(false);
  const fields = item && typeof item === 'object' ? Object.entries(item as Record<string, unknown>).filter(([, value]) => value != null && value !== '' && (!Array.isArray(value) || value.length > 0)) : [];
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Observation {number}<span className="explorer-field-reason">One recorded source observation.</span></summary>
    {open ? <dl className="explorer-facts">{fields.map(([key, value]) => <div key={key}><dt>{fieldLabel(key)}</dt><dd>{readableValue(value).split('\n').map((line, lineIndex) => <span key={lineIndex}>{line}</span>)}</dd></div>)}</dl> : null}
  </details>;
}

function Observations({ id, catalog }: { id: string; catalog: string }) {
  const [offset, setOffset] = useState(0);
  const [state, retry] = useRequest(signal => filenameRequest<{ items: unknown[]; total: number; next: number | null }>(entryPath('observations', id, catalog, `offset=${offset}&limit=20`), signal), [id, catalog, offset]);
  if (state.status !== 'ready') return <RequestMessage state={state} retry={retry} noun="source observations" />;
  if (!state.value.total) return <p className="explorer-note">No source observations recorded.</p>;
  return <div>
    <h4>Source observations</h4>
    <p className="explorer-note">{integer(offset + 1)}–{integer(offset + state.value.items.length)} of {integer(state.value.total)} observations</p>
    {state.value.items.map((item, index) => <ObservationItem key={offset + index} item={item} number={offset + index + 1} />)}
    <p>{offset ? <button className="explorer-button" type="button" data-field="source_occurrences" aria-label="Previous page of source observations" onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous observations</button> : null}{state.value.next != null ? <button className="explorer-button" type="button" data-field="source_occurrences" aria-label="Next page of source observations" onClick={() => setOffset(state.value.next || 0)}>Next observations</button> : null}</p>
  </div>;
}
