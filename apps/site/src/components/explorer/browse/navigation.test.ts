import test from 'node:test';
import assert from 'node:assert/strict';
import { readNavigation, viewNavigation, drillNavigation } from './navigation.ts';
import { sourcePageUrl } from './record-presentation.ts';

test('chart drill-down preserves the counted population and reloadable chart settings', () => {
  const nav = readNavigation('?view=coverage&congress=119&type=business&chamber=senate&q=budget&from=2025-01-01&measure=recording&grouping=month&committeeLevel=full&access=closed&committeeType=standing', 119);
  const drilled = drillNavigation(nav, {month:'2025-01', aspect:'recording', evidence:'reported'});
  for (const key of ['type','chamber','q','from','measure','grouping','committeeLevel','committeeType','access']) assert.equal(drilled[key], nav[key]);
  assert.equal(drilled.month, '2025-01'); assert.equal(drilled.aspect, 'recording'); assert.equal(drilled.view, 'meetings');
  assert.deepEqual(readNavigation(new URLSearchParams(Object.entries(nav)), 119), nav);
  assert.equal(viewNavigation(drilled, 'coverage').type, 'business');
  for (const view of ['meetings', 'committees', 'materials', 'witnesses', 'coverage', 'gaps']) {
    assert.equal(viewNavigation(drilled, view).committeeLevel, 'full');
    assert.equal(viewNavigation(drilled, view).committeeType, 'standing');
    assert.equal(viewNavigation(drilled, view).access, ['meetings', 'coverage'].includes(view) ? 'closed' : '');
  }
});

test('workspace transitions retain compatible filters and remove meaningless filters', () => {
  const nav = readNavigation('?view=meetings&congress=119&type=business&from=2026-10-01&to=2026-10-02&month=2026-10&aspect=recording&evidence=reported',119);
  const committees = viewNavigation(nav, 'committees');
  for (const key of ['type','from','to','month','aspect','evidence']) assert.equal(committees[key], '');
  const materials = viewNavigation(nav, 'materials');
  assert.equal(materials.from, '2026-10-01'); assert.equal(materials.type, ''); assert.equal(materials.congress, '119');
});

test('material sorting survives reloads and clears on incompatible views', () => {
  const sorted = readNavigation('?view=materials&sort=record&direction=desc', 119);
  assert.equal(sorted.sort, 'record');
  assert.equal(sorted.direction, 'desc');
  assert.deepEqual(readNavigation(new URLSearchParams(Object.entries(sorted)), 119), sorted);
  assert.equal(viewNavigation(sorted, 'meetings').sort, '');
  assert.equal(viewNavigation(sorted, 'meetings').direction, '');
  assert.equal(readNavigation('?sort=nope', 119).direction, '');
  assert.equal(readNavigation('?view=meetings&sort=date&direction=desc', 119).sort, 'date');
  assert.equal(viewNavigation(readNavigation('?view=meetings&sort=date&direction=desc', 119), 'materials').sort, 'date');
});

test('malformed routing values recover to usable defaults', () => {
  for (const page of ['Infinity','NaN','-3','1e99']) assert.equal(readNavigation(`?page=${page}`,119).page,0);
  const nav = readNavigation('?view=missing&congress=garbage&measure=missing&grouping=missing&committeeLevel=missing&access=garbage',119);
  assert.equal(nav.view,'meetings'); assert.equal(nav.congress,'119');
  assert.equal(nav.measure,'transcript'); assert.equal(nav.grouping,'congress');
  assert.equal(nav.committeeLevel, '');
  assert.equal(nav.access, '');
  const issues = readNavigation('?view=gaps&category=conflicting&severity=informational', 119);
  assert.equal(issues.category, 'conflicting');
  assert.equal(issues.severity, 'informational');
  assert.equal(viewNavigation(issues, 'meetings').category, '');
  assert.equal(viewNavigation(issues, 'meetings').severity, '');
  assert.equal(readNavigation('?category=nope&severity=nope', 119).category, '');
  assert.equal(readNavigation('?category=nope&severity=nope', 119).severity, '');
  const documents = readNavigation('?view=materials&materialCategory=statement', 119);
  assert.equal(documents.materialCategory, 'statement');
  assert.equal(viewNavigation(documents, 'meetings').materialCategory, '');
  assert.equal(readNavigation('?materialCategory=hearing', 119).materialCategory, '');
  const witnesses = readNavigation('?view=witnesses&participation=testified', 119);
  assert.equal(witnesses.participation, 'testified');
  assert.equal(viewNavigation(witnesses, 'meetings').participation, '');
  assert.equal(readNavigation('?participation=attended', 119).participation, '');
  const canceled = readNavigation('?view=meetings&status=canceled', 119);
  assert.equal(canceled.status, 'canceled');
  assert.equal(viewNavigation(canceled, 'coverage').status, 'canceled');
  assert.equal(viewNavigation(canceled, 'witnesses').status, '');
  assert.equal(readNavigation('?view=meetings&status=open', 119).status, '');
  assert.equal(readNavigation('?view=gaps&status=open', 119).status, 'open');
  assert.equal(readNavigation('?view=gaps&status=canceled', 119).status, '');
  const youtube = readNavigation('?view=materials&provider=youtube', 119);
  assert.equal(youtube.provider, 'youtube');
  assert.equal(viewNavigation(youtube, 'meetings').provider, '');
  assert.equal(readNavigation('?provider=vimeo', 119).provider, '');
  const retained = readNavigation('?view=gaps&history=retained', 119);
  assert.equal(retained.history, 'retained');
  assert.equal(viewNavigation(retained, 'meetings').history, '');
  assert.equal(readNavigation('?view=meetings&history=retained', 119).history, '');
  assert.equal(readNavigation('?view=gaps&history=old', 119).history, '');
});

test('source links use public Congress event pages and preserve other source URLs', () => {
  assert.equal(sourcePageUrl('https://api.congress.gov/v3/committee-meeting/113/house/100240'), 'https://www.congress.gov/event/113th-congress/house-event/100240');
  assert.equal(sourcePageUrl('https://api.congress.gov/v3/committee-meeting/119/senate/123?format=json'), 'https://www.congress.gov/event/119th-congress/senate-event/123');
  assert.equal(sourcePageUrl('https://docs.house.gov/meeting/meetingdocs.aspx'), 'https://docs.house.gov/meeting/meetingdocs.aspx');
  assert.equal(sourcePageUrl(null), undefined);
});
