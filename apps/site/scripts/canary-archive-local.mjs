import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {argumentsMap,readTargets} from './archive-targets.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {verifyArchive} from './verify-archive.mjs';
const args=argumentsMap(process.argv.slice(2));
const server=await startArchiveServer({release:resolve(args.release),bodies:args.bodies?JSON.parse(await readFile(args.bodies)):{}});
try{
  global.gc?.();
  const receipt=await verifyArchive({pointerUrl:server.pointerUrl,releaseId:server.manifest.release_id,rawBase:server.rawBase,local:true,savedRow:args['saved-row'],checkSaved:args['check-saved']!=='false',targets:await readTargets(args.targets)});
  if(args.output)await writeFile(args.output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{await server.close();}
