import {
  committeeShortLabel,
  congressLabel,
  formatSubject,
  type CommitteeCatalogInput,
} from './archive-metadata.ts';
import {day} from './ArchiveRows.tsx';
import {integer} from '../view/request-state.tsx';

export type ArchiveTab = 'documents' | 'hearings' | 'committees' | 'witnesses' | 'members' | 'subjects';

export const ARCHIVE_TABS: ReadonlyArray<{
  key: ArchiveTab;
  label: string;
  noun: string;
  singular: string;
}> = [
  {key: 'documents', label: 'Documents', noun: 'documents', singular: 'document'},
  {key: 'hearings', label: 'Hearings', noun: 'hearings', singular: 'hearing'},
  {key: 'committees', label: 'Committees', noun: 'committees', singular: 'committee'},
  {key: 'witnesses', label: 'Witnesses', noun: 'witnesses', singular: 'witness'},
  {key: 'members', label: 'Members', noun: 'members', singular: 'member'},
  {key: 'subjects', label: 'Bills & Nominations', noun: 'bills and nominations', singular: 'bill or nomination'},
];

export function normalizeArchiveTab(raw: string | null | undefined): ArchiveTab {
  const clean = String(raw ?? '').trim().toLowerCase();
  switch (clean) {
    case 'hearings':
    case 'hearing':
    case 'meetings':
    case 'meeting':
      return 'hearings';
    case 'committees':
    case 'committee':
      return 'committees';
    case 'witnesses':
    case 'witness':
      return 'witnesses';
    case 'members':
    case 'member':
      return 'members';
    case 'subjects':
    case 'subject':
    case 'bills':
    case 'bill':
    case 'nominations':
    case 'nomination':
      return 'subjects';
    default:
      return 'documents';
  }
}

export function tabTotalCount(tab: ArchiveTab, docCount?: number, entityCounts?: Record<string, number>): number | null {
  if (tab === 'documents') return typeof docCount === 'number' ? docCount : null;
  if (!entityCounts) return null;
  switch (tab) {
    case 'hearings':
      return entityCounts.meetings ?? null;
    case 'committees':
      return entityCounts.committees ?? null;
    case 'witnesses':
      return entityCounts.witnesses ?? null;
    case 'members':
      return entityCounts.members ?? null;
    case 'subjects': {
      const bills = entityCounts.bills ?? 0;
      const nominations = entityCounts.nominations ?? 0;
      return bills + nominations > 0 ? bills + nominations : (entityCounts.subjects ?? null);
    }
  }
}

export function ArchiveEntityRows({
  tab,
  rows,
  committeesCatalog,
  onInspectHearing,
  onInspectCommittee,
  onInspectWitness,
  onInspectMember,
  onInspectSubject,
}: {
  tab: Exclude<ArchiveTab, 'documents'>;
  rows: any[];
  committeesCatalog?: CommitteeCatalogInput;
  onInspectHearing: (key: string) => void;
  onInspectCommittee: (key: string) => void;
  onInspectWitness: (key: string) => void;
  onInspectMember: (bioguideId: string) => void;
  onInspectSubject: (key: string) => void;
}) {
  if (!rows.length) {
    return <p className="explorer-muted">No matching {ARCHIVE_TABS.find(t => t.key === tab)?.noun ?? 'records'} found.</p>;
  }
  return <ul className="archive-rows" data-archive-entity-list={tab}>{rows.map((item, idx) => {
    if (tab === 'hearings') {
      const ev = String(item.event_id ?? item.meeting_key ?? idx);
      const committeeNames = (item.committee_keys ?? [])
        .slice(0, 2)
        .map((ck: string) => committeeShortLabel(ck, committeesCatalog, item.meeting_date || item.congress));
      const contextParts = [
        congressLabel(item.congress),
        item.chamber ? String(item.chamber).charAt(0).toUpperCase() + String(item.chamber).slice(1) : null,
        ...committeeNames,
        item.meeting_type ? String(item.meeting_type) : null,
      ].filter(Boolean);
      const docCount = Array.isArray(item.list_rows) ? item.list_rows.length : 0;
      const witnessCount = Array.isArray(item.witnesses) ? item.witnesses.length : 0;
      return <li key={ev}>
        <div className="archive-row-main">
          {contextParts.length > 0 && <span className="archive-row-context">{contextParts.join(' · ')}</span>}
          <button type="button" className="archive-document" onClick={() => onInspectHearing(ev)}>
            <strong>{item.title || `Hearing ${ev}`}</strong>
            {item.status && <span className="archive-document-subtitle">Status: {item.status}</span>}
          </button>
        </div>
        <span className="archive-row-format">{ev}</span>
        <div className="archive-row-dates">
          {item.meeting_date ? <span>Hearing date: {day(item.meeting_date)}</span> : <span>Date not recorded</span>}
          <span>{integer(docCount)} {docCount === 1 ? 'document' : 'documents'}{witnessCount > 0 ? ` · ${integer(witnessCount)} ${witnessCount === 1 ? 'witness' : 'witnesses'}` : ''}</span>
        </div>
      </li>;
    }

    if (tab === 'committees') {
      const code = String(item.committee_key ?? item.system_code ?? idx).toLowerCase();
      const title = item.current_name || item.name || code.toUpperCase();
      const contextParts = [
        item.chamber ? String(item.chamber).charAt(0).toUpperCase() + String(item.chamber).slice(1) : null,
        item.type || item.committee_type,
        item.parent_key ? `Subcommittee of ${String(item.parent_key).toUpperCase()}` : null,
      ].filter(Boolean);
      const docCount = Number(item.doc_count ?? 0);
      const hearingCount = Number(item.hearing_count ?? 0);
      return <li key={code}>
        <div className="archive-row-main">
          {contextParts.length > 0 && <span className="archive-row-context">{contextParts.join(' · ')}</span>}
          <button type="button" className="archive-document" onClick={() => onInspectCommittee(code)}>
            <strong>{title}</strong>
            {item.jurisdiction && <span className="archive-document-subtitle">{String(item.jurisdiction).slice(0, 140)}{String(item.jurisdiction).length > 140 ? '…' : ''}</span>}
          </button>
        </div>
        <span className="archive-row-format">{code.toUpperCase()}</span>
        <div className="archive-row-dates">
          <span>{integer(docCount)} {docCount === 1 ? 'document' : 'documents'}</span>
          {hearingCount > 0 && <span>{integer(hearingCount)} {hearingCount === 1 ? 'hearing' : 'hearings'}</span>}
        </div>
      </li>;
    }

    if (tab === 'witnesses') {
      const wk = String(item.witness_key ?? item.name_key ?? idx);
      const orgs: string[] = Array.isArray(item.organizations) && item.organizations.length
        ? item.organizations
        : item.organization ? [String(item.organization)] : [];
      const positions: string[] = Array.isArray(item.positions) && item.positions.length
        ? item.positions
        : item.position ? [String(item.position)] : [];
      const appCount = Array.isArray(item.appearances) ? item.appearances.length : 0;
      const docCount = Array.isArray(item.list_rows) ? item.list_rows.length : 0;
      return <li key={wk}>
        <div className="archive-row-main">
          {orgs.length > 0 && <span className="archive-row-context">{orgs.slice(0, 2).join(' · ')}</span>}
          <button type="button" className="archive-document" onClick={() => onInspectWitness(wk)}>
            <strong>{item.name || wk}</strong>
            {positions.length > 0 && <span className="archive-document-subtitle">{positions.slice(0, 2).join(' · ')}</span>}
          </button>
        </div>
        <span className="archive-row-format">{appCount > 0 ? `${integer(appCount)} ${appCount === 1 ? 'hearing' : 'hearings'}` : 'Witness'}</span>
        <div className="archive-row-dates">
          <span>{integer(docCount)} {docCount === 1 ? 'document' : 'documents'}</span>
        </div>
      </li>;
    }

    if (tab === 'members') {
      const bio = String(item.bioguide_id ?? idx);
      const stateLabel = item.state ? (item.district != null ? `${item.state}-${item.district}` : String(item.state)) : null;
      const contextParts = [
        item.party,
        stateLabel,
        item.chamber ? String(item.chamber).charAt(0).toUpperCase() + String(item.chamber).slice(1) : null,
      ].filter(Boolean);
      const termCount = Array.isArray(item.terms) ? item.terms.length : 0;
      const docCount = Array.isArray(item.list_rows) ? item.list_rows.length : 0;
      return <li key={bio}>
        <div className="archive-row-main">
          {contextParts.length > 0 && <span className="archive-row-context">{contextParts.join(' · ')}</span>}
          <button type="button" className="archive-document" onClick={() => onInspectMember(bio)}>
            <strong>{item.name || bio}</strong>
          </button>
        </div>
        <span className="archive-row-format">{bio}</span>
        <div className="archive-row-dates">
          {termCount > 0 && <span>{integer(termCount)} {termCount === 1 ? 'term' : 'terms'}</span>}
          <span>{integer(docCount)} {docCount === 1 ? 'document' : 'documents'}</span>
        </div>
      </li>;
    }

    // tab === 'subjects'
    const sk = String(item.subject_key ?? item.bill_id ?? item.nomination_id ?? idx);
    const isNom = item.kind === 'nomination' || Boolean(item.nomination_id) || /^(?:\d+-)?pn-/i.test(sk);
    const label = formatSubject(sk, item);
    const heading = item.short_title || item.title || item.description || '';
    const contextParts = [
      congressLabel(item.congress),
      isNom ? 'Presidential Nomination' : 'Legislation',
      item.status || item.stage,
      item.policy_area,
    ].filter(Boolean);
    const docCount = Array.isArray(item.list_rows) ? item.list_rows.length : 0;
    const actionDate = day(item.latest_action_date || item.introduced_date || item.received_date);
    return <li key={sk}>
      <div className="archive-row-main">
        {contextParts.length > 0 && <span className="archive-row-context">{contextParts.join(' · ')}</span>}
        <button type="button" className="archive-document" onClick={() => onInspectSubject(sk)}>
          <strong>{label}{heading && heading !== label ? ` — ${heading}` : ''}</strong>
          {item.sponsor_name && <span className="archive-document-subtitle">Sponsor: {item.sponsor_name}</span>}
        </button>
      </div>
      <span className="archive-row-format">{label}</span>
      <div className="archive-row-dates">
        {actionDate && <span>{isNom ? 'Received/Action: ' : 'Action: '}{actionDate}</span>}
        <span>{integer(docCount)} {docCount === 1 ? 'document' : 'documents'}</span>
      </div>
    </li>;
  })}</ul>;
}
