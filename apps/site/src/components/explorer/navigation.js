const meetingViews = new Set(['meetings', 'coverage']);
const views = new Set(['meetings', 'committees', 'materials', 'witnesses', 'coverage', 'gaps']);
const measures = new Set(['recording', 'transcript', 'documents', 'witnesses', 'captions']);

/** @returns {import('./Explorer').Navigation} */
export function readNavigation(search, defaultCongress) {
  const params = new URLSearchParams(search);
  const congress = params.get('congress') || String(defaultCongress);
  const page = Number(params.get('page'));
  return {
    view: views.has(params.get('view')) ? params.get('view') : 'meetings',
    congress: congress === 'all' || /^\d+$/.test(congress) ? congress : String(defaultCongress),
    chamber: params.get('chamber') || '', q: params.get('q') || '',
    from: params.get('from') || '', to: params.get('to') || '',
    type: params.get('type') || '', status: params.get('status') || '',
    page: Number.isSafeInteger(page) && page > 0 ? page : 0,
    kind: params.get('kind') || '', id: params.get('id') || '',
    committee: params.get('committee') || '', month: params.get('month') || '',
    aspect: params.get('aspect') || '', evidence: params.get('evidence') || '',
    measure: measures.has(params.get('measure')) ? params.get('measure') : 'transcript',
    grouping: params.get('grouping') === 'month' ? 'month' : 'congress',
  };
}

/** Only carry filters between workspaces where they have the same meaning.
 * @param {import('./Explorer').Navigation} nav
 * @param {import('./Explorer').Navigation['view']} view
 * @returns {import('./Explorer').Navigation}
 */
export function viewNavigation(nav, view) {
  const meetings = meetingViews.has(nav.view) && meetingViews.has(view);
  return { ...nav, view, page: 0, kind: '', id: '',
    type: meetings || nav.view === view ? nav.type : '',
    status: nav.view === view ? nav.status : '',
    committee: meetings ? nav.committee : '', month: meetings ? nav.month : '',
    aspect: meetings ? nav.aspect : '', evidence: meetings ? nav.evidence : '',
    ...(view === 'committees' ? { from: '', to: '' } : {}),
  };
}

/** Chart counts and their destinations must use the same population.
 * @param {import('./Explorer').Navigation} nav
 * @param {import('./data-source').ExplorerQuery} patch
 * @returns {import('./Explorer').Navigation}
 */
export function drillNavigation(nav, patch) {
  return { ...nav, view: 'meetings', page: 0, kind: '', id: '',
    congress: patch.congress === undefined ? nav.congress : String(patch.congress),
    committee: patch.committeeId ?? nav.committee, month: patch.month ?? nav.month,
    aspect: patch.aspect ?? nav.aspect, evidence: patch.evidence ?? nav.evidence,
  };
}
