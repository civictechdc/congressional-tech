"""Public release scheduling and bounded, append-only raw capture."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from dataclasses import replace
from contextlib import ExitStack
import hashlib
from itertools import chain
import json
import os
import resource
from pathlib import Path
import re
import socket
import threading
from urllib.parse import parse_qsl, urljoin, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.acquisition.admission import AdmissionDenied
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
        if len(value.encode('utf-8'))>16384 or any(ord(c)<0x20 or ord(c)==0x7f for c in value):return False
        validate_record(value)
        parts=urlsplit(value)
        if parts.scheme.lower() not in {'','http','https'} or (parts.scheme and not parts.hostname):
            return False
        names={row['parameter'].casefold() for row in credential_parameters()}
        return (parts.username is None and parts.password is None and
            not any(name.casefold() in names for name,_ in parse_qsl(parts.query,keep_blank_values=True)))
    except (ValueError,UnicodeError):
        return False


def _require_capture_authority(release):
    """Display-only releases never authorize queue work or network capture."""
    origins=(release,release.get('origin'),release.get('manifest_origin'))
    if any(isinstance(origin,dict) and (origin.get('kind')=='seed_v5'
            or origin.get('display_only') is True) for origin in origins):
        raise ValueError('A display-only release cannot authorize capture')


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
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
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
    _require_capture_authority(manifest)
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
        origin='public' if pointer else 'local',manifest_origin=manifest.get('origin'),
        identities={name:next(row for row in files if row['name']==name) for name in selected})


def _records(path):
    with pq.ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=64):
            yield from batch.to_pylist()


def _url_binding(release,engine):
    """Bind SQL, rules, variants and engine to the selected immutable release."""
    _require_capture_authority(release)
    for key,name in [('state','url_state.parquet'),('scope','capture_scope.json'),
                     ('profile','capture_profile.json'),('variants','url_variants.parquet')]:
        _identity(release[key],release['identities'][name])
    profile=validate_capture_profile(json.loads(Path(release['profile']).read_text()),
        engine_revision=engine.source_revision)
    definitions={name:profile['sql'][name]['text'] for name in ('url_normalized','url_keys')}
    binding=dict(sql=definitions,rules=profile['url_rules'],variants_sha256=release['identities']['url_variants.parquet']['sha256'],
        engine_revision=profile['engine_revision'])
    digest=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    if release.get('url_key_definition_sha256',digest)!=digest:
        raise ValueError('Capture profile changed within the capture run')
    return binding,digest


def _profile_inputs(release,binding,work):
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


def cutoff_report(release,*,urls,attempted,engine,work,as_of,stop_reason,_keyed_states_cache=None):
    """Account for every reviewed URL, including deadline/budget/scope deferrals."""
    _require_capture_authority(release)
    urls=_reviewed_cutoffs(urls)
    if not urls:return []
    binding,_=_url_binding(release,engine)
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    policy=CapturePolicy(release['scope'])
    reuse_keyed_states=_keyed_states_cache is not None and Path(_keyed_states_cache).is_file()
    inputs=[dict(name='keyed_states' if reuse_keyed_states else 'states',kind='parquet',
                 path=str(Path(_keyed_states_cache if reuse_keyed_states else release['state']).resolve())),
        json_input(work,'cutoffs',(dict(url=url) for url in urls),url='Utf8'),
        dict(name='attempted',kind='json_lines',
            files=[dict(key='attempted',path=str(attempted))] if attempted.exists() else [],
            schema=dict(fields=[field('url','Utf8'),field('attempted','Boolean'),field('complete','Boolean'),
                field('outcome','Utf8'),field('http_status','Int32'),field('error_type','Utf8')],metadata={}))]
    inputs.extend(_profile_inputs(release,binding,work))
    key_sources=[('attempted','attempted','url'),('cutoffs','cutoff','url')]
    if not reuse_keyed_states:
        key_sources.insert(0,('states','state','requested_url'))
    steps=_key_steps(binding,key_sources)
    selected_states_sql=(f"SELECT s.requested_url,s.next_attempt_at,{policy.sql('s.requested_url')} AS family,s.url_key FROM keyed_states s"
        if reuse_keyed_states else
        f"""SELECT s.requested_url,s.next_attempt_at,
        {policy.sql('s.requested_url')} AS family,k.url_key FROM states s JOIN url_keys k
        ON k.input_id='state:' || s.requested_url""")
    steps.extend([dict(name='selected_states',sql=selected_states_sql),
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
               seed_files=(),discovery_files=(),attempted=None,cutoff_urls=(),_keyed_states_cache=None,campaign=None):
    """Use shared URL keys for matching, retaining literal requested URL outputs."""
    _require_capture_authority(release)
    _positive(request_budget,'request budget');as_of=_utc(as_of)
    cutoff_urls=_reviewed_cutoffs(cutoff_urls)
    binding,definition_sha256=_url_binding(release,engine)
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
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
    profile=validate_capture_profile(json.loads(Path(release['profile']).read_text()),engine_revision=engine.source_revision)
    recovery_eligibility=profile['version']==2
    if recovery_eligibility and not {'capture_disposition','capture_reason','capture_decision_id'}.issubset(schema.names):
        raise ValueError('Version 2 capture requires explicit eligibility fields')
    if campaign is not None:
        profile=validate_capture_profile(json.loads(Path(release['profile']).read_text()),engine_revision=engine.source_revision)
        if profile['version'] != 2:
            raise ValueError('Campaign capture requires a recovery-bound version 2 profile')
        requirement_pins=[pin for pin in campaign.tables.values() if pin.sha256 == profile['recovery_policy']['requirements_sha256']]
        if not requirement_pins:
            raise ValueError('Campaign does not pin the profile recovery requirements')
        requirements_path=requirement_pins[0].path
        if not {'capture_disposition','capture_reason','capture_decision_id'}.issubset(schema.names):
            raise ValueError('Campaign capture requires explicit eligibility fields')
        target_path=campaign.table_path(campaign.target_table)
        candidate_path=campaign.table_path(campaign.candidate_table)
        for path,columns in ((target_path,{'target_url'}),(candidate_path,{'target_url','candidate_url'}),
                             (requirements_path,{'original_url','target_requirement','acceptance_policy'})):
            table_schema=pq.read_schema(path)
            if not columns.issubset(table_schema.names) or any(not pa.types.is_string(table_schema.field(c).type) for c in columns):
                raise ValueError('Invalid campaign table schema')
        campaign.require_custody()
    reuse_keyed_states=_keyed_states_cache is not None and Path(_keyed_states_cache).is_file()
    export_keyed_states=_keyed_states_cache is not None and not reuse_keyed_states
    inputs=[dict(name='keyed_states' if reuse_keyed_states else 'states',kind='parquet',
                 path=str(Path(_keyed_states_cache if reuse_keyed_states else release['state']).resolve()))]
    if campaign is not None:
        inputs.extend([dict(name='campaign_targets',kind='parquet',path=str(target_path)),
                       dict(name='campaign_candidates',kind='parquet',path=str(candidate_path)),
                       dict(name='campaign_requirements',kind='parquet',path=str(requirements_path))])
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
    campaign_seeds = " UNION ALL SELECT target_url AS url,'campaign' AS source,'[]' AS pointer FROM campaign_targets" if campaign is not None else ''
    steps=[dict(name='seed_rows',sql="""SELECT url,source,pointer FROM seeds UNION ALL
        SELECT url_resolve(href,coalesce(url_resolve(base_href,context),context)) AS url,source,pointer FROM discovery"""+campaign_seeds)]
    key_sources=[('seed_rows','seed','url'),('attempted','attempted','url'),('cutoffs','cutoff','url')]
    if not reuse_keyed_states:
        key_sources.insert(0,('states','state','requested_url'))
    steps.extend(_key_steps(binding,key_sources))
    if not reuse_keyed_states:
        steps.append(dict(name='keyed_states',sql="""SELECT s.*,k.url_key FROM states s JOIN url_keys k
            ON k.input_id='state:' || s.requested_url"""))
    disposition = 's.capture_disposition' if recovery_eligibility else 'cast(NULL AS VARCHAR)'
    campaign_filter = " AND (capture_disposition IS NULL OR capture_disposition='eligible')" if recovery_eligibility else ''
    if campaign is not None:campaign_filter+=" AND EXISTS (SELECT 1 FROM campaign_targets t WHERE t.target_url=scoped.requested_url)"
    steps.extend([
        dict(name='keyed_seeds',sql="""SELECT s.*,k.url_key FROM seed_rows s JOIN url_keys k
            ON k.input_id='seed:' || s.url"""),
        dict(name='keyed_attempts',sql="""SELECT DISTINCT k.url_key FROM attempted a JOIN url_keys k
            ON k.input_id='attempted:' || a.url"""),
        dict(name='keyed_cutoffs',sql="""SELECT DISTINCT k.url_key FROM cutoffs c JOIN url_keys k
            ON k.input_id='cutoff:' || c.url"""),
        dict(name='observations',sql="""SELECT url_key,min(url) AS url,array_agg(DISTINCT json_array(url,source,pointer)
            ORDER BY json_array(url,source,pointer)) AS observations FROM keyed_seeds GROUP BY url_key"""),
        dict(name='seed_urls',sql="""SELECT url_key,min(url) AS url FROM keyed_seeds GROUP BY url_key"""),
        dict(name='candidates',sql=f"""SELECT requested_url,attempts,cast(last_outcome AS VARCHAR) AS last_outcome,next_attempt_at,s.url_key,{disposition} AS capture_disposition
            FROM keyed_states s
            UNION ALL SELECT o.url AS requested_url,0 AS attempts,cast(NULL AS VARCHAR) AS last_outcome,
                cast(NULL AS TIMESTAMP) AS next_attempt_at,o.url_key,cast(NULL AS VARCHAR) AS capture_disposition
            FROM seed_urls o LEFT ANTI JOIN keyed_states s ON o.url_key=s.url_key"""),
        dict(name='scoped',sql=f"""SELECT c.*,{policy.sql('requested_url')} AS family,
            CASE WHEN attempts=0 THEN 0 WHEN last_outcome='size_limit' OR k.url_key IS NOT NULL
            THEN 1 WHEN last_outcome IN ('stored','unchanged') AND next_attempt_at IS NULL THEN 3 ELSE 2 END AS priority
            FROM candidates c LEFT JOIN keyed_cutoffs k ON c.url_key=k.url_key
            LEFT ANTI JOIN keyed_attempts a ON c.url_key=a.url_key"""),
        dict(name='eligible',sql=f"SELECT * FROM scoped WHERE family IS NOT NULL AND (next_attempt_at IS NULL OR next_attempt_at<=to_timestamp({_literal(as_of)})){campaign_filter}"),
        dict(name='due',sql="""SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY url_key
            ORDER BY priority,next_attempt_at NULLS FIRST,requested_url) AS ordinal FROM eligible) WHERE ordinal=1"""),
        dict(name='top_due',sql=f"""SELECT requested_url,family,priority,next_attempt_at,url_key FROM due
            ORDER BY priority,next_attempt_at NULLS FIRST,requested_url LIMIT {request_budget}""")])
    outputs=[parquet_output(work,'queue',
        f"""SELECT d.requested_url,d.family,d.priority,d.next_attempt_at,
            coalesce(o.observations,make_array(json_array(d.requested_url,{_literal('release:'+release['release_id'])},'[]'))) AS observations
            FROM top_due d LEFT JOIN observations o ON d.url_key=o.url_key
            ORDER BY d.priority,d.next_attempt_at NULLS FIRST,d.requested_url""",
        ['priority','next_attempt_at','requested_url'])]
    if export_keyed_states:
        outputs.append(parquet_output(work,'keyed_states',
            f"""SELECT requested_url,attempts,cast(last_outcome AS VARCHAR) AS last_outcome,next_attempt_at,url_key{',capture_disposition,capture_reason,capture_decision_id' if recovery_eligibility else ''}
               FROM keyed_states ORDER BY url_key,requested_url""",
            ['url_key','requested_url']))
    states_table='keyed_states' if reuse_keyed_states else 'states'
    eligibility_invalid=" OR capture_disposition IS NULL OR capture_disposition NOT IN ('eligible','satisfied','excluded')" if recovery_eligibility else ''
    campaign_queries=[]
    if campaign is not None:
        campaign_queries=[dict(name='bad_campaign_targets',sql="SELECT count(*) AS violations FROM campaign_targets WHERE target_url IS NULL OR target_url=''"),
            dict(name='duplicate_campaign_targets',sql="SELECT count(*) AS violations FROM (SELECT target_url FROM campaign_targets GROUP BY target_url HAVING count(*)>1)"),
            dict(name='bad_campaign_candidates',sql="SELECT count(*) AS violations FROM campaign_candidates c LEFT ANTI JOIN campaign_targets t ON c.target_url=t.target_url"),
            dict(name='null_campaign_candidates',sql="SELECT count(*) AS violations FROM campaign_candidates WHERE target_url IS NULL OR candidate_url IS NULL OR candidate_url=''"),
            dict(name='bad_campaign_requirements',sql=f"SELECT count(*) AS violations FROM campaign_requirements r JOIN campaign_targets t ON r.original_url=t.target_url WHERE r.target_requirement IS NULL OR r.acceptance_policy IS NULL OR r.target_requirement<>{_literal(campaign.requirement)} OR r.acceptance_policy<>{_literal(profile['recovery_policy']['acceptance_policy'])}"),
            dict(name='bad_campaign_state',sql=f"SELECT count(*) AS violations FROM {states_table} WHERE capture_disposition IS NULL OR capture_disposition NOT IN ('eligible','satisfied','excluded')")]
    values=run_job(work,engine,inputs=inputs,steps=steps,outputs=outputs,queries=[
        *campaign_queries,
        *_key_queries(),dict(name='counts',sql="SELECT count(*) AS due,count(*) FILTER(WHERE priority=0) AS queue,count(*) FILTER(WHERE priority=1) AS cutoffs FROM due"),
        dict(name='bad_states',sql=f"SELECT count(*) AS violations FROM {states_table} WHERE requested_url IS NULL OR attempts IS NULL OR attempts<0 OR octet_length(requested_url)>16384{eligibility_invalid}"),
        dict(name='large_observations',sql='SELECT count(*) AS violations FROM observations WHERE array_length(observations)>256'),
        dict(name='duplicates',sql=f'SELECT count(*) AS violations FROM (SELECT requested_url FROM {states_table} GROUP BY requested_url HAVING count(*)>1)')])
    _check_keys(values)
    if campaign is not None:
        campaign.require_custody()
        if any(values[q['name']][0]['violations'] for q in campaign_queries):
            raise ValueError('Invalid campaign membership or eligibility')
    if any(values[name][0]['violations'] for name in ('bad_states','duplicates','large_observations')):
        raise ValueError('Invalid or duplicate url_state rows')
    return dict(queue=str(work/'queue.parquet'),counts=values['counts'][0],release_id=release['release_id'],
                as_of=as_of,seed_files=files,url_key_definition_sha256=definition_sha256)


def _provider_terminal(transport,status,error):
    return transport!='direct' and (status in {401,402,403,429} or error in {
        'provider_quota','provider_credits','provider_http_error','invalid_provider_response'})


class _Counted:
    def __init__(self,adapter,stats,admission,kind,cost,entity_limit,wire,spool_guard,provider_state):
        self.adapter,self.stats,self.admission,self.kind,self.cost=adapter,stats,admission,kind,cost
        self.entity_limit=entity_limit;self.wire=wire;self.spool_guard=spool_guard;self.provider_state=provider_state
    def hop(self,url,destination,*,limit,headers):
        from congress_api.acquisition.capture_journal import UnknownRemoteOutcome
        lock,disabled=self.provider_state
        # Account-state observation and admission form one atomic boundary.
        # Network calls already admitted can finish outside this short lock.
        with lock:
            if disabled:
                error=AdmissionDenied('Network admission is deferred after a terminal or uncertain response')
                error.resource='unknown' if '*' in disabled else 'provider'
                raise error
            self.spool_guard()
            allowance=min(limit,self.entity_limit) if self.kind=='direct' else limit
            wire_attempt=self.wire.reserve(self.kind,allowance)
            self.last_wire_attempt=wire_attempt
            try:attempt=self.admission.reserve(self.kind,self.cost)
            except AdmissionDenied:
                self.wire.settle(wire_attempt,0)
                raise
            self.last_attempt=attempt
        self.stats['requests']+=1
        try:
            result=self.adapter.hop(url,destination,limit=allowance,headers=headers)
        except Exception:
            with lock:disabled.add('*')
            raise
        from congress_api.transport.raw_adapters import network_outcome_unknown
        if network_outcome_unknown(result):
            with lock:disabled.add('*')
            raise UnknownRemoteOutcome('Uncertain network response retains its reservation')
        if _provider_terminal(self.kind,result.provider_status,result.error):
            with lock:disabled.add(self.kind)
        # Keep a conservative upper cost until authoritative billing replaces it.
        self.admission.settle(attempt,self.cost)
        delivered=result.wire_bytes if result.wire_bytes is not None else result.size if result.size is not None else destination.stat().st_size
        self.wire.settle(wire_attempt,delivered)
        self.stats['fetched_bytes']+=delivered
        return replace(result,wire_bytes=delivered)


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


def _run_capture(release,*,engine,work,as_of,request_budget,byte_budget,spool_budget,
                store,identity,direct,provider=None,resolve=resolve_host,pace=None,
                archive_limits=None,seed_inventories=(),cutoff_urls=(),
                discover=None,max_discovery_jobs=8,headers=None,worker_factory=None,workers=1,campaign=None,
                admission=None,provider_cost=None,firecrawl=None,firecrawl_cost=None,max_entity_bytes=16<<20):
    """Bounded raw writer. No state/index or table writes occur here."""
    _require_capture_authority(release)
    for name,value in [('request budget',request_budget),('byte budget',byte_budget),('spool budget',spool_budget),('discovery jobs',max_discovery_jobs),('workers',workers)]:
        _positive(value,name)
    if type(max_entity_bytes) is not int or not 0<max_entity_bytes<=16<<20:
        raise ValueError('Capture entity capacity is qualified only through 16MiB')
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
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    from congress_api.acquisition.admission import Admission
    for adapter,cost in ((provider,provider_cost),(firecrawl,firecrawl_cost)):
        if adapter is not None and (type(cost) is not int or cost <= 0 or admission is None):
            raise ValueError('Paid transport requires a positive per-call cost bound and shared admission')
    admission=admission or Admission(work/'admission.sqlite',request_budget,0)
    wire=Admission(work/'wire-admission.sqlite',2**63-1,byte_budget)
    dns_cache,dns_lock={},threading.Lock()
    def cached_resolve(host):
        with dns_lock:
            if host in dns_cache:return dns_cache[host]
        addrs=resolve(host)
        with dns_lock:
            dns_cache[host]=addrs
        return addrs
    policy=CapturePolicy(release['scope'],resolve=cached_resolve);policy.require_capture()
    archive_limits=archive_limits or ZipLimits(max_archive_bytes=min(16<<20,max(1,spool_budget//16)),
        max_member_bytes=min(16<<20,max(1,spool_budget//16)),max_total_bytes=min(32<<20,max(1,spool_budget//8)),
        max_directory_bytes=min(256<<10,max(1,spool_budget//256)));hops=7*(1+int(provider is not None)+int(firecrawl is not None))
    stats=dict(release_id=release['release_id'],as_of=as_of,run_id=new_run_id(),requests=0,
        fetched_bytes=0,captures=0,receipts=[],refusals=[],discovery_errors=[],discovery_refused=0,cutoffs=[],cutoff_attempts=[],
        budgets=dict(requests=request_budget,bytes=byte_budget,spool=spool_budget,max_entity_bytes=max_entity_bytes),spool_reserved_bound=0,
        url_key_definition_sha256=url_key_digest,stop_reason=None)
    from congress_api.acquisition.capture_journal import DurableCapture,durable_json
    binding=dict(release_id=release['release_id'],as_of=as_of,identity=identity,
                 budgets=stats['budgets'],campaign_id=getattr(campaign,'campaign_id',None),campaign_sha256=getattr(campaign,'descriptor_sha256',None),
                 provider_cost=provider_cost,firecrawl_cost=firecrawl_cost,
                 admission_path=str(Path(admission.path).resolve()),spend_cap=admission.spend_cap,
                 store_destination=str(getattr(store.adapter,'root',getattr(store.adapter,'bucket','unknown'))),
                 archive_limits=vars(archive_limits),workers=workers,max_entity_bytes=max_entity_bytes)
    journal=DurableCapture(work/'attempts',binding)
    protected_spool_bytes=sum(path.stat().st_size for path in (work/'attempts').glob('*/quarantine/*.body'))
    stats['protected_scratch_bytes']=protected_spool_bytes
    # A killed receipt writer can leave disposable expansion scratch. Remove
    # only directories carrying our owner marker and a durable source record.
    import shutil
    for abandoned in work.glob('raw-receipt-*'):
        marker=abandoned/'capture-owner.json'
        if abandoned.is_symlink() or not marker.is_file():continue
        owner=json.loads(marker.read_text())
        operation=owner.get('operation_id','')
        if owner.get('kind')!='receipt-scratch-v1' or not re.fullmatch('[a-f0-9]{64}',operation):continue
        if not ((work/'attempts'/operation/'downloaded.json').exists() or (work/'attempts'/operation/'committed.json').exists()):
            continue
        shutil.rmtree(abandoned)
    context=work/'run.json'
    if context.exists():run=json.loads(context.read_text())
    else:
        run=dict(run_id=stats['run_id'],write_date=datetime.now(timezone.utc).date().isoformat())
        durable_json(context,run)
    stats['run_id']=run['run_id']
    writer=ReceiptWriter(store,identity=identity,run_id=run['run_id'],write_date=run['write_date'],archive_limits=archive_limits)
    # A fresh invocation has disposable plans; attempts and frozen receipts stay
    # under the original durable owner. Reconstruct continuation before planning.
    invocation=0
    while (work/('plan-0' if invocation==0 else f'invocation-{invocation}')).exists():invocation+=1
    plan_work=work if invocation==0 else work/f'invocation-{invocation}'
    plan_work.mkdir(parents=True,exist_ok=True)
    attempted=plan_work/'attempted.jsonl.gz';discovered=[];generation=0
    stats['fetched_bytes']=sum((row.get('transfer',{}).get('wire_bytes') or row.get('transfer',{}).get('size',0))
        for p in (work/'attempts').glob('*/*.json') for row in [json.loads(p.read_text())])
    restored_links=[];disabled_providers=set()
    for committed in sorted((work/'attempts').glob('*/committed.json')):
        journal.cleanup(committed.parent.name)
        completed=json.loads(committed.read_text());line=completed['line'];url=line['requested_url']
        if _provider_terminal(line['transport'],line['provider_status'],line.get('error_type')):disabled_providers.add(line['transport'])
        stats['captures']+=1;stats['receipts'].append(completed['key'])
        _record_attempt(attempted,url,attempted=True,complete=completed['result']['final']['complete'],
            outcome=line['outcome'],http_status=line['http_status'],error_type=completed['result']['final']['error'])
        restored_links.extend(completed['links'])
    if restored_links:
        entry=json_input(plan_work,'restored-discovery',restored_links,href='Utf8',base_href='Utf8',context='Utf8',source='Utf8',pointer='Utf8')
        discovered.extend(entry['files'])
    parser_workers={};worker_stack=ExitStack();parser_lock=threading.Lock()
    worker_version=hashlib.sha256(json.dumps(['capture-discovery',identity['commit'],
        identity['lockfile_digest']],separators=(',',':')).encode()).hexdigest()
    keyed_states_cache=plan_work/'plan-0/keyed_states.parquet'
    plan=plan_queue(release,engine=engine,work=plan_work/'plan-0',as_of=as_of,
        request_budget=request_budget,seed_inventories=seed_inventories,cutoff_urls=cutoff_urls,
        _keyed_states_cache=keyed_states_cache,campaign=campaign,attempted=attempted if attempted.exists() else None,discovery_files=discovered)
    stats['initial_counts']=plan['counts'];seed_files=plan['seed_files']
    def pending_rows(selected_plan):
        retained=[];urls=set()
        for request_file in sorted((work/'attempts').glob('*/request.json')):
            if (request_file.parent/'committed.json').exists():continue
            retained_request=json.loads(request_file.read_text());url=retained_request['url']
            row=retained_request.get('row') or dict(requested_url=url,priority=0,
                observations=[json.dumps([url,'resume:'+release['release_id'],'[]'])])
            retained.append(row);urls.add(url)
        return iter(chain(retained,(row for row in _records(selected_plan['queue']) if row['requested_url'] not in urls)))
    pending=pending_rows(plan)
    pace=pace or HostPacer(PACING)
    for record in (work/'attempts').glob('*/*.json'):
        saved=json.loads(record.read_text())
        if saved.get('phase')=='started':disabled_providers.add('*')
        elif saved.get('phase')=='downloaded' and isinstance(saved.get('transfer'),dict):
            transfer=saved['transfer'];transport=record.name.split('-',1)[0]
            if _provider_terminal(transport,transfer.get('provider_status'),transfer.get('error')):
                disabled_providers.add(transport)
    provider_state=(threading.Lock(),disabled_providers)

    def _capture_one(row,url,family,limit,allow_discovery):
        local_stats=dict(requests=0,fetched_bytes=0)
        observations=[dict(url=value[0],source=value[1],pointer=json.loads(value[2]))
                      for value in map(json.loads,row['observations'])]
        links=[];disc_errors=[];disc_refused=0
        operation_id=hashlib.sha256(json.dumps([binding,url],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        spool=journal.directory(operation_id)
        request_path=spool/'request.json'
        if request_path.exists():limit=json.loads(request_path.read_text())['limit']
        else:durable_json(request_path,dict(url=url,limit=limit,row={name:row[name] for name in ('requested_url','priority','observations')}))
        def spool_guard():
            remaining=max(0,spool_budget-protected_spool_bytes)
            _,overhead=_allowance(0,0,archive_limits,hops)
            share=(overhead+(remaining-overhead)//workers) if remaining>=overhead else remaining//workers
            allowed,_=_allowance(2**63-1,share,archive_limits,hops)
            if limit>allowed:
                error=AdmissionDenied('Protected scratch leaves insufficient room for a network attempt')
                error.resource='scratch'
                raise error
        def factory(directory):
            return Fetcher(scope=policy,direct=_Counted(direct,local_stats,admission,'direct',0,max_entity_bytes,wire,spool_guard,provider_state),
                provider=_Counted(provider,local_stats,admission,'zyte',provider_cost,max_entity_bytes,wire,spool_guard,provider_state) if provider is not None else None,
                firecrawl=_Counted(firecrawl,local_stats,admission,'firecrawl',firecrawl_cost,max_entity_bytes,wire,spool_guard,provider_state) if firecrawl is not None else None,
                pace=pace,directory=directory,spool_limit=limit,headers=headers)
        # The stable spool survives body PUT, qualification, and receipt failures.
        result=journal.fetch(operation_id,url,factory)
        # Completed acquisition bypasses request/byte admission, while receipt
        # preparation and expansion still require their scratch reservation.
        spool_guard()
        key,line=writer.write(result,family=family,observations=observations,
                              operation_id=operation_id,freeze_dir=work/'frozen-receipts')
        body=result.final.body
        parser=line['captures'][0]['sniffed_format'] if body is not None else None
        if (allow_discovery and body is not None and result.final.complete
                and result.final.http_status is not None and 200<=result.final.http_status<300
                and parser in {'html','xml','json'}):
            if body.size>PAGE_BYTES:
                disc_errors.append(dict(url=url,reason='discovery_size_limit'))
            else:
                if discover is not None:
                    facts=discover(body.path.read_bytes(),parser)
                else:
                    with parser_lock:
                        if parser not in parser_workers:
                            parser_workers[parser]=worker_stack.enter_context(worker_factory(parser,worker_version,
                                'congress_api.acquisition.capture_scheduler:read_discovery_payload',
                                timeout_seconds=30,memory_bytes=512<<20,max_input_bytes=PAGE_BYTES+16384))
                        outcome=parser_workers[parser].parse(body.sha256,json.dumps(dict(path=str(body.path),bytes=body.size,
                            sha256=body.sha256,parser=parser),ensure_ascii=False,separators=(',',':')).encode('utf-8'))
                    if outcome['status'] in {'unreadable','size_limit'}:
                        facts=dict(status='error',error_type=outcome.get('reason',outcome['status']))
                    elif outcome['status']=='completed':facts=outcome['value']
                    else:raise ValueError('Invalid bounded discovery worker result')
                if facts['status']!='completed':
                    disc_errors.append(dict(url=url,reason=facts['error_type']))
                else:
                    for index,link in enumerate(facts['links']):
                        if (not _safe_reference(link['href']) or facts['base_href'] is not None
                                and not _safe_reference(facts['base_href'])):
                            disc_refused+=1
                            continue
                        links.append(dict(href=link['href'],base_href=facts['base_href'],context=result.final.url,
                            source=key,pointer=json.dumps([index])))
        from congress_api.acquisition.capture_journal import encode_result
        durable_json(spool/'committed.json',dict(key=key,line=line,result=encode_result(result),links=links))
        journal.cleanup(operation_id)
        return row,url,result,key,line,local_stats,links,disc_errors,disc_refused

    def _commit(outcome_tuple):
        row,url,result,key,line,local_stats,links,disc_errors,disc_refused=outcome_tuple
        stats['requests']+=local_stats['requests']
        stats['fetched_bytes']+=local_stats['fetched_bytes']
        stats['receipts'].append(key);stats['captures']+=1
        if row['priority']==1:
            stats['cutoff_attempts'].append(dict(url=url,outcome=line['outcome'],complete=result.final.complete,
                reason=result.final.error))
        _record_attempt(attempted,url,attempted=True,complete=result.final.complete,
            outcome=line['outcome'],http_status=line['http_status'],error_type=result.final.error)
        stats['discovery_errors'].extend(disc_errors)
        stats['discovery_refused']+=disc_refused
        if _provider_terminal(line['transport'],line['provider_status'],line.get('error_type')):
            stats['stop_reason']='provider_unavailable'
            stats['provider_failure']=dict(transport=line['transport'],status=line['provider_status'],error=line.get('error_type'))
        return links

    pool=None
    try:
        pool=worker_stack.enter_context(ThreadPoolExecutor(max_workers=workers)) if workers>1 else None
        inflight=set();wire_reservations={};exhausted=False;held_row=None
        while True:
            while len(inflight)<workers and not exhausted and stats['stop_reason'] is None:
                row=held_row if held_row is not None else next(pending,None)
                held_row=None
                if row is None:
                    exhausted=True
                    if not inflight:stats['stop_reason']='request_budget' if admission.totals()['requests']>=request_budget else 'queue_empty'
                    break
                operation_id=hashlib.sha256(json.dumps([binding,row['requested_url']],sort_keys=True,separators=(',',':')).encode()).hexdigest()
                previous_root=work/'attempts'/operation_id
                continuing=(previous_root/'request.json').exists()
                if admission.totals()['requests']>=request_budget and not continuing:
                    held_row=row
                    if not inflight:stats['stop_reason']='request_budget'
                    break
                active=len(inflight)+1
                _,min_overhead=_allowance(0,0,archive_limits,hops)
                protected=protected_spool_bytes
                available_spool=max(0,spool_budget-protected)
                worker_spool=(min_overhead+(available_spool-min_overhead)//workers) if available_spool>=min_overhead else available_spool//workers
                available=byte_budget-stats['fetched_bytes']-sum(wire_reservations.values())
                limit,reserved=_allowance(max(0,available)//max(1,workers-len(inflight)),worker_spool,archive_limits,hops)
                if continuing:limit=json.loads((previous_root/'request.json').read_text())['limit']
                if limit<=0:
                    held_row=row
                    if not inflight:stats['stop_reason']='byte_or_spool_budget'
                    break
                url=row['requested_url']
                if campaign is not None:
                    campaign.require_custody()
                try:validate_record(url)
                except ValueError:
                    stats['refusals'].append(dict(reason='unsafe_recorded_url'))
                    continue
                family=policy.family(url)
                if family is None:
                    stats['refusals'].append(dict(url=url,reason='outside_capture_scope'))
                    _record_attempt(attempted,url,attempted=False,error_type='outside_capture_scope')
                    continue
                scratch_limit,_=_allowance(2**63-1,worker_spool,archive_limits,hops)
                if limit<=scratch_limit:
                    stats['spool_reserved_bound']=max(stats['spool_reserved_bound'],protected+min_overhead+active*3*limit)
                if pool is None:
                    links=_commit(_capture_one(row,url,family,limit,generation<max_discovery_jobs))
                    if links and generation<max_discovery_jobs:
                        generation+=1
                        entry=json_input(plan_work,f'discovered-{generation}',links,href='Utf8',base_href='Utf8',context='Utf8',source='Utf8',pointer='Utf8')
                        discovered.extend(entry['files'])
                        plan=plan_queue(release,engine=engine,work=plan_work/f'plan-{generation}',as_of=as_of,
                            request_budget=request_budget,seed_files=seed_files,
                            discovery_files=discovered,attempted=attempted,cutoff_urls=cutoff_urls,
                            _keyed_states_cache=keyed_states_cache,campaign=campaign)
                        pending=pending_rows(plan);exhausted=False
                else:
                    future=pool.submit(_capture_one,row,url,family,limit,generation<max_discovery_jobs)
                    inflight.add(future);wire_reservations[future]=hops*limit
            if stats['stop_reason'] is not None:
                break
            if not inflight:
                if exhausted:
                    stats['stop_reason']='queue_empty';break
                continue
            done,inflight=wait(inflight,return_when=FIRST_COMPLETED)
            batch_links=[]
            for fut in done:
                wire_reservations.pop(fut,None)
                batch_links.extend(_commit(fut.result()))
            if batch_links and generation<max_discovery_jobs:
                if inflight:
                    rest,_=wait(inflight)
                    inflight=set()
                    for fut in rest:
                        wire_reservations.pop(fut,None)
                        batch_links.extend(_commit(fut.result()))
                generation+=1
                entry=json_input(plan_work,f'discovered-{generation}',batch_links,href='Utf8',base_href='Utf8',context='Utf8',source='Utf8',pointer='Utf8')
                discovered.extend(entry['files'])
                plan=plan_queue(release,engine=engine,work=plan_work/f'plan-{generation}',as_of=as_of,
                    request_budget=request_budget,seed_files=seed_files,
                    discovery_files=discovered,attempted=attempted,cutoff_urls=cutoff_urls,
                    _keyed_states_cache=keyed_states_cache,campaign=campaign)
                pending=pending_rows(plan);exhausted=False
        return stats
    except AdmissionDenied as error:
        stats['stop_reason']={'scratch':'byte_or_spool_budget','provider':'provider_unavailable','unknown':'unknown_remote_outcome'}.get(getattr(error,'resource',None),'request_or_spend_budget')
        return stats
    except Exception as error:
        stats.update(stop_reason='error',error_type=type(error).__name__)
        raise
    finally:
        # Drain writers before reading durable completions or closing parsers.
        if pool is not None:pool.shutdown(wait=True)
        worker_stack.close()
        stats['discovery_jobs']=generation
        completed=[json.loads(p.read_text()) for p in sorted((work/'attempts').glob('*/committed.json'))]
        stats['captures']=len(completed);stats['receipts']=[item['key'] for item in completed]
        for item in completed:
            final=item['result']['final'];line=item['line']
            _record_attempt(attempted,line['requested_url'],attempted=True,complete=final['complete'],
                outcome=line['outcome'],http_status=line['http_status'],error_type=final['error'])
        stats['fetched_bytes']=sum((row.get('transfer',{}).get('wire_bytes') or row.get('transfer',{}).get('size',0))
            for p in (work/'attempts').glob('*/*.json') for row in [json.loads(p.read_text())])
        stats['wire_admission']=wire.totals()
        stats['admission']=admission.totals()
        stats['requests']=stats['admission']['requests']
        stats['resources']=dict(peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if os.uname().sysname=='Darwin' else 1024),
            retained_scratch_bytes=sum(p.stat().st_size for p in work.rglob('*') if p.is_file()),
            scope='capture process high water; native/parser child limits are separate')
        # D discovery replans plus initial planning and this report give D+2
        # linear input passes (ten at the default D=8), not one per capture.
        try:
            stats['cutoffs']=cutoff_report(release,urls=cutoff_urls,attempted=attempted,engine=engine,
                work=plan_work/'cutoff-report',as_of=as_of,stop_reason=stats['stop_reason'],
                _keyed_states_cache=keyed_states_cache)
        finally:
            (work/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n')


def run_capture(release,**options):
    """Resume one pinned campaign, with one active local writer per work root."""
    _require_capture_authority(release)
    import fcntl
    work=Path(options['work']);work.mkdir(parents=True,exist_ok=True)
    with (work/'capture.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Capture work is already active') from None
        return _run_capture(release,**options)
