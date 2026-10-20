import test from 'node:test';
import assert from 'node:assert/strict';
import { filenameSearchParams } from './filename-search.ts';
import { readNavigation } from './navigation.ts';
import type { FilenameCatalogInfo } from '../reader/filenames/types.ts';

const info = { catalog_id: 'c'.repeat(32), rows: 3, fields: ['filename', 'source_url'], facets: { congress: ['119'], document_kind: ['statement'], format: ['pdf'] }, review_sha256: 'd'.repeat(64), reviewed_search: true } as FilenameCatalogInfo;

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
});
