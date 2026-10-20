import type { ExplorerQuery } from '../reader/types.ts';
import type { CoverageAspect } from './kinds.ts';
import { accessStates, committeeTypes, isAccessState, isCommitteeType, isCoverageAspect, isFilenameScope, isRetainedFilter, isView, type FilenameScope, type RetainedFilter, type View } from './kinds.ts';

export { accessStates, committeeTypes };
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
  return {
    view: isView(requestedView) ? requestedView : legacyFilename ? 'materials' : 'meetings',
    congress: congress === 'all' || /^\d+$/.test(congress) ? congress : String(defaultCongress),
    chamber: params.get('chamber') || '',
    q: params.get('q') || '',
    from: params.get('from') || '',
    to: params.get('to') || '',
    type: params.get('type') || '',
    status: params.get('status') || '',
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
  };
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
    status: nav.view === view ? nav.status : '',
    committee: meetings ? nav.committee : '',
    month: meetings ? nav.month : '',
    aspect: meetings ? nav.aspect : '',
    evidence: meetings ? nav.evidence : '',
    ...(view === 'committees' ? { from: '', to: '' } : {}),
    ...(view === 'materials' ? {} : { scope: '', retained: '', document_family: '', document_kind: '', format: '', field: '', classification: '', review: '', catalog: '' }),
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
