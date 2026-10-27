import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {browserDependency} from './archive-browser.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {argumentsMap} from './archive-targets.mjs';
const args=argumentsMap(process.argv.slice(2));
const server=await startArchiveServer({release:args.release,siteDist:args.dist||'dist'});
const {chromium}=browserDependency('playwright'),browser=await chromium.launch({headless:true,executablePath:args['browser-executable']});
try{
  const page=await browser.newPage();await page.goto(server.pageUrl);
  const bundle=await build({entryPoints:[new URL('../src/components/explorer/archive/saved-tab.ts',import.meta.url).pathname],bundle:true,format:'iife',globalName:'ArchiveSaved',write:false});await page.addScriptTag({content:bundle.outputFiles[0].text});
  await page.evaluate(()=>{localStorage.setItem('archive-fixture-sentinel','unchanged');const button=document.createElement('button');button.id='hostile-saved-fixture';button.textContent='Open hostile saved fixture';button.onclick=()=>{const tab=window.open('about:blank','_blank');window.ArchiveSaved.openSavedBlob(tab,new Blob([`<h1>Archived page</h1><script>parent.localStorage.setItem('archive-fixture-sentinel','changed'); parent.document.body.dataset.compromised='yes';<\/script><img src="/unexpected-raw-subresource">`],{type:'text/html'}));};document.body.append(button);});
  const popupPromise=page.waitForEvent('popup');await page.locator('#hostile-saved-fixture').click();const popup=await popupPromise;
  await popup.locator('iframe[sandbox]').waitFor();const frame=popup.frames().find(frame=>frame!==popup.mainFrame());await frame.waitForSelector('h1');
  assert.equal(await popup.evaluate(()=>opener),null);
  assert.equal(await popup.locator('iframe').getAttribute('sandbox'),'');
  assert.equal(await page.evaluate(()=>localStorage.getItem('archive-fixture-sentinel')),'unchanged');assert.equal(await popup.evaluate(()=>document.body.dataset.compromised),undefined);
  assert(!server.state.requests.some(item=>item.path==='/unexpected-raw-subresource'));
  console.log(JSON.stringify({status:'passed',operation:'saved HTML remains in a sandboxed opaque frame with subresources blocked'}));await popup.close();
}finally{await browser.close();await server.close();}
