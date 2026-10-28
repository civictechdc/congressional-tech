"""Refresh the three phase-one lake tables before building a daily release."""
import json
from pathlib import Path
import re

import pyarrow.parquet as pq

from congress_api.lake import captures,filenames,readings,tables
from congress_api.lake.receipt_inventory import select_receipts
from congress_api.retention.body_store import BodyStore,LocalAdapter,validate_key
from congress_api.retention.provenance import file_pin,instant,local_unreadable_inventory
from congress_shared.custody import custody_identity


TABLE_NAMES=('captures','readings','filename_readings')
PROVENANCE_KINDS=('recoveries','reviews','unreadable')
QUALIFIED_FIELDS={'key','etag','path','sha256','size'}


def _qualified(row,kind):
    if (not isinstance(row,dict) or set(row)!=QUALIFIED_FIELDS
            or not isinstance(row['key'],str) or not row['key'].startswith('provenance/'+kind+'/')
            or not isinstance(row['path'],str) or not Path(row['path']).is_absolute()
            or '..' in Path(row['path']).parts
            or not isinstance(row['sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None
            or type(row['size']) is not int or row['size']<0
            or (row['etag'] is not None and (not isinstance(row['etag'],str) or not row['etag']))):
        raise ValueError('Invalid qualified daily provenance')
    validate_key(row['key'])
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
    required={'work','decided_at','catalog_root','tables','receipt_inventory','body_inventory',
              'local_root','max_work_items','provenance'}
    optional={'validated_counter','source_qualifications','vocabularies'}
    if not isinstance(spec,dict) or not required<=spec.keys() or spec.keys()-(required|optional):
        raise ValueError('Daily producer requires explicit receipt, body, table and provenance inputs')
    readings._positive(spec['max_work_items'],'max_work_items')
    instant(spec['decided_at'])
    if any(not isinstance(spec[k],(str,Path)) or not str(spec[k])
           for k in ('work','body_inventory','local_root')):
        raise ValueError('Daily producer requires explicit work and body-cache paths')
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
    if (not isinstance(spec['tables'],dict) or set(spec['tables'])!=set(TABLE_NAMES)
            or any(not isinstance(t,dict) or set(t)!={'namespace','name'}
                or not isinstance(t['namespace'],list) or not t['namespace']
                or any(not isinstance(p,str) or not p for p in t['namespace'])
                or not isinstance(t['name'],str) or not t['name'] for t in spec['tables'].values())
            or len({json.dumps(t,sort_keys=True) for t in spec['tables'].values()})!=3):
        raise ValueError('Daily tables must name three distinct explicit targets')
    if not isinstance(spec['receipt_inventory'],list) or any(not isinstance(r,dict) for r in spec['receipt_inventory']):
        raise ValueError('Daily receipt inventory must contain original receipt metadata')
    if not isinstance(raw_store,BodyStore) or not isinstance(raw_store.adapter,LocalAdapter):
        raise ValueError('Daily producer requires a local durable raw inventory authority')
    tables.validate_catalog_authority(engine,spec['catalog_root'])
    if (not isinstance(spec['provenance'],dict) or set(spec['provenance'])!=set(PROVENANCE_KINDS)
            or any(not isinstance(v,list) for v in spec['provenance'].values())):
        raise ValueError('Daily provenance must explicitly name recoveries, reviews and unreadable')
    qualified={};identities={}
    for kind in PROVENANCE_KINDS:
        qualified[kind]=[];keys=set()
        for row in spec['provenance'][kind]:
            row,identity=_qualified(row,kind)
            if row['key'] in keys:raise ValueError('Duplicate daily provenance key')
            keys.add(row['key']);qualified[kind].append(row);identities[row['path']]=identity
    work=Path(spec['work']).resolve()
    if work.exists():raise FileExistsError('Daily producer requires a fresh work directory')
    return work,qualified,identities


def _input_files(rows):
    return [dict(key=row['key'],path=row['path']) for row in rows]


def _source_qualifications(spec,selected):
    bindings=spec.get('source_qualifications')
    if bindings is None or spec.get('validated_counter') is not None:return bindings
    paths={str(Path(row['path']).resolve()) for row in selected}
    return {key:value for key,value in bindings.items() if str(Path(key).resolve()) in paths}


def _final_provenance(initial,raw_store,imported,identities):
    result={kind:list(rows) for kind,rows in initial.items()}
    known={row['key']:row for row in result['unreadable']}
    imported={row['key']:row for row in imported if row is not None}
    for ref in local_unreadable_inventory(raw_store):
        if ref['key'] in known and known[ref['key']]['path']==ref['path']:continue
        if ref['key'] in imported:
            row=dict(imported[ref['key']],path=ref['path'])
            if Path(row['path']).stat().st_size!=row['size']:
                raise ValueError('Imported unreadable provenance changed')
            identities[row['path']]=custody_identity(row['path'])
        else:
            # Older imports not in the supplied snapshot are qualified once as
            # small provenance records; body bytes never enter this inventory.
            validate_key(ref['key'])
            observed,identity=_qualify_path(ref['path'])
            row=dict(ref,etag=None,**observed);identities[row['path']]=identity
        if ref['key'] in known and any(known[ref['key']][k]!=row[k] for k in ('sha256','size')):
            raise ValueError('Conflicting unreadable provenance inputs')
        known[ref['key']]=row
    result['unreadable']=sorted(known.values(),key=lambda r:r['key'])
    for path,identity in identities.items():
        if custody_identity(path)!=identity:raise ValueError('Daily provenance changed while producing')
    return result


def produce_daily(spec,*,engine,raw_store):
    """D1 then budgeted D2 then D3, returning fresh pins only after completion.

    Native jobs own table scans, joins, sorting and appends. Each producer builds
    one work list; parser workers persist for that list. Head lookups are batched
    at preflight/finalization, with required intermediate refreshes after writes.
    Local provenance discovery is O(U log U) in filenames per consumer; native
    key anti-joins and sorted appends retain their existing O(N+M)/O(K log K) cost.
    """
    work,provenance,identities=_validate(spec,engine,raw_store)
    work.mkdir(parents=True,exist_ok=False)
    authority=dict(engine=engine,catalog_root=spec['catalog_root'])
    heads=tables.resolve_tables(**authority,work=work/'initial-heads',tables=spec['tables'])
    versions=dict(captures=captures.current_version())
    report=dict(status='running',pins=None,receipt_keys=[],provenance=provenance,
                currentversions=versions,producerreports={})
    selected=select_receipts(spec['receipt_inventory'],heads['captures'],engine=engine,work=work/'receipt-selection')
    if selected:
        stage=captures.stage_captures(selected,engine=engine,work=work/'captures',
            validated_counter=spec.get('validated_counter'),
            source_qualifications=_source_qualifications(spec,selected))
        manifest=json.loads((stage/'ingested-receipts.json').read_text())
        if manifest['mapping_digest']!=versions['captures']:
            raise ValueError('Captures producer changed during daily production')
        if not pq.ParquetFile(stage/'captures.parquet').metadata.num_rows:
            raise ValueError('Selected receipts produced no captures')
        appended=tables.append_rows(stage/'captures.parquet',**authority,work=work/'captures-append',
            table=spec['tables']['captures'],keys=['receipt_key'],definition=manifest['mapping_digest'])
        report['receipt_keys']=manifest['receipt_keys']
        report['producerreports']['captures']=dict(stage=str(stage),append=appended)
        heads.update(tables.resolve_tables(**authority,work=work/'captures-head',
            tables={'captures':spec['tables']['captures']}))
    else:report['producerreports']['captures']=dict(stage=None,append=None)
    try:
        parsed=readings.run(engine=engine,work=work/'readings',mode='daily',execute=True,
            max_work_items=spec['max_work_items'],table=spec['tables']['readings'],
            catalog_root=spec['catalog_root'],unreadable_store=raw_store,
            captures=heads['captures'],body_inventory=spec['body_inventory'],local_root=spec['local_root'],
            decided_at=spec['decided_at'],unreadable_files=_input_files(provenance['unreadable']))
    except readings.BackfillRequired as error:
        report.update(status='backfill_required');report['producerreports']['readings']=error.as_dict()
        return report
    report['producerreports']['readings']=parsed
    versions.update(readings=parsed['parser_version'],parsers={p:readings.current_version(p)
        for p in ['sniff','html','xml','json']})
    imports=[batch['unreadable_provenance'] for batch in parsed['batches']]
    if parsed['status']=='pending':
        report.update(status='pending',provenance=_final_provenance(provenance,raw_store,imports,identities))
        return report
    filename_head=tables.resolve_tables(**authority,work=work/'filename-head',
        tables={'filename_readings':spec['tables']['filename_readings']})['filename_readings']
    current_unreadable={r['key']:r for r in _input_files(provenance['unreadable'])}
    current_unreadable.update({r['key']:r for r in local_unreadable_inventory(raw_store)})
    names=filenames.stage(captures=heads['captures'],existing=filename_head,engine=engine,
        work=work/'filenames',decided_at=spec['decided_at'],vocabularies=spec.get('vocabularies'),
        recovery_files=_input_files(provenance['recoveries']),unreadable_files=list(current_unreadable.values()),
        unreadable_store=raw_store)
    names['append']=(filenames.append(names,**authority,work=work/'filenames-append',
        table=spec['tables']['filename_readings']) if pq.ParquetFile(names['readings']).metadata.num_rows else None)
    imports.append(names['unreadable_provenance'])
    report['producerreports']['filename_readings']=names;versions['filename_readings']=names['catalog_version']
    report['provenance']=_final_provenance(provenance,raw_store,imports,identities)
    final=tables.resolve_tables(**authority,work=work/'final-heads',tables=spec['tables'])
    if final['captures']!=heads['captures']:
        raise ValueError('Current captures head changed after daily parser work; rerun from fresh heads')
    if (captures.current_version()!=versions['captures']
            or filenames.current_version(vocabularies=spec.get('vocabularies'))!=versions['filename_readings']
            or {p:readings.current_version(p) for p in versions['parsers']}!=versions['parsers']
            or readings.bundle_version(versions['parsers'],policy=readings.worker_limits())!=versions['readings']):
        raise ValueError('Daily producer definitions changed during execution')
    report['pins']=final
    report['status']='completed'
    return report
