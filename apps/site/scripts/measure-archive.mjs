/** Browser measurements use the built page and the worker it ships. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
import {argumentsMap,checkTargets,readTargets,measurementProfiles} from './archive-targets.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {browserDependency,heapSampler,routeArchiveOrigin} from './archive-browser.mjs';
export async function measureArchive(args){
  const samples=[],repeats=Number(args.repeats||3),deviceClass=args['device-class']||'desktop-profile';
  if(!Number.isSafeInteger(repeats)||repeats<1||repeats>20)throw new Error('Use between one and twenty repetitions.');
  const profileKind=deviceClass==='phone-profile'?'phone':'desktop',profile=measurementProfiles[profileKind];
  const emulated=!args.cdp&&['phone-profile','desktop-profile'].includes(deviceClass);
  if(emulated&&!/^[a-f0-9]{40}$/.test(args['harness-commit']||''))throw new Error('Emulated measurements require --harness-commit.');
  const targets=await readTargets(args.targets);
  const {chromium}=browserDependency('playwright');
  if(args['device-class']==='real-phone'&&!args.cdp)throw new Error('A real phone run requires its remote CDP endpoint.');
  const bodies=args.bodies?JSON.parse(await readFile(args.bodies)):{};
  const server=await startArchiveServer({release:resolve(args.release),siteDist:resolve(args.dist||'dist'),bodies,port:Number(args.port||0)});
  let browser;
  try{
    browser=args.cdp?await chromium.connectOverCDP(args.cdp):await chromium.launch({headless:true,...(args['browser-executable']?{executablePath:args['browser-executable']}:{})});
    for(let i=0;i<repeats;i++){
      const ownedContext=!args.cdp,context=ownedContext?await browser.newContext({viewport:profile.viewport,deviceScaleFactor:profile.deviceScaleFactor,isMobile:profile.isMobile}):browser.contexts()[0];
      const page=await context.newPage();await routeArchiveOrigin(page,server);page.setDefaultTimeout(Number(args['timeout-ms']||60000));
      const sampler=heapSampler(browser,page,{profile:emulated?profile:undefined});
      try{
        await sampler.ready;
        let started=performance.now();await page.goto(args.page||server.pageUrl);await page.locator('[data-archive-ready="true"]').waitFor();await page.locator('.archive-document').first().waitFor();const observedReleaseId=await page.locator('[data-archive-ready="true"]').getAttribute('data-archive-release');if(observedReleaseId!==server.manifest.release_id)throw new Error('The measured page selected a different release than its fixture.');const startupMs=performance.now()-started;
        let peak={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0};
        started=performance.now();await page.getByRole('searchbox').fill(args.query||'hearing');await page.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(query=>document.querySelector('[data-archive-query]')?.getAttribute('data-archive-query')===query,args.query||'hearing');const searchMs=performance.now()-started;
        // Return to a known visible row, then measure the actual document page.
        await page.getByRole('searchbox').fill('');await page.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-archive-query]')?.getAttribute('data-archive-query')==='');await page.locator('.archive-document').first().waitFor();
        started=performance.now();await page.locator('.archive-document').first().click();await page.locator('[data-archive-detail]').waitFor();const detailMs=performance.now()-started;
        const after=await sampler.stop();if(after.heapBytes>peak.heapBytes)peak=after;
        const sample={releaseId:observedReleaseId,pageUrl:page.url(),startupMs,searchMs,detailMs,...peak};
        if(targets)checkTargets(sample,targets,server.manifest.origin,profileKind);samples.push(sample);
        if(args.screenshot)await page.screenshot({path:args.screenshot,fullPage:true});
      }finally{try{await sampler.stop();}finally{await page.close();if(ownedContext)await context.close();}}
    }
    return {version:1,deviceClass,basis:emulated?'emulated':'real-device',...(emulated?{profile,harnessCommit:args['harness-commit']}:{}),origin:server.manifest.origin,runtime:{node:process.version,browser:browser.version(),platform:process.platform,architecture:process.arch,cdp:Boolean(args.cdp)},heapMethod:'CDP Runtime.getHeapUsage on page and archive worker every50ms through startup/search/detail; includes backing storage and reports sample count',samples};
  }finally{try{if(browser)await browser.close();}finally{await server.close();}}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){const args=argumentsMap(process.argv.slice(2));const receipt=await measureArchive(args);if(args.output)await writeFile(args.output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));}
