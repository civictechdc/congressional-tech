"""Native body work lists, bounded parser invocations and typed reading stages."""
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import stat
import shutil
from contextlib import nullcontext
from itertools import islice

from congress_api.lake.tables import table_input
from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.parser_worker import ParserWorker, reading_input
from congress_api.retention.provenance import (field, instant, json_input, list_of,
    parquet_output, parquet_records, run_job, struct, finish_stage, import_unreadable,
    imported_unreadable_provenance)

ROOT=Path(__file__).resolve().parents[5]
PK=['body_sha','parser','parser_version']
MAX_STORED_BYTES=64<<20
MAX_DECODED_BYTES=64<<20
WORKER_MEMORY_BYTES=512<<20
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
        'resources':Path(__file__).parents[1]/'retention/process_resources.py'}
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


def _positive(value,name):
    if type(value) is not int or value<=0:
        raise ValueError(name+' must be a positive integer')
    return value


def plan(*,captures,body_inventory,local_root,engine,work,decided_at,parser,
         sniff_version=None,parser_version=None,existing=None,unreadable_files=(),max_work_items=None):
    """Materialize one native missing-body work list, without opening raw bodies."""
    if max_work_items is not None:_positive(max_work_items,'max_work_items')
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
            table_input('captures',captures),
            dict(name='body_inventory',kind='parquet',path=str(Path(body_inventory).resolve()))]
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
    settled_join=' LEFT JOIN settled_parsers sp ON b.body_sha=sp.body_sha' if combined else ''
    sql=f'''SELECT b.body_sha,i.physical_key,i.relative_path,i.stored_bytes,i.stored_gzip{extra}
        FROM bodies b LEFT JOIN body_inventory i ON b.body_sha=i.body_sha{settled_join}
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
        dict(name='invalid_inventory',sql='''SELECT count(*) AS n FROM body_inventory
            WHERE body_sha IS NULL OR physical_key IS NULL OR relative_path IS NULL
               OR stored_bytes IS NULL OR stored_bytes<0 OR stored_gzip IS NULL''')]+([
        dict(name='writer_admission_conflicts',sql=writer_admission_conflict_sql())]
        if combined else [])+[dict(name='work_items',sql='SELECT count(*) AS n FROM pending_bodies')])
    if any(rows[0]['n'] for name,rows in checks.items() if name!='work_items'):
        raise ValueError('Conflicting or incomplete pinned body metadata')
    planned=dict(status='planned',work=work,work_list=work/'work-list.parquet',
        body_admissions=work/'body-admissions.parquet' if combined else None,
        parser=parser,parser_version=version,versions=versions,limits=limits,
        local_root=raw,decided_at=decided_at,work_items=checks['work_items'][0]['n'])
    if max_work_items is not None and planned['work_items']>max_work_items:
        raise BackfillRequired(planned,max_work_items)
    return planned


def stage(*,worker_factory=ParserWorker,unreadable_store=None,**kwargs):
    """Use the same admitted plan for legacy single-parser and combined staging."""
    planned=plan(**kwargs)
    return _execute_plan(planned,engine=kwargs['engine'],worker_factory=worker_factory,
                         unreadable_store=unreadable_store)


def _execute_plan(planned,*,engine,worker_factory=ParserWorker,unreadable_store=None,
                  work=None,items=None,worker=None,work_items=None):
    parser=planned['parser'];version=planned['parser_version'];combined=parser=='readings'
    versions=planned['versions'];limits=planned['limits'];raw=planned['local_root']
    decided_at=planned['decided_at']
    if work is None:work=planned['work']
    else:work=Path(work);work.mkdir(parents=True,exist_ok=False)
    if items is None:items=parquet_records(planned['work_list'])
    parsed=work/'parsed';parsed.mkdir()
    decisions_path=parsed/'unreadable.jsonl'
    counters=dict(pending_reads=0,read_bytes=0,unreadable=0)
    def rows():
        context=(nullcontext(worker) if worker is not None else worker_factory(parser,version,
            'congress_api.lake.readings:'+('parse_once_payload' if combined else 'parse_payload'),**limits))
        with context as active_worker,decisions_path.open('x') as decisions:
            for item in items:
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
                cache=work/'body-bytes'/body_hex if combined else None
                try:
                    if not combined and parser!='sniff' and item['stored_bytes']>MAX_STORED_BYTES:
                        value=dict(status='size_limit',error_type='stored_size_limit')
                    else:
                        payload=json.dumps(dict(path=str(path),parser=parser,stored_bytes=item['stored_bytes'],
                            stored_gzip=item['stored_gzip']),separators=(',',':')).encode()
                        if combined:
                            payload=json.dumps(dict(path=str(path),cache=str(cache),stored_bytes=item['stored_bytes'],
                                stored_gzip=item['stored_gzip'],versions=versions,known_format=item['known_format'],
                                skip_parsers=sorted(set(item['skip_parsers'] or []) | ({'sniff'} if item['known_format'] is not None else set()))),separators=(',',':')).encode()
                        outcome=active_worker.parse(body_hex,payload)
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
                        if response.get('read_error'):
                            counters['pending_reads']+=1;continue
                        value=response.get('rows') if combined else response['row']
                    for value in (value if combined else [value]):
                        value=dict(value,body_hex=body_hex,parser=value.get('parser',parser),parser_version=value.get('parser_version',version),
                            fingerprint_hex=value.get('fingerprint'),named_meetings=value.get('named_meetings',[]),
                            links=value.get('links',[]),fields=value.get('fields',[]))
                        value.pop('fingerprint',None)
                        yield value
                finally:
                    if cache is not None and cache.exists():shutil.rmtree(cache)
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
        work_items=planned['work_items'] if work_items is None else work_items,**counters)


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
        unreadable_store=None,read_unreadable=None,unreadable_snapshot=None,worker_factory=ParserWorker,**inputs):
    """Admit one plan; execute daily once, or stream bounded backfill batches.

    The native anti-join runs once per invocation. The sorted metadata work list
    is consumed once, O(N), with one persistent worker. Resuming means a fresh
    current-table read and anti-join, never a local journal or stale saved plan.
    """
    if mode not in {'daily','backfill'}:raise ValueError('mode must be daily or backfill')
    if type(execute) is not bool:raise ValueError('execute must be boolean')
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
        max_work_items=max_work_items if mode=='daily' else None,**inputs)
    report={name:planned[name] for name in ('status','work_items','work_list','body_admissions','parser','parser_version')}
    report.update(mode=mode,applied=False,batches=[])
    if not execute:return report
    report.update(status='completed',pending_reads=0,read_bytes=0,unreadable=0)
    if planned['work_items']==0:return report
    size=planned['work_items'] if mode=='daily' else batch_size
    items=iter(parquet_records(planned['work_list']))
    callable_name='parse_once_payload' if parser is None else 'parse_payload'
    with worker_factory(planned['parser'],planned['parser_version'],
            'congress_api.lake.readings:'+callable_name,**planned['limits']) as worker:
        for number,start in enumerate(range(0,planned['work_items'],size)):
            count=min(size,planned['work_items']-start)
            batch_work=work/('batch-'+str(number).zfill(6))
            staged=_execute_plan(planned,engine=engine,work=batch_work,
                items=islice(items,count),worker=worker,work_items=count,
                unreadable_store=unreadable_store)
            import pyarrow.parquet as pq
            staged['append']=(append(staged,engine=engine,work=batch_work/'append',
                catalog_root=catalog_root,table=table) if pq.ParquetFile(staged['readings']).metadata.num_rows else None)
            report['batches'].append(staged)
            report['applied']|=staged['append'] is not None
            for key in ('pending_reads','read_bytes','unreadable'):report[key]+=staged[key]
    if report['pending_reads']:report['status']='pending'
    return report


class _ReadOnceBody:
    """Keep disjoint bounded byte ranges for supervised parser retries."""
    def __init__(self,path,cache,stored_bytes):
        import re
        self.path=Path(path);self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True)
        self.source=None;self.size=stored_bytes;self.ranges=[]
        with reading_input():
            observed=self.path.stat()
        if not stat.S_ISREG(observed.st_mode) or observed.st_size!=stored_bytes:
            raise OSError('changed_input')
        self.identity=[observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns]
        pin=self.cache/'identity.json'
        if pin.exists():
            if json.loads(pin.read_text())!=self.identity:raise OSError('changed_input')
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
                with reading_input():
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


def parse_once_payload(payload):
    """Use one bounded source read for sniff and its actual page parser."""
    import io
    from congress_api.retention.sniff import read_sniff
    from congress_api.parsers.archive_readings import read_page
    request=json.loads(payload);source=None
    try:
        versions=request['versions'];skip=set(request['skip_parsers']);rows=[]
        known=request['known_format']
        if known is None:
            source=_ReadOnceBody(request['path'],request['cache'],request['stored_bytes'])
        sniff=(dict(status='completed',format=known) if known is not None else
            read_sniff(source.read,stored_size=source.size,stored_gzip=request['stored_gzip']))
        if 'sniff' not in skip:
            rows.append(dict(sniff,parser='sniff',parser_version=versions['sniff']))
        parser=sniff.get('format')
        if sniff['status']=='completed' and parser in {'html','xml','json'} and parser not in skip:
            if request['stored_bytes']>MAX_STORED_BYTES:
                row=dict(status='size_limit',error_type='stored_size_limit')
            else:
                if source is None:source=_ReadOnceBody(request['path'],request['cache'],request['stored_bytes'])
                stored=source.read(0,source.size)
                if request['stored_gzip']:
                    try:
                        with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
                            data=stream.read(MAX_DECODED_BYTES+1)
                    except (OSError,EOFError):
                        row=dict(status='error',error_type='invalid_gzip');data=None
                else:data=stored
                if data is not None:
                    row=(dict(status='error',error_type='decoded_size_limit') if len(data)>MAX_DECODED_BYTES else
                         read_page(data,parser))
            rows.append(dict(row,parser=parser,parser_version=versions[parser]))
        return dict(rows=rows,read_bytes=0 if source is None else source.read_bytes)
    except (OSError,EOFError) as error:
        return dict(read_error=type(error).__name__,rows=[],read_bytes=0 if source is None else source.read_bytes)
    finally:
        if source is not None:source.close()
