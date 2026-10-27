import {readFile,writeFile,rename} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
export const defaultTargets=new URL('../archive-targets.json',import.meta.url);
export async function readTargets(path=defaultTargets){const value=JSON.parse(await readFile(path));if(value.version!==1)throw new Error('Unsupported target schema.');if(value.status==='owner-gated')return undefined;if(value.status!=='measured'||targetNames.some(name=>!Number.isFinite(value.ceilings?.[name])||value.ceilings[name]<=0))throw new Error('Invalid measured archive targets.');return value;}
export const targetNames=['startupMs','searchMs','detailMs','heapBytes'];
const positive=value=>Number.isFinite(value)&&value>0;
export function checkTargets(sample,targets){
  if(targets?.status!=='measured'||targetNames.some(name=>!positive(targets.ceilings?.[name])))throw new Error('Measured archive targets are missing or invalid.');
  for(const name of targetNames)if(!Number.isFinite(sample[name])||sample[name]<0||sample[name]>targets.ceilings[name])throw new Error(`Archive ${name} exceeds its measured target.`);
}
const sampleHeapInvalid=measurements=>measurements.some(receipt=>receipt.samples.some(sample=>sample.heapBytes<sample.workerHeapBytes));
export async function writeTargets({measurements,ceilings,output}){
  if(!Array.isArray(measurements)||!['real-phone','real-desktop'].every(kind=>measurements.some(item=>item.deviceClass===kind)))throw new Error('Targets require real-phone and real-desktop measurements.');
  const devices=[];
  for(const receipt of measurements){
    if(!['real-phone','real-desktop'].includes(receipt.deviceClass)||!Array.isArray(receipt.samples)||!receipt.samples.length)throw new Error('Missing real device samples.');
    for(const sample of receipt.samples){
      if(!/^[a-f0-9]{64}$/.test(sample.releaseId)||!positive(sample.workerHeapBytes))throw new Error('Each device sample must identify its release and measured worker heap.');
      checkTargets(sample,{status:'measured',ceilings});
    }
    devices.push({deviceClass:receipt.deviceClass,sha256:createHash('sha256').update(JSON.stringify(receipt)).digest('hex'),runtime:receipt.runtime??null,releases:[...new Set(receipt.samples.map(sample=>sample.releaseId))]});
  }
  if(sampleHeapInvalid(measurements))throw new Error('Measured heap must include its worker backing storage.');
  if(!devices[0].releases.some(id=>devices.every(device=>device.releases.includes(id))))throw new Error('Both real devices must measure the same release.');
  const targets={version:1,status:'measured',ceilings,devices};
  let pending=false;try{const existing=JSON.parse(await readFile(output));if(existing.status!=='owner-gated')throw new Error('Measured targets already exist; use a new output file for review.');pending=true;}catch(error){if(error.code!=='ENOENT')throw error;}
  if(pending){const temporary=String(output)+'.pending';await writeFile(temporary,JSON.stringify(targets,null,2)+'\n',{flag:'wx'});await rename(temporary,output);}else await writeFile(output,JSON.stringify(targets,null,2)+'\n',{flag:'wx'});return targets;
}
export function argumentsMap(args){const out={};for(let i=0;i<args.length;i+=2){if(!args[i].startsWith('--')||args[i+1]===undefined)throw new Error('Use --name value arguments.');out[args[i].slice(2)]=args[i+1];}return out;}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const args=argumentsMap(process.argv.slice(2));if(!args.measurements||!args.output)throw new Error('Use --measurements phone.json,desktop.json --output targets.json and --startupMs/--searchMs/--detailMs/--heapBytes ceilings.');
  const measurements=await Promise.all(args.measurements.split(',').map(async name=>JSON.parse(await readFile(name))));
  await writeTargets({measurements,ceilings:Object.fromEntries(targetNames.map(name=>[name,Number(args[name])])),output:args.output});
}
