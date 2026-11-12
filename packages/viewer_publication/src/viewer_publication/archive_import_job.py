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
from viewer_publication.archive_backfill_job import EXPLORER_TABLE_NAMES,_table_ref
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
    if not isinstance(tables,dict) or not tables or set(tables)-set(ALL_TABLE_NAMES)-set(EXPLORER_TABLE_NAMES)-{'playlist_records','transcript_headings'}:
        raise ValueError('Import tables must name archive or Explorer lake tables')
    result={}
    for name,item in tables.items():
        if not isinstance(item,dict) or not {'source','schema','partition_spec','table'}<=set(item) or set(item)-{'source','schema','partition_spec','table','producer'}:
            raise ValueError('Import table requires source, schema, partition_spec and table (producer optional)')
        if item['partition_spec'] is not None and not isinstance(item['partition_spec'],dict):
            raise ValueError('Import partition_spec must be None or an object')
        result[name]=dict(source=_file(item['source'],base),schema=_file(item['schema'],base),
            partition_spec=item['partition_spec'],table=_table_ref(item['table']))
        # Gate 5: the record of the job that produced these rows (for example the selective
        # backfill's producers/<table>.json); the import's own record carries it as origin.
        if 'producer' in item:result[name]['producer']=_file(item['producer'],base)
    if len({json.dumps(t['table'],sort_keys=True) for t in result.values()})!=len(result):
        raise ValueError('Import tables must name distinct targets')
    spec=dict(version=1,catalog_root=catalog_root,work=_local(value['work'],base),location=location,
        definition=value['definition'],provenance=value['provenance'],tables=result,
        create_namespace=value.get('create_namespace',False))
    if value.get('engine_config') is not None:spec['engine_config']=_local(value['engine_config'],base)
    return spec


def _verified(name, item):
    """Refuse changed source, schema or origin evidence before the first effect."""
    from congress_api.retention.provenance import file_pin
    from viewer_publication.producer_proof import import_origin_problem
    for key in ('source','schema','producer'):
        if key in item and file_pin(item[key]['path'])!={k:item[key][k] for k in ('sha256','size')}:
            raise ValueError('Import '+key+' does not match its pin: '+item[key]['path'])
    if 'producer' in item:
        origin = json.loads(Path(item['producer']['path']).read_text(encoding='utf-8'))
        if problem := import_origin_problem(name, item['source'], origin):
            raise ValueError('Import producer refused: '+problem)
    return json.loads(Path(item['schema']['path']).read_text(encoding='utf-8'))


IMPORT_JOB='packages/viewer_publication/src/viewer_publication/archive_import_job.py'


def _writer(spec):
    """Gate 5 preflight/postflight: require a clean checkout and reachable origin commits."""
    import re
    from congress_api.retention.writer_identity import writer_identity
    from viewer_publication.producer_proof import IMPORT, PRODUCERS, ROOT, _git

    writer = writer_identity(ROOT, IMPORT_JOB)
    if _git(ROOT, 'cat-file', '-t', writer['commit']).returncode == 0:
        if _git(ROOT, 'cat-file', '-e', f"{writer['commit']}:{IMPORT_JOB}").returncode != 0:
            raise ValueError(f"Import job {IMPORT_JOB} is not checked in at {writer['commit'][:12]}")
        for name, item in spec['tables'].items():
            if 'producer' in item:
                origin = json.loads(Path(item['producer']['path']).read_text(encoding='utf-8'))
                origin_job = origin.get('job')
                if origin_job == IMPORT:
                    raise ValueError(f'Import {name} cannot name another import as its origin')
                if origin_job not in PRODUCERS.get(name, ()):
                    raise ValueError(f'Import {name} origin job {origin_job!r} is not a registered producer')
                commit = origin.get('commit')
                if (not isinstance(commit, str) or re.fullmatch('[0-9a-f]{40}', commit) is None
                        or _git(ROOT, 'merge-base', '--is-ancestor', commit, writer['commit']).returncode != 0):
                    raise ValueError(f'Import {name} origin commit {str(commit)[:12]} is not reachable from HEAD')
                if _git(ROOT, 'cat-file', '-e', f'{commit}:{origin_job}').returncode != 0:
                    raise ValueError(f'Import {name} origin job {origin_job!r} is not checked in at {commit[:12]}')
    return writer


def _producer_records(spec,report,work,writer):
    """Gate 5: one record per imported snapshot, naming this job and the commit that ran it.

    The import copies rows it did not produce, so a record is written only when the spec
    pins the origin record of the job that produced them; it is embedded (custody-checked
    against its pin) as `origin`. Rows were verified equal to the source both ways (EXCEPT
    ALL) before this step. Without an origin, nothing is written and gate 5 refuses that table.
    """
    from congress_api.retention.provenance import file_pin
    directory=work/'producers';directory.mkdir(exist_ok=True);out={}
    for name,entry in report['tables'].items():
        origin=spec['tables'][name].get('producer')
        if not entry.get('verified') or origin is None:
            out[name]=dict(unavailable='no verified copy' if not entry.get('verified') else 'no origin producer record was pinned')
            continue
        if file_pin(origin['path'])!={k:origin[k] for k in ('sha256','size')}:
            raise ValueError('Import origin producer record does not match its pin: '+origin['path'])
        record=dict(version=1,input=name,selector=entry['pin'],job=IMPORT_JOB,commit=writer['commit'],
            lockfile_digest=writer['lockfile_digest'],verified='EXCEPT ALL both ways against the source file',
            source=entry['source'],origin=dict(pin=origin,record=json.loads(Path(origin['path']).read_text())))
        path=directory/(name+'.json');path.write_text(json.dumps(record,indent=1,sort_keys=True)+'\n')
        out[name]=dict(path=str(path),**file_pin(path))
    return out


def plan(spec):
    return dict(status='planned',executed=False,catalog_root=spec['catalog_root'],location=spec['location'],
        definition=spec['definition'],tables={name:dict(table=item['table'],source=item['source'])
            for name,item in spec['tables'].items()})


def execute(spec,*,runtime_factory=None):
    work=Path(spec['work'])
    if work.exists() or work.is_symlink():raise ValueError('Import work directory must be fresh')
    schemas={name:_verified(name,item) for name,item in spec['tables'].items()}
    writer=_writer(spec)
    import sys
    from congress_api.lake.maintenance import verify_generations
    from congress_api.lake.tables import TABLE_SPECS,WRITER_PROFILES,_job,append_rows,create_table,validate_catalog_authority
    from docspec_client.client import NativeDatasets,choose_runtime,runtime_record
    engine_config,choice=choose_runtime(spec.get('engine_config'),job_fallback=True)
    if not isinstance(engine_config,str) or not engine_config.strip():
        raise ValueError('Import execution requires engine_config or DOCSPEC_RUNTIME_CONFIG')
    runtime_factory=runtime_factory or NativeDatasets.from_config
    report=dict(status='running',catalog_root=spec['catalog_root'],location=spec['location'],
        definition=spec['definition'],provenance=spec['provenance'],engine_config=engine_config,tables={})
    def save():(work/'import-report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    with runtime_factory(engine_config) as engine:
        report['engine_runtime']=runtime_record(engine_config,choice,log=sys.stderr)
        engine.verify_runtime()
        validate_catalog_authority(engine,spec['catalog_root'])
        work.mkdir(parents=True)
        report['engine']=dict(source_revision=engine.source_revision,binary_sha256=engine.binary_sha256)
        # One read-only head per target. A table left empty by an interrupted run
        # (created, append failed) is adopted; a table holding any snapshot is refused.
        # A local catalog that was never created holds no tables and cannot be opened.
        if spec['catalog_root'] is not None and not Path(spec['catalog_root']).exists():
            heads={name:{} for name in spec['tables']}
        else:
            heads={row['name']:row for row in _job(engine,work/'heads',catalog_root=spec['catalog_root'],
                operations=[dict(kind='resolve',name=name,table=item['table'])
                    for name,item in spec['tables'].items()])['table_operations']}
        if any(head.get('exists') and head.get('snapshot') is not None for head in heads.values()):
            raise ValueError('Import refuses a target table that already holds rows')
        report['adopted_empty']=sorted(name for name,head in heads.items() if head.get('exists'))
        first=spec['create_namespace'] and not report['adopted_empty']
        for name,item in spec['tables'].items():
            table_work=work/name
            keys=list(TABLE_SPECS[name]['primary_key'])
            created=None
            if not heads[name].get('exists'):
                created=create_table(engine=engine,work=table_work/'create',catalog_root=spec['catalog_root'],
                    table=item['table'],schema=schemas[name],location=spec['location']+'/'+item['table']['name'],
                    create_namespace=first,partition_spec=item['partition_spec'])['table_operations']
                first=False
            # A whole table in one append: the table's declared part layout, not the
            # small-batch default, keeps row-group metadata inside the writer allowance.
            layout=WRITER_PROFILES[TABLE_SPECS[name]['writer_profile']]['layout']
            appended=append_rows(item['source']['path'],engine=engine,work=table_work/'append',
                catalog_root=spec['catalog_root'],table=item['table'],keys=keys,definition=spec['definition'],
                **layout)
            pin=dict(kind='native_table',**{k:appended[k] for k in ('metadata_location','table_uuid','snapshot','schema_id')})
            entry=dict(table=item['table'],source=item['source'],schema=item['schema'],keys=keys,pin=pin,
                files=appended.get('files'),created=created,verified=False)
            report['tables'][name]=entry;save()
            verify_generations(dict(kind='parquet',**item['source']),pin,keys=keys,engine=engine,
                work=table_work/'verify',exact=False)
            entry['verified']=True;save()
    if _writer(spec)!=writer:
        raise ValueError('Import writer identity changed during execution')
    report['producers']=_producer_records(spec,report,work,writer);report['status']='executed';save()
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
