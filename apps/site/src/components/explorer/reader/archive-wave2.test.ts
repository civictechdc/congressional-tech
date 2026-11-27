import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {build} from 'esbuild';
import {createRequire} from 'node:module';
import {openArchive} from './archive.ts';
import {createArchiveEntities} from './archive-entities.ts';
import {SPICYENGINE_SEARCH_ORIGIN} from '../archive/search-config.ts';
import {extractLinkKeyFromHitId, readSpicySection, searchSpicyPassages} from '../archive/spicy-search.ts';
import * as archiveMeta from '../archive/archive-metadata.ts';
import {buildAccountabilityFeedXml, parseReleaseNotes} from '../../../lib/archive-feed.ts';

async function loadCitableReceipt() {
  const result = await build({
    entryPoints: [resolve(process.cwd(), 'src/components/explorer/archive/CitableReceipt.tsx')],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    packages: 'external',
    write: false,
  });
  const mod = {exports: {} as any};
  const require = createRequire(import.meta.url);
  new Function('require', 'module', 'exports', result.outputFiles[0].text)(require, mod, mod.exports);
  return mod.exports as {buildCitableDuckDbSql: (props: any) => string};
}

const CURRENT_FIXTURE = resolve(process.cwd(), '../../model/fixtures/archive-contract/current');
const VENV_PYTHON = resolve(process.cwd(), '../../.venv/bin/python');

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

test('Wave 2 accountability reads live Parquet fixture, deduplicates identity_notes, and preserves review_removed metadata', async () => {
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

  const notes = await reader.accountability({kind: 'identity_notes', limit: 100});
  assert.equal(notes.total, all.counts.withIdentityNote);
  assert.equal(new Set(notes.rows.map((r: any) => r.list_row)).size, notes.rows.length);
  assert(notes.rows.every((r: any) => Array.isArray(r.recoveries) && r.recoveries.some((rec: any) => Boolean(rec.identity_note))));

  // Verify multi-churn document deduplication & review_removed review_note/review_decided_at against custom DuckDB-built parquet
  const dir = await mkdtemp(resolve(tmpdir(), 'ct-wave2-acc-'));
  try {
    const emptyFiles = await readFile(resolve(CURRENT_FIXTURE, 'manifest.json'), 'utf8').then(s => JSON.parse(s));
    execFileSync(VENV_PYTHON, ['-c', `
import duckdb, json, pathlib, hashlib
src = pathlib.Path(${JSON.stringify(CURRENT_FIXTURE)})
dst = pathlib.Path(${JSON.stringify(dir)})
db = duckdb.connect()
db.execute(f"""COPY (
  SELECT * EXCLUDE(file_row_number)
    REPLACE(
      CASE WHEN file_row_number = 0 THEN true ELSE false END AS hidden,
      CASE WHEN file_row_number = 1 THEN 'recovery' ELSE 'original' END AS saved_kind,
      CASE WHEN file_row_number = 1 THEN ['ed-1', 'ed-2'] ELSE []::VARCHAR[] END AS version_keys
    )
  FROM read_parquet('{src}/list.parquet', file_row_number=true)
  WHERE file_row_number < 2
) TO '{dst}/list.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT * EXCLUDE(file_row_number)
    REPLACE(
      CASE WHEN file_row_number = 1 THEN DATE '2025-03-10' ELSE NULL::DATE END AS removed_on,
      CASE WHEN file_row_number = 0 THEN 'Superseded complete record' ELSE NULL::VARCHAR END AS review_note,
      CASE WHEN file_row_number = 0 THEN DATE '2025-02-02' ELSE NULL::DATE END AS review_decided_at,
      0 AS src_start, 0 AS src_len,
      0 AS rec_start,
      CASE WHEN file_row_number = 1 THEN 1 ELSE 0 END AS rec_len
    )
  FROM read_parquet('{src}/detail.parquet', file_row_number=true)
  WHERE file_row_number < 2
) TO '{dst}/detail.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT link_key, list_row FROM read_parquet('{src}/links.parquet') WHERE list_row < 2
) TO '{dst}/links.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT * FROM read_parquet('{src}/urls.parquet') WHERE list_row < 2
) TO '{dst}/urls.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT * FROM read_parquet('{src}/sources.parquet') WHERE false
) TO '{dst}/sources.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT 1 AS list_row, 'recovered_document' AS kind, saved_body AS body, '.gz' AS suffix,
         CAST(100 AS BIGINT) AS bytes, 'https://recovered.test/doc.pdf' AS recovered_url,
         TIMESTAMP '2025-03-01 00:00:00' AS imported_at, 'Committee index identifies this statement' AS identity_note
  FROM read_parquet('{dst}/detail.parquet', file_row_number=true)
  WHERE file_row_number = 1
) TO '{dst}/recoveries.parquet' (FORMAT PARQUET)""")
db.execute(f"""COPY (
  SELECT * FROM read_parquet('{src}/url_state.parquet') WHERE false
) TO '{dst}/url_state.parquet' (FORMAT PARQUET)""")
for extra in ('schema.json', 'capture_scope.json'):
    (dst / extra).write_bytes((src / extra).read_bytes())
src_manifest = json.loads((src / 'manifest.json').read_text())
files = []
for name in ('list.parquet','detail.parquet','links.parquet','urls.parquet','sources.parquet','recoveries.parquet','url_state.parquet','schema.json','capture_scope.json'):
    p = dst / name
    b = p.read_bytes()
    rows = db.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0] if name.endswith('.parquet') else 0
    files.append({'name': name, 'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b), 'rows': rows})
rel = hashlib.sha256(json.dumps([src_manifest['schema_version'], [[f['name'], f['sha256'], f['size'], f['rows']] for f in files]], separators=(',', ':')).encode()).hexdigest()
(dst / 'manifest.json').write_text(json.dumps({'schema_version': src_manifest['schema_version'], 'release_id': rel, 'files': files}))
`]);
    const customReader = await openArchive('https://archive.test/viewer-publications/manifest.json', {
      fetcher: fixtureFetcher(dir),
    });
    const customAll = await customReader.accountability({kind: 'all', limit: 20});
    assert.equal(customAll.counts.withIdentityNote, 1);
    const customNotes = await customReader.accountability({kind: 'identity_notes', limit: 20});
    assert.equal(customNotes.total, 1);
    assert.equal(customNotes.rows.length, 1);
    assert.equal(customNotes.rows[0].list_row, 1);

    const customRemoved = await customReader.accountability({kind: 'removed', limit: 20});
    const reviewRemoved = customRemoved.rows.find((r: any) => r.churn_kind === 'review_removed');
    assert(reviewRemoved, 'Expected review_removed row');
    assert.equal(reviewRemoved.review_note, 'Superseded complete record');
    assert.equal(reviewRemoved.review_decided_at, '2025-02-02');
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
});

test('Wave 2 CitableReceipt DuckDB SQL executes cleanly in real DuckDB against unsharded and sharded Parquet releases', async () => {
  const {buildCitableDuckDbSql} = await loadCitableReceipt();
  const reader = await openArchive('https://archive.test/viewer-publications/manifest.json', {
    fetcher: fixtureFetcher(CURRENT_FIXTURE),
  });
  const docEntry = await reader.entry(0);
  assert.deepEqual(docEntry.detailShard, {name: 'detail.parquet', rowStart: 0});
  const linkKeyHex = Buffer.from(docEntry.detail.link_key).toString('hex');
  const expectedSha = Buffer.from(docEntry.detail.saved_body).toString('hex');

  const unshardedSql = buildCitableDuckDbSql({
    kind: 'document',
    releaseId: reader.releaseId,
    rawBase: 'https://congressional-data.spicygov.ai/',
    linkKey: linkKeyHex,
    detailFile: docEntry.detailShard.name,
    detailRowStart: docEntry.detailShard.rowStart,
  }).replaceAll(`https://congressional-data.spicygov.ai/viewer-publications/releases/${reader.releaseId}/`, `${CURRENT_FIXTURE}/`);

  const unshardedRows = JSON.parse(execFileSync(VENV_PYTHON, ['-c', `
import duckdb, json
db = duckdb.connect()
cur = db.execute(${JSON.stringify(unshardedSql)})
cols = [d[0] for d in cur.description]
print(json.dumps([dict(zip(cols, r)) for r in cur.fetchall()]))
`], {encoding: 'utf8'}));
  assert.equal(unshardedRows.length, 1);
  assert.equal(unshardedRows[0].list_row, 0);
  assert.equal(unshardedRows[0].link_key, linkKeyHex);
  assert.equal(unshardedRows[0].saved_body_sha256, expectedSha);

  // Sharded release test: split detail.parquet into detail-00000.parquet [0, 1) and detail-00001.parquet [1, N)
  const shardedDir = await mkdtemp(resolve(tmpdir(), 'ct-wave2-sharded-'));
  try {
    const manifestJson = JSON.parse(await readFile(resolve(CURRENT_FIXTURE, 'manifest.json'), 'utf8'));
    execFileSync(VENV_PYTHON, ['-c', `
import duckdb, json, pathlib, hashlib
import pyarrow.parquet as pq
src = pathlib.Path(${JSON.stringify(CURRENT_FIXTURE)})
dst = pathlib.Path(${JSON.stringify(shardedDir)})
for p in src.iterdir():
    if p.name not in ('detail.parquet', 'manifest.json') and p.is_file():
        (dst / p.name).write_bytes(p.read_bytes())
tbl = pq.read_table(src / 'detail.parquet')
total = tbl.num_rows
pq.write_table(tbl.slice(0, 1), dst / 'detail-00000.parquet')
pq.write_table(tbl.slice(1), dst / 'detail-00001.parquet')
manifest_json = json.loads((src / 'manifest.json').read_text())
files = []
for f in manifest_json['files']:
    if f['name'] == 'detail.parquet':
        for s_name, rng in [('detail-00000.parquet', [0, 1]), ('detail-00001.parquet', [1, total])]:
            b = (dst / s_name).read_bytes()
            files.append({'name': s_name, 'sha256': hashlib.sha256(b).hexdigest(), 'size': len(b), 'rows': rng[1] - rng[0], 'shard': 'detail', 'row_range': rng})
    else:
        files.append(f)
rel = hashlib.sha256(json.dumps([manifest_json['schema_version'], [[x['name'], x['sha256'], x['size'], x['rows']] for x in files]], separators=(',', ':')).encode()).hexdigest()
(dst / 'manifest.json').write_text(json.dumps({'schema_version': manifest_json['schema_version'], 'release_id': rel, 'files': files}))
`]);
    const shardedReader = await openArchive('https://archive.test/viewer-publications/manifest.json', {
      fetcher: fixtureFetcher(shardedDir),
    });
    const shardedEntry = await shardedReader.entry(1);
    assert.equal(shardedEntry.detailShard.name, 'detail-00001.parquet');
    assert.equal(shardedEntry.detailShard.rowStart, 1);
    const shardedLinkKey = Buffer.from(shardedEntry.detail.link_key).toString('hex');
    const shardedSql = buildCitableDuckDbSql({
      kind: 'document',
      releaseId: shardedReader.releaseId,
      rawBase: 'https://congressional-data.spicygov.ai/',
      linkKey: shardedLinkKey,
      detailFile: shardedEntry.detailShard.name,
      detailRowStart: shardedEntry.detailShard.rowStart,
    }).replaceAll(`https://congressional-data.spicygov.ai/viewer-publications/releases/${shardedReader.releaseId}/`, `${shardedDir}/`);

    const shardedRows = JSON.parse(execFileSync(VENV_PYTHON, ['-c', `
import duckdb, json
db = duckdb.connect()
cur = db.execute(${JSON.stringify(shardedSql)})
cols = [d[0] for d in cur.description]
print(json.dumps([dict(zip(cols, r)) for r in cur.fetchall()]))
`], {encoding: 'utf8'}));
    assert.equal(shardedRows.length, 1);
    assert.equal(shardedRows[0].list_row, 1);
    assert.equal(shardedRows[0].link_key, shardedLinkKey);
  } finally {
    await rm(shardedDir, {recursive: true, force: true});
  }
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

test('Wave 2 SpicyEngine passage search parses hits, clamps limit to 10, detects release mismatch, and handles CORS errors', async () => {
  assert.equal(SPICYENGINE_SEARCH_ORIGIN, 'https://spicyengine.45.55.61.191.sslip.io');
  assert.equal(extractLinkKeyFromHitId('archive-documents:446d4dbc5406d389'), '446d4dbc5406d389');

  const releaseId = 'efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c';
  let capturedBody: any = null;
  const okRes = await searchSpicyPassages('appropriations', {
    expectedReleaseId: releaseId,
    limit: 50,
    fetcher: async (url, init) => {
      assert.equal(url, `${SPICYENGINE_SEARCH_ORIGIN}/v1/search`);
      assert.equal(init?.method, 'POST');
      capturedBody = JSON.parse(String(init?.body));
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
  assert.equal(capturedBody.limit, 10);
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

test('Wave 2 cross-branch deep links use verified SpicyGov table+where params and omit unsupported URL parameters', () => {
  assert.equal('spicyGovOrganizationUrl' in archiveMeta, false);
  assert.equal('deltaTrackBillUrl' in archiveMeta, false);

  const hearingHref = archiveMeta.spicyGovHearingUrl({event_id: 118001});
  assert(hearingHref);
  const hearingUrl = new URL(hearingHref);
  assert.equal(hearingUrl.origin, 'https://spicygov.ai');
  assert.equal(hearingUrl.searchParams.get('table'), 'committee_meetings');
  assert.deepEqual(JSON.parse(hearingUrl.searchParams.get('where') ?? '[]'), [{column: 'event_id', value: '118001'}]);
  assert.equal(archiveMeta.spicyGovHearingUrl({title: 'Missing ID'}), null);

  const billHref = archiveMeta.spicyGovBillUrl('119-hr-475');
  assert(billHref);
  const billUrl = new URL(billHref);
  assert.equal(billUrl.origin, 'https://spicygov.ai');
  assert.equal(billUrl.searchParams.get('table'), 'congress_bills');
  assert.deepEqual(JSON.parse(billUrl.searchParams.get('where') ?? '[]'), [{column: 'bill_id', value: '119-hr-475'}]);
  assert.equal(archiveMeta.spicyGovBillUrl('119-pn-730-2'), null);
});

test('Wave 2 Atom feed builder and feed.xml.ts GET handler produce valid Atom XML without broken ?q= entry links', async () => {
  const sampleNote = [
    '# Release 2026-11-20',
    '- Release: `' + 'a'.repeat(64) + '`',
    '## Links',
    'Published 10 new documents & 2 retired links.',
    '',
    '| `list` | added | 10 | 10 |',
  ].join('\n');
  const olderNote = [
    '# Release 2026-11-10',
    '- Release: `' + 'b'.repeat(64) + '`',
    '## Links',
    'Initial release.',
  ].join('\n');

  const parsed = parseReleaseNotes({
    'docs/releases/2026-11-10-bbbbbbbbbbbb.md': olderNote,
    'docs/releases/2026-11-20-aaaaaaaaaaaa.md': sampleNote,
  });
  assert.deepEqual(parsed.map(e => e.shortId), ['aaaaaaaaaaaa', 'bbbbbbbbbbbb']);

  const xml = buildAccountabilityFeedXml({
    releaseFiles: {
      'docs/releases/2026-11-10-bbbbbbbbbbbb.md': olderNote,
      'docs/releases/2026-11-20-aaaaaaaaaaaa.md': sampleNote,
    },
    site: new URL('https://civictechdc.github.io'),
    baseUrl: '/custom-base/',
  });
  assert(xml.startsWith('<?xml version="1.0" encoding="utf-8"?>'));
  assert(xml.includes('<id>https://civictechdc.github.io/custom-base/archive/feed.xml</id>'));
  assert(xml.includes('href="https://civictechdc.github.io/custom-base/archive/?tab=accountability"'));
  assert(!xml.includes('&amp;q='));

  // Compile feed.xml.ts replacing Vite's import.meta.glob and invoke GET directly
  const feedPath = resolve(process.cwd(), 'src/pages/archive/feed.xml.ts');
  const source = await readFile(feedPath, 'utf8');
  const require = createRequire(import.meta.url);
  (globalThis as any).__FEED_IMPORT_META_ENV__ = {BASE_URL: '/congressional-tech'};
  const injectedSource = source.replace(
    /const releaseFiles =[\s\S]*?as Record<string, string>;/,
    `const releaseFiles = ${JSON.stringify({'docs/releases/2026-11-20-aaaaaaaaaaaa.md': sampleNote})};`,
  );
  const result = await build({
    stdin: {
      contents: injectedSource,
      resolveDir: resolve(process.cwd(), 'src/pages/archive'),
      loader: 'ts',
    },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    write: false,
    define: {'import.meta.env': 'globalThis.__FEED_IMPORT_META_ENV__'},
  });
  const mod = {exports: {} as any};
  new Function('require', 'module', 'exports', result.outputFiles[0].text)(require, mod, mod.exports);
  const res: Response = await mod.exports.GET({site: new URL('https://civictechdc.github.io')});
  assert.equal(res.headers.get('Content-Type'), 'application/atom+xml; charset=utf-8');
  const body = await res.text();
  assert(body.includes('<feed xmlns="http://www.w3.org/2005/Atom">'));
  assert(body.includes('href="https://civictechdc.github.io/congressional-tech/archive/?tab=accountability"'));
  assert(!body.includes('&amp;q='));
  assert(body.includes('&amp; 2 retired links.'));
});
