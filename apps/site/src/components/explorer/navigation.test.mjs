import test from 'node:test';
import assert from 'node:assert/strict';
import { readNavigation, viewNavigation, drillNavigation } from './navigation.js';
import { sourcePageUrl } from './record-presentation.js';

test('chart drill-down preserves the counted population and reloadable chart settings', () => {
  const nav = readNavigation('?view=coverage&congress=119&type=business&chamber=senate&q=budget&from=2025-01-01&measure=recording&grouping=month', 119);
  const drilled = drillNavigation(nav, {month:'2025-01', aspect:'recording', evidence:'reported'});
  for (const key of ['type','chamber','q','from','measure','grouping']) assert.equal(drilled[key], nav[key]);
  assert.equal(drilled.month, '2025-01'); assert.equal(drilled.aspect, 'recording'); assert.equal(drilled.view, 'meetings');
  assert.deepEqual(readNavigation(new URLSearchParams(Object.entries(nav)), 119), nav);
  assert.equal(viewNavigation(drilled, 'coverage').type, 'business');
});

test('workspace transitions retain compatible filters and remove meaningless filters', () => {
  const nav = readNavigation('?view=meetings&congress=119&type=business&from=2026-10-01&to=2026-10-02&month=2026-10&aspect=recording&evidence=reported',119);
  const committees = viewNavigation(nav, 'committees');
  for (const key of ['type','from','to','month','aspect','evidence']) assert.equal(committees[key], '');
  const materials = viewNavigation(nav, 'materials');
  assert.equal(materials.from, '2026-10-01'); assert.equal(materials.type, ''); assert.equal(materials.congress, '119');
});

test('malformed routing values recover to usable defaults', () => {
  for (const page of ['Infinity','NaN','-3','1e99']) assert.equal(readNavigation(`?page=${page}`,119).page,0);
  const nav = readNavigation('?view=missing&congress=garbage&measure=missing&grouping=missing',119);
  assert.equal(nav.view,'meetings'); assert.equal(nav.congress,'119');
  assert.equal(nav.measure,'transcript'); assert.equal(nav.grouping,'congress');
});

test('source links use public Congress event pages and preserve other source URLs', () => {
  assert.equal(sourcePageUrl('https://api.congress.gov/v3/committee-meeting/113/house/100240'), 'https://www.congress.gov/event/113th-congress/house-event/100240');
  assert.equal(sourcePageUrl('https://api.congress.gov/v3/committee-meeting/119/senate/123?format=json'), 'https://www.congress.gov/event/119th-congress/senate-event/123');
  assert.equal(sourcePageUrl('https://docs.house.gov/meeting/meetingdocs.aspx'), 'https://docs.house.gov/meeting/meetingdocs.aspx');
  assert.equal(sourcePageUrl(null), undefined);
});
