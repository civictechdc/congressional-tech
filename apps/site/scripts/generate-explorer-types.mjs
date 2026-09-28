import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { delimiter, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { compile } from 'json-schema-to-typescript';

const root = fileURLToPath(new URL('../../../', import.meta.url));
const source = resolve(root, 'packages/committee_meeting/src');
const localPython = resolve(root, '.venv/bin/python');
const python = process.env.COMMITTEE_PYTHON || (existsSync(localPython) ? localPython : 'python3');
const schema = JSON.parse(execFileSync(python, ['-m', 'committee_meeting.main'], {
  cwd: root,
  env: { ...process.env, PYTHONPATH: [source, process.env.PYTHONPATH].filter(Boolean).join(delimiter) },
  encoding: 'utf8',
  maxBuffer: 16 * 1024 * 1024,
}));
const types = await compile(schema, 'Catalog', {
  bannerComment: '/** Generated from committee_meeting.Catalog. Do not edit. Run npm run generate:explorer-types. */',
  style: { singleQuote: true, printWidth: 100 },
});
const target = fileURLToPath(new URL('../src/components/explorer/catalog.generated.d.ts', import.meta.url));
if (process.argv.includes('--check')) {
  if (!existsSync(target) || readFileSync(target, 'utf8') !== types) {
    throw new Error('Explorer types differ from the Python model. Run npm run generate:explorer-types.');
  }
  console.log('Explorer types match committee_meeting.Catalog.');
} else {
  writeFileSync(target, types);
  console.log(`Generated ${target}`);
}
