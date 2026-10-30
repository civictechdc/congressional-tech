import {readFile,writeFile,rename} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
export const defaultTargets=new URL('../archive-targets.json',import.meta.url);
export const targetNames=['startupMs','searchMs','detailMs','heapBytes'];
// Chrome Lighthouse's Moto G Power viewport and Slow 4G baseline, explicitly
// applied through CDP. These are emulated observations, never physical devices.
export const measurementProfiles={
  phone:{name:'Moto G Power-class',viewport:{width:412,height:823},deviceScaleFactor:1.75,isMobile:true,cpuSlowdown:4,cpuScope:'page main thread (CDP); worker CPU unthrottled',network:{name:'slow-4g',latency:150,downloadThroughput:1600000/8,uploadThroughput:750000/8}},
  desktop:{name:'desktop',viewport:{width:1440,height:1000},deviceScaleFactor:1,isMobile:false,cpuSlowdown:1,cpuScope:'unthrottled',network:null},
};
const positive=value=>Number.isFinite(value)&&value>0;
const measurableOrigin=origin=>origin?.kind==='model'&&(origin.display_only===undefined||origin.display_only===false);
const median=values=>[...values].sort((a,b)=>a-b)[2];
function profileStatistics(samples){
  if(!Array.isArray(samples)||samples.length!==5)throw new Error('Provisional targets require exactly five runs per profile.');
  for(const sample of samples)if(!/^[a-f0-9]{64}$/.test(sample.releaseId)||!positive(sample.workerHeapBytes)||sample.heapBytes<sample.workerHeapBytes||targetNames.some(name=>!positive(sample[name])))throw new Error('Invalid measured profile sample or worker heap.');
  const medians=Object.fromEntries(targetNames.map(name=>[name,median(samples.map(sample=>sample[name]))]));
  return {medians,ceilings:Object.fromEntries(targetNames.map(name=>[name,Math.ceil(1.5*medians[name])]))};
}
function validateTargets(value){
  if(value.version!==1||!['owner-approved','provisional-emulated'].includes(value.status)||targetNames.some(name=>!positive(value.ceilings?.[name])))throw new Error('Invalid qualified archive targets.');
  if(value.status==='owner-approved'){if(value.basis!=='real-device')throw new Error('Owner-approved targets require real-device measurements.');return value;}
  if(value.basis!=='emulated'||!/^[a-f0-9]{40}$/.test(value.harness_commit))throw new Error('Provisional targets need their emulated basis and harness commit.');
  const releases=new Set();
  for(const kind of ['phone','desktop']){
    const expected=profileStatistics(value.raw_runs?.[kind]),profile=value.profile?.[kind];
    if(!profile||Object.keys(measurementProfiles[kind]).some(name=>JSON.stringify(profile[name])!==JSON.stringify(measurementProfiles[kind][name]))||JSON.stringify(profile.medians)!==JSON.stringify(expected.medians)||JSON.stringify(profile.ceilings)!==JSON.stringify(expected.ceilings))throw new Error('Provisional profile or median ceilings differ from their measured runs.');
    for(const sample of value.raw_runs[kind])releases.add(sample.releaseId);
  }
  if(releases.size!==1)throw new Error('Both profiles must measure the same release.');
  if(targetNames.some(name=>value.ceilings[name]!==Math.max(value.profile.phone.ceilings[name],value.profile.desktop.ceilings[name])))throw new Error('Provisional combined ceilings differ from their profiles.');
  return value;
}
export async function readTargets(path=defaultTargets){const value=JSON.parse(await readFile(path));if(value.version!==1)throw new Error('Unsupported target schema.');if(value.status==='owner-gated')return undefined;return validateTargets(value);}
export function checkTargetRelease(releaseId,targets,origin){
  validateTargets(targets??{});
  if(targets.status==='provisional-emulated'&&!measurableOrigin(origin))throw new Error('Provisional emulated targets require a non-display-only model release.');
  if(targets.status==='provisional-emulated'&&releaseId!==targets.raw_runs.phone[0].releaseId)throw new Error('Provisional targets measured a different release identity.');
}
export function checkTargets(sample,targets,origin,profile){
  checkTargetRelease(sample.releaseId,targets,origin);
  const ceilings=targets.status==='provisional-emulated'&&profile?targets.profile[profile]?.ceilings:targets.ceilings;
  if(!ceilings)throw new Error('Unknown measured target profile.');
  for(const name of targetNames)if(!Number.isFinite(sample[name])||sample[name]<0||sample[name]>ceilings[name])throw new Error(`Archive ${name} exceeds its measured target.`);
}
export async function validateTargetFile(path,origin){
  const targets=await readTargets(path);if(!targets)throw new Error('Qualified archive targets are missing.');
  if(targets.status==='provisional-emulated'&&!measurableOrigin(origin))throw new Error('Provisional targets require a non-display-only model release.');
  return {status:targets.status,basis:targets.basis,measured_release_id:targets.status==='provisional-emulated'?targets.raw_runs.phone[0].releaseId:null};
}
export async function writeTargets({measurements,ceilings,output,basis='real-device',harnessCommit}){
  let targets;
  if(basis==='emulated'){
    if(!Array.isArray(measurements)||measurements.length!==2)throw new Error('Provisional targets require two emulated profiles.');
    const profile={},raw_runs={};
    for(const kind of ['phone','desktop']){
      const receipt=measurements.find(item=>item.deviceClass===kind+'-profile');
      if(!receipt||receipt.basis!=='emulated'||!measurableOrigin(receipt.origin)||receipt.harnessCommit!==harnessCommit||JSON.stringify(receipt.profile)!==JSON.stringify(measurementProfiles[kind]))throw new Error('Emulated profile, harness commit and origin must match the measurement.');
      raw_runs[kind]=receipt.samples;profile[kind]={...measurementProfiles[kind],...profileStatistics(receipt.samples)};
    }
    targets={version:1,status:'provisional-emulated',basis,profile,harness_commit:harnessCommit,raw_runs,ceilings:Object.fromEntries(targetNames.map(name=>[name,Math.max(profile.phone.ceilings[name],profile.desktop.ceilings[name])]))};
  }else{
    if(basis!=='real-device'||!Array.isArray(measurements)||!['real-phone','real-desktop'].every(kind=>measurements.some(item=>item.deviceClass===kind)))throw new Error('Targets require real-phone and real-desktop measurements.');
    const devices=[];
    for(const receipt of measurements){
      if(!['real-phone','real-desktop'].includes(receipt.deviceClass)||!Array.isArray(receipt.samples)||!receipt.samples.length)throw new Error('Missing real device samples.');
      for(const sample of receipt.samples){
        if(!/^[a-f0-9]{64}$/.test(sample.releaseId)||!positive(sample.workerHeapBytes)||sample.heapBytes<sample.workerHeapBytes)throw new Error('Each device sample must identify its release and measured worker heap.');
        checkTargets(sample,{version:1,status:'owner-approved',basis,ceilings});
      }
      devices.push({deviceClass:receipt.deviceClass,sha256:createHash('sha256').update(JSON.stringify(receipt)).digest('hex'),runtime:receipt.runtime??null,releases:[...new Set(receipt.samples.map(sample=>sample.releaseId))]});
    }
    if(!devices[0].releases.some(id=>devices.every(device=>device.releases.includes(id))))throw new Error('Both real devices must measure the same release.');
    targets={version:1,status:'owner-approved',basis,ceilings,devices};
  }
  validateTargets(targets);
  let pending=false;try{const existing=JSON.parse(await readFile(output));if(existing.status!=='owner-gated')throw new Error('Qualified targets already exist; use a new output file for review.');pending=true;}catch(error){if(error.code!=='ENOENT')throw error;}
  if(pending){const temporary=String(output)+'.pending';await writeFile(temporary,JSON.stringify(targets,null,2)+'\n',{flag:'wx'});await rename(temporary,output);}else await writeFile(output,JSON.stringify(targets,null,2)+'\n',{flag:'wx'});return targets;
}
export function argumentsMap(args){const out={};for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||args[i+1]===undefined)throw new Error('Use --name value arguments.');out[args[i].slice(2)]=args[i+1];}return out;}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const args=argumentsMap(process.argv.slice(2));
  if(args.check){if(args['display-only']!=='false'||args['origin-kind']!=='model')throw new Error('Target validation requires --origin-kind model and --display-only false.');console.log(JSON.stringify(await validateTargetFile(args.check,{kind:args['origin-kind'],display_only:false})));}
  else{if(!args.measurements||!args.output)throw new Error('Use --measurements phone.json,desktop.json --output targets.json and either real-device ceilings or --basis emulated --harness-commit SHA.');
  const measurements=await Promise.all(args.measurements.split(',').map(async name=>JSON.parse(await readFile(name))));
  await writeTargets({measurements,ceilings:Object.fromEntries(targetNames.map(name=>[name,Number(args[name])])),output:args.output,basis:args.basis,harnessCommit:args['harness-commit']});}
}
