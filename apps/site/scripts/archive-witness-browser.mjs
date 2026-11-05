/** Built-site check: /witness/<earlier key> through witness_key_map (ct-kb4w).
 * --release names a release with witness_key_map.parquet; --cases a JSON file
 * {live:{key,name},redirect:{key},ambiguous:{key,candidates},unresolved:{key}}
 * (default <release>/witness-map-expected.json); --screenshots a folder to write
 * one PNG per case. */
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {browserDependency,routeArchiveOrigin} from './archive-browser.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {argumentsMap} from './archive-targets.mjs';
const args=argumentsMap(process.argv.slice(2));
const cases=JSON.parse(await readFile(args.cases||join(args.release,'witness-map-expected.json')));
const server=await startArchiveServer({release:resolve(args.release),siteDist:resolve(args.dist||'dist')});
const {chromium}=browserDependency('playwright');
const browser=await chromium.launch({headless:true,...(args['browser-executable']?{executablePath:args['browser-executable']}:{})});
if(args.screenshots)await mkdir(args.screenshots,{recursive:true});
try{
  const context=await browser.newContext();await routeArchiveOrigin(context,server);
  const page=await context.newPage();page.setDefaultTimeout(60000);const errors=[];page.on('pageerror',error=>errors.push(error.message));
  async function open(name,key){
    await page.goto(`${server.pageUrl}?tab=witnesses&witness=${key}`);
    const ready=page.locator('[data-archive-ready="true"]');await ready.waitFor();
    assert.equal(await ready.getAttribute('data-archive-release'),server.manifest.release_id,'The page must read the fixture release, not the public one.');
  }
  const shot=async name=>{if(args.screenshots)await page.screenshot({path:join(args.screenshots,`witness-${name}.png`),fullPage:true});};
  const status=()=>page.locator('[role="status"]').filter({hasText:'witness link you followed'});
  const witnessParam=()=>new URL(page.url()).searchParams.get('witness');

  await open('live',cases.live.key);
  await page.getByRole('heading',{name:cases.live.name}).first().waitFor();
  assert.equal(await status().count(),0,'A current key shows no notice.');
  await shot('live');

  await open('redirect',cases.redirect.key);
  await status().filter({hasText:`(${cases.redirect.key}) now points to this witness`}).waitFor();
  await page.getByRole('heading',{name:cases.live.name}).first().waitFor();
  await page.waitForFunction(key=>new URL(location.href).searchParams.get('witness')===key,cases.live.key);
  assert.equal(witnessParam(),cases.live.key,'The address bar names the current key.');
  await shot('redirect');

  await open('ambiguous',cases.ambiguous.key);
  const ambiguous=status().filter({hasText:`(${cases.ambiguous.key})`});await ambiguous.filter({hasText:'more than one current witness matches it'}).waitFor();
  assert.deepEqual(await ambiguous.getByRole('link').allInnerTexts(),cases.ambiguous.candidates);
  assert.equal(await page.getByText('No matching witness found.').count(),0);
  assert.equal(witnessParam(),cases.ambiguous.key,'An ambiguous key is not replaced.');
  await shot('ambiguous');
  await ambiguous.getByRole('link',{name:cases.ambiguous.candidates[0]}).click();
  await page.waitForFunction(key=>new URL(location.href).searchParams.get('witness')===key,cases.ambiguous.candidates[0]);
  await page.locator('.archive-redirect-note, .archive-removed-notice').waitFor({state:'detached'});

  await open('unresolved',cases.unresolved.key);
  await status().filter({hasText:`(${cases.unresolved.key})`}).filter({hasText:'no current witness matches it'}).waitFor();
  assert.equal(await page.getByText('No matching witness found.').count(),0);
  await shot('unresolved');

  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',operation:'earlier witness keys open, list or explain their current witness',release:server.manifest.release_id}));
}finally{await browser.close();await server.close();}
