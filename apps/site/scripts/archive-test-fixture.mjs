/** Explicit transport for reader tests. Byte verification belongs to the reader. */
import {readFile,stat} from 'node:fs/promises';
import {isAbsolute} from 'node:path';

export async function loadArchiveFixture(envName='ARCHIVE_FIXTURE_FILES') {
  const path=process.env[envName];
  if(!path)throw new Error(`${envName} is required and must name a JSON file containing the exact logical-name to absolute-path release inventory.`);
  return archiveFixture(JSON.parse(await readFile(path,'utf8')));
}

export async function archiveFixture(files) {
  if(!files||typeof files!=='object'||Array.isArray(files))throw new Error('Fixture inventory must be an object.');
  if(typeof files['manifest.json']!=='string'||!isAbsolute(files['manifest.json']))throw new Error('Fixture inventory needs absolute asset paths, including manifest.json.');
  const manifest=JSON.parse(await readFile(files['manifest.json'],'utf8'));
  const names=['manifest.json',...manifest.files.map(file=>file.name)];
  if(new Set(names).size!==names.length||Object.keys(files).length!==names.length||names.some(name=>!Object.hasOwn(files,name)))throw new Error('Fixture inventory differs from release membership.');
  for(const name of names){
    if(!/^(?:[a-z_0-9.-]+|queries\/[a-f0-9]{64}\.sql|lineage\/[0-9]{4}\.openlineage\.json)$/.test(name)||['.','..'].includes(name))throw new Error('Invalid fixture asset name.');
    if(typeof files[name]!=='string'||!isAbsolute(files[name]))throw new Error('Fixture inventory needs absolute asset paths.');
    if(!(await stat(files[name])).isFile())throw new Error(`Fixture asset is not a file: ${name}`);
  }
  const requests=[];
  const remapRelease=url=>{
    const mapped=new URL(url);
    mapped.pathname=mapped.pathname.replace(/\/releases\/[^/]+\//,`/releases/${manifest.release_id}/`);
    return mapped.href;
  };
  const fetcher=async(url,options={})=>{
    const pathname=new URL(url).pathname,range=new Headers(options.headers).get('Range');
    requests.push({path:pathname,range:range??undefined});
    if(pathname==='/manifest.json')return Response.json({release_id:manifest.release_id,previous_release_id:null});
    const prefix=`/releases/${manifest.release_id}/`;
    if(!pathname.startsWith(prefix))return new Response(null,{status:404});
    const name=pathname.slice(prefix.length);
    if(!Object.hasOwn(files,name))return new Response(null,{status:404});
    const bytes=await readFile(files[name]);
    if(!range)return new Response(bytes);
    const match=/^bytes=(\d+)-(\d+)$/.exec(range);
    const start=Number(match?.[1]),end=Number(match?.[2]);
    if(!match||!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||end>=bytes.length)return new Response(null,{status:416,headers:{'Content-Range':`bytes */${bytes.length}`}});
    return new Response(bytes.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
  };
  return {files,manifest,requests,fetcher,remapRelease};
}
