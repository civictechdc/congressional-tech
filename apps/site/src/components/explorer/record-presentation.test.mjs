import test from 'node:test';
import assert from 'node:assert/strict';
import { presentRecord, recordingVisible } from './record-presentation.js';

const now = new Date('2026-09-27T15:00:00Z');
const meeting = {kind: 'meeting', status: 'scheduled', date: '2026-09-27', evidence_states: {recording: 'reported', captions: 'inferred', documents: 'reported'}};
const recording = {kind: 'material', type: 'recording', recording_url: 'https://example.org/player', meeting_status: 'scheduled', files: [{url: 'https://example.org/player'}]};

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
