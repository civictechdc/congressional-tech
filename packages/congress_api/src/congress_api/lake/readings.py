"""Native body work lists, bounded parser invocations and typed reading stages."""
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import stat
import shutil
import zlib
import threading
import time
from contextlib import nullcontext
from itertools import islice
from functools import lru_cache

from congress_api.lake.tables import table_input
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.parser_worker import ParserWorker, ParserWorkerPool, reading_input
from congress_api.retention.provenance import (field, instant, json_input, list_of,
    parquet_output, parquet_records, run_job, struct, finish_stage, import_unreadable,
    imported_unreadable_provenance)

ROOT=Path(__file__).resolve().parents[5]
PK=['body_sha','parser','parser_version']
MAX_STORED_BYTES=64<<20
MAX_DECODED_BYTES=64<<20
RAW_CACHE_BYTES=1<<30
RAW_CACHE_CEILING=10<<30
GZIP_RULE_FIELDS=tuple('gzip_rule'+str(n) for n in range(1,5))
WORKER_MEMORY_BYTES=512<<20
PARSER_MEMORY_BYTES=10<<30
WORKER_TIMEOUT_SECONDS=15
LINK_FIELDS=('href','text','tag','basis','group_path','doc_type','add_date','publish_date','remove_date')
STRINGS=('parser','parser_version','status','error_type','format','xml_root','title','heading',
         'text_head','content_date','base_href')
INTEGERS=('text_bytes','link_count','link_text_bytes')


def current_version(parser):
    if parser=='sniff':
        from congress_api.retention.sniff import sniff_version
        return sniff_version()
    if parser not in {'html','xml','json'}:
        raise ValueError('Unsupported reading parser')
    from congress_api.lake.versions import version_digest
    return version_digest(packages={},files={
        'parser':Path(__file__).parents[1]/'parsers/archive_readings.py',
        'xml_helper':Path(__file__).parents[1]/'parsers/xml.py',
        'lock':ROOT/'uv.lock','schema':ROOT/'model/lake/readings.schema.json'},
        values=dict(parser=parser,stored_bytes=MAX_STORED_BYTES,decoded_bytes=MAX_DECODED_BYTES))


def parse_payload(payload):
    """Read only a named local body; read failures remain pending, not verdicts."""
    source=json.loads(payload)
    path=Path(source['path'])
    count=0
    try:
        with reading_input():
            stream=path.open('rb')
        with stream:
            with reading_input():
                observed=os.fstat(stream.fileno())
            if not stat.S_ISREG(observed.st_mode) or observed.st_size!=source['stored_bytes']:
                return dict(read_error='changed_input',read_bytes=0)
            if source['parser']=='sniff':
                from congress_api.retention.sniff import read_sniff
                def read(start,length):
                    nonlocal count
                    with reading_input():
                        stream.seek(start)
                        data=stream.read(length)
                    count+=len(data)
                    return data
                # The sniffer switches phases around each raw read. Its PDF
                # fallback already uses the bounded external reader.
                row=read_sniff(read,stored_size=observed.st_size,stored_gzip=source['stored_gzip'])
            else:
                with reading_input():
                    entity=gzip.GzipFile(fileobj=stream) if source['stored_gzip'] else stream
                    try:
                        data=entity.read(MAX_DECODED_BYTES+1)
                        count=stream.tell()
                    finally:
                        if entity is not stream:entity.close()
                if len(data)>MAX_DECODED_BYTES:
                    return dict(row=dict(status='error',error_type='decoded_size_limit'),read_bytes=count)
        if source['parser']!='sniff':
            from congress_api.parsers.archive_readings import read_page
            row=read_page(data,source['parser'])
        return dict(row=row,read_bytes=count)
    except (OSError, EOFError) as exc:
        return dict(read_error=type(exc).__name__,read_bytes=count)


def _reading_fields():
    result={name:'Utf8' for name in (*STRINGS,'body_hex','fingerprint_hex')}
    result.update({name:'Int32' for name in INTEGERS})
    result.update(intact='Boolean',named_meetings=list_of('Int64'),
        links=list_of(struct(**{name:'Utf8' for name in LINK_FIELDS})),
        fields=list_of(struct(field='Utf8',value='Utf8')))
    return result


def worker_limits():
    """Name the exact resource policy passed to the supervised producer."""
    return dict(timeout_seconds=WORKER_TIMEOUT_SECONDS,memory_bytes=WORKER_MEMORY_BYTES,
                max_input_bytes=65536,max_output_bytes=8<<20)


def bundle_version(versions,*,policy):
    """Pin combined failure authority without invalidating completed leaf facts."""
    from congress_api.lake.versions import version_digest
    files={'producer':Path(__file__),
        'supervisor':Path(__file__).parents[1]/'retention/parser_worker.py',
        'resources':Path(__file__).parents[1]/'retention/process_resources.py',
        'raw_transport':Path(__file__).parents[1]/'retention/r2.py'}
    files.update({name:ROOT/'model/sql'/(name+'.sql') for name in
        ['pinned-readings','sniff-observations','sniff-conflicts','sniff-facts','body-admissions']})
    return version_digest(packages={},files=files,values=dict(leaf_versions=versions,policy=policy))


def writer_admission_step(*,root=ROOT):
    """Derive current writer proofs from captures using the one versioned rule."""
    return dict(name='body_admissions',sql=(Path(root)/'model/sql/body-admissions.sql').read_text(),materialize=True)


def writer_admission_conflict_sql():
    """Count contradictions between current writer proof and current byte facts."""
    return """SELECT count(*) AS n FROM body_admissions a
        JOIN sniff_facts s ON a.body_sha=s.body_sha WHERE a.format IS DISTINCT FROM s.format"""


class BackfillRequired(ValueError):
    """A daily plan exceeded its runner budget before any body was opened."""
    def __init__(self,planned,max_work_items):
        self.report={name:planned[name] for name in
            ('work_items','work_list','parser','parser_version')}
        self.report['work_list']=str(self.report['work_list'])
        self.report.update(status='backfill_required',max_work_items=max_work_items)
        super().__init__('Reading work list exceeds daily budget; backfill required')

    def as_dict(self):
        return dict(self.report)


class RawCustodyRequired(ValueError):
    def __init__(self,planned):
        self.report=dict(planned['raw_custody'],status='missing_raw_custody',work_list=str(planned['work_list']))
        super().__init__('Ranged raw work requires captured stored MD5 and size pins; '+str(self.report))
    def as_dict(self):return dict(self.report)


def _raw_policy(body_store,max_cache_bytes,max_get_workers):
    from congress_api.retention.r2 import R2Store
    if body_store is not None and not isinstance(body_store,R2Store):raise ValueError('Body reader must be the maintained R2Store')
    if (type(max_cache_bytes) is not int or not 0<max_cache_bytes<=RAW_CACHE_CEILING
            or type(max_get_workers) is not int or not 0<max_get_workers<=64):
        raise ValueError('Raw cache budget must be at most10GiB and GET concurrency1–64')


def _positive(value,name):
    if type(value) is not int or value<=0:
        raise ValueError(name+' must be a positive integer')
    return value


def plan(*,captures,body_inventory,local_root,engine,work,decided_at,parser,
         sniff_version=None,parser_version=None,existing=None,unreadable_files=(),max_work_items=None,raw_ranges=False,
         body_listing=None):
    """Materialize one native missing-body work list, without opening raw bodies."""
    if max_work_items is not None:_positive(max_work_items,'max_work_items')
    if type(raw_ranges) is not bool:raise ValueError('raw_ranges must be an explicit boolean')
    if body_listing is not None and not raw_ranges:raise ValueError('Body listing requires ranged reads')
    direct_listing=body_inventory is None
    if direct_listing and body_listing is None:raise ValueError('A selected inventory or complete body listing is required')
    instant(decided_at)
    combined=parser is None
    versions={p:current_version(p) for p in ['sniff','html','xml','json']}
    limits=worker_limits()
    version=(bundle_version(versions,policy=limits) if combined else versions[parser])
    parser='readings' if combined else parser
    if parser_version is not None and parser_version!=version:
        raise ValueError('Parser version does not match its current definition')
    if combined and sniff_version is not None and sniff_version!=versions['sniff']:
        raise ValueError('Combined sniff version must match the current definition')
    if sniff_version is None:
        sniff_version=versions['sniff']
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    raw=Path(local_root).resolve()
    inputs=[json_input(work,'parser_versions',[dict(parser=p,version=v) for p,v in ({**versions,'sniff':sniff_version} if combined else {'sniff':sniff_version}).items()],parser='Utf8',version='Utf8'),
            table_input('captures',captures)]
    if not direct_listing:
        inputs.append(dict(name='body_inventory',kind='parquet',path=str(Path(body_inventory).resolve())))
    if body_listing is not None:
        inputs.append(dict(name='body_listing',kind='parquet',path=str(Path(body_listing).resolve())))
    unreadable_schema=dict(id='Utf8',body_sha256='Utf8',parser='Utf8',parser_version='Utf8',supersedes='Utf8')
    if unreadable_files:
        inputs.append(dict(name='unreadable',kind='json_lines',files=list(unreadable_files),
            schema=dict(fields=[field(k,v) for k,v in unreadable_schema.items()],metadata={})))
    else:inputs.append(json_input(work,'unreadable',[],**unreadable_schema))
    if isinstance(existing,dict) or existing:
        inputs.append(table_input('existing',existing))
    else:
        empty=json_input(work,'existing',[],**_reading_fields())
        empty['name']='existing_json';inputs.append(empty)
    quote=lambda value:"'"+value.replace("'","''")+"'"
    steps=[]
    if raw_ranges:
        steps.append(dict(name='body_storage',sql="""SELECT sha256 AS body_sha,coalesce(stored_suffix,'.gz') AS stored_suffix,
            concat('bodies/sha256/',substr(encode(sha256,'hex'),1,2),'/',encode(sha256,'hex'),
                coalesce(stored_suffix,'.gz')) AS physical_key,
            max(bytes) AS captured_bytes,max(stored_bytes) AS captured_stored_bytes,max(encode(stored_md5,'hex')) AS stored_md5,
            min(bytes)<>max(bytes) OR min(stored_bytes)<>max(stored_bytes) OR min(encode(stored_md5,'hex'))<>max(encode(stored_md5,'hex')) AS conflict,
            bool_or(lower(split_part(media_type,';',1)) IN ('text/html','application/xhtml+xml','text/xml',
                'application/xml','application/json','text/json') OR
                ends_with(lower(split_part(media_type,';',1)),'+xml') OR
                ends_with(lower(split_part(media_type,';',1)),'+json')) AS page_hint
            FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256,coalesce(stored_suffix,'.gz')""",materialize=True))
    if direct_listing:
        # Choose only capture-recorded copies. Rank before consulting availability;
        # a rejected higher-ranked copy contributes its own fallback reason.
        steps.extend([
            dict(name='listed_copies',sql='''SELECT s.*,CASE WHEN nullif(l.etag,'') IS NOT NULL THEN l.size END AS listed_size,
                l.key IS NULL AS listing_missing,
                CASE s.stored_suffix WHEN '' THEN 0 WHEN '.gz' THEN 1 ELSE 2 END AS priority,
                coalesce(l.etag,CASE WHEN s.stored_md5 IS NOT NULL THEN concat('"',s.stored_md5,'"') END) AS version,
                coalesce(s.conflict,false) OR coalesce(s.stored_md5 IS NOT NULL AND l.etag IS NOT NULL AND
                    s.stored_md5<>lower(trim(BOTH '"' FROM l.etag)),false) OR
                    coalesce(s.captured_stored_bytes<>l.size,false) AS pin_conflict
                FROM body_storage s LEFT JOIN body_listing l ON s.physical_key=l.key''',materialize=True),
            dict(name='copy_candidates',sql='''SELECT *,NOT listing_missing AND NOT pin_conflict AND
                coalesce(captured_stored_bytes,listed_size) IS NOT NULL AND nullif(version,'') IS NOT NULL AS usable
                FROM listed_copies''',materialize=True),
            dict(name='ranked_copies',sql='''SELECT *,row_number() OVER (
                PARTITION BY body_sha ORDER BY usable DESC,priority ASC) AS choice FROM copy_candidates''',materialize=True),
            dict(name='copy_fallbacks',sql='''SELECT r.body_sha,
                sum(CASE WHEN c.listing_missing THEN 1 ELSE 0 END) AS fallback_missing,
                sum(CASE WHEN c.pin_conflict THEN 1 ELSE 0 END) AS fallback_conflict,
                sum(CASE WHEN coalesce(c.captured_stored_bytes,c.listed_size) IS NULL OR nullif(c.version,'') IS NULL THEN 1 ELSE 0 END) AS fallback_pin
                FROM ranked_copies r JOIN copy_candidates c ON r.body_sha=c.body_sha
                WHERE r.choice=1 AND (NOT r.usable OR c.priority<r.priority) GROUP BY r.body_sha''',materialize=True),
            dict(name='body_inventory',sql='''SELECT r.body_sha,r.physical_key,r.physical_key AS relative_path,
                coalesce(r.captured_stored_bytes,r.listed_size) AS stored_bytes,false AS stored_gzip,
                r.usable,r.listing_missing,coalesce(f.fallback_missing,0) AS fallback_missing,
                coalesce(f.fallback_conflict,0) AS fallback_conflict,coalesce(f.fallback_pin,0) AS fallback_pin
                FROM ranked_copies r LEFT JOIN copy_fallbacks f ON r.body_sha=f.body_sha WHERE r.choice=1''',materialize=True)])
    if not existing:
        steps.append(dict(name='existing',sql='SELECT decode(body_hex,\'hex\') AS body_sha,* FROM existing_json'))
    steps.extend([
        dict(name='bodies',sql='SELECT DISTINCT sha256 AS body_sha FROM captures WHERE sha256 IS NOT NULL',materialize=True),
        dict(name='readings',sql='SELECT * FROM existing'),
        *[dict(name=name.replace('-','_'),sql=(ROOT/'model/sql'/(name+'.sql')).read_text())
          for name in ['pinned-readings','sniff-observations','sniff-conflicts','sniff-facts']],
        dict(name='known_formats',sql='SELECT body_sha,format FROM sniff_facts'),
        dict(name='active_unreadable',sql='''SELECT u.* FROM unreadable u
            WHERE NOT EXISTS (SELECT 1 FROM unreadable s WHERE s.supersedes=u.id)''')])
    if combined:
        steps.append(writer_admission_step())
    candidate=(f"NOT EXISTS(SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha)" if parser=='sniff' else
               f"EXISTS(SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha AND f.format={quote(parser)})")
    if combined:
        steps.append(dict(name='settled_parsers',sql="""SELECT body_sha,array_agg(DISTINCT parser) AS parsers FROM (
            SELECT body_sha,parser FROM pinned_readings UNION
            SELECT decode(u.body_sha256,'hex') AS body_sha,u.parser FROM active_unreadable u
            JOIN parser_versions v ON u.parser=v.parser AND u.parser_version=v.version
            WHERE u.body_sha256 IS NOT NULL) GROUP BY body_sha""",materialize=True))
        candidate="""NOT EXISTS(SELECT 1 FROM body_admissions a WHERE a.body_sha=b.body_sha) AND
         ((NOT EXISTS(SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha) AND NOT EXISTS(
           SELECT 1 FROM settled_parsers sp WHERE sp.body_sha=b.body_sha AND array_has(sp.parsers,'sniff'))) OR EXISTS(
          SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha AND f.format IN ('html','xml','json')
          AND NOT EXISTS(SELECT 1 FROM existing e JOIN parser_versions v ON e.parser=v.parser AND e.parser_version=v.version
              WHERE e.body_sha=f.body_sha AND e.parser=f.format)
          AND NOT EXISTS(SELECT 1 FROM active_unreadable u JOIN parser_versions v ON u.parser=v.parser AND u.parser_version=v.version
              WHERE u.body_sha256=encode(f.body_sha,'hex') AND u.parser=f.format)))"""
    extra=""",(SELECT max(format) FROM known_formats f WHERE f.body_sha=b.body_sha) AS known_format,
       sp.parsers AS skip_parsers""" if combined else ''
    storage_join=''
    if raw_ranges:
        size_pin="coalesce(s.captured_stored_bytes,CASE WHEN nullif(l.etag,'') IS NOT NULL THEN l.size END)" if body_listing is not None else 's.captured_stored_bytes'
        extra+=f',s.stored_md5,s.captured_bytes,{size_pin} AS captured_stored_bytes,coalesce(s.page_hint,false) AS page_hint,coalesce(s.conflict,false) AS capture_conflict'
        storage_join=' LEFT JOIN body_storage s ON b.body_sha=s.body_sha AND i.physical_key=s.physical_key'
        if body_listing is not None:
            storage_join+=' LEFT JOIN body_listing l ON i.physical_key=l.key'
            extra+=''',CASE WHEN s.stored_md5 IS NOT NULL THEN concat('"',s.stored_md5,'"') ELSE nullif(l.etag,'') END AS conditional_etag,
                coalesce(s.stored_md5 IS NOT NULL AND l.etag IS NOT NULL AND
                    s.stored_md5<>lower(trim(BOTH '"' FROM l.etag)),false) AS md5_conflict,
                coalesce(l.size<>s.captured_stored_bytes,false) AS size_conflict'''
        else:
            extra+=''',CASE WHEN s.stored_md5 IS NOT NULL THEN concat('"',s.stored_md5,'"') END AS conditional_etag,
                false AS md5_conflict,false AS size_conflict'''
        extra+=(''',coalesce(i.usable,false) AS copy_usable,coalesce(i.listing_missing,true) AS listing_missing,
            i.fallback_missing,i.fallback_conflict,i.fallback_pin''' if direct_listing else
            ',true AS copy_usable,false AS listing_missing,0 AS fallback_missing,0 AS fallback_conflict,0 AS fallback_pin')
    settled_join=' LEFT JOIN settled_parsers sp ON b.body_sha=sp.body_sha' if combined else ''
    stored_size=size_pin if raw_ranges and body_listing is not None else 'i.stored_bytes'
    sql=f'''SELECT b.body_sha,i.physical_key,i.relative_path,{stored_size} AS stored_bytes,i.stored_gzip{extra}
        FROM bodies b LEFT JOIN body_inventory i ON b.body_sha=i.body_sha{settled_join}{storage_join}
        WHERE {candidate} AND NOT EXISTS(SELECT 1 FROM existing e WHERE e.body_sha=b.body_sha
          AND e.parser={quote(parser)} AND e.parser_version={quote(version)})
        AND NOT EXISTS(SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(b.body_sha,'hex')
          AND u.parser={quote(parser)} AND u.parser_version={quote(version)})'''
    steps.append(dict(name='pending_bodies',sql=sql,materialize=True))
    checks=run_job(work,engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(work,'work-list','SELECT * FROM pending_bodies',['body_sha'])]+([parquet_output(work,'body-admissions','SELECT * FROM body_admissions',['body_sha'])] if combined else []),queries=[
        dict(name='conflicts',sql='''SELECT count(*) AS n FROM (
            SELECT body_sha FROM body_inventory GROUP BY body_sha HAVING count(*)>1
            UNION ALL SELECT body_sha FROM sniff_conflicts)'''),
        dict(name='invalid_inventory',sql=f'''SELECT count(*) AS n FROM body_inventory
            WHERE body_sha IS NULL OR physical_key IS NULL OR relative_path IS NULL
               {'OR stored_bytes IS NULL' if not direct_listing else ''} OR stored_bytes<0 OR stored_gzip IS NULL''')]+([
        dict(name='writer_admission_conflicts',sql=writer_admission_conflict_sql())]
        if combined else [])+([dict(name='listing_conflicts',sql='''SELECT count(*) AS n FROM (
            SELECT key FROM body_listing GROUP BY key HAVING count(*)>1
            UNION ALL SELECT key FROM body_listing WHERE key IS NULL OR size IS NULL OR size<0)''')]
            if body_listing is not None else [])+[dict(name='work_items',sql='SELECT count(*) AS n FROM pending_bodies')]+([
        dict(name='invalid_storage_suffix',sql="SELECT count(*) AS n FROM body_storage WHERE stored_suffix NOT IN ('','.gz','.pdf')"),
        dict(name='storage_conflicts',sql=f'''SELECT count(*) AS n FROM body_inventory i JOIN body_storage s
            ON i.body_sha=s.body_sha AND i.physical_key=s.physical_key
            WHERE {'i.usable AND' if direct_listing else ''} (s.conflict OR i.stored_bytes<>s.captured_stored_bytes)'''),
        dict(name='raw_custody',sql=f'''SELECT count(*) AS bodies,
            coalesce(sum(CASE WHEN physical_key IS NULL OR conditional_etag IS NULL OR captured_stored_bytes IS NULL OR NOT copy_usable THEN 1 ELSE 0 END),0) AS missing_pins,
            coalesce(sum(CASE WHEN physical_key IS NULL OR listing_missing THEN 1 ELSE 0 END),0) AS missing_physical,
            coalesce(sum(CASE WHEN stored_md5 IS NULL THEN 1 ELSE 0 END),0) AS missing_md5,
            coalesce(sum(CASE WHEN captured_stored_bytes IS NULL THEN 1 ELSE 0 END),0) AS missing_size,
            coalesce(sum(CASE WHEN stored_md5 IS NOT NULL THEN 1 ELSE 0 END),0) AS capture_md5,
            coalesce(sum(CASE WHEN stored_md5 IS NULL AND conditional_etag IS NOT NULL THEN 1 ELSE 0 END),0) AS listing_etag,
            coalesce(sum(CASE WHEN md5_conflict THEN 1 ELSE 0 END),0) AS md5_conflicts,
            coalesce(sum(CASE WHEN size_conflict THEN 1 ELSE 0 END),0) AS size_conflicts,
            coalesce(sum(CASE WHEN capture_conflict THEN 1 ELSE 0 END),0) AS capture_conflicts,
            coalesce(sum(CASE WHEN md5_conflict OR size_conflict OR capture_conflict THEN 1 ELSE 0 END),0) AS conflicts,
            coalesce(sum(fallback_missing),0) AS fallback_missing,
            coalesce(sum(fallback_conflict),0) AS fallback_conflict,
            coalesce(sum(fallback_pin),0) AS fallback_pin
            FROM pending_bodies WHERE NOT ({
                "coalesce(stored_bytes>67108864,false) AND coalesce(known_format IN ('html','xml','json'),false)" if combined else
                'coalesce(stored_bytes>67108864,false)' if parser!='sniff' else 'false'})''')]
        if raw_ranges else []))
    if any(rows[0]['n'] for name,rows in checks.items() if name not in {'work_items','raw_custody'}):
        raise ValueError('Conflicting or incomplete pinned body metadata')
    planned=dict(status='planned',work=work,work_list=work/'work-list.parquet',
        body_admissions=work/'body-admissions.parquet' if combined else None,
        parser=parser,parser_version=version,versions=versions,limits=limits,
        local_root=raw,decided_at=decided_at,work_items=checks['work_items'][0]['n'],raw_ranges=raw_ranges,
        raw_custody=checks.get('raw_custody',[None])[0])
    if max_work_items is not None and planned['work_items']>max_work_items:
        raise BackfillRequired(planned,max_work_items)
    return planned


def stage(*,worker_factory=ParserWorker,unreadable_store=None,body_store=None,
          max_cache_bytes=RAW_CACHE_BYTES,max_get_workers=64,
          parser_workers=1,parser_memory_bytes=PARSER_MEMORY_BYTES,request_timings=False,**kwargs):
    """Use the same admitted plan for legacy single-parser and combined staging."""
    _raw_policy(body_store,max_cache_bytes,max_get_workers)
    ParserWorkerPool.validate_budget(parser_workers,parser_memory_bytes,WORKER_MEMORY_BYTES)
    if type(request_timings) is not bool:raise ValueError('Request timings must be an explicit boolean')
    if kwargs.get('raw_ranges') and body_store is None:raise ValueError('Ranged staging requires the maintained raw store')
    if body_store is not None:kwargs['raw_ranges']=True
    planned=plan(**kwargs)
    return _execute_plan(planned,engine=kwargs['engine'],worker_factory=worker_factory,
                         unreadable_store=unreadable_store,body_store=body_store,
                         max_cache_bytes=max_cache_bytes,max_get_workers=max_get_workers,
                         parser_workers=parser_workers,parser_memory_bytes=parser_memory_bytes,request_timings=request_timings)


def _execute_plan(planned,*,engine,worker_factory=ParserWorker,unreadable_store=None,
                  work=None,items=None,work_items=None,body_store=None,
                  cache_root=None,max_cache_bytes=RAW_CACHE_BYTES,max_get_workers=64,
                  parser_workers=1,parser_memory_bytes=PARSER_MEMORY_BYTES,request_timings=False):
    ParserWorkerPool.validate_budget(parser_workers,parser_memory_bytes,WORKER_MEMORY_BYTES)
    parser=planned['parser'];version=planned['parser_version'];combined=parser=='readings'
    versions=planned['versions'];limits=planned['limits'];raw=planned['local_root']
    decided_at=planned['decided_at']
    if work is None:work=planned['work']
    else:work=Path(work);work.mkdir(parents=True,exist_ok=False)
    if items is None:items=parquet_records(planned['work_list'])
    prefetched={};cleanup=[];cache_use=dict(prefetched=0,ranges=0,actual=0,reserve=0)
    cache_root=Path(cache_root or planned['work']).resolve()
    if body_store is not None:
        if planned['raw_custody']['missing_pins'] or planned['raw_custody']['conflicts']:raise RawCustodyRequired(planned)
        if body_store.cache_dir is None or not body_store.cache_dir.resolve().is_relative_to(cache_root):
            raise ValueError('Ranged reads require an owned cache below the producer work directory')
        items=list(items)
        candidates=[item for item in items if item['physical_key'] is not None and item['stored_bytes']<=MAX_STORED_BYTES
            and (item.get('page_hint') or item.get('known_format') in {'html','xml','json'} or parser in {'html','xml','json'})
            and body_store._immutable_cache_path(item['physical_key']) is not None]
        # Identity plus at most three disjoint sniff/page ranges, in filesystem blocks.
        cache_use['reserve']=len(items)*4*max(4096,os.statvfs(cache_root).f_frsize)
        cache_use['prefetched']=sum(item['stored_bytes'] for item in candidates)
        if cache_use['prefetched']*2+cache_use['reserve']>max_cache_bytes:
            raise ValueError('Ranged page prefetch exceeds the cache budget')
        pins={item['physical_key']:dict(etag=item['conditional_etag'],md5=item['stored_md5'],bytes=item['captured_stored_bytes']) for item in candidates}
        prefetched={item['body_sha'].hex():body_store._immutable_cache_path(item['physical_key']) for item in candidates}
    quota=(max_cache_bytes-2*cache_use['prefetched']-cache_use['reserve'])//parser_workers
    local=threading.local()
    parsed=work/'parsed';parsed.mkdir()
    decisions_path=parsed/'unreadable.jsonl'
    counters=dict(pending_reads=0,read_bytes=0,unreadable=0,ambiguous_gzip=0,**dict.fromkeys(GZIP_RULE_FIELDS,0))
    trace=None;trace_path=work/'read-timings.jsonl.gz' if request_timings else None
    def record_timing(phase,body,values):
        if trace is not None:trace.write(json.dumps(dict(phase=phase,body_sha=body,**values),separators=(',',':'))+'\n')
    def jobs():
        source=iter(items)
        while window:=list(islice(source,4*parser_workers)):
            if body_store is not None:
                selected={item['physical_key']:pins[item['physical_key']] for item in window
                    if item['body_sha'].hex() in prefetched}
                timings=[] if request_timings else None
                # A new window overlaps range reads already running in the pool.
                # Reserve those slots within the global64-request ceiling.
                try:body_store.prefetch_immutable(list(selected),expected=selected,
                    max_workers=min(max_get_workers,64-parser_workers),timings=timings)
                finally:
                    for timing in timings or ():
                        key=timing.pop('key');record_timing('prefetch',body_object_digest(key),timing)
                cache_use['actual']+=sum(_cache_file_bytes(prefetched[item['body_sha'].hex()])
                    for item in window if item['body_sha'].hex() in prefetched)
            for item in window:
                if item['physical_key'] is None:
                    counters['pending_reads']+=1;continue
                validate_key(item['physical_key'])
                relative=Path(item['relative_path'])
                if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                    raise ValueError('Body cache paths must be relative to the read-only root')
                path=(raw/relative).resolve()
                if not path.is_relative_to(raw):raise ValueError('Body path escapes read-only root')
                body_hex=item['body_sha'].hex()
                if body_object_digest(item['physical_key'])!=body_hex:
                    raise ValueError('Pinned physical key names a different body')
                cache=work/'body-bytes'/body_hex if combined or body_store is not None else None
                request=dict(path=str(path),body_sha=body_hex,parser=parser,stored_bytes=item['stored_bytes'],
                    stored_gzip=item['stored_gzip'])
                if combined or body_store is not None:
                    request.update(cache=str(cache),versions=versions,
                        known_format=item['known_format'] if combined else None if parser=='sniff' else parser,
                        skip_parsers=sorted(set(item.get('skip_parsers') or []) |
                            ({'sniff'} if item.get('known_format') is not None else set()) |
                            (set(versions)-{parser} if not combined else set())))
                    if body_store is not None:
                        request['original_bytes']=item['captured_bytes']
                        if request_timings:request['request_timings']=True
                        if body_hex in prefetched:request.update(path=str(prefetched[body_hex]),prefetched=True)
                        else:request['remote']=dict(bucket=body_store.bucket,key=item['physical_key'],
                            etag=item['conditional_etag'],md5=item['stored_md5'])
                yield body_hex,cache,request

    def invoke(worker,job):
        body_hex,cache,request=job
        actual=ranges=0;started=time.monotonic()
        try:
            if not combined and parser!='sniff' and request['stored_bytes']>MAX_STORED_BYTES:
                value=dict(status='size_limit',error_type='stored_size_limit')
                value=dict(rows=[value]) if body_store is not None else dict(row=value)
                outcome=dict(status='completed',value=value)
            else:
                if body_store is not None:
                    remaining=quota-getattr(local,'spent',0)
                    # Whole-page bytes and their local range copies are already
                    # reserved by the actual-size preflight, twice, for this batch.
                    request['max_read_bytes']=request['stored_bytes'] if request.get('prefetched') else max(0,remaining)
                outcome=worker.parse(body_hex,json.dumps(request,separators=(',',':')).encode())
        finally:
            if cache is not None and cache.exists():
                if body_store is None:shutil.rmtree(cache)
                else:
                    files=[p for p in cache.iterdir() if p.is_file()]
                    actual=sum(_cache_file_bytes(p) for p in files)
                    ranges=sum(_cache_file_bytes(p) for p in files if p.name!='identity.json')
                    if not request.get('prefetched'):local.spent=getattr(local,'spent',0)+ranges
        return body_hex,cache,outcome,actual,ranges,time.monotonic()-started,threading.get_ident()

    def rows():
        nonlocal trace
        with ParserWorkerPool(parser,version,
                'congress_api.lake.readings:'+('parse_once_payload' if combined or body_store is not None else 'parse_payload'),
                workers=parser_workers,memory_budget=parser_memory_bytes,worker_factory=worker_factory,**limits) as pool,decisions_path.open('x') as decisions,\
                gzip.open(trace_path,'xt') if trace_path is not None else nullcontext(None) as trace:
            for body_hex,cache,outcome,actual,ranges,seconds,worker_id in pool.map(invoke,jobs()):
                cache_use['actual']+=actual;cache_use['ranges']+=ranges
                record_timing('supervisor',body_hex,dict(seconds=seconds,worker=worker_id,status=outcome['status']))
                if outcome['status']=='read_error':
                    counters['pending_reads']+=1;continue
                if outcome['status']=='unreadable':
                    identity=json.dumps([body_hex,parser,version,decided_at],separators=(',',':'))
                    record=dict(id=sha256(identity.encode()).hexdigest(),body_sha256=body_hex,
                        parser=parser,parser_version=version,reason=outcome['reason'],
                        decided_by='readings',decided_at=decided_at,supersedes=None)
                    encoded=json.dumps(record,separators=(',',':'))+'\n'
                    decisions.write(encoded)
                    counters['unreadable']+=1;continue
                if outcome['status']!='completed':raise ValueError('Invalid reading worker outcome')
                response=outcome['value'];counters['read_bytes']+=response.get('read_bytes',0)
                for timing in response.get('read_timings',()):record_timing('range',body_hex,timing)
                if response.get('omitted_request_timings'):
                    record_timing('range_omitted',body_hex,dict(count=response['omitted_request_timings']))
                rule=response.get('gzip_rule')
                if type(rule) is int and 1<=rule<=4:counters['gzip_rule'+str(rule)]+=1
                if response.get('read_error'):
                    counters['ambiguous_gzip']+=int(response.get('ambiguous_gzip',False))
                    counters['pending_reads']+=1;continue
                value=response.get('rows') if combined or body_store is not None else response['row']
                values=value if combined or body_store is not None else [value]
                if body_store is not None and values:
                    cleanup.append(str(cache))
                    if body_hex in prefetched:cleanup.append(str(prefetched[body_hex]))
                for value in values:
                    value=dict(value,body_hex=body_hex,parser=value.get('parser',parser),parser_version=value.get('parser_version',version),
                        fingerprint_hex=value.get('fingerprint'),named_meetings=value.get('named_meetings',[]),
                        links=value.get('links',[]),fields=value.get('fields',[]))
                    value.pop('fingerprint',None)
                    yield value
    source=json_input(parsed,'parsed_readings',rows(),**_reading_fields())
    columns=["arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha",
             *[f'cast({name} AS DATE) AS {name}' if name=='content_date' else name for name in STRINGS],
             *INTEGERS,'intact','named_meetings','links',
             "arrow_cast(decode(fingerprint_hex,'hex'),'FixedSizeBinary(32)') AS fingerprint",'fields']
    run_job(parsed,engine,inputs=[source],steps=[],outputs=[parquet_output(work,'readings',
        'SELECT '+','.join(columns)+' FROM parsed_readings',PK)])
    key=path=unreadable_stage=unreadable_provenance=unreadable_custody=None
    pending=bool(counters['unreadable'] and unreadable_store is None)
    if counters['unreadable']:
        if pending:
            unreadable_stage=work/'unreadable-stage';unreadable_stage.mkdir()
            imported=import_unreadable(BodyStore(LocalAdapter(unreadable_stage)),decisions_path,decided_at=decided_at)
            path=str(unreadable_stage/imported['key'])
            finish_stage(unreadable_stage,kind='unreadable',provenance=imported['key'],
                records=counters['unreadable'],inputs={},extra=dict(decided_at=decided_at))
        else:
            imported=import_unreadable(unreadable_store,decisions_path,decided_at=decided_at)
            unreadable_provenance,unreadable_custody=imported_unreadable_provenance(imported,unreadable_store,decisions_path)
        key=imported['key']
    return dict(readings=work/'readings.parquet',work_list=planned['work_list'],
        parser=parser,parser_version=version,unreadable_key=key,unreadable_path=path,
        unreadable_stage=unreadable_stage,unreadable_pending=pending,
        unreadable_provenance=unreadable_provenance,
        _unreadable_custody=unreadable_custody,
        body_admissions=planned['body_admissions'],
        work_items=planned['work_items'] if work_items is None else work_items,
        cache_bytes=cache_use['actual'],request_timings=trace_path,
        _cache_cleanup=cleanup,_cache_root=str(cache_root),**counters)


def _cache_file_bytes(path):
    observed=path.stat()
    return max(observed.st_size,getattr(observed,'st_blocks',0)*512)


def _clean_committed_cache(staged):
    if staged.get('append') is None:raise ValueError('A successful readings append is required before cache cleanup')
    root=Path(staged['_cache_root']).resolve();removed=0
    for value in dict.fromkeys(staged['_cache_cleanup']):
        path=Path(value)
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Cache cleanup escapes owned work')
        if path.is_dir():
            removed+=sum(_cache_file_bytes(p) for p in path.rglob('*') if p.is_file());shutil.rmtree(path)
        elif path.exists():removed+=_cache_file_bytes(path);path.unlink()
    staged['cache_retained_bytes']=max(0,staged['cache_bytes']-removed)
    return staged['cache_retained_bytes']


def stage_once(**kwargs):
    """Stage sniff and page evidence from one cached read per body."""
    return stage(**kwargs,parser=None)


def create_table(**kwargs):
    from congress_api.lake.tables import create_table as native_create
    return native_create(**kwargs,schema=json.loads((ROOT/'model/lake/readings.schema.json').read_text()),
        partition_spec={'spec-id':0,'fields':[
            {'source-id':2,'field-id':1000,'name':'parser','transform':'identity'},
            {'source-id':3,'field-id':1001,'name':'parser_version','transform':'identity'}]})


def append(staged,**kwargs):
    if staged.get('unreadable_pending'):
        raise ValueError('Pending unreadable decisions require durable import: '
            '.venv/bin/python -I -m congress_api.cli.provenance --stage '+str(staged['unreadable_stage'])+' --apply --bucket congressional-tech-raw')
    from congress_api.lake.tables import append_rows
    return append_rows(staged['readings'],**kwargs,keys=PK,
        definition='readings:'+staged['parser']+':'+staged['parser_version'])


def run(*,engine,work,mode,execute=False,max_work_items=None,batch_size=None,parser=None,
        table=None,catalog_root=None,read_current=None,existing=None,
        unreadable_store=None,read_unreadable=None,unreadable_snapshot=None,worker_factory=ParserWorker,
        body_store=None,raw_ranges=False,max_cache_bytes=RAW_CACHE_BYTES,max_get_workers=64,
        parser_workers=1,parser_memory_bytes=PARSER_MEMORY_BYTES,request_timings=False,**inputs):
    """Admit one plan; execute daily once, or stream bounded backfill batches.

    The native anti-join runs once per invocation. The sorted metadata work list
    is consumed once, O(N), with bounded persistent workers per batch. Resuming means a fresh
    current-table read and anti-join, never a local journal or stale saved plan.
    """
    if mode not in {'daily','backfill'}:raise ValueError('mode must be daily or backfill')
    if type(execute) is not bool:raise ValueError('execute must be boolean')
    if type(raw_ranges) is not bool:raise ValueError('raw_ranges must be an explicit boolean')
    _raw_policy(body_store,max_cache_bytes,max_get_workers)
    ParserWorkerPool.validate_budget(parser_workers,parser_memory_bytes,WORKER_MEMORY_BYTES)
    if type(request_timings) is not bool:raise ValueError('Request timings must be an explicit boolean')
    raw_ranges=raw_ranges or body_store is not None
    if execute and raw_ranges and body_store is None:raise ValueError('Ranged execution requires the maintained raw store')
    if mode=='daily':
        _positive(max_work_items,'max_work_items')
        if batch_size is not None:raise ValueError('batch_size is only for backfill')
    else:
        _positive(batch_size,'batch_size')
        if max_work_items is not None:raise ValueError('max_work_items is only for daily')
    if existing is not None and (mode=='backfill' or execute):
        raise ValueError('Execution and backfill require current lake readings, not existing pins')
    if execute and unreadable_store is None:
        raise ValueError('Execution requires an explicit durable unreadable store')
    if unreadable_snapshot is not None:
        from congress_api.retention.provenance_inventory import UnreadableInventory
        if (not isinstance(unreadable_snapshot,UnreadableInventory)
                or unreadable_snapshot.store is not unreadable_store or read_unreadable is not None):
            raise ValueError('Readings require an inventory bound to the same unreadable store')
    work=Path(work).resolve()
    if execute or mode=='backfill':
        from congress_api.lake.tables import validate_catalog_authority
        validate_catalog_authority(engine,catalog_root)
        if not table:raise ValueError('Current readings require an explicit table identifier')
        if read_current is None:
            from congress_api.lake.tables import resolve_tables
            existing=resolve_tables(engine=engine,work=work/'current',catalog_root=catalog_root,
                tables={'readings':table})['readings']
        else:
            existing=read_current(engine=engine,work=work/'current',catalog_root=catalog_root,table=table)
    if execute:
        # The daily controller shares its complete qualified snapshot. A
        # standalone invocation discovers current filenames once before planning.
        if unreadable_snapshot is not None:
            fresh=unreadable_snapshot.files()
        elif read_unreadable is not None:
            fresh=read_unreadable(store=unreadable_store)
        else:
            from congress_api.retention.provenance_inventory import unreadable_inventory
            unreadable_snapshot=unreadable_inventory(unreadable_store,work=work/'unreadable-inventory')
            fresh=unreadable_snapshot.files()
        inventory={r['key']:r for r in inputs.get('unreadable_files',())}
        inventory.update({r['key']:r for r in fresh})
        inputs['unreadable_files']=list(inventory.values())
    planned=plan(engine=engine,work=work/'plan',parser=parser,existing=existing,
        max_work_items=max_work_items if mode=='daily' else None,raw_ranges=raw_ranges,**inputs)
    report={name:planned[name] for name in ('status','work_items','work_list','body_admissions','parser','parser_version')}
    report.update(mode=mode,applied=False,batches=[])
    if raw_ranges:report['raw_custody']=planned['raw_custody']
    if not execute:return report
    if raw_ranges and (planned['raw_custody']['missing_pins'] or planned['raw_custody']['conflicts']):raise RawCustodyRequired(planned)
    report.update(status='completed',pending_reads=0,read_bytes=0,unreadable=0,ambiguous_gzip=0,**dict.fromkeys(GZIP_RULE_FIELDS,0))
    if planned['work_items']==0:return report
    size=planned['work_items'] if mode=='daily' else batch_size
    items=iter(parquet_records(planned['work_list']))
    retained_cache=0
    for number,start in enumerate(range(0,planned['work_items'],size)):
        count=min(size,planned['work_items']-start)
        batch_work=work/('batch-'+str(number).zfill(6))
        staged=_execute_plan(planned,engine=engine,work=batch_work,
            items=islice(items,count),worker_factory=worker_factory,work_items=count,
            unreadable_store=unreadable_store,body_store=body_store,cache_root=work,
            max_cache_bytes=max_cache_bytes-retained_cache,max_get_workers=max_get_workers,
            parser_workers=parser_workers,parser_memory_bytes=parser_memory_bytes,request_timings=request_timings)
        import pyarrow.parquet as pq
        staged['append']=(append(staged,engine=engine,work=batch_work/'append',
            catalog_root=catalog_root,table=table) if pq.ParquetFile(staged['readings']).metadata.num_rows else None)
        if body_store is not None:
            retained_cache+=_clean_committed_cache(staged) if staged['append'] is not None else staged['cache_bytes']
        report['batches'].append(staged)
        report['applied']|=staged['append'] is not None
        for key in ('pending_reads','read_bytes','unreadable','ambiguous_gzip')+GZIP_RULE_FIELDS:report[key]+=staged[key]
    if report['pending_reads']:report['status']='pending'
    return report


class _ReadOnceBody:
    """Keep disjoint bounded byte ranges for supervised parser retries."""
    def __init__(self,path,cache,stored_bytes,*,remote=None,body_store=None,stored_gzip=False,max_read_bytes=None,request_timings=False):
        import re
        self.path=Path(path) if remote is None else None
        self.remote,self.body_store,self.stored_gzip=remote,body_store,stored_gzip
        self.encoding=None
        self.max_read_bytes=max_read_bytes
        self.timings=[] if request_timings else None;self.omitted_timings=0
        self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True)
        self.source=None;self.size=stored_bytes;self.ranges=[]
        if remote is None:
            with reading_input():observed=self.path.stat()
            if not stat.S_ISREG(observed.st_mode) or observed.st_size!=stored_bytes:raise OSError('changed_input')
            self.identity=[observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns]
        else:
            from congress_api.retention.r2 import _raw_pin
            expected=_raw_pin(remote['key'],{**{k:remote[k] for k in ('etag','md5') if k in remote},'bytes':stored_bytes})
            self.identity=dict(kind='r2',bucket=remote['bucket'],key=remote['key'],**expected,stored_gzip=stored_gzip)
        pin=self.cache/'identity.json'
        if pin.exists():
            previous=json.loads(pin.read_text())
            if remote is not None and isinstance(previous,dict):
                self.encoding=previous.pop('encoding',None)
                if self.encoding not in (None,'','gzip'):raise OSError('invalid_range_encoding')
                self.stored_gzip=stored_gzip or self.encoding=='gzip'
            if previous!=self.identity:raise OSError('changed_input')
        else:pin.write_text(json.dumps(self.identity))
        for path in self.cache.glob('*.bin'):
            match=re.fullmatch(r'(\d+)-(\d+)\.bin',path.name)
            if not match:raise OSError('invalid_range_cache')
            start,end=map(int,match.groups())
            if not 0<=start<end<=self.size or path.stat().st_size!=end-start:
                raise OSError('invalid_range_cache')
            self.ranges.append((start,end,path))
        self.ranges.sort()

    def close(self):
        if self.source is not None:self.source.close()

    @property
    def read_bytes(self):
        return sum(end-start for start,end,_ in self.ranges)

    def read(self,start,length):
        if not 0<=start<=start+length<=self.size:raise OSError('invalid_range')
        cursor=start;end=start+length;pieces=[]
        while cursor<end:
            cached=next((item for item in self.ranges if item[0]<=cursor<item[1]),None)
            if cached:
                left,right,path=cached;stop=min(end,right)
                with reading_input(),path.open('rb') as stream:
                    stream.seek(cursor-left);piece=stream.read(stop-cursor)
                if len(piece)!=stop-cursor:raise OSError('short_cache_read')
            else:
                stop=min([end]+[left for left,_,_ in self.ranges if left>cursor])
                if self.max_read_bytes is not None and self.read_bytes+stop-cursor>self.max_read_bytes:
                    raise OSError('raw_cache_budget')
                with reading_input():
                    if self.remote is not None:
                        from botocore.exceptions import BotoCoreError,ClientError
                        metadata={}
                        try:
                            store=self.body_store or _ranged_store(self.remote['bucket'])
                            timing={} if self.timings is not None else None
                            try:
                                piece=store.read(self.remote['key'],start=cursor,length=stop-cursor,
                                    expected={k:self.identity[k] for k in ('etag','md5','bytes')},metadata=metadata,timing=timing)
                            finally:
                                if timing is not None:
                                    if len(self.timings)<128:self.timings.append(dict(start=cursor,length=stop-cursor,**timing))
                                    else:self.omitted_timings+=1
                        except (BotoCoreError,ClientError,ValueError) as error:
                            raise OSError('raw_range_'+type(error).__name__) from None
                        encoding=metadata.get('content_encoding') or ''
                        if encoding not in ('','gzip') or self.encoding not in (None,encoding):
                            raise OSError('changed_storage_encoding')
                        if self.encoding is None:
                            self.encoding=encoding;self.stored_gzip=self.stored_gzip or encoding=='gzip'
                            (self.cache/'identity.json').write_text(json.dumps(dict(self.identity,encoding=encoding)))
                    else:
                        if self.source is None:
                            self.source=self.path.open('rb')
                            observed=os.fstat(self.source.fileno())
                            current=[observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns]
                            if current!=self.identity:raise OSError('changed_input')
                        self.source.seek(cursor);piece=self.source.read(stop-cursor)
                    if len(piece)!=stop-cursor:raise OSError('short_read')
                    path=self.cache/f'{cursor}-{stop}.bin';pending=path.with_suffix('.pending')
                    pending.write_bytes(piece);pending.replace(path)
                self.ranges.append((cursor,stop,path));self.ranges.sort()
            pieces.append(piece);cursor=stop
        return b''.join(pieces)


@lru_cache(maxsize=2)
def _ranged_store(bucket):
    """One maintained SDK client per persistent worker; credentials stay in env."""
    from congress_shared.storage import R2Config,connect_r2
    from congress_api.retention.r2 import R2Store
    return R2Store(connect_r2(R2Config.from_env(bucket=bucket)),bucket)


def _page_entity(stored,body_sha):
    """Prove storage decoding from the content-addressed identity, not suffix."""
    if sha256(stored).hexdigest()==body_sha:return stored,False
    if stored.startswith(b'\x1f\x8b'):
        import io
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:data=stream.read(MAX_DECODED_BYTES+1)
        except (OSError,EOFError,zlib.error):raise OSError('invalid_storage_gzip') from None
        if len(data)>MAX_DECODED_BYTES:return None,True
        if sha256(data).hexdigest()==body_sha:return data,True
    raise OSError('decoded_sha_mismatch')


def parse_once_payload(payload,*,body_store=None):
    """Use one bounded source read for sniff and its actual page parser."""
    from congress_api.retention.sniff import read_sniff
    from congress_api.parsers.archive_readings import read_page
    request=json.loads(payload);source=None
    def result(**value):
        if request.get('request_timings'):
            value.update(read_timings=[] if source is None else source.timings,
                omitted_request_timings=0 if source is None else source.omitted_timings)
        return value
    try:
        versions=request['versions'];skip=set(request['skip_parsers']);rows=[];data=None;gzip_rule=None
        known=request['known_format']
        def open_source():
            return _ReadOnceBody(request['path'],request['cache'],request['stored_bytes'],
                remote=request.get('remote'),body_store=body_store,stored_gzip=request['stored_gzip'],
                max_read_bytes=request.get('max_read_bytes'),request_timings=request.get('request_timings',False))
        if request.get('remote') and body_object_digest(request['remote']['key'])!=request['body_sha']:
            raise OSError('body_key_mismatch')
        if request.get('prefetched'):
            source=open_source()
            data,source.stored_gzip=_page_entity(source.read(0,source.size),request['body_sha'])
        elif known is None:
            source=open_source()
            head=source.read(0,min(source.size,8192))
            if request.get('remote'):
                if not head.startswith(b'\x1f\x8b'):
                    source.stored_gzip=False;gzip_rule=1
                elif not source.stored_gzip:
                    if source.size<=len(head):
                        data,source.stored_gzip=_page_entity(head,request['body_sha'])
                        if data is None:raise OSError('ambiguous_gzip_decoded_size_limit')
                    else:
                        gzip_rule=4;original=request.get('original_bytes')
                        if type(original) is int and original>=0 and request['remote']['key'].endswith('.gz'):
                            isize=int.from_bytes(source.read(source.size-4,4),'little')
                            if original!=source.size and isize==original%(1<<32):
                                source.stored_gzip=True;gzip_rule=2
                        # Rule3 needs historical single-member writer proof,
                        # which these inputs do not establish. Equality is ambiguous.
                        if gzip_rule==4:raise OSError('ambiguous_storage_gzip')
        sniff=(dict(status='completed',format=known) if known is not None else
            read_sniff(source.read,stored_size=source.size,stored_gzip=source.stored_gzip))
        if 'sniff' not in skip:
            rows.append(dict(sniff,parser='sniff',parser_version=versions['sniff']))
        parser=sniff.get('format')
        if sniff['status']=='completed' and parser in {'html','xml','json'} and parser not in skip:
            if request['stored_bytes']>MAX_STORED_BYTES:
                row=dict(status='size_limit',error_type='stored_size_limit')
            else:
                if source is None:source=open_source()
                if not request.get('prefetched') and data is None:
                    data,source.stored_gzip=_page_entity(source.read(0,source.size),request['body_sha'])
                row=(dict(status='error',error_type='decoded_size_limit') if data is None else read_page(data,parser))
            rows.append(dict(row,parser=parser,parser_version=versions[parser]))
        return result(rows=rows,gzip_rule=gzip_rule,read_bytes=0 if source is None else source.read_bytes)
    except (OSError,EOFError) as error:
        return result(read_error=type(error).__name__,gzip_rule=gzip_rule,ambiguous_gzip=str(error)=='ambiguous_storage_gzip',
            rows=[],read_bytes=0 if source is None else source.read_bytes)
    finally:
        if source is not None:source.close()
