import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogMatchFiles } from './filename-match.ts';
import { captureNotes, checkedAtNote, contentCongressLabel, contentCongressNote, contentKindNote, documentKindLabel, fileRoleLabel, httpStatusNote, kindBasis, pretty, recordLabel, recordRoleNote, recoveredSourceHost, recoveredSourceUrl, responseCheckNote, retrievedAtNote, savedBodyNote, savedResponseLabel, serverTypeNote, sourceDocumentBasis, sourceDocumentTypeNote, sourcePageLabel } from './filename-presentation.ts';

test('catalog matching keeps a recording file digest even when its URL is not public', () => {
  const files = catalogMatchFiles({
    type: 'recording',
    recording_url: 'https://www.youtube.com/watch?v=abc',
    files: [
      { url: 'https://docs.house.gov/meetings/notice.pdf', saved_copy_sha256: 'ab'.repeat(32) },
      { saved_copy_sha256: 'cd'.repeat(32) },
      { url: 'javascript:bad()' },
    ],
  });
  assert.deepEqual(files, [
    { url: 'https://docs.house.gov/meetings/notice.pdf', saved_copy_sha256: 'ab'.repeat(32) },
    { saved_copy_sha256: 'cd'.repeat(32) },
    { url: 'https://www.youtube.com/watch?v=abc' },
  ]);
});

test('filename labels speak in words', () => {
  assert.equal(pretty('url_path'), 'Url path');
  assert.equal(documentKindLabel({ video_reference: { provider: 'YouTube', id: 'abc' } }), 'Video reference');
  assert.equal(documentKindLabel({ document_kind: ['witness-statement'] }), 'Witness statement');
  assert.equal(documentKindLabel({}), 'Unclassified');
  const hearing = {
    source_url: 'https://www.appropriations.senate.gov/hearings/forest-service',
    source_page_url: ['https://www.appropriations.senate.gov/hearings/forest-service', 'https://api.congress.gov/v3/committee-meeting/117/senate/332414'],
    source_page_title: ['Hearing'],
    source_meeting_type: ['Meeting'],
    format: ['html'],
  };
  assert.equal(sourcePageLabel(hearing), 'Hearing page');
  assert.equal(documentKindLabel(hearing), 'Unclassified');
  assert.equal(recordLabel(hearing), 'Hearing page');
  assert.equal(sourcePageLabel({ ...hearing, source_page_url: ['https://www.appropriations.senate.gov/hearings'] }), '');
  assert.equal(sourcePageLabel({ ...hearing, format: ['pdf'] }), '');
  assert.equal(fileRoleLabel({ filename: 'text_1_00195.vtt', format: ['text/vtt'] }), 'Caption segment');
  assert.equal(fileRoleLabel({ filename: 'HHRG-115-HA00-20180516.xml', format: ['xml'] }), 'Meeting package');
  assert.equal(fileRoleLabel({ filename: 'HHRG-115-HA00-Wstate-Lee-20180516.pdf', format: ['pdf'] }), '');
  assert.equal(fileRoleLabel({ filename: 'mods.xml', format: ['xml'] }), 'Package metadata');
  assert.equal(recordLabel({ document_kind: ['witness-statement'], filename: 'mods.xml' }), 'Witness statement');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['hearing'], filename: '1' }), 'Hearing record');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['hearing'], filename: '1', api_reference: { title: 'Senate hearing 1' } }), 'Hearing record');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['package-summary'], filename: 'summary', api_reference: { title: 'Summary' } }), 'Package summary');
  assert.equal(recordLabel({ api_reference: { title: 'Bill' }, filename: 'hr1' }), 'Source/API reference');
  assert.equal(recordLabel({ record_role: ['document'], source_record_type: ['hearing'], filename: 'notice.pdf' }), 'Unclassified');
  assert.equal(recordLabel({ record_role: ['capture-state'], source_record_type: ['house-cache-marker'], filename: '100052.none' }), 'Cache marker');
  assert.equal(recordLabel({ record_role: ['error-response'], source_record_type: ['error-page'], filename: 'mets.xml' }), 'Error page');
  assert.equal(recordLabel({ record_role: ['capture-state'], source_record_type: ['collector-artifact'], filename: 'documents-acquire.py.before' }), 'Collector artifact');
  assert.equal(recordRoleNote({ record_role: ['error-response'] }), 'Error response');
  assert.equal(recordRoleNote({ record_role: ['capture-state'] }), 'Capture state');
  assert.equal(recordRoleNote({ record_role: ['document'] }), '');
  assert.equal(recordRoleNote({ record_role: ['source-record'] }), '');
  assert.deepEqual(captureNotes({ capture_outcome: ['saved'], state_outcome: ['pending'], http_status: [404], format: ['html'] }), ['Fetch pending']);
  assert.deepEqual(captureNotes({ capture_outcome: ['http_error', 'saved'], state_outcome: ['retained'], http_status: [404] }), []);
  assert.deepEqual(captureNotes({ state_outcome: ['excluded_probe', 'request_failed'] }), ['Excluded probe', 'Request failed']);
  assert.equal(httpStatusNote({ http_status: ['200'], retained: true }), '');
  assert.equal(httpStatusNote({ http_status: ['200'], retained: false }), 'HTTP 200');
  assert.equal(httpStatusNote({ http_status: ['404'] }), 'HTTP 404');
  assert.equal(httpStatusNote({ http_status: ['200', '503'], retained: true }), 'HTTP 200 · 503');
  assert.equal(serverTypeNote({ format: ['html'], media_type: ['application/pdf'] }), 'Server reported application/pdf');
  assert.equal(serverTypeNote({ format: ['pdf'], media_type: ['application/pdf'] }), '');
  assert.equal(serverTypeNote({ format: ['docx'], media_type: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'] }), '');
  assert.equal(serverTypeNote({ format: [], media_type: ['text/html'] }), 'Server reported text/html');
  assert.equal(savedBodyNote({ format: ['html', 'pdf'], body_format: ['html'] }), 'Saved body HTML');
  assert.equal(savedBodyNote({ format: ['pdf'], body_format: ['pdf'] }), '');
  assert.equal(savedBodyNote({ format: ['html', 'pdf'], body_format: ['pdf', 'html'] }), '');
  assert.equal(kindBasis({ document_kind_source: ['filename'] }), '');
  assert.equal(kindBasis({ document_kind_source: ['content'] }), 'Based on the saved contents');
  assert.equal(recoveredSourceUrl({ source_url: 'https://docs.house.gov/a.pdf', recovered_source_url: ['https://www.congress.gov/a.pdf'] }), '');
  assert.equal(recoveredSourceHost({ recovered_source_url: ['https://www.congress.gov/113/meeting/house/102028/documents/HHRG.pdf'] }), 'Recovered from congress.gov');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['html_requires_document_discovery', 'pdf'] }), 'Saved page needs document discovery · Checked body includes PDF');
  assert.equal(responseCheckNote({ format: ['pdf'], response_format: ['pdf'] }), '');
  assert.equal(responseCheckNote({ format: ['pdf'], response_format: ['pdf_missing_eof'] }), 'PDF is missing its end marker');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['challenge_html'] }), 'Saved page is a challenge page');
  assert.equal(responseCheckNote({ format: ['docx'], response_format: ['zip_or_office'] }), '');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['empty_response'] }), 'Empty saved response');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['false'] }), 'Saved · Saved response marked unusable');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['false', 'true'], response_body_complete: ['false', 'true'] }), 'Saved · Usability readings disagree · Completeness readings disagree');
  assert.equal(savedResponseLabel({ retained: true, recovery: { recovery_status: 'recovered' }, response_usable: ['false', 'true'] }), 'Recovered · Usability readings disagree');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['true'] }), 'Saved');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-report'], source_document_type: ['Committee Recorded Vote'] }), 'Committee Recorded Vote');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['witness-statement'], source_document_type: ['WS', 'witness statement'] }), '');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-vote'], source_document_type: ['CV'] }), '');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['publisher'] }), 'Recorded on the source page');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['house_parser_inference', 'publisher'] }), 'Includes an inferred reading');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['senate_parser_fallback'] }), 'Inferred from the source page');
  assert.equal(contentKindNote({ document_kind: ['bill-untyped-numbered'], content_document_kind: ['legislative-text'] }), 'Saved contents read as Legislative text');
  assert.equal(contentKindNote({ document_kind: ['witness-statement'], content_document_kind: ['witness-statement'] }), '');
  assert.equal(checkedAtNote({ state_checked_at: ['2026-10-04T12:44:22.621Z'] }), 'Checked 2026-10-04');
  assert.equal(checkedAtNote({}), '');
  assert.equal(retrievedAtNote({ state_checked_at: ['2026-10-12T18:14:12.251Z'], state_retrieved_at: ['2026-10-12T18:14:11.751Z'] }), '');
  assert.equal(retrievedAtNote({ state_retrieved_at: ['2026-10-01T21:08:46.230Z'] }), 'Retrieved 2026-10-01');
  assert.equal(contentCongressLabel({ content_congress: ['114'] }), '114th Congress');
  assert.equal(contentCongressLabel({ congress: ['114'], content_congress: ['114'] }), '');
  assert.equal(contentCongressNote({ congress: ['113'], content_congress: ['114'] }), 'Saved contents record 114th Congress');
  assert.equal(contentCongressNote({ content_congress: ['114'] }), '');
});
