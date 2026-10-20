import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evidenceGraph, mergeOrigin, sourceContext} from '../../../../../docs/youtube-coverage/research/filename-provenance.mjs';

const url = name => 'https://committee.test/' + name;
const page = (from, to, extra = {}) => ({urls: [url(from)], link_urls: [url(to)], titles: [],
  link_labels: [], relationship: 'Linked through', ...extra});
const origin = pages => ({file_url: url('file'), pages, redirects: [], recovered_urls: []});

test('cycles and convergent paths retain first shortest recorded path without inventing ambiguous links', () => {
  const value = origin([page('root', 'a', {types: ['hearing']}), page('root', 'b'), page('a', 'root'),
    page('a', 'file'), page('b', 'file'), page('possible', 'file', {relationship: 'Possible source page'}),
    page('ambiguous', 'file', {urls: [url('ambiguous'), url('other')], titles: ['Unpaired title']})]);
  const graph = evidenceGraph(value);
  assert.deepEqual(graph.paths.map(({path}) => path.map(edge => edge.to)), [[url('a'), url('file')]]);
  assert.equal(graph.references.find(item => item.url === url('ambiguous')).pages[0].titles[0], 'Unpaired title');
  assert.equal(graph.metrics.pathCopies, 0);
});

test('duplicate pages collapse while competing titles and exact-protocol evidence remain', () => {
  const first = page('root', 'file', {titles: ['First']});
  const added = origin([first, {...first, titles: ['Competing']}]);
  const merged = mergeOrigin(origin([first]), added);
  assert.equal(merged.pages.length, 2);
  const graph = evidenceGraph(merged);
  assert.equal(graph.paths.length, 1);
  assert.equal(graph.references[0].pages.length, 2);
  const insecure = {...first, link_urls: ['http://committee.test/file']};
  assert.equal(evidenceGraph(origin([insecure])).paths.length, 0);
});

test('redirect assembly is keyed and linked ancestors never become redirects', () => {
  const redirect = {source_association_basis: ['publisher_redirect'], source_associated_url: [url('original')]};
  const ancestor = {...redirect, source_association_basis: ['publisher_redirect', 'linked_page'], source_associated_url: [url('ancestor')]};
  const context = sourceContext({source_url: url('file'), source_occurrences: [redirect, redirect, ancestor],
    recovered_source_url: [url('candidate'), 'javascript:bad']});
  assert.deepEqual(context.redirects, [{original: url('original'), final: url('file')}]);
  assert.deepEqual(context.recovered_urls, [url('candidate')]);
});

test('large chain has linear graph work and no partial path copies', () => {
  const count = 2000;
  const pages = Array.from({length: count}, (_, i) => page('node-' + i, i + 1 === count ? 'file' : 'node-' + (i + 1)));
  const graph = evidenceGraph(origin(pages));
  assert.equal(graph.paths[0].path.length, count);
  assert.equal(graph.metrics.queueVisits, count + 1);
  assert.equal(graph.metrics.edgeVisits, count * 2);
  assert.equal(graph.metrics.pathEdges, count);
  assert.equal(graph.metrics.pathCopies, 0);
  // The former forward BFS copied 0+1+...+(N-1) existing path entries.
  assert.equal(graph.metrics.pathPageLinks, count);
  assert.equal(graph.metrics.uncoveredReferences, 0);
  assert.equal(count * (count - 1) / 2, 1999000);
  assert.deepEqual(evidenceGraph(mergeOrigin(origin(pages), origin(pages))).metrics, graph.metrics);
});
