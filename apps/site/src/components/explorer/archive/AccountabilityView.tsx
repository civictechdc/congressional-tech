import {
  cleanIdentityNote,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day, siteBase} from './ArchiveRows.tsx';
import {recoveryLabel} from '../reader/archive.ts';
import {integer} from '../view/request-state.tsx';

export type AccountabilityKind = 'all' | 'removed' | 'retired' | 'recovered' | 'identity_notes' | 'multi_edition';

const CHURN_LABELS: Record<string, string> = {
  removed_on: 'Removed from hearing page',
  review_removed: 'Removed by review',
  retired_redirected: 'Retired key (redirected to successor)',
  retired_removed: 'Retired key (no successor)',
  recovered_only: 'Recovered-only document',
  identity_note: 'Recovery identity note',
  multi_edition: 'Multi-edition document',
};

export function AccountabilityView({
  data,
  committeesCatalog,
  kindFilter,
  onKindFilter,
  onSelect,
  onNavigateKey,
  offset,
  pageSize,
  onOffsetChange,
}: {
  data: any;
  committeesCatalog?: CommitteeCatalogInput;
  kindFilter: AccountabilityKind;
  onKindFilter: (kind: AccountabilityKind) => void;
  onSelect: (listRow: number) => void;
  onNavigateKey: (key: string) => void;
  offset: number;
  pageSize: number;
  onOffsetChange: (nextOffset: number) => void;
}) {
  if (!data) return null;
  const counts = data.counts ?? {};
  const availability = data.availability ?? {};
  const rows: any[] = Array.isArray(data.rows) ? data.rows : [];
  const feedHref = `${siteBase()}/archive/feed.xml`;

  const filters: Array<{key: AccountabilityKind; label: string; count?: number}> = [
    {key: 'all', label: 'All churn & accountability'},
    {key: 'removed', label: 'Removed', count: (counts.removedOn ?? 0) + (counts.hidden ?? 0) + (counts.retiredRemoved ?? 0)},
    {key: 'retired', label: 'Retired / successor_key', count: (counts.retiredRedirected ?? 0) + (counts.retiredRemoved ?? 0)},
    {key: 'recovered', label: 'Recovered-only', count: counts.recoveredOnly ?? 0},
    {key: 'identity_notes', label: 'Identity notes', count: counts.withIdentityNote ?? 0},
    {key: 'multi_edition', label: 'Multi-edition', count: counts.multiEdition ?? 0},
  ];

  const missingNotices = [
    availability.retiredLinks === 'missing' ? 'Retired link records (retired_links.parquet) are not published in this release.' : null,
    availability.removedOn === 'missing' ? 'Hearing-page removal dates (detail.removed_on) are not published in this release.' : null,
    availability.recoveries === 'missing' ? 'Recovery records (recoveries.parquet) are not published in this release.' : null,
  ].filter(Boolean) as string[];

  return <section className="archive-accountability" aria-label="Accountability and release churn" data-archive-accountability>
    <div className="archive-accountability-header">
      <div>
        <h2>Accountability &amp; Release Churn</h2>
        <p className="archive-source-meta">
          Track quietly removed documents (<code>removed_on</code> and retired keys), successor redirects (<code>successor_key</code>),
          multi-edition documents (<code>document_editions</code>), and recovered-only records with authored <code>identity_note</code> evidence.
        </p>
      </div>
      <a className="archive-measure-pill" href={feedHref}>Atom churn feed</a>
    </div>

    {missingNotices.length > 0 && <div role="status" className="archive-notice">
      {missingNotices.map(msg => <p key={msg}>{msg}</p>)}
    </div>}

    <div className="archive-pill-list archive-accountability-filters" role="group" aria-label="Filter accountability records">
      {filters.map(item => <button
        key={item.key}
        type="button"
        className={kindFilter === item.key ? 'archive-measure-pill archive-pill-active' : 'archive-measure-pill'}
        aria-pressed={kindFilter === item.key}
        onClick={() => onKindFilter(item.key)}
      >
        {item.label}{typeof item.count === 'number' ? ` (${integer(item.count)})` : ''}
      </button>)}
    </div>

    <div className="archive-results-bar">
      <p className="archive-total" data-archive-total>
        {data.total === 1 ? '1 accountability record' : `${integer(data.total)} accountability records`}
      </p>
    </div>

    {rows.length === 0 ? (
      <p className="explorer-muted">
        {kindFilter === 'removed' && availability.removedOn === 'ready' && counts.removedOn === 0 && counts.hidden === 0 && counts.retiredRemoved === 0
          ? '0 matching documents carry a removal notice or removed_on date under the current filters.'
          : 'No matching accountability records found in this release under the current filters.'}
      </p>
    ) : (
      <>
        <ul className="archive-rows archive-accountability-rows">
          {rows.map((item: any, idx: number) => {
            const kindLabel = CHURN_LABELS[item.churn_kind] ?? item.churn_kind;
            const isRetired = item.churn_kind === 'retired_redirected' || item.churn_kind === 'retired_removed';
            if (isRetired) {
              const versions: string[] = Array.isArray(item.address_versions) ? item.address_versions : [];
              return <li key={`${item.churn_kind}:${item.link_key}:${idx}`}>
                <div className="archive-row-main">
                  <span className="archive-row-context">
                    {kindLabel}
                    {item.last_release_id ? ` · Last release ${String(item.last_release_id).slice(0, 12)}` : ''}
                  </span>
                  <div className="archive-accountability-title">
                    <strong>{item.last_filename || `Retired key ${item.link_key}`}</strong>
                    <span className="archive-document-subtitle">link_key: {item.link_key}</span>
                  </div>
                  <div className="archive-pill-list">
                    {item.successor_key ? (
                      <button type="button" className="archive-measure-pill" onClick={() => onNavigateKey(item.successor_key)}>
                        Open successor ({item.successor_key}) →
                      </button>
                    ) : (
                      <button type="button" className="archive-measure-pill" onClick={() => onNavigateKey(item.link_key)}>
                        View removal notice →
                      </button>
                    )}
                    {versions.length > 0 && <span className="archive-source-meta">
                      {versions.length} other {versions.length === 1 ? 'edition' : 'editions'} at this address
                    </span>}
                  </div>
                </div>
                <span className="archive-row-format">{item.successor_key ? 'Redirect' : 'Removed'}</span>
                <div className="archive-row-dates">
                  <span>{item.successor_key ? 'Has successor_key' : 'No successor'}</span>
                </div>
              </li>;
            }

            const doc = item.document ?? {};
            const presented = presentDocument(doc, undefined, undefined, item.recoveries, committeesCatalog);
            const recs: any[] = Array.isArray(item.recoveries) ? item.recoveries : [];
            const notes = recs.map(r => cleanIdentityNote(r.identity_note)).filter(Boolean) as string[];
            const firstRec = recs[0];

            return <li key={`${item.churn_kind}:${item.list_row}:${idx}`}>
              <div className="archive-row-main">
                <span className="archive-row-context">
                  {[kindLabel, ...presented.contextParts].filter(Boolean).join(' · ')}
                </span>
                <button type="button" className="archive-document" onClick={() => onSelect(item.list_row)}>
                  <strong>{presented.title}</strong>
                  {presented.subtitle && <span className="archive-document-subtitle">{presented.subtitle}</span>}
                </button>
                {item.review_note && <p className="archive-source-meta">Review note: {item.review_note}</p>}
                {firstRec && <p className="archive-source-meta">
                  {recoveryLabel(firstRec.kind)}
                  {firstRec.imported_at ? ` · Added ${day(firstRec.imported_at)}` : ''}
                  {firstRec.recovered_url && <> · <PublicLink url={firstRec.recovered_url}>Recovery source</PublicLink></>}
                </p>}
                {notes.map((n, ni) => <p key={ni} className="archive-accountability-note">{n}</p>)}
              </div>
              <span className="archive-row-format">{presented.format || 'DOC'}</span>
              <div className="archive-row-dates">
                {item.removed_on && <span className="archive-row-removed">Removed {day(item.removed_on)}</span>}
                {item.edition_count > 0 && <span>{integer(item.edition_count)} linked {item.edition_count === 1 ? 'edition' : 'editions'}</span>}
                {doc.document_date ? <span>Document date: {day(doc.document_date)}</span> : doc.first_captured ? <span>Captured {day(doc.first_captured)}</span> : null}
              </div>
            </li>;
          })}
        </ul>
        <nav className="explorer-pagination" aria-label="Accountability pages">
          <button type="button" className="explorer-button" disabled={!offset} onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}>Previous</button>
          <span>{data.total ? integer(offset + 1) : 0}–{integer(Math.min(offset + rows.length, data.total))} of {integer(data.total)}</span>
          <button type="button" className="explorer-button" disabled={data.next === null} onClick={() => onOffsetChange(data.next)}>Next</button>
        </nav>
      </>
    )}
  </section>;
}
