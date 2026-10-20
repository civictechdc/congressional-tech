import type { Navigation } from '../browse/navigation.ts';
import { filenameSearchParams } from '../browse/filename-search.ts';
import { congressLabel, documentKindLabel, fieldLabel, filenameClues, filenameIdentity, formatLabel, pretty, reviewStatusLabel, savedResponseLabel } from '../browse/filename-presentation.ts';
import { filenameRequest } from '../reader/filenames/session.ts';
import type { FilenameCatalogInfo, FilenameRecord, FilenameSearchResult } from '../reader/filenames/types.ts';
import { Pagination, RequestMessage, integer, useRequest } from './request-state';

const searchFields = ['filename', 'source_url', 'source_page_url', 'source_link_label', 'document_kind', 'congress', 'source_congress', 'content_congress'];

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
    <label>Saved copy<select value={nav.retained} onChange={event => onChange({ retained: event.target.value === 'yes' || event.target.value === 'no' ? event.target.value : '' })}><option value="">Any</option><option value="yes">Saved</option><option value="no">None saved</option></select></label>
    <label>Document kind<select value={nav.document_kind} onChange={event => onChange({ document_kind: event.target.value })}><option value="">All kinds</option><option value="__null__">Unclassified</option>{kinds.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
    <label>Format<select value={nav.format} onChange={event => onChange({ format: event.target.value })}><option value="">All formats</option>{formats.map(value => <option key={value} value={value}>{formatLabel(value)}</option>)}</select></label>
    <details className="explorer-filter-more">
      <summary>More filters</summary>
      <label>Search field<select value={nav.field || 'filename'} onChange={event => onChange({ field: event.target.value === 'filename' ? '' : event.target.value })}>{fields.map(key => <option key={key} value={key}>{fieldLabel(key)}</option>)}</select></label>
      <label>Broad category<select value={nav.document_family} onChange={event => onChange({ document_family: event.target.value })}><option value="">All categories</option><option value="__null__">Unclassified</option>{family.map(value => <option key={value} value={value}>{pretty(value)}</option>)}</select></label>
      {info.complete_body_reviews || nav.classification ? <label>Catalog<select value={nav.classification} onChange={event => onChange({ classification: event.target.value === 'reviewed' ? 'reviewed' : '', review: event.target.value === 'reviewed' ? info.review_sha256 || '' : '' })}><option value="">Original</option><option value="reviewed" disabled={!info.reviewed_search}>Reviewed categories</option></select></label> : null}
    </details>
  </>;
}

export function FilenameListing({ nav, info, onOpen, onPage }: { nav: Navigation; info: FilenameCatalogInfo; onOpen: (row: FilenameRecord) => void; onPage: (page: number) => void }) {
  const query = filenameSearchParams(nav, info);
  const [state, retry] = useRequest(signal => filenameRequest<FilenameSearchResult>(`/api/rows?${query}`, signal), [query]);
  const congressSkipped = nav.congress !== 'all' && !facetValues(info, 'congress').includes(nav.congress);
  const heading = nav.scope === 'capture-records' ? 'Source & capture records' : nav.scope === 'all' ? 'All captured records' : 'Documents';
  return <>
    <div className="explorer-subheading"><h2>{heading}</h2>{state.status === 'ready' ? <span className="explorer-muted">{integer(state.value.total)} {state.value.total === 1 ? 'record' : 'records'}</span> : null}</div>
    <p className="explorer-note">{nav.scope === 'capture-records' ? 'Source and capture records, including API references that are not saved documents.' : nav.scope === 'all' ? 'Every captured record, including documents and capture metadata.' : 'Files found on committee sites, including files that are not matched to a meeting.'} Chamber, committee, and date filters do not apply in this list.</p>
    {congressSkipped ? <p className="explorer-note">The filename catalog has no entries for the {nav.congress}th Congress, so that Congress filter is not applied here.</p> : null}
    {nav.classification === 'reviewed' ? <p className="explorer-note">{info.reviewed_search ? `Search uses ${integer(info.reviewed_groups || 0)} assistant-reviewed groups. Downloads keep the original catalog.` : info.review_error || 'Reviewed categories are unavailable. Choose Original.'}</p> : null}
    {state.status === 'loading' ? <p className="explorer-loading" role="status">Searching the captured-file catalog. This can take about 30 seconds.</p> : state.status !== 'ready' ? <RequestMessage state={state} retry={retry} noun="captured files" /> : state.value.rows.length ? <>
      <div className="explorer-table-scroll"><table className="explorer-table"><thead><tr>
        <th scope="col">Record</th><th scope="col">Document kind</th><th scope="col">Congress / saved copy</th>
      </tr></thead><tbody>
        {state.value.rows.map(row => {
          const clues = filenameClues(row);
          const review = reviewStatusLabel(row._review_status);
          const kind = documentKindLabel(row);
          return <tr key={`${row.source_id || row._row}`}>
            <td className="explorer-title-cell"><button className="explorer-text-button" onClick={() => onOpen(row)}>{filenameIdentity(row)}</button>
              <span className="explorer-row-meta">{[sourceHost(row.source_url), row.source_committee_name?.join(' · ') || '', clues.join(' · ') || 'None recorded', row.source_count && row.source_count > 1 ? `${integer(row.source_count)} source records` : ''].filter(Boolean).join(' · ')}</span>
            </td>
            <td>{kind}{review ? <span className="explorer-row-meta">{review}</span> : null}</td>
            <td>{congressLabel(row.congress) || 'Congress unrecorded'}<span className="explorer-row-meta">{savedResponseLabel(row)}{row.recovery?.kind && !row.format?.includes(row.recovery.kind) ? ` · Recovered ${formatLabel(row.recovery.kind)}` : ''}</span></td>
          </tr>;
        })}
      </tbody></table></div>
      <Pagination total={state.value.total} offset={(state.value.page - 1) * state.value.limit} count={state.value.rows.length} onPage={onPage} />
    </> : <div className="explorer-alert"><p>{state.value.total ? 'This page is beyond the available results. Return to the first page to continue.' : 'No captured files match this selection.'}</p>{nav.page ? <button className="explorer-button" onClick={() => onPage(0)}>Return to first page</button> : null}</div>}
  </>;
}
