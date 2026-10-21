import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {showPublicationUpdate} from './publication.ts';
import {appendOriginPage, evidenceGraph} from '../../browse/provenance.ts';
import {contentCongressLabel, contentKindNote, filenameIdentity, filenameReadings, recordLabel, savedResponseLabel} from '../../browse/filename-presentation.ts';
import {filenameDate} from '../../browse/filename-rules.ts';

const require = createRequire(new URL('../../../../../package.json', import.meta.url));
const {JSDOM} = require('jsdom');

const html = `<!doctype html><html><body>
  <div data-catalog-update hidden><span></span><a href="?">Open latest</a></div>
  <dialog open><div data-catalog-update hidden><span></span><a href="?">Open latest</a></div></dialog>
</body></html>`;

const original = 'https://committee.test/UploadedFiles/Resolution.pdf';
const final = 'https://committee.test/uploadedfiles/resolution.pdf';
const origin = {file_url: final, pages: [], recovered_urls: [], redirects: [{original, final}]};
const record = {
  source_id: 'stable-final',
  document_id: 'group',
  filename: 'resolution.pdf',
  source_url: final,
  body_key: 'bodies/sha256/hidden-from-summary.gz',
  document_kind: null,
  source_congress: null,
  body_format: ['pdf'],
  format: ['pdf'],
  name_token: ['resolution_by_cmw'],
  date_token: ['01.30.2019'],
  date_token_candidates: ['2019-01-30'],
  source_occurrences: [{source_occurrence_scope: ['capture'], source_receipt_key: ['receipts/archive.jsonl.gz']}],
};

test('new data is reachable inside an open detail panel and follows the selected file', () => {
  const dom = new JSDOM(html, {url: 'https://viewer.test/?source=first&catalog=old'});
  try {
    const {document, location, history} = dom.window;
    showPublicationUpdate({catalogId: 'latest', document, location});
    const notice = document.querySelector('dialog [data-catalog-update]');
    assert.ok(notice);
    assert.equal(notice.hidden, false);
    const link = notice.querySelector('a');
    assert.equal(new URL(link.href).searchParams.get('source'), 'first');
    history.replaceState(null, '', '?source=second&catalog=old&q=hearing');
    link.onfocus();
    assert.equal(new URL(link.href).searchParams.get('source'), 'second');
    assert.equal(new URL(link.href).searchParams.get('catalog'), 'latest');
    assert.equal(new URL(link.href).searchParams.get('q'), 'hearing');
    showPublicationUpdate({message: 'This review snapshot could not be loaded.', document, location});
    assert.match(notice.textContent, /could not be loaded/);
    assert.equal(new URL(link.href).searchParams.has('catalog'), false);
  } finally {
    dom.window.close();
  }
});

test('origin pagination deduplicates exact evidence and preserves competing titles and link labels', () => {
  const first = {urls: ['https://committee.test/hearing'], titles: ['Recorded hearing'], link_urls: [], link_labels: [], relationship: 'Linked from'};
  const page = appendOriginPage(
    {origin: {...origin, pages: [first]}, next: 20},
    {origin: {...origin, pages: [first, {...first, titles: ['Competing hearing title']}]}, next: null},
  );
  assert.equal(page.next, null);
  assert.equal(page.origin.pages.length, 2);
  const graph = evidenceGraph(page.origin);
  assert.equal(graph.references.length, 1);
  assert.equal(graph.references[0].pages.length, 2);

  const root = {urls: ['https://committee.test/hearing'], titles: ['First title'], link_urls: ['https://committee.test/article'], link_labels: ['First label'], relationship: 'Linked through'};
  const chainGraph = evidenceGraph({
    ...origin,
    pages: [
      root,
      {...root, titles: ['Competing title'], link_labels: ['Second label']},
      {urls: ['https://committee.test/article'], titles: [], link_urls: [final], link_labels: [], relationship: 'Linked from'},
    ],
  });
  assert.equal(chainGraph.paths.length, 1);
  assert.equal(chainGraph.references[0].pages.length, 2);
});

test('explorer presentation helpers format filename identity, dates, and content findings', () => {
  assert.equal(filenameIdentity(record), 'resolution.pdf');
  assert.equal(recordLabel(record), 'No category');
  assert.equal(savedResponseLabel({...record, retained: true}), 'Saved');
  assert.match(filenameDate(record.date_token_candidates[0]), /January 30, 2019/);
  assert.deepEqual(filenameReadings(record), []);
  assert.equal(contentKindNote({document_kind: null, content_document_kind: ['committee-resolution']}), 'Saved contents read as Committee resolution');
  assert.equal(contentCongressLabel({content_congress: ['116']}), '116th Congress');
});
