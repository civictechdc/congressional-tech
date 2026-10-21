import test from 'node:test';
import assert from 'node:assert/strict';
import { categoryNote, collapseRepeatedFacts, committeeHierarchyNote, committeeKindNote, committeeLevelNote, committeeSourceNote, committeeTypeLabel, earlierCommitteeNames, coverageDrillNote, dateFilterReason, disagreementSummary, distinctRecordedFacts, recordedTitleLines, recordedTitlePreview, documentSourceInContext, documentSourceLabel, listedDocumentType, listedSourcePile, evidenceLine, listedEvidence, listedWitnessCount, factLabel, detectedNote, fileLinkName, filePartNote, extraIssueAlternatives, issueNotes, landingPageNote, linkedMeetingIds, listedSourceStatus, listedWhen, listTitle, meetingStatusNote, presentRecord, providerLabel, publishedNote, recordedAction, recordedAddressNames, recordedAmendments, recordedFileName, recordedFileNames, recordedFormatNote, recordedMeasures, recordedPlace, recordedVotes, recordedWhen, recordedWitnesses, scheduleNote, separateWitnesses, witnessNameList, recordingEmbedUrl, recordingIdentity, recordingVisible, notableRoles, omitRepeatedChamber, omitRepeatedCongress, omitRepeatedWhen, participationNote, plainLegislativeNote, plainRecordedNote, relatedMeta, relatedParts, savedCopyHref, sourceCountNote, sourceFacts, sourceLinks, sourceTypeNote, subjectAbsentNote, subjectKindLabel, witnessNotes } from './record-presentation.ts';
import { matches } from './query-utils.ts';

const now = new Date('2026-09-27T15:00:00Z');
const meeting = {kind: 'meeting', status: 'scheduled', date: '2026-09-27', evidence_states: {recording: 'reported', captions: 'inferred', documents: 'reported'}};
const recording = {kind: 'material', type: 'recording', recording_url: 'https://example.org/player', meeting_status: 'scheduled', files: [{url: 'https://example.org/player'}]};

test('a source observation shows its identifier and place without the payload blob', () => {
  const source = {
    provider: 'congress.gov',
    retrieved_at: '2026-10-11T02:53:52.043379Z',
    retained_sha256: 'abc123',
    identifier: '{"scheme":"congress.gov:record","value":"congress.gov|119|house|119575","scope":null}',
    payload: {
      eventId: '119575', meetingStatus: 'Scheduled', type: 'Hearing',
      location: { address: '{"building_name":"Orgill Innovation Center","street-address":"4027 Bailey Station Rd","city":"Collierville","state":"TN","postal_code":"38017"}' },
      committees: [{ name: 'House Ways and Means', systemCode: 'hswm00' }],
      witnesses: [{ name: 'Boyden Moore', position: 'President & CEO', organization: 'Orgill' }],
      witnessDocuments: [{ documentType: 'Witness Statement', url: 'https://docs.example/statement.pdf' }],
      videos: [{ name: 'Hearing video', url: 'https://youtube.example/watch?v=abc' }, { name: 'No address' }],
      relatedItems: { bills: [{ type: 'HR', number: '1', congress: 119 }] },
      hearingTranscript: [{ jacketNumber: 73739, url: 'https://api.congress.gov/v3/hearing/112/house/73739?format=json' }],
      continuations: [{ continuationDate: '2023-04-27T16:15:00Z' }, { continuationDate: '2023-04-28T13:15:00Z' }],
    },
  };
  const facts = sourceFacts(source);
  assert.equal(facts.find(([label]) => label === 'Retained SHA-256'), undefined);
  assert.equal(facts.find(([label]) => label === 'Input snapshot'), undefined);
  assert.deepEqual(facts.filter(([label]) => ['Source', 'Fetched', 'Record number', 'Place', 'Status at the source', 'Source witnesses', 'Related items'].includes(label)), [
    ['Source', 'congress.gov'],
    ['Fetched', '2026-10-11 02:53:52 UTC'],
    ['Record number', '119th Congress, House, event 119575'],
    ['Place', 'Orgill Innovation Center, 4027 Bailey Station Rd, Collierville, TN, 38017'],
    ['Status at the source', 'Scheduled'],
    ['Source witnesses', 'Boyden Moore · President & CEO · Orgill'],
    ['Related items', 'bills · HR 1 · 119th Congress'],
  ]);
  assert.equal(facts.find(([label]) => label === 'Hearing transcript')?.[1], 'Transcript number 73739');
  assert.equal(facts.find(([label]) => label === 'Additional sitting')?.[1], '2023-04-27T16:15:00Z\n2023-04-28T13:15:00Z');
  const many = sourceFacts({ payload: { relatedItems: { bills: Array.from({ length: 13 }, (_, index) => ({ type: 'HR', number: String(index + 1), congress: 119 })) } } });
  assert.equal(many.find(([label]) => label === 'Related items')?.[1].split('\n').at(-1), 'bills · HR 13 · 119th Congress');
  const parts = sourceFacts({ payload: { relatedItems: { nominations: [{ congress: 117, number: 78, part: '20' }, { congress: 117, number: 78, part: '00' }] } } });
  assert.equal(parts.find(([label]) => label === 'Related items')?.[1], 'nominations · 78 part 20 · 117th Congress\nnominations · 78 · 117th Congress');
  const described = sourceFacts({ payload: { meetingDocuments: [
    { documentType: 'Generic Document', description: 'Janet Garvin McCabe, of Indiana, to be Deputy Administrator, vice Andrew Wheeler, resigned.' },
    { documentType: 'Support Document', name: 'Printed Hearing Record', url: 'https://www.congress.gov/112/meeting/house/100094/documents/CHRG-112hhrg73739.pdf' },
  ] } });
  assert.equal(described.find(([label]) => label === 'Recorded document')?.[1], 'Generic Document: Janet Garvin McCabe, of Indiana, to be Deputy Administrator, vice Andrew Wheeler, resigned.');
  assert.deepEqual(sourceLinks(source).links, [
    { group: 'Witness document', label: 'Witness Statement · statement.pdf', href: 'https://docs.example/statement.pdf' },
    { group: 'Video', label: 'Hearing video', href: 'https://youtube.example/watch?v=abc' },
  ]);
  const shared = sourceLinks({ payload: { videos: [
    { name: 'Field hearing', url: 'https://www.youtube.com/watch?v=aaa111' },
    { name: 'Field hearing', url: 'https://www.youtube.com/watch?v=bbb222' },
  ] } });
  assert.deepEqual(shared.links.map(link => link.label), ['Field hearing · aaa111', 'Field hearing · bbb222']);
  const eventVideo = sourceLinks({ url: 'https://api.congress.gov/v3/committee-meeting/119/house/119583', payload: { videos: [
    { name: 'Field hearing', url: 'https://www.congress.gov/event/119th-Congress/house-event/119583' },
    { name: 'Field hearing', url: 'https://www.youtube.com/watch?v=SLCyBiAinWY' },
  ] } });
  assert.deepEqual(eventVideo.links.map(link => [link.group, link.label]), [['Video', 'Field hearing']]);
  assert.equal(sourceLinks({ payload: { videos: [{ name: 'Hearing page', url: 'https://www.congress.gov/event/119th-congress/house-event/119583' }] } }).links[0].group, 'Event page');
  assert.equal(sourceLinks({ payload: { meetingDocuments: Array.from({ length: 25 }, (_, index) => ({ name: `Bill ${index + 1}`, url: `https://docs.example/bill-${index + 1}.pdf` })) } }).links.length, 25);
  assert.deepEqual(sourceLinks({ payload: { documents: [['bill or amendment', 'HR 5040, as amended', 'mailto:https://www.congress.gov/116/bills/hr5040/BILLS-116hr5040ih.pdf', ['BILLS-116hr5040ih.pdf']]] } }).links, [
    { group: 'Bill or amendment', href: 'mailto:https://www.congress.gov/116/bills/hr5040/BILLS-116hr5040ih.pdf', label: 'HR 5040, as amended · BILLS-116hr5040ih.pdf · Not a web link. The saved address has extra “mailto:” text in front of https://www.congress.gov/116/bills/hr5040/BILLS-116hr5040ih.pdf' },
  ]);
  const youtube = sourceFacts({ provider: 'youtube', payload: { title: 'Rules Committee Hearing', description: 'Rules Committee Hearing for Feb. 28, 2017.', publishedAt: '2017-02-28T23:05:59Z', videoId: 'DM7o2FYeT84', caption: false, duration: 4697 } });
  assert.equal(youtube.find(([label]) => label === 'Recorded title'), undefined);
  assert.equal(youtube.find(([label]) => label === 'YouTube video')?.[1], 'DM7o2FYeT84');
  assert.equal(youtube.find(([label]) => label === 'Duration')?.[1], '1:18:17');
  assert.equal(youtube.find(([label]) => label === 'Captions')?.[1], 'Not recorded');
  assert.equal(youtube.find(([label]) => label === 'Description')?.[1], 'Rules Committee Hearing for Feb. 28, 2017.');
  assert.equal(youtube.find(([label]) => label === 'Published')?.[1], '2017-02-28 23:05:59 UTC');
  assert.equal(sourceFacts({ payload: { details_checked_at: '2026-10-04T03:19:09.216500+00:00' } }).find(([label]) => label === 'Checked')?.[1], '2026-10-04 03:19:09 UTC');
  assert.equal(sourceFacts({ payload: { details_checked_at: '2026-10-04T03:19:09-04:00' } }).find(([label]) => label === 'Checked')?.[1], '2026-10-04 07:19:09 UTC');
  assert.equal(sourceFacts({ payload: { checked: '2026-09-27', details_checked_at: '2026-10-04T03:19:09.216500+00:00' } }).find(([label]) => label === 'Checked')?.[1], '2026-09-27');
  assert.equal(sourceFacts({ payload: { channelTitle: 'House Judiciary GOP', channelId: 'UCdvbanLNRlC0Af1QWeJ9foA' } }).find(([label]) => label === 'Channel')?.[1], 'House Judiciary GOP');
  assert.equal(sourceFacts({ payload: { preferred_citation: 'S. Hrg. 119-199', record_type: 'errata', last_modified: '2025-03-07T16:44:20Z' } }).find(([label]) => label === 'Citation')?.[1], 'S. Hrg. 119-199');
  assert.equal(sourceFacts({ payload: { preferred_citation: 'S. Hrg. 119-199', record_type: 'errata', last_modified: '2025-03-07T16:44:20Z' } }).find(([label]) => label === 'Last changed')?.[1], '2025-03-07 16:44:20 UTC');
  assert.equal(sourceFacts({ payload: { record_type: 'errata' } }).find(([label]) => label === 'Record type')?.[1], 'errata');
  assert.equal(sourceFacts({ payload: { record_type: 'hearing' } }).find(([label]) => label === 'Record type'), undefined);
  assert.equal(sourceFacts({ payload: { video_minutes: '316', channels: '@EdWorkforceCmte @EdWorkforceDemocrats', note: 'Both channels posted the hearing that day.' } }).find(([label]) => label === 'Video length')?.[1], '5 hr 16 min');
  assert.deepEqual(sourceLinks({ payload: { video_ids: 'bOsa4DtHM3E https://www.senate.gov/isvp/?comm=finance&filename=finance101515', channelId: 'UCdvbanLNRlC0Af1QWeJ9foA', channelTitle: 'House Judiciary GOP' } }).links.map(link => [link.group, link.href, link.label]), [
    ['Matched video', 'https://www.youtube.com/watch?v=bOsa4DtHM3E', 'bOsa4DtHM3E'],
    ['Matched video', 'https://www.senate.gov/isvp/?comm=finance&filename=finance101515', 'finance101515'],
    ['Channel', 'https://www.youtube.com/channel/UCdvbanLNRlC0Af1QWeJ9foA', 'House Judiciary GOP'],
  ]);
  const printed = sourceFacts({ provider: 'govinfo', payload: { package_id: 'CHRG-108jhrg89733', title: 'WILL RELIGION FLOURISH', committee_name: 'Congressional-Executive Commission on China', subcommittees: 'Subcommittee on Trade', held_date: '2003-07-24', serial: 'S. Hrg. 108-1', witness_count: '4', congress: '108', chamber: 'joint', html_url: 'https://www.govinfo.gov/content/pkg/CHRG-108jhrg89733/html/CHRG-108jhrg89733.htm', pdf_url: 'https://www.govinfo.gov/content/pkg/CHRG-108jhrg89733/pdf/CHRG-108jhrg89733.pdf' } });
  assert.equal(printed.find(([label]) => label === 'GovInfo number')?.[1], 'CHRG-108jhrg89733');
  assert.equal(printed.find(([label]) => label === 'Witnesses listed')?.[1], '4');
  assert.equal(printed.find(([label]) => label === 'Subcommittee')?.[1], 'Subcommittee on Trade');
  assert.equal(printed.find(([label]) => label === 'Congress')?.[1], '108th Congress');
  assert.deepEqual(sourceLinks({ payload: { html_url: 'https://www.govinfo.gov/content/pkg/CHRG-108jhrg89733/html/CHRG-108jhrg89733.htm', pdf_url: 'https://www.govinfo.gov/content/pkg/CHRG-108jhrg89733/pdf/CHRG-108jhrg89733.pdf', documents: [['witness statement', 'Pai Testimony', 'https://www.appropriations.senate.gov/download/101719_-pai-testimony-']], amendments: [{ bill: 'H.R. 369', number: '1', description: 'Amendment to H.R. 369', url: 'https://docs.house.gov/BILLS-115-HR369-Amdt-1.pdf' }], witnesses: [{ name: 'Ajit Pai', page: 'https://www.appropriations.senate.gov/hearings/oversight' }] } }).links.map(link => [link.group, link.label]), [
    ['Printed hearing', 'CHRG-108jhrg89733.htm'],
    ['Printed hearing', 'CHRG-108jhrg89733.pdf'],
    ['Witness statement', 'Pai Testimony'],
    ['Amendment', 'H.R. 369 · Amendment 1 · Amendment to H.R. 369 · BILLS-115-HR369-Amdt-1.pdf'],
    ['Witness page', 'Ajit Pai'],
  ]);
  assert.equal(sourceFacts({ payload: { status: 'no_video_found', package_id: 'CHRG-111hhrg57220' } }).find(([label]) => label === 'Video match')?.[1], 'No video found');
  assert.equal(sourceFacts({ payload: { witnesses: [{ honorific: 'Honorable', first: 'Robert', last: 'Kadlec', position: 'Nominee', testified: 'Yes', panel: '1' }] } }).find(([label]) => label === 'Source witnesses')?.[1], 'Honorable Robert Kadlec · Nominee · Panel 1 · Testified');
  assert.equal(sourceFacts({ payload: { witnesses: [{ name: 'Ms. Alexandra Steinberg Barrage', honorific: 'Ms.', organization: 'Morrison Foerster', location: 'Washington, D.C.', witness_type: 'Non-Governmental', behalf_of: 'The Coalition', bioguide_id: 'S000001' }] } }).find(([label]) => label === 'Source witnesses')?.[1], 'Ms. Alexandra Steinberg Barrage · Morrison Foerster · Washington, D.C. · On behalf of The Coalition · Non-Governmental · Member number S000001');
  assert.equal(sourceFacts({ payload: { held_date: '2016-02-25', hearing_dates: '2016-02-25;2016-09-22', date_ingested: '2016-10-01' } }).find(([label]) => label === 'Additional sitting')?.[1], '2016-09-22');
  assert.equal(sourceFacts({ payload: { held_date: '2016-02-25', hearing_dates: '2016-02-25;2016-09-22', date_ingested: '2016-10-01' } }).find(([label]) => label === 'Added at the source')?.[1], '2016-10-01');
  assert.equal(sourceFacts({ payload: { witness_status: 'absent' } }).find(([label]) => label === 'Witness list')?.[1], 'Not recorded');
  assert.equal(sourceFacts({ payload: { witness_status: 'present' } }).find(([label]) => label === 'Witness list')?.[1], 'Recorded');
  assert.equal(sourceFacts({ payload: { kind: 'webvtt' } }).find(([label]) => label === 'Captions')?.[1], 'Web captions');
  assert.equal(sourceFacts({ payload: { kind: 'none' } }).find(([label]) => label === 'Captions')?.[1], 'None recorded');
  assert.deepEqual(sourceLinks({ payload: { recording_id: 'BhwjiTpnSYo', urls: ['https://www.senate.gov/isvp/?comm=banking&filename=banking071123'], source_urls: ['https://www.govinfo.gov/content/pkg/CHRG-111shrg86304/html/CHRG-111shrg86304.htm'], cited_evidence: { url: 'https://history.house.gov/Records-and-Research/Committees-Bibliography/Committee-History/', description: 'House committee history' } } }).links.map(link => [link.group, link.label]), [
    ['Recording', 'BhwjiTpnSYo'],
    ['Recording', 'banking071123'],
    ['Source', 'CHRG-111shrg86304.htm'],
    ['Cited evidence', 'House committee history'],
  ]);
  assert.equal(sourceFacts({ payload: { xml_update: '2017-02-28T16:39:39.370', version: '2024-05-17T17:19:13Z' } }).find(([label]) => label === 'Meeting file updated')?.[1], '2017-02-28 16:39:39 UTC');
  assert.equal(sourceFacts({ payload: { xml_update: '2017-02-28T16:39:39.370', version: '2024-05-17T17:19:13Z' } }).find(([label]) => label === 'File dated')?.[1], '2024-05-17 17:19:13 UTC');
  assert.equal(sourceLinks({ payload: { amendments: [{ bill: 'H.R. 369', number: '1', description: 'Amendment to H.R. 369', sponsor_bioguide: 'W000799', url: 'https://docs.house.gov/BILLS-115-HR369-Amdt-1.pdf' }] } }).links[0]?.label, 'H.R. 369 · Amendment 1 · Amendment to H.R. 369 · Member number W000799 · BILLS-115-HR369-Amdt-1.pdf');
  assert.equal(sourceLinks({ payload: { documents: [['bill or amendment', 'Amendment to H.R. 369', 'https://docs.house.gov/BILLS-115-HR369-Amdt-1.pdf']], amendments: [{ description: 'Amendment to H.R. 369', sponsor_bioguide: 'W000799', url: 'https://docs.house.gov/BILLS-115-HR369-Amdt-1.pdf' }] } }).links[0]?.label, 'Amendment to H.R. 369 · BILLS-115-HR369-Amdt-1.pdf · Member number W000799');
  assert.equal(sourceFacts({ payload: { name: 'Aumua Amata Radewagen', position: 'Congresswoman', organization: 'U.S. House of Representatives', event_id: '327613', from: 'CHRG-116shrg40920' } }).find(([label]) => label === 'Witness')?.[1], 'Aumua Amata Radewagen · Congresswoman · U.S. House of Representatives');
  assert.equal(recordedPlace({ facts: [{ label: 'label', value: 'Orgill Innovation Center, Collierville, TN' }, { label: 'city', value: 'Collierville' }] }), 'Orgill Innovation Center, Collierville, TN');
  assert.deepEqual(distinctRecordedFacts([{ label: 'label', value: 'Northampton Community College, Bethlehem, PA' }, { label: 'building', value: 'Northampton Community College' }, { label: 'city', value: 'Bethlehem' }, { label: 'room', value: '1324' }]), [['Place', 'Northampton Community College, Bethlehem, PA'], ['room', '1324']]);
  assert.deepEqual(distinctRecordedFacts([{ label: 'field path', value: '/published_at' }, { label: 'detected at', value: '2026-09-28T00:40:12.226742Z' }]), [['Compared field', 'Published at'], ['Detected', '2026-09-28 00:40:12 UTC']]);
  assert.equal(recordedPlace({ facts: [{ label: 'building', value: 'Rayburn House Office Building' }, { label: 'room', value: '2118' }] }), 'Rayburn House Office Building, room 2118');
  assert.equal(recordedPlace({ facts: [{ label: 'room', value: 'HVC-210' }] }), 'Room HVC-210');
  assert.equal(recordedMeasures({ facts: [{ label: 'Related bill', value: 'HR 1' }, { label: 'Related bill', value: 'HR 2' }, { label: 'Related nomination', value: 'PN11-05' }] }), 'H.R. 1 · H.R. 2 · PN11-05');
  assert.equal(recordedMeasures({ facts: ['HR 1', 'HR 2', 'HR 3', 'HR 4', 'HR 5'].map(value => ({ label: 'Related bill', value })) }), 'H.R. 1 · H.R. 2 · H.R. 3 · H.R. 4 and 1 more');
  assert.equal(recordedAction({ title: 'The Honorable Jay Obernolte', facts: [{ label: 'Amendment number', value: '063' }, { label: 'Sponsor', value: 'The Honorable Jay Obernolte' }, { label: 'Regarding', value: 'H.R. 8462' }] }), 'Amendment 063 · H.R. 8462');
  assert.equal(recordedAction({ title: 'Amendment #1 to H.R. 1341', facts: [{ label: 'Sponsor Bioguide ID', value: 'B001281' }, { label: 'En bloc group', value: '2' }, { label: 'Vote question', value: 'Ordered reported' }, { label: 'Amendment description', value: 'Amendment 7' }] }), 'Member number B001281 · En bloc 2 · Ordered reported · Amendment 7');
  assert.equal(recordedAction({ title: 'Amendment offered by Ms. DelBene', facts: [{ label: 'Amendment number', value: '1' }, { label: 'Amendment number', value: '10' }] }), 'Amendment 1 · Amendment 10');
  assert.deepEqual(recordedAmendments({ facts: [{ label: 'Amendment', value: 'Amendment to HR 5487 – Offered by Rep. Roe - (WITHDRAWN)' }] }), ['Amendment to H.R. 5487 – Offered by Rep. Roe - (WITHDRAWN)']);
  assert.equal(recordedWitnesses({ title: 'Hearing on Prescription Drug Abuse', search_text: 'Hearing on Prescription Drug Abuse Avi Israel Gil Kerlikowske' }), 'Avi Israel Gil Kerlikowske');
  assert.equal(recordedWitnesses({ title: 'Hearing on Prescription Drug Abuse', search_text: 'Hearing on Prescription Drug Abuse' }), '');
  assert.equal(separateWitnesses('Avi Israel Gil Kerlikowske John Smith Jr', ['Gil Kerlikowske', 'John Smith', 'John Smith Jr', 'Avi Israel']), 'Avi Israel · Gil Kerlikowske · John Smith Jr');
  assert.equal(separateWitnesses('Avi Israel Gil Kerlikowske', []), 'Avi Israel Gil Kerlikowske');
  assert.deepEqual(witnessNameList('Avi Israel Gil Kerlikowske John Smith Jr', ['Gil Kerlikowske', 'John Smith', 'John Smith Jr', 'Avi Israel']), ['Avi Israel', 'Gil Kerlikowske', 'John Smith Jr']);
  assert.deepEqual(witnessNameList('Avi Israel', ['Avi Israel', 'Jane Doe']), ['Avi Israel', 'Jane Doe']);
  assert.deepEqual(witnessNameList('Avi Israel Gil Kerlikowske', []), ['Avi Israel Gil Kerlikowske']);
  assert.deepEqual(witnessNameList('', ['Jane Doe']), ['Jane Doe']);
  assert.equal(committeeKindNote({ committee_types: ['select'], committee_ids: ['intel'] }, { intel: 'House Intelligence (Permanent) Subcommittee on Defense Intelligence and Overhead Architecture' }), 'Select');
  assert.equal(committeeKindNote({ committee_types: ['select'], committee_ids: ['intel'] }, { intel: 'House Permanent Select Committee on Intelligence' }), '');
  assert.equal(committeeKindNote({ committee_types: ['standing', 'unknown', 'other'] }, {}), '');
  assert.equal(committeeKindNote({ committee_types: ['commission_or_caucus'], committee_ids: ['caucus'] }, { caucus: 'United States Senate Caucus on International Narcotics Control' }), '');
  assert.equal(committeeLevelNote({ committee_level: 'subcommittee', committee_ids: ['sba'] }, { sba: 'Innovation, Entrepreneurship, and Workforce Development' }), 'Subcommittee');
  assert.equal(committeeLevelNote({ committee_level: 'subcommittee', committee_ids: ['intel'] }, { intel: 'House Intelligence Subcommittee' }), '');
  assert.equal(committeeHierarchyNote('The source identifies a parent committee.'), '');
  assert.equal(committeeHierarchyNote('Congress.gov systemCode hsha00: final two digits 00 identify a full committee; other digits identify a subcommittee.'), '');
  assert.equal(committeeHierarchyNote('This committee reports to two parents.'), 'This committee reports to two parents.');
  assert.equal(committeeLevelNote({ committee_level: 'full', committee_ids: ['sba'] }, { sba: 'Small Business' }), '');
  assert.equal(publishedNote({ date: '2013-07-17', files: [{ published_at: '2016-02-08' }] }), 'Published 2016-02-08');
  assert.equal(publishedNote({ date: '2016-03-08', files: [{ published_at: '2016-03-08' }] }), '');
  assert.deepEqual(recordedVotes({ facts: [{ label: 'Vote number', value: '12' }, { label: 'Vote 12', value: 'Later result' }, { label: 'Vote 1', value: 'H.R. 647 was ordered favorably reported by voice vote' }] }), ['H.R. 647 was ordered favorably reported by voice vote', 'Later result']);
  assert.deepEqual(recordedAmendments({ facts: [{ label: 'Amendment 1', value: 'HR 5415 ANS' }, { label: 'Amendment number', value: '1' }] }), ['Amendment 1: H.R. 5415 ANS']);
  assert.equal(evidenceLine({ recording: 'reported', transcript: 'unchecked', documents: 'reported', witnesses: 'reported', captions: 'unknown' }), 'Recording stated by the source · Transcript not checked · Documents stated by the source · Witness list stated by the source · Captions not recorded');
  assert.equal(evidenceLine({ recording: 'not_applicable', captions: 'not_applicable' }), 'Recording outside this meeting · Captions outside this meeting');
  assert.deepEqual(listedEvidence({ recording: 'reported', transcript: 'unchecked', documents: 'not_applicable', witnesses: 'inferred', captions: 'unknown' }), ['Recording stated by the source', 'Witness list likely match, needs a check']);
  assert.deepEqual(listedEvidence({ recording: 'reported', transcript: 'unchecked', documents: 'reported', witnesses: 'reported', captions: 'unknown' }, { omit: ['witnesses'] }), ['Recording stated by the source', 'Documents stated by the source']);
  assert.deepEqual(listedEvidence({ recording: 'not_applicable', captions: 'unchecked' }), []);
  assert.equal(listedWitnessCount(0), '');
  assert.equal(listedWitnessCount(1), '1 witness');
  assert.equal(listedWitnessCount(4), '4 witnesses');
  assert.equal(factLabel('label', ['label', 'building', 'city']), 'Place');
  assert.equal(factLabel('label', ['label']), 'label');
  assert.deepEqual(linkedMeetingIds({ meeting_id: 'one', meeting_ids: ['two', 'two', 'three'] }), ['two', 'three']);
  assert.deepEqual(linkedMeetingIds({ meeting_id: 'one', meeting_ids: [] }), ['one']);
  assert.deepEqual(collapseRepeatedFacts([['Related bill', 'S 1254'], ['Related bill', 'S 1254'], ['Related bill', 'S 2970'], ['Room', '366']]), [['Related bill', 'S 1254\nS 2970'], ['Room', '366']]);
});

test('related rows keep the recorded role, time, and issue severity', () => {
  assert.equal(relatedMeta('appearance', { position: 'President', organization: 'Orgill', roles: ['witness'], participation: 'listed', date: '2026-10-06' }), 'President · Orgill · 2026-10-06');
  assert.equal(relatedMeta('committee_term', { title: 'House Administration Subcommittee on Elections', committee_type: 'subcommittee', committee_level: 'subcommittee', committee_types: ['standing'], congress: 119 }), 'Standing, like the parent committee · 119th Congress');
  assert.equal(relatedMeta('committee_term', { title: 'Committee on House Administration', committee_type: 'standing', committee_level: 'full', congress: 119 }), 'Standing · Full committee · 119th Congress');
  assert.equal(omitRepeatedCongress(relatedParts('committee_term', { title: 'House Administration Subcommittee on Elections', committee_type: 'subcommittee', committee_level: 'subcommittee', committee_types: ['standing'], congress: 119 }), 119).map(part => part.text).join(' · '), 'Standing, like the parent committee');
  assert.equal(omitRepeatedCongress(relatedParts('meeting', { type: 'hearing', congress: 118, chamber: 'house' }), 119).map(part => part.text).join(' · '), 'Hearing · 118th Congress · House');
  assert.equal(omitRepeatedChamber(relatedParts('meeting', { type: 'hearing', chamber: 'house', facts: [{ label: 'building', value: 'Rayburn House Office Building' }, { label: 'room', value: '2237' }] }), 'house').map(part => part.text).join(' · '), 'Hearing · Rayburn House Office Building, room 2237');
  assert.equal(omitRepeatedChamber(relatedParts('meeting', { type: 'hearing', chamber: 'house', facts: [{ label: 'building', value: 'Capitol' }, { label: 'room', value: 'S-219' }] }), 'house').map(part => part.text).join(' · '), 'Hearing · House · Capitol, room S-219');
  assert.equal(listedWhen({ date: '2025-03-25', scheduled_at: '2025-03-25T19:30:00Z' }, { timeZone: 'America/New_York', locale: 'en-US' }), '2025-03-25 3:30 PM EDT');
  assert.equal(plainLegislativeNote('HR 2625'), 'H.R. 2625');
  assert.equal(plainLegislativeNote('S 1254'), 'S. 1254');
  assert.equal(plainLegislativeNote('H.R.1107 AGREED (no attached file)'), 'H.R. 1107 AGREED');
  assert.equal(omitRepeatedWhen(relatedParts('appearance', { position: 'Commander', participation: 'testified', date: '2025-03-25' }), '2025-03-25 3:30 PM EDT').map(part => part.text).join(' · '), 'Commander · Testified');
  assert.equal(omitRepeatedWhen(relatedParts('appearance', { date: '2025-03-26' }), '2025-03-25 3:30 PM EDT').map(part => part.text).join(' · '), '2025-03-26');
  assert.equal(documentSourceInContext({ source_document_groups: ['meetingDocuments'] }, true), '');
  assert.equal(documentSourceInContext({ source_document_groups: ['meetingDocuments', 'witnessDocuments'] }, true), 'Witness document');
  assert.equal(documentSourceInContext({ source_document_groups: ['meetingDocuments'] }, false), 'Meeting document');
  assert.equal(relatedMeta('appearance', { position: 'Ophthalmologist', roles: ['witness'], participation: 'testified', date: '2014-01-16' }), 'Ophthalmologist · Testified · 2014-01-16');
  assert.deepEqual(notableRoles({ position: 'Nominee to be Director', roles: ['nominee', 'witness'] }), []);
  assert.equal(participationNote({ participation: 'listed' }), '');
  assert.equal(participationNote({ participation: 'testified' }), 'Testified');
  assert.deepEqual(witnessNotes({ organization: 'U.S. Forest Service', facts: [{ label: 'on behalf of', value: 'U.S. Department of Agriculture' }, { label: 'location', value: 'Washington, D.C.' }] }), ['On behalf of U.S. Department of Agriculture', 'Washington, D.C.']);
  assert.deepEqual(witnessNotes({ organization: 'Orgill', facts: [{ label: 'on behalf of', value: 'Orgill' }, { label: 'on behalf of', value: 'themselves' }] }), []);
  assert.equal(listedSourceStatus({ status: 'upcoming', source_status: 'scheduled' }), '');
  assert.equal(listedSourceStatus({ status: 'past', source_status: 'scheduled' }), 'The source still says scheduled');
  assert.equal(relatedMeta('meeting', { type: 'hearing', status: 'past', source_status: 'scheduled', date: '2026-01-01' }).includes('The source still says scheduled'), true);
  assert.equal(relatedMeta('meeting', { title: 'Full Committee Hearing on elections', type: 'hearing', date: '2026-07-22' }).startsWith('2026-07-22'), true);
  assert.equal(relatedMeta('meeting', { title: 'Full Committee Hearing on elections', type: 'meeting', date: '2026-06-25' }).startsWith('Meeting'), true);
  assert.equal(listedSourceStatus({ status: 'past', source_status: 'unknown' }), 'Status at the source not recorded');
  assert.deepEqual(relatedParts('meeting', { type: 'business', date: '2026-09-30', congress: 119, chamber: 'senate', status: 'past', facts: [{ label: 'building', value: 'Dirksen Senate Office Building' }, { label: 'room', value: '366' }] }).filter(part => part.role).map(part => [part.role, part.text]), [['place', 'Dirksen Senate Office Building, room 366'], ['status', 'Past']]);
  assert.equal(sourceFacts({ payload: { chamber: 'house' } }).find(([label]) => label === 'Chamber')?.[1], 'House');
  assert.equal(sourceFacts({ payload: { witnesses: [{ name: 'Richard Blaylock' }], people: [{ name: 'Richard Blaylock', position: 'Professor' }, { name: 'Sue Peschin' }] } }).find(([label]) => label === 'Source witnesses')?.[1], 'Richard Blaylock\nRichard Blaylock · Professor\nSue Peschin');
  assert.equal(sourceFacts({ payload: { absent: true } }).find(([label]) => label === 'Listing')?.[1], 'Recorded as absent');
  assert.equal(sourceFacts({ payload: { absent: false, people: [{ name: 'Sue Peschin' }] } }).find(([label]) => label === 'Listing'), undefined);
  const decision = sourceFacts({ payload: { status: 'dismissed', decided_at: '2026-09-28T14:13:10.594295+00:00', explanation: 'Collectors assigned different internal edition labels.' } });
  assert.equal(decision.find(([label]) => label === 'Decision')?.[1], 'Dismissed');
  assert.equal(decision.find(([label]) => label === 'Decided')?.[1], '2026-09-28');
  assert.equal(decision.find(([label]) => label === 'Explanation')?.[1], 'Collectors assigned different internal edition labels.');
  assert.equal(sourceFacts({ payload: { status: 'no_video_found', decided_at: '2026-09-28', explanation: 'No video found.' } }).find(([label]) => label === 'Decision'), undefined);
  const committee = sourceFacts({ payload: { committee: { name: 'Foreign Affairs Committee', chamber: 'House', committeeTypeCode: 'Standing', subcommittees: [{ name: 'Africa Subcommittee' }] }, detail: { type: 'Standing', isCurrent: false, history: [{ officialName: 'Committee on Foreign Affairs', startDate: '2007-01-02T05:00:01Z', establishingAuthority: '110 H Res 6' }, { officialName: 'Committee on International Relations', startDate: '1995-01-03T05:00:01Z', endDate: '2007-01-02T05:00:00Z' }] } } });
  assert.equal(committee.find(([label]) => label === 'Committee')?.[1], 'Foreign Affairs Committee');
  assert.equal(committee.find(([label]) => label === 'Committee type')?.[1], 'Standing');
  assert.equal(committee.find(([label]) => label === 'Committee status')?.[1], 'Former');
  assert.equal(committee.find(([label]) => label === 'Subcommittees')?.[1], 'Africa Subcommittee');
  assert.equal(committee.find(([label]) => label === 'Name history')?.[1], 'Committee on Foreign Affairs · From 2007-01-02 · 110 H Res 6\nCommittee on International Relations · 1995-01-03 to 2007-01-02');
  assert.deepEqual(sourceLinks({ payload: { detail: { committeeWebsiteUrl: 'https://foreignaffairs.house.gov/' } } }).links, [{ group: 'Committee website', href: 'https://foreignaffairs.house.gov/', label: 'foreignaffairs.house.gov' }]);
  const curated = sourceFacts({ payload: { event_id: '108756', recording: 'BhwjiTpnSYo', found_by: 'committee event page', note: 'Homeland Security second record of the same joint hearing.' } });
  assert.equal(curated.find(([label]) => label === 'Note')?.[1], 'Homeland Security second record of the same joint hearing.');
  assert.equal(curated.find(([label]) => label === 'Found')?.[1], 'Committee event page');
  assert.equal(curated.find(([label]) => label === 'Event number')?.[1], '108756');
  assert.equal(sourceFacts({ payload: { status: 'clips_only', note: 'Clips only that day.' } }).find(([label]) => label === 'Match note')?.[1], 'Clips only that day.');
  assert.deepEqual(sourceLinks({ payload: { recording: 'BhwjiTpnSYo' } }).links, [{ group: 'Recording', href: 'https://www.youtube.com/watch?v=BhwjiTpnSYo', label: 'BhwjiTpnSYo' }]);
  const review = sourceFacts({ payload: { explanation: 'Floor proceedings are outside this committee-meeting collection.', values: { committee_type: 'other', name: 'Committee of the Whole House on the State of the Union', website: 'https://live.house.gov/' } } });
  assert.equal(review.find(([label]) => label === 'Committee')?.[1], 'Committee of the Whole House on the State of the Union');
  assert.equal(review.find(([label]) => label === 'Committee type')?.[1], 'Other');
  assert.equal(review.find(([label]) => label === 'Explanation')?.[1], 'Floor proceedings are outside this committee-meeting collection.');
  const span = sourceFacts({ payload: { first_congress: 110, last_congress: 112, terminated: '2011-04-03', add_congresses: [119], source_document_type: 'Congressional Budget Justification', category: 'supporting', explanation: 'Terminated April 3, 2011.' } });
  assert.equal(span.find(([label]) => label === 'First Congress')?.[1], '110th Congress');
  assert.equal(span.find(([label]) => label === 'Last Congress')?.[1], '112th Congress');
  assert.equal(span.find(([label]) => label === 'Terminated')?.[1], '2011-04-03');
  assert.equal(span.find(([label]) => label === 'Also recorded')?.[1], '119th Congress');
  assert.equal(span.find(([label]) => label === 'Document type')?.[1], 'Congressional Budget Justification');
  assert.equal(span.find(([label]) => label === 'Document category')?.[1], 'Supporting');
  assert.deepEqual(sourceLinks({ payload: { values: { website: 'https://live.house.gov/' } } }).links, [{ group: 'Committee website', href: 'https://live.house.gov/', label: 'live.house.gov' }]);
  assert.equal(sourceCountNote({ source_ids: ['a'] }), '');
  assert.equal(sourceCountNote({ source_ids: ['a', 'b'] }), 'Built from 2 original pages');
  assert.equal(relatedMeta('meeting', { type: 'hearing', congress: 119, source_ids: ['a', 'b', 'c'] }), 'Hearing · 119th Congress · Built from 3 original pages');
  assert.equal(detectedNote({ date: '2013-10-23', facts: [{ label: 'detected at', value: '2026-09-28T00:40:12.226742Z' }] }), 'Detected 2026-09-28');
  assert.equal(detectedNote({ date: '2026-09-28', facts: [{ label: 'detected at', value: '2026-09-28T00:40:12Z' }] }), '');
  assert.equal(detectedNote({ facts: [{ label: 'detected at', value: '2026-10-18T01:02:03Z' }] }), 'Detected 2026-10-18');
  assert.equal(subjectAbsentNote('material'), 'The document or recording this issue describes is not in this publication.');
  assert.equal(subjectAbsentNote('source_record'), 'The original source this issue describes is not in this publication.');
  assert.equal(sourceTypeNote({ type: 'hearing', facts: [{ label: 'Source type', value: 'Meeting' }] }), 'Source type Meeting');
  assert.equal(sourceTypeNote({ type: 'hearing', facts: [{ label: 'Source type', value: 'Open Hearing' }] }), '');
  assert.equal(sourceTypeNote({ type: 'hearing', facts: [{ label: 'Source type', value: 'Joint Open Hearing' }] }), '');
  assert.equal(sourceTypeNote({ type: 'business', facts: [{ label: 'Source type', value: 'Open Business Meeting' }] }), '');
  assert.equal(sourceTypeNote({ type: 'business', facts: [{ label: 'Source type', value: 'Meeting' }] }), 'Source type Meeting');
  assert.equal(sourceTypeNote({ type: 'markup', facts: [{ label: 'Source type', value: 'Closed Markup Session' }] }), '');
  assert.equal(sourceTypeNote({ type: 'roundtable', facts: [{ label: 'Source type', value: 'Open Hearing' }] }), 'Source type Open Hearing');
  assert.equal(relatedMeta('meeting', { type: 'hearing', congress: 113, facts: [{ label: 'Source type', value: 'Meeting' }] }), 'Hearing · Source type Meeting · 113th Congress');
  assert.equal(relatedMeta('meeting', { type: 'business', date: '2026-09-30', congress: 119, chamber: 'senate', status: 'past', facts: [{ label: 'building', value: 'Dirksen Senate Office Building' }, { label: 'room', value: '366' }, { label: 'Related bill', value: 'S 1254' }, { label: 'Vote 1', value: 'Agreed to' }, { label: 'Amendment 1', value: 'HR 5415 ANS' }] }), 'Business meeting · 2026-09-30 · 119th Congress · Senate · Dirksen Senate Office Building, room 366 · Past');
  assert.equal(relatedMeta('data_issue', { category: 'conflicting', title: 'Sources disagree about name', explanation: 'The retained name keeps the later source.' }), 'Conflicting · The retained name keeps the later source.');
  assert.equal(relatedMeta('data_issue', { category: 'conflicting', severity: 'affects_interpretation', status: 'open', date: '2026-10-18' }), 'Conflicting · Changes how to read it · Still open · 2026-10-18');
  const disagreement = relatedParts('data_issue', { category: 'conflicting', status: 'open', source_ids: ['a', 'b'], facts: [{ label: 'Selected value', value: '{"channel":"5dbb6c64-2f48-4364-86cc-68a38059ae57"}' }, { label: 'alternative 1', value: '{}' }] });
  assert.equal(disagreement.find(part => part.text === 'Built from 4 original pages'), undefined);
  assert.equal(disagreement[disagreement.findIndex(part => part.role === 'note') - 1]?.text, 'Built from 2 original pages');
  assert.match(disagreement.find(part => part.role === 'note')?.text || '', /Channel: recorded on this version\. Another recorded version does not have one/);
});

test('an issue list names the field and the recorded difference', () => {
  assert.deepEqual(issueNotes({
    title: 'Sources disagree about title',
    facts: [
      { label: 'field path', value: '/title' },
      { label: 'Selected value', value: 'Rules Committee Hearing H.R. 3838 and 3486 Part II' },
      { label: 'Alternative 1', value: 'Rules Committee Hearing H.R. 3838 and 3486' },
      { label: 'Selection reason', value: 'Later record in deterministic source order; alternatives retained.' },
    ],
  }), [
    'Compared field: Title',
    'Rules Committee Hearing H.R. 3838 and 3486 Part II',
    'Alternative: Rules Committee Hearing H.R. 3838 and 3486',
    'The later source was kept. The other version is still saved.',
  ]);
  assert.deepEqual(issueNotes({
    title: 'Sources disagree about title',
    facts: [
      { label: 'Selected value', value: 'First title' },
      { label: 'Alternative 1', value: 'Second title' },
      { label: 'Alternative 2', value: 'Third title' },
      { label: 'Alternative 3', value: 'Fourth title' },
    ],
  }), ['First title', 'Alternative: Second title']);
  assert.deepEqual(extraIssueAlternatives({
    facts: [
      { label: 'Selected value', value: 'First title' },
      { label: 'Alternative 1', value: 'Second title' },
      { label: 'Alternative 2', value: 'Third title' },
      { label: 'Alternative 3', value: 'Fourth title' },
    ],
  }), ['Third title', 'Fourth title']);
  assert.deepEqual(issueNotes({ title: 'Same', explanation: 'Same' }), []);
  assert.deepEqual(issueNotes({ title: 'Unlinked recording', explanation: 'The containing page has no unambiguous saved meeting match.' }), ['The page this came from does not match one saved meeting.']);
  assert.deepEqual(issueNotes({
    title: 'This package has no verified meeting association.',
    explanation: 'Retained as a document. A title, committee code or hearing date alone does not establish meeting identity.',
    facts: [{ label: 'Resolution', value: 'The existing print matcher supplied a supported association; its method and evidence remain on the link.' }],
  }), [
    'A match to a printed hearing was saved with this link.',
    'Kept as a document. A title, a committee, or a hearing date is not enough to name the meeting.',
  ]);
  assert.equal(plainRecordedNote('The probe has no supported live check date.'), 'There is no saved date for a live check of this page.');
  assert.equal(plainRecordedNote('A sentence saved only on this issue.'), 'A sentence saved only on this issue.');
  assert.equal(plainRecordedNote('Imported 18141 of 18141 retained records. Retention is not proof of complete upstream coverage.'), 'All 18,141 of 18,141 saved records were included. Saving a record does not mean every source was collected.');
  assert.equal(plainRecordedNote('Collection job youtube concluded success; this job-level receipt does not establish individual source acquisition outcomes.'), 'The YouTube collection reported success. That does not show the result for each source.');
  assert.equal(plainRecordedNote('Legacy native records lack per-record retrieval timestamps. Collection job congress concluded success; this job-level receipt does not establish individual source acquisition outcomes.'), 'Older records do not say when each one was downloaded. The Congress collection reported success. That does not show the result for each source.');
});

test('a recorded disagreement names the fields that differ', () => {
  const selected = '{"type":"recording","medium":"video","coverage":"unknown","provider":"youtube","channel":{"kind":"channel","id":"30826b4e-9d56-48ec-a0f7-326a4440461f"}}';
  const alternative = '{"type":"recording","medium":"video","coverage":"unknown","provider":"youtube","channel":null}';
  assert.deepEqual(disagreementSummary(selected, [alternative]), [
    'Channel: recorded on this version. Another recorded version does not have one.',
  ]);
  assert.deepEqual(disagreementSummary('{"type":"document","category":"statement"}', ['{"type":"document","category":"witness_list"}']), [
    'Category: Statement on this record; Witness list on another recorded version',
  ]);
  assert.equal(disagreementSummary('plain text', ['{"a":1}']), null);
});

test('a repeated document type uses the recorded file name', () => {
  const file = { url: 'https://docs.house.gov/meetings/WM/WM00/HHRG-119-WM00-Wstate-MooreB-20261006.pdf' };
  assert.equal(listTitle({ title: 'Witness Statement', document_type: 'Witness Statement', files: [file] }), 'HHRG-119-WM00-Wstate-MooreB-20261006.pdf');
  assert.equal(listTitle({ title: 'Opening remarks of Jane Doe', document_type: 'Witness Statement', files: [file] }), 'Opening remarks of Jane Doe');
});

test('a file name comes from the saved copy or the URL path', () => {
  assert.equal(recordedFileName({ saved_filename: 'Statement.pdf', url: 'https://docs.house.gov/other.pdf' }), 'Statement.pdf');
  assert.equal(recordedFileName({ url: 'https://docs.house.gov/meetings/WM/WM00/HHRG-119-WM00-Wstate-MooreB-20261006.pdf' }), 'HHRG-119-WM00-Wstate-MooreB-20261006.pdf');
  assert.equal(recordedFileName({ url: 'https://docs.house.gov/meetings/' }), '');
  assert.equal(recordedFileName(null), '');
  assert.deepEqual(recordedFileNames([{ url: 'https://www.govinfo.gov/CHRG-106shrg71518.htm' }, { url: 'https://www.govinfo.gov/CHRG-106shrg71518.pdf' }, { url: 'https://www.govinfo.gov/CHRG-106shrg71518-err.pdf' }]), ['CHRG-106shrg71518.pdf', 'CHRG-106shrg71518-err.pdf']);
  assert.equal(recordedFormatNote([{ label: 'HTML', url: 'https://www.govinfo.gov/CHRG-106shrg71518.htm' }, { label: 'PDF', url: 'https://www.govinfo.gov/CHRG-106shrg71518.pdf' }]), 'PDF and web page');
  assert.equal(recordedFormatNote([{ label: 'pdf', url: 'https://www.govinfo.gov/a.pdf' }]), '');
  assert.equal(recordedFormatNote([{ label: 'download', url: 'https://www.senate.gov/download/statement' }]), '');
  assert.deepEqual(recordedAddressNames({ title: 'Howard Schiller', files: [{ url: 'https://www.aging.senate.gov/download/howard-schiller' }] }), []);
  assert.deepEqual(recordedAddressNames({ title: 'Rules', files: [{ url: 'https://www.finance.senate.gov/download/rules-of-the-procedure-119-2' }] }), ['rules-of-the-procedure-119-2']);
  assert.deepEqual(recordedAddressNames({ title: 'Admiral John C. Aquilino, USN', files: [{ url: 'https://www.armed-services.senate.gov/download/aquilino-statement' }] }), ['aquilino-statement']);
  assert.deepEqual(recordedAddressNames({ title: 'Cassidy S.2840 Amendment #24.pdf', files: [{ url: 'https://www.help.senate.gov/download/cassidy-s2840-amendment-24' }] }), []);
  assert.deepEqual(recordedAddressNames({ title: 'Hearing video', files: [{ url: 'https://www.youtube.com/watch?v=abc' }] }), []);
  assert.deepEqual(recordedAddressNames({ title: 'Baldwin', files: [{ url: 'https://www.commerce.senate.gov/services/files/CE7E8689-C1B8-4FCF-B276-752935F5552C' }] }), []);
  assert.equal(fileLinkName({ label: 'download', url: 'https://www.finance.senate.gov/download/rules-of-the-procedure-119-2' }), 'rules-of-the-procedure-119-2');
  assert.equal(fileLinkName({ label: 'html', url: 'https://www.govinfo.gov/content/pkg/CHRG-106shrg71518.htm' }), 'CHRG-106shrg71518.htm');
  assert.equal(fileLinkName({ label: 'pdf — OTHERPART — confirmation hearing', url: 'https://www.govinfo.gov/CHRG-106shrg71518.pdf' }), 'OTHERPART — confirmation hearing · CHRG-106shrg71518.pdf');
  assert.equal(fileLinkName({ role: 'player', label: 'youtube player', url: 'https://www.youtube.com/watch?v=abc' }), 'Watch recording');
});

test('a scheduled clock time stays with the recorded date', () => {
  const eastern = { timeZone: 'America/New_York', locale: 'en-US' };
  assert.deepEqual(recordedWhen({ date: '2026-09-27', scheduled_at: '2026-09-27T14:30:00-04:00' }, eastern), { date: '2026-09-27', time: '2:30 PM EDT' });
  assert.deepEqual(recordedWhen({ date: '2026-09-27', scheduled_at: '2026-09-27T18:30:00Z' }, eastern), { date: '2026-09-27', time: '2:30 PM EDT' });
  assert.deepEqual(recordedWhen({ scheduled_at: '2026-09-27' }, eastern), { date: '2026-09-27', time: '' });
  assert.deepEqual(recordedWhen({ date: '2026-09-27', scheduled_at: '2026-09-27T00:00:00Z' }, eastern), { date: '2026-09-27', time: '' });
  assert.deepEqual(recordedWhen({}), { date: '', time: '' });
  assert.deepEqual(recordedWhen({ date: '2014-03-26', scheduled_at: '2014-04-03T17:00:00Z' }, eastern), { date: '2014-03-26', time: '' });
  assert.equal(scheduleNote({ date: '2014-03-26', scheduled_at: '2014-04-03T17:00:00Z' }, eastern), 'Scheduled 2014-04-03 1:00 PM EDT');
  assert.equal(scheduleNote({ date: '2026-09-27', scheduled_at: '2026-09-27T14:30:00-04:00' }, eastern), '');
  assert.equal(scheduleNote({ scheduled_at: '2019-12-04T15:00:00Z' }, eastern), 'Scheduled 2019-12-04 10:00 AM EST');
  assert.equal(relatedMeta('material', { title: 'Recording', scheduled_at: '2019-12-04T15:00:00Z' }), scheduleNote({ scheduled_at: '2019-12-04T15:00:00Z' }));
  assert.deepEqual(recordedWhen({ scheduled_at: '2019-12-04T15:00:00Z' }, eastern), { date: '2019-12-04', time: '10:00 AM EST' });
});

test('saved copies use the viewer-data content route', () => {
  const hash = 'ab'.repeat(32);
  const origin = 'https://congressional-viewer-data.mdeeb.workers.dev';
  assert.equal(savedCopyHref({saved_copy_sha256: hash, saved_filename: 'Witness statement.pdf'}), `${origin}/saved/${hash}/Witness%20statement.pdf`);
  assert.equal(savedCopyHref({saved_copy_sha256: hash}), `${origin}/saved/${hash}/saved-copy`);
  assert.equal(savedCopyHref({saved_copy_sha256: hash, saved_filename: '../secret'}), `${origin}/saved/${hash}/saved-copy`);
  assert.equal(savedCopyHref({saved_copy_sha256: 'short', saved_filename: 'a.pdf'}), undefined);
  assert.equal(savedCopyHref(null), undefined);
});

test('supported YouTube and Senate recordings embed without autoplay', () => {
  for (const url of ['https://www.youtube.com/watch?v=PRXQf-CSnoo&t=0', 'https://youtu.be/PRXQf-CSnoo', 'https://www.youtube.com/embed/PRXQf-CSnoo', 'https://m.youtube.com/shorts/PRXQf-CSnoo', 'https://www.youtube.com/live/PRXQf-CSnoo', 'https://www.youtube.com/v/PRXQf-CSnoo']) {
    assert.equal(recordingEmbedUrl({...recording, recording_url: url}, now), 'https://www.youtube.com/embed/PRXQf-CSnoo');
    assert.equal(recordingIdentity(url), 'YouTube PRXQf-CSnoo');
    assert.equal(recordingIdentity('https://www.senate.gov/isvp/?comm=armed&filename=armedA050825'), 'armedA050825');
    assert.equal(meetingStatusNote({ meeting_status: 'postponed' }), 'Meeting postponed');
    assert.equal(meetingStatusNote({ meeting_status: 'canceled' }), 'Meeting canceled');
    assert.equal(meetingStatusNote({ meeting_status: 'scheduled' }), '');
    assert.equal(meetingStatusNote({ meeting_status: 'unknown' }), 'Meeting status unknown');
    assert.equal(relatedMeta('meeting', { type: 'hearing', status: 'past', source_status: 'unknown', congress: 112 }), 'Hearing · 112th Congress · Past · Status at the source not recorded');
  }
  assert.equal(recordingEmbedUrl({...recording, recording_url: 'https://www.senate.gov/isvp/?comm=armed&filename=armedA050825&auto_play=true'}, now),
    'https://www.senate.gov/isvp/?comm=armed&filename=armedA050825&auto_play=false');
});

test('unsupported URLs and unavailable recordings never produce embeds', () => {
  for (const url of ['javascript:alert(1)', 'https://example.org/player', 'https://www.youtube.com.evil.test/watch?v=PRXQf-CSnoo', 'https://www.youtube.com/watch?v=invalid', 'https://www.senate.gov/isvp/?comm=armed', 'https://www.senate.gov/hearing', null]) {
    assert.equal(recordingEmbedUrl({...recording, recording_url: url}, now), undefined);
  }
  const row = {...recording, recording_url: 'https://youtu.be/PRXQf-CSnoo'};
  for (const changes of [{date: '2026-10-01'}, {date: '2026-09-27'}, {meeting_status: 'canceled'}, {meeting_status: 'postponed'}, {type: 'document'}]) {
    assert.equal(recordingEmbedUrl({...row, ...changes}, now), undefined);
  }
});

test('source document groups remain distinct and searchable alongside native documentType', () => {
  const row = {title: 'Prepared remarks', document_type: 'Witness Statement', source_document_groups: ['witnessDocuments']};
  assert.equal(documentSourceLabel(row), 'Witness document');
  assert.equal(matches(row, {q: 'witness document'}), true);
  assert.equal(matches(row, {q: 'witnessDocuments'}), true);
  assert.equal(matches(row, {q: 'Witness Statement'}), true);
  assert.equal(matches(row, {q: 'meetingDocuments'}), false);
  assert.equal(documentSourceLabel({source_document_groups: ['meetingDocuments', 'witnessDocuments']}), 'Meeting document · Witness document');
  assert.equal(listedDocumentType('Generic Document'), 'Document');
  assert.equal(listedDocumentType('Hearing: Transcript'), 'Transcript');
  assert.equal(listedDocumentType('Hearing: Questions for the Record'), 'Questions for the record');
  assert.equal(listedDocumentType('COMMITTEE PRINT'), 'Committee print');
  assert.equal(listedDocumentType('Support Document'), 'Supporting document');
  assert.equal(listedDocumentType('Witness Biography'), 'Witness biography');
  assert.equal(listedDocumentType('Witness Statement'), 'Witness statement');
  assert.equal(listedDocumentType('Witness Truth in Testimony'), 'Truth in testimony');
  assert.equal(listedDocumentType('Witness Support Document'), 'Supporting document for a witness');
  assert.equal(listedDocumentType('Bills and Resolutions'), 'Bills and resolutions');
  assert.equal(listedSourcePile({ document_type: 'Support Document', source_document_groups: ['meetingDocuments'] }, 'Supporting document'), '');
  assert.equal(listedSourcePile({ document_type: 'Witness Statement', source_document_groups: ['witnessDocuments'] }, 'Witness Statement'), '');
  assert.equal(listedSourcePile({ source_document_groups: ['meetingDocuments'] }, ''), 'Meeting document');
  assert.equal(listedSourcePile({ source_document_groups: ['meetingDocuments', 'witnessDocuments'] }, 'Support Document'), 'Witness document');
  assert.equal(documentSourceLabel({}), '');
  assert.equal(categoryNote({ category: 'statement', document_type: 'Support Document' }), 'Statement');
  assert.equal(categoryNote({ category: 'statement', document_type: 'Witness Statement' }), '');
  assert.equal(categoryNote({ category: 'disclosure', document_type: 'Witness Truth in Testimony' }), '');
  assert.equal(categoryNote({ category: 'witness_list', document_type: 'Support Document' }), 'Witness list');
  assert.equal(categoryNote({ category: 'amendment', document_type: 'Committee Recorded Vote' }), 'Amendment');
  assert.equal(categoryNote({ category: 'supporting', document_type: 'Support Document' }), '');
  assert.equal(categoryNote({ category: 'unknown', document_type: 'Support Document' }), '');
  assert.equal(categoryNote({ category: 'statement' }), 'Statement');
  assert.equal(subjectKindLabel('source_record'), 'source record');
  assert.equal(subjectKindLabel('committee'), 'committee');
  assert.equal(subjectKindLabel('person'), 'person');
  assert.equal(subjectKindLabel('meeting'), '');
  assert.equal(providerLabel('youtube'), 'YouTube');
  assert.equal(providerLabel('www.c-span.org'), 'C-SPAN');
  assert.equal(providerLabel('example.org'), 'example.org');
  assert.equal(providerLabel('www.dvidshub.net'), 'Defense media library');
  assert.equal(providerLabel('senate'), 'Senate.gov');
  assert.equal(providerLabel('www.senate.gov'), 'Senate.gov');
  assert.equal(filePartNote({ title: 'PBM Power Play', files: [{ label: 'PDF — OTHERPART — PBM POWER PLAY' }, { label: 'HTML — OTHERPART — PBM POWER PLAY' }] }), 'Other part');
  assert.equal(filePartNote({ title: '[ERRATA] Confirmation hearings', files: [{ label: 'PDF — ERRATA — [ERRATA] Confirmation hearings' }] }), '');
  assert.equal(filePartNote({ title: 'Hearing transcript', files: [{ label: 'PDF — FIRSTPART — Hearing transcript' }, { label: 'PDF — ERRATA — Hearing transcript' }] }), 'First part · Errata');
  assert.equal(landingPageNote({ files: [{ role: 'download' }, { role: 'landing' }] }), 'Committee page');
  assert.equal(landingPageNote({ files: [{ role: 'download' }] }), '');
});

test('elapsed schedules become Past without asserting that the meeting was held', () => {
  const past = presentRecord({...meeting, date: '2026-09-26'}, now);
  assert.equal(past.status, 'past');
  assert.equal(past.source_status, 'scheduled');
  assert.equal(past.evidence_states.recording, 'reported');
  assert.equal(presentRecord({...meeting, status: 'held'}, now).status, 'held');
  assert.equal(presentRecord({...meeting, status: 'rescheduled', date: '2026-09-26'}, now).status, 'past');
});

test('future recordings are hidden in listings and direct details, including timezone boundaries', () => {
  for (const scheduled_at of ['2026-10-01', '2026-09-27T12:00:00-04:00', '2026-09-27T16:00:00Z']) {
    assert.equal(recordingVisible({...recording, scheduled_at}, now), false);
    assert.deepEqual(presentRecord({...recording, scheduled_at}, now).files, []);
    const row = presentRecord({...meeting, scheduled_at}, now);
    assert.equal(row.status, 'upcoming');
    assert.equal(row.evidence_states.recording, 'not_applicable');
    assert.equal(row.evidence_states.documents, 'reported');
  }
  assert.equal(recordingVisible({...recording, scheduled_at: '2026-09-27T10:00:00-04:00'}, now), true);
});

test('date-only events use Washington calendar day; canceled meetings retain their status', () => {
  const midnightUTC = new Date('2026-09-28T01:00:00Z');
  assert.equal(recordingVisible({...recording, date: '2026-09-27'}, midnightUTC), false);
  assert.equal(presentRecord(meeting, midnightUTC).status, 'today');
  for (const status of ['canceled', 'postponed', 'not_held']) {
    assert.equal(presentRecord({...meeting, status, date: '2026-09-26'}, now).status, status);
    assert.equal(recordingVisible({...recording, meeting_status: status, date: '2026-09-26'}, now), false);
  }
  assert.equal(recordingVisible({...recording, recording_url: null}, now), false);
  assert.equal(recordingVisible(recording, now), true); // Undated archive video is not assumed upcoming.
});


test('committee category is separate from level and preserves explicit child categories', () => {
  const child = {committee_type:'subcommittee', committee_level:'subcommittee', source_committee_type:'Subcommittee', committee_types:['standing']};
  assert.equal(committeeTypeLabel(child), 'Standing, like the parent committee');
  assert.equal(child.source_committee_type, 'Subcommittee');
  assert.equal(committeeTypeLabel({...child, committee_type:'task_force'}), 'Task force');
  assert.equal(committeeTypeLabel({...child, committee_type:'unknown'}), 'Standing, like the parent committee');
  assert.equal(committeeTypeLabel({...child, committee_types:['unknown']}), 'Type not recorded');
  assert.equal(committeeTypeLabel({...child, committee_types:undefined}), 'Type not recorded');
  assert.equal(committeeTypeLabel({committee_type:'unknown', committee_level:'full', committee_types:['standing']}), 'Type not recorded');
  assert.equal(committeeSourceNote({ committee_type: 'commission_or_caucus', source_committee_type: 'Other' }), 'Source recorded Other');
  assert.equal(committeeSourceNote(child), '');
  assert.deepEqual(earlierCommitteeNames([
    { title: 'House Education and Workforce', congress: 119 },
    { title: 'House Education and the Workforce', congress: 118 },
    { title: 'Education and Workforce Committee', congress: 117 },
    { title: 'Education and Workforce Committee', congress: 116 },
    { title: 'Education and Workforce Committee', congress: 115 },
  ], 'House Education and Workforce'), [
    'House Education and the Workforce · 118th Congress',
    'Education and Workforce Committee · 115th–117th Congress',
  ]);
  assert.equal(dateFilterReason('gaps', 'from'), 'Keep issues on or after this day. This uses the issue date, not the detected day shown on a row. Issues with a date in range stay in.');
  assert.equal(dateFilterReason('witnesses', 'through'), 'Keep witnesses on or before this day. Witnesses with a date in range stay in.');
  assert.equal(dateFilterReason('meetings', 'from'), 'Keep records on or after this day. A record with no date uses its scheduled day when it has one.');
  assert.deepEqual(recordedTitleLines('Legislative Hearing on:H.R. 338\r\n\nH.R. 1514\nH.R. 3756'), ['Legislative Hearing on:H.R. 338', 'H.R. 1514', 'H.R. 3756']);
  const longTitle = `${'word '.repeat(70).trim()} ending`;
  const preview = recordedTitlePreview(longTitle);
  assert.equal(preview.continued, true);
  assert.ok(preview.preview.length <= 240);
  assert.equal(`${preview.preview} ${preview.rest.join(' ')}`, longTitle);
  assert.deepEqual(recordedTitlePreview('One\nTwo\nThree\nFour'), { preview: 'One\nTwo\nThree', rest: ['Four'], continued: false });
  assert.equal(coverageDrillNote({ committee: 'House Education and Workforce', month: '2014-05', aspect: 'transcript', evidence: 'reported' }), 'These limits came from a coverage chart. Only meetings of House Education and Workforce. Only meetings in 2014-05. Only meetings whose transcript result is stated by the source.');
  assert.equal(coverageDrillNote({ month: 'unknown' }), 'These limits came from a coverage chart. Only meetings with no recorded month.');
});
