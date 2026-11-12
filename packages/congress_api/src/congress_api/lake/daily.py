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
from congress_api.lake.producer_records import DAILY_JOB,appended_from,owed_key,pin_of
from congress_api.lake.receipt_inventory import (LocalReceiptStore,R2ReceiptStore,copy_receipts,
    discover_receipts,select_receipts)
from congress_api.retention.writer_identity import writer_identity
from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter,validate_key
from congress_shared.storage import single_put_md5
from congress_api.retention.provenance import durable_json,field,file_pin,instant,json_input,local_unreadable_inventory,parquet_output,run_job
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
# Waits between final head reads. That read is idempotent and follows appends, so a catalog
# blip (nightly 20261108T193702Z: a /v1/config connect timeout) must not cost the records.
FINAL_HEAD_DELAYS=(10,30,90)
# Waits between attempts to mark owed records refused; an unmarked one could be completed.
REFUSE_DELAYS=(1,5,15)
SLEEP=time.sleep  # The retry waits; tests replace this, never the global time.sleep.


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
        if (not isinstance(scope,dict) or set(scope)!={'captures','versions','max_stored_bytes'}
                or not isinstance(scope['captures'],dict)):
            raise ValueError('Derived scopes require a qualified captures baseline, versions and budgets')
        tables.table_input('derived_baseline',scope['captures'])
        if scope['versions']!=current_pins():
            raise ValueError('Derived scope reading versions changed; qualify a new baseline')
        readings._positive(scope['max_stored_bytes'],'max_stored_bytes')
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

    Lists each family's dated prefixes within INCREMENTAL_LOOKBACK_DAYS of its newest
    captured date and onward (inclusive), so late receipts in recent prior day prefixes
    are picked up without listing full history; the native anti-join drops keys already
    in captures.
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


def _scope_daily_inputs(heads,backlog,stage,*,engine,output_dir,job_dir,need_keys=False):
    """Materialize the local captures and readings subsets for (backlog + staged) bodies once."""
    from congress_api.retention.provenance import parquet_output,run_job
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    if not backlog['work_items'] and stage is None:
        run_job(Path(job_dir),engine,inputs=[tables.table_input('captures',heads['captures']),
            tables.table_input('readings',heads['readings'])],steps=[],
            outputs=[parquet_output(output_dir,'scoped-captures','SELECT * FROM captures WHERE false',
                    ['receipt_key','receipt_line','capture_index']),
                parquet_output(output_dir,'scoped-readings','SELECT * FROM readings WHERE false',readings.PK)])
        return dict(captures=output_dir/'scoped-captures.parquet',readings=output_dir/'scoped-readings.parquet',keys=[])
    inputs=[tables.table_input('captures',heads['captures']),tables.table_input('readings',heads['readings']),
            tables.table_input('backlog',backlog['work_list'])]
    scoped='SELECT DISTINCT body_sha AS sha256 FROM backlog'
    listed='SELECT sha256 FROM scoped_shas'
    rows='SELECT * FROM prior_captures'
    if stage is not None:
        inputs.append(tables.table_input('staged',stage))
        names=pq.read_schema(stage).names
        scoped+=' UNION SELECT sha256 FROM staged WHERE sha256 IS NOT NULL'
        listed=('SELECT DISTINCT body_sha AS sha256 FROM backlog'
                ' UNION SELECT s.sha256 FROM staged s WHERE s.sha256 IS NOT NULL'
                ' AND NOT EXISTS(SELECT 1 FROM prior_captures c WHERE c.sha256=s.sha256)')
        rows=('SELECT '+','.join('c."'+n+'"' for n in names)+' FROM prior_captures c'
              ' UNION ALL SELECT '+','.join('"'+n+'"' for n in names)+' FROM staged')
    steps=[dict(name='scoped_shas',sql=scoped,materialize=True),
           dict(name='prior_captures',sql='SELECT c.* FROM scoped_shas k JOIN captures c ON c.sha256=k.sha256',materialize=True)]
    if need_keys:steps.append(dict(name='listed_shas',sql=listed,materialize=True))
    steps.append(dict(name='scoped_captures',sql=rows,materialize=True))
    queries=([dict(name='keys',sql="""SELECT DISTINCT concat('bodies/sha256/',substr(encode(c.sha256,'hex'),1,2),'/',
        encode(c.sha256,'hex'),coalesce(c.stored_suffix,'.gz')) AS key FROM scoped_captures c
        JOIN listed_shas k ON c.sha256=k.sha256 ORDER BY key""")] if need_keys else [])
    result=run_job(Path(job_dir),engine,inputs=inputs,steps=steps,
        outputs=[parquet_output(output_dir,'scoped-captures','SELECT * FROM scoped_captures',
                ['receipt_key','receipt_line','capture_index']),
            parquet_output(output_dir,'scoped-readings','SELECT r.* FROM scoped_shas k JOIN readings r ON k.sha256=r.body_sha',
                readings.PK)],
        queries=queries)
    return dict(captures=output_dir/'scoped-captures.parquet',readings=output_dir/'scoped-readings.parquet',
        keys=[row['key'] for row in result.get('keys',[])])


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
    scoped=_scope_daily_inputs(heads,backlog,stage,engine=engine,output_dir=work,job_dir=work/'scope',need_keys=True)
    keys=scoped['keys']
    for key in keys:validate_key(key)
    client,bucket=raw_store.adapter.client,raw_store.adapter.bucket
    with ThreadPoolExecutor(max_workers=max(1,min(HEAD_WORKERS,len(keys)))) as pool:
        found=list(pool.map(lambda key:_head(client,bucket,key),keys))
    listing=work/'body-listing.parquet'
    pq.write_table(pa.Table.from_pylist([row for row in found if row is not None],schema=LISTING_SCHEMA),listing)
    planned=readings.run(engine=engine,work=work/'readings',mode='daily',execute=False,
        max_work_items=spec['max_work_items'],existing=scoped['readings'],captures=scoped['captures'],
        unreadable_files=unreadable_snapshot.files(),body_inventory=None,body_listing=listing,raw_ranges=True,
        local_root=work/'unopened',decided_at=spec['decided_at'],parser=parser)
    return dict(listing=listing,planned=planned,heads=len(keys),
                absent=[key for key,row in zip(keys,found) if row is None],
                scoped_captures=scoped['captures'],scoped_readings=scoped['readings'])


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


class CheckoutChanged(ValueError):
    """The checkout is no longer the clean commit the run named, so its records would lie."""


def _require_commit(chain):
    """The one owner of: a record names the commit that actually ran."""
    try:commit=writer_identity(ROOT,DAILY_JOB)['commit']
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        raise CheckoutChanged('Application checkout changed during daily production: '+str(error)) from error
    if commit!=chain['writer']['commit']:
        raise CheckoutChanged('Application commit changed during daily production')


def _record_fields(chain,name,base,decided_at):
    """A table's record without its head: what a run owes before it appends onto `base`."""
    return dict(version=1,input=name,job=DAILY_JOB,commit=chain['writer']['commit'],
        lockfile_digest=chain['writer']['lockfile_digest'],decided_at=decided_at,
        base=dict(selector=dict(kind='native_table',**base),record=chain['bases'][name]))


def _producer_bases(records,heads):
    """Gate 5 preflight: the commit that will append, and each head's own record.

    Refuses before any append: a head without a record would leave every later
    snapshot of that table unprovable. An unrecorded head is first completed from
    the record a stopped run owed for it (_complete_owed); the refusal names any
    owed record it could not use, and either result lists owed records completed
    but not marked (`owed_unmarked`).
    """
    try:writer=writer_identity(ROOT,DAILY_JOB)
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        return None,dict(unavailable='the checkout was not clean, so no commit can be named: '+str(error))
    bases={};missing=[];owed={};unmarked=[]
    for name,pin in heads.items():
        if pin['snapshot'] is None:bases[name]=None;continue
        found=records.find(name,pin)
        if found is None:
            found,problem=_complete_owed(records,name,pin,unmarked)
            if problem is not None:owed[name]=problem
        if found is None:missing.append(name)
        else:bases[name]=found[1]
    marks={'owed_unmarked':unmarked} if unmarked else {}
    if missing:return None,dict(missing=sorted(missing),**({'owed':owed} if owed else {}),**marks)
    return dict(writer=writer,bases=bases,**marks),None


def _complete_owed(records,name,head,unmarked):
    """((record, reference), None) once the owed record for this unrecorded head is written,
    (None, why) when it cannot be, or (None, None) when no owed record applies.

    The base is the head's nearest recorded ancestor (or the empty table), reached by
    appends only. A record in between stops the walk, so an owed record left at an older
    base by a run whose records were written another way is never used. The lineage is
    one bounded metadata read; the walk is one record lookup per unrecorded snapshot,
    linear in the stopped run's own appends, and len(lineage)+1 steps bound a cycle.
    """
    lineage=records.lineage(head['metadata_location'])
    base,current=None,head['snapshot']
    for _ in range(len(lineage)+1):
        if current not in lineage:
            return None,dict(reason=f'snapshot {current} is missing from the head lineage')
        parent=lineage[current][0]
        if parent is None:break
        base=records.at(name,head['table_uuid'],parent)
        if base is not None:break
        current=parent
    else:
        return None,dict(reason='the head lineage repeats a snapshot')
    snapshot=None if base is None else base[0]['selector']['snapshot']
    if not appended_from(lineage,head['snapshot'],snapshot):return None,None
    found=records.owed(dict(table_uuid=head['table_uuid'],snapshot=snapshot))
    if found is None:return None,None
    intent,key,version=found
    state=intent.get('owed') or {}
    if state.get('status')!='pending':
        return None,dict(key=key,reason='the owed record is '+str(state.get('status')),owed=state)
    claimed=intent.get('base') or {}
    if base is None:
        matches=(claimed.get('record') is None and (claimed.get('selector') or {}).get('snapshot') is None
                 and (claimed.get('selector') or {}).get('table_uuid')==head['table_uuid'])
    else:
        matches=(claimed.get('record')==base[1]
                 and claimed.get('selector')==dict(kind='native_table',**pin_of(base[0]['selector'])))
    if intent.get('input')!=name or not matches:
        return None,dict(key=key,reason='the owed record names another table or base record')
    record=dict(_owed_fields(intent),selector=dict(kind='native_table',**head))
    reference=records.write(record)
    try:records.owe(dict(intent,owed=dict(status='recorded',by='preflight',record=reference)),version)
    except Exception as error:  # The record is written; the mark is evidence only.
        unmarked.append(f'{key} not marked recorded: {error}')
    return (record,reference),None


def _owed_fields(intent):
    return {k:v for k,v in intent.items() if k!='owed'}


def _owe_records(records,chain,heads,*,decided_at):
    """Before the first append, leave each table's owed record beside the records.

    The caller passes the heads its preflight just proved current and recorded, under
    the nightly flock, so whatever is still pending at them owed nothing and is replaced.
    """
    for name,base in heads.items():
        found=records.owed(base)
        records.owe(dict(_record_fields(chain,name,base,decided_at),owed=dict(status='pending')),
                    None if found is None else found[2])


def _mark_owed(records,base,state,own=None):
    """Mark the owed record at `base` if still pending (and, given `own`, this run's); returns its key."""
    found=records.owed(base)
    if found is None or (found[0].get('owed') or {}).get('status')!='pending':return None
    if own is not None and _owed_fields(found[0])!=own:return None
    records.owe(dict(found[0],owed=state),found[2])
    return found[1]


def _supersede_owed(records,base,label):
    """Before another writer appends onto `base`, retire a daily owed record still pending there.

    That head is recorded and current, so the daily run that left it did not move the table;
    left pending, a later preflight could credit this writer's appends to it.
    """
    _mark_owed(records,base,dict(status='superseded',by=label))


def _refuse_owed(records,chain,initial,*,decided_at,error,delays):
    """Mark every table's owed record refused, retrying each; name any that stays completable."""
    unmarked=[]
    for name,base in initial.items():
        for delay in (*delays,None):
            try:
                _mark_owed(records,base,dict(status='refused',reason=str(error)),
                           _record_fields(chain,name,base,decided_at))
                break
            except Exception as failure:
                if delay is None:unmarked.append(f'{owed_key(base)} ({failure})')
                else:SLEEP(delay)
    if unmarked:
        raise CheckoutChanged(f'{error}; these owed producer records could not be marked refused and must '
                              'not be completed: '+', '.join(unmarked)) from error


def _settle_owed(records,chain,initial,*,authority,work,tables_spec,decided_at,patient=True):
    """(final heads, written records, unmarked notes) after appends.

    The commit is checked once, after the head read or its failure: a changed checkout
    marks the owed records refused so no preflight completes them. A failed head read
    or record write leaves them pending for the next preflight. Marking an owed record
    recorded is evidence only; a failure is returned, never raised. Not `patient`
    (an interrupt), every read and mark is tried once, without waits.
    """
    refuse=dict(decided_at=decided_at,delays=REFUSE_DELAYS if patient else ())
    try:final=_final_heads(authority,work,tables_spec,FINAL_HEAD_DELAYS if patient else ())
    except BaseException:
        try:_require_commit(chain)
        except CheckoutChanged as error:_refuse_owed(records,chain,initial,error=error,**refuse)
        raise
    try:_require_commit(chain)
    except CheckoutChanged as error:
        _refuse_owed(records,chain,initial,error=error,**refuse)
        raise
    written=_write_moved(records,chain,initial,{n:final[n] for n in initial},decided_at=decided_at)
    unmarked=[]
    for name,reference in written.items():
        try:_mark_owed(records,initial[name],dict(status='recorded',by='run',record=reference),
                       _record_fields(chain,name,initial[name],decided_at))
        except Exception as error:unmarked.append(f'{owed_key(initial[name])} not marked recorded: {error}')
    return final,written,unmarked


def _finish_owed(records,chain,initial,report,stopped,**settle):
    """Settle in a producer's finally; returns the final heads (None after an interrupt's failure).

    Owed-record marks never fail a run: they go on its stopping exception's notes, or in
    its report. An interrupt (`stopped` is no Exception) gets one try at everything and
    keeps propagating; what stays pending is completed by the next preflight.
    """
    interrupted=stopped is not None and not isinstance(stopped,Exception)
    try:final,report['producers'],unmarked=_settle_owed(records,chain,initial,patient=not interrupted,**settle)
    except Exception as error:
        if not interrupted:raise
        stopped.add_note(f'Owed producer records not settled: {error}')
        return None
    unmarked=chain.get('owed_unmarked',[])+unmarked
    if unmarked and stopped is not None:stopped.add_note('; '.join(unmarked))
    elif unmarked:report['owed_unmarked']=unmarked
    return final


def _record_moved(records,chain,initial,final,*,decided_at,transition_inputs=None,
                  transition_field="house_xml_transition"):
    """One record per table whose head moved during this run, written before returning."""
    _require_commit(chain)
    return _write_moved(records,chain,initial,final,decided_at=decided_at,
                        transition_inputs=transition_inputs,transition_field=transition_field)


def _write_moved(records,chain,initial,final,*,decided_at,transition_inputs=None,
                 transition_field="house_xml_transition"):
    written={}
    for name,pin in sorted(final.items()):
        if pin==initial[name]:continue
        record=dict(_record_fields(chain,name,initial[name],decided_at),selector=dict(kind='native_table',**pin))
        if transition_inputs is not None:
            record[transition_field]=transition_inputs[name]
        written[name]=records.write(record)
    return written


def _final_heads(authority,work,tables_spec,delays=FINAL_HEAD_DELAYS):
    """Heads after appends: a failed read is retried in a sibling dir, then raised."""
    for attempt,delay in enumerate((*delays,None)):
        try:
            return tables.resolve_tables(**authority,tables=tables_spec,
                work=work if not attempt else work.with_name(f'{work.name}-retry-{attempt}'))
        except (OSError,subprocess.TimeoutExpired):  # DocSpecFailure is an OSError
            if delay is None:raise
            SLEEP(delay)


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


def _stored_bytes(work_list):
    """(known stored bytes, bodies with no stored size) over one work list."""
    sizes=pq.read_table(work_list,columns=['stored_bytes']).column('stored_bytes')
    return pc.sum(sizes).as_py() or 0,sizes.null_count


def _carry_html_metadata(work_list,scoped,max_items,max_bytes,*,engine,work):
    """Narrow the scoped captures and readings to the oldest budget's worth of the work list.

    Bodies are ordered by their oldest receipt in (day, key) order, as _within_budget orders
    receipts (RECEIPT_DAY), then by hash, so nothing starves and every night picks the same
    prefix. The prefix stops at `max_items` bodies or before its stored bytes pass `max_bytes`,
    but always holds one body. An unknown stored size (an R2 capture that pinned none; custody
    learns it later) counts as more than the whole byte budget, so such a body is only ever
    admitted alone, first. The rest stays unread in the current heads, which the next night's
    anti-join selects again; nothing records it here. One native job: O(W log W) for W pending
    bodies plus joins from them into the scoped captures and readings, never a rescan per body.
    """
    receipt=f"concat(coalesce((regexp_match(c.receipt_key,'{RECEIPT_DAY.pattern}'))[1],''),' ',c.receipt_key)"
    order='ORDER BY f.oldest,w.body_sha'
    carried=run_job(work,engine,inputs=[tables.table_input('work_list',work_list),
        tables.table_input('captures',scoped/'captures.parquet'),tables.table_input('readings',scoped/'readings.parquet')],
        steps=[dict(name='oldest',materialize=True,sql=f'''SELECT w.body_sha,min({receipt}) AS oldest
            FROM work_list w JOIN captures c ON c.sha256=w.body_sha GROUP BY w.body_sha'''),
        dict(name='ordered',materialize=True,sql=f'''SELECT w.body_sha,w.stored_bytes,f.oldest,
            row_number() OVER ({order}) AS position,
            sum(coalesce(w.stored_bytes,{int(max_bytes)+1})) OVER ({order} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS held
            FROM work_list w JOIN oldest f ON f.body_sha=w.body_sha'''),
        dict(name='admitted',materialize=True,sql=f'''SELECT body_sha FROM ordered
            WHERE position<={int(max_items)} AND (held<={int(max_bytes)} OR position=1)''')],
        outputs=[parquet_output(work,'captures','SELECT c.* FROM admitted a JOIN captures c ON c.sha256=a.body_sha',
                ['receipt_key','receipt_line','capture_index']),
            parquet_output(work,'readings','SELECT r.* FROM admitted a JOIN readings r ON r.body_sha=a.body_sha',readings.PK)],
        # Known sizes only: the stand-in for an unknown size is a rule, not bytes.
        queries=[dict(name='carried',sql='''SELECT count(*) AS bodies,coalesce(sum(stored_bytes),0) AS stored_bytes,
            count(*)-count(stored_bytes) AS unknown_sizes,nullif(split_part(min(oldest),' ',1),'') AS oldest_day
            FROM ordered o WHERE NOT EXISTS(SELECT 1 FROM admitted a WHERE a.body_sha=o.body_sha)''')])['carried'][0]
    return carried


def _daily_html_metadata(spec,heads,*,engine,raw_store,unreadable_snapshot,work):
    """Read only missing pairs for bodies admitted after a qualified immutable baseline.

    A fresh attempt uses the same baseline, so committed receipts cannot hide an
    interrupted derived pass. The maintained scoped producer selection settles accepted
    older readings and active unreadable decisions before either budget is evaluated.
    Admitted work fits both budgets, so it is read in one batch and appended in one
    catalog commit (ct-z4i9: one commit per body made the step 93% catalog round-trips).
    Work past a budget is carried, not refused (ct-hiec): the oldest budget's worth is
    read (_carry_html_metadata) and the report names the rest, which the next night's
    selection finds still unread. Unknown stored sizes at the read still refuse.
    """
    scope=derived_scopes(spec)['html_metadata']
    baseline=scope['captures']
    if baseline['table_uuid']!=heads['captures']['table_uuid']:
        raise ValueError('Derived baseline must name the current captures table')
    work=Path(work)
    scope_work=work/'delta'
    scope_work.mkdir(parents=True,exist_ok=False)
    inputs=[tables.table_input('captures',heads['captures']),tables.table_input('baseline',baseline)]
    schema=dict(id='Utf8',body_sha256='Utf8',parser='Utf8',reason='Utf8',supersedes='Utf8')
    files=unreadable_snapshot.files()
    inputs.append(dict(name='unreadable',kind='json_lines',files=files,
        schema=dict(fields=[field(k,v) for k,v in schema.items()],metadata={})) if files
        else json_input(scope_work,'unreadable',[],**schema))
    observed=run_job(scope_work,engine,inputs=inputs,steps=[
        dict(name='reconsidered_shas',materialize=True,sql='''
            SELECT decode(u.body_sha256,'hex') AS body_sha FROM unreadable u
            WHERE u.parser='html_metadata' AND u.body_sha256 IS NOT NULL
                AND coalesce(u.reason,'')<>'withdrawn'
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
    def admit(scoped,name):
        return readings.run(engine=engine,work=work/name,mode='daily',execute=False,
            max_work_items=spec['max_work_items'],existing=scoped/'readings.parquet',
            captures=scoped/'captures.parquet',unreadable_files=unreadable_snapshot.files(),
            decided_at=spec['decided_at'],parser='html_metadata',**source)
    try:
        planned=admit(scoped,'admission');pending=planned['work_list']
        known,unknown=_stored_bytes(pending)
        # An unknown size may be anything once custody learns it: read it alone (ct-hiec).
        over=known>scope['max_stored_bytes'] or (unknown and planned['work_items']>1)
    except readings.BackfillRequired as error:
        pending=error.report['work_list'];over=True
    if over:
        details['carried']=_carry_html_metadata(pending,scoped,
            spec['max_work_items'],scope['max_stored_bytes'],engine=engine,work=work/'carry')
        scoped=work/'carry'
        # The narrowed scope holds at most max_work_items bodies, so this plan cannot exceed it.
        planned=admit(scoped,'admitted')
    listing=None
    if _listed_reads(spec,raw_store):
        custody=_listed_custody(spec,engine,raw_store,
            dict(captures=scoped/'captures.parquet',readings=scoped/'readings.parquet'),
            planned,None,unreadable_snapshot,work/'custody',parser='html_metadata')
        planned=custody['planned'];listing=custody['listing']
        if planned['raw_custody']['missing_pins'] or planned['raw_custody']['conflicts']:
            raise readings.RawCustodyRequired(planned)
    stored_bytes,missing_sizes=_stored_bytes(planned['work_list'])
    budget=dict(work_items=planned['work_items'],max_work_items=spec['max_work_items'],
        stored_bytes=stored_bytes,missing_sizes=missing_sizes,max_stored_bytes=scope['max_stored_bytes'])
    details['budget']=budget
    if missing_sizes or (stored_bytes>scope['max_stored_bytes'] and planned['work_items']>1):
        # The generic nightly backfill fallback cannot repair this scoped byte budget. One body
        # past it is read alone (at most MAX_STORED_BYTES, as _batches allows), so it cannot block.
        return dict(status='derived_budget_required',parser='html_metadata',
            parser_version=readings.current_version('html_metadata'),batches=[],**details)
    current=tables.resolve_tables(engine=engine,catalog_root=spec['catalog_root'],work=work/'admitted-heads',
        tables={name:spec['tables'][name] for name in ('captures','readings')})
    if current!={name:heads[name] for name in current}:
        raise ValueError('Derived captures or readings head changed during admission')
    source=_body_source(spec,raw_store,work/'readings',listing)
    if _listed_reads(spec,raw_store):source['captured_copies']=listing is None
    result=readings.run(engine=engine,work=work/'readings',mode='backfill',execute=True,
        batch_size=spec['max_work_items'],batch_bytes=scope['max_stored_bytes'],
        table=spec['tables']['readings'],catalog_root=spec['catalog_root'],
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

    _owe_records(producer_records, chain, base, decided_at=decided_at)
    stopped = None
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
    except BaseException as error:
        stopped = error
        raise
    finally:
        final = _finish_owed(producer_records, chain, base, report, stopped, authority=authority,
            work=work/'producer-heads', tables_spec=tables_spec, decided_at=decided_at)
    if final['captures'] != heads['captures']:
        raise ValueError('HTML metadata captures head changed during production')
    return dict(report, pins=final, unreadable=unreadable_snapshot.rows())


def _arrow_field_paths(dtype, prefix=''):
    out = set()
    if pa.types.is_struct(dtype):
        for f in dtype:
            path = f'{prefix}.{f.name}' if prefix else f.name
            out.add(path)
            out.update(_arrow_field_paths(f.type, path))
    elif pa.types.is_list(dtype) or pa.types.is_large_list(dtype):
        out.update(_arrow_field_paths(dtype.value_type, f'{prefix}[]'))
    return out


def _iceberg_field_paths(schema_obj, prefix=''):
    out = set()
    if isinstance(schema_obj, dict) and schema_obj.get('type') == 'struct':
        for f in schema_obj.get('fields', ()):
            name = f['name']
            path = f'{prefix}.{name}' if prefix else name
            out.add(path)
            if isinstance(f.get('type'), dict):
                out.update(_iceberg_field_paths(f['type'], path))
    elif isinstance(schema_obj, dict) and schema_obj.get('type') == 'list':
        element = schema_obj.get('element')
        if isinstance(element, dict):
            out.update(_iceberg_field_paths(element, f'{prefix}[]'))
    return out


def writer_field_paths(name):
    paths = _iceberg_field_paths(tables.load_schema(name))
    arrow_modules = {
        'filename_readings': (filenames, 'SCHEMA'),
        'meeting_records': (meeting_records, 'ARROW_SCHEMA'),
        'appearance_records': (appearance_records, 'ARROW_SCHEMA'),
        'committee_records': (committee_records, 'ARROW_SCHEMA'),
        'playlist_records': (playlist_records, 'ARROW_SCHEMA'),
        'video_records': (video_records, 'ARROW_SCHEMA'),
    }
    if name in arrow_modules:
        mod, attr = arrow_modules[name]
        paths |= _arrow_field_paths(pa.struct(getattr(mod, attr)))
    return paths


def _sql_lit(value):
    return "'" + str(value).replace("'", "''") + "'"


def _count_query(name, present_columns):
    from congress_api.lake import compatible_versions

    registry = compatible_versions.load_registry()

    def allowed_versions(parser_key, current):
        vals = {current, *(e['version'] for e in registry if e.get('parser') == parser_key and e.get('current') == current)}
        return ','.join(_sql_lit(v) for v in sorted(vals))

    if name == 'captures':
        if 'mapping_version' not in present_columns:
            return 'SELECT count(*) AS total_rows, 0 AS current_rows, count(*) AS stale_records FROM "captures"'
        allowed = allowed_versions('captures', captures.current_version())
        return (
            f'SELECT count(*) AS total_rows, '
            f'count(*) FILTER (WHERE mapping_version IN ({allowed})) AS current_rows, '
            f'count(*) FILTER (WHERE mapping_version IS NULL OR mapping_version NOT IN ({allowed})) AS stale_records '
            f'FROM "captures"'
        )
    if name == 'readings':
        if not {'body_sha', 'parser', 'parser_version'} <= present_columns:
            return 'SELECT count(*) AS total_rows, 0 AS current_rows, count(*) AS stale_records FROM "readings"'
        pins = compatible_versions.current_pins()
        terms = ' OR '.join(
            f'(parser={_sql_lit(p)} AND parser_version IN ({allowed_versions(p, ver)}))'
            for p, ver in sorted(pins.items()) if isinstance(ver, str)
        ) or 'false'
        return (
            f'WITH cur AS (SELECT DISTINCT body_sha, parser FROM "readings" WHERE {terms}), '
            f'all_keys AS (SELECT DISTINCT body_sha, parser FROM "readings") '
            f'SELECT (SELECT count(*) FROM "readings") AS total_rows, '
            f'(SELECT count(*) FROM "readings" WHERE {terms}) AS current_rows, '
            f'(SELECT count(*) FROM all_keys LEFT ANTI JOIN cur '
            f'ON all_keys.body_sha = cur.body_sha AND all_keys.parser = cur.parser) AS stale_records'
        )
    if name == 'filename_readings':
        if not {'filename', 'source_url', 'catalog_version'} <= present_columns:
            return 'SELECT count(*) AS total_rows, 0 AS current_rows, count(*) AS stale_records FROM "filename_readings"'
        allowed = allowed_versions('filename_readings', filenames.current_version())
        return (
            f'WITH cur AS (SELECT DISTINCT filename, source_url FROM "filename_readings" WHERE catalog_version IN ({allowed})), '
            f'all_keys AS (SELECT DISTINCT filename, source_url FROM "filename_readings") '
            f'SELECT (SELECT count(*) FROM "filename_readings") AS total_rows, '
            f'(SELECT count(*) FROM "filename_readings" WHERE catalog_version IN ({allowed})) AS current_rows, '
            f'(SELECT count(*) FROM all_keys LEFT ANTI JOIN cur '
            f'ON all_keys.filename = cur.filename AND all_keys.source_url = cur.source_url) AS stale_records'
        )
    record_modules = {'meeting_records': meeting_records, 'appearance_records': appearance_records, **DAILY_CAPTURE_RECORDS}
    versions = record_modules[name].current_versions()
    if not ({'record_sha', 'source', 'parser_version'} <= present_columns and versions):
        return f'SELECT count(*) AS total_rows, 0 AS current_rows, count(*) AS stale_records FROM "{name}"'
    pred = ' OR '.join(
        f'(source={_sql_lit(s)} AND parser_version IN ({allowed_versions(f"{name}.{s}", v)}))'
        for s, v in sorted(versions.items())
    )
    return (
        f'WITH cur AS (SELECT DISTINCT record_sha, source FROM "{name}" WHERE {pred}), '
        f'all_keys AS (SELECT DISTINCT record_sha, source FROM "{name}") '
        f'SELECT (SELECT count(*) FROM "{name}") AS total_rows, '
        f'(SELECT count(*) FROM "{name}" WHERE {pred}) AS current_rows, '
        f'(SELECT count(*) FROM all_keys LEFT ANTI JOIN cur '
        f'ON all_keys.record_sha = cur.record_sha AND all_keys.source = cur.source) AS stale_records'
    )


def inspect_targets(tables_spec, *, engine, catalog_root, work, heads=None, include_counts=False, max_work_items=None):
    """Read target table schemas (and optional record counts) through the engine before writes."""
    work = Path(work)
    if heads is None:
        heads = tables.resolve_tables(engine=engine, work=work / 'heads', catalog_root=catalog_root, tables=tables_spec)
    inputs = [tables.table_input(name, head) for name, head in heads.items()]
    schema_dir = work / 'schemas'
    run_job(
        schema_dir, engine, inputs=inputs, steps=[],
        outputs=[
            parquet_output(schema_dir, name, f'SELECT * FROM "{name}" WHERE FALSE', list(tables.TABLE_SPECS[name]['primary_key']))
            for name in heads
        ],
    )
    schemas_out = {}
    present_by_table = {}
    for name, head in heads.items():
        actual = pq.read_schema(schema_dir / f'{name}.parquet')
        present_by_table[name] = set(actual.names)
        actual_paths = _arrow_field_paths(pa.struct(actual))
        expected_paths = writer_field_paths(name)
        missing = sorted(expected_paths - actual_paths)
        schemas_out[name] = dict(
            schema_id=head['schema_id'],
            snapshot=head['snapshot'],
            columns=[dict(name=f.name, type=str(f.type), nullable=bool(f.nullable)) for f in actual],
            compatible=not missing,
            missing_fields=missing,
        )
    counts_out = {}
    if include_counts:
        queries = [dict(name=name, sql=_count_query(name, present_by_table[name])) for name in heads]
        raw_counts = run_job(work / 'counts', engine, inputs=inputs, steps=[], outputs=[], queries=queries)
        for name in heads:
            row = raw_counts[name][0]
            stale = int(row['stale_records'])
            touch = stale if max_work_items is None else min(stale, int(max_work_items))
            counts_out[name] = dict(
                total_rows=int(row['total_rows']),
                current_rows=int(row['current_rows']),
                stale_records=stale,
                would_touch=touch,
            )
    return dict(heads=heads, target_schemas=schemas_out, record_counts=counts_out)


def verify_target_schemas(heads, *, engine, work):
    """Refuse before any producer-record write or body fetch if a target table lacks writer fields."""
    schemas = inspect_targets({}, engine=engine, catalog_root=None, work=work, heads=heads)['target_schemas']
    incompatible = {name: entry['missing_fields'] for name, entry in schemas.items() if not entry['compatible']}
    if incompatible:
        details = '; '.join(f'{name} missing {fields}' for name, fields in sorted(incompatible.items()))
        raise ValueError(f'Target lake table schema mismatch before write: {details}')


def produce_daily(spec,*,engine,raw_store,producer_records=None,verified_heads=None):
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
    head this run moves gets one, whether the run completes, stops or fails. If the run
    dies or the catalog cannot name its final heads, the records it owed stay pending
    beside the records and the next run's preflight writes them (_complete_owed).
    """
    work,provenance,identities=_validate(spec,engine,raw_store)
    work.mkdir(parents=True,exist_ok=False)
    unreadable_snapshot=(UnreadableInventory.from_qualified(raw_store,qualified=provenance['unreadable'])
        if isinstance(raw_store.adapter,R2Adapter) else unreadable_inventory(raw_store,
            work=work/'unreadable-inventory',qualified=provenance['unreadable']))
    provenance['unreadable']=unreadable_snapshot.rows()
    authority=dict(engine=engine,catalog_root=spec['catalog_root'])
    if verified_heads is not None:
        heads=dict(verified_heads)
    else:
        heads=tables.resolve_tables(**authority,work=work/'initial-heads',tables=spec['tables'])
        verify_target_schemas(heads,engine=engine,work=work/'target-schemas')
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
    _owe_records(producer_records,chain,initial,decided_at=spec['decided_at'])
    stopped=None
    try:
        _produce(spec,engine,raw_store,work,provenance,identities,unreadable_snapshot,authority,heads,versions,report)
    except BaseException as error:
        stopped=error
        raise
    finally:
        _finish_owed(producer_records,chain,initial,report,stopped,authority=authority,
            work=work/'producer-heads',tables_spec=spec['tables'],decided_at=spec['decided_at'])
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
    staged_parquet=None if stage is None else stage/'captures.parquet'
    if _listed_reads(spec,raw_store):
        try:
            custody=_listed_custody(spec,engine,raw_store,heads,backlog,staged_parquet,
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
        scoped_captures,scoped_readings=custody['scoped_captures'],custody['scoped_readings']
    else:
        scoped=_scope_daily_inputs(heads,backlog,staged_parquet,engine=engine,
            output_dir=work/'readings-scope',job_dir=work/'readings-scope/job')
        scoped_captures,scoped_readings=scoped['captures'],scoped['readings']
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
                current_readings=tables.resolve_tables(**authority,work=work/'readings-admitted-head',
                    tables={'readings':spec['tables']['readings']})['readings']
                if current_readings!=heads['readings']:
                    raise ValueError('Readings head changed during daily admission')
                passes[step]=readings.run(engine=engine,work=work/step,mode='daily',execute=True,
                    max_work_items=spec['max_work_items'],table=spec['tables']['readings'],parser=name,
                    catalog_root=spec['catalog_root'],unreadable_store=raw_store,
                    captures=scoped_captures,read_current=lambda **_:scoped_readings,
                    **_body_source(spec,raw_store,work/step,listing),
                    decided_at=spec['decided_at'],unreadable_snapshot=unreadable_snapshot)
        except readings.BackfillRequired as error:
            report.update(status='backfill_required');report['producerreports'][step]=error.as_dict()
            return report
        except readings.RawCustodyRequired as error:
            report.update(status='raw_custody_required');report['producerreports'][step]=error.as_dict()
            return report
        report['producerreports'][step]=passes[step]
        if passes[step].get('carried',{}).get('bodies'):report.setdefault('carried',{})[step]=passes[step]['carried']
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
    routed_readings=readings_head
    if 'meeting_records' in spec['tables'] and 'appearance_records' in spec['tables']:
        from congress_api.lake._record_producer import ROUTES
        from congress_api.retention.provenance import parquet_output,run_job
        routed_parsers=sorted({p for entries in ROUTES.values() for _,_,p,_ in entries if p})
        routed_list=','.join("'"+p.replace("'","''")+"'" for p in routed_parsers)
        routed_dir=work/'routed-readings';routed_dir.mkdir(parents=True,exist_ok=False)
        run_job(routed_dir,engine,inputs=[tables.table_input('readings',readings_head)],steps=[],
            outputs=[parquet_output(routed_dir,'readings',
                f'SELECT * FROM readings WHERE parser IN ({routed_list})',readings.PK)])
        routed_readings=routed_dir/'readings.parquet'
    if 'meeting_records' in spec['tables']:
        meeting_head=tables.resolve_tables(**authority,work=work/'meeting-head',
            tables={'meeting_records':spec['tables']['meeting_records']})['meeting_records']
        try:
            meetings_staged=meeting_records.stage(captures=heads['captures'],existing=meeting_head,engine=engine,
                work=work/'meeting-records',local_root=spec.get('local_root'),raw_store=raw_store,
                unreadable_files=unreadable_snapshot.files(),max_work_items=spec['max_work_items'],
                decided_at=spec['decided_at'],unreadable_store=raw_store,readings=routed_readings)
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
                decided_at=spec['decided_at'],unreadable_store=raw_store,readings=routed_readings)
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
    capture,=pq.read_table(stages['captures'],
        columns=['receipt_key','mode','original_url','mapping_version']).to_pylist()
    names=pq.read_table(stages['filename_readings'],columns=filenames.PK).to_pylist()
    if (capture['receipt_key']!=prepared['receipt_key'] or capture['mode']!='retained_import'
            or capture['mapping_version']!=versions['captures']
            or [[row['filename'],row['source_url']] for row in names]!=prepared['filename_pairs']
            or any(row['source_url']!=capture['original_url'] or row['catalog_version']!=versions['filename_readings']
                   for row in names)):
        raise ValueError('Scoped recovery staged keys differ from the admitted receipt and filename')
    keys={'captures':['receipt_key'],'filename_readings':filenames.PK}

    def prove_delta(name,head,phase):
        _record_activation_step(producer_records,base[name],head,'Scoped recovery')
        columns=','.join(f'h."{c}"' for c in pq.read_schema(stages[name]).names)
        using=','.join(f'"{k}"' for k in keys[name])
        checks=run_job(attempt/f'verify-{phase}-{name}',engine,inputs=[
            tables.table_input('before_rows',base[name]),tables.table_input('after_rows',head),
            tables.table_input('incoming',stages[name])],steps=[dict(name='matching_rows',
                sql=f'SELECT {columns} FROM incoming i JOIN after_rows h USING ({using})',materialize=True)],
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
        _record_activation_file(prepared['stages'][name],'Scoped recovery')
        if name not in state['intents']:
            _supersede_owed(producer_records,heads[name],'scoped recovery')
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
        records.update(record({name:head}))
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
        if sum(path.stat().st_size for path in work.rglob('*') if path.is_file() and path.name!='engine.log')>max_output_bytes:
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
            _supersede_owed(producer_records,heads[name],label+' activation')
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
        final=_final_heads(authority,attempt/'final-heads',targets)
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
