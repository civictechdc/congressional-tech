#!/usr/bin/env node
/**
 * One-shot migration: converts the legacy JSON content in
 * apps/website/src/data/ into Astro content-collection markdown under
 * apps/site/src/content/. After this runs, the markdown is the source of
 * truth (browsable directly on GitHub); the JSON is no longer authoritative.
 *
 * Usage: node scripts/migrate-content.mjs  (from apps/site/)
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(here, '..');
const dataDir = resolve(siteRoot, '../website/src/data');
const contentDir = join(siteRoot, 'src/content');

const REPO_BASE =
  'https://github.com/civictechdc/congressional-tech/tree/main';
const SITE_BASE = 'https://civictechdc.github.io/congressional-tech';

/**
 * Theme grouping for the 19 proposals, in proposals.json order. This mirrors
 * the categorized project list in the repo README (categories I–V): the first
 * 4 proposals are theme I, the next 5 theme II, then 5 in III and 5 in IV.
 * Theme V ("Basic Utility Tools") has no proposal entries — its only project
 * (the inflation calculator, V.1) is already built and lives in the projects
 * collection.
 */
const THEME_COUNTS = [
  ['I', 4],
  ['II', 5],
  ['III', 5],
  ['IV', 5],
];

/** Per-proposal repo links, keyed by proposal id. */
const PROPOSAL_REPOS = {
  'I.2': `${REPO_BASE}/apps/committee_youtube`,
};

/** Short human tags per theme (used for filter chips instead of numerals). */
const THEME_TAGS = {
  I: 'Data Access',
  II: 'Workflow',
  III: 'AI & Analysis',
  IV: 'Insights',
  V: 'Utilities',
};

async function readJson(name) {
  return JSON.parse(await readFile(join(dataDir, name), 'utf8'));
}

/** Quote a YAML string safely. */
function yaml(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'number') return String(value);
  return JSON.stringify(String(value));
}

function frontmatter(fields) {
  const lines = Object.entries(fields)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}: ${yaml(v)}`);
  return `---\n${lines.join('\n')}\n---`;
}

/**
 * Convert the JSON's newline/tab pseudo-structure into readable markdown.
 * - a single line stays a paragraph;
 * - a first line ending in ":" becomes an intro paragraph;
 * - every other line becomes a bullet, tab depth = list nesting;
 * - "Label: text" bullets get a bold label.
 */
function toMarkdown(text) {
  const lines = (text ?? '')
    .split('\n')
    .map((l) => l.replace(/\s+$/, ''))
    .filter((l) => l.trim() !== '');
  if (lines.length === 0) return '';
  if (lines.length === 1) return lines[0].trim();

  const out = [];
  let rest = lines;
  if (!lines[0].startsWith('\t') && lines[0].trim().endsWith(':')) {
    out.push(lines[0].trim(), '');
    rest = lines.slice(1);
  }
  for (const line of rest) {
    const depth = (line.match(/^\t+/)?.[0] ?? '').length;
    out.push(`${'  '.repeat(depth)}- ${boldLabel(line.trim())}`);
  }
  return out.join('\n');
}

/** Bold short "Label:" prefixes so scan-reading works on GitHub. */
function boldLabel(text) {
  const match = text.match(/^([^:.]{3,60}):\s+(.+)$/s);
  if (!match) return text;
  return `**${match[1]}:** ${match[2]}`;
}

async function write(relPath, body) {
  const file = join(contentDir, relPath);
  await mkdir(dirname(file), { recursive: true });
  await writeFile(file, `${body.trimEnd()}\n`, 'utf8');
  console.log(`wrote ${relPath}`);
}

const [themesJson, proposalsJson, activeJson] = await Promise.all([
  readJson('project-themes.json'),
  readJson('proposals.json'),
  readJson('active-projects.json'),
]);

// ---- themes/ ----
for (const [index, theme] of themesJson.entries()) {
  const body = [
    frontmatter({
      id: theme.id,
      title: theme.title,
      tag: THEME_TAGS[theme.id],
      order: index + 1,
      focus: theme.focus ?? null,
    }),
    '',
    theme.focus ?? '',
  ].join('\n');
  await write(`themes/${theme.id}.md`, body);
}

// ---- proposals/ ----
const themeForIndex = THEME_COUNTS.flatMap(([id, count]) =>
  Array.from({ length: count }, () => id),
);
if (themeForIndex.length !== proposalsJson.length) {
  throw new Error(
    `Theme map covers ${themeForIndex.length} proposals but proposals.json has ${proposalsJson.length}`,
  );
}
const builtIds = new Set(activeJson.map((p) => p.id));

const counters = {};
for (const [index, proposal] of proposalsJson.entries()) {
  const theme = themeForIndex[index];
  counters[theme] = (counters[theme] ?? 0) + 1;
  const id = `${theme}.${counters[theme]}`;
  const effort = proposal.level_of_effort?.trim();
  const sections = [
    frontmatter({
      id,
      title: proposal.title,
      theme,
      status: builtIds.has(id) ? 'built' : 'idea',
      effort: effort || undefined,
      repo: PROPOSAL_REPOS[id],
    }),
    '',
    proposal.description.trim(),
    '',
    '## Problem',
    '',
    toMarkdown(proposal.problem),
    '',
    '## Solution',
    '',
    toMarkdown(proposal.solution),
  ];
  await write(`proposals/${id}.md`, sections.join('\n'));
}

// ---- projects/ ----
const projectDetails = {
  'I.2': {
    theme: 'I',
    repo: `${REPO_BASE}/apps/committee_youtube`,
    body: [
      'Tracks every House and Senate committee YouTube channel and measures how',
      'consistently committees include official Event IDs in their video',
      'descriptions, so proceedings can be linked back to Congress.gov records.',
      '',
      `- **Source:** [\`apps/committee_youtube\`](${REPO_BASE}/apps/committee_youtube)`,
      `- **Live dashboard:** [${SITE_BASE}/dashboard/](${SITE_BASE}/dashboard/)`,
    ].join('\n'),
  },
  'V.1': {
    theme: 'V',
    repo: `${REPO_BASE}/apps/inflation_gsheets`,
    body: [
      'A Google Sheets template plus supporting scripts for quickly adjusting',
      'dollar amounts for inflation — a small utility built for congressional',
      'staff and researchers.',
      '',
      `- **Source:** [\`apps/inflation_gsheets\`](${REPO_BASE}/apps/inflation_gsheets)`,
    ].join('\n'),
  },
};

for (const project of activeJson) {
  const details = projectDetails[project.id];
  if (!details) throw new Error(`No project details mapped for ${project.id}`);
  const body = [
    frontmatter({
      id: project.id,
      title: project.title,
      theme: details.theme,
      status: 'built',
      description: project.description,
      repo: details.repo,
    }),
    '',
    project.description.trim() + '.',
    '',
    details.body,
  ].join('\n');
  await write(`projects/${project.id}.md`, body);
}

console.log('Migration complete.');
