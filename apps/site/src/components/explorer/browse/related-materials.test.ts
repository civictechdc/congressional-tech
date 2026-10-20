import test from 'node:test';
import assert from 'node:assert/strict';
import { materialCategory, relatedMaterialTitle, sameRecordedTitle, selectRelatedMaterials } from './related-materials.ts';

test('a meeting title that differs only by quotation marks is the same title', () => {
  assert.equal(sameRecordedTitle('"Child Care and the American Workforce"', '“Child Care and the American Workforce”'), true);
  assert.equal(sameRecordedTitle('Benched: The Crisis in American Youth Sports', 'Child Care and the American Workforce'), false);
});

test('a related recording keeps a recorded title and a generic one stays an action', () => {
  assert.equal(relatedMaterialTitle({ type: 'recording', title: 'Chairman Griffith Delivers Opening Statement' }, 'Recording'), 'Chairman Griffith Delivers Opening Statement');
  assert.equal(relatedMaterialTitle({ type: 'recording', title: 'Recording' }, 'Recording'), 'Watch recording');
  assert.equal(relatedMaterialTitle({ type: 'document', title: 'Witness Statement' }, 'Witness Statement', 'statement.pdf'), 'statement.pdf');
});

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


test('reviewed committee prints and supporting documents stay distinct from transcripts', () => {
  for (const legacy of [false, true]) {
    const records = ['transcript','committee_print','supporting'].map(category => ({kind:'material',id:category,
      ...(legacy ? {details:{type:'document',category}} : {type:'document',category})}));
    const selected = selectRelatedMaterials(records,{materialType:'document',category:'Committee print'});
    assert.deepEqual(selected.rows.map(row=>row.id),['committee_print']);
    assert.deepEqual(selected.categories,[{label:'Committee print',count:1},{label:'Supporting',count:1},{label:'Transcript',count:1}]);
  }
});
