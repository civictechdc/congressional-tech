"""Native body work lists, bounded parser invocations and typed reading stages."""
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import stat

from congress_api.retention.body_store import BodyStore, LocalAdapter, validate_key
from congress_api.retention.body_keys import body_object_digest
from congress_api.retention.parser_worker import ParserWorker, reading_input
from congress_api.retention.provenance import (field, instant, json_input, list_of,
    parquet_output, parquet_records, run_job, struct, finish_stage, import_unreadable)

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
        'producer':Path(__file__), 'supervisor':Path(__file__).parents[1]/'retention/parser_worker.py',
        'resources':Path(__file__).parents[1]/'retention/process_resources.py',
        'lock':ROOT/'uv.lock','schema':ROOT/'model/lake/readings.schema.json'},
        values=dict(parser=parser,stored_bytes=MAX_STORED_BYTES,decoded_bytes=MAX_DECODED_BYTES,
                    memory_bytes=WORKER_MEMORY_BYTES,timeout_seconds=WORKER_TIMEOUT_SECONDS))


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


def stage(*,captures,body_inventory,local_root,engine,work,decided_at,parser,
          sniff_version=None,parser_version=None,existing=None,unreadable_files=(),
          worker_factory=ParserWorker,unreadable_store=None):
    """Stage missing readings; raw decisions require an explicitly supplied store."""
    instant(decided_at)
    version=current_version(parser)
    if parser_version is not None and parser_version!=version:
        raise ValueError('Parser version does not match its current definition')
    if sniff_version is None:
        sniff_version=current_version('sniff')
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=False)
    raw=Path(local_root).resolve()
    inputs=[json_input(work,'parser_versions',[dict(parser='sniff',version=sniff_version)],parser='Utf8',version='Utf8'),
            dict(name='captures',kind='parquet',path=str(Path(captures).resolve())),
            dict(name='body_inventory',kind='parquet',path=str(Path(body_inventory).resolve()))]
    unreadable_schema=dict(id='Utf8',body_sha256='Utf8',parser='Utf8',parser_version='Utf8',supersedes='Utf8')
    if unreadable_files:
        inputs.append(dict(name='unreadable',kind='json_lines',files=list(unreadable_files),
            schema=dict(fields=[field(k,v) for k,v in unreadable_schema.items()],metadata={})))
    else:inputs.append(json_input(work,'unreadable',[],**unreadable_schema))
    if existing:
        inputs.append(dict(name='existing',kind='parquet',path=str(Path(existing).resolve())))
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
    candidate=(f"NOT EXISTS(SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha)" if parser=='sniff' else
               f"EXISTS(SELECT 1 FROM known_formats f WHERE f.body_sha=b.body_sha AND f.format={quote(parser)})")
    sql=f'''SELECT b.body_sha,i.physical_key,i.relative_path,i.stored_bytes,i.stored_gzip
        FROM bodies b LEFT JOIN body_inventory i ON b.body_sha=i.body_sha
        WHERE {candidate} AND NOT EXISTS(SELECT 1 FROM existing e WHERE e.body_sha=b.body_sha
          AND e.parser={quote(parser)} AND e.parser_version={quote(version)})
        AND NOT EXISTS(SELECT 1 FROM active_unreadable u WHERE u.body_sha256=encode(b.body_sha,'hex')
          AND u.parser={quote(parser)} AND u.parser_version={quote(version)})'''
    checks=run_job(work,engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(work,'work-list',sql,['body_sha'])],queries=[
        dict(name='conflicts',sql='''SELECT count(*) AS n FROM (
            SELECT body_sha FROM body_inventory GROUP BY body_sha HAVING count(*)>1
            UNION ALL SELECT body_sha FROM sniff_conflicts)'''),
        dict(name='invalid_inventory',sql='''SELECT count(*) AS n FROM body_inventory
            WHERE body_sha IS NULL OR physical_key IS NULL OR relative_path IS NULL
               OR stored_bytes IS NULL OR stored_bytes<0 OR stored_gzip IS NULL''')])
    if any(rows[0]['n'] for rows in checks.values()):
        raise ValueError('Conflicting or incomplete pinned body metadata')
    parsed=work/'parsed';parsed.mkdir()
    decisions_path=parsed/'unreadable.jsonl'
    counters=dict(pending_reads=0,read_bytes=0,unreadable=0)
    def rows():
        with worker_factory(parser,version,'congress_api.lake.readings:parse_payload',
                timeout_seconds=WORKER_TIMEOUT_SECONDS,memory_bytes=WORKER_MEMORY_BYTES,
                max_input_bytes=65536) as worker,decisions_path.open('x') as decisions:
            for item in parquet_records(work/'work-list.parquet'):
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
                if parser!='sniff' and item['stored_bytes']>MAX_STORED_BYTES:
                    value=dict(status='size_limit',error_type='stored_size_limit')
                else:
                    payload=json.dumps(dict(path=str(path),parser=parser,stored_bytes=item['stored_bytes'],
                        stored_gzip=item['stored_gzip']),separators=(',',':')).encode()
                    outcome=worker.parse(body_hex,payload)
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
                    value=response['row']
                value=dict(value,body_hex=body_hex,parser=parser,parser_version=version,
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
    key=path=unreadable_stage=None
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
        key=imported['key']
    return dict(readings=work/'readings.parquet',work_list=work/'work-list.parquet',
        parser=parser,parser_version=version,unreadable_key=key,unreadable_path=path,
        unreadable_stage=unreadable_stage,unreadable_pending=pending,**counters)


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

