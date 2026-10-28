"""Append-only provenance records and pinned, local-only import stages."""
from datetime import datetime
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from congress_shared.custody import verify_local_file

from congress_api.retention.body_store import BodyStore,LocalAdapter,validate_record
from congress_api.retention.receipt_privacy import cut_paths


KINDS=frozenset({'recoveries','reviews','unreadable'})
VERDICTS=frozenset({'hide','duplicate_of','title_override','kind_override','withdraw'})


def instant(value):
    if not isinstance(value,str):raise ValueError('An explicit source timestamp is required')
    try: stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ValueError('Invalid timestamp') from None
    if stamp.tzinfo is None:raise ValueError('Timestamp must include its timezone')
    return stamp


def timestamp_key(value):
    return instant(value).strftime('%Y%m%dT%H%M%S%z')


def validate_provenance(kind,row):
    if kind not in KINDS or not isinstance(row,dict):raise ValueError('Unsupported provenance kind')
    if kind=='unreadable':
        identities=set(row)&{'body_sha256','record_sha'}
        if len(identities)!=1:raise ValueError('Unreadable decision needs one input identity')
        required={'id','parser','parser_version','reason','decided_by','decided_at','supersedes'}|identities
    else:
        required=({'id','target','verdict','value','note','reviewer','decided_at','supersedes'} if kind=='reviews' else
            {'id','original_url','recovered_url','recovered_filename','body_sha256','kind','match_basis',
             'evidence_sha256','identity_note','decided_by','decided_at','supersedes'})
    if set(row)!=required or not isinstance(row['id'],str) or not row['id'].strip():
        raise ValueError('Incomplete provenance record')
    def text(name,*,nullable=False,allow_blank=False):
        value=row[name]
        if nullable and value is None:return
        if not isinstance(value,str) or (not allow_blank and not value.strip()):
            raise ValueError('Invalid provenance '+name)

    def url(name,*,nullable=False):
        if nullable and row[name] is None:return
        text(name)
        try:parts=urlsplit(row[name])
        except ValueError:raise ValueError('Invalid provenance '+name) from None
        if parts.scheme not in {'http','https'} or not parts.netloc:
            raise ValueError('Invalid provenance '+name)

    def digest(name,*,nullable=False):
        value=row[name]
        if nullable and value is None:return
        if not isinstance(value,str) or re.fullmatch('[0-9a-fA-F]{64}',value) is None:
            raise ValueError('Invalid provenance '+name)

    instant(row['decided_at'])
    if row['supersedes'] is not None and (not isinstance(row['supersedes'],str) or not row['supersedes'].strip()
                                         or row['supersedes']==row['id']):
        raise ValueError('Invalid superseded decision')
    if kind=='unreadable':
        identity=next(iter(identities))
        digest(identity)
        if re.fullmatch('[0-9a-f]{64}',row[identity]) is None:
            raise ValueError('Unreadable identity must be canonical lowercase SHA-256')
        for name in ('parser','parser_version','reason','decided_by'):text(name)
        if re.fullmatch('[a-z][a-z0-9_]*',row['reason']) is None:
            raise ValueError('Invalid unreadable reason')
    elif kind=='reviews':
        verdict=row['verdict']
        if (not isinstance(verdict,str) or verdict not in VERDICTS or not isinstance(row['target'],str)
                or re.fullmatch('[0-9a-f]{16}',row['target']) is None):
            raise ValueError('Invalid review target or verdict')
        text('reviewer')
        text('note',nullable=True,allow_blank=True)
        value=row['value']
        if ((verdict=='kind_override' and (not isinstance(value,list) or not value or
                any(not isinstance(v,str) or not v for v in value)))
            or verdict=='duplicate_of' and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{16}',value))
            or verdict=='title_override' and (not isinstance(value,str) or not value)
            or verdict=='hide' and type(value) is not bool
            or verdict=='withdraw' and (value is not None or row['supersedes'] is None)):
            raise ValueError('Invalid review value')
    else:
        url('original_url')
        url('recovered_url',nullable=True)
        digest('body_sha256')
        digest('evidence_sha256',nullable=True)
        text('kind')
        text('decided_by')
        text('match_basis',nullable=True)
        text('recovered_filename',nullable=True,allow_blank=True)
        text('identity_note',nullable=True,allow_blank=True)
    validate_record(row)
    def paths(value):
        if isinstance(value,str) and cut_paths(value)[1]:raise ValueError('Local path in public provenance')
        if isinstance(value,dict):
            for k,v in value.items():paths(k);paths(v)
        elif isinstance(value,list):
            for child in value:paths(child)
    paths(row)
    return row


def write_records(store,kind,records,*,timestamp):
    if kind=='unreadable':raise ValueError('Use content-qualified import_unreadable for unreadable decisions')
    if not isinstance(timestamp,str) or not re.fullmatch('[0-9A-Za-z+_.-]+',timestamp):
        raise ValueError('Invalid provenance timestamp key')
    key=f'provenance/{kind}/{timestamp}.jsonl'
    with TemporaryDirectory(prefix='raw-provenance-') as temporary:
        path=Path(temporary)/'records.jsonl'
        count=0;seen=set()
        with path.open('x',encoding='utf-8') as out:
            for row in records:
                validate_provenance(kind,row)
                if row['id'] in seen:raise ValueError('Duplicate provenance decision ID')
                seen.add(row['id'])
                out.write(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
                count+=1
        if not count:raise ValueError('Empty provenance batch')
        store.put(key,path,'application/x-ndjson')
    return key,count



def import_unreadable(store, decisions_path, *, decided_at, expected=None):
    """Validate and freeze producer decisions, then import exact bytes create-only."""
    stamp=timestamp_key(decided_at)
    with TemporaryDirectory(prefix='raw-unreadable-') as temporary:
        frozen=Path(temporary)/'decisions.jsonl'
        digest=sha256();count=0;size=0;seen=set()
        with Path(decisions_path).open('rb') as source,frozen.open('xb') as out:
            for line in source:
                row=validate_provenance('unreadable',json.loads(line))
                if row['id'] in seen:raise ValueError('Duplicate unreadable decision ID')
                seen.add(row['id'])
                out.write(line);digest.update(line);size+=len(line);count+=1
        if not count:raise ValueError('Empty unreadable batch')
        if expected is not None and expected!=dict(sha256=digest.hexdigest(),size=size):
            raise ValueError('Reviewed unreadable decisions changed before import')
        key='provenance/unreadable/'+stamp+'-'+digest.hexdigest()+'.jsonl'
        store.put(key,frozen,'application/x-ndjson')
    return dict(key=key,records=count,sha256=digest.hexdigest(),size=size)


def local_unreadable_inventory(store):
    """List current decision filenames once, without reading their records."""
    if not isinstance(store,BodyStore) or not isinstance(store.adapter,LocalAdapter):
        raise ValueError('Execution requires a current unreadable inventory reader')
    root=store.adapter.root.resolve()
    return [dict(key=p.relative_to(root).as_posix(),path=str(p))
            for p in sorted((root/'provenance/unreadable').glob('*.jsonl'))]


def imported_unreadable_provenance(imported,store,path):
    """Bind the acknowledged import to verified local bytes and private custody."""
    if isinstance(getattr(store,'adapter',None),LocalAdapter):
        path=store.adapter.root/imported['key']
    try:
        custody=verify_local_file(path,expected_sha256=imported['sha256'],expected_size=imported['size'])
    except (OSError,ValueError):
        raise ValueError('Acknowledged unreadable provenance changed or disappeared') from None
    public=dict(key=imported['key'],sha256=imported['sha256'],size=imported['size'],
                path=str(custody.path),etag=None)
    return public,custody


def record_review(store,record,*,timestamp):
    return write_records(store,'reviews',[record],timestamp=timestamp)[0]


def file_pin(path):
    with Path(path).open('rb') as source:
        digest=file_digest(source,'sha256').hexdigest()
        return dict(sha256=digest,size=source.tell())


def stage_records(root,kind,records,*,decided_at):
    root=Path(root)
    key,count=write_records(BodyStore(LocalAdapter(root)),kind,records,timestamp=timestamp_key(decided_at))
    return key,count


def finish_stage(root,*,kind,provenance,records,inputs,extra=None):
    root=Path(root)
    value=dict(version=1,kind=kind,provenance=provenance,records=records,inputs=inputs,
               files=[dict(path=provenance,**file_pin(root/provenance))],**(extra or {}))
    (root/'manifest.json').write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    return value


def load_stage(root):
    root=Path(root)
    if root.is_symlink():raise ValueError('Stage root must not be a symlink')
    root=root.resolve()
    value=json.loads((root/'manifest.json').read_text())
    if value.get('version')!=1 or value.get('kind') not in KINDS or not value.get('files'):
        raise ValueError('Invalid provenance stage')
    seen=set();count=0
    for item in value['files']:
        relative=Path(item['path']);path=(root/relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root) or item['path'] in seen:
            raise ValueError('Unsafe provenance stage path')
        seen.add(item['path'])
        if not item['path'].startswith('provenance/'+value['kind']+'/') or not item['path'].endswith('.jsonl'):
            raise ValueError('Wrong provenance stage prefix')
        if file_pin(path)!={k:item[k] for k in ('sha256','size')}:raise ValueError('Staged provenance changed')
        if value['kind']=='unreadable' and item['path']!=('provenance/unreadable/'+
                timestamp_key(value.get('decided_at'))+'-'+item['sha256']+'.jsonl'):
            raise ValueError('Unreadable stage is not content-qualified')
        with path.open() as source:
            for line in source:
                validate_provenance(value['kind'],json.loads(line));count+=1
    if count!=value['records']:raise ValueError('Stage record count differs')
    for item in value.get('artifacts',[]):
        relative=Path(item['path']);path=(root/relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
            raise ValueError('Unsafe staged artifact path')
        if file_pin(path)!={k:item[k] for k in ('sha256','size')}:
            raise ValueError('Staged import evidence changed')
    return root,value


def apply_staged(root,store):
    root,value=load_stage(root)
    for item in value['files']:
        if value['kind']=='unreadable':
            import_unreadable(store,root/item['path'],decided_at=value['decided_at'],
                expected={name:item[name] for name in ('sha256','size')})
        else:
            store.put(item['path'],root/item['path'],'application/x-ndjson')
    return dict(objects=len(value['files']),records=value['records'])


# JSONL staging serializes source records only. Every join/selection/export below
# is a declarative engine job; Python never matches rows across inputs.
def field(name,kind):
    return dict(name=name,data_type=kind,nullable=True,dict_id=0,dict_is_ordered=False,metadata={})


def struct(**fields):return {'Struct':[field(k,v) for k,v in fields.items()]}
def list_of(kind):return {'List':field('item',kind)}


def json_input(directory,table_name,records,**fields):
    import gzip
    path=Path(directory)/(table_name+'.jsonl.gz')
    with gzip.open(path,'wt',encoding='utf-8') as out:
        for row in records:out.write(json.dumps(row,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
    return dict(name=table_name,kind='json_lines',files=[dict(key=table_name,path=str(path))],
                schema=dict(fields=[field(k,v) for k,v in fields.items()],metadata={}))


def parquet_output(root,name,sql,order):
    return dict(name=name,path=str(Path(root)/(name+'.parquet')),sql=sql,
        settings=dict(profile='whole',row_group_rows=65536,order_by=[dict(field=k) for k in order],
            columns=[],dictionary_columns=[],delta_columns=[],created_by='docspec raw provenance v1',footer_limit=512<<10))


def run_job(root,engine,*,inputs,steps,outputs,queries=()):
    root=Path(root)
    path=root/'job.json'
    path.write_text(json.dumps(dict(scratch=str(root/'native'),inputs=inputs,steps=steps,
                                   outputs=outputs,queries=list(queries)),separators=(',',':')))
    result=engine.run_job(path)
    (root/'result.json').write_text(json.dumps(result,separators=(',',':')))
    return {query['name']:query['data'] for query in result.get('queries',[])}


def parquet_records(path):
    import pyarrow.parquet as pq
    with pq.ParquetFile(path) as source:
        for batch in source.iter_batches(batch_size=1024):
            yield from batch.to_pylist()
