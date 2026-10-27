"""Public release scheduling and bounded, append-only raw capture."""
from datetime import datetime, timezone
from contextlib import ExitStack
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
from congress_api.models.archive_profile import RULE_FIELDS, validate_capture_profile
from congress_api.acquisition.fetcher import CaptureScope, Fetcher, HostPacer
from congress_api.retention.archive_members import ZipLimits
from congress_api.retention.body_store import validate_record
from congress_api.retention.pipeline_raw import new_run_id
from congress_api.retention.provenance import field, json_input, parquet_output, run_job
from congress_api.retention.receipt_writer import ReceiptWriter
from congress_api.retention.receipt_privacy import credential_parameters

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
    """Select one public release once; verify all release-pinned scheduler inputs."""
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
    for name in ('url_state.parquet','capture_scope.json','capture_profile.json','url_variants.parquet'):
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
    return dict(release_id=release_id,state=selected['url_state.parquet'],scope=selected['capture_scope.json'],
        profile=selected['capture_profile.json'],variants=selected['url_variants.parquet'],
        origin='public' if pointer else 'local',
        identities={name:next(row for row in files if row['name']==name) for name in selected})


def _records(path):
    with pq.ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=64):
            yield from batch.to_pylist()


def _url_binding(release,engine):
    """Bind SQL, rules, variants and engine to the selected immutable release."""
    overrides=('url_keys_sql','url_normalized_sql','url_key_inputs')
    if release.get('origin')!='local' and any(name in release for name in overrides):
        raise ValueError('Public release URL identity overrides are forbidden')
    for key,name in [('state','url_state.parquet'),('scope','capture_scope.json'),
                     ('profile','capture_profile.json'),('variants','url_variants.parquet')]:
        _identity(release[key],release['identities'][name])
    profile=validate_capture_profile(json.loads(Path(release['profile']).read_text()),
        engine_revision=engine.source_revision)
    definitions={}
    for name in ('url_normalized','url_keys'):
        definitions[name]=profile['sql'][name]['text']
        override=release.get(name+'_sql')
        if override is not None:
            if not Path(override).is_file():raise ValueError('Authored url_key SQL is unavailable')
            definitions[name]=Path(override).read_text()
    inputs=release.get('url_key_inputs')
    if inputs is not None and (not isinstance(inputs,list) or any(not isinstance(item,dict) for item in inputs)):
        raise ValueError('Authored url_key profile inputs must be native input declarations')
    binding=dict(sql=definitions,rules=profile['url_rules'],variants_sha256=release['identities']['url_variants.parquet']['sha256'],
        engine_revision=profile['engine_revision'],authored_inputs=inputs)
    digest=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if release.get('url_key_definition_sha256',digest)!=digest:
        raise ValueError('Capture profile changed within the capture run')
    return binding,digest


def _profile_inputs(release,binding,work):
    if binding['authored_inputs'] is not None:return binding['authored_inputs']
    return [json_input(work,'url_rules',binding['rules'],**{name:'Utf8' for name in RULE_FIELDS}),
            dict(name='url_variants',kind='parquet',path=str(Path(release['variants']).resolve()))]


def _key_steps(binding,sources):
    union=' UNION ALL '.join(f"SELECT {_literal(prefix+':')} || {column} AS input_id,{column} AS url FROM {name}"
        for name,prefix,column in sources)
    return [dict(name='url_inputs',sql=f'SELECT DISTINCT input_id,url FROM ({union}) WHERE url IS NOT NULL'),
        dict(name='url_normalized',sql=binding['sql']['url_normalized'],materialize=True),
        dict(name='url_keys',sql=binding['sql']['url_keys'],materialize=True)]


def _key_queries():
    return [dict(name='invalid_url_keys',sql='''SELECT count(*) AS violations FROM url_inputs i
        FULL JOIN url_keys k ON i.input_id=k.input_id WHERE i.input_id IS NULL OR k.input_id IS NULL
        OR (k.url IS DISTINCT FROM i.url) OR k.url_key IS NULL OR k.url_key='' '''),
        dict(name='duplicate_url_keys',sql='''SELECT count(*) AS violations FROM
            (SELECT input_id FROM url_keys GROUP BY input_id HAVING count(*)>1)''')]


def _check_keys(values):
    if any(values[name][0]['violations'] for name in ('invalid_url_keys','duplicate_url_keys')):
        raise ValueError('Shared url_key definition did not preserve one key per input')


def _reviewed_cutoffs(urls):
    urls=tuple(urls)
    if len(urls)>1024 or any(not isinstance(url,str) or not url or len(url.encode('utf-8'))>16384 for url in urls):
        raise ValueError('Reviewed cutoff input exceeds its metadata allowance')
    for url in urls:
        validate_record(url)
    return urls


def _record_attempt(path,url,*,attempted,complete=None,outcome=None,http_status=None,error_type=None):
    import gzip
    with gzip.open(path,'at',encoding='utf-8') as out:
        out.write(json.dumps(dict(url=url,attempted=attempted,complete=complete,outcome=outcome,
            http_status=http_status,error_type=error_type))+'\n')


def cutoff_report(release,*,urls,attempted,engine,work,as_of,stop_reason):
    """Account for every reviewed URL, including deadline/budget/scope deferrals."""
    urls=_reviewed_cutoffs(urls)
    if not urls:return []
    binding,_=_url_binding(release,engine)
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    policy=CapturePolicy(release['scope'])
    inputs=[dict(name='states',kind='parquet',path=str(Path(release['state']).resolve())),
        json_input(work,'cutoffs',(dict(url=url) for url in urls),url='Utf8'),
        dict(name='attempted',kind='json_lines',
            files=[dict(key='attempted',path=str(attempted))] if attempted.exists() else [],
            schema=dict(fields=[field('url','Utf8'),field('attempted','Boolean'),field('complete','Boolean'),
                field('outcome','Utf8'),field('http_status','Int32'),field('error_type','Utf8')],metadata={}))]
    inputs.extend(_profile_inputs(release,binding,work))
    steps=_key_steps(binding,[('states','state','requested_url'),('attempted','attempted','url'),('cutoffs','cutoff','url')])
    steps.extend([dict(name='selected_states',sql=f"""SELECT s.requested_url,s.next_attempt_at,
        {policy.sql('s.requested_url')} AS family,k.url_key FROM states s JOIN url_keys k
        ON k.input_id='state:' || s.requested_url"""),
        dict(name='selected_attempts',sql="""SELECT a.*,k.url_key FROM attempted a JOIN url_keys k
            ON k.input_id='attempted:' || a.url"""),
        dict(name='reviewed_cutoffs',sql="""SELECT DISTINCT c.url,k.url_key FROM cutoffs c JOIN url_keys k
            ON k.input_id='cutoff:' || c.url""")])
    values=run_job(work,engine,inputs=inputs,outputs=[],steps=steps,
        queries=[*_key_queries(),dict(name='cutoffs',sql=f"""SELECT requested_url,disposition,reason,
            next_attempt_at,complete,outcome,http_status FROM (SELECT k.url AS requested_url,
            CASE WHEN a.attempted THEN 'attempted'
                 WHEN a.url IS NOT NULL OR s.requested_url IS NOT NULL AND s.family IS NULL THEN 'refused'
                 ELSE 'deferred' END AS disposition,
            CASE WHEN a.url IS NOT NULL THEN a.error_type
                 WHEN s.requested_url IS NULL THEN 'not_in_release'
                 WHEN s.family IS NULL THEN 'outside_capture_scope'
                 WHEN s.next_attempt_at>to_timestamp({_literal(_utc(as_of))}) THEN 'not_due'
                 ELSE {_literal(stop_reason or 'not_attempted')} END AS reason,
            s.next_attempt_at,a.complete,a.outcome,a.http_status,
            row_number() OVER(PARTITION BY k.url ORDER BY CASE WHEN k.url=s.requested_url THEN 0 ELSE 1 END,
                s.next_attempt_at DESC NULLS LAST,s.requested_url) AS ordinal
            FROM reviewed_cutoffs k LEFT JOIN selected_states s ON k.url_key=s.url_key
            LEFT JOIN selected_attempts a ON k.url_key=a.url_key) WHERE ordinal=1 ORDER BY requested_url""")])
    _check_keys(values)
    return values['cutoffs']


def plan_queue(release,*,engine,work,as_of,request_budget,seed_inventories=(),
               seed_files=(),discovery_files=(),attempted=None,cutoff_urls=()):
    """Use shared URL keys for matching, retaining literal requested URL outputs."""
    _positive(request_budget,'request budget');as_of=_utc(as_of)
    cutoff_urls=_reviewed_cutoffs(cutoff_urls)
    binding,definition_sha256=_url_binding(release,engine)
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
    inputs.extend(_profile_inputs(release,binding,work))
    steps=[dict(name='seed_rows',sql="""SELECT url,source,pointer FROM seeds UNION ALL
        SELECT url_resolve(href,coalesce(url_resolve(base_href,context),context)) AS url,source,pointer FROM discovery""")]
    steps.extend(_key_steps(binding,[('states','state','requested_url'),('seed_rows','seed','url'),
        ('attempted','attempted','url'),('cutoffs','cutoff','url')]))
    steps.extend([dict(name='keyed_states',sql="""SELECT s.*,k.url_key FROM states s JOIN url_keys k
        ON k.input_id='state:' || s.requested_url"""),
        dict(name='keyed_seeds',sql="""SELECT s.*,k.url_key FROM seed_rows s JOIN url_keys k
            ON k.input_id='seed:' || s.url"""),
        dict(name='keyed_attempts',sql="""SELECT DISTINCT k.url_key FROM attempted a JOIN url_keys k
            ON k.input_id='attempted:' || a.url"""),
        dict(name='keyed_cutoffs',sql="""SELECT DISTINCT k.url_key FROM cutoffs c JOIN url_keys k
            ON k.input_id='cutoff:' || c.url"""),
        dict(name='observations',sql="""SELECT url_key,min(url) AS url,array_agg(DISTINCT json_array(url,source,pointer)
            ORDER BY json_array(url,source,pointer)) AS observations FROM keyed_seeds GROUP BY url_key"""),
        dict(name='candidates',sql=f"""SELECT requested_url,attempts,cast(last_outcome AS VARCHAR) AS last_outcome,next_attempt_at,
                coalesce(o.observations,make_array(json_array(requested_url,{_literal('release:'+release['release_id'])},'[]'))) AS observations,s.url_key
            FROM keyed_states s LEFT JOIN observations o ON s.url_key=o.url_key
            UNION ALL SELECT o.url AS requested_url,0 AS attempts,cast(NULL AS VARCHAR) AS last_outcome,
                cast(NULL AS TIMESTAMP) AS next_attempt_at,o.observations,o.url_key
            FROM observations o LEFT ANTI JOIN keyed_states s ON o.url_key=s.url_key"""),
        dict(name='scoped',sql=f"""SELECT c.*,{policy.sql('requested_url')} AS family,
            CASE WHEN attempts=0 THEN 0 WHEN last_outcome='size_limit' OR k.url_key IS NOT NULL
            THEN 1 ELSE 2 END AS priority FROM candidates c LEFT JOIN keyed_cutoffs k ON c.url_key=k.url_key
            LEFT ANTI JOIN keyed_attempts a ON c.url_key=a.url_key"""),
        dict(name='eligible',sql=f"SELECT * FROM scoped WHERE family IS NOT NULL AND (next_attempt_at IS NULL OR next_attempt_at<=to_timestamp({_literal(as_of)}))"),
        dict(name='due',sql="""SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY url_key
            ORDER BY priority,next_attempt_at NULLS FIRST,requested_url) AS ordinal FROM eligible) WHERE ordinal=1""")])
    values=run_job(work,engine,inputs=inputs,steps=steps,outputs=[parquet_output(work,'queue',
        f'SELECT requested_url,family,priority,next_attempt_at,observations FROM due ORDER BY priority,next_attempt_at NULLS FIRST,requested_url LIMIT {request_budget}',
        ['priority','next_attempt_at','requested_url'])],queries=[
        *_key_queries(),dict(name='counts',sql="SELECT count(*) AS due,count(*) FILTER(WHERE priority=0) AS queue,count(*) FILTER(WHERE priority=1) AS cutoffs FROM due"),
        dict(name='bad_states',sql="SELECT count(*) AS violations FROM states WHERE requested_url IS NULL OR attempts IS NULL OR attempts<0 OR octet_length(requested_url)>16384"),
        dict(name='large_observations',sql='SELECT count(*) AS violations FROM observations WHERE array_length(observations)>256'),
        dict(name='duplicates',sql='SELECT count(*) AS violations FROM (SELECT requested_url FROM states GROUP BY requested_url HAVING count(*)>1)')])
    _check_keys(values)
    if any(values[name][0]['violations'] for name in ('bad_states','duplicates','large_observations')):
        raise ValueError('Invalid or duplicate url_state rows')
    return dict(queue=str(work/'queue.parquet'),counts=values['counts'][0],release_id=release['release_id'],
                as_of=as_of,seed_files=files,url_key_definition_sha256=definition_sha256)


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


def read_discovery_payload(payload):
    """Shared worker entry; bound and verify the owned file before parsing."""
    from congress_api.parsers.archive_readings import read_page
    payload=json.loads(payload.decode('utf-8'))
    path=Path(payload['path'])
    if path.stat().st_size!=payload['bytes'] or payload['bytes']>PAGE_BYTES:
        raise ValueError('Discovery input exceeds or differs from its declared bytes')
    with path.open('rb') as source:body=source.read(PAGE_BYTES+1)
    if len(body)!=payload['bytes'] or hashlib.sha256(body).hexdigest()!=payload['sha256']:
        raise ValueError('Discovery input changed after raw storage')
    return read_page(body,payload['parser'])


def run_capture(release,*,engine,work,as_of,request_budget,byte_budget,spool_budget,
                store,identity,direct,provider=None,resolve=resolve_host,pace=None,
                archive_limits=None,seed_inventories=(),cutoff_urls=(),
                discover=None,max_discovery_jobs=8,headers=None,worker_factory=None):
    """One sequential raw writer. No state/index or table writes occur here."""
    for name,value in [('request budget',request_budget),('byte budget',byte_budget),('spool budget',spool_budget),('discovery jobs',max_discovery_jobs)]:
        _positive(value,name)
    _,url_key_digest=_url_binding(release,engine)
    release=dict(release,url_key_definition_sha256=url_key_digest)
    if discover is None and worker_factory is None:
        try:
            from congress_api.retention.parser_worker import ParserWorker
        except ModuleNotFoundError as error:
            if error.name!='congress_api.retention.parser_worker':raise
            raise ValueError('Shared bounded discovery worker is unavailable') from None
        worker_factory=ParserWorker
    as_of=_utc(as_of);cutoff_urls=_reviewed_cutoffs(cutoff_urls)
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    policy=CapturePolicy(release['scope'],resolve=resolve);policy.require_capture()
    archive_limits=archive_limits or ZipLimits();hops=14 if provider is not None else 7
    stats=dict(release_id=release['release_id'],as_of=as_of,run_id=new_run_id(),requests=0,
        fetched_bytes=0,captures=0,receipts=[],refusals=[],discovery_errors=[],discovery_refused=0,cutoffs=[],cutoff_attempts=[],
        budgets=dict(requests=request_budget,bytes=byte_budget,spool=spool_budget),spool_reserved_bound=0,
        url_key_definition_sha256=url_key_digest,stop_reason=None)
    writer=ReceiptWriter(store,identity=identity,run_id=stats['run_id'],write_date=datetime.now(timezone.utc).date().isoformat(),archive_limits=archive_limits)
    attempted=work/'attempted.jsonl.gz';discovered=[];generation=0
    workers={};worker_stack=ExitStack()
    worker_version=hashlib.sha256(json.dumps(['capture-discovery',identity['commit'],
        identity['lockfile_digest']],separators=(',',':')).encode()).hexdigest()
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
                stats['refusals'].append(dict(url=url,reason='outside_capture_scope'))
                _record_attempt(attempted,url,attempted=False,error_type='outside_capture_scope')
                continue
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
                    stats['cutoff_attempts'].append(dict(url=url,outcome=line['outcome'],complete=result.final.complete,
                        reason=result.final.error))
                _record_attempt(attempted,url,attempted=True,complete=result.final.complete,
                    outcome=line['outcome'],http_status=line['http_status'],error_type=result.final.error)
                body=result.final.body;links=[]
                if (body is not None and result.final.complete and result.final.http_status is not None
                        and 200<=result.final.http_status<300 and body.sniffed_format in {'html','xml','json'}):
                    if body.size>PAGE_BYTES:
                        stats['discovery_errors'].append(dict(url=url,reason='discovery_size_limit'))
                    else:
                        if discover is not None:
                            facts=discover(body.path.read_bytes(),body.sniffed_format)
                        else:
                            parser=body.sniffed_format
                            if parser not in workers:
                                workers[parser]=worker_stack.enter_context(worker_factory(parser,worker_version,
                                    'congress_api.acquisition.capture_scheduler:read_discovery_payload',
                                    timeout_seconds=30,memory_bytes=512<<20,max_input_bytes=PAGE_BYTES+16384))
                            outcome=workers[parser].parse(body.sha256,json.dumps(dict(path=str(body.path),bytes=body.size,
                                sha256=body.sha256,parser=parser),ensure_ascii=False,separators=(',',':')).encode('utf-8'))
                            if outcome['status'] in {'unreadable','size_limit'}:
                                facts=dict(status='error',error_type=outcome.get('reason',outcome['status']))
                            elif outcome['status']=='completed':facts=outcome['value']
                            else:raise ValueError('Invalid bounded discovery worker result')
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
        # D discovery replans plus initial planning and this report give D+2
        # linear input passes (ten at the default D=8), not one per capture.
        try:
            worker_stack.close()
            stats['cutoffs']=cutoff_report(release,urls=cutoff_urls,attempted=attempted,engine=engine,
                work=work/'cutoff-report',as_of=as_of,stop_reason=stats['stop_reason'])
        finally:
            (work/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')
