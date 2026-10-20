import type { ExplorerQuery } from '../reader/types.ts';
import type { CoverageAspect } from './kinds.ts';
import { accessStates, committeeTypes, isAccessState, isCommitteeType, isCoverageAspect, isFilenameScope, isIssueCategory, isIssueHistory, isIssueSeverity, isIssueStatus, isMaterialCategory, isMaterialProvider, isMeetingStatus, isRetainedFilter, isView, isWitnessParticipation, materialCategories, materialProviders, type FilenameScope, type IssueHistory, type MaterialProvider, type RetainedFilter, type View, type WitnessParticipation } from './kinds.ts';

export { accessStates, committeeTypes, materialCategories, materialProviders };
export type { View };

export interface Navigation {
  view: View;
  congress: string;
  chamber: string;
  q: string;
  from: string;
  to: string;
  type: string;
  status: string;
  category: string;
  severity: string;
  materialCategory: string;
  participation: '' | WitnessParticipation;
  provider: '' | MaterialProvider;
  history: '' | IssueHistory;
  access: string;
  page: number;
  kind: string;
  id: string;
  committee: string;
  committeeLevel: '' | 'full';
  committeeType: string;
  month: string;
  aspect: string;
  evidence: string;
  measure: CoverageAspect;
  grouping: 'congress' | 'month';
  scope: FilenameScope;
  retained: RetainedFilter;
  document_family: string;
  document_kind: string;
  format: string;
  field: string;
  classification: '' | 'reviewed';
  review: string;
  catalog: string;
  sort: '' | 'record' | 'date' | 'kind' | 'congress';
  direction: '' | 'asc' | 'desc';
}

const meetingViews: ReadonlySet<View> = new Set(['meetings', 'coverage']);

function legacyCongress(params: URLSearchParams, defaultCongress: number): string {
  const requestedView = params.get('view') || '';
  const scopeValue = params.get('scope') || '';
  const legacyFilename = !params.has('view') && (params.has('source') || params.has('row') || params.has('document_kind') || params.has('document_family') || params.has('retained') || params.has('classification') || params.has('field') || params.has('format') || params.has('review') || scopeValue === 'documents' || scopeValue === 'capture-records' || scopeValue === 'all');
  return legacyFilename && !requestedView ? 'all' : String(defaultCongress);
}

function filenameScope(scopeValue: string, legacyFilename: boolean): FilenameScope {
  if (!isFilenameScope(scopeValue)) return legacyFilename ? 'documents' : '';
  if (legacyFilename && scopeValue === '') return 'documents';
  return scopeValue;
}

export function readNavigation(search: string, defaultCongress: number): Navigation {
  const params = new URLSearchParams(search);
  const congress = params.has('congress') ? params.get('congress') || String(defaultCongress) : legacyCongress(params, defaultCongress);
  const requestedView = params.get('view') || '';
  const measure = params.get('measure') || '';
  const access = params.get('access') || '';
  const committeeType = params.get('committeeType') || '';
  const scopeValue = params.get('scope') || '';
  const retainedValue = params.get('retained') || '';
  const classificationValue = params.get('classification') || '';
  const legacyFilename = !params.has('view') && (params.has('source') || params.has('row') || params.has('document_kind') || params.has('document_family') || params.has('retained') || params.has('classification') || params.has('field') || params.has('format') || params.has('review') || scopeValue === 'documents' || scopeValue === 'capture-records' || scopeValue === 'all');
  const page = Number(params.get('page'));
  const pageIndex = legacyFilename
    ? (Number.isSafeInteger(page) && page >= 1 ? page - 1 : 0)
    : (Number.isSafeInteger(page) && page > 0 ? page : 0);
  const legacyId = params.get('source') || params.get('row') || '';
  const sortValue = params.get('sort') || '';
  const sort = sortValue === 'record' || sortValue === 'date' || sortValue === 'kind' || sortValue === 'congress' ? sortValue : '';
  const directionValue = params.get('direction') || '';
  return {
    view: isView(requestedView) ? requestedView : legacyFilename ? 'materials' : 'meetings',
    congress: congress === 'all' || /^\d+$/.test(congress) ? congress : String(defaultCongress),
    chamber: params.get('chamber') || '',
    q: params.get('q') || '',
    from: params.get('from') || '',
    to: params.get('to') || '',
    type: params.get('type') || '',
    status: readStatus(isView(requestedView) ? requestedView : legacyFilename ? 'materials' : 'meetings', params.get('status') || ''),
    category: isIssueCategory(params.get('category') || '') ? params.get('category') || '' : '',
    severity: isIssueSeverity(params.get('severity') || '') ? params.get('severity') || '' : '',
    materialCategory: isMaterialCategory(params.get('materialCategory') || '') ? params.get('materialCategory') || '' : '',
    participation: isWitnessParticipation(params.get('participation') || '') ? params.get('participation') as WitnessParticipation : '',
    provider: isMaterialProvider(params.get('provider') || '') ? params.get('provider') as MaterialProvider : '',
    history: requestedView === 'gaps' && isIssueHistory(params.get('history') || '') ? params.get('history') as IssueHistory : '',
    access: isAccessState(access) ? access : '',
    page: pageIndex,
    kind: legacyFilename && legacyId ? 'filename_entry' : params.get('kind') || '',
    id: legacyFilename && legacyId ? legacyId : params.get('id') || '',
    committee: params.get('committee') || '',
    month: params.get('month') || '',
    committeeLevel: params.get('committeeLevel') === 'full' ? 'full' : '',
    committeeType: isCommitteeType(committeeType) ? committeeType : '',
    aspect: params.get('aspect') || '',
    evidence: params.get('evidence') || '',
    measure: isCoverageAspect(measure) ? measure : 'transcript',
    grouping: params.get('grouping') === 'month' ? 'month' : 'congress',
    scope: filenameScope(scopeValue, legacyFilename),
    retained: isRetainedFilter(retainedValue) ? retainedValue : '',
    document_family: params.get('document_family') || '',
    document_kind: params.get('document_kind') || '',
    format: params.get('format') || params.get('extension') || '',
    field: params.get('field') || '',
    classification: classificationValue === 'reviewed' ? 'reviewed' : '',
    review: params.get('review') || '',
    catalog: params.get('catalog') || '',
    sort,
    direction: sort ? directionValue === 'desc' ? 'desc' : 'asc' : '',
  };
}

function readStatus(view: View, value: string): string {
  if (view === 'gaps') return isIssueStatus(value) ? value : '';
  if (view === 'meetings' || view === 'coverage') return isMeetingStatus(value) ? value : '';
  return '';
}

export function nextSort(nav: Navigation, column: Navigation['sort']): Pick<Navigation, 'sort' | 'direction'> {
  if (!column || nav.sort !== column) return { sort: column, direction: 'asc' };
  if (nav.direction !== 'desc') return { sort: column, direction: 'desc' };
  return { sort: '', direction: '' };
}

export function viewNavigation(nav: Navigation, view: View): Navigation {
  const meetings = meetingViews.has(nav.view) && meetingViews.has(view);
  return {
    ...nav,
    view,
    page: 0,
    kind: '',
    id: '',
    type: meetings || nav.view === view ? nav.type : '',
    access: meetings ? nav.access : '',
    status: nav.view === view || (meetings && isMeetingStatus(nav.status)) ? nav.status : '',
    category: nav.view === view ? nav.category : '',
    severity: nav.view === view ? nav.severity : '',
    materialCategory: nav.view === view ? nav.materialCategory : '',
    participation: nav.view === view ? nav.participation : '',
    provider: nav.view === view ? nav.provider : '',
    history: nav.view === view ? nav.history : '',
    committee: meetings ? nav.committee : '',
    month: meetings ? nav.month : '',
    aspect: meetings ? nav.aspect : '',
    evidence: meetings ? nav.evidence : '',
    ...(view === 'committees' ? { from: '', to: '' } : {}),
    ...(view === 'materials' ? {} : { scope: '', retained: '', document_family: '', document_kind: '', format: '', field: '', classification: '', review: '', catalog: '', sort: '', direction: '' }),
  };
}

export function drillNavigation(nav: Navigation, patch: ExplorerQuery): Navigation {
  return {
    ...nav,
    view: 'meetings',
    page: 0,
    kind: '',
    id: '',
    congress: patch.congress === undefined ? nav.congress : String(patch.congress),
    committee: patch.committeeId ?? nav.committee,
    month: patch.month ?? nav.month,
    aspect: patch.aspect ?? nav.aspect,
    evidence: patch.evidence ?? nav.evidence,
  };
}
