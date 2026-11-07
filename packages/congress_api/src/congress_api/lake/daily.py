"""Refresh the three phase-one lake tables before building a daily release."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from shutil import copyfile
import subprocess
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_api.lake import appearance_records,capture_staging,captures,committee_records,filenames,meeting_records,playlist_records,readings,tables,video_records
from congress_api.lake.producer_records import DAILY_JOB
from congress_api.lake.receipt_inventory import (LocalReceiptStore,R2ReceiptStore,copy_receipts,
    discover_receipts,select_receipts)
from congress_api.retention.writer_identity import writer_identity
from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter,validate_key
from congress_shared.storage import single_put_md5
from congress_api.retention.provenance import field,file_pin,instant,json_input,local_unreadable_inventory,parquet_output,run_job
from congress_api.retention.provenance_inventory import UnreadableInventory,unreadable_inventory
from congress_shared.custody import custody_identity,VerifiedFile


ROOT=Path(__file__).resolve().parents[5]
TABLE_NAMES=('captures','readings','filename_readings')
OPTIONAL_TABLE_NAMES=('meeting_records','appearance_records')
ALL_TABLE_NAMES=TABLE_NAMES+OPTIONAL_TABLE_NAMES
DAILY_CAPTURE_RECORDS={'committee_records':committee_records,'playlist_records':playlist_records,'video_records':video_records}
PROVENANCE_KINDS=('recoveries','reviews','unreadable')
QUALIFIED_FIELDS={'key','etag','path','sha256','size'}
LISTING_SCHEMA=pa.schema([('key',pa.string()),('size',pa.int64()),('etag',pa.string())])
HEAD_WORKERS=16
HEAD_ATTEMPTS=5
HEAD_RETRY_STATUS={429,500,502,503,504}


def _qualified(row,kind,*,check_file=True):
    if (not isinstance(row,dict) or set(row)!=QUALIFIED_FIELDS
            or not isinstance(row['key'],str) or not row['key'].startswith('provenance/'+kind+'/')
            or not isinstance(row['path'],str) or not Path(row['path']).is_absolute()
            or '..' in Path(row['path']).parts
            or not isinstance(row['sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None
            or type(row['size']) is not int or row['size']<0
            or (row['etag'] is not None and (not isinstance(row['etag'],str) or not row['etag']))):
        raise ValueError('Invalid qualified daily provenance')
    validate_key(row['key'])
    if not check_file:return dict(row),None
    observed,before=_qualify_path(row['path'])
    if observed!={k:row[k] for k in ('sha256','size')}:
        raise ValueError('Qualified daily provenance changed')
    return dict(row),before


def _qualify_path(path):
    before=custody_identity(path)
    observed=file_pin(path)
    if custody_identity(path)!=before:
        raise ValueError('Qualified daily provenance changed')
    return observed,before


def _validate(spec,engine,raw_store):
    required={'work','decided_at','catalog_root','tables','receipt_inventory','max_work_items','provenance'}
    # Without a pinned body inventory, bodies are read from the raw store itself (_body_source).
    optional={'validated_counter','source_qualifications','vocabularies','body_inventory','local_root','receipt_families','derived_parsers','derived_scopes'}
    if not isinstance(spec,dict) or not required<=spec.keys() or spec.keys()-(required|optional):
        raise ValueError('Daily producer requires explicit receipt, body, table and provenance inputs')
    readings._positive(spec['max_work_items'],'max_work_items')
    derived_parsers(spec)
    derived_scopes(spec)
    instant(spec['decided_at'])
    if any(not isinstance(spec[k],(str,Path)) or not str(spec[k])
           for k in ('work','body_inventory','local_root') if k=='work' or spec.get(k) is not None):
        raise ValueError('Daily producer requires explicit work and body-cache paths')
    if (spec.get('body_inventory') is None)!=(spec.get('local_root') is None):
        raise ValueError('A pinned body inventory and its local root go together')
    if (spec.get('validated_counter') is not None and
            (not isinstance(spec['validated_counter'],(str,Path)) or not str(spec['validated_counter']))):
        raise ValueError('Daily validated counter must name an explicit path')
    if spec.get('source_qualifications') is not None and (not isinstance(spec['source_qualifications'],dict)
            or any(not isinstance(k,(str,Path)) or not isinstance(v,(str,Path))
                   for k,v in spec['source_qualifications'].items())):
        raise ValueError('Daily source qualifications must bind source and authority paths')
    if spec.get('vocabularies') is not None:
        if not isinstance(spec['vocabularies'],dict):raise ValueError('Daily vocabularies must be an explicit object')
        json.dumps(spec['vocabularies'],allow_nan=False)
    if (not isinstance(spec['tables'],dict) or set(spec['tables'])-set(DAILY_CAPTURE_RECORDS) not in (set(TABLE_NAMES),set(ALL_TABLE_NAMES))
            or any(not isinstance(t,dict) or set(t)!={'namespace','name'}
                or not isinstance(t['namespace'],list) or not t['namespace']
                or any(not isinstance(p,str) or not p for p in t['namespace'])
                or not isinstance(t['name'],str) or not t['name'] for t in spec['tables'].values())
            or len({json.dumps(t,sort_keys=True) for t in spec['tables'].values()})!=len(spec['tables'])):
        raise ValueError('Daily tables must name distinct core or optional record targets')
    if not isinstance(spec['receipt_inventory'],list) or any(not isinstance(r,dict) for r in spec['receipt_inventory']):
        raise ValueError('Daily receipt inventory must contain original receipt metadata')
    families=spec.get('receipt_families')
    if families is not None:
        if (not isinstance(families,list) or not families or len(set(families))!=len(families)
                or any(not isinstance(f,str) or not f or f.startswith('/') or '..' in f.split('/') for f in families)):
            raise ValueError('Daily receipt families must be distinct relative family names')
        if spec['receipt_inventory'] or spec.get('validated_counter') is not None or spec.get('source_qualifications') is not None:
            raise ValueError('Daily receipt families discover receipts; they take no pinned inventory, counter or qualifications')
    if not isinstance(raw_store,BodyStore) or not isinstance(raw_store.adapter,(LocalAdapter,R2Adapter)):
        raise ValueError('Daily producer requires an explicit durable raw store')
    tables.validate_catalog_authority(engine,spec['catalog_root'])
    if (not isinstance(spec['provenance'],dict) or set(spec['provenance'])!=set(PROVENANCE_KINDS)
            or any(not isinstance(v,list) for v in spec['provenance'].values())):
        raise ValueError('Daily provenance must explicitly name recoveries, reviews and unreadable')
    qualified={};identities={}
    for kind in PROVENANCE_KINDS:
        qualified[kind]=[];keys=set()
        for row in spec['provenance'][kind]:
            row,_=_qualified(row,kind,check_file=False)
            cached=raw_store._provenance_cache.get(row['key'])
            if cached is not None:
                previous,identity,_=cached
                if any(previous[k]!=row[k] for k in ('key','path','sha256','size')):
                    raise ValueError('Cached daily provenance changed')
                if isinstance(raw_store.adapter,R2Adapter):
                    if (single_put_md5(previous['etag'])!=single_put_md5(row['etag'])
                            or identity.get('md5')!=single_put_md5(row['etag'])):
                        raise ValueError('Cached daily provenance MD5 changed')
                elif previous['etag']!=row['etag']:
                    raise ValueError('Cached daily provenance ETag changed')
                if identity.sha256!=row['sha256'] or identity.size_bytes!=row['size']:
                    raise ValueError('Cached daily provenance byte identity changed')
                identity._require_custody(row['path'])
            else:
                row,identity=_qualified(row,kind,check_file=kind!='unreadable')
            if row['key'] in keys:raise ValueError('Duplicate daily provenance key')
            keys.add(row['key']);qualified[kind].append(row)
            if identity is not None:identities[row['path']]=identity
    work=Path(spec['work']).resolve()
    if work.exists():raise FileExistsError('Daily producer requires a fresh work directory')
    return work,qualified,identities


def _input_files(rows):
    return [dict(key=row['key'],path=row['path']) for row in rows]


def _complete_receipt_keys(pin,*,engine,work):
    work=Path(work);work.mkdir(parents=True,exist_ok=False)
    rows=run_job(work,engine,inputs=[tables.table_input('current_captures',pin)],steps=[],outputs=[],
        queries=[dict(name='receipt_keys',sql='SELECT DISTINCT receipt_key FROM current_captures ORDER BY receipt_key')])
    return [row['receipt_key'] for row in rows['receipt_keys']]


def _source_qualifications(spec,selected):
    bindings=spec.get('source_qualifications')
    if bindings is None or spec.get('validated_counter') is not None:return bindings
    paths={str(Path(row['path']).resolve()) for row in selected}
    return {key:value for key,value in bindings.items() if str(Path(key).resolve()) in paths}


def _final_provenance(initial,raw_store,imported,identities,*,acknowledgements=None,unreadable_snapshot=None):
    result={kind:list(rows) for kind,rows in initial.items()}
    known={row['key']:row for row in result['unreadable']}
    required={};acknowledgements=acknowledgements or {}
    def require_ack(row,custody):
        if (not isinstance(custody,VerifiedFile) or custody.sha256!=row['sha256']
                or custody.size_bytes!=row['size']):
            raise ValueError('Acknowledged unreadable provenance requires import-bound custody')
        try:custody._require_custody(row['path'])
        except (OSError,ValueError):
            raise ValueError('Acknowledged unreadable provenance changed or disappeared') from None
    for row in imported:
        if row is None:continue
        key=row['key']
        if key in required:raise ValueError('Duplicate acknowledged unreadable provenance')
        if key in known and (any(known[key][k]!=row[k] for k in ('sha256','size'))
                or (known[key]['etag'] is not None and row['etag'] is not None
                    and known[key]['etag']!=row['etag'])):
            raise ValueError('Conflicting unreadable provenance inputs')
        require_ack(row,acknowledgements.get(key))
        required[key]=row
        # An unchanged initial qualification keeps its exact path and ETag.
        # Every acknowledged source is still independently mandatory below.
        if key not in known:known[key]=dict(row)
    discovered=(unreadable_snapshot.rows() if unreadable_snapshot is not None
                else local_unreadable_inventory(raw_store))
    for ref in discovered:
        if ref['key'] in required:continue
        if ref['key'] in known and known[ref['key']]['path']==ref['path']:continue
        # Older imports not in the supplied snapshot are qualified once as
        # small provenance records; body bytes never enter this inventory.
        validate_key(ref['key'])
        if unreadable_snapshot is not None:
            row=dict(ref)
        else:
            observed,identity=_qualify_path(ref['path'])
            row=dict(ref,etag=None,**observed);identities[row['path']]=identity
        if ref['key'] in known and any(known[ref['key']][k]!=row[k] for k in ('sha256','size')):
            raise ValueError('Conflicting unreadable provenance inputs')
        if ref['key'] not in known:known[ref['key']]=row
    result['unreadable']=sorted(known.values(),key=lambda r:r['key'])
    for path,identity in identities.items():
        if isinstance(identity,VerifiedFile):identity._require_custody(path)
        elif custody_identity(path)!=identity:raise ValueError('Daily provenance changed while producing')
    for key,row in required.items():require_ack(row,acknowledgements[key])
    if unreadable_snapshot is not None:unreadable_snapshot.rows()
    return result


def derived_parsers(spec):
    """Derived readings passes a run asks for; default none, so a first run never demands a backfill."""
    value=spec.get('derived_parsers',[])
    if (not isinstance(value,list) or any(not isinstance(p,str) or p not in readings.READ_AS for p in value)
            or len(set(value))!=len(value)):
        raise ValueError('derived_parsers must list distinct derived readings parsers: '+', '.join(readings.READ_AS))
    return value


def derived_scopes(spec):
    """An explicit qualified baseline and byte budget for each requested derived pass.

    The baseline captures head must already have every applicable derived pair settled.
    Current native readings and unreadable decisions, rather than a local work journal,
    retain unfinished pairs admitted after it. A version move needs a newly qualified
    baseline; it must not silently turn a daily pass into a historical replay.
    """
    from congress_api.lake.compatible_versions import current_pins
    requested=derived_parsers(spec)
    scopes=spec.get('derived_scopes',{})
    if not isinstance(scopes,dict) or set(scopes)!=set(requested):
        raise ValueError('Derived daily parsers require matching explicit derived_scopes')
    for name,scope in scopes.items():
        if (not isinstance(scope,dict) or set(scope)!={'captures','versions','max_stored_bytes','batch_size'}
                or not isinstance(scope['captures'],dict)):
            raise ValueError('Derived scopes require a qualified captures baseline, versions and budgets')
        tables.table_input('derived_baseline',scope['captures'])
        if scope['versions']!=current_pins():
            raise ValueError('Derived scope reading versions changed; qualify a new baseline')
        readings._positive(scope['max_stored_bytes'],'max_stored_bytes')
        readings._positive(scope['batch_size'],'batch_size')
    return scopes


def _check_entity_versions(table_name,actual,mod):
    expected=mod.current_versions()
    if not isinstance(actual,dict) or actual!=expected:
        raise ValueError(f'Daily producer definitions for {table_name} must match current source-scoped versions')


def _stale_mapping_receipts(captures_pin,current,*,engine,work):
    """Receipts whose rows another capture mapping built (or none recorded), by mapping.

    One narrow-column scan grouped by mapping_version, a handful of groups. A head without
    the column fails here, before any effect.
    """
    rows=run_job(work,engine,inputs=[tables.table_input('captures',captures_pin)],steps=[],outputs=[],queries=[dict(name='stale',
        sql="SELECT mapping_version,count(DISTINCT receipt_key) AS receipts,count(*) AS captures FROM captures "
            "WHERE mapping_version IS DISTINCT FROM '"+current.replace("'","''")+"' GROUP BY mapping_version")])['stale']
    return sorted(rows,key=lambda row:str(row['mapping_version']))


def _discovered_receipts(families,raw_store,captures_head,*,engine,work):
    """Receipts in the raw store that captures lacks, copied and qualified under work.

    Lists each family's dated prefixes from its newest captured date on (inclusive), so a
    run costs one listing per new day, not the whole history; the native anti-join drops
    keys already in captures.
    """
    adapter=raw_store.adapter
    store=(R2ReceiptStore(adapter.client,adapter.bucket) if isinstance(adapter,R2Adapter)
           else LocalReceiptStore(adapter.root))
    rows=discover_receipts(store,families,existing=captures_head,engine=engine,work=work/'receipt-discovery')
    return copy_receipts(store,rows,work/'receipts')


RECEIPT_DAY=re.compile(r'/(\d{4}-\d{2}-\d{2})/')


def _receipt_order(row):
    day=RECEIPT_DAY.search(row['key'])
    return (day.group(1) if day else '',row['key'])


def _within_budget(stage,selected,captures_head,max_work_items,*,engine,work):
    """The oldest selected receipts whose bodies new to captures fit one night's readings budget.

    Returns (kept, fresh bodies by kept receipt count); kept is a prefix of the selection in
    (day, key) order, so a deferred receipt is never older than a kept one of the same family
    and the next run's inclusive watermark still lists it. A body counts once, at the first
    receipt naming it. Bodies already in captures are read or already pending; the caller
    passes the night's budget less the pending ones (_pending_backlog).
    """
    rows=run_job(work,engine,inputs=[tables.table_input('staged',stage),
        tables.table_input('captures',captures_head)],steps=[],outputs=[],queries=[dict(name='fresh',
        sql="SELECT DISTINCT s.receipt_key,lower(encode(s.sha256,'hex')) AS sha FROM staged s "
            "WHERE s.sha256 IS NOT NULL AND NOT EXISTS(SELECT 1 FROM captures c WHERE c.sha256=s.sha256)")])['fresh']
    bodies={}
    for row in rows:bodies.setdefault(row['receipt_key'],set()).add(row['sha'])
    kept=[];seen=set()
    for row in sorted(selected,key=_receipt_order):
        new=bodies.get(row['key'],set())-seen
        if len(seen)+len(new)>max_work_items:break
        kept.append(row);seen|=new
    return kept,len(seen)


def _listed_reads(spec,raw_store):
    return spec.get('body_inventory') is None and isinstance(raw_store.adapter,R2Adapter)


def _pending_backlog(spec,engine,raw_store,heads,unreadable_snapshot,work,*,parser=None):
    """The readings work the current heads already hold, planned without opening a body.

    Candidacy never reads the body source, so an R2 run plans over the recorded copies
    before any listing exists. A head alone past the budget raises BackfillRequired.
    """
    source=(_body_source(spec,raw_store,work) if not _listed_reads(spec,raw_store)
            else dict(body_inventory=None,captured_copies=True,local_root=Path(work)/'unopened'))
    return readings.run(engine=engine,work=work,mode='daily',execute=False,max_work_items=spec['max_work_items'],
        existing=heads['readings'],captures=heads['captures'],unreadable_files=unreadable_snapshot.files(),
        decided_at=spec['decided_at'],parser=parser,**source)


def _head(client,bucket,key):
    """One exact-key HEAD: a listing row with the ETag as R2 returns it (quoted), or None.

    A HEAD is safe to repeat, so throttling, server errors and dropped connections back off
    and retry a bounded number of times; a server wait past a minute is not waited out.
    """
    from botocore.exceptions import ClientError,ConnectionClosedError,EndpointConnectionError,ReadTimeoutError,SSLError
    from congress_api.retention.r2 import _throttle_delay
    for attempt in range(1,HEAD_ATTEMPTS+1):
        try:
            value=client.head_object(Bucket=bucket,Key=key)
            return dict(key=key,size=value['ContentLength'],etag=value['ETag'])
        except ClientError as error:
            if error.response.get('Error',{}).get('Code') in {'404','NoSuchKey','NotFound'}:return None
            metadata=error.response.get('ResponseMetadata',{})
            if metadata.get('HTTPStatusCode') not in HEAD_RETRY_STATUS or attempt==HEAD_ATTEMPTS:raise
            delay=_throttle_delay({k.lower():v for k,v in metadata.get('HTTPHeaders',{}).items()},attempt,time.time())
            if delay is False:raise
        except (ConnectionClosedError,EndpointConnectionError,ReadTimeoutError,SSLError,ConnectionResetError):
            if attempt==HEAD_ATTEMPTS:raise
            delay=_throttle_delay({},attempt,time.time())
        time.sleep(delay)


def _listed_custody(spec,engine,raw_store,heads,backlog,stage,unreadable_snapshot,work,*,parser=None):
    """Raw custody, before captures move, for every body the readings run after the append reads.

    The bodies are those already pending plus the staged bodies new to captures. Every copy
    their captures record is HEADed at its exact key into a listing; an absent object has no
    row. Readings then plans over every capture row, head and staged, of the pending and
    staged bodies against that listing. Per body that is the plan the run after the append
    makes, so its missing pins or conflicts are the refusal that run would raise. Cost is
    one HEAD per recorded candidate copy, not a bucket LIST.
    """
    work=Path(work);work.mkdir(parents=True)
    inputs=[tables.table_input('captures',heads['captures']),tables.table_input('backlog',backlog['work_list'])]
    listed='SELECT body_sha AS sha256 FROM backlog'
    scoped='SELECT sha256 FROM listed_shas'
    rows='SELECT c.* FROM captures c JOIN scoped_shas k ON c.sha256=k.sha256'
    if stage is not None:
        inputs.append(tables.table_input('staged',stage))
        names=pq.read_schema(stage).names
        listed+=(' UNION SELECT s.sha256 FROM staged s WHERE s.sha256 IS NOT NULL'
                 ' AND NOT EXISTS(SELECT 1 FROM captures c WHERE c.sha256=s.sha256)')
        scoped+=' UNION SELECT sha256 FROM staged WHERE sha256 IS NOT NULL'
        rows=('SELECT '+','.join('c."'+n+'"' for n in names)+' FROM captures c JOIN scoped_shas k ON c.sha256=k.sha256'
              ' UNION ALL SELECT '+','.join('"'+n+'"' for n in names)+' FROM staged')
    from congress_api.retention.provenance import parquet_output,run_job
    keys=[row['key'] for row in run_job(work/'scope',engine,inputs=inputs,steps=[
        dict(name='listed_shas',sql=listed,materialize=True),dict(name='scoped_shas',sql=scoped,materialize=True),
        dict(name='scoped_captures',sql=rows,materialize=True)],
        outputs=[parquet_output(work,'scoped-captures','SELECT * FROM scoped_captures',['receipt_key','receipt_line','capture_index'])],
        queries=[dict(name='keys',sql="""SELECT DISTINCT concat('bodies/sha256/',substr(encode(c.sha256,'hex'),1,2),'/',
            encode(c.sha256,'hex'),coalesce(c.stored_suffix,'.gz')) AS key FROM scoped_captures c
            JOIN listed_shas k ON c.sha256=k.sha256 ORDER BY key""")])['keys']]
    for key in keys:validate_key(key)
    client,bucket=raw_store.adapter.client,raw_store.adapter.bucket
    with ThreadPoolExecutor(max_workers=max(1,min(HEAD_WORKERS,len(keys)))) as pool:
        found=list(pool.map(lambda key:_head(client,bucket,key),keys))
    listing=work/'body-listing.parquet'
    pq.write_table(pa.Table.from_pylist([row for row in found if row is not None],schema=LISTING_SCHEMA),listing)
    planned=readings.run(engine=engine,work=work/'readings',mode='daily',execute=False,
        max_work_items=spec['max_work_items'],existing=heads['readings'],captures=work/'scoped-captures.parquet',
        unreadable_files=unreadable_snapshot.files(),body_inventory=None,body_listing=listing,raw_ranges=True,
        local_root=work/'unopened',decided_at=spec['decided_at'],parser=parser)
    return dict(listing=listing,planned=planned,heads=len(keys),
                absent=[key for key,row in zip(keys,found) if row is None])


def _body_source(spec,raw_store,work,listing=None):
    """How readings reaches bodies: a pinned inventory under local_root, else the raw store.

    The raw store binding is the one producers already write to: a local root is read in place
    from each capture's recorded copy; R2 is read by ranges through the maintained R2Store,
    against the exact-key listing of the candidates' recorded copies (_listed_custody). Each
    read is conditional on the capture's recorded MD5 and size where it has them, else on the
    listed ETag and size. Never an empty inventory, which turns every body into a pending read.
    """
    if spec.get('body_inventory') is not None:
        return dict(body_inventory=spec['body_inventory'],local_root=spec['local_root'])
    if isinstance(raw_store.adapter,LocalAdapter):
        return dict(body_inventory=None,captured_copies=True,local_root=raw_store.adapter.root)
    from congress_api.retention.r2 import R2Store
    # The ranged cache must sit below the readings run's own work directory.
    cache=Path(work)/'raw-pages'
    return dict(body_inventory=None,body_listing=listing,local_root=cache,
                body_store=R2Store(raw_store.adapter.client,raw_store.adapter.bucket,cache_dir=cache))


def _producer_bases(records,heads):
    """Gate 5 preflight: the commit that will append, and each head's own record.

    Refuses before any append: a head without a record would leave every later
    snapshot of that table unprovable.
    """
    try:writer=writer_identity(ROOT,DAILY_JOB)
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        return None,dict(unavailable='the checkout was not clean, so no commit can be named: '+str(error))
    bases={};missing=[]
    for name,pin in heads.items():
        if pin['snapshot'] is None:bases[name]=None;continue
        found=records.find(name,pin)
        if found is None:missing.append(name)
        else:bases[name]=found[1]
    if missing:return None,dict(missing=sorted(missing))
    return dict(writer=writer,bases=bases),None


def _record_moved(records,chain,initial,final,*,decided_at,transition_inputs=None,
                  transition_field="house_xml_transition"):
    """One record per table whose head moved during this run, written before returning."""
    if writer_identity(ROOT,DAILY_JOB)['commit']!=chain['writer']['commit']:
        raise ValueError('Application commit changed during daily production')
    written={}
    for name,pin in sorted(final.items()):
        if pin==initial[name]:continue
        record=dict(version=1,input=name,selector=dict(kind='native_table',**pin),job=DAILY_JOB,
            commit=chain['writer']['commit'],lockfile_digest=chain['writer']['lockfile_digest'],decided_at=decided_at,
            base=dict(selector=dict(kind='native_table',**initial[name]),record=chain['bases'][name]))
        if transition_inputs is not None:
            record[transition_field]=transition_inputs[name]
        written[name]=records.write(record)
    return written


def _copy_html_input(pin, target):
    if (not isinstance(pin, dict) or set(pin) != {'path', 'sha256', 'size'}
            or not isinstance(pin['path'], (str, Path))
            or not isinstance(pin['sha256'], str) or re.fullmatch('[0-9a-f]{64}', pin['sha256']) is None
            or type(pin['size']) is not int or pin['size'] <= 0):
        raise ValueError('HTML metadata inputs require path, SHA-256 and size pins')
    source = Path(pin['path'])
    if custody_identity(source)[2] != pin['size']:
        raise ValueError('Pinned HTML metadata input size changed')
    copyfile(source, target)
    if file_pin(target) != {k: pin[k] for k in ('sha256', 'size')}:
        raise ValueError('Pinned HTML metadata input bytes changed')
    return target


def _scope_html_inputs(scope, heads, *, engine, work, allow_empty=False):
    keys = pq.read_table(scope, columns=['body_sha']).column('body_sha')
    if (not pa.types.is_string(keys.type) or (not len(keys) and not allow_empty) or keys.null_count
            or (len(keys) and not pc.all(pc.match_substring_regex(keys, '^[0-9a-f]{64}$')).as_py())
            or pc.count_distinct(keys).as_py() != len(keys)):
        raise ValueError('HTML metadata scope requires distinct lowercase hexadecimal body_sha values')
    inputs = [tables.table_input('scope_keys', scope),
              tables.table_input('captures', heads['captures']),
              tables.table_input('readings', heads['readings'])]
    steps = [
        dict(name='candidate_shas', materialize=True,
             sql="SELECT arrow_cast(decode(body_sha,'hex'),'FixedSizeBinary(32)') AS body_sha FROM scope_keys"),
        dict(name='scoped_captures', materialize=True, sql='''
            SELECT c.sha256,c.sniffed_format,c.sniff_version,c.intact,c.media_type,c.bytes,
                c.stored_suffix,c.stored_bytes,c.stored_md5,c.receipt_key,c.receipt_line,c.capture_index
            FROM candidate_shas k JOIN captures c ON k.body_sha=c.sha256'''),
    ]
    checks = run_job(work, engine, inputs=inputs, steps=steps, outputs=[
        parquet_output(work, 'captures', 'SELECT * FROM scoped_captures',
                       ['receipt_key', 'receipt_line', 'capture_index']),
        parquet_output(work, 'readings', """SELECT r.* FROM candidate_shas k
            JOIN readings r ON k.body_sha=r.body_sha WHERE r.parser IN ('sniff','html_metadata')""", readings.PK),
    ], queries=[dict(name='coverage', sql='SELECT count(DISTINCT sha256) AS bodies FROM scoped_captures')])
    if checks['coverage'][0]['bodies'] != len(keys):
        raise ValueError('HTML metadata scope contains bodies missing from the pinned captures')
    return len(keys)


def _daily_html_metadata(spec,heads,*,engine,raw_store,unreadable_snapshot,work):
    """Read only missing pairs for bodies admitted after a qualified immutable baseline.

    A fresh attempt uses the same baseline, so committed receipts cannot hide an
    interrupted derived pass. The maintained scoped producer selection settles accepted
    older readings and active unreadable decisions before either budget is evaluated.
    """
    scope=derived_scopes(spec)['html_metadata']
    baseline=scope['captures']
    if baseline['table_uuid']!=heads['captures']['table_uuid']:
        raise ValueError('Derived baseline must name the current captures table')
    work=Path(work)
    scope_work=work/'delta'
    scope_work.mkdir(parents=True,exist_ok=False)
    inputs=[tables.table_input('captures',heads['captures']),tables.table_input('baseline',baseline)]
    schema=dict(id='Utf8',body_sha256='Utf8',parser='Utf8',supersedes='Utf8')
    files=unreadable_snapshot.files()
    inputs.append(dict(name='unreadable',kind='json_lines',files=files,
        schema=dict(fields=[field(k,v) for k,v in schema.items()],metadata={})) if files
        else json_input(scope_work,'unreadable',[],**schema))
    observed=run_job(scope_work,engine,inputs=inputs,steps=[
        dict(name='reconsidered_shas',materialize=True,sql='''
            SELECT decode(u.body_sha256,'hex') AS body_sha FROM unreadable u
            WHERE u.parser='html_metadata' AND u.body_sha256 IS NOT NULL
                AND EXISTS (SELECT 1 FROM unreadable newer WHERE newer.supersedes=u.id)'''),
        # Baseline captures repeat a body for each capture occurrence. Membership
        # needs one key, otherwise anti/semi joins repeat duplicate match work.
        dict(name='baseline_keys',materialize=True,sql='''
            SELECT DISTINCT sha256 FROM baseline WHERE sha256 IS NOT NULL'''),
        dict(name='candidate_shas',materialize=True,
        sql='''SELECT DISTINCT c.sha256 AS body_sha FROM captures c
            WHERE c.sha256 IS NOT NULL AND NOT EXISTS
                (SELECT 1 FROM baseline_keys b WHERE b.sha256=c.sha256)
            UNION SELECT c.sha256 AS body_sha FROM reconsidered_shas r JOIN captures c
                ON r.body_sha=c.sha256''')],outputs=[
        parquet_output(scope_work,'body-scope',
            "SELECT lower(encode(body_sha,'hex')) AS body_sha FROM candidate_shas",['body_sha'])],queries=[
        dict(name='reconsidered_baseline',sql='''SELECT count(DISTINCT r.body_sha) AS n
            FROM reconsidered_shas r JOIN captures c ON r.body_sha=c.sha256
            WHERE EXISTS (SELECT 1 FROM baseline_keys b WHERE b.sha256=r.body_sha)''')])
    scoped=work/'scope'
    count=_scope_html_inputs(scope_work/'body-scope.parquet',heads,engine=engine,work=scoped,allow_empty=True)
    source=_body_source(spec,raw_store,work/'readings')
    if _listed_reads(spec,raw_store):source['captured_copies']=True
    reconsidered=observed['reconsidered_baseline'][0]['n']
    details=dict(scope=dict(baseline=baseline,versions=scope['versions'],
        bodies_since_baseline=count-reconsidered,reconsidered_baseline_bodies=reconsidered))
    try:
        planned=readings.run(engine=engine,work=work/'admission',mode='daily',execute=False,
            max_work_items=spec['max_work_items'],existing=scoped/'readings.parquet',
            captures=scoped/'captures.parquet',unreadable_files=unreadable_snapshot.files(),
            decided_at=spec['decided_at'],parser='html_metadata',**source)
    except readings.BackfillRequired as error:
        return dict(error.as_dict(),status='derived_budget_required',batches=[],**details)
    listing=None
    if _listed_reads(spec,raw_store):
        custody=_listed_custody(spec,engine,raw_store,
            dict(captures=scoped/'captures.parquet',readings=scoped/'readings.parquet'),
            planned,None,unreadable_snapshot,work/'custody',parser='html_metadata')
        planned=custody['planned'];listing=custody['listing']
        if planned['raw_custody']['missing_pins'] or planned['raw_custody']['conflicts']:
            raise readings.RawCustodyRequired(planned)
    stored_bytes=0;missing_sizes=0
    for batch in pq.ParquetFile(planned['work_list']).iter_batches(columns=['stored_bytes']):
        for size in batch.column('stored_bytes').to_pylist():
            if size is None:missing_sizes+=1
            else:stored_bytes+=size
    budget=dict(work_items=planned['work_items'],max_work_items=spec['max_work_items'],
        stored_bytes=stored_bytes,missing_sizes=missing_sizes,max_stored_bytes=scope['max_stored_bytes'])
    details['budget']=budget
    if missing_sizes or stored_bytes>scope['max_stored_bytes']:
        # The generic nightly backfill fallback cannot repair this scoped byte budget.
        return dict(status='derived_budget_required',parser='html_metadata',
            parser_version=readings.current_version('html_metadata'),batches=[],**details)
    current=tables.resolve_tables(engine=engine,catalog_root=spec['catalog_root'],work=work/'admitted-heads',
        tables={name:spec['tables'][name] for name in ('captures','readings')})
    if current!={name:heads[name] for name in current}:
        raise ValueError('Derived captures or readings head changed during admission')
    source=_body_source(spec,raw_store,work/'readings',listing)
    if _listed_reads(spec,raw_store):source['captured_copies']=listing is None
    result=readings.run(engine=engine,work=work/'readings',mode='backfill',execute=True,
        batch_size=scope['batch_size'],table=spec['tables']['readings'],catalog_root=spec['catalog_root'],
        read_current=lambda **_:scoped/'readings.parquet',captures=scoped/'captures.parquet',
        parser='html_metadata',decided_at=spec['decided_at'],unreadable_store=raw_store,
        unreadable_snapshot=unreadable_snapshot,**source)
    return dict(result,**details)


def produce_html_metadata(*, engine, raw_store, producer_records, catalog_root, work, decided_at,
                          tables_spec, expected_heads, scope, unreadable_snapshot, batch_size,
                          parser_workers=1, max_get_workers=64, body_listing=None):
    """Append missing HTML metadata for a pinned body scope in bounded batches.

    The caller holds the archive writer lock across this call and supplies the complete
    qualified unreadable inventory. The scope Parquet names unique lowercase body hashes
    in body_sha. It limits the work considered by the maintained readings selection.
    An optional pinned R2 listing (key, size, etag) must cover the recorded copies
    of bodies to be read.
    Otherwise reads use the capture's own stored size and MD5 for conditional GETs.
    The result describes this scope only. The maintained cache limit applies to each
    batch. After a stop that unwinds this call, resolve fresh heads and replan.
    """
    names = {'captures', 'readings'}
    if (not isinstance(tables_spec, dict) or tables_spec.keys() != names
            or not isinstance(expected_heads, dict) or expected_heads.keys() != names
            or any(not isinstance(pin, dict) for pin in expected_heads.values())):
        raise ValueError('HTML metadata requires explicit captures and readings tables and expected heads')
    for name in names:
        tables.table_input(name, expected_heads[name])
    if (producer_records is None or not isinstance(raw_store, BodyStore)
            or not isinstance(raw_store.adapter, (LocalAdapter, R2Adapter))
            or not isinstance(unreadable_snapshot, UnreadableInventory)
            or unreadable_snapshot.store is not raw_store):
        raise ValueError('HTML metadata requires a producer ledger and qualified unreadable inventory')
    if body_listing is not None and not isinstance(raw_store.adapter, R2Adapter):
        raise ValueError('HTML metadata body listings require an R2 raw store')
    readings._positive(batch_size, 'batch_size')
    instant(decided_at)
    authority = dict(engine=engine, catalog_root=catalog_root)
    tables.validate_catalog_authority(**authority)
    work = Path(work)
    if work.is_symlink():
        raise ValueError('HTML metadata requires a fresh work directory')
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    heads = tables.resolve_tables(**authority, work=work/'initial-heads', tables=tables_spec)
    if heads != expected_heads:
        raise ValueError('HTML metadata expected captures or readings head changed')
    base = {'readings': heads['readings']}
    chain, refusal = _producer_bases(producer_records, base)
    report = dict(scope=scope, source=heads, pins=None)
    if chain is None:
        return dict(report, status='producer_unrecorded', producers=refusal)

    scoped = work/'scope'
    scope_file = _copy_html_input(scope, work/'body-scope.parquet')
    report['scope_bodies'] = _scope_html_inputs(scope_file, heads, engine=engine, work=scoped)
    listing = _copy_html_input(body_listing, work/'body-listing.parquet') if body_listing is not None else None
    reading_work = work/'html_metadata'
    source = _body_source({}, raw_store, reading_work, listing)
    source['captured_copies'] = listing is None

    current = tables.resolve_tables(**authority, work=work/'scoped-heads', tables=tables_spec)
    if current != heads:
        raise ValueError('HTML metadata expected captures or readings head changed during scoping')

    try:
        result = readings.run(engine=engine, work=reading_work, mode='backfill', execute=True,
            table=tables_spec['readings'], catalog_root=catalog_root, parser='html_metadata',
            captures=scoped/'captures.parquet', read_current=lambda **_: scoped/'readings.parquet',
            batch_size=batch_size,
            decided_at=decided_at, unreadable_store=raw_store, unreadable_snapshot=unreadable_snapshot,
            parser_workers=parser_workers, max_get_workers=max_get_workers, **source)
        report.update(status=result['status'], readings=result)
    except readings.RawCustodyRequired as error:
        report.update(status='raw_custody_required', readings=error.as_dict())
    finally:
        final = tables.resolve_tables(**authority, work=work/'producer-heads', tables=tables_spec)
        report['producers'] = _record_moved(producer_records, chain, base,
            {'readings': final['readings']}, decided_at=decided_at)
    if final['captures'] != heads['captures']:
        raise ValueError('HTML metadata captures head changed during production')
    return dict(report, pins=final, unreadable=unreadable_snapshot.rows())


def produce_daily(spec,*,engine,raw_store,producer_records=None):
    """D1 then budgeted D2 then D3, returning fresh pins only after completion.

    Native jobs own table scans, joins, sorting and appends. Each producer builds
    one work list; parser workers persist for that list. Head lookups are batched
    at preflight/finalization, with required intermediate refreshes after writes.
    Local provenance discovery is once per invocation, O(U log U); daily R2
    decisions reuse the controller's complete qualified initial snapshot plus
    acknowledged imports, with no second LIST or GET. Native
    key anti-joins and sorted appends retain their existing O(N+M)/O(K log K) cost.

    The receipt budget is the readings budget less the bodies the current heads already
    leave unread. An R2 run settles raw custody for every body it will read before captures
    move (status raw_custody_required otherwise), so a refusal never leaves appended,
    unread captures behind.

    With `producer_records` (gate 5), every head must already have a record and every
    head this run moves gets one, whether the run completes, stops or fails.
    """
    work,provenance,identities=_validate(spec,engine,raw_store)
    work.mkdir(parents=True,exist_ok=False)
    unreadable_snapshot=(UnreadableInventory.from_qualified(raw_store,qualified=provenance['unreadable'])
        if isinstance(raw_store.adapter,R2Adapter) else unreadable_inventory(raw_store,
            work=work/'unreadable-inventory',qualified=provenance['unreadable']))
    provenance['unreadable']=unreadable_snapshot.rows()
    authority=dict(engine=engine,catalog_root=spec['catalog_root'])
    heads=tables.resolve_tables(**authority,work=work/'initial-heads',tables=spec['tables'])
    versions=dict(captures=captures.current_version())
    report=dict(status='running',pins=None,receipt_keys=None,new_receipt_keys=[],provenance=provenance,
                currentversions=versions,producerreports={})
    if producer_records is None:
        return _produce(spec,engine,raw_store,work,provenance,identities,unreadable_snapshot,authority,heads,versions,report)
    chain,refusal=_producer_bases(producer_records,heads)
    if chain is None:
        report.update(status='producer_unrecorded',producers=refusal)
        return report
    initial=dict(heads)
    try:
        _produce(spec,engine,raw_store,work,provenance,identities,unreadable_snapshot,authority,heads,versions,report)
    finally:
        final=tables.resolve_tables(**authority,work=work/'producer-heads',tables=spec['tables'])
        report['producers']=_record_moved(producer_records,chain,initial,final,decided_at=spec['decided_at'])
    return report


def _produce(spec,engine,raw_store,work,provenance,identities,unreadable_snapshot,authority,heads,versions,report):
    stale=_stale_mapping_receipts(heads['captures'],versions['captures'],engine=engine,work=work/'mapping-check')
    if stale:
        # The receipt anti-join would count these receipts as present forever, and re-staging
        # them would duplicate their keys: only the selective backfill rebuilds them.
        report.update(status='backfill_required')
        report['producerreports']['captures']=dict(status='backfill_required',stale_mappings=stale)
        return report
    try:
        backlog=_pending_backlog(spec,engine,raw_store,heads,unreadable_snapshot,work/'readings-backlog')
    except readings.BackfillRequired as error:
        # The heads alone hold more unread bodies than a night may read: admit no receipts.
        report.update(status='backfill_required');report['producerreports']['readings']=error.as_dict()
        return report
    pending=backlog['work_items'];budget=spec['max_work_items']-pending
    if spec.get('receipt_families'):
        selected=_discovered_receipts(spec['receipt_families'],raw_store,heads['captures'],engine=engine,work=work)
        report['discovered_receipts']=len(selected)
    else:
        selected=select_receipts(spec['receipt_inventory'],heads['captures'],engine=engine,work=work/'receipt-selection')
    stage=None
    if selected:
        stage=capture_staging.stage_captures(selected,engine=engine,work=work/'captures',
            validated_counter=spec.get('validated_counter'),
            source_qualifications=_source_qualifications(spec,selected))
        kept,fresh=_within_budget(stage/'captures.parquet',selected,heads['captures'],budget,
            engine=engine,work=work/'captures-budget')
        report['receipt_budget']=dict(selected=len(selected),kept=len(kept),fresh_bodies=fresh,
            pending_bodies=pending,max_work_items=spec['max_work_items'])
        if not kept and not pending:
            # The oldest receipt alone holds more new bodies than a night may read.
            report.update(status='backfill_required')
            report['producerreports']['captures']=dict(status='backfill_required',
                receipt=min(selected,key=_receipt_order)['key'])
            return report
        if not kept:stage=None
        elif len(kept)<len(selected):
            stage=capture_staging.stage_captures(kept,engine=engine,work=work/'captures-kept',
                validated_counter=spec.get('validated_counter'),
                source_qualifications=_source_qualifications(spec,kept))
    if stage is not None:
        manifest=json.loads((stage/'ingested-receipts.json').read_text())
        if manifest['mapping_digest']!=versions['captures']:
            raise ValueError('Captures producer changed during daily production')
        if not pq.ParquetFile(stage/'captures.parquet').metadata.num_rows:
            raise ValueError('Selected receipts produced no captures')
    report['producerreports']['captures']=dict(stage=None if stage is None else str(stage),append=None)
    listing=None
    if _listed_reads(spec,raw_store):
        try:
            custody=_listed_custody(spec,engine,raw_store,heads,backlog,None if stage is None else stage/'captures.parquet',
                unreadable_snapshot,work/'raw-custody')
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports']['readings']=error.as_dict()
            return report
        planned=custody['planned']
        report['raw_listing']=dict(heads=custody['heads'],absent=custody['absent'])
        if planned['raw_custody']['missing_pins'] or planned['raw_custody']['conflicts']:
            report.update(status='raw_custody_required')
            report['producerreports']['readings']=dict(planned['raw_custody'],status='missing_raw_custody',
                work_list=str(planned['work_list']))
            return report
        listing=custody['listing']
    if stage is not None:
        appended=tables.append_rows(stage/'captures.parquet',**authority,work=work/'captures-append',
            table=spec['tables']['captures'],keys=['receipt_key'],definition=manifest['mapping_digest'])
        report['new_receipt_keys']=manifest['receipt_keys']
        report['producerreports']['captures']=dict(stage=str(stage),append=appended)
        heads.update(tables.resolve_tables(**authority,work=work/'captures-head',
            tables={'captures':spec['tables']['captures']}))
    passes={}
    # Classify new bodies first; derived passes then select their explicit admission delta.
    for name in [None,*derived_parsers(spec)]:
        step=name or 'readings'
        try:
            if name is not None:
                derived_heads=dict(heads)
                derived_heads.update(tables.resolve_tables(**authority,work=work/(name+'-head'),
                    tables={'readings':spec['tables']['readings']}))
                passes[step]=_daily_html_metadata(spec,derived_heads,engine=engine,raw_store=raw_store,
                    unreadable_snapshot=unreadable_snapshot,work=work/(name+'-scoped'))
                if passes[step]['status']=='derived_budget_required':
                    report.update(status='derived_budget_required')
                    report['producerreports'][step]=passes[step]
                    return report
            else:
                passes[step]=readings.run(engine=engine,work=work/step,mode='daily',execute=True,
                    max_work_items=spec['max_work_items'],table=spec['tables']['readings'],parser=name,
                    catalog_root=spec['catalog_root'],unreadable_store=raw_store,
                    captures=heads['captures'],**_body_source(spec,raw_store,work/step,listing),
                    decided_at=spec['decided_at'],unreadable_snapshot=unreadable_snapshot)
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports'][step]=error.as_dict()
            return report
        except readings.RawCustodyRequired as error:
            report.update(status='raw_custody_required');report['producerreports'][step]=error.as_dict()
            return report
        report['producerreports'][step]=passes[step]
        if passes[step]['status']=='pending':break
    parsed=passes['readings']
    versions.update(readings=parsed['parser_version'],parsers={p:readings.current_version(p)
        for p in ['sniff','html','xml','json']})
    versions.update({name:run['parser_version'] for name,run in passes.items() if name!='readings'})
    batches=[batch for run in passes.values() for batch in run['batches']]
    imports=[batch['unreadable_provenance'] for batch in batches]
    acknowledgements={batch['unreadable_provenance']['key']:batch['_unreadable_custody']
        for batch in batches if batch['unreadable_provenance'] is not None}
    if any(run['status']=='pending' for run in passes.values()):
        report.update(status='pending',provenance=_final_provenance(provenance,raw_store,imports,identities,
            acknowledgements=acknowledgements,unreadable_snapshot=unreadable_snapshot))
        return report
    filename_head=tables.resolve_tables(**authority,work=work/'filename-head',
        tables={'filename_readings':spec['tables']['filename_readings']})['filename_readings']
    names=filenames.stage(captures=heads['captures'],existing=filename_head,engine=engine,
        work=work/'filenames',decided_at=spec['decided_at'],vocabularies=spec.get('vocabularies'),
        recovery_files=_input_files(provenance['recoveries']),unreadable_files=unreadable_snapshot.files(),
        unreadable_store=raw_store)
    names['append']=(filenames.append(names,**authority,work=work/'filenames-append',
        table=spec['tables']['filename_readings']) if pq.ParquetFile(names['readings']).metadata.num_rows else None)
    imports.append(names['unreadable_provenance'])
    if names['unreadable_provenance'] is not None:
        acknowledgements[names['unreadable_provenance']['key']]=names['_unreadable_custody']
    report['producerreports']['filename_readings']=names;versions['filename_readings']=names['catalog_version']
    # D4 routes House XML by its current reading, so it reads readings after this run's append.
    readings_head=tables.resolve_tables(**authority,work=work/'readings-head',
        tables={'readings':spec['tables']['readings']})['readings']
    if 'meeting_records' in spec['tables']:
        meeting_head=tables.resolve_tables(**authority,work=work/'meeting-head',
            tables={'meeting_records':spec['tables']['meeting_records']})['meeting_records']
        try:
            meetings_staged=meeting_records.stage(captures=heads['captures'],existing=meeting_head,engine=engine,
                work=work/'meeting-records',local_root=spec.get('local_root'),raw_store=raw_store,
                unreadable_files=unreadable_snapshot.files(),max_work_items=spec['max_work_items'],
                decided_at=spec['decided_at'],unreadable_store=raw_store,readings=readings_head)
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports']['meeting_records']=error.as_dict()
            return report
        meetings_staged['append']=(meeting_records.append(meetings_staged,**authority,work=work/'meeting-records-append',
            table=spec['tables']['meeting_records']) if pq.ParquetFile(meetings_staged['records']).metadata.num_rows else None)
        imports.append(meetings_staged['unreadable_provenance'])
        if meetings_staged['unreadable_provenance'] is not None:
            acknowledgements[meetings_staged['unreadable_provenance']['key']]=meetings_staged['_unreadable_custody']
        report['producerreports']['meeting_records']=meetings_staged
        versions['meeting_records']=meetings_staged['parser_version']
    if 'appearance_records' in spec['tables']:
        appearance_head=tables.resolve_tables(**authority,work=work/'appearance-head',
            tables={'appearance_records':spec['tables']['appearance_records']})['appearance_records']
        try:
            appearances_staged=appearance_records.stage(captures=heads['captures'],existing=appearance_head,engine=engine,
                work=work/'appearance-records',local_root=spec.get('local_root'),raw_store=raw_store,
                unreadable_files=unreadable_snapshot.files(),max_work_items=spec['max_work_items'],
                decided_at=spec['decided_at'],unreadable_store=raw_store,readings=readings_head)
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports']['appearance_records']=error.as_dict()
            return report
        appearances_staged['append']=(appearance_records.append(appearances_staged,**authority,work=work/'appearance-records-append',
            table=spec['tables']['appearance_records']) if pq.ParquetFile(appearances_staged['records']).metadata.num_rows else None)
        imports.append(appearances_staged['unreadable_provenance'])
        if appearances_staged['unreadable_provenance'] is not None:
            acknowledgements[appearances_staged['unreadable_provenance']['key']]=appearances_staged['_unreadable_custody']
        report['producerreports']['appearance_records']=appearances_staged
        versions['appearance_records']=appearances_staged['parser_version']
    for name,module in DAILY_CAPTURE_RECORDS.items():
        if name not in spec['tables']:continue
        head=tables.resolve_tables(**authority,work=work/(name+'-head'),
            tables={name:spec['tables'][name]})[name]
        try:
            staged=module.stage(captures=heads['captures'],existing=head,engine=engine,
                work=work/name,local_root=spec.get('local_root'),raw_store=raw_store,
                unreadable_files=unreadable_snapshot.files(),max_work_items=spec['max_work_items'],
                decided_at=spec['decided_at'],unreadable_store=raw_store)
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports'][name]=error.as_dict()
            return report
        staged['append']=(module.append(staged,**authority,work=work/(name+'-append'),
            table=spec['tables'][name]) if pq.ParquetFile(staged['records']).metadata.num_rows else None)
        imports.append(staged['unreadable_provenance'])
        if staged['unreadable_provenance'] is not None:
            acknowledgements[staged['unreadable_provenance']['key']]=staged['_unreadable_custody']
        report['producerreports'][name]=staged
        versions[name]=staged['parser_version']
    report['provenance']=_final_provenance(provenance,raw_store,imports,identities,
        acknowledgements=acknowledgements,unreadable_snapshot=unreadable_snapshot)
    final=tables.resolve_tables(**authority,work=work/'final-heads',tables=spec['tables'])
    if final['captures']!=heads['captures']:
        raise ValueError('Current captures head changed after daily parser work; rerun from fresh heads')
    if (captures.current_version()!=versions['captures']
            or filenames.current_version(vocabularies=spec.get('vocabularies'))!=versions['filename_readings']
            or {p:readings.current_version(p) for p in versions['parsers']}!=versions['parsers']
            or readings.bundle_version(versions['parsers'],policy=readings.worker_limits())!=versions['readings']):
        raise ValueError('Daily producer definitions changed during execution')
    if any(readings.current_version(name)!=versions[name] for name in derived_parsers(spec)):
        raise ValueError('Daily derived readings definitions changed during execution')
    if 'meeting_records' in versions:
        _check_entity_versions('meeting_records',versions['meeting_records'],meeting_records)
    if 'appearance_records' in versions:
        _check_entity_versions('appearance_records',versions['appearance_records'],appearance_records)
    for name,module in DAILY_CAPTURE_RECORDS.items():
        if name in versions:
            _check_entity_versions(name,versions[name],module)
    report['pins']=final
    report['receipt_keys']=_complete_receipt_keys(final['captures'],engine=engine,work=work/'receipt-identity')
    report['status']='completed'
    return report


def _record_activation_file(pin, label):
    path=Path(pin['path'])
    if file_pin(path)!={key:pin[key] for key in ('sha256','size')}:
        raise ValueError(f'{label} activation input changed: {path}')
    return path


def _record_activation_rows(name,head,stage,*,engine,work,complete,versions,label):
    """Compare every new-pin field before the append helper may skip existing keys."""
    incoming=pq.read_table(_record_activation_file(stage['records'],label)).to_pylist()
    if ({row['source'] for row in incoming}!=versions.keys()
            or any(row['parser_version']!=versions.get(row['source']) or row['status']!='completed' for row in incoming)):
        raise ValueError(f'{label} activation input contains rows outside the selected generation')
    key=lambda row:(row['record_sha'],row['source'],row['parser_version'])
    expected={key(row):row for row in incoming}
    if len(expected)!=len(incoming):raise ValueError(f'Duplicate {label} incoming keys')
    predicates=' OR '.join(f"(source='{source}' AND parser_version='{version}')"
                           for source,version in versions.items())
    run_job(work,engine,inputs=[tables.table_input('head',head)],steps=[],
        outputs=[parquet_output(work,'rows',f"SELECT * FROM head WHERE {predicates} LIMIT {len(incoming)+1}",
            list(tables.TABLE_SPECS[name]['primary_key']))])
    actual=pq.read_table(work/'rows.parquet').to_pylist()
    found={key(row):row for row in actual}
    if (len(found)!=len(actual) or found.keys()-expected.keys()
            or any(row!=expected[k] for k,row in found.items())
            or complete and found.keys()!=expected.keys()):
        raise ValueError(f'{label} existing new-version rows conflict with the staged values: {name}')
    return len(found)==len(expected)


def _record_activation_step(records,before,after,label):
    if (before['table_uuid']!=after['table_uuid'] or before['schema_id']!=after['schema_id']
            or before['snapshot']==after['snapshot']):
        raise ValueError(f'{label} activation advanced an unexpected table or schema')
    lineage=records.lineage(after['metadata_location'])
    if lineage.get(after['snapshot'])!=(before['snapshot'],'append'):
        raise ValueError(f'{label} activation cannot explain the advanced head as its one append')


def append_scoped_recovery(prepared, *, engine, catalog_root, targets, producer_records, work):
    """Append a staged recovery under the caller's archive writer lock.

    The caller admits and stages one receipt and its filename work locally.
    An interrupted append can be adopted only from durable intent and an exact
    one-append delta. No parser or raw provenance writer runs here.
    """
    authority=dict(engine=engine,catalog_root=catalog_root)
    base=prepared['base']
    versions={'captures':captures.current_version(),'filename_readings':filenames.current_version()}
    if (set(targets)!=set(TABLE_NAMES) or set(base)!=set(targets)
            or prepared['versions']!=versions or set(prepared['stages'])!=set(versions)):
        raise ValueError('Scoped recovery requires its original table and producer bindings')
    instant(prepared['decided_at'])
    chain,refusal=_producer_bases(producer_records,base)
    if chain is None:
        raise ValueError(f'Scoped recovery predecessor proof unavailable: {refusal}')
    work=Path(work)
    work.mkdir(parents=True,exist_ok=True)
    journal=work/'intent.json'
    identity=dict(prepared=prepared,targets=targets,catalog_root=catalog_root,chain=chain)
    if journal.exists():
        state=json.loads(journal.read_text())
        if state['identity']!=identity:
            raise ValueError('Scoped recovery continuation inputs changed')
    else:
        state=dict(identity=identity,intents=[])
        durable_json(journal,state)
    attempt=work/('attempt-'+str(len(list(work.glob('attempt-*')))+1))
    attempt.mkdir()
    stages={name:_record_activation_file(pin,'Scoped recovery') for name,pin in prepared['stages'].items()}
    rows={name:pq.read_metadata(path).num_rows for name,path in stages.items()}
    if rows['captures']!=1 or rows['filename_readings']>1:
        raise ValueError('Scoped recovery admits one capture row and at most one filename row')
    keys={'captures':['receipt_key'],'filename_readings':filenames.PK}

    def prove_delta(name,head,phase):
        _record_activation_step(producer_records,base[name],head,'Scoped recovery')
        columns=','.join(f'h."{c}"' for c in pq.read_schema(stages[name]).names)
        using=','.join(f'"{k}"' for k in keys[name])
        checks=run_job(attempt/f'{phase}-{name}',engine,inputs=[
            tables.table_input('before_rows',base[name]),tables.table_input('after_rows',head),
            tables.table_input('incoming',stages[name])],steps=[dict(name='matching_rows',
                sql=f'SELECT {columns} FROM after_rows h JOIN incoming i USING ({using})')],
            outputs=[],queries=[dict(name='delta',sql='''SELECT
                (SELECT count(*) FROM after_rows)-(SELECT count(*) FROM before_rows) AS added,
                (SELECT count(*) FROM (SELECT * FROM matching_rows EXCEPT ALL SELECT * FROM incoming) extra) AS extra,
                (SELECT count(*) FROM (SELECT * FROM incoming EXCEPT ALL SELECT * FROM matching_rows) missing) AS missing''')])
        if checks['delta']!=[dict(added=rows[name],extra=0,missing=0)]:
            raise ValueError(f'Scoped recovery advanced head differs from the staged {name} delta')

    heads=tables.resolve_tables(**authority,work=attempt/'heads',tables=targets)
    for name,head in heads.items():
        if head==base[name]:
            continue
        if name not in state['intents'] or not rows.get(name):
            raise ValueError(f'Scoped recovery observed an unexplained {name} head')
        prove_delta(name,head,'resume')

    def record(heads):
        return _record_moved(producer_records,chain,base,heads,decided_at=prepared['decided_at'],
            transition_inputs={name:dict(records=prepared['stages'][name],
                receipt_key=prepared['receipt_key'],new_unreadable_files=[]) for name in stages},
            transition_field='scoped_recovery')

    records=record(heads)
    for name,path in stages.items():
        if heads[name]!=base[name] or not rows[name]:
            continue
        if name not in state['intents']:
            state['intents'].append(name)
            durable_json(journal,state)
        if name=='captures':
            result=tables.append_rows(path,**authority,work=attempt/'append-captures',table=targets[name],
                keys=keys[name],definition=versions[name])
        else:
            result=filenames.append(dict(readings=path,catalog_version=versions[name],unreadable_pending=False),
                **authority,work=attempt/'append-filenames',table=targets[name])
        head=tables.resolve_tables(**authority,work=attempt/f'head-{name}',tables={name:targets[name]})[name]
        if head!={key:result[key] for key in head}:
            raise ValueError(f'Scoped recovery append no longer names the current {name} head')
        prove_delta(name,head,'append')
        heads[name]=head
        records=record(heads)
    final=tables.resolve_tables(**authority,work=attempt/'final-heads',tables=targets)
    if final!=heads:
        raise ValueError('Scoped recovery heads changed before selection')
    return dict(pins=final,producers=records,
        receipt_keys=_complete_receipt_keys(final['captures'],engine=engine,work=attempt/'receipt-identity'))


def activate_house_xml_records(prepared,*,engine,raw_store,producer_records,catalog_root,targets,work,
                              decided_at,resume,max_output_bytes,min_disk_bytes):
    """Append the qualified zero-refusal House cohort as a real daily-chain owner.

    The registered caller holds the archive writer lock. This callable performs
    the appends and records their actual heads, including after a lost response.
    It never reads source bodies, parses XML or imports provenance/receipts.
    """
    modules=dict(meeting_records=meeting_records,appearance_records=appearance_records,committee_records=committee_records)
    if prepared['tables'].keys()!=modules.keys() or targets.keys()!=modules.keys() or len(prepared['frozen_unreadable'])!=31:
        raise ValueError('House XML activation requires exactly the qualified three-table cohort')
    return _activate_record_transition(prepared,engine=engine,raw_store=raw_store,producer_records=producer_records,
        catalog_root=catalog_root,targets=targets,work=work,decided_at=decided_at,resume=resume,
        max_output_bytes=max_output_bytes,min_disk_bytes=min_disk_bytes,modules=modules,house_xml=True,
        label='House XML',transition_field='house_xml_transition')


def activate_appearance_generations(prepared,*,engine,raw_store,producer_records,catalog_root,targets,work,
                                    decided_at,resume,max_output_bytes,min_disk_bytes):
    """Append qualified MODS and Senate page generations in one appearance snapshot."""
    modules={'appearance_records':appearance_records}
    if prepared['tables'].keys()!=modules.keys() or targets.keys()!=modules.keys():
        raise ValueError('Appearance activation requires only the appearance table')
    if prepared['tables']['appearance_records']['versions'].keys()!={'mods','senate_page'}:
        raise ValueError('Appearance activation requires the MODS and Senate page generations')
    return _activate_record_transition(prepared,engine=engine,raw_store=raw_store,producer_records=producer_records,
        catalog_root=catalog_root,targets=targets,work=work,decided_at=decided_at,resume=resume,
        max_output_bytes=max_output_bytes,min_disk_bytes=min_disk_bytes,modules=modules,house_xml=False,
        label='Appearance',transition_field='appearance_transition')


def _activate_record_transition(prepared,*,engine,raw_store,producer_records,catalog_root,targets,work,
                                decided_at,resume,max_output_bytes,min_disk_bytes,modules,house_xml,
                                label,transition_field):
    from shutil import disk_usage
    from congress_api.retention.provenance import durable_json
    from congress_api.lake.producer_records import encode

    authority=dict(engine=engine,catalog_root=catalog_root)
    tables.validate_catalog_authority(engine,catalog_root)
    writer=writer_identity(ROOT,DAILY_JOB)
    identity=dict(prepared=prepared,targets=targets,catalog_root=catalog_root,writer=writer,decided_at=decided_at,
                  max_output_bytes=max_output_bytes,min_disk_bytes=min_disk_bytes)
    if not house_xml:
        identity['transition']=transition_field
    versions={name:{'house_xml':stage['version']} if house_xml else stage['versions']
              for name,stage in prepared['tables'].items()}
    work=Path(work);state_path=work/'activation.json'
    if work.exists():
        if not resume or not state_path.is_file():raise ValueError(f'{label} activation needs fresh work or an explicit resume')
        state=json.loads(state_path.read_text())
        if state['identity']!=identity:raise ValueError(f'{label} activation resume identity changed')
    else:
        work.mkdir(parents=True)
        state=dict(identity=identity,heads={name:item['base'] for name,item in prepared['tables'].items()},
            head_records={name:{k:item['base_record'][k] for k in ('sha256','size')} for name,item in prepared['tables'].items()},
            intent=[],completed=[],append_results={},status='running')

    def save():
        if disk_usage(work).free<min_disk_bytes:raise ValueError(f'{label} activation reached its disk floor')
        if sum(path.stat().st_size for path in work.rglob('*') if path.is_file())>max_output_bytes:
            raise ValueError(f'{label} activation exceeded its output byte limit')
        durable_json(state_path,state)

    save()
    attempt=work/('attempt-'+str(len(list(work.glob('attempt-*')))+1));attempt.mkdir()
    heads=tables.resolve_tables(**authority,work=attempt/'heads',tables=targets)
    expected=dict(state['heads'])
    for name,stage in prepared['tables'].items():
        current_versions=modules[name].current_versions()
        if any(current_versions.get(source)!=version for source,version in versions[name].items()):
            raise ValueError(f'{label} activation parser versions changed')
        found=producer_records.find(name,expected[name])
        if found is None or any(found[1][k]!=state['head_records'][name][k] for k in ('sha256','size')):
            raise ValueError(f'{label} activation predecessor record differs from its exact pin')
        if heads[name]!=expected[name]:
            if name not in state['intent']:raise ValueError(f'{label} activation base head drifted before shared writes')
            _record_activation_step(producer_records,expected[name],heads[name],label)
        _record_activation_rows(name,heads[name],stage,engine=engine,work=attempt/('preflight-'+name),
                               complete=heads[name]!=expected[name] or name in state['completed'],
                                versions=versions[name],label=label)

    # Requalify only the small current refusal inventory. This accepted cohort has
    # no new decisions: any baseline drift stops before table or ledger writes.
    inventory=UnreadableInventory(raw_store,work=attempt/'unreadable-inventory')
    frozen={item['key']:item for item in prepared['frozen_unreadable']}
    current={item['key']:item for item in inventory.rows()}
    if (current.keys()!=frozen.keys() or any(current[key][field]!=frozen[key][field]
            for key in frozen for field in ('sha256','size'))):
        raise ValueError(f'{label} activation refusal baseline changed')
    details={name:dict(cohort=prepared['cohort'],records=stage['records'],new_unreadable_files=[])
             for name,stage in prepared['tables'].items()}
    if house_xml:
        for name,stage in prepared['tables'].items():
            details[name].update(delta_producer=stage['producer'],disposition_ledger=stage['ledger'])

    def record_progress(initial,final,chain):
        written=_record_moved(producer_records,chain,initial,final,decided_at=decided_at,transition_inputs=details,
                              transition_field=transition_field)
        for name,head in final.items():
            if head==initial[name]:continue
            found=producer_records.find(name,head)
            if found is None:raise ValueError(f'{label} activation head was not durably recorded')
            state['heads'][name]=head;state['head_records'][name]=found[1]
            if name not in state['completed']:state['completed'].append(name)
        state['producer_records']=dict(state.get('producer_records',{}),**written)
        state['intent']=[]
        save()

    # A killed launcher may leave the append committed but its response unsaved.
    # The durable intent, exact values and one-append ancestry explain that head;
    # reconcile it before issuing another append, never adopt arbitrary drift.
    if heads!=expected:
        chain,refusal=_producer_bases(producer_records,expected)
        if chain is None:raise ValueError('House XML recovery predecessor proof unavailable: '+str(refusal))
        record_progress(expected,heads,chain)
    chain,refusal=_producer_bases(producer_records,heads)
    if chain is None:raise ValueError(f'{label} activation producer proof unavailable: '+str(refusal))
    initial=dict(heads)
    state['status']='running';save()
    try:
        for name,module in modules.items():
            if name in state['completed']:continue
            stage=prepared['tables'][name]
            # No pending flag is cleared here: the qualified input is explicitly
            # the observed cohort with zero new refusals and unchanged provenance.
            state['intent']=[name];save()
            result=module.append(dict(records=_record_activation_file(stage['records'],label),
                parser_version=module.current_versions(),unreadable_pending=False),
                **authority,work=attempt/('append-'+name),table=targets[name])
            state['append_results'][name]=result;save()
            actual=tables.resolve_tables(**authority,work=attempt/('head-'+name),tables={name:targets[name]})[name]
            returned={key:result[key] for key in ('metadata_location','table_uuid','snapshot','schema_id')}
            if actual!=returned:raise ValueError('House XML append result no longer names the actual head')
            _record_activation_rows(name,actual,stage,engine=engine,work=attempt/('reconcile-'+name),
                                    complete=True,versions=versions[name],label=label)
            heads[name]=actual
            # Bind each completed table before the next table can fail.
            _record_activation_step(producer_records,initial[name],actual,label)
            record_progress(initial,heads,chain)
            initial=dict(heads)
            chain,refusal=_producer_bases(producer_records,heads)
            if chain is None:raise ValueError(f'{label} activation new head lacks its producer: '+str(refusal))
    finally:
        final=tables.resolve_tables(**authority,work=attempt/'final-heads',tables=targets)
        for name,head in final.items():
            if head==initial[name]:continue
            if name not in state['intent']:raise ValueError(f'{label} activation observed an unexplained advanced head')
            _record_activation_step(producer_records,initial[name],head,label)
            _record_activation_rows(name,head,prepared['tables'][name],engine=engine,
                                   work=attempt/('recover-'+name),complete=True,versions=versions[name],label=label)
        record_progress(initial,final,chain)

    pins={name:dict(kind='native_table',**head) for name,head in state['heads'].items()}
    records={name:producer_records.find(name,head)[0] for name,head in state['heads'].items()}
    producer_files={}
    for name,record in records.items():
        path=work/(name+'.head.json');path.write_bytes(encode(record))
        producer_files[name]=dict(path=str(path),**file_pin(path))
    state['status']='appended'
    state['result']=dict(status='appended',pins=pins,producers=producer_files,producer_records=state['head_records'],
        cohort=prepared['cohort'],unchanged_selectors=prepared['unchanged_selectors'],
        unchanged_inventory=prepared['unchanged_inventory'],unreadable_files=prepared['frozen_unreadable'],
        new_unreadable_files=[],receipts_unchanged=True)
    save()
    return state['result']
