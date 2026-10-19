// Exercise the actual bundled bootstrap and UI under the deployed Pages prefix.
// Network/catalog correctness belongs to the maintained worker/reader tests.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve, sep} from 'node:path';
import {SourceTextModule} from 'node:vm';
import {test} from 'node:test';
import {JSDOM} from 'jsdom';

for (const pinned of [false,true]) test(`built filename page runs its real bootstrap${pinned ? ' with a pinned deep link' : ''} at the Pages base path`, async () => {
  const root = resolve('dist');
  const base = 'https://civictechdc.github.io/congressional-tech/';
  const catalog='a'.repeat(32);
  const dom = new JSDOM(await readFile(resolve(root, 'filenames/index.html'), 'utf8'), {
    url: base + 'filenames/' + (pinned ? '?source=deep-source&catalog='+catalog : ''), runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const requests = [], workers = [], modules = new Map();
  const window = dom.window;
  window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  window.HTMLDialogElement.prototype.close=function(){this.open=false;};
  const record={source_id:'deep-source',filename:'Recorded.pdf',source_url:'https://committee.test/recorded.pdf',body_key:null,format:['pdf']};
  const origin={file_url:record.source_url,pages:[],redirects:[],recovered_urls:[]};
  window.fetch = async () => { throw new Error('Unexpected network request in built-page smoke test'); };
  window.Worker = class {
    constructor(url) { workers.push(String(url)); }
    postMessage(request) {
      if (request.cancel) return;
      requests.push(request);
      const result = request.url === '/api/info'
        ? {catalog_id: catalog, rows: 0, documents: 0, capture_records: 0, fields: ['filename','source_url','source_id'],
          facets: {congress: [], document_kind: [], document_family: [], format: []}}
        : request.url.startsWith('/api/entry/') ? {record,document:record,filename:record.filename,catalog_id:catalog,published_only:true,record_complete:false,sources:[record],origin,document_origin:origin,saved_file_available:false}
        : {rows: [], total: 0, page: 1, pages: 1, limit: 100};
      queueMicrotask(() => this.onmessage?.({data: {id: request.id, result}}));
    }
    terminate() {}
  };
  window.HTMLElement.prototype.scrollIntoView = function() {};
  async function load(url) {
    if (modules.has(url)) return modules.get(url);
    assert.ok(url.startsWith(base), `Bundle escaped Pages base: ${url}`);
    const path = resolve(root, new URL(url).pathname.slice(new URL(base).pathname.length));
    assert.ok(path.startsWith(root + sep), 'Bundle must remain inside dist');
    const module = new SourceTextModule(await readFile(path, 'utf8'), {
      context: dom.getInternalVMContext(), identifier: url,
      initializeImportMeta(meta) { meta.url = url; },
      importModuleDynamically: async (name, parent) => {
        const child = await load(new URL(name, parent.identifier).href);
        if (child.status === 'linked') await child.evaluate();
        return child;
      },
    });
    modules.set(url, module);
    await module.link((name, parent) => load(new URL(name, parent.identifier).href));
    return module;
  }
  try {
    const scripts = [...window.document.querySelectorAll('script[type="module"][src]')];
    assert.ok(scripts.length, 'Built page must include its module bootstrap');
    for (const script of scripts) await (await load(script.src)).evaluate();
    for (let attempt = 0; attempt < 30 && !requests.some(r => r.url.startsWith('/api/rows')); attempt++) {
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert.equal(workers.length, 1);
    assert.ok(workers[0].startsWith(base + '_astro/filename-worker'));
    assert.ok(requests.some(r => r.url === '/api/info'));
    assert.ok(requests.some(r => r.url.startsWith('/api/rows')));
    assert.equal(window.document.getElementById('error').hidden, true);
    assert.ok(requests.every(r => r.reviewPublication.url.startsWith(base + 'data/document-reviews/')));
    assert.equal(typeof window.filenameViewerApi, 'function');
    assert.equal(window.document.body.dataset.filenameMode,'published');
    assert.equal(requests[0].snapshot,pinned?catalog:null);
    assert.ok(requests.slice(1).every(request=>request.snapshot===catalog),'accepted info pins all later requests');
    if(pinned) {
      assert.ok(requests.some(request=>request.url==='/api/entry/deep-source?catalog='+catalog));
      assert.equal(window.document.getElementById('detail').dataset.row,'deep-source');
      assert.equal(window.document.getElementById('detail').dataset.catalog,catalog);
      assert.ok(!requests.some(request=>request.url.startsWith('/api/full/')||request.url.startsWith('/api/evidence/')));
    }
  } finally {
    window.dispatchEvent(new window.Event('pagehide'));
    dom.window.close();
  }
});
