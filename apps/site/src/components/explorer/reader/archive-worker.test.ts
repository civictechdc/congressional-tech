import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import test from 'node:test';
import {ArchiveReleaseChangedError} from './cache.ts';

test('the worker keeps the selected document and sibling rows when optional display details fail', async () => {
  const hook = registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier === './archive.ts' && context.parentURL?.endsWith('/archive-worker.ts')) {
        return {
          url: 'data:text/javascript,export async function openArchive(){return globalThis.fixtureReader}',
          shortCircuit: true,
        };
      }
      return nextResolve(specifier, context);
    },
  });
  const globals = globalThis as any;
  const document = {filename: 'agenda.pdf', title: 'Hearing agenda'};
  const source = {url: 'https://fixture.test/agenda.pdf'};
  const failedSibling = {list_row: 1, date_kind: 'import_day', title: 'Archived sibling'};
  const workingSibling = {list_row: 2, date_kind: 'import_day', title: 'Other version'};
  const entry = {
    detail: {in_archive_since: '2020-01-02', removed_on: null},
    sources: [{url: 'https://fixture.test/version.pdf'}],
    recoveries: [],
  };
  const responses: any[] = [];
  let loadSibling = async (_signal: AbortSignal) => entry;
  globals.self = {postMessage: (message: unknown) => responses.push(message)};
  globals.fixtureReader = {
    releaseId: 'fixture-release',
    async locate() { return {index: 0}; },
    async openDocument(index: number) {
      assert.equal(index, 0);
      return {document, detail: {}, sources: [source], recoveries: [], meetings: [],
        versions: [{...failedSibling}, {...workingSibling}]};
    },
    async entry(index: number, signal: AbortSignal) {
      return index === failedSibling.list_row ? loadSibling(signal) : entry;
    },
  };
  const open = (id: number) => globals.self.onmessage({data: {
    id, url: '/entry', pointerUrl: 'https://fixture.test/manifest.json', payload: {key: 'fixture'},
  }});

  try {
    await import('./archive-worker.ts');
    await open(1);
    assert.equal(responses.pop().result.versions[0].in_archive_since, '2020-01-02');

    loadSibling = async () => { throw new Error('Sibling detail could not be loaded'); };
    await open(2);
    const {result} = responses.pop();
    assert.deepEqual(result.entry.document, document);
    assert.deepEqual(result.entry.sources, [source]);
    assert.deepEqual(result.versions[0], failedSibling);
    assert.equal(result.versions[1].source_url, 'https://fixture.test/version.pdf');

    loadSibling = async () => { throw new ArchiveReleaseChangedError('Release changed'); };
    await open(3);
    assert.deepEqual(responses.pop(), {id: 3, error: 'Release changed'});

    let started!: () => void;
    const reading = new Promise<void>(resolve => { started = resolve; });
    loadSibling = signal => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), {once: true});
      started();
    });
    const pending = open(4);
    await reading;
    await globals.self.onmessage({data: {cancel: 4}});
    await pending;
    assert.deepEqual(responses, []);
  } finally {
    hook.deregister();
    delete globals.self;
    delete globals.fixtureReader;
  }
});
