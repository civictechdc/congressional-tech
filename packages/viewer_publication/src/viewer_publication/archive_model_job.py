"""Plan or execute the maintained archive model over exact immutable inputs."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import UUID

from congress_api.retention.body_store import validate_key
from congress_api.retention.provenance import file_pin

TABLES=('captures','readings','filename_readings')
PROVENANCE={'recovery_files':'recoveries','review_files':'reviews','verification_files':'verification',
            'unreadable_files':'unreadable','variant_files':'url_variants'}
REQUIRED={'version','engine_config',*TABLES,'parser_versions','catalog_version','output','scratch'}


def _local(value,base):
    if not isinstance(value,str) or not value.strip() or urlsplit(value).scheme:
        raise ValueError('Expected an explicit local path')
    return str((base/value).resolve())


def _pin(value,fields):
    if not isinstance(value,dict) or set(value)!=fields:
        raise ValueError('Input selector requires exactly its declared immutable fields')
    if (not isinstance(value['sha256'],str) or re.fullmatch('[a-f0-9]{64}',value['sha256']) is None
            or type(value['size']) is not int or value['size']<0):
        raise ValueError('Input selector requires a SHA-256 and byte size pin')


def _selector(value,base):
    if not isinstance(value,dict):raise ValueError('A model input requires an immutable selector')
    if value.get('kind')=='parquet':
        _pin(value,{'kind','path','sha256','size'})
        return dict(value,path=_local(value['path'],base))
    if value.get('kind')!='native_table' or set(value)!={'kind','metadata_location','table_uuid','snapshot','schema_id'}:
        raise ValueError('Native input selector requires exact metadata, UUID, snapshot and schema')
    location=value['metadata_location']
    if not isinstance(location,str) or not location.strip():raise ValueError('Invalid native metadata selector')
    uri=urlsplit(location)
    if uri.scheme not in {'','file','s3'} or uri.query or uri.fragment or uri.username or uri.password:
        raise ValueError('Native metadata selector must not contain mutable lookup or credentials')
    if uri.scheme=='s3' and (not uri.netloc or not uri.path.strip('/')):
        raise ValueError('Invalid native metadata selector')
    try:UUID(value['table_uuid'])
    except (ValueError,AttributeError,TypeError):raise ValueError('Native selector requires a table UUID') from None
    if (type(value['schema_id']) is not int or value['schema_id']<0 or
            (value['snapshot'] is not None and (type(value['snapshot']) is not int or
             not -(1<<63)<=value['snapshot']<(1<<63)))):
        raise ValueError('Native selector requires an exact snapshot and schema ID')
    return dict(value,metadata_location=_local(location,base) if not uri.scheme else location)


def load_spec(path):
    """Read only the job description and current definitions, never input payloads."""
    path=Path(path).resolve();value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Model job spec must be an object')
    if value.get('status')=='blocked':
        if not isinstance(value.get('reason'),str) or not value['reason']:
            raise ValueError('Blocked model job requires its reason')
        return dict(status='blocked',reason=value['reason'])
    if set(value)-REQUIRED-PROVENANCE.keys():raise ValueError('Model job has unknown fields')
    if not REQUIRED<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Model job requires version 1 and all explicit inputs')
    base=path.parent
    result=dict(value,**{name:_selector(value[name],base) for name in TABLES})
    for name in ['engine_config','output','scratch']:result[name]=_local(value[name],base)
    output,scratch=Path(result['output']),Path(result['scratch'])
    if output.is_relative_to(scratch) or scratch.is_relative_to(output):
        raise ValueError('Model output and scratch must be separate fresh directories')
    for name,family in PROVENANCE.items():
        files=value.get(name,[])
        if not isinstance(files,list):raise ValueError('Pinned provenance inputs must be arrays')
        result[name]=[]
        for item in files:
            _pin(item,{'key','path','sha256','size'})
            key=item['key']
            if not isinstance(key,str) or not key.startswith('provenance/'+family+'/'):
                raise ValueError('Provenance pin has the wrong object family')
            validate_key(key)
            result[name].append(dict(item,path=_local(item['path'],base)))
    from congress_api.lake import readings,filenames
    current={name:readings.current_version(name) for name in ['sniff','html','xml','json']}
    if value['parser_versions']!=current:
        raise ValueError('Parser versions must match the current definitions')
    if value['catalog_version']!=filenames.current_version():
        raise ValueError('Catalog version must match the current definition')
    return result


def _check_pin(value):
    if file_pin(value['path'])!={name:value[name] for name in ['sha256','size']}:
        raise ValueError('Pinned model input changed: '+value['path'])


def model_arguments(spec):
    """Verify local pins and fresh destinations before opening the native runtime."""
    for name in ['output','scratch']:
        path=Path(spec[name])
        if path.exists() or path.is_symlink():raise ValueError('Model output and scratch must be fresh')
    arguments={}
    for name in TABLES:
        value=spec[name]
        if value['kind']=='parquet':
            _check_pin(value)
            arguments[name]=dict(kind='parquet',path=value['path'])
        else:arguments[name]=dict(value)
    for name in PROVENANCE:
        arguments[name]=[]
        for value in spec[name]:
            _check_pin(value)
            arguments[name].append({key:value[key] for key in ['key','path']})
    return arguments


def execute(spec):
    """Verify inputs, then invoke the one maintained model producer."""
    arguments=model_arguments(spec)
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import build_release
    with NativeDatasets.from_config(spec['engine_config']) as engine:
        manifest=build_release(**arguments,parser_versions=spec['parser_versions'],
            catalog_version=spec['catalog_version'],engine=engine,
            output=Path(spec['output']),scratch=Path(spec['scratch']))
    return dict(status='built',executed=True,release_id=manifest['release_id'],
        output=spec['output'],scratch=spec['scratch'],rows={entry['name']:entry['rows'] for entry in manifest['files']})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--plan',action='store_true');mode.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':
            print(json.dumps(spec,sort_keys=True));return 2
        result=(execute(spec) if args.execute else dict(status='planned',executed=False,
            inputs={name:spec[name] for name in TABLES},output=spec['output'],scratch=spec['scratch'],
            parser_versions=spec['parser_versions'],catalog_version=spec['catalog_version']))
    except (ValueError,OSError) as error:parser.error(str(error))
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
