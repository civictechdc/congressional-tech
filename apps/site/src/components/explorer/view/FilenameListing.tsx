import { useRef } from 'react';
import { nextSort, type Navigation } from '../browse/navigation.ts';
import { filenameSearchParams } from '../browse/filename-search.ts';
import { captureNotes, checkedAtNote, congressLabel, congressWarning, contentAddressedFilename, contentCongressLabel, contentCongressNote, contentKindNote, fieldLabel, filenameClues, filenameIdentity, formatLabel, httpStatusNote, kindBasis, pretty, recordLabel, recordRoleNote, recoveredSourceHost, responseCheckNote, retrievedAtNote, reviewStatusLabel, savedBodyNote, savedResponseLabel, serverTypeNote, sourceDocumentTypeNote } from '../browse/filename-presentation.ts';
import { filenameRequest } from '../reader/filenames/session.ts';
import type { FilenameCatalogInfo, FilenameRecord, FilenameSearchResult } from '../reader/filenames/types.ts';
import { Pagination, RequestMessage, integer, useRequest } from './request-state';

const searchFields = ['filename', 'source_url', 'source_page_url', 'source_link_label', 'document_kind', 'content_document_kind', 'congress', 'source_congress', 'content_congress', 'committee_code', 'source_committee_name', 'measure_references', 'date_token_candidates', 'source_record_type', 'source_meeting_title', 'source_chamber'];

function sourceHost(value: string | null | undefined): string {
  if (!value) return '';
  try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return ''; }
}

function facetValues(info: FilenameCatalogInfo, key: 'congress' | 'document_family' | 'document_kind' | 'format'): string[] {
  return info.review_facets?.[key] || info.facets[key] || [];
}

export function FilenameFilters({ nav, info, onChange }: { nav: Navigation; info: FilenameCatalogInfo; onChange: (patch: Partial<Navigation>) => void }) {
  const fields = [...searchFields.filter(key => info.fields.includes(key)), ...(nav.field && !searchFields.includes(nav.field) ? [nav.field] : [])];
  const family = facetValues(info, 'document_family');
  const kinds = facetValues(info, 'document_kind');
  const formats = facetValues(info, 'format');
  return <>
    <label><span>Saved copy</span><span className="explorer-field-reason">Keep files with a saved response, or files with none.</span><select value={nav.retained} onChange={event => onChange({ retained: event.target.value === 'yes' || event.target.value === 'no' ? event.target.value : '' })}><option value="">Any</option><option value="yes">Saved</option><option value="no">None saved</option></select></label>
    <label><span>Document kind</span><span className="explorer-field-reason">The file form the catalog recorded. No document kind means it abstained.</span><select value={nav.document_kind} onChange={event => onChange({ document_kind: event.target.value })}><option value="">All kinds</option><option value="__null__">No document kind</option>{kinds.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
    <label><span>Format</span><span className="explorer-field-reason">The recorded file format, such as PDF, HTML, or XML.</span><select value={nav.format} onChange={event => onChange({ format: event.target.value })}><option value="">All formats</option>{formats.map(value => <option key={value} value={value}>{formatLabel(value)}</option>)}</select></label>
    <details className="explorer-filter-more">
      <summary>More filters<span className="explorer-field-reason">Search field, broad category, and the reviewed catalog.</span></summary>
      <label><span>Search field</span><span className="explorer-field-reason">Which captured-file field the search box reads.</span><select value={nav.field || 'filename'} onChange={event => onChange({ field: event.target.value === 'filename' ? '' : event.target.value })}>{fields.map(key => <option key={key} value={key}>{fieldLabel(key)}</option>)}</select></label>
      <label><span>Broad category</span><span className="explorer-field-reason">A coarser grouping than document kind.</span><select value={nav.document_family} onChange={event => onChange({ document_family: event.target.value })}><option value="">All categories</option><option value="__null__">Unclassified</option>{family.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
      {info.complete_body_reviews || nav.classification ? <label><span>Catalog</span><span className="explorer-field-reason">Original classifications, or the assistant-reviewed preview.</span><select value={nav.classification} onChange={event => onChange({ classification: event.target.value === 'reviewed' ? 'reviewed' : '', review: event.target.value === 'reviewed' ? info.review_sha256 || '' : '' })}><option value="">Original</option><option value="reviewed" disabled={!info.reviewed_search}>Reviewed categories</option></select></label> : null}
    </details>
  </>;
}

const sortColumns = [
  ['record', 'Record', 'record name'],
  ['kind', 'Document kind', 'document kind'],
  ['congress', 'Congress / saved copy', 'Congress'],
] as const;

export function FilenameListing({ nav, info, onOpen, onPage, onSort }: { nav: Navigation; info: FilenameCatalogInfo; onOpen: (row: FilenameRecord) => void; onPage: (page: number) => void; onSort: (patch: Pick<Navigation, 'sort' | 'direction'>) => void }) {
  const query = filenameSearchParams(nav, info);
  const [state, retry] = useRequest(signal => filenameRequest<FilenameSearchResult>(`/api/rows?${query}`, signal), [query]);
  const shown = useRef<{ scope: string; value: FilenameSearchResult } | null>(null);
  if (state.status === 'ready') shown.current = { scope: nav.scope, value: state.value };
  const visible = shown.current?.scope === nav.scope ? shown.current.value : null;
  const congressSkipped = nav.congress !== 'all' && !facetValues(info, 'congress').includes(nav.congress);
  const heading = nav.scope === 'capture-records' ? 'Source & capture records' : nav.scope === 'all' ? 'All captured records' : 'Documents';
  return <>
    <div className="explorer-subheading"><h2>{heading}</h2>{state.status === 'ready' ? <span className="explorer-muted">{integer(state.value.total)} {state.value.total === 1 ? 'record' : 'records'}</span> : visible ? <span className="explorer-muted">Updating the list</span> : null}</div>
    <p className="explorer-note">{nav.scope === 'capture-records' ? 'Source and capture records, including API references that are not saved documents.' : nav.scope === 'all' ? 'Every captured record, including documents and capture metadata.' : 'Files found on committee sites, including files that are not matched to a meeting.'} Chamber, committee, and date filters do not apply in this list. Column headings sort the full list; a third click returns to catalog order.</p>
    {nav.document_kind === '__null__' ? <p className="explorer-note">These records have no document kind. The list labels caption segments, meeting packages, package metadata, committee pages, and meeting pages from the catalog. A page identified only by its recorded title is labeled when the file is opened.</p> : null}
    {congressSkipped ? <p className="explorer-note">The filename catalog has no entries for the {nav.congress}th Congress, so that Congress filter is not applied here.</p> : null}
    {nav.classification === 'reviewed' ? <p className="explorer-note">{info.reviewed_search ? `Search uses ${integer(info.reviewed_groups || 0)} assistant-reviewed groups. Downloads keep the original catalog.` : info.review_error || 'Reviewed categories are unavailable. Choose Original.'}</p> : null}
    {state.status === 'error' ? <RequestMessage state={state} retry={retry} noun="captured files" /> : null}
    {state.status === 'loading' && !visible ? <p className="explorer-loading" role="status">Searching the captured-file catalog.</p> : null}
    {visible?.rows.length ? <>
      {state.status === 'loading' ? <p className="explorer-note" role="status">Updating the list.</p> : null}
      <div className="explorer-table-scroll"><table className="explorer-table explorer-filename-table" aria-busy={state.status === 'loading'}><thead><tr>
        {sortColumns.map(([column, label, reason]) => {
          const active = nav.sort === column;
          const direction = active ? nav.direction : '';
          return <th key={column} scope="col" aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'}><button type="button" className="explorer-sort" data-direction={direction} onClick={() => onSort(nextSort(nav, column))} aria-label={direction === 'asc' ? `Sort by ${reason}, ascending. Activate to sort descending.` : direction === 'desc' ? `Sort by ${reason}, descending. Activate to restore catalog order.` : `Sort by ${reason}`}>{label}</button></th>;
        })}
      </tr></thead><tbody>
        {visible.rows.map(row => {
          const clues = filenameClues(row).filter(clue => !clue.startsWith('Filename Congress '));
          const context = [sourceHost(row.source_url) || recoveredSourceHost(row), row.source_committee_name?.join(' · ') || '', ...clues, congressWarning(row.congress, row.source_congress), row.source_count && row.source_count > 1 ? `${integer(row.source_count)} source records` : ''].filter(Boolean);
          const review = reviewStatusLabel(row._review_status);
          const kind = recordLabel(row);
          const role = recordRoleNote(row);
          const basis = kindBasis(row);
          const serverType = serverTypeNote(row);
          const savedBody = savedBodyNote(row);
          const responseCheck = responseCheckNote(row);
          const sourceType = sourceDocumentTypeNote(row);
          const contentKind = contentKindNote(row);
          const family = (row.document_family || []).map(pretty).filter(value => value && !kind.toLowerCase().includes(value.toLowerCase()));
          const http = httpStatusNote(row);
          const congress = congressLabel(row.congress);
          const sourceCongress = congressLabel(row.source_congress);
          const savedCongress = contentCongressLabel(row);
          const identity = filenameIdentity(row);
          const saved = contentAddressedFilename(identity);
          const copyNotes = [savedResponseLabel(row), responseCheck, ...captureNotes(row), checkedAtNote(row), retrievedAtNote(row), row.recovery?.kind && !row.format?.includes(row.recovery.kind) ? `Recovered ${formatLabel(row.recovery.kind)}` : '', http].filter(Boolean);
          return <tr key={`${row.source_id || row._row}`}>
            <td className="explorer-title-cell"><button className="explorer-text-button" title={identity} aria-label={`Open ${identity}`} onClick={() => onOpen(row)}>{saved ? <><span className="explorer-filename-hash">{saved.hash}.</span>{saved.name}</> : identity}</button>
              {context.length ? context.map(line => <span className="explorer-row-meta" key={line}>{line}</span>) : <span className="explorer-row-meta">No filename clues recorded</span>}
            </td>
            <td>{kind}{role && !kind.toLowerCase().includes(role.toLowerCase()) ? <span className="explorer-row-meta">{role}</span> : null}{family.length ? <span className="explorer-row-meta">{family.join(' · ')}</span> : null}{sourceType ? <span className="explorer-row-meta">{sourceType}</span> : null}{contentKind ? <span className="explorer-row-meta">{contentKind}</span> : null}{basis ? <span className="explorer-row-meta">{basis}</span> : null}{row.format?.length ? <span className="explorer-row-meta">{row.format.map(formatLabel).join(' · ')}</span> : null}{savedBody ? <span className="explorer-row-meta">{savedBody}</span> : null}{serverType ? <span className="explorer-row-meta">{serverType}</span> : null}{review ? <span className="explorer-row-meta">{review}</span> : null}</td>
            <td>{congress || sourceCongress || savedCongress || 'Congress unrecorded'}{!congress && sourceCongress ? <span className="explorer-row-meta">From the source record</span> : null}{savedCongress ? <span className="explorer-row-meta">From the saved contents</span> : null}{contentCongressNote(row) ? <span className="explorer-row-meta">{contentCongressNote(row)}</span> : null}{copyNotes.map(note => <span className="explorer-row-meta" key={note}>{note}</span>)}</td>
          </tr>;
        })}
      </tbody></table></div>
      <Pagination total={visible.total} offset={(visible.page - 1) * visible.limit} count={visible.rows.length} onPage={onPage} />
    </> : state.status === 'ready' ? <div className="explorer-alert"><p>{state.value.total ? 'This page is beyond the available results. Return to the first page to continue.' : 'No captured files match this selection.'}</p>{nav.page ? <button className="explorer-button" aria-label="This page is past the last result. Return to the first page." onClick={() => onPage(0)}>Return to first page</button> : null}</div> : null}
  </>;
}
