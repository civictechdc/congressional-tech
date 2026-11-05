"""Refresh the three phase-one lake tables before building a daily release."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import time

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.lake import appearance_records,capture_staging,captures,committee_records,filenames,meeting_records,playlist_records,readings,tables
from congress_api.lake.producer_records import DAILY_JOB
from congress_api.lake.receipt_inventory import (LocalReceiptStore,R2ReceiptStore,copy_receipts,
    discover_receipts,select_receipts)
from congress_api.retention.writer_identity import writer_identity
from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter,validate_key
from congress_shared.storage import single_put_md5
from congress_api.retention.provenance import file_pin,instant,local_unreadable_inventory,run_job
from congress_api.retention.provenance_inventory import UnreadableInventory,unreadable_inventory
from congress_shared.custody import custody_identity,VerifiedFile


ROOT=Path(__file__).resolve().parents[5]
TABLE_NAMES=('captures','readings','filename_readings')
OPTIONAL_TABLE_NAMES=('meeting_records','appearance_records')
ALL_TABLE_NAMES=TABLE_NAMES+OPTIONAL_TABLE_NAMES
DAILY_CAPTURE_RECORDS={'committee_records':committee_records,'playlist_records':playlist_records}
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
    optional={'validated_counter','source_qualifications','vocabularies','body_inventory','local_root','receipt_families'}
    if not isinstance(spec,dict) or not required<=spec.keys() or spec.keys()-(required|optional):
        raise ValueError('Daily producer requires explicit receipt, body, table and provenance inputs')
    readings._positive(spec['max_work_items'],'max_work_items')
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


def _pending_backlog(spec,engine,raw_store,heads,unreadable_snapshot,work):
    """The readings work the current heads already hold, planned without opening a body.

    Candidacy never reads the body source, so an R2 run plans over the recorded copies
    before any listing exists. A head alone past the budget raises BackfillRequired.
    """
    source=(_body_source(spec,raw_store,work) if not _listed_reads(spec,raw_store)
            else dict(body_inventory=None,captured_copies=True,local_root=Path(work)/'unopened'))
    return readings.run(engine=engine,work=work,mode='daily',execute=False,max_work_items=spec['max_work_items'],
        existing=heads['readings'],captures=heads['captures'],unreadable_files=unreadable_snapshot.files(),
        decided_at=spec['decided_at'],**source)


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


def _listed_custody(spec,engine,raw_store,heads,backlog,stage,unreadable_snapshot,work):
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
        local_root=work/'unopened',decided_at=spec['decided_at'])
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


def _record_moved(records,chain,initial,*,authority,work,tables_spec,decided_at):
    """One record per table whose head moved during this run, written before returning."""
    final=tables.resolve_tables(**authority,work=work,tables=tables_spec)
    if writer_identity(ROOT,DAILY_JOB)['commit']!=chain['writer']['commit']:
        raise ValueError('Application commit changed during daily production')
    written={}
    for name,pin in sorted(final.items()):
        if pin==initial[name]:continue
        record=dict(version=1,input=name,selector=dict(kind='native_table',**pin),job=DAILY_JOB,
            commit=chain['writer']['commit'],lockfile_digest=chain['writer']['lockfile_digest'],decided_at=decided_at,
            base=dict(selector=dict(kind='native_table',**initial[name]),record=chain['bases'][name]))
        written[name]=records.write(record)
    return written


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
        report['producers']=_record_moved(producer_records,chain,initial,authority=authority,
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
    try:
        parsed=readings.run(engine=engine,work=work/'readings',mode='daily',execute=True,
            max_work_items=spec['max_work_items'],table=spec['tables']['readings'],
            catalog_root=spec['catalog_root'],unreadable_store=raw_store,
            captures=heads['captures'],**_body_source(spec,raw_store,work/'readings',listing),
            decided_at=spec['decided_at'],unreadable_snapshot=unreadable_snapshot)
    except readings.BackfillRequired as error:
        report.update(status='backfill_required');report['producerreports']['readings']=error.as_dict()
        return report
    except readings.RawCustodyRequired as error:
        report.update(status='raw_custody_required');report['producerreports']['readings']=error.as_dict()
        return report
    report['producerreports']['readings']=parsed
    versions.update(readings=parsed['parser_version'],parsers={p:readings.current_version(p)
        for p in ['sniff','html','xml','json']})
    imports=[batch['unreadable_provenance'] for batch in parsed['batches']]
    acknowledgements={batch['unreadable_provenance']['key']:batch['_unreadable_custody']
        for batch in parsed['batches'] if batch['unreadable_provenance'] is not None}
    if parsed['status']=='pending':
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
