import test from 'node:test';
import assert from 'node:assert/strict';
import {groupCommitteeTerms, matches} from './query-utils.js';

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
  assert.deepEqual(groups[0].terms.map(term=>({kind:term.kind,id:term.id})),[{kind:'committee_term',id:'new'},{kind:'committee_term',id:'old'}]);
  const filtered = {...query,committeeType:'other'};
  assert.deepEqual(groupCommitteeTerms(rows.filter(row=>matches(row,filtered)),filtered)[0].terms.map(term=>term.id),['old']);
  assert.equal(groupCommitteeTerms(rows,{...query,congress:119}),rows);
  assert.equal(groupCommitteeTerms(rows,{kind:'meeting',congress:'all'}),rows);
});
