"""Plan or execute the maintained archive model over exact immutable inputs."""
import argparse
from contextlib import contextmanager
from collections.abc import Mapping
from hashlib import md5
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import re
from urllib.parse import urlsplit
from uuid import UUID

from congress_api.retention.body_store import validate_key
from congress_api.retention.derived_files import file_identity, check_identity, retain_verified_file
from congress_shared.custody import custody_identity,VerifiedFile

TABLES=('captures','readings','filename_readings')
PROVENANCE={'recovery_files':'recoveries','review_files':'reviews','verification_files':'verification',
            'unreadable_files':'unreadable','variant_files':'url_variants'}
REQUIRED={'version','engine_config',*TABLES,'parser_versions','catalog_version','output','scratch'}


def provenance_record_kind(key):
    """Recognize model records; other raw provenance remains identity metadata."""
    parts=key.split('/') if isinstance(key,str) else []
    if (len(parts)==3 and parts[0]=='provenance' and parts[1] in PROVENANCE.values()
            and parts[2].endswith('.jsonl') and parts[2][:-6]):
        return parts[1]
    return None


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
    return validate_spec(value,base=path.parent)


def validate_spec(value,*,base):
    """Apply the same selector and definition checks to file or daily inputs."""
    if not isinstance(value,dict):raise ValueError('Model job spec must be an object')
    if value.get('status')=='blocked':
        if not isinstance(value.get('reason'),str) or not value['reason']:
            raise ValueError('Blocked model job requires its reason')
        return dict(status='blocked',reason=value['reason'])
    if set(value)-REQUIRED-PROVENANCE.keys():raise ValueError('Model job has unknown fields')
    if not REQUIRED<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Model job requires version 1 and all explicit inputs')
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
            if provenance_record_kind(key)!=family:
                raise ValueError('Expected a provenance record of the declared object family')
            validate_key(key)
            result[name].append(dict(item,path=_local(item['path'],base)))
    from congress_api.lake import readings,filenames
    current={name:readings.current_version(name) for name in ['sniff','html','xml','json']}
    if value['parser_versions']!=current:
        raise ValueError('Parser versions must match the current definitions')
    if value['catalog_version']!=filenames.current_version():
        raise ValueError('Catalog version must match the current definition')
    return result


def provenance_etag_md5(etag):
    """Normalize the stored-byte checksum of a single-PUT provenance object."""
    if isinstance(etag,str) and etag.startswith('"') and etag.endswith('"'):
        etag=etag[1:-1]
    if not isinstance(etag,str) or re.fullmatch('[a-fA-F0-9]{32}',etag) is None:
        raise ValueError('Provenance ETag must be a single-PUT MD5')
    return etag.lower()


@contextmanager
def model_arguments(spec, *, provenance_etags=None,verified_files=None):
    """Hold verified local inputs until native consumption completes successfully.

    The retained names prevent original-path replacement from selecting new bytes.
    Custody checks on exit reject in-place changes before the caller accepts output.
    One physical file has one verification and one retained name, including aliases.
    """
    for name in ['output','scratch']:
        path=Path(spec[name])
        if path.exists() or path.is_symlink():raise ValueError('Model output and scratch must be fresh')
    if verified_files is None:verified_files={}
    if not isinstance(verified_files,Mapping):raise ValueError('Verified input custody must be a path mapping')
    etags=None
    if provenance_etags is not None:
        keys={value['key'] for name in PROVENANCE for value in spec[name]}
        if not isinstance(provenance_etags,Mapping) or set(provenance_etags)!=keys:
            raise ValueError('Selected provenance keys must exactly match their ETags')
        etags={}
        for key,etag in provenance_etags.items():
            etags[key]=provenance_etag_md5(etag)
    parent=Path(spec['scratch']).parent
    parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.'+Path(spec['scratch']).name+'-inputs-',dir=parent) as directory:
        retained={}

        def hold(value,expected_md5=None):
            path=Path(value['path'])
            identity=custody_identity(path)
            physical=identity[:2]
            expected=dict(sha256=value['sha256'],bytes=value['size'])
            key='Pinned model input changed: '+str(path)
            if physical in retained:
                source,verified=retained[physical]
                verified.require(verified.path)
                if identity!=source.custody:
                    raise ValueError('Verified catalog file custody changed: '+str(path))
                check_identity(verified,expected,key)
                if expected_md5 is not None and source.get('md5')!=expected_md5:
                    raise ValueError('Local provenance bytes differ from the selected ETag')
                return str(verified.path)
            verified=verified_files.get(str(path))
            if verified is not None:
                if not isinstance(verified,VerifiedFile):raise ValueError('Expected process-local verified input custody')
                verified.require(path)
            else:
                verified=file_identity(path,additional_hashes={'md5':md5} if expected_md5 is not None else None)
            check_identity(verified,expected,key)
            if expected_md5 is not None and verified.get('md5')!=expected_md5:
                raise ValueError('Local provenance bytes differ from the selected ETag')
            destination=Path(directory)/(str(len(retained))+'-'+path.name)
            owned=retain_verified_file(path,destination,expected=verified,key=key)
            retained[physical]=(verified,owned)
            return str(owned.path)

        arguments={}
        # Verify provenance first so any physical aliases share its one SHA/MD5 pass.
        for name in PROVENANCE:
            arguments[name]=[dict(key=value['key'],path=hold(value,None if etags is None else etags[value['key']]))
                             for value in spec[name]]
        for name in TABLES:
            value=spec[name]
            arguments[name]=(dict(kind='parquet',path=hold(value))
                             if value['kind']=='parquet' else dict(value))
        for _source,verified in retained.values():verified.require(verified.path)
        yield arguments
        for _source,verified in retained.values():verified.require(verified.path)


def execute(spec):
    """Verify inputs, then invoke the one maintained model producer."""
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import build_release
    with model_arguments(spec) as arguments:
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
