import {test} from 'node:test';
import assert from 'node:assert/strict';
import {canonicalKind, kindSynonymSets, mergeKindFacets, withKindSynonyms} from './kind-synonyms.ts';

const schema = {files: [{name: 'detail.parquet'}, {name: 'list.parquet', synonyms: {'document_kind[]': [['witness-statement', 'testimony']]}}]};

test('a release lists the kind words it publishes as one kind (ct-isnv)', () => {
  assert.deepEqual(kindSynonymSets(schema), [['witness-statement', 'testimony']]);
  // A release published before synonyms keeps exact kinds.
  assert.deepEqual(kindSynonymSets({files: [{name: 'list.parquet'}]}), []);
  assert.deepEqual(kindSynonymSets(null), []);
  assert.deepEqual(kindSynonymSets({files: [{name: 'list.parquet', synonyms: {'document_kind[]': [['a', 7]]}}]}), []);
});

test('a filter or bookmark for either word selects the whole set', () => {
  const sets = kindSynonymSets(schema);
  assert.deepEqual(withKindSynonyms(['testimony'], sets), ['witness-statement', 'testimony']);
  assert.deepEqual(withKindSynonyms(['witness-statement'], sets), ['witness-statement', 'testimony']);
  assert.deepEqual(withKindSynonyms(['statement', 'testimony'], sets), ['statement', 'witness-statement', 'testimony']);
  assert.deepEqual(withKindSynonyms(['testimony'], []), ['testimony']);
  assert.equal(canonicalKind('testimony', sets), 'witness-statement');
  assert.equal(canonicalKind('statement', sets), 'statement');
});

test('the Document type menu shows one entry per kind with the summed count', () => {
  const facets = [
    {facet: 'document_kind', value: 'testimony', count: 24650},
    {facet: 'document_kind', value: 'witness-statement', count: 39365},
    {facet: 'document_kind', value: 'statement', count: '3979'},
  ];
  assert.deepEqual(mergeKindFacets(facets, kindSynonymSets(schema)), [
    {facet: 'document_kind', value: 'witness-statement', count: 64015},
    {facet: 'document_kind', value: 'statement', count: 3979},
  ]);
  assert.deepEqual(mergeKindFacets(facets, []).map(item => item.value), ['testimony', 'witness-statement', 'statement']);
});
