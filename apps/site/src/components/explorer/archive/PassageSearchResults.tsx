import {useState} from 'react';
import {
  readSpicySection,
  type PassageHit,
  type PassageSearchResponse,
} from './spicy-search.ts';
import {SPICYENGINE_SEARCH_ORIGIN} from './search-config.ts';
import {PublicLink} from './ArchiveRows.tsx';
import {integer} from '../view/request-state.tsx';

export type SearchMode = 'metadata' | 'passages' | 'top_orgs';

export function normalizeSearchMode(raw: string | null | undefined): SearchMode {
  const clean = String(raw ?? '').trim().toLowerCase();
  if (clean === 'passages' || clean === 'fulltext' || clean === 'hybrid') return 'passages';
  if (clean === 'top_orgs' || clean === 'orgs_topic') return 'top_orgs';
  return 'metadata';
}

const EXAMPLE_TOPICS = ['artificial intelligence', 'supply chain', 'water infrastructure', 'cybersecurity'];

export function GuidedRecipesBar({
  mode,
  currentQuery,
  onSelectMode,
  onRunRecipe,
  onOpenAccountability,
}: {
  mode: SearchMode;
  currentQuery: string;
  onSelectMode: (mode: SearchMode) => void;
  onRunRecipe: (mode: SearchMode, topic: string) => void;
  onOpenAccountability: () => void;
}) {
  return <div className="archive-recipes" aria-label="Search mode and guided question recipes">
    <div className="archive-mode-switch" role="group" aria-label="Document search mode">
      <button
        type="button"
        className={mode === 'metadata' ? 'archive-measure-pill archive-pill-active' : 'archive-measure-pill'}
        aria-pressed={mode === 'metadata'}
        onClick={() => onSelectMode('metadata')}
      >
        Metadata &amp; URLs
      </button>
      <button
        type="button"
        className={mode === 'passages' ? 'archive-measure-pill archive-pill-active' : 'archive-measure-pill'}
        aria-pressed={mode === 'passages'}
        onClick={() => onSelectMode('passages')}
      >
        Full-text passages
      </button>
      <button
        type="button"
        className={mode === 'top_orgs' ? 'archive-measure-pill archive-pill-active' : 'archive-measure-pill'}
        aria-pressed={mode === 'top_orgs'}
        onClick={() => onSelectMode('top_orgs')}
      >
        Top testifying organizations
      </button>
    </div>
    <div className="archive-recipe-pills">
      <span className="archive-source-meta">Guided questions:</span>
      <button
        type="button"
        className="archive-filter-pill"
        onClick={() => onRunRecipe('passages', currentQuery.trim() || 'artificial intelligence')}
      >
        Testimony mentioning…
      </button>
      <button
        type="button"
        className="archive-filter-pill"
        onClick={() => onRunRecipe('top_orgs', currentQuery.trim() || 'artificial intelligence')}
      >
        Top testifying organizations on…
      </button>
      <button
        type="button"
        className="archive-filter-pill"
        onClick={onOpenAccountability}
      >
        Removed or recovered committee documents →
      </button>
    </div>
    {mode !== 'metadata' && <div className="archive-recipe-examples">
      <span className="archive-source-meta">Try topic:</span>
      {EXAMPLE_TOPICS.map(topic => <button
        key={topic}
        type="button"
        className="explorer-text-button"
        onClick={() => onRunRecipe(mode, topic)}
      >
        {topic}
      </button>)}
    </div>}
  </div>;
}

function PassageHitCard({
  hit,
  onOpenKey,
}: {
  hit: PassageHit;
  onOpenKey: (linkKey: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sectionState, setSectionState] = useState<{content?: string; reason?: string} | null>(null);

  async function togglePassage() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (sectionState !== null) return;
    setLoading(true);
    const res = await readSpicySection(hit.url);
    setLoading(false);
    setSectionState(res.state === 'ready' ? {content: res.content} : {reason: res.reason});
  }

  return <li>
    <div className="archive-row-main">
      <span className="archive-row-context">
        {[hit.crumb, hit.kind === 'text' ? 'Indexed passage' : hit.kind].filter(Boolean).join(' · ')}
      </span>
      {hit.linkKey ? (
        <button type="button" className="archive-document" onClick={() => onOpenKey(hit.linkKey!)}>
          <strong>{hit.title}</strong>
        </button>
      ) : (
        <strong className="archive-passage-title">{hit.title}</strong>
      )}
      {hit.snippet && <p className="archive-passage-snippet">{hit.snippet}</p>}
      <div className="archive-pill-list">
        {hit.linkKey && <button type="button" className="archive-measure-pill" onClick={() => onOpenKey(hit.linkKey!)}>
          Open document in Explorer →
        </button>}
        <button type="button" className="archive-measure-pill" aria-expanded={expanded} onClick={togglePassage}>
          {expanded ? 'Hide full passage' : 'Read passage'}
        </button>
        {hit.publisherUrl && <span className="archive-measure-pill"><PublicLink url={hit.publisherUrl}>Publisher page</PublicLink></span>}
        {hit.sourceUrl && <span className="archive-measure-pill"><PublicLink url={hit.sourceUrl}>Source file</PublicLink></span>}
      </div>
      {expanded && <div className="archive-passage-expanded">
        {loading ? <p className="archive-source-meta">Loading passage…</p>
          : sectionState?.content ? <p style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{sectionState.content}</p>
            : <p className="archive-source-meta">{sectionState?.reason || 'Passage text is unavailable from the search service.'}</p>}
      </div>}
    </div>
    <span className="archive-row-format">{hit.crumb || 'Passage'}</span>
    <div className="archive-row-dates">
      {hit.linkKey && <span>key: {hit.linkKey}</span>}
    </div>
  </li>;
}

export function PassageResults({
  data,
  activeReleaseId,
  onOpenKey,
  onRetry,
  onSwitchToMetadata,
}: {
  data: PassageSearchResponse;
  activeReleaseId?: string;
  onOpenKey: (linkKey: string) => void;
  onRetry: () => void;
  onSwitchToMetadata: () => void;
}) {
  if (!data.query) {
    return <p className="explorer-muted">
      Enter keywords or a quoted phrase above to search full document passages via SpicyEngine (<code>{SPICYENGINE_SEARCH_ORIGIN}</code>).
    </p>;
  }

  if (data.state === 'unavailable') {
    return <div role="status" className="archive-notice">
      <h2>Full-text passage search is currently unreachable from this browser</h2>
      <p>
        {data.reason ? `${data.reason}. ` : ''}
        Metadata &amp; URL search remains available directly in your browser, or you can query <code>search_docs</code> through Congress Explorer MCP.
      </p>
      <div className="archive-pill-list">
        <button type="button" className="archive-measure-pill" onClick={onRetry}>Retry passage search</button>
        <button type="button" className="archive-measure-pill" onClick={onSwitchToMetadata}>Switch to Metadata &amp; URLs</button>
      </div>
    </div>;
  }

  return <section aria-label="Full-text passage results" data-archive-passage-results>
    {data.releaseMismatch && data.releaseId && activeReleaseId && <p role="status" className="archive-notice">
      Passage search indexed release <code>{data.releaseId.slice(0, 12)}</code>, which differs from the active archive release <code>{activeReleaseId.slice(0, 12)}</code>.
    </p>}
    <div className="archive-results-bar">
      <p className="archive-total" data-archive-total>
        {data.results.length === 0
          ? '0 matching passages'
          : `${integer(data.results.length)}${data.hasMore ? '+' : ''} matching passages (${data.mode}${data.tookMs != null ? `, ${integer(data.tookMs)} ms` : ''})`}
      </p>
    </div>
    {data.results.length === 0 ? (
      <div className="archive-zero-boundary" role="status">
        <p className="explorer-muted">
          No indexed passages matched &ldquo;{data.query}&rdquo; in this release. Full-text search indexes extracted document text;
          metadata-only or unextracted files can still appear under Metadata &amp; URLs search.
        </p>
        <button type="button" className="archive-measure-pill" onClick={onSwitchToMetadata}>
          Search metadata &amp; filenames instead
        </button>
      </div>
    ) : (
      <ul className="archive-rows archive-passage-rows">
        {data.results.map((hit, idx) => <PassageHitCard key={`${hit.id}:${idx}`} hit={hit} onOpenKey={onOpenKey} />)}
      </ul>
    )}
  </section>;
}

export function TopOrganizationsResults({
  data,
  onInspectOrganization,
  onSwitchToMetadata,
}: {
  data: any;
  onInspectOrganization: (orgId: string) => void;
  onSwitchToMetadata: () => void;
}) {
  if (!data) return null;
  if (!data.topic) {
    return <p className="explorer-muted">
      Enter a topic above (or choose an example topic) to rank organizations linked to matching hearings and witness documents.
    </p>;
  }
  if (data.state === 'unavailable') {
    return <p className="explorer-muted">{data.reason || 'Organizations are not published in this release.'}</p>;
  }
  const rows: any[] = Array.isArray(data.rows) ? data.rows : [];
  return <section aria-label="Top testifying organizations results" data-archive-top-orgs>
    <div className="archive-results-bar">
      <p className="archive-total" data-archive-total>
        {rows.length === 0
          ? '0 linked organizations found'
          : `Top ${integer(rows.length)} of ${integer(data.totalOrgs)} testifying organizations on "${data.topic}"`}
      </p>
      <span className="archive-source-meta">
        Matched {integer(data.matchedHearings)} {data.matchedHearings === 1 ? 'hearing' : 'hearings'} and {integer(data.matchedDocuments)} {data.matchedDocuments === 1 ? 'document' : 'documents'}
      </span>
    </div>
    <p className="archive-source-meta">
      Counts reflect linked witness-organization records in matching hearings and documents in this release; unlinked witness affiliation strings are not included.
    </p>
    {rows.length === 0 ? (
      <div className="archive-zero-boundary" role="status">
        <p className="explorer-muted">
          No linked testifying organizations matched &ldquo;{data.topic}&rdquo; in this release.
        </p>
        <button type="button" className="archive-measure-pill" onClick={onSwitchToMetadata}>
          Search document metadata instead
        </button>
      </div>
    ) : (
      <ul className="archive-rows">
        {rows.map((org: any) => <li key={org.org_id}>
          <div className="archive-row-main">
            <span className="archive-row-context">
              {[org.taxonomy_parent, org.taxonomy_category, org.kind].filter(Boolean).join(' · ')}
            </span>
            <button type="button" className="archive-document" onClick={() => onInspectOrganization(org.org_id)}>
              <strong>{org.display_name || org.org_id}</strong>
              {Array.isArray(org.sample_hearings) && org.sample_hearings.length > 0 && (
                <span className="archive-document-subtitle">e.g. {org.sample_hearings[0]}</span>
              )}
            </button>
          </div>
          <span className="archive-row-format">{org.org_id}</span>
          <div className="archive-row-dates">
            <span>{integer(org.matching_appearances)} matching {org.matching_appearances === 1 ? 'appearance' : 'appearances'}</span>
            <span>{integer(org.matching_hearings)} {org.matching_hearings === 1 ? 'hearing' : 'hearings'}</span>
          </div>
        </li>)}
      </ul>
    )}
  </section>;
}
