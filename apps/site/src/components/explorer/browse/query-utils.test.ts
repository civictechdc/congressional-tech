import test from 'node:test';
import assert from 'node:assert/strict';
import {compareSearchRows, groupCommitteeTerms, matches, orderSearchRows, selectSearchRows} from './query-utils.ts';
import {presentRecord} from './record-presentation.ts';

test('the default list puts the newest recorded date first', () => {
  const rows = [
    {kind: 'meeting', id: 'blank', title: 'Undated', date: ''},
    {kind: 'meeting', id: 'old', title: 'Old', date: '2020-01-01'},
    {kind: 'meeting', id: 'new', title: 'New', date: '2026-01-01'},
  ];
  assert.deepEqual([...rows].sort(compareSearchRows).map(row => row.id), ['new', 'old', 'blank']);
  const sameDay = [
    {kind: 'meeting', id: 'early', title: 'Zebra', date: '2026-10-01', scheduled_at: '2026-10-01T13:30:00Z'},
    {kind: 'meeting', id: 'late', title: 'Alpha', date: '2026-10-01', scheduled_at: '2026-10-01T14:15:00Z'},
    {kind: 'meeting', id: 'mid', title: 'Middle', date: '2026-10-01', scheduled_at: '2026-10-01T14:00:00Z'},
  ];
  assert.deepEqual([...sameDay].sort(compareSearchRows).map(row => row.id), ['late', 'mid', 'early']);
});

test('column sort orders the full selection and keeps blank values last', () => {
  const rows = [
    {kind: 'meeting', id: 'b', title: 'Beta', date: '2026-01-02', congress: 118, type: 'hearing'},
    {kind: 'meeting', id: 'a', title: 'Alpha', date: '', congress: 119, type: 'markup'},
    {kind: 'meeting', id: 'c', title: 'alpha', date: '2026-03-01', congress: null, type: 'hearing'},
  ];
  assert.deepEqual(orderSearchRows(rows, 'record', 'asc').map(row => row.id), ['a', 'c', 'b']);
  assert.deepEqual(orderSearchRows(rows, 'record', 'desc').map(row => row.id), ['b', 'a', 'c']);
  assert.deepEqual(orderSearchRows(rows, 'date', 'asc').map(row => row.id), ['b', 'c', 'a']);
  assert.deepEqual(orderSearchRows(rows, 'date', 'desc').map(row => row.id), ['c', 'b', 'a']);
  assert.deepEqual(orderSearchRows(rows, 'congress', 'asc').map(row => row.id), ['b', 'a', 'c']);
  assert.deepEqual(orderSearchRows(rows, '', 'asc').map(row => row.id), ['b', 'a', 'c']);
  assert.deepEqual(orderSearchRows([{kind: 'appearance', id: 'w', title: 'Ada', position: 'Director', organization: 'Agency'}], 'kind', 'asc')[0].id, 'w');
  const statements = [
    {kind: 'material', id: 'b', title: 'Witness Statement', document_type: 'Witness Statement', files: [{url: 'https://docs.house.gov/Wstate-ThomsonW.pdf'}]},
    {kind: 'material', id: 'a', title: 'Witness Statement', document_type: 'Witness Statement', files: [{url: 'https://docs.house.gov/Wstate-MooreB.pdf'}]},
  ];
  assert.deepEqual(orderSearchRows(statements, 'record', 'asc').map(row => row.id), ['a', 'b']);
  assert.equal(matches(statements[1], {q: 'MooreB'}), true);
  assert.equal(matches({ kind: 'meeting', id: 'place', title: 'Field hearing', facts: [{ label: 'label', value: 'Collierville, TN' }] }, { q: 'Collierville' }), true);
  assert.equal(matches({ kind: 'meeting', id: 'bill', title: 'Markup', facts: [{ label: 'Related bill', value: 'S 1254' }] }, { q: 'S 1254' }), true);
  assert.equal(matches({ kind: 'meeting', id: 'later-bill', title: 'Full Committee Business Meeting', facts: ['HR 1234', 'HR 1133', 'HR 313', 'HR 1232', 'HR 882'].map(value => ({ label: 'Related bill', value })) }, { q: 'HR 882' }), true);
  assert.equal(matches({ kind: 'appearance', id: 'witness', title: 'Mr. Randy S. Howard', organization: 'Northern California Power Agency', facts: [{ label: 'location', value: 'Roseville, CA' }] }, { q: 'Roseville' }), true);
  assert.equal(matches({ kind: 'appearance', id: 'testified', title: 'Dr. Patricia McLaughlin', participation: 'testified' }, { q: 'testified' }), true);
  assert.equal(matches({ kind: 'material', id: 'amendment', title: 'The Honorable Jay Obernolte', facts: [{ label: 'Regarding', value: 'H.R. 8462' }] }, { q: '8462' }), true);
  assert.equal(matches({ kind: 'material', id: 'sponsor', title: 'Amendment #1 to H.R. 1341', facts: [{ label: 'Sponsor Bioguide ID', value: 'B001281' }] }, { q: 'B001281' }), true);
  assert.equal(matches({ kind: 'committee_term', id: 'admin', title: 'Committee on House Administration', committee_code: 'hsha00' }, { q: 'hsha00' }), true);
  assert.equal(matches({ kind: 'material', id: 'published', title: 'Hearing video', date: '2013-07-17', files: [{ published_at: '2016-02-08' }] }, { q: '2016-02-08' }), true);
  assert.equal(matches({ kind: 'meeting', id: 'markup', title: 'Markup of H.R. 647', facts: [{ label: 'Vote 1', value: 'H.R. 647 was ordered favorably reported by voice vote' }] }, { q: 'voice vote' }), true);
  assert.equal(matches({ kind: 'meeting', id: 'amendment', title: 'Business Meeting', facts: [{ label: 'Amendment 1', value: 'ANS - Conway Contempt Resolution' }] }, { q: 'Conway' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'edition', title: 'Sources disagree about label', facts: [{ label: 'Resolution', value: 'Collectors assigned different internal edition labels. This is not evidence of a disagreement in source content.' }] }, { q: 'edition labels' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'conflict', title: 'Sources disagree', category: 'conflicting', severity: 'affects_interpretation' }, { category: 'conflicting' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'conflict-word', title: 'Sources disagree about label', category: 'conflicting' }, { q: 'conflicting' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'probe', title: 'The probe has no supported live check date.', subject_kind: 'source_record' }, { q: 'source record' }), true);
  assert.equal(matches({ kind: 'material', id: 'moy', title: '3-11-2014 Moy Testimony', document_type: 'Support Document', category: 'statement' }, { q: 'statement' }), true);
  assert.equal(matches({ kind: 'material', id: 'statement', title: 'Opening remarks', category: 'statement' }, { category: 'statement' }), true);
  assert.equal(matches({ kind: 'material', id: 'recording', title: 'Hearing video', type: 'recording' }, { category: 'statement' }), false);
  assert.equal(matches({ kind: 'appearance', id: 'spoke', title: 'Ada', participation: 'testified' }, { participation: 'testified' }), true);
  assert.equal(matches({ kind: 'material', id: 'video', title: 'Hearing video', provider: 'youtube' }, { provider: 'youtube' }), true);
  assert.equal(matches({ kind: 'material', id: 'video', title: 'Hearing video', provider: 'youtube' }, { q: 'c-span' }), false);
  assert.equal(matches({ kind: 'material', id: 'span', title: 'Hearing video', provider: 'www.c-span.org' }, { q: 'c-span' }), true);
  assert.equal(matches({ kind: 'material', id: 'timed', title: 'Recording', scheduled_at: '2019-12-04T15:00:00Z' }, { dateFrom: '2019-12-01', dateTo: '2019-12-31' }), true);
  assert.equal(matches({ kind: 'material', id: 'timed', title: 'Recording', scheduled_at: '2019-12-04T15:00:00Z' }, { dateFrom: '2020-01-01' }), false);
  assert.equal(matches({ kind: 'data_issue', id: 'old', title: 'Earlier disagreement', selection: 'retained_history' }, { history: 'retained' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'now', title: 'Current disagreement' }, { history: 'current' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'old', title: 'Earlier disagreement', selection: 'retained_history' }, { history: 'current' }), false);
  assert.equal(matches({ kind: 'appearance', id: 'named', title: 'Bea', participation: 'listed' }, { participation: 'testified' }), false);
  assert.equal(matches({ kind: 'meeting', id: 'off', title: 'Markup', status: 'canceled' }, { q: 'canceled' }), true);
  const scheduled = selectSearchRows([
    { kind: 'meeting', id: 'later', title: 'Later hearing', status: 'scheduled', date: '2026-11-01' },
    { kind: 'meeting', id: 'earlier', title: 'Earlier hearing', status: 'scheduled', date: '2026-01-01' },
    { kind: 'meeting', id: 'off', title: 'Called off', status: 'canceled', date: '2026-11-01' },
  ], { kind: 'meeting', status: 'upcoming' }, new Date('2026-10-20T16:00:00Z'), { present: presentRecord });
  assert.deepEqual(scheduled.rows.map(row => row.id), ['later']);
  assert.equal(matches({ kind: 'data_issue', id: 'info', title: 'Note', category: 'unverified', severity: 'informational' }, { category: 'conflicting', severity: 'informational' }), false);
  assert.equal(matches({ kind: 'meeting', id: 'sub', title: 'Fostering Women’s Entrepreneurial Success', committee_level: 'subcommittee' }, { q: 'subcommittee' }), true);
  assert.equal(matches({ kind: 'material', id: 'errata', title: 'MARKUP ON PENDING LEGISLATION', explanation: 'The publisher errata says the printed title was an error.' }, { q: 'errata' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'issue', title: 'Sources disagree about title', facts: [{ label: 'field path', value: '/title' }, { label: 'Selected value', value: 'H.R. 3838 Part II' }, { label: 'Alternative 1', value: 'H.R. 3838' }] }, { q: '3838' }), true);
  assert.equal(matches({ kind: 'data_issue', id: 'note', title: 'Unlinked recording', explanation: 'The containing page has no unambiguous saved meeting match.' }, { q: 'unambiguous' }), true);
  const issues = [
    {kind: 'data_issue', id: 'low', title: 'A', category: 'unlinked', severity: 'minor'},
    {kind: 'data_issue', id: 'high', title: 'B', category: 'conflicting', severity: 'affects interpretation'},
  ];
  assert.deepEqual(orderSearchRows(issues, 'kind', 'asc').map(row => row.id), ['high', 'low']);
});

test('committee grouping uses explicit chamber/code, preserves exact term routes, and follows filters', () => {
  const rows = [
    {kind:'committee_term',id:'old',committee_code:'slia00',chamber:'senate',congress:118,title:'Old name',committee_types:['other']},
    {kind:'committee_term',id:'new',committee_code:'slia00',chamber:'senate',congress:119,title:'New name',committee_types:['select']},
    {kind:'committee_term',id:'other-chamber',committee_code:'slia00',chamber:'house',congress:119,title:'New name'},
    {kind:'committee_term',id:'no-code-a',chamber:'senate',congress:118,title:'Same name'},
    {kind:'committee_term',id:'no-code-b',chamber:'senate',congress:119,title:'Same name'},
  ];
  const query = {kind:'committee_term',congress:'all'};
  const groups = groupCommitteeTerms(rows,query);
  assert.equal(groups.length,4);
  assert.equal(groups[0].id,'new');
  assert.equal(groups[0].title,'New name');
  const noted = groupCommitteeTerms([
    {kind:'committee_term',id:'old',committee_code:'sscm00',chamber:'senate',congress:118,title:'Medicare Commission Committee',explanation:'Historical meeting notices are available in the Federal Register.',facts:[{label:'Official website or archive',value:'https://www.indian.senate.gov/'}]},
    {kind:'committee_term',id:'new',committee_code:'sscm00',chamber:'senate',congress:119,title:'Medicare Commission Committee'},
  ], query);
  assert.equal(noted[0].explanation,'Historical meeting notices are available in the Federal Register.');
  assert.equal(noted[0].facts?.[0]?.value,'https://www.indian.senate.gov/');
  assert.equal(matches(noted[0], { q: 'Federal Register' }), true);
  assert.deepEqual(groups[0].terms.map(term=>({kind:term.kind,id:term.id})),[{kind:'committee_term',id:'new'},{kind:'committee_term',id:'old'}]);
  const filtered = {...query,committeeType:'other'};
  assert.deepEqual(groupCommitteeTerms(rows.filter(row=>matches(row,filtered)),filtered)[0].terms.map(term=>term.id),['old']);
  const byOldName = selectSearchRows(rows, { ...query, q: 'Old name' }, new Date('2026-10-20T16:00:00Z'));
  assert.equal(byOldName.rows.length, 1);
  assert.equal(byOldName.rows[0].title, 'New name');
  assert.deepEqual(byOldName.rows[0].terms?.map(term => term.id), ['new', 'old']);
  assert.equal(groupCommitteeTerms(rows,{...query,congress:119}),rows);
  assert.equal(groupCommitteeTerms(rows,{kind:'meeting',congress:'all'}),rows);
});
