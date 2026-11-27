import taxonomy from '../../../../../../model/registries/ban-park-you-org-taxonomy.json';
import {
  committeeLabel,
  presentDocument,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {PublicLink, day} from './ArchiveRows.tsx';
import {CitableReceipt} from './CitableReceipt.tsx';

const parentLabels = new Map<string, string>(
  (taxonomy.parent_categories ?? []).map((p: any) => [String(p.id), String(p.label)]),
);
const categoryMeta = new Map<string, {label: string; parentLabel: string}>(
  (taxonomy.categories ?? []).map((c: any) => [
    String(c.id),
    {label: String(c.label), parentLabel: String(c.parent_label ?? '')},
  ]),
);

function formatTaxonomy(org: any): string | null {
  const catId = org?.taxonomy_category ? String(org.taxonomy_category) : '';
  const parentId = org?.taxonomy_parent ? String(org.taxonomy_parent) : '';
  const cat = catId ? categoryMeta.get(catId) : undefined;
  const parentLabel = (parentId ? parentLabels.get(parentId) : undefined) || cat?.parentLabel || parentId;
  const catLabel = cat?.label || catId;
  if (parentLabel && catLabel && parentLabel.toLowerCase() !== catLabel.toLowerCase()) {
    return `${parentLabel} — ${catLabel}`;
  }
  return catLabel || parentLabel || null;
}

function externalIdUrl(scheme: string, value: string): string | null {
  const s = scheme.trim().toLowerCase();
  const v = value.trim();
  if (s === 'wikidata' && /^Q\d+$/i.test(v)) {
    return `https://www.wikidata.org/wiki/${encodeURIComponent(v.toUpperCase())}`;
  }
  if (s === 'ror' && v) {
    return v.startsWith('http') ? v : `https://ror.org/${encodeURIComponent(v)}`;
  }
  return null;
}

export function OrganizationDetail({
  organization,
  committeesCatalog,
  rawBase,
  releaseId,
  compact,
  onSelect,
  onHearing,
  onWitness,
  onCommittee,
  onOrganization,
  onFilterDocuments,
  onInspect,
  onClose,
  closeLabel,
}: {
  organization: any;
  committeesCatalog?: CommitteeCatalogInput;
  rawBase?: string;
  releaseId?: string;
  compact?: boolean;
  onSelect?: (row: number) => void;
  onHearing?: (key: string) => void;
  onWitness?: (key: string) => void;
  onCommittee?: (key: string) => void;
  onOrganization?: (orgId: string) => void;
  onFilterDocuments?: () => void;
  onInspect?: () => void;
  onClose?: () => void;
  closeLabel?: string;
}) {
  if (!organization) return null;
  if (organization.retired) {
    const oldId = String(organization.retired.old_org_id ?? organization.org_id ?? '');
    return <section className="archive-entity-card" aria-label="Organization details" data-archive-entity="organization">
      <p role="status" className="archive-removed-notice">
        The organization link you followed ({oldId}) is no longer active in this release.
      </p>
    </section>;
  }

  const redirectedFrom: string | null = organization.redirectedFrom ?? organization.redirected_from ?? null;
  const externalIds: any[] = Array.isArray(organization.organization_ids) ? organization.organization_ids : [];
  const childOrgs: any[] = Array.isArray(organization.child_orgs) ? organization.child_orgs : [];
  const appearances: any[] = Array.isArray(organization.appearances) ? organization.appearances : [];
  const documents: any[] = Array.isArray(organization.documents) ? organization.documents : [];
  const shownAppearances = compact ? appearances.slice(0, 5) : appearances;
  const taxonomyLabel = formatTaxonomy(organization);

  return <section className="archive-entity-card" aria-label="Organization details" data-archive-entity="organization">
    {redirectedFrom && <p role="status" className="archive-redirect-note">
      The organization link you followed ({redirectedFrom}) now points to this organization.
    </p>}
    <header className="archive-entity-header">
      <div className="archive-entity-header-top">
        <p className="archive-detail-context">Witness Organization Profile</p>
        <div className="archive-pill-list">
          {onInspect && <button type="button" className="archive-measure-pill" onClick={onInspect}>Open full profile →</button>}
          {onFilterDocuments && <button type="button" className="archive-measure-pill" onClick={onFilterDocuments}>Filter documents in Document Search</button>}
          {onClose && <button type="button" className="archive-measure-pill" onClick={onClose}>{closeLabel || 'Close organization profile'}</button>}
        </div>
      </div>
      <h2>{organization.display_name || organization.org_id}</h2>
      {taxonomyLabel && <p className="archive-entity-meta"><strong>Category (Ban–Park–You):</strong> {taxonomyLabel}</p>}
      {organization.kind && <p className="archive-entity-meta"><strong>Kind:</strong> {String(organization.kind)}</p>}
      {organization.parent_org_id && <p className="archive-entity-meta">
        <strong>Parent organization:</strong>{' '}
        {onOrganization
          ? <button type="button" className="archive-measure-pill" onClick={() => onOrganization(String(organization.parent_org_id))}>
              {organization.parent_org?.display_name || organization.parent_org_id}
            </button>
          : <span>{organization.parent_org?.display_name || organization.parent_org_id}</span>}
      </p>}
      {childOrgs.length > 0 && <p className="archive-entity-meta">
        <strong>Sub-organizations:</strong>{' '}
        <span className="archive-pill-list">
          {childOrgs.map((child: any) => onOrganization
            ? <button key={child.org_id} type="button" className="archive-measure-pill" onClick={() => onOrganization(String(child.org_id))}>
                {child.display_name || child.org_id}
              </button>
            : <span key={child.org_id} className="archive-measure-pill">{child.display_name || child.org_id}</span>)}
        </span>
      </p>}
      {externalIds.length > 0 && <div className="archive-entity-meta">
        <strong>External identifiers:</strong>{' '}
        <span className="archive-pill-list">
          {externalIds.map((id: any, idx: number) => {
            const scheme = String(id.scheme ?? id.id_scheme ?? '').trim();
            const value = String(id.value ?? id.id_value ?? '').trim();
            const href = externalIdUrl(scheme, value);
            const text = scheme ? `${scheme}: ${value}` : value;
            return href
              ? <span key={`${scheme}:${value}:${idx}`} className="archive-measure-pill"><PublicLink url={href}>{text}</PublicLink></span>
              : <span key={`${scheme}:${value}:${idx}`} className="archive-measure-pill">{text}</span>;
          })}
        </span>
      </div>}
      <p className="archive-source-meta">
        Organization ID: <code>{organization.org_id}</code> · {Number(organization.appearance_count ?? appearances.length)} linked witness {Number(organization.appearance_count ?? appearances.length) === 1 ? 'appearance' : 'appearances'}
      </p>
      {!compact && organization.org_id && <CitableReceipt kind="organization" releaseId={releaseId} rawBase={rawBase} orgId={String(organization.org_id)} />}
    </header>

    {appearances.length > 0 && <div className="archive-entity-section">
      <h3>Witness Appearances ({appearances.length})</h3>
      <ul className="archive-entity-list">
        {shownAppearances.map((app: any, i: number) => {
          const ev = String(app.event_id ?? '').trim();
          const cleanTitle = String(app.meeting_title || app.title || '').trim().replace(/^[-–—]+\s+/, '').trim();
          const title = cleanTitle || (ev ? `Hearing ${ev}` : 'Recorded Witness Appearance');
          return <li key={`${app.witness_key}:${ev}:${app.field ?? ''}:${i}`}>
            {ev && onHearing
              ? <button type="button" className="explorer-text-button" onClick={() => onHearing(ev)}><strong>{title}</strong></button>
              : <strong>{title}</strong>}
            {app.meeting_date && <span className="archive-source-meta"> · {day(app.meeting_date)}</span>}
            {app.witness_key && <>
              <span aria-hidden="true"> · </span>
              {onWitness
                ? <button type="button" className="archive-measure-pill" onClick={() => onWitness(String(app.witness_key))}>{app.witness_name || app.witness_key}</button>
                : <span>{app.witness_name || app.witness_key}</span>}
            </>}
            {(app.position || app.raw_text || app.field) && <p className="archive-source-meta">
              {[app.position, app.raw_text ? `Listed as "${app.raw_text}"` : null, app.field ? `(${app.field})` : null].filter(Boolean).join(' · ')}
            </p>}
            {Array.isArray(app.committee_keys) && app.committee_keys.length > 0 && <div className="archive-pill-list">
              {app.committee_keys.map((ck: string) => onCommittee
                ? <button key={ck} type="button" className="archive-measure-pill" onClick={() => onCommittee(ck)}>{committeeLabel(ck, committeesCatalog, app.meeting_date || app.congress)}</button>
                : <span key={ck} className="archive-measure-pill">{committeeLabel(ck, committeesCatalog, app.meeting_date || app.congress)}</span>)}
            </div>}
          </li>;
        })}
      </ul>
    </div>}

    {!compact && documents.length > 0 && onSelect && <div className="archive-entity-section">
      <h3>Submitted Documents ({documents.length})</h3>
      <ul className="archive-entity-list">
        {documents.slice(0, 20).map((doc: any) => {
          const pres = presentDocument(doc, undefined, undefined, undefined, committeesCatalog);
          return <li key={doc.list_row}>
            <button type="button" className="explorer-text-button" onClick={() => onSelect(doc.list_row)}>{pres.title}</button>
            <span className="archive-source-meta">
              {doc.document_date ? ` · ${day(doc.document_date)}` : ''}
              {pres.kinds[0] ? ` · ${pres.kinds[0]}` : ''}
              {pres.format ? ` (${pres.format})` : ''}
            </span>
          </li>;
        })}
      </ul>
    </div>}
  </section>;
}
