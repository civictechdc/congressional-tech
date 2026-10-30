import type { ExplorerQuery } from '../reader/types.ts';
import type { CoverageAspect } from './kinds.ts';
import { accessStates, committeeTypes, isAccessState, isCommitteeType, isCoverageAspect, isIssueCategory, isIssueHistory, isIssueSeverity, isIssueStatus, isMaterialCategory, isMaterialProvider, isMeetingStatus, isView, isWitnessParticipation, materialCategories, materialProviders, type IssueHistory, type MaterialProvider, type View, type WitnessParticipation } from './kinds.ts';

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
  sort: '' | 'record' | 'date' | 'kind' | 'congress';
  direction: '' | 'asc' | 'desc';
}

const meetingViews: ReadonlySet<View> = new Set(['meetings', 'coverage']);

export function readNavigation(search: string, defaultCongress: number): Navigation {
  const params = new URLSearchParams(search);
  const meetingParam = params.get('meeting') || '';
  const congress = params.get('congress') || (meetingParam ? 'all' : String(defaultCongress));
  const requestedView = params.get('view') || '';
  const measure = params.get('measure') || '';
  const access = params.get('access') || '';
  const committeeType = params.get('committeeType') || '';
  const page = Number(params.get('page'));
  const pageIndex = Number.isSafeInteger(page) && page > 0 ? page : 0;
  const sortValue = params.get('sort') || '';
  const sort = sortValue === 'record' || sortValue === 'date' || sortValue === 'kind' || sortValue === 'congress' ? sortValue : '';
  const directionValue = params.get('direction') || '';
  return {
    view: isView(requestedView) ? requestedView : 'meetings',
    congress: congress === 'all' || /^\d+$/.test(congress) ? congress : String(defaultCongress),
    chamber: params.get('chamber') || '',
    q: params.get('q') || meetingParam || '',
    from: params.get('from') || '',
    to: params.get('to') || '',
    type: params.get('type') || '',
    status: readStatus(isView(requestedView) ? requestedView : 'meetings', params.get('status') || ''),
    category: isIssueCategory(params.get('category') || '') ? params.get('category') || '' : '',
    severity: isIssueSeverity(params.get('severity') || '') ? params.get('severity') || '' : '',
    materialCategory: isMaterialCategory(params.get('materialCategory') || '') ? params.get('materialCategory') || '' : '',
    participation: isWitnessParticipation(params.get('participation') || '') ? params.get('participation') as WitnessParticipation : '',
    provider: isMaterialProvider(params.get('provider') || '') ? params.get('provider') as MaterialProvider : '',
    history: requestedView === 'gaps' && isIssueHistory(params.get('history') || '') ? params.get('history') as IssueHistory : '',
    access: isAccessState(access) ? access : '',
    page: pageIndex,
    kind: params.get('kind') || '',
    id: params.get('id') || '',
    committee: params.get('committee') || '',
    month: params.get('month') || '',
    committeeLevel: params.get('committeeLevel') === 'full' ? 'full' : '',
    committeeType: isCommitteeType(committeeType) ? committeeType : '',
    aspect: params.get('aspect') || '',
    evidence: params.get('evidence') || '',
    measure: isCoverageAspect(measure) ? measure : 'transcript',
    grouping: params.get('grouping') === 'month' ? 'month' : 'congress',
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
    ...(view === 'materials' ? {} : { sort: '', direction: '' }),
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
