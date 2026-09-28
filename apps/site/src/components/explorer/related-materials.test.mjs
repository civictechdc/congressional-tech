import test from 'node:test';
import assert from 'node:assert/strict';
import { materialCategory, selectRelatedMaterials } from './related-materials.js';

test('native types remain exact; legacy typed records use their normalized category', () => {
  assert.equal(materialCategory({document_type:'Witness Statement', category:'statement'}), 'Witness Statement');
  assert.equal(materialCategory({details:{type:'document', category:'questions_for_record'}}), 'Questions for record');
  assert.equal(materialCategory({details:{type:'document', category:'unknown'}}), 'Document');
  assert.equal(materialCategory({details:{type:'text', category:'unknown'}}), 'Text product');
  const records = [
    {id:'b', kind:'material', title:'Statement B', details:{type:'document',category:'statement'}},
    {id:'a', kind:'material', title:'Statement A', details:{type:'document',category:'statement'}},
    {id:'q', kind:'material', details:{type:'document',category:'questions_for_record'}},
    {id:'r', kind:'material', details:{type:'recording'}},
    {id:'t', kind:'material', details:{type:'text',category:'captions'}},
  ];
  const selected = selectRelatedMaterials(records, {materialType:'document',category:'Statement'});
  assert.deepEqual(selected.rows.map(row => row.id), ['a','b']);
  assert.deepEqual(selected.categories, [{label:'Captions',count:1}, {label:'Questions for record',count:1}, {label:'Statement',count:2}]);
  assert.deepEqual(selectRelatedMaterials(records, {materialType:'recording'}).rows.map(row => row.id), ['r']);
  assert.deepEqual(records.map(row => row.id), ['b','a','q','r','t']);
});
