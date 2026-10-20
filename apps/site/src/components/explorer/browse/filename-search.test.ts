import test from 'node:test';
import assert from 'node:assert/strict';
import { contentHash, filenameReadings, readableValue, sourceCommitteeNote } from './filename-presentation.ts';
import { filenameSearchParams } from './filename-search.ts';
import { readNavigation } from './navigation.ts';
import type { FilenameCatalogInfo } from '../reader/filenames/types.ts';

const info = { catalog_id: 'c'.repeat(32), rows: 3, fields: ['filename', 'source_url'], facets: { congress: ['119'], document_kind: ['statement'], format: ['pdf'] }, review_sha256: 'd'.repeat(64), reviewed_search: true } as FilenameCatalogInfo;

test('filename readings keep the stored package and token labels', () => {
  assert.deepEqual(filenameReadings({ package_family: ['HHRG'], package_family_label: ['Hearings'], document_type: ['SD'], document_token_label: ['Documents in general support of the meeting'] }), [
    { label: 'Package', value: 'Hearings · HHRG' },
    { label: 'Filename token', value: 'Documents in general support of the meeting · SD' },
  ]);
  assert.deepEqual(filenameReadings({ package_family: ['BILLS'], package_family_label: ['Congressional Measures (Bills, Resolutions, and Amendments)'] }), [
    { label: 'Package', value: 'Congressional Measures (Bills, Resolutions, and Amendments)' },
  ]);
  assert.deepEqual(filenameReadings({ package_family: ['HHRG'], document_type: ['SD'] }), []);
  assert.deepEqual(filenameReadings({ amendment_marker_label: ['Amendment considered in committee'], citation_marker_label: ['House report citation'], publication_code_label: ['House hearing'], package_family_label: ['Congressional Hearings including House and Senate Appropriations Hearings'] }), [
    { label: 'Package', value: 'Congressional Hearings including House and Senate Appropriations Hearings' },
    { label: 'Amendment marker', value: 'Amendment considered in committee' },
    { label: 'Citation', value: 'House report citation' },
    { label: 'Publication code', value: 'House hearing' },
  ]);
  assert.deepEqual(filenameReadings({ version_token_label: ['Introduced in Senate'], package_family_label: ['Congressional Measures (Bills, Resolutions, and Amendments)'] }), [
    { label: 'Package', value: 'Congressional Measures (Bills, Resolutions, and Amendments)' },
    { label: 'Version', value: 'Introduced in Senate' },
  ]);
  assert.deepEqual(filenameReadings({ meeting_wording_label: ['Hearing'], draft_label: ['Discussion Draft'], enbloc_marker_label: ['Amendments en bloc'], nomination_wording_label: ['Nomination'], committee_token_label: ['Senate Committee on Energy and Natural Resources'], package_family_label: ['Congressional Hearings including House and Senate Appropriations Hearings'] }), [
    { label: 'Package', value: 'Congressional Hearings including House and Senate Appropriations Hearings' },
    { label: 'Meeting wording', value: 'Hearing' },
    { label: 'Draft', value: 'Discussion Draft' },
    { label: 'En bloc', value: 'Amendments en bloc' },
    { label: 'Nomination', value: 'Nomination' },
    { label: 'Committee', value: 'Senate Committee on Energy and Natural Resources' },
  ]);
  assert.deepEqual(filenameReadings({ subcommittee_token_label: ['National Parks'], committee_token_label: ['Senate Committee on Energy and Natural Resources'] }).map(reading => reading.label), ['Committee', 'Subcommittee']);
  assert.deepEqual(filenameReadings({ scope_token_label: ['Bill as it is being considered by the subcommittee'], degree_token_label: ['Second degree'], document_abbreviation_label: ['Explanatory statement'], document_abbreviation: ['SOM'], collection_token_label: ['Congressional Measures (Bills, Resolutions, and Amendments)'], package_family_label: ['Congressional Measures (Bills, Resolutions, and Amendments)'] }), [
    { label: 'Package', value: 'Congressional Measures (Bills, Resolutions, and Amendments)' },
    { label: 'Stage', value: 'Bill as it is being considered by the subcommittee' },
    { label: 'Amendment degree', value: 'Second degree' },
    { label: 'Abbreviation', value: 'Explanatory statement (SOM)' },
  ]);
  assert.deepEqual(filenameReadings({ qualifier_wording: ['CLEARED', 'FINAL'], document_wording: ['opening statement'], subject_role_wording: ['rankingmember'], relation_wording: ['Statement of Support for'] }), [
    { label: 'Mark', value: 'Cleared · Final' },
    { label: 'Wording', value: 'Opening statement' },
    { label: 'Role', value: 'Ranking member' },
    { label: 'Relation', value: 'Statement of Support for' },
  ]);
  assert.deepEqual(filenameReadings({ revision_marker_label: ['Document update'], revision_number: ['1'], local_code_token_label: ['Measure considered under suspension'] }), [
    { label: 'Revision', value: 'Document update 1' },
    { label: 'Local code', value: 'Measure considered under suspension' },
  ]);
});

test('a source committee code stays beside the recorded name', () => {
  assert.deepEqual(sourceCommitteeNote({ source_committee_name: ['Committee on Energy and Commerce'], source_committee_code: ['hsif00'] }), { text: 'Committee on Energy and Commerce · hsif00', code: 'Committee code from the source record' });
  assert.deepEqual(sourceCommitteeNote({ source_committee_code: ['hsif14'] }), { text: 'hsif14', code: 'Committee code' });
  assert.deepEqual(sourceCommitteeNote({ source_committee_name: ['House Committee hsif00'], source_committee_code: ['hsif00'] }), { text: 'House Committee hsif00', code: '' });
});

test('a saved-copy key yields its content hash', () => {
  assert.equal(contentHash('bodies/sha256/b3/b382546c4ea755db479f9fae93f03928e2c028b4c17035278b1feafb43fa6241.gz'), 'b382546c4ea755db479f9fae93f03928e2c028b4c17035278b1feafb43fa6241');
  assert.equal(contentHash('not-a-digest'), '');
});

test('recorded objects stay readable without a JSON blob', () => {
  assert.equal(readableValue({ source_page_title: ['Observation 0'], source_occurrence_scope: ['anchor'] }), 'source page title: Observation 0\nsource occurrence scope: anchor');
  assert.equal(readableValue('pdf'), 'pdf');
  const many = Object.fromEntries(Array.from({ length: 13 }, (_, index) => [`field_${index + 1}`, `value ${index + 1}`]));
  assert.equal(readableValue(many).split('\n').at(-1), 'field 13: value 13');
});

test('filename search keeps explorer filters and asks for the next one-based page', () => {
  const nav = readNavigation('?view=materials&scope=documents&congress=119&q=hearing&page=2&document_kind=statement&retained=yes&classification=reviewed', 118);
  const params = new URLSearchParams(filenameSearchParams(nav, info));
  assert.equal(params.get('q'), 'hearing');
  assert.equal(params.get('page'), '3');
  assert.equal(params.get('limit'), '25');
  assert.equal(params.get('congress'), '119');
  assert.equal(params.get('document_kind'), 'statement');
  assert.equal(params.get('retained'), 'yes');
  assert.equal(params.get('classification'), 'reviewed');
  assert.equal(params.get('review'), 'd'.repeat(64));
  assert.equal(params.has('scope'), false);
  const capture = readNavigation('?view=materials&scope=capture-records&congress=117', 119);
  assert.equal(new URLSearchParams(filenameSearchParams(capture, info)).has('congress'), false);
  assert.equal(new URLSearchParams(filenameSearchParams(capture, info)).get('scope'), 'capture-records');
  const sorted = readNavigation('?view=materials&scope=all&sort=congress&direction=desc', 119);
  const sortedParams = new URLSearchParams(filenameSearchParams(sorted, info));
  assert.equal(sortedParams.get('sort'), 'congress');
  assert.equal(sortedParams.get('dir'), 'desc');
  assert.equal(sorted.sort, 'congress');
  assert.equal(sorted.direction, 'desc');
  assert.equal(readNavigation('?view=materials&sort=missing&direction=desc', 119).sort, '');
  assert.equal(new URLSearchParams(filenameSearchParams(readNavigation('?view=materials&scope=documents&sort=date&direction=asc', 119), info)).has('sort'), false);
});
