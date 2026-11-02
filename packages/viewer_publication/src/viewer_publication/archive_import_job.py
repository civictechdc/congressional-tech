"""Commit pinned Parquet files, unchanged, as fresh native lake table generations.

For inputs whose producer cannot be rerun, such as a release's retained inputs.
Each table is created empty, receives the file through the shared native append,
and is read back with native EXCEPT ALL in both directions before its pin is
reported. The writer definition records the caller's provenance, never a parser
version the rows did not come from. A failed table leaves an unselected
candidate; nothing is purged or retried here.

Cost per table: one file hash, one append (anti-join against an empty table,
expected O(N)) and one comparison (hash EXCEPT ALL, expected O(N+M)).
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.lake.daily import ALL_TABLE_NAMES
from viewer_publication.archive_backfill_job import _table_ref
from viewer_publication.archive_model_job import _local,_pin

FIELDS={'version','catalog_root','work','location','definition','provenance','tables'}
OPTIONAL={'engine_config','create_namespace'}
FILE_PIN={'path','sha256','size'}


def _file(value,base):
    _pin(value,FILE_PIN)
    return dict(value,path=_local(value['path'],base))


def load_spec(path):
    """Validate the job description without opening runtime, storage or payloads."""
    path=Path(path).resolve();value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or set(value)-FIELDS-OPTIONAL or not FIELDS<=set(value):
        raise ValueError('Import job requires version 1 and all explicit fields')
    if type(value['version']) is not int or value['version']!=1:
        raise ValueError('Import job requires version 1')
    base=path.parent
    catalog_root=value['catalog_root']
    if catalog_root is not None:
        if not isinstance(catalog_root,str) or urlsplit(catalog_root).scheme:
            raise ValueError('Import catalog_root must be None or a local path')
        catalog_root=_local(catalog_root,base)
    location=value['location']
    if not isinstance(location,str) or not location.strip() or location.endswith('/'):
        raise ValueError('Import location must be a root without a trailing slash')
    if catalog_root is not None:
        if urlsplit(location).scheme:raise ValueError('A local catalog requires a local location')
        location=_local(location,base)
    elif urlsplit(location).scheme!='s3':
        raise ValueError('A remote catalog requires an s3 location')
    if not isinstance(value['definition'],str) or not value['definition'].strip():
        raise ValueError('Import definition must name the rows\' real producer')
    if not isinstance(value['provenance'],dict) or not value['provenance']:
        raise ValueError('Import provenance must be a non-empty object')
    if 'create_namespace' in value and type(value['create_namespace']) is not bool:
        raise ValueError('Import create_namespace must be boolean')
    tables=value['tables']
    if not isinstance(tables,dict) or not tables or set(tables)-set(ALL_TABLE_NAMES):
        raise ValueError('Import tables must name archive lake tables')
    result={}
    for name,item in tables.items():
        if not isinstance(item,dict) or set(item)!={'source','schema','partition_spec','table'}:
            raise ValueError('Import table requires source, schema, partition_spec and table')
        if item['partition_spec'] is not None and not isinstance(item['partition_spec'],dict):
            raise ValueError('Import partition_spec must be None or an object')
        result[name]=dict(source=_file(item['source'],base),schema=_file(item['schema'],base),
            partition_spec=item['partition_spec'],table=_table_ref(item['table']))
    if len({json.dumps(t['table'],sort_keys=True) for t in result.values()})!=len(result):
        raise ValueError('Import tables must name distinct targets')
    spec=dict(version=1,catalog_root=catalog_root,work=_local(value['work'],base),location=location,
        definition=value['definition'],provenance=value['provenance'],tables=result,
        create_namespace=value.get('create_namespace',False))
    if value.get('engine_config') is not None:spec['engine_config']=_local(value['engine_config'],base)
    return spec


def _verified(item):
    """Refuse any changed source or schema file before the first effect."""
    from congress_api.retention.provenance import file_pin
    for key in ('source','schema'):
        if file_pin(item[key]['path'])!={k:item[key][k] for k in ('sha256','size')}:
            raise ValueError('Import '+key+' does not match its pin: '+item[key]['path'])
    return json.loads(Path(item['schema']['path']).read_text(encoding='utf-8'))


def plan(spec):
    return dict(status='planned',executed=False,catalog_root=spec['catalog_root'],location=spec['location'],
        definition=spec['definition'],tables={name:dict(table=item['table'],source=item['source'])
            for name,item in spec['tables'].items()})


def execute(spec,*,runtime_factory=None):
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():raise ValueError('Import work directory must be fresh')
    schemas={name:_verified(item) for name,item in spec['tables'].items()}
    engine_config=(spec.get('engine_config') or os.environ.get('DOCSPEC_RUNTIME_CONFIG')
        or os.environ.get('DOCSPEC_JOB_CONFIG'))
    if not isinstance(engine_config,str) or not engine_config.strip():
        raise ValueError('Import execution requires engine_config or DOCSPEC_RUNTIME_CONFIG')
    from congress_api.lake.maintenance import verify_generations
    from congress_api.lake.tables import TABLE_SPECS,append_rows,create_table,validate_catalog_authority
    from docspec_client.client import NativeDatasets
    runtime_factory=runtime_factory or NativeDatasets.from_config
    work.mkdir(parents=True)
    report=dict(status='running',catalog_root=spec['catalog_root'],location=spec['location'],
        definition=spec['definition'],provenance=spec['provenance'],tables={})
    def save():(work/'import-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    with runtime_factory(engine_config) as engine:
        engine.verify_runtime()
        validate_catalog_authority(engine,spec['catalog_root'])
        report['engine']=dict(source_revision=engine.source_revision,binary_sha256=engine.binary_sha256)
        first=spec['create_namespace']
        for name,item in spec['tables'].items():
            table_work=work/name
            keys=list(TABLE_SPECS[name]['primary_key'])
            created=create_table(engine=engine,work=table_work/'create',catalog_root=spec['catalog_root'],
                table=item['table'],schema=schemas[name],location=spec['location']+'/'+item['table']['name'],
                create_namespace=first,partition_spec=item['partition_spec'])
            first=False
            appended=append_rows(item['source']['path'],engine=engine,work=table_work/'append',
                catalog_root=spec['catalog_root'],table=item['table'],keys=keys,definition=spec['definition'])
            pin=dict(kind='native_table',**{k:appended[k] for k in ('metadata_location','table_uuid','snapshot','schema_id')})
            entry=dict(table=item['table'],source=item['source'],schema=item['schema'],keys=keys,pin=pin,
                files=appended.get('files'),created=created.get('table_operations'),verified=False)
            report['tables'][name]=entry;save()
            verify_generations(dict(kind='parquet',**item['source']),pin,keys=keys,engine=engine,
                work=table_work/'verify',exact=False)
            entry['verified']=True;save()
    report['status']='executed';save()
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',action='store_true')
    mode.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        result=execute(spec) if args.execute else plan(spec)
    except (ValueError,OSError) as error:
        parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
