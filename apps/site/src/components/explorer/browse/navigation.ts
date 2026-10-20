import type { ExplorerQuery } from '../reader/types.ts';
import type { CoverageAspect } from './kinds.ts';
import { accessStates, committeeTypes, isAccessState, isCommitteeType, isCoverageAspect, isView, type View } from './kinds.ts';

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
}

const meetingViews: ReadonlySet<View> = new Set(['meetings', 'coverage']);

export function readNavigation(search: string, defaultCongress: number): Navigation {
  const params = new URLSearchParams(search);
  const congress = params.get('congress') || String(defaultCongress);
  const page = Number(params.get('page'));
  const requestedView = params.get('view') || '';
  const measure = params.get('measure') || '';
  const access = params.get('access') || '';
  const committeeType = params.get('committeeType') || '';
  return {
    view: isView(requestedView) ? requestedView : 'meetings',
    congress: congress === 'all' || /^\d+$/.test(congress) ? congress : String(defaultCongress),
    chamber: params.get('chamber') || '',
    q: params.get('q') || '',
    from: params.get('from') || '',
    to: params.get('to') || '',
    type: params.get('type') || '',
    status: params.get('status') || '',
    access: isAccessState(access) ? access : '',
    page: Number.isSafeInteger(page) && page > 0 ? page : 0,
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
