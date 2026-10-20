import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';

test('explicit shared markup preserves accessible controls and local script/style order',async()=>{
 const root=new URL('../../../../../docs/youtube-coverage/research/',import.meta.url);
 const shell=await readFile(new URL('filename-viewer.html',root),'utf8'),body=await readFile(new URL('filename-viewer-body.html',root),'utf8');
 assert.equal(shell.split('<!-- filename-viewer:body -->').length,2);
 const dom=new JSDOM(shell.replace('<!-- filename-viewer:body -->',body));
 try {
  const doc=dom.window.document;
  for(const id of ['q','field','retry','detail','close-detail','source-link','saved-link','copy','share'])assert(doc.getElementById(id));
  assert.equal(doc.querySelector('body').dataset.filenameMode,'local');
  assert.equal(doc.querySelector('head link[rel="stylesheet"]').getAttribute('href'),'/filename-viewer.css');
  assert.equal(doc.querySelector('body').lastElementChild.getAttribute('src'),'/filename-viewer.mjs');
  assert.equal(doc.getElementById('detail').getAttribute('aria-labelledby'),'detail-title');
 } finally {dom.window.close();}
 const astro=await readFile(new URL('../../pages/filenames.astro',import.meta.url),'utf8');
 assert(astro.includes('filename-viewer-body.html?raw'));assert(astro.includes('filename-viewer.css?raw'));assert(!astro.includes('.match('));
 assert(astro.includes('data-filename-mode="published"'));
});
