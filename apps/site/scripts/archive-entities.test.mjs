import {test} from 'node:test';
import assert from 'node:assert/strict';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
import {formatSubject} from '../src/components/explorer/archive/archive-metadata.ts';
import {loadArchiveFixture} from './archive-test-fixture.mjs';

// Requires a separately assembled rich entity release; the small hand fixture does not qualify.
test('current entity Parquet files load lazily, support cross-filtering, and resolve rich entity details',async()=>{
  const fixture = await loadArchiveFixture('ARCHIVE_ENTITY_FIXTURE_FILES');
  const fetchedFiles = fixture.requests;
  const phase2Fetch = fixture.fetcher;

  const reader = await openArchive('https://fixture.test/manifest.json', {
    fetcher: phase2Fetch,
    heapBytes: 64 * 1024 * 1024,
  });

  // Startup admits catalog controls and list rows without loading optional entity tables.
  assert(!fetchedFiles.some(request=>request.path.endsWith('/witnesses.parquet')));
  assert(!fetchedFiles.some(request=>request.path.endsWith('/bills.parquet')));

  // Resolve one published source occurrence; a person's name is not a witness key.
  const occurrences=(await reader.listEntities('witnesses',{text:'Dr. Jane Smith'})).rows.filter(w=>
    w.name==='Dr. Jane Smith'&&w.occasion==='meeting:118001'&&w.source==='congress_gov'
    &&w.source_locator==='witness/1'&&w.superseded_by==null);
  assert.equal(occurrences.length,1,'The authored witness occurrence must resolve uniquely');
  const janeKey=occurrences[0].witness_key;
  assert.match(janeKey,/^[a-f0-9]{16}$/);

  // Filter documents by witness_key, bioguide_id, event_id, subject_key, and committee_key
  assert.equal((await reader.search({witness_key: janeKey})).total, 2);
  assert.equal((await reader.search({bioguide_id: 'S000510'})).total, 1);
  assert.equal((await reader.search({event_id: '118001'})).total, 2);
  assert.equal((await reader.search({subject_key: '118-hr-1234'})).total, 1);
  assert.equal((await reader.search({subject_key: '118-pn-730-2'})).total, 1);
  assert.equal((await reader.search({committee_key: 'hspw00'})).total, 2);

  // Rich Meeting lookup with joined recordings, committees, subjects, witnesses, and documents
  const meeting = await reader.getMeeting('house', 118001);
  assert(meeting);
  assert.equal(meeting.title, 'Transportation infrastructure hearing');
  assert.equal(meeting.status, 'held');
  assert.equal(meeting.sittings[0].building, 'Rayburn');
  assert.equal(meeting.recordings.length, 1);
  const recording=meeting.recordings[0];
  assert.equal(recording.video_key,'youtube:fixture-transit');
  assert.deepEqual(recording.event_ids,['118001']);
  assert.equal(recording.duration_seconds,5420);
  assert.equal(recording.tracks.length,1);
  const track=recording.tracks[0];
  assert.deepEqual({format:track.format,language:track.language,production:track.production,suffix:track.suffix},
    {format:'vtt',language:'en',production:'manual',suffix:'.gz'});
  assert.equal(Buffer.from(track.body).toString('hex'),'99'.repeat(32));
  assert.equal(track.sha256,'99'.repeat(32));
  const video=meeting.videos.find(item=>item.video_key===recording.video_key);
  assert(video,'The publisher video link must retain its captured caption tracks');
  assert.equal(video.url,'https://www.youtube.com/watch?v=fixture-transit');
  assert.equal(video.duration_seconds,5420);
  assert.deepEqual(video.tracks,recording.tracks);
  assert.equal(meeting.witnesses.length, 2);
  assert.equal(meeting.witnesses[0].name, 'Dr. Jane Smith');
  assert.equal(meeting.witnesses[0].documents.length, 2);
  assert.equal(meeting.subjects.length, 2);
  assert.equal(meeting.documents.length, 2);

  // Rich Committee lookup with historical name intervals, subcommittees, and roster
  const committeeCurrent = await reader.getCommittee('hspw00', {congress: 118});
  assert(committeeCurrent);
  assert.equal(committeeCurrent.resolved_name, 'House Committee on Transportation and Infrastructure');
  assert.equal(committeeCurrent.subcommittees.length, 1);
  assert.equal(committeeCurrent.roster.length, 2);
  assert.equal(committeeCurrent.roster[0].name, 'Sam Graves');
  assert.equal(committeeCurrent.hearings.length, 1);

  const committeeHistorical = await reader.getCommittee('hspw00', {date: '1985-06-01'});
  assert.equal(committeeHistorical.resolved_name, 'House Committee on Public Works and Transportation');

  // Rich Witness lookup
  const witness = await reader.getWitness(janeKey);
  assert(witness);
  assert.equal(witness.witness_key,janeKey);
  assert.equal(witness.name, 'Dr. Jane Smith');
  assert.deepEqual(witness.organizations, ['National Transit Institute']);
  assert.equal(witness.appearances.length, 1);
  assert.equal(witness.documents.length, 2);

  // Rich Member lookup
  const member = await reader.getMember('S000510');
  assert(member);
  assert.equal(member.name, 'Adam Smith');
  assert.equal(member.party, 'D');
  assert.equal(member.roster_entries.length, 1);
  assert.equal(member.sponsored_bills.length, 1);
  assert.equal(member.hearings.length, 1);
  assert.equal(member.documents.length, 1);

  // Rich Bill & Nomination lookups via getSubject / getBill / getNomination
  const bill = await reader.getSubject('118-hr-1234');
  assert(bill);
  assert.equal(bill.kind, 'bill');
  assert.equal(bill.short_title, 'Surface Transportation Modernization Act');
  assert.equal(bill.cbo_estimates.length, 1);
  assert.equal(bill.votes.length, 1);
  assert.equal(bill.votes[0].basis,'vote_record');
  assert.equal(bill.amendment_count, 1);
  assert.equal(bill.hearings.length, 1);
  assert.equal(bill.documents.length, 1);
  assert.deepEqual(await reader.getBill('118-hr-1234'),bill);

  const nom = await reader.getSubject('118-pn-730-2');
  assert(nom);
  assert.equal(nom.kind, 'nomination');
  assert.equal(nom.nomination_id,'118-pn-730-2');
  assert.equal(nom.description,'Jane Doe, to be Administrator.');
  assert.equal(nom.organization,'Department of Transportation');
  assert.deepEqual(nom.committees,[]);
  assert.equal(nom.committee_activities,null);
  assert.equal(formatSubject(nom.nomination_id,nom),'PN730-2');
  // Missing structured nominee data remains unknown, distinct from a valid empty list.
  assert.equal(nom.nominees,null);
  assert.equal(nom.votes.length, 1);
  assert.equal(nom.hearings.length, 1);
  assert.deepEqual(await reader.getNomination('118-pn-730-2'),nom);

  // openDocument returns the document entry and its joined entities.
  const opened = await reader.openDocument(0);
  assert.equal(opened.document.filename, 'Agenda.pdf');
  assert.equal(opened.meetings.length, 1);
  assert.equal(opened.committees.length, 2);
  assert.equal(opened.subjects.length, 2);
  assert.equal(opened.witnesses.length, 2);
  assert.equal(opened.members.length, 1);

  // listEntities supports listing and filtering
  assert.equal((await reader.listEntities('witnesses', {text: 'transit'})).total, 1);
  assert.equal((await reader.listEntities('subjects', {congress: 118})).total, 2);
});
