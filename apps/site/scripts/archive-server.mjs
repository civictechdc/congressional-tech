/** Read-only fixture origin: explicit verified releases, built site, approved body paths. */
import {createServer} from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {resolve,sep,extname} from 'node:path';
import {createHash} from 'node:crypto';
export async function startArchiveServer({release,siteDist,bodies={},nextRelease,port=0}){
  const releases=new Map();
  for(const folder of [release,nextRelease].filter(Boolean)){
    const manifest=JSON.parse(await readFile(resolve(folder,'manifest.json')));
    const identity=createHash('sha256').update(JSON.stringify([manifest.schema_version,manifest.files.map(f=>[f.name,f.sha256,f.size,f.rows])])).digest('hex');
    if(identity!==manifest.release_id)throw new Error('Fixture release identity failed verification.');
    const assets=new Map();
    for(const file of manifest.files){
      if(!/^[a-z_0-9.-]+$/.test(file.name))throw new Error('Invalid fixture asset name.');
      const path=resolve(folder,file.name),bytes=await readFile(path);
      if(bytes.byteLength!==file.size||createHash('sha256').update(bytes).digest('hex')!==file.sha256)throw new Error('Fixture asset bytes failed verification.');assets.set(file.name,{path,size:file.size,digest:file.sha256});
    }
    const path=resolve(folder,'manifest.json'),bytes=await readFile(path);assets.set('manifest.json',{path,size:bytes.length,digest:createHash('sha256').update(bytes).digest('hex')});
    releases.set(manifest.release_id,{manifest,assets});
  }
  const bodyAssets=new Map();
  for(const [key,value] of Object.entries(bodies)){
    const path=typeof value==='string'?value:value.path;
    const match=/^bodies\/sha256\/([a-f0-9]{2})\/([a-f0-9]{64})([.]gz|[.]pdf)?$/.exec(key);
    if(!match||match[1]!==match[2].slice(0,2))throw new Error('Invalid approved fixture body key.');
    const bytes=await readFile(path);const expected=typeof value==='string'?match[2]:value.stored_sha256;if(!/^[a-f0-9]{64}$/.test(expected)||typeof value==='object'&&bytes.length!==value.stored_bytes||createHash('sha256').update(bytes).digest('hex')!==expected)throw new Error('Approved body hash does not match its physical key.');
    bodyAssets.set(key,{path:resolve(path),size:bytes.length,digest:expected});
  }
  const state={releaseId:releases.keys().next().value,missingFile:null,flipOnMissing:null,pointerReads:0,delayDetailMs:0,requests:[]};
  const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.woff2':'font/woff2'};
  const server=createServer(async(req,res)=>{
    try{
      if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
      const url=new URL(req.url,'http://localhost'),path=decodeURIComponent(url.pathname);let asset,cache='public,max-age=31536000,immutable';
      if(path==='/congressional-tech/data/archive/manifest.json'){
        state.pointerReads++;const bytes=Buffer.from(JSON.stringify({release_id:state.releaseId,previous_release_id:null}));
        res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Access-Control-Allow-Origin':'*','Content-Length':bytes.length});res.end(req.method==='HEAD'?undefined:bytes);return;
      }
      const match=/^\/congressional-tech\/data\/archive\/releases\/([a-f0-9]{64})\/([a-z_0-9.-]+)$/.exec(path);
      if(match){
        if(state.missingFile===match[2]){if(state.flipOnMissing)state.releaseId=state.flipOnMissing;res.writeHead(404,{'Cache-Control':'no-store'});res.end();return;}
        if(server && state.delayDetailMs && /^detail(?:-|[.])/.test(match[2]))await new Promise(resolve=>setTimeout(resolve,state.delayDetailMs));
        asset=releases.get(match[1])?.assets.get(match[2]);
      }else if(path.startsWith('/bodies/'))asset=bodyAssets.get(path.slice(1));
      else if(siteDist&&path.startsWith('/congressional-tech/')){
        const root=resolve(siteDist),relative=path.slice('/congressional-tech/'.length),target=resolve(root,relative+(path.endsWith('/')?'index.html':''));
        if(!target.startsWith(root+sep)){res.writeHead(404);res.end();return;}
        try{const info=await stat(target);if(info.isFile())asset={path:target,size:info.size};}catch{}
        cache='no-store';
      }
      if(!asset){res.writeHead(404,{'Cache-Control':'no-store'});res.end();return;}
      let start=0,end=asset.size-1,status=200;
      if(req.headers.range){const range=/^bytes=(\d+)-(\d+)$/.exec(req.headers.range);if(!range||Number(range[1])>Number(range[2])||Number(range[2])>=asset.size){res.writeHead(416);res.end();return;}start=Number(range[1]);end=Number(range[2]);status=206;}
      const headers={'Content-Type':mime[extname(asset.path)]||'application/octet-stream','Cache-Control':cache,'Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*','Access-Control-Expose-Headers':'Content-Range,Content-Length,Accept-Ranges,Cache-Control,Content-Encoding','Content-Length':end-start+1};
      if(status===206)headers['Content-Range']=`bytes ${start}-${end}/${asset.size}`;if(asset.digest)headers.ETag=`"${asset.digest}"`;
      state.requests.push({path,start,end,status});res.writeHead(status,headers);if(req.method==='HEAD')res.end();else createReadStream(asset.path,{start,end}).pipe(res);
    }catch(error){res.writeHead(500);res.end('Fixture server error');}
  });
  server.keepAliveTimeout=65000;server.headersTimeout=70000;
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
  const origin=`http://127.0.0.1:${server.address().port}`;
  return {origin,pointerUrl:origin+'/congressional-tech/data/archive/manifest.json',pageUrl:origin+'/congressional-tech/archive/',rawBase:origin+'/',state,manifest:releases.get(state.releaseId).manifest,nextManifest:nextRelease?[...releases.values()][1].manifest:null,close:()=>new Promise(resolve=>{server.close(resolve);server.closeAllConnections();})};
}
