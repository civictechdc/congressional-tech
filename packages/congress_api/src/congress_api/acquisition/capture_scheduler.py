"""Public release scheduling and bounded, append-only raw capture."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urljoin, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.acquisition.capture_seeds import inventories
from congress_api.acquisition.fetcher import CaptureScope, Fetcher, HostPacer
from congress_api.parsers.archive_readings import read_page
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import validate_record
from congress_api.retention.pipeline_raw import new_run_id
from congress_api.retention.provenance import field, json_input, parquet_output, run_job
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.receipt_privacy import credential_parameters

ROOT = Path(__file__).resolve().parents[5]
REGISTRY = ROOT / 'model/registries/capture-scope.json'
HEX = re.compile('[0-9a-f]{64}')
PAGE_BYTES = 8 << 20
RELEASE_FILE_BYTES = 128 << 20
PACING = dict(default_gap_seconds=0.2,provider_gap_seconds=0,
              hosts={'docs.house.gov':dict(gap_seconds=1.2,backoffs={'403':60})})


def _literal(value):
    return "'" + value.replace("'", "''") + "'"


def _utc(value):
    stamp = datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Scheduler time needs a timezone')
    return stamp.astimezone(timezone.utc).isoformat()


def _positive(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(name + ' must be a positive integer')
    return value


def resolve_host(host):
    return list({item[4][0] for item in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)})


class CapturePolicy:
    def __init__(self, path, *, resolve=resolve_host):
        value=json.loads(Path(path).read_text())
        if (not isinstance(value,dict) or set(value)!={'version','entries'} or type(value['version']) is not int or value['version']!=1
                or not isinstance(value['entries'],list)):
            raise ValueError('Invalid capture scope registry')
        self.entries=[]
        families=set()
        for entry in value['entries']:
            if (not isinstance(entry,dict) or set(entry)!={'family','patterns','exclusions'}
                    or not isinstance(entry['family'],str) or entry['family'] in families
                    or not re.fullmatch(r'[a-z0-9_-]+(?:/[a-z0-9_-]+)*',entry['family'])
                    or not isinstance(entry['patterns'],list) or not entry['patterns']
                    or not isinstance(entry['exclusions'],list)
                    or any(not isinstance(x,str) or not x for x in entry['patterns']+entry['exclusions'])):
                raise ValueError('Invalid capture scope entry')
            families.add(entry['family'])
            scope=CaptureScope(entry['patterns'],entry['exclusions'],resolve=resolve)
            self.entries.append((entry,scope))

    def require_capture(self):
        if not self.entries:
            raise ValueError('Cannot capture with an empty scope registry')

    def family(self,url):
        if not isinstance(url,str) or len(url.encode('utf-8'))>16384:return None
        return next((entry['family'] for entry,scope in self.entries if scope(url)),None)

    def __call__(self,url):
        return self.family(url) is not None

    def sql(self,column):
        choices=[]
        for entry,_ in self.entries:
            include=' OR '.join(f'regexp_like({column},{_literal(pattern)})' for pattern in entry['patterns'])
            exclude=' OR '.join(f'regexp_like({column},{_literal(pattern)})' for pattern in entry['exclusions']) or 'false'
            choices.append(f'WHEN ({include}) AND NOT ({exclude}) THEN {_literal(entry["family"])}')
        return 'CASE '+' '.join(choices)+" ELSE cast(NULL AS VARCHAR) END" if choices else 'cast(NULL AS VARCHAR)'


def _safe_reference(value):
    """Check URI references without resolving or rewriting their identity."""
    if not isinstance(value,str):return False
    try:
        if len(value.encode('utf-8'))>16384:return False
        validate_record(value)
        parts=urlsplit(value)
        names={row['parameter'].casefold() for row in credential_parameters()}
        return (parts.username is None and parts.password is None and
            not any(name.casefold() in names for name,_ in parse_qsl(parts.query,keep_blank_values=True)))
    except (ValueError,UnicodeError):
        return False


def _identity(path,entry):
    with Path(path).open('rb') as source:
        digest=hashlib.file_digest(source,'sha256').hexdigest()
        size=source.tell()
    if (digest,size)!=(entry['sha256'],entry['size']):
        raise ValueError('Release file identity or size differs from the manifest')


def _download(session,url,path,limit):
    if urlsplit(url).scheme!='https':
        raise ValueError('Capture release URLs must use HTTPS')
    validate_record(url)
    with session.get(url,stream=True,allow_redirects=False,timeout=(15,120),headers={'Cache-Control':'no-cache'}) as response:
        response.raise_for_status()
        size=0
        with Path(path).open('xb') as out:
            for chunk in response.iter_content(chunk_size=1<<20):
                size+=len(chunk)
                if size>limit:raise ValueError('Release download exceeds its byte allowance')
                out.write(chunk)
    return Path(path)


def load_release(*,work,release_root=None,pointer=None,session=None):
    """Select one public release once; verify its two scheduler input files."""
    if (release_root is None)==(pointer is None):
        raise ValueError('Select a public pointer or a local release root')
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    if pointer:
        if session is None:
            import requests
            session=requests.Session()
        selected=json.loads(_download(session,pointer,work/'pointer.json',1<<20).read_text())
        release_id=selected.get('release_id')
        if not isinstance(release_id,str) or not HEX.fullmatch(release_id):
            raise ValueError('Invalid public release pointer')
        base=urljoin(pointer,f'releases/{release_id}/')
        manifest=json.loads(_download(session,urljoin(base,'manifest.json'),work/'manifest.json',2<<20).read_text())
    else:
        release_root=Path(release_root).resolve()
        manifest=json.loads((release_root/'manifest.json').read_text())
        release_id=manifest.get('release_id')
    if not isinstance(manifest,dict) or manifest.get('schema_version')!=1 or manifest.get('release_id')!=release_id or not HEX.fullmatch(release_id or ''):
        raise ValueError('Unsupported release manifest or identity')
    files=manifest.get('files')
    if not isinstance(files,list) or any(not isinstance(row,dict) or not all(key in row for key in ('name','sha256','size','rows')) for row in files):
        raise ValueError('Invalid release file manifest')
    if len({row['name'] for row in files})!=len(files):raise ValueError('Duplicate release file name')
    actual=hashlib.sha256(json.dumps([1,[[row[k] for k in ('name','sha256','size','rows')] for row in files]],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if actual!=release_id:raise ValueError('Release manifest content identity differs')
    selected={}
    for name in ('url_state.parquet','capture_scope.json'):
        entry=next((row for row in files if row['name']==name),None)
        if (entry is None or not isinstance(entry['sha256'],str) or not HEX.fullmatch(entry['sha256'])
                or type(entry['size']) is not int or not 0<=entry['size']<=RELEASE_FILE_BYTES):
            raise ValueError('Release omits a bounded scheduler input')
        if pointer:
            path=_download(session,urljoin(base,name),work/name,entry['size'])
        else:
            path=(release_root/name).resolve()
            if not path.is_relative_to(release_root):raise ValueError('Release input escapes its root')
        _identity(path,entry);selected[name]=path
    CapturePolicy(selected['capture_scope.json'])
    return dict(release_id=release_id,state=selected['url_state.parquet'],scope=selected['capture_scope.json'])


def _records(path):
    with pq.ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=64):
            yield from batch.to_pylist()


def plan_queue(release,*,engine,work,as_of,request_budget,seed_inventories=(),
               seed_files=(),discovery_files=(),attempted=None,cutoff_urls=()):
    """Native due/seed anti-joins and priority selection; exact requested URL key."""
    _positive(request_budget,'request budget');as_of=_utc(as_of)
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    required={'requested_url','attempts','next_attempt_at','last_outcome'}
    schema=pq.read_schema(release['state'])
    if not required.issubset(schema.names):
        raise ValueError('url_state has no scheduler schema')
    timestamp=schema.field('next_attempt_at').type
    if (not pa.types.is_int32(schema.field('attempts').type)
            or not pa.types.is_string(schema.field('requested_url').type)
            or not pa.types.is_timestamp(timestamp) or timestamp.unit!='us' or timestamp.tz!='UTC'):
        raise ValueError('url_state has incompatible scheduler column types')
    policy=CapturePolicy(release['scope'])
    inputs=[dict(name='states',kind='parquet',path=str(Path(release['state']).resolve()))]
    files=list(seed_files)
    if seed_inventories:
        seeded=json_input(work,'weekly',inventories(seed_inventories),url='Utf8',source='Utf8',pointer='Utf8')
        files.extend(seeded['files'])
    inputs.append(dict(name='seeds',kind='json_lines',files=files,
        schema=dict(fields=[field(k,'Utf8') for k in ('url','source','pointer')],metadata={})))
    inputs.append(dict(name='discovery',kind='json_lines',files=list(discovery_files),
        schema=dict(fields=[field(k,'Utf8') for k in ('href','base_href','context','source','pointer')],metadata={})))
    inputs.append(dict(name='attempted',kind='json_lines',files=[] if attempted is None else [dict(key='attempted',path=str(attempted))],
        schema=dict(fields=[field('url','Utf8')],metadata={})))
    inputs.append(json_input(work,'cutoffs',(dict(url=url) for url in cutoff_urls),url='Utf8'))
    steps=[dict(name='seed_rows',sql="""SELECT url,source,pointer FROM seeds UNION ALL
        SELECT url_resolve(href,coalesce(url_resolve(base_href,context),context)) AS url,source,pointer FROM discovery"""),
        dict(name='observations',sql="""SELECT url,array_agg(DISTINCT json_array(url,source,pointer)
            ORDER BY json_array(url,source,pointer)) AS observations FROM seed_rows WHERE url IS NOT NULL GROUP BY url"""),
        dict(name='candidates',sql=f"""SELECT requested_url,attempts,cast(last_outcome AS VARCHAR) AS last_outcome,next_attempt_at,
                coalesce(o.observations,make_array(json_array(requested_url,{_literal('release:'+release['release_id'])},'[]'))) AS observations
            FROM states s LEFT JOIN observations o ON s.requested_url=o.url
            UNION ALL SELECT o.url AS requested_url,0 AS attempts,cast(NULL AS VARCHAR) AS last_outcome,cast(NULL AS TIMESTAMP) AS next_attempt_at,o.observations
            FROM observations o LEFT ANTI JOIN states s ON o.url=s.requested_url"""),
        dict(name='scoped',sql=f"""SELECT c.*,{policy.sql('requested_url')} AS family,
            CASE WHEN attempts=0 THEN 0 WHEN last_outcome='size_limit' OR k.url IS NOT NULL
            THEN 1 ELSE 2 END AS priority FROM candidates c LEFT JOIN (SELECT DISTINCT url FROM cutoffs) k ON c.requested_url=k.url
            LEFT ANTI JOIN attempted a ON c.requested_url=a.url"""),
        dict(name='due',sql=f"SELECT * FROM scoped WHERE family IS NOT NULL AND (next_attempt_at IS NULL OR next_attempt_at<=to_timestamp({_literal(as_of)}))")]
    values=run_job(work,engine,inputs=inputs,steps=steps,outputs=[parquet_output(work,'queue',
        f'SELECT requested_url,family,priority,next_attempt_at,observations FROM due ORDER BY priority,next_attempt_at NULLS FIRST,requested_url LIMIT {request_budget}',
        ['priority','next_attempt_at','requested_url'])],queries=[
        dict(name='counts',sql="SELECT count(*) AS due,count(*) FILTER(WHERE priority=0) AS queue,count(*) FILTER(WHERE priority=1) AS cutoffs FROM due"),
        dict(name='bad_states',sql="SELECT count(*) AS violations FROM states WHERE requested_url IS NULL OR attempts IS NULL OR attempts<0 OR octet_length(requested_url)>16384"),
        dict(name='large_observations',sql='SELECT count(*) AS violations FROM observations WHERE array_length(observations)>256'),
        dict(name='duplicates',sql='SELECT count(*) AS violations FROM (SELECT requested_url FROM states GROUP BY requested_url HAVING count(*)>1)')])
    if any(values[name][0]['violations'] for name in ('bad_states','duplicates','large_observations')):
        raise ValueError('Invalid or duplicate url_state rows')
    return dict(queue=str(work/'queue.parquet'),counts=values['counts'][0],release_id=release['release_id'],
                as_of=as_of,seed_files=files)


class _Counted:
    def __init__(self,adapter,stats):self.adapter,self.stats=adapter,stats
    def hop(self,url,destination,*,limit,headers):
        self.stats['requests']+=1
        result=self.adapter.hop(url,destination,limit=limit,headers=headers)
        self.stats['fetched_bytes']+=result.size if result.size is not None else destination.stat().st_size
        return result


def _allowance(byte_budget,spool_budget,archive_limits,hops):
    # Source+prepared copy+compression overhead, plus all expanded members and
    # a member's preparation. Each redirect can consume its full allowance.
    # Admit the full entity range; BodyStore separately checks actual encoded
    # stored bytes against single-PUT capacity. Compression headroom belongs
    # in the spool reservation, not an arbitrary half-size entity ceiling.
    overhead=2*archive_limits.max_total_bytes+2*archive_limits.max_member_bytes+6*archive_limits.max_directory_bytes+(16<<20)
    limit=min(byte_budget//hops,max(0,(spool_budget-overhead)//3),5*1024**3)
    return limit,3*limit+overhead


def run_capture(release,*,engine,work,as_of,request_budget,byte_budget,spool_budget,
                store,identity,direct,provider=None,resolve=resolve_host,pace=None,
                archive_limits=None,seed_inventories=(),cutoff_urls=(),
                discover=read_page,max_discovery_jobs=8,headers=None):
    """One sequential raw writer. No state/index or table writes occur here."""
    for name,value in [('request budget',request_budget),('byte budget',byte_budget),('spool budget',spool_budget),('discovery jobs',max_discovery_jobs)]:
        _positive(value,name)
    as_of=_utc(as_of);work=Path(work);work.mkdir(parents=True,exist_ok=False)
    policy=CapturePolicy(release['scope'],resolve=resolve);policy.require_capture()
    archive_limits=archive_limits or ZipLimits();hops=14 if provider is not None else 7
    stats=dict(release_id=release['release_id'],as_of=as_of,run_id=new_run_id(),requests=0,
        fetched_bytes=0,captures=0,receipts=[],refusals=[],discovery_errors=[],discovery_refused=0,cutoffs=[],
        budgets=dict(requests=request_budget,bytes=byte_budget,spool=spool_budget),spool_reserved_bound=0,stop_reason=None)
    writer=ReceiptWriter(store,identity=identity,run_id=stats['run_id'],write_date=datetime.now(timezone.utc).date().isoformat(),archive_limits=archive_limits)
    attempted=work/'attempted.jsonl.gz';discovered=[];generation=0
    plan=plan_queue(release,engine=engine,work=work/'plan-0',as_of=as_of,
        request_budget=request_budget,seed_inventories=seed_inventories,cutoff_urls=cutoff_urls)
    stats['initial_counts']=plan['counts'];seed_files=plan['seed_files']
    pending=iter(_records(plan['queue']))
    pace=pace or HostPacer(PACING)
    try:
        while True:
            if request_budget-stats['requests']<hops:
                stats['stop_reason']='request_budget';break
            limit,reserved=_allowance(byte_budget-stats['fetched_bytes'],spool_budget,archive_limits,hops)
            if limit<=0:
                stats['stop_reason']='byte_or_spool_budget';break
            stats['spool_reserved_bound']=max(stats['spool_reserved_bound'],reserved)
            row=next(pending,None)
            if row is None:stats['stop_reason']='queue_empty';break
            url=row['requested_url']
            try:validate_record(url)
            except ValueError:
                stats['refusals'].append(dict(reason='unsafe_recorded_url'))
                continue
            family=policy.family(url)
            if family is None:
                stats['refusals'].append(dict(url=url,reason='outside_capture_scope'));continue
            observations=[dict(url=value[0],source=value[1],pointer=json.loads(value[2]))
                          for value in map(json.loads,row['observations'])]
            with TemporaryDirectory(prefix='body-',dir=work) as spool:
                fetcher=Fetcher(scope=policy,direct=_Counted(direct,stats),
                    provider=_Counted(provider,stats) if provider is not None else None,
                    pace=pace,directory=spool,spool_limit=limit,headers=headers)
                result=fetcher.fetch(url)
                key,line=writer.write(result,family=family,observations=observations)
                stats['receipts'].append(key);stats['captures']+=1
                if row['priority']==1:
                    stats['cutoffs'].append(dict(url=url,outcome=line['outcome'],complete=result.final.complete,
                        reason=result.final.error))
                import gzip
                with gzip.open(attempted,'at',encoding='utf-8') as out:out.write(json.dumps(dict(url=url))+'\n')
                body=result.final.body;links=[]
                if (body is not None and result.final.complete and result.final.http_status is not None
                        and 200<=result.final.http_status<300 and body.sniffed_format in {'html','xml','json'}):
                    if body.size>PAGE_BYTES:
                        stats['discovery_errors'].append(dict(url=url,reason='discovery_size_limit'))
                    else:
                        facts=discover(body.path.read_bytes(),body.sniffed_format)
                        if facts['status']!='completed':
                            stats['discovery_errors'].append(dict(url=url,reason=facts['error_type']))
                        else:
                            for index,link in enumerate(facts['links']):
                                if (not _safe_reference(link['href']) or facts['base_href'] is not None
                                        and not _safe_reference(facts['base_href'])):
                                    stats['discovery_refused']+=1
                                    continue
                                links.append(dict(href=link['href'],base_href=facts['base_href'],context=result.final.url,
                                    source=key,pointer=json.dumps([index])))
                # The surrounding spool owns every original attempt file and
                # removes them only after body+receipt storage has completed.
            if links:
                if generation>=max_discovery_jobs:
                    stats['stop_reason']='discovery_job_budget';break
                generation+=1
                entry=json_input(work,f'discovered-{generation}',links,href='Utf8',base_href='Utf8',context='Utf8',source='Utf8',pointer='Utf8')
                discovered.extend(entry['files'])
                plan=plan_queue(release,engine=engine,work=work/f'plan-{generation}',as_of=as_of,
                    request_budget=request_budget-stats['requests'],seed_files=seed_files,
                    discovery_files=discovered,attempted=attempted,cutoff_urls=cutoff_urls)
                pending=iter(_records(plan['queue']))
        return stats
    except Exception as error:
        stats.update(stop_reason='error',error_type=type(error).__name__)
        raise
    finally:
        stats['discovery_jobs']=generation
        (work/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
