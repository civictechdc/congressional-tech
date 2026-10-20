import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogMatchFiles } from './filename-match.ts';
import { captureNotes, checkedAtNote, contentCongressLabel, contentCongressNote, contentKindNote, documentKindLabel, documentKindName, familyName, fileRoleLabel, formatLabel, httpStatusNote, kindBasis, listedFamilyNames, listedKindLines, plainFormat, pretty, recordLabel, recordRoleNote, recoveredSourceHost, recoveredSourceUrl, repeatsShownRecord, responseCheckNote, retrievedAtNote, savedBodyNote, savedResponseLabel, serverTypeNote, sourceDocumentBasis, sourceDocumentTypeNote, sourcePageLabel } from './filename-presentation.ts';

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
  assert.equal(documentKindLabel({ video_reference: { provider: 'YouTube', id: 'abc' } }), 'Video link');
  assert.equal(documentKindLabel({ document_kind: ['witness-statement'] }), 'Witness statement');
  assert.equal(familyName('print'), 'Committee print');
  assert.equal(familyName('chair-mark'), 'Chair’s mark');
  assert.equal(familyName('op-ed'), 'Op-ed');
  assert.equal(familyName('letter'), 'Letter');
  assert.equal(documentKindName('bill-untyped-numbered'), 'Numbered file, bill type not recorded');
  assert.equal(documentKindName('bill-numbered-described'), 'Numbered bill with a description in the name');
  assert.equal(documentKindName('witness-support'), 'Supporting file for a witness');
  assert.equal(documentKindName('chair-mark'), 'Chair’s mark');
  assert.equal(documentKindLabel({ document_kind: ['bill-numbered', 'witness-statement'] }), 'Bill or resolution with a number · Witness statement');
  assert.equal(documentKindLabel({ document_kind: ['committee-amendment', 'committee-amendment-described'] }), 'Amendment named by its subject');
  assert.equal(formatLabel('application/pdf'), 'PDF');
  assert.equal(formatLabel('video/mp4'), 'MP4 video');
  assert.equal(formatLabel('text/vtt'), 'Captions');
  assert.equal(formatLabel('mp3'), 'MP3 audio');
  assert.equal(plainFormat('pdf'), 'a PDF');
  assert.equal(plainFormat('mp3'), 'an MP3 audio file');
  assert.equal(plainFormat('text/vtt'), 'a caption file');
  assert.equal(documentKindLabel({}), 'No category');
  const hearing = {
    source_url: 'https://www.appropriations.senate.gov/hearings/forest-service',
    source_page_url: ['https://www.appropriations.senate.gov/hearings/forest-service', 'https://api.congress.gov/v3/committee-meeting/117/senate/332414'],
    source_page_title: ['Hearing'],
    source_meeting_type: ['Meeting'],
    format: ['html'],
  };
  assert.equal(sourcePageLabel(hearing), 'Hearing page');
  assert.equal(documentKindLabel(hearing), 'No category');
  assert.equal(recordLabel(hearing), 'Hearing page');
  assert.equal(sourcePageLabel({ ...hearing, source_page_url: ['https://www.appropriations.senate.gov/hearings'] }), '');
  assert.equal(sourcePageLabel({ ...hearing, format: ['pdf'] }), '');
  assert.equal(fileRoleLabel({ filename: 'text_1_00195.vtt', format: ['text/vtt'] }), 'Caption file');
  assert.equal(fileRoleLabel({ filename: 'HHRG-115-HA00-20180516.xml', format: ['xml'] }), 'Meeting file');
  assert.equal(fileRoleLabel({ filename: 'HHRG-115-HA00-Wstate-Lee-20180516.pdf', format: ['pdf'] }), '');
  assert.equal(fileRoleLabel({ filename: 'mods.xml', format: ['xml'] }), 'Notes kept with the file');
  assert.equal(recordLabel({ document_kind: ['witness-statement'], filename: 'mods.xml' }), 'Witness statement');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['hearing'], filename: '1' }), 'Hearing record');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['hearing'], filename: '1', api_reference: { title: 'Senate hearing 1' } }), 'Hearing record');
  assert.equal(recordLabel({ record_role: ['source-record'], source_record_type: ['package-summary'], filename: 'summary', api_reference: { title: 'Summary' } }), 'File summary');
  assert.equal(recordLabel({ api_reference: { title: 'Bill' }, filename: 'hr1' }), 'Official record link');
  assert.equal(recordLabel({ record_role: ['document'], source_record_type: ['hearing'], filename: 'notice.pdf' }), 'No category');
  assert.equal(recordLabel({ record_role: ['capture-state'], source_record_type: ['house-cache-marker'], filename: '100052.none' }), 'Note that the page was checked');
  assert.equal(recordLabel({ record_role: ['error-response'], source_record_type: ['error-page'], filename: 'mets.xml' }), 'Error page');
  assert.equal(recordLabel({ record_role: ['capture-state'], source_record_type: ['collector-artifact'], filename: 'documents-acquire.py.before' }), 'File from the collection tools');
  assert.equal(recordRoleNote({ record_role: ['error-response'] }), 'Error page');
  assert.equal(recordRoleNote({ record_role: ['capture-state'] }), 'Note about the capture');
  assert.equal(recordRoleNote({ record_role: ['document'] }), '');
  assert.equal(recordRoleNote({ record_role: ['source-record'] }), '');
  assert.deepEqual(listedKindLines({ document_kind: ['committee-amendment'], record_role: ['error-response'] }), ['Error page', 'Committee amendment']);
  assert.deepEqual(listedKindLines({ document_kind: ['committee-amendment', 'committee-amendment-described'], record_role: ['error-response'] }), ['Error page', 'Amendment named by its subject']);
  assert.deepEqual(listedFamilyNames(['committee-amendment-described'], ['Committee amendment']), []);
  assert.deepEqual(listedFamilyNames(['legislation'], ['Bill or resolution with a number']), []);
  assert.deepEqual(listedFamilyNames(['correspondence'], ['Document']), ['Correspondence']);
  assert.deepEqual(listedFamilyNames(['correspondence'], ['Error page']), ['Correspondence']);
  assert.deepEqual(captureNotes({ capture_outcome: ['saved'], state_outcome: ['pending'], http_status: [404], format: ['html'] }), ['Still waiting to save a copy']);
  assert.deepEqual(captureNotes({ capture_outcome: ['http_error', 'saved'], state_outcome: ['retained'], http_status: [404] }), []);
  assert.deepEqual(captureNotes({ state_outcome: ['excluded_probe', 'request_failed'] }), ['Not downloaded; it was only a check', 'The request failed']);
  assert.equal(httpStatusNote({ http_status: ['200'], retained: true }), '');
  assert.equal(httpStatusNote({ http_status: ['200'], retained: false }), 'The website answered');
  assert.equal(httpStatusNote({ http_status: ['404'] }), 'The website said this page was not found');
  assert.equal(httpStatusNote({ http_status: ['200', '503'], retained: true }), 'The website reported an error');
  assert.equal(serverTypeNote({ format: ['html'], media_type: ['application/pdf'] }), 'The website called this a PDF');
  assert.equal(serverTypeNote({ format: ['pdf'], media_type: ['application/pdf'] }), '');
  assert.equal(serverTypeNote({ format: ['docx'], media_type: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'] }), '');
  assert.equal(serverTypeNote({ format: [], media_type: ['text/html'] }), 'The website called this a web page');
  assert.equal(savedBodyNote({ format: ['html', 'pdf'], body_format: ['html'] }), 'The saved copy is a web page');
  assert.equal(savedBodyNote({ format: ['pdf'], body_format: ['pdf'] }), '');
  assert.equal(savedBodyNote({ format: ['html', 'pdf'], body_format: ['pdf', 'html'] }), '');
  assert.equal(kindBasis({ document_kind_source: ['filename'] }), '');
  assert.equal(kindBasis({ document_kind_source: ['content'] }), 'Based on the saved contents');
  assert.equal(recoveredSourceUrl({ source_url: 'https://docs.house.gov/a.pdf', recovered_source_url: ['https://www.congress.gov/a.pdf'] }), '');
  assert.equal(recoveredSourceHost({ recovered_source_url: ['https://www.congress.gov/113/meeting/house/102028/documents/HHRG.pdf'] }), 'Recovered from congress.gov');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['html_requires_document_discovery', 'pdf'] }), 'This saved page still needs its documents found · The saved copy includes a PDF');
  assert.equal(responseCheckNote({ format: ['pdf'], response_format: ['pdf'] }), '');
  assert.equal(responseCheckNote({ format: ['pdf'], response_format: ['pdf_missing_eof'] }), 'The PDF is missing its ending');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['challenge_html'] }), 'The saved page is a security check, not the document');
  assert.equal(responseCheckNote({ format: ['docx'], response_format: ['zip_or_office'] }), '');
  assert.equal(responseCheckNote({ format: ['html'], response_format: ['empty_response'] }), 'The saved copy is empty');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['false'] }), 'Saved · Saved response marked unusable');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['false', 'true'], response_body_complete: ['false', 'true'] }), 'Saved · Usability readings disagree · Completeness readings disagree');
  assert.equal(savedResponseLabel({ retained: true, recovery: { recovery_status: 'recovered' }, response_usable: ['false', 'true'] }), 'Recovered · Usability readings disagree');
  assert.equal(savedResponseLabel({ retained: false, recovery: { recovery_status: 'recovered', kind: 'pdf' }, format: ['html'] }), 'Recovered as a PDF');
  assert.equal(savedResponseLabel({ retained: true, response_usable: ['true'] }), 'Saved');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-report'], source_document_type: ['Committee Recorded Vote'] }), 'Committee Recorded Vote');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-transcript'], source_document_type: ['Hearing: Transcript'] }), '');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-report'], source_document_type: ['Hearing: Cover Page'] }), 'Cover page');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['witness-statement'], source_document_type: ['WS', 'witness statement'] }), '');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['committee-vote'], source_document_type: ['CV'] }), '');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['bill-numbered'], source_document_type: ['Other'] }), '');
  assert.equal(sourceDocumentTypeNote({ document_kind: ['bill-numbered'], source_document_type: ['Generic Document'] }), '');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['publisher'] }), 'Recorded on the source page');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['house_parser_inference', 'publisher'] }), 'Includes a reading worked out from the page');
  assert.equal(sourceDocumentBasis({ source_document_type_basis: ['senate_parser_fallback'] }), 'Worked out from the source page');
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
  assert.equal(repeatsShownRecord('Document kind', 'Witness biography', { documentKind: 'Witness biography' }), true);
  assert.equal(repeatsShownRecord('Document kind', 'Error page · Witness biography', { documentKind: 'Witness biography' }), false);
});
