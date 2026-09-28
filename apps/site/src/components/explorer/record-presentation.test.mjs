import test from 'node:test';
import assert from 'node:assert/strict';
import { committeeTypeLabel, documentSourceLabel, presentRecord, recordingEmbedUrl, recordingVisible } from './record-presentation.js';
import { matches } from './query-utils.js';

const now = new Date('2026-09-27T15:00:00Z');
const meeting = {kind: 'meeting', status: 'scheduled', date: '2026-09-27', evidence_states: {recording: 'reported', captions: 'inferred', documents: 'reported'}};
const recording = {kind: 'material', type: 'recording', recording_url: 'https://example.org/player', meeting_status: 'scheduled', files: [{url: 'https://example.org/player'}]};

test('supported YouTube and Senate recordings embed without autoplay', () => {
  for (const url of ['https://www.youtube.com/watch?v=PRXQf-CSnoo&t=0', 'https://youtu.be/PRXQf-CSnoo', 'https://www.youtube.com/embed/PRXQf-CSnoo', 'https://m.youtube.com/shorts/PRXQf-CSnoo', 'https://www.youtube.com/live/PRXQf-CSnoo']) {
    assert.equal(recordingEmbedUrl({...recording, recording_url: url}, now), 'https://www.youtube.com/embed/PRXQf-CSnoo');
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
  assert.equal(documentSourceLabel({}), '');
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
  assert.equal(committeeTypeLabel(child), 'Standing (inherited from parent)');
  assert.equal(child.source_committee_type, 'Subcommittee');
  assert.equal(committeeTypeLabel({...child, committee_type:'task_force'}), 'Task force');
  assert.equal(committeeTypeLabel({...child, committee_type:'unknown'}), 'Standing (inherited from parent)');
  assert.equal(committeeTypeLabel({...child, committee_types:['unknown']}), 'Type unrecorded');
  assert.equal(committeeTypeLabel({...child, committee_types:undefined}), 'Type unrecorded');
  assert.equal(committeeTypeLabel({committee_type:'unknown', committee_level:'full', committee_types:['standing']}), 'Type unrecorded');
});
