#!/usr/bin/env node
// Real Chromium reads through the maintained loaders and local HTTP range/CORS.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {resolve, dirname, delimiter, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import os from 'node:os';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const options = {};
for (let i = 2; i < process.argv.length; i += 2) {
  if (!process.argv[i].startsWith('--') || process.argv[i + 1] === undefined) throw new Error('Arguments require --name value');
  options[process.argv[i].slice(2)] = process.argv[i + 1];
}
for (const name of ['publication', 'output', 'review-data']) if (!options[name]) throw new Error(`Missing --${name}`);
const output = resolve(options.output), repeats = Number(options.repeats || 5);
if (!Number.isInteger(repeats) || repeats < 2) throw new Error('Use at least two browser repetitions');
const modulePaths = (process.env.VIEWER_BENCHMARK_MODULES || '').split(delimiter).filter(Boolean).map(path => resolve(path));
const require = createRequire(import.meta.url);
function dependency(name) {
  for (const load of [require, ...modulePaths.map(path => createRequire(join(path, '__benchmark__.cjs')))]) {
    try { return load(name); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
  }
  throw new Error(`Missing ${name}; install the pinned browser benchmark tools and set VIEWER_BENCHMARK_MODULES (see browser-benchmark.md)`);
}
const hash = value => createHash('sha256').update(value).digest('hex');
async function bounded(promise, milliseconds) {
  let timer;
  try { return await Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('Browser case exceeded its time bound')), milliseconds);
  })]); } finally { clearTimeout(timer); }
}
const receipt = {version: 1, status: 'running', runtime: {node: process.version, platform: process.platform,
  architecture: process.arch, os_release: os.release()}, repetitions: repeats,
  cache_condition: 'new browser context each repetition; fresh catalog per case; fetch cache=no-store', samples: []};
let server, browser, config;
await mkdir(output, {recursive: false});
const save = () => writeFile(join(output, 'browser-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
try {
  const esbuild = dependency('esbuild'), {chromium} = dependency('playwright');
  receipt.runtime.esbuild = esbuild.version;
  receipt.runtime.playwright = dependency('playwright/package.json').version;
  const moduleNames = ['filename-catalog.mjs', 'filename-reviews.mjs', 'filename-recoveries.mjs',
    'filename-publication.mjs', 'filename-observations.mjs'];
  receipt.loader_hashes = Object.fromEntries(await Promise.all(moduleNames.map(async name =>
    [name, hash(await readFile(join(root, 'apps/site/src/components', name)))])));
  const bundle = join(output, 'browser-bundle.js');
  await esbuild.build({stdin: {contents: `export {createFilenameCatalog,savedCopyUrl} from './filename-catalog.mjs';
    export {loadReviews} from './filename-reviews.mjs'; export {loadPublication} from './filename-publication.mjs';
    export {loadRecoveries} from './filename-recoveries.mjs';`, resolveDir: join(root, 'apps/site/src/components')},
    bundle: true, format: 'iife', globalName: 'ViewerBenchmark', outfile: bundle, platform: 'browser', nodePaths: modulePaths, tsconfigRaw: {}});
  receipt.bundle_sha256 = hash(await readFile(bundle));
  const serverArgs = [join(root, 'scripts/viewer_benchmark_server.py'), '--publication', resolve(options.publication),
    '--output', output, '--bundle', bundle, '--review-data', resolve(options['review-data'])];
  for (const name of ['review-descriptor', 'review-identities', 'accepted', 'cases']) {
    if (options[name]) serverArgs.push('--' + name, resolve(options[name]));
  }
  server = spawn(options.python || join(root, '.venv/bin/python'), serverArgs, {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
  let serverErrors = '';
  server.stderr.on('data', chunk => { serverErrors += chunk; });
  config = await new Promise((accept, reject) => {
    const timeout = setTimeout(() => reject(new Error('Local input preparation timed out after 10 minutes')), 600000);
    const lines = createInterface({input: server.stdout});
    lines.once('line', line => { clearTimeout(timeout); try { accept(JSON.parse(line)); } catch (error) { reject(error); } });
    server.once('error', error => { clearTimeout(timeout); reject(error); });
    server.once('exit', code => { clearTimeout(timeout); reject(new Error(`Local server exited ${code}: ${serverErrors}`)); });
  });
  receipt.inputs = config;
  const launch = {headless: true};
  if (options['browser-executable']) launch.executablePath = resolve(options['browser-executable']);
  browser = await chromium.launch(launch);
  receipt.runtime.browser = browser.version();
  const cases = [...config.cases.cases, {id: 'reviews', operation: 'reviews'}, {id: 'recoveries', operation: 'recoveries'}];
  for (let repetition = 0; repetition < repeats; repetition++) {
    const context = await browser.newContext();
    // The page and data have different loopback hostnames, so Chromium enforces CORS.
    const page = await context.newPage();
    page.setDefaultTimeout(Number(options['case-timeout-ms'] || 120000));
    await page.goto(config.page_url);
    for (const item of cases) {
      const measured = await bounded(page.evaluate(async ({config, item}) => {
        const api = window.ViewerBenchmark;
        let bytes = 0, requests = 0, ranges = 0;
        const fetcher = async (url, options = {}) => {
          const response = await fetch(url, {...options, cache: 'no-store'});
          requests++;
          bytes += Number(response.headers.get('Content-Length') || 0);
          if (options.headers?.Range) ranges++;
          return response;
        };
        const descriptor = {...config.review_descriptor, url: config.review_url};
        const reader = item.operation === 'initialize' ? null :
          await api.createFilenameCatalog(config.data_url, fetcher, config.catalog_id, descriptor);
        if (reader?.info.review_error) throw new Error(reader.info.review_error);
        bytes = 0; requests = 0; ranges = 0;
        const started = performance.now();
        const identity = item.source_id || String(item.row);
        let result;
        if (item.operation === 'initialize') {
          const loaded = await api.createFilenameCatalog(config.data_url, fetcher, config.catalog_id, descriptor);
          if (loaded.info.review_error) throw new Error(loaded.info.review_error);
          result = {catalog_id: loaded.info.catalog_id, rows: loaded.info.rows, entries: loaded.info.entries,
            review_sha256: loaded.info.review_sha256, reviewed_groups: loaded.info.reviewed_groups};
        } else if (item.operation === 'search') result = await reader.search(item.query);
        else if (item.operation === 'detail') result = await reader.entry(identity, config.catalog_id);
        else if (item.operation === 'origin') result = await reader.entryOrigin(identity, config.catalog_id);
        else if (item.operation === 'observations') result = await reader.observationPage(identity, config.catalog_id, {limit: item.limit || 20});
        else if (item.operation === 'review') {
          result = await reader.review(identity, config.catalog_id);
          if (result.status === 'no_review') throw new Error('Pinned bound review did not load');
        } else if (item.operation === 'recovery') {
          const detail = await reader.entry(identity, config.catalog_id);
          result = {recovery: detail.record.recovery, url: api.savedCopyUrl(detail.record, detail.recovery, config.data_url)};
          if (!result.recovery || !result.url) throw new Error('Pinned recovery link did not load');
        } else if (item.operation === 'reviews') {
          const selected = await api.loadPublication(config.data_url, fetcher, config.catalog_id);
          const loaded = await api.loadReviews(descriptor, selected.manifest, fetcher, selected.url);
          if (loaded.info.review_error || !loaded.info.reviewed_search) throw new Error(loaded.info.review_error || 'Review loader did not activate');
          if (config.expected.bound_reviews != null && loaded.groups.size !== config.expected.bound_reviews) throw new Error('Bound review count changed');
          result = {groups: [...loaded.groups], sources: [...loaded.sources], info: loaded.info};
        } else if (item.operation === 'recoveries') {
          const selected = await api.loadPublication(config.data_url, fetcher, config.catalog_id);
          const loaded = await api.loadRecoveries(selected.recovery, selected.manifest.info, fetcher);
          if (loaded.sources.size !== config.expected.recovered_sources) throw new Error('Recovery count changed');
          result = {groups: [...loaded.groups], sources: [...loaded.sources]};
        } else throw new Error('Unknown browser case operation: ' + item.operation);
        const milliseconds = performance.now() - started;
        const canonical = value => typeof value === 'string' ? value.replace(/http:\/\/(?:localhost|127\.0\.0\.1):\d+/g, 'http://benchmark.local')
          .replace(/\/releases\/[a-f0-9]{32}\//g, '/releases/<release>/') :
          Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ?
            Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => [key, canonical(value)])) : value;
        const raw = new TextEncoder().encode(JSON.stringify(canonical(result)));
        const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(v => v.toString(16).padStart(2, '0')).join('');
        return {milliseconds, requests, bytes, ranges, result_sha256: digest, result_bytes: raw.length};
      }, {config, item}), Number(options['case-timeout-ms'] || 120000));
      receipt.samples.push({case_id: item.id, operation: item.operation, repetition, ...measured});
      await save();
    }
    await context.close();
  }
  receipt.cases = Object.fromEntries(cases.map(item => {
    const samples = receipt.samples.filter(sample => sample.case_id === item.id);
    const sorted = samples.map(sample => sample.milliseconds).sort((a, b) => a - b);
    if (new Set(samples.map(sample => sample.result_sha256)).size !== 1) throw new Error(`Nondeterministic browser output: ${item.id}`);
    return [item.id, {p95_milliseconds: sorted[Math.ceil(.95 * sorted.length) - 1],
      median_milliseconds: sorted[Math.floor(sorted.length / 2)], result_sha256: samples[0].result_sha256,
      samples: samples.length, operation: item.operation}];
  }));
  if (!receipt.samples.some(item => item.ranges > 0)) throw new Error('No actual byte-range reads occurred');
  receipt.status = 'complete';
} catch (error) {
  receipt.status = 'failed'; receipt.error = error.stack || String(error); process.exitCode = 1;
} finally {
  await browser?.close();
  server?.kill('SIGTERM');
  await save();
}
console.log(JSON.stringify({status: receipt.status, receipt: join(output, 'browser-receipt.json'), error: receipt.error}));
