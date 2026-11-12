"""Plan or execute the bounded archive lake backfill job."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from congress_api.lake.daily import ALL_TABLE_NAMES,DAILY_CAPTURE_RECORDS
from viewer_publication.archive_model_job import _local,provenance_record_kind

FIELDS={'version','bucket','catalog_root','work','tables','batch_size','max_batches'}
OPTIONAL={'engine_config','decided_at','max_work_items','body_inventory','receipt_inventory','local_root','selective','resume','through','producers','derived_parsers','derived_scopes'}
FILENAME_PRIOR_VERSION = '6528235b033633460b3a2f008adb4dba66f2fcfb82c0640caf90203e5e86f4f1'
FILENAME_ACT_CITATION_VERSION = 'c65e505ef8eb085e38072297aad395ca532fdc76a348a72b86f88c7734a83b09'


def _bucket(value):
    if not isinstance(value,str) or re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',value) is None:
        raise ValueError('Invalid archive bucket')
    return value


def _table_ref(value):
    if (not isinstance(value,dict) or set(value)!={'namespace','name'}
            or not isinstance(value['namespace'],list) or not value['namespace']
            or any(not isinstance(p,str) or not p for p in value['namespace'])
            or not isinstance(value['name'],str) or not value['name']):
        raise ValueError('Invalid lake table reference')
    return dict(namespace=list(value['namespace']),name=value['name'])


EXPLORER_TABLE_NAMES=('video_records','committee_records')


def _tables(value):
    core=set(ALL_TABLE_NAMES)
    if not isinstance(value,dict) or not core<=value.keys() or set(value)-core-set(DAILY_CAPTURE_RECORDS)-set(EXPLORER_TABLE_NAMES):
        raise ValueError('Backfill job requires all five archive lake table references and supported optional tables')
    if 'video_records' in value and 'committee_records' not in value:
        raise ValueError('Selective backfill video records require the committee records table')
    refs={name:_table_ref(value[name]) for name in value}
    if len({json.dumps(t,sort_keys=True) for t in refs.values()})!=len(refs):
        raise ValueError('Backfill tables must name distinct explicit targets')
    return refs


def require_no_derived(spec):
    """A private backfill catalog cannot inherit a qualified daily captures baseline."""
    from congress_api.lake.daily import derived_parsers
    if derived_parsers(spec) or spec.get('derived_scopes',{})!={}:
        raise ValueError('Backfill derived passes are unsupported; use the qualified scoped HTML producer or daily scope')


def load_spec(path):
    """Validate the committed backfill job specification without opening runtime or storage."""
    path=Path(path).resolve();value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):raise ValueError('Backfill job spec must be an object')
    require_no_derived(value)
    if value.get('status')=='blocked':
        if set(value)!={'status','reason'} or not isinstance(value.get('reason'),str) or not value['reason'].strip():
            raise ValueError('Blocked backfill job requires exactly its reason')
        return dict(value)
    if 'record_only' in value:
        from viewer_publication.archive_record_backfill import load_record_only
        return load_record_only(value,base=path.parent)
    if 'house_xml_disposition' in value:
        from viewer_publication.archive_house_xml_dispositions import load_dispositions
        return load_dispositions(value, base=path.parent)
    if 'house_xml_activation' in value:
        from viewer_publication.archive_house_xml_activation import load_activation
        return load_activation(value, base=path.parent)
    if 'house_xml_version_transition' in value:
        from viewer_publication.archive_house_xml_transition import load_transition
        return load_transition(value, base=path.parent)
    if 'filename_transition' in value:
        from viewer_publication.archive_model_job import _selector
        if set(value) != {'version', 'work', 'engine_config', 'filename_transition'} or value['version'] != 1:
            raise ValueError('Filename transition requires version 1, work and a local engine config')
        transition = value['filename_transition']
        if not isinstance(transition, dict) or set(transition) != {'base', 'engine_config'}:
            raise ValueError('Filename transition requires a pinned base and its read engine config')
        source = _selector(transition['base'], path.parent)
        if source['kind'] != 'native_table' or source['snapshot'] is None:
            raise ValueError('Filename transition requires an immutable native snapshot')
        return dict(value, work=_local(value['work'], path.parent), engine_config=_local(value['engine_config'], path.parent),
                    filename_transition=dict(base=source, engine_config=_local(transition['engine_config'], path.parent)))
    if set(value)-FIELDS-OPTIONAL or not FIELDS<=set(value):
        raise ValueError('Backfill job requires version 1 and all explicit fields')
    if type(value['version']) is not int or value['version']!=1:
        raise ValueError('Backfill job requires version 1')
    base=path.parent
    work=_local(value['work'],base)
    if any(char in work for char in '\r\n\0'):
        raise ValueError('Backfill work path cannot contain control characters')
    catalog_root=value['catalog_root']
    if catalog_root is not None:
        if not isinstance(catalog_root,str) or not catalog_root.strip():
            raise ValueError('Backfill catalog_root must be None or a non-empty string')
        uri=urlsplit(catalog_root)
        if not uri.scheme:catalog_root=_local(catalog_root,base)
    for field_name in ('batch_size','max_batches'):
        number=value[field_name]
        if type(number) is not int or number<=0:
            raise ValueError(f'Backfill {field_name} must be a positive integer')
    result=dict(
        version=1,
        bucket=_bucket(value['bucket']),
        catalog_root=catalog_root,
        work=work,
        tables=_tables(value['tables']),
        batch_size=value['batch_size'],
        max_batches=value['max_batches'],
    )
    if 'engine_config' in value and value['engine_config'] is not None:
        result['engine_config']=_local(value['engine_config'],base)
    if 'decided_at' in value and value['decided_at'] is not None:
        if not isinstance(value['decided_at'],str) or not value['decided_at'].strip():
            raise ValueError('Backfill decided_at must be a non-empty ISO timestamp')
        result['decided_at']=value['decided_at']
    if 'max_work_items' in value and value['max_work_items'] is not None:
        if type(value['max_work_items']) is not int or value['max_work_items']<=0:
            raise ValueError('Backfill max_work_items must be a positive integer')
        result['max_work_items']=value['max_work_items']
    if 'derived_parsers' in value:
        from congress_api.lake.daily import derived_parsers
        result['derived_parsers']=derived_parsers(value)
    if 'body_inventory' in value and value['body_inventory'] is not None:
        result['body_inventory']=_local(value['body_inventory'],base)
    if 'local_root' in value and value['local_root'] is not None:
        result['local_root']=_local(value['local_root'],base)
    if 'receipt_inventory' in value and value['receipt_inventory'] is not None:
        if not isinstance(value['receipt_inventory'],list) or any(not isinstance(item,dict) for item in value['receipt_inventory']):
            raise ValueError('Backfill receipt_inventory must be a list of objects')
        result['receipt_inventory']=list(value['receipt_inventory'])
    if 'resume' in value and type(value['resume']) is not bool:
        raise ValueError('Backfill resume must be boolean')
    result['resume']=value.get('resume',False)
    if 'selective' in value:
        from viewer_publication.archive_selective import validate_selective
        result['selective']=validate_selective(value['selective'],base=base,catalog_root=catalog_root,tables=result['tables'])
    elif result['resume'] or 'through' in value or set(result['tables'])-set(ALL_TABLE_NAMES)-set(DAILY_CAPTURE_RECORDS):
        raise ValueError('Only a selective backfill can resume, stop early or build the Explorer tables')
    if 'through' in value:
        from viewer_publication.archive_selective import THROUGH
        if value['through'] not in THROUGH:raise ValueError('Selective through must be tables or model')
        result['through']=value['through']
    if 'producers' in value:
        from viewer_publication.archive_publish_job import _metadata_pin
        if not isinstance(value['producers'],dict) or not value['producers']:
            raise ValueError('Backfill producers must map each anchored table to its record pin')
        result['producers']={name:_metadata_pin(pin,base) for name,pin in value['producers'].items()}
    elif catalog_root is None and 'selective' not in value:
        # Gate 5: a head this job moves without a record refuses every later publish.
        raise ValueError('A daily backfill of the R2 lake requires the producer anchors the publisher pins')
    return result


def _json_path(value):
    if isinstance(value,Path):return str(value)
    raise TypeError('Object of type '+type(value).__name__+' is not JSON serializable')


def _dumps(value):
    return json.dumps(value,sort_keys=True,default=_json_path)


def plan(spec, *, runtime_factory=None):
    require_no_derived(spec)
    if spec.get('status')=='blocked':return dict(spec)
    if 'record_only' in spec:
        return dict(status='planned',executed=False,work=spec['work'],**spec['record_only'])
    if 'house_xml_disposition' in spec:
        return dict(status='planned', executed=False, work=spec['work'], **spec['house_xml_disposition'])
    if 'house_xml_activation' in spec:
        return dict(status='planned', executed=False, work=spec['work'], **spec['house_xml_activation'])
    if 'house_xml_version_transition' in spec:
        return dict(status='planned', executed=False, work=spec['work'],
                    model_spec=spec['house_xml_version_transition'])
    if 'filename_transition' in spec:
        return dict(status='planned', executed=False, work=spec['work'],
                    base=spec['filename_transition']['base'], prior_version=FILENAME_PRIOR_VERSION,
                    catalog_version=FILENAME_ACT_CITATION_VERSION)
    planned=dict(
        status='planned',
        executed=False,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        tables=spec['tables'],
        batch_size=spec['batch_size'],
        max_batches=spec['max_batches'],
    )
    if 'selective' in spec:
        planned.update(where=spec['selective']['where'],base=spec['selective']['base'],resume=spec['resume'])
        return planned
    from tempfile import TemporaryDirectory
    from congress_api.lake.daily import inspect_targets, writer_field_paths
    from docspec_client.client import NativeDatasets, choose_runtime

    planned['writer_schemas'] = {name: sorted(writer_field_paths(name)) for name in spec['tables']}
    local_catalog = spec['catalog_root'] is not None and Path(spec['catalog_root']).exists()
    engine_config, _ = choose_runtime(spec.get('engine_config'), job_fallback=local_catalog)
    if isinstance(engine_config, str) and engine_config.strip():
        factory = runtime_factory or NativeDatasets.from_config
        with factory(engine_config) as engine:
            if (spec['catalog_root'] is None) == (getattr(engine, 'remote', None) is not None):
                engine.verify_runtime()
                max_items = spec.get('max_work_items', spec['batch_size'] * spec['max_batches'])
                with TemporaryDirectory(prefix='backfill-plan-') as temp:
                    inspected = inspect_targets(
                        spec['tables'], engine=engine, catalog_root=spec['catalog_root'],
                        work=temp, include_counts=True, max_work_items=max_items,
                    )
                planned['target_schemas'] = inspected['target_schemas']
                planned['record_counts'] = inspected['record_counts']
    return planned


def _verify_filename_transition(base_path, result_path, replacements, predicate):
    """Check all output pairs, untouched values and selected replacements in sorted order."""
    from itertools import pairwise
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    selected, rows, previous_key = 0, 0, None
    with pq.ParquetFile(base_path) as before, pq.ParquetFile(result_path) as after:
        for old, new in zip(before.iter_batches(), after.iter_batches(), strict=True):
            keys = ('filename', 'source_url')
            key_rows = list(zip(*(new.column(key).to_pylist() for key in keys)))
            if (previous_key is not None and previous_key >= key_rows[0]
                    or any(a >= b for a, b in pairwise(key_rows))
                    or not old.select(keys).equals(new.select(keys))):
                raise ValueError('Filename transition changed or duplicated source pairs')
            previous_key = key_rows[-1]
            if not pc.all(pc.equal(new.column('catalog_version'), FILENAME_ACT_CITATION_VERSION), skip_nulls=False).as_py():
                raise ValueError('Filename transition wrote an unexpected catalog version')
            mask = pc.match_substring_regex(old.column('filename'), predicate)
            keep = pc.invert(mask)
            columns = [name for name in old.schema.names if name != 'catalog_version']
            if not old.filter(keep).select(columns).equals(new.filter(keep).select(columns)):
                raise ValueError('Filename transition changed values outside its predicate')
            recomputed = new.filter(mask)
            expected = replacements.slice(selected, recomputed.num_rows)
            if recomputed.to_pylist() != expected.to_pylist():
                raise ValueError('Filename transition lost or changed a recomputed row')
            selected += recomputed.num_rows
            rows += new.num_rows
    if selected != replacements.num_rows:
        raise ValueError('Filename transition did not preserve every recomputed row')
    return dict(rows=rows, reused=rows - selected, recomputed=selected)


def _filename_transition(spec, runtime_factory):
    """Advance the reviewed Act-citation change using one read-only snapshot and a fresh local lake."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from congress_api.lake import filenames, tables
    from congress_api.retention.provenance import file_pin, parquet_output, run_job
    from congress_api.retention.writer_identity import writer_identity
    from docspec_client.client import NativeDatasets
    from house_naming.extraction import ACT_CITATION
    from viewer_publication.producer_proof import BACKFILL, ROOT, record

    if filenames.current_version() != FILENAME_ACT_CITATION_VERSION:
        raise ValueError('Filename transition only supports the reviewed Act citation version')
    writer = writer_identity(ROOT, BACKFILL)
    runtime_factory = runtime_factory or NativeDatasets.from_config
    source = spec['filename_transition']
    base = {k: v for k, v in source['base'].items() if k != 'kind'}
    work = Path(spec['work'])
    catalog = work / 'catalog'
    target = dict(namespace=['filename_transition'], name='filename_readings')
    with runtime_factory(spec['engine_config']) as engine, runtime_factory(source['engine_config']) as reader:
        tables.validate_catalog_authority(engine, catalog)
        engine.verify_runtime()
        reader.verify_runtime()
        if (reader.source_revision, reader.binary_sha256) != (engine.source_revision, engine.binary_sha256):
            raise ValueError('Filename transition requires the same pinned read and write engine')
        work.mkdir(parents=True, exist_ok=False)
        exported = work / 'base'
        base_path = exported / 'filename-readings.parquet'
        counts = run_job(exported, reader, inputs=[tables.table_input('base', base)], steps=[],
            outputs=[parquet_output(exported, 'filename-readings',
                f"SELECT * FROM base WHERE catalog_version = '{FILENAME_PRIOR_VERSION}'", filenames.PK)],
            queries=[dict(name='versions', sql=f"""SELECT count(*) AS total,
                count(*) FILTER (WHERE catalog_version IS DISTINCT FROM '{FILENAME_PRIOR_VERSION}') AS other
                FROM base""")])['versions'][0]
        if not counts['total'] or counts['other']:
            raise ValueError('Filename transition base must have only the reviewed prior version')

        predicate = ACT_CITATION.pattern
        parser = filenames._parser()
        replacements = []
        with pq.ParquetFile(base_path) as inputs:
            for batch in inputs.iter_batches(columns=filenames.PK[:2]):
                selected = batch.filter(pc.match_substring_regex(batch.column('filename'), predicate))
                replacements.extend(filenames.read_filename(row['filename'], row['source_url'],
                    parser=parser, catalog_version=FILENAME_ACT_CITATION_VERSION) for row in selected.to_pylist())
        if not replacements:
            raise ValueError('Filename transition selected no source pairs')
        new_rows = pa.Table.from_pylist(replacements, schema=filenames.SCHEMA)
        changed = work / 'recomputed.parquet'
        pq.write_table(new_rows, changed)

        filenames.create_table(engine=engine, work=work / 'create', catalog_root=catalog,
                               table=target, location=work / 'lake', create_namespace=True)
        columns = ','.join(f"'{FILENAME_ACT_CITATION_VERSION}' AS catalog_version" if name == 'catalog_version'
                           else name for name in filenames.SCHEMA.names)
        identity = file_pin(base_path)['sha256'] + ':' + file_pin(changed)['sha256']
        operation = dict(kind='append', name='append', table=target, current_table='existing', work_table='pending',
            sql=f"SELECT {columns} FROM base WHERE NOT regexp_like(filename, '{predicate}') UNION ALL SELECT * FROM changed",
            identity_sql=f"SELECT '{identity}' AS identity", layout=tables.PART_LAYOUT)
        tables._job(engine, work / 'append', catalog_root=catalog,
                    inputs=[tables.table_input('base', base_path), tables.table_input('changed', changed)], operations=[operation])
        pin = tables.resolve_tables(engine=engine, work=work / 'head', catalog_root=catalog,
                                   tables={'filename_readings': target})['filename_readings']
        checked = work / 'check'
        run_job(checked, engine, inputs=[tables.table_input('result', pin)], steps=[],
            outputs=[parquet_output(checked, 'filename-readings', 'SELECT * FROM result', filenames.PK)])
        proof = _verify_filename_transition(base_path, checked / 'filename-readings.parquet', new_rows, predicate)
        if proof['rows'] != counts['total'] or writer != writer_identity(ROOT, BACKFILL):
            raise ValueError('Filename transition source count or writer identity changed')

    selector = dict(kind='native_table', **pin)
    report = dict(status='tables_built', executed=True, base=source['base'], selector=selector, predicate=predicate,
                  prior_version=FILENAME_PRIOR_VERSION, catalog_version=FILENAME_ACT_CITATION_VERSION, **proof,
                  source_export=file_pin(base_path), recomputed_file=file_pin(changed))
    report_path = work / 'filename-transition.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    producer_path = work / 'filename_readings.json'
    producer = record(producer_path, input='filename_readings', selector=selector, job=BACKFILL)
    producer.update(recorded='with production', reused_rows=proof['reused'], appended=proof['recomputed'],
                    filename_transition=dict(path=str(report_path), **file_pin(report_path)))
    producer_path.write_text(json.dumps(producer, indent=1, sort_keys=True) + '\n')
    return dict(report, producer=dict(path=str(producer_path), **file_pin(producer_path)))


def execute(spec,*,runtime_factory=None,storage_factory=None,producer=None,activation_lock_fd=None):
    """Run bounded lake backfill batches against the configured remote runtime and raw store."""
    require_no_derived(spec)
    if spec.get('status')=='blocked':return dict(spec)
    if 'record_only' in spec:
        from viewer_publication.archive_record_backfill import execute_record_only
        return execute_record_only(spec,runtime_factory=runtime_factory)
    if 'house_xml_disposition' in spec:
        from viewer_publication.archive_house_xml_dispositions import execute_dispositions
        return execute_dispositions(spec, runtime_factory=runtime_factory)
    if 'house_xml_activation' in spec:
        from viewer_publication.archive_house_xml_activation import execute_activation
        return execute_activation(spec, runtime_factory=runtime_factory, storage_factory=storage_factory, lock_fd=activation_lock_fd)
    if 'house_xml_version_transition' in spec:
        from viewer_publication.archive_house_xml_transition import execute_transition
        return execute_transition(spec, runtime_factory=runtime_factory)
    if 'filename_transition' in spec:
        return _filename_transition(spec, runtime_factory)
    if 'selective' in spec:
        from viewer_publication.archive_selective import execute_selective
        return execute_selective(spec,runtime_factory=runtime_factory)
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():
        raise ValueError('Backfill work directory must be fresh')
    import sys
    from tempfile import TemporaryDirectory
    from congress_api.lake import tables as lake_tables
    from congress_api.lake.daily import produce_daily, verify_target_schemas
    from congress_api.retention.body_store import BodyStore,R2Adapter
    from congress_api.retention.provenance_inventory import provenance_inventory
    from congress_api.retention.r2 import configure_read_retries
    from congress_shared.storage import connect_r2
    from docspec_client.client import NativeDatasets,choose_runtime,runtime_record
    engine_config,choice=choose_runtime(spec.get('engine_config'),job_fallback=True)
    if not isinstance(engine_config,str) or not engine_config.strip():
        raise ValueError('Backfill execution requires an explicit engine_config or DOCSPEC_RUNTIME_CONFIG')
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    check_targets=producer is None
    producer=producer or produce_daily
    decided_at=spec.get('decided_at') or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with runtime_factory(engine_config) as engine:
        ran=runtime_record(engine_config,choice,log=sys.stderr)
        engine.verify_runtime()
        if check_targets:
            with TemporaryDirectory(prefix='backfill-preflight-') as temp:
                heads=lake_tables.resolve_tables(
                    engine=engine, work=Path(temp)/'heads',
                    catalog_root=spec['catalog_root'], tables=spec['tables'],
                )
                verify_target_schemas(heads, engine=engine, work=Path(temp)/'schemas')
        # Body GETs retry transient R2 server errors and throttling; writes keep one attempt.
        client=configure_read_retries(storage_factory(bucket=spec['bucket'],retries={'total_max_attempts':1}))
        raw_store=BodyStore(R2Adapter(client,spec['bucket']))
        snapshot=provenance_inventory(raw_store,work=work/'provenance')
        decision_kinds=('recoveries','reviews','unreadable')
        records=snapshot.qualify(row['key'] for row in snapshot.metadata()
            if provenance_record_kind(row['key']) in decision_kinds)
        provenance={kind:[row for row in records if provenance_record_kind(row['key'])==kind]
            for kind in decision_kinds}
        daily_spec=dict(
            work=str(work/'producer'),
            decided_at=decided_at,
            catalog_root=spec['catalog_root'],
            tables=spec['tables'],
            receipt_inventory=spec.get('receipt_inventory',[]),
            max_work_items=spec.get('max_work_items',spec['batch_size']*spec['max_batches']),
            provenance=provenance,
            # A pinned inventory only if the spec names one; otherwise bodies come from raw_store.
            **{k:spec[k] for k in ('body_inventory','local_root') if spec.get(k) is not None},
        )
        records=None
        if 'producers' in spec:
            from congress_api.lake.producer_records import ProducerRecords
            from viewer_publication.archive_publish_job import _verify_metadata
            anchors={}
            for name,pin in spec['producers'].items():
                identity=_verify_metadata(pin);anchors[name]=Path(pin['path']).read_bytes();identity.require(pin['path'])
            records=ProducerRecords(anchors,client=client,bucket=spec['bucket'])
        production=producer(daily_spec,engine=engine,raw_store=raw_store,producer_records=records)
    work.mkdir(parents=True,exist_ok=True)
    report=dict(
        status='executed',
        executed=True,
        bucket=spec['bucket'],
        catalog_root=spec['catalog_root'],
        work=spec['work'],
        engine_config=engine_config,
        engine_runtime=ran,
        production=production,
    )
    (work/'backfill-report.json').write_text(_dumps(report)+'\n',encoding='utf-8')
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--activation-lock-fd',type=int,help=argparse.SUPPRESS)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',action='store_true')
    mode.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':
            print(_dumps(spec))
            return 2
        if args.activation_lock_fd is not None and ('house_xml_activation' not in spec or not args.execute):
            parser.error('activation-lock-fd requires an explicit House XML activation execution')
        result=execute(spec,activation_lock_fd=args.activation_lock_fd) if args.execute else plan(spec)
    except (ValueError,OSError) as error:
        parser.error(str(error))
    print(_dumps(result))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
