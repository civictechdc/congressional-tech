/** Bounded local-file measurement; no acquisition or hosted qualification. */
import {readFile, open, stat, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

const [fixture, destination, repeats = '3'] = process.argv.slice(2);
if (!fixture || !destination) throw new Error('Usage: node search-benchmark.mjs FIXTURE OUTPUT [REPEATS]');
const moduleUrl = new URL('../../../apps/site/src/components/filename-catalog.mjs', import.meta.url);
const {createFilenameCatalog} = await import(moduleUrl);
const manifest = pathToFileURL(resolve(fixture, 'public/manifest.json'));
let transferMs = 0, transferred = 0;
const watchdog = setInterval(() => {if (process.memoryUsage().rss > 1024 ** 3) {console.error('1 GiB RSS ceiling exceeded');process.exit(2);}}, 20);
const deadline = setTimeout(() => {console.error('90 second arm deadline exceeded');process.exit(2);}, 90_000);
async function localFetch(url, options = {}) {
  const started = performance.now();
  try {
    if (!options.headers?.Range) {const data=await readFile(new URL(url));transferred+=data.length;return new Response(data);}
    const [start,end]=options.headers.Range.slice(6).split('-').map(Number), file=await open(new URL(url));
    try {const data=Buffer.alloc(end-start+1);await file.read(data,0,data.length,start);transferred+=data.length;
      return new Response(data,{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${(await stat(new URL(url))).size}`}});
    } finally {await file.close();}
  } finally {transferMs += performance.now()-started;}
}
const cases = [
 {name:'source-url',query:{q:'path-path',field:'source_url',scope:'all',limit:10}},
 {name:'wide-arbitrary',query:{q:'marker',field:'content_document_kind',scope:'all',limit:10}},
 {name:'same-source-and',query:{q:'marker',field:'content_document_kind',congress:'117',scope:'all',limit:10,page:2}},
 {name:'observation-unicode',query:{q:'josé 🏛️',field:'source_occurrences',scope:'all',limit:10}},
 {name:'observation-null-json',query:{q:'"source_page_url":null',field:'source_occurrences',scope:'all',limit:10}},
];
const runs=[];
for (let run=0;run<Number(repeats);run++) for(const item of cases) {
  global.gc?.();const reader=await createFilenameCatalog(manifest,localFetch);
  for(const temperature of ['cold','warm']) {
    const before=reader.diagnostics(), transferredBefore=transferred,transferBefore=transferMs;
    const started=performance.now(),result=await reader.search(item.query), elapsedMs=performance.now()-started, after=reader.diagnostics();
    const delta=Object.fromEntries(Object.entries(after).filter(([,v])=>typeof v==='number').map(([k,v])=>[k,v-(before[k]||0)]));
    const record={run,name:item.name,temperature,elapsedMs,transferMs:transferMs-transferBefore,transferred:transferred-transferredBefore,total:result.total,resultSha256:createHash('sha256').update(JSON.stringify(result)).digest('hex'),delta,diagnostics:after,memory:process.memoryUsage()};
    runs.push(record);console.log(JSON.stringify({run,name:item.name,temperature,elapsedMs,total:result.total,transferred:record.transferred}));
  }
}
clearInterval(watchdog);clearTimeout(deadline);
await writeFile(destination,JSON.stringify({head:execFileSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).trim(),moduleSha256:createHash('sha256').update(await readFile(moduleUrl)).digest('hex'),node:process.version,fixture:JSON.parse(await readFile(resolve(fixture,'fixture.json'))),runs,maxRssBytes:process.resourceUsage().maxRSS*1024},null,2));
