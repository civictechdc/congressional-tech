/** Optional regex portability test, not a JavaScript JSON Schema validator test. */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const data = path.join(root, 'src/house_naming/data');
const load = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const cases = load(path.join(root, 'tests/records.json'));
let compiled = 0, positives = 0, negatives = 0;
function walk(value) {
  if (Array.isArray(value)) return value.forEach(walk);
  if (!value || typeof value !== 'object') return;
  if (typeof value.pattern === 'string') { new RegExp(value.pattern, 'u'); compiled++; }
  Object.values(value).forEach(walk);
}
for (const filename of fs.readdirSync(data)) {
  if (filename.endsWith('.schema.json')) walk(load(path.join(data, filename)));
}
const schema = load(path.join(data, 'filename-lexical.schema.json'));
for (const fixture of cases) {
  const definition = schema.$defs[fixture.input.kind];
  if (!definition) continue;
  const regex = new RegExp(definition.pattern, 'u');
  if (!regex.test(fixture.output)) throw new Error(`No match: ${fixture.output}`);
  positives++;
  if (regex.test(fixture.output + '\n')) throw new Error('Trailing newline accepted');
  negatives++;
}
console.log(JSON.stringify({node: process.version, unicodeRegexesCompiled: compiled,
  positiveFilenameChecks: positives, trailingNewlineRejections: negatives}, null, 2));
