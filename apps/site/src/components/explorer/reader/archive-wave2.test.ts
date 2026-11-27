import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {openArchive} from './archive.ts';
import {createArchiveEntities} from './archive-entities.ts';
import {SPICYENGINE_SEARCH_ORIGIN} from '../archive/search-config.ts';
import {extractLinkKeyFromHitId, readSpicySection, searchSpicyPassages} from '../archive/spicy-search.ts';
import {
  deltaTrackBillUrl,
  spicyGovBillUrl,
  spicyGovHearingUrl,
  spicyGovOrganizationUrl,
} from '../archive/archive-metadata.ts';

const CURRENT_FIXTURE = resolve(process.cwd(), '../../model/fixtures/archive-contract/current');

function fixtureFetcher(root: string) {
  return async (url: string, init: RequestInit = {}) => {
    const u = new URL(url);
    const rel = u.pathname.replace(/^\/viewer-publications\/(?:releases\/[0-9a-f]{64}\/)?/, '');
    const data = await readFile(resolve(root, rel));
    const rangeHeader = (init.headers as Record<string, string> | undefined)?.Range;
    if (rangeHeader) {
      const match = /^bytes=(\d+)-(\d+)$/.exec(rangeHeader);
      if (!match) return new Response(null, {status: 416});
      const start = Number(match[1]);
      const end = Math.min(data.byteLength - 1, Number(match[2]));
      return new Response(data.subarray(start, end + 1), {
        status: 206,
        headers: {'Content-Range': `bytes ${start}-${end}/${data.byteLength}`},
      });
    }
    return new Response(data, {status: 200});
  };
}

test('Wave 2 accountability reads live Parquet fixture (removed_on, retired_links, recoveries, multi-edition)', async () => {
  const reader = await openArchive('https://archive.test/viewer-publications/manifest.json', {
    fetcher: fixtureFetcher(CURRENT_FIXTURE),
  });
  const all = await reader.accountability({kind: 'all', limit: 100});
  assert.equal(all.releaseId, reader.releaseId);
  assert.equal(all.availability.recoveries, 'ready');
  assert(all.counts.recoveredOnly >= 1, 'Expected recovered-only fixture rows');
  assert(all.counts.multiEdition >= 1, 'Expected multi-edition fixture rows');

  const recovered = await reader.accountability({kind: 'recovered'});
  assert(recovered.rows.every((r: any) => r.churn_kind === 'recovered_only'));

  const multi = await reader.accountability({kind: 'multi_edition'});
  assert(multi.rows.length >= 1 && multi.rows.every((r: any) => r.edition_count > 0));

  const notes = await reader.accountability({kind: 'identity_notes'});
  assert(notes.rows.every((r: any) => Array.isArray(r.recoveries) && r.recoveries.some((rec: any) => Boolean(rec.identity_note))));
});

test('Wave 2 topOrganizationsByTopic ranks linked testifying organizations and respects unavailable releases', async () => {
  const docs = [
    {list_row: 0, title: 'AI Safety Hearing Testimony', filename: 'ai.pdf', hidden: false, congress: 119, witness_keys: ['wk-1'], meeting_keys: ['119001'], measure_keys: []},
    {list_row: 1, title: 'Agricultural Subsidies', filename: 'ag.pdf', hidden: false, congress: 119, witness_keys: ['wk-2'], meeting_keys: ['119002'], measure_keys: []},
  ];
  const tables: Record<string, any[]> = {
    organizations: [
      {org_id: 'org-ai', display_name: 'AI Policy Lab', kind: 'research', taxonomy_parent: 'research', taxonomy_category: 'think_tank', appearance_count: 5},
      {org_id: 'org-ag', display_name: 'Farm Coalition', kind: 'advocacy', taxonomy_parent: 'advocacy', taxonomy_category: 'trade', appearance_count: 3},
    ],
    organization_ids: [{org_id: 'org-ai', scheme: 'wikidata', value: 'Q12345'}],
    witness_organizations: [
      {witness_key: 'wk-1', org_id: 'org-ai', field: 'organization', raw_text: 'AI Policy Lab', event_id: '119001'},
      {witness_key: 'wk-2', org_id: 'org-ag', field: 'organization', raw_text: 'Farm Coalition', event_id: '119002'},
    ],
    witnesses: [
      {witness_key: 'wk-1', name: 'Dr. Ada Lovelace', event_id: 119001, list_rows: [0]},
      {witness_key: 'wk-2', name: 'Bob Farmer', event_id: 119002, list_rows: [1]},
    ],
    meetings: [
      {event_id: 119001, title: 'Artificial Intelligence Oversight', congress: 119, witness_keys: ['wk-1'], list_rows: [0]},
      {event_id: 119002, title: 'Farm Bill Markup', congress: 119, witness_keys: ['wk-2'], list_rows: [1]},
    ],
  };
  const entityStore = createArchiveEntities({
    count: docs.length,
    files: new Map(Object.keys(tables).map(n => [n + '.parquet', {}])),
    columns: new Map(['meeting_keys', 'witness_keys', 'congress', 'committee_keys'].map(c => [c, {}])),
    row: i => docs[i],
    value: (col, i) => (docs[i] as any)?.[col] ?? null,
    entity: async name => tables[name] ?? [],
    resolve: async () => null,
    entry: async () => null,
    versions: async () => [],
  });
  const top = await entityStore.topOrganizationsByTopic({topic: 'artificial intelligence'});
  assert.equal(top.state, 'ready');
  assert.equal(top.rows.length, 1);
  assert.equal(top.rows[0].org_id, 'org-ai');
  assert.equal(top.rows[0].matching_appearances, 1);

  const legacyStore = createArchiveEntities({
    count: docs.length,
    files: new Map([['meetings.parquet', {}]]),
    columns: new Map([['witness_keys', {}]]),
    row: i => docs[i],
    value: (col, i) => (docs[i] as any)?.[col] ?? null,
    entity: async () => [],
    resolve: async () => null,
    entry: async () => null,
    versions: async () => [],
  });
  const missing = await legacyStore.topOrganizationsByTopic({topic: 'artificial intelligence'});
  assert.equal(missing.state, 'unavailable');
});

test('Wave 2 SpicyEngine passage search parses hits, detects release mismatch, and handles CORS/network errors honestly', async () => {
  assert.equal(SPICYENGINE_SEARCH_ORIGIN, 'https://spicyengine.45.55.61.191.sslip.io');
  assert.equal(extractLinkKeyFromHitId('archive-documents:446d4dbc5406d389'), '446d4dbc5406d389');

  const releaseId = 'efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c';
  const okRes = await searchSpicyPassages('appropriations', {
    expectedReleaseId: releaseId,
    fetcher: async (url, init) => {
      assert.equal(url, `${SPICYENGINE_SEARCH_ORIGIN}/v1/search`);
      assert.equal(init?.method, 'POST');
      return new Response(JSON.stringify({
        query: 'appropriations',
        mode: 'hybrid',
        release_id: releaseId,
        total: 1,
        hasMore: false,
        tookMs: 42,
        results: [{
          id: 'archive-documents:446d4dbc5406d389',
          title: 'FY 2026 Appropriations Testimony',
          url: '/page?id=archive-documents%3A446d4dbc5406d389&page=5',
          crumb: 'Page 5',
          kind: 'text',
          snippet: 'appropriations snippet',
          publisher_url: 'https://www.govinfo.gov/app/details/CHRG-119hhrg1',
        }],
      }), {status: 200});
    },
  });
  assert.equal(okRes.state, 'ready');
  assert.equal(okRes.releaseMismatch, false);
  assert.equal(okRes.results[0].linkKey, '446d4dbc5406d389');
  assert.equal(okRes.results[0].url, `${SPICYENGINE_SEARCH_ORIGIN}/page?id=archive-documents%3A446d4dbc5406d389&page=5`);

  const emptyRes = await searchSpicyPassages('zzzznothing', {
    expectedReleaseId: releaseId,
    fetcher: async () => new Response(JSON.stringify({
      query: 'zzzznothing',
      mode: 'hybrid',
      release_id: 'a'.repeat(64),
      results: [],
    }), {status: 200}),
  });
  assert.equal(emptyRes.state, 'ready');
  assert.equal(emptyRes.results.length, 0);
  assert.equal(emptyRes.releaseMismatch, true);

  const corsErr = await searchSpicyPassages('testimony', {
    fetcher: async () => { throw new TypeError('Failed to fetch'); },
  });
  assert.equal(corsErr.state, 'unavailable');
  assert.match(corsErr.reason ?? '', /Failed to fetch/);

  const sec = await readSpicySection(`${SPICYENGINE_SEARCH_ORIGIN}/page?id=archive-documents%3A446d4dbc5406d389`, {
    fetcher: async () => new Response(JSON.stringify({content: 'Full passage text', title: 'Doc'}), {status: 200}),
  });
  assert.equal(sec.state, 'ready');
  assert.equal(sec.content, 'Full passage text');
});

test('Wave 2 cross-branch deep links target SpicyGov and DeltaTrack cleanly without linking nominations to DeltaTrack', () => {
  const orgUrl = spicyGovOrganizationUrl({
    org_id: 'e5b88f10d3d5a5ea',
    display_name: 'Environmental Protection Agency',
    organization_ids: [{scheme: 'wikidata', value: 'Q460173'}, {scheme: 'fr_agency', value: '145'}],
  });
  assert.match(orgUrl ?? '', /^https:\/\/spicygov\.ai\/\?/);
  assert.match(orgUrl ?? '', /wikidata=Q460173/);
  assert.match(orgUrl ?? '', /fr_agency=145/);

  assert.match(spicyGovHearingUrl({event_id: 118001}) ?? '', /^https:\/\/spicygov\.ai\/\?q=118001$/);
  assert.match(spicyGovBillUrl('119-hr-475') ?? '', /^https:\/\/spicygov\.ai\/\?q=H\.R\.%20475$/);
  assert.equal(spicyGovBillUrl('119-pn-730-2'), null);
  assert.match(deltaTrackBillUrl('119-hr-475') ?? '', /^https:\/\/civictechdc\.github\.io\/DeltaTrack\/\?bill=119-hr-475$/);
  assert.equal(deltaTrackBillUrl('119-pn-730-2'), null);
});
