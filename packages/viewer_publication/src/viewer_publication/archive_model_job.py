"""Plan or execute the maintained archive model over exact immutable inputs.

A model-only build (no publish, pointer or upload) proves a model or engine change:
``--from-candidate <candidate> --build <fresh folder> --runtime <runtime.json>`` binds this
checkout's model to the completed daily a candidate holds, as the publisher binds it, and
keeps the spec, the runtime copy and its workspace, the ledger, output and scratch in the
build folder. ``--ledger``/``--ledger-base`` pass the retired-link ledger the publisher
passes, and ``--expect-release-id`` fails a control build that does not reproduce a release.
"""
import argparse
from contextlib import contextmanager
from collections.abc import Mapping
from hashlib import md5
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import sys
from urllib.parse import urlsplit
from uuid import UUID

from congress_api.retention.body_store import validate_key
from congress_api.retention.derived_files import file_identity, check_identity, retain_verified_file
from congress_shared.custody import custody_identity,VerifiedFile
from congress_shared.storage import single_put_md5 as provenance_etag_md5

TABLES=('captures','readings','filename_readings')
ENTITY_TABLES=('meeting_records','appearance_records')
# The Explorer tables (ct-gi01): with recording decisions they add meeting_coverage, videos,
# channels, recording_matches and committee_records. All three inputs or none.
EXPLORER_TABLES=('video_records','committee_records')
OPTIONAL_TABLES=(*ENTITY_TABLES,*EXPLORER_TABLES,'playlist_records')
OPTIONAL={*OPTIONAL_TABLES,'spicy_regs','recovery_requirements','text_index','historical_recording_matcher'}
PROVENANCE={'recovery_files':'recoveries','review_files':'reviews','verification_files':'verification',
            'unreadable_files':'unreadable','variant_files':'url_variants',
            'recording_decision_files':'recording_decisions'}
REQUIRED={'version','engine_config',*TABLES,'parser_versions','catalog_version','output','scratch'}
# The runtime fields that name files; the client resolves them against the runtime file.
RUNTIME_PATHS=('binary','workspace','remote','limits','credentials')
RELEASE_ID=re.compile('[a-f0-9]{12,64}')


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
    if set(value)-REQUIRED-PROVENANCE.keys()-OPTIONAL:raise ValueError('Model job has unknown fields')
    if not REQUIRED<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Model job requires version 1 and all explicit inputs')
    result=dict(value,**{name:_selector(value[name],base) for name in TABLES})
    if value.get('text_index') is not None:
        from viewer_publication.archive_text_index import validate_policy
        result['text_index']=validate_policy(value['text_index'],base)
    if value.get('historical_recording_matcher') is not None:
        matcher=value['historical_recording_matcher']
        _pin(matcher,{'path','sha256','size'})
        result['historical_recording_matcher']=dict(matcher,path=_local(matcher['path'],base))
    if value.get('recovery_requirements') is not None:
        requirement=value['recovery_requirements']
        _pin(requirement,{'path','sha256','size','acceptance_policy'})
        if not isinstance(requirement['acceptance_policy'],str) or not requirement['acceptance_policy'].strip():
            raise ValueError('Recovery requirements need a policy version')
        result['recovery_requirements']=dict(requirement,path=_local(requirement['path'],base))
    for name in OPTIONAL_TABLES:
        if value.get(name) is not None:
            result[name]=_selector(value[name],base)
    if value.get('spicy_regs') is not None:
        _pin(value['spicy_regs'],{'path','sha256','size'})
        result['spicy_regs']=dict(value['spicy_regs'],path=_local(value['spicy_regs']['path'],base))
    elif any(value.get(name) is not None for name in OPTIONAL_TABLES):
        raise ValueError('Entity inputs require pinned spicy-regs generations')
    explorer=[value.get(name) is not None for name in EXPLORER_TABLES]+[bool(value.get('recording_decision_files'))]
    if any(explorer) and not (all(explorer) and all(value.get(name) is not None for name in ENTITY_TABLES)):
        raise ValueError('Explorer tables require video_records, committee_records and recording decisions together, with the entity tables')
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
    from congress_api.lake import compatible_versions,filenames
    from viewer_publication.archive_model_profile import SELECTED_SOURCES,current_parser_versions
    pv=value.get('parser_versions')
    if not isinstance(pv,dict):
        raise ValueError('Parser versions must match the current definitions')
    for name in SELECTED_SOURCES:
        if value.get(name) is not None and name not in pv:
            raise ValueError(f'Model job with {name} requires pinned {name} parser_versions')
    if pv!=current_parser_versions(pv.keys()):
        raise ValueError('Parser versions must match the current definitions')
    # A stale or unproved compatible entry refuses here, before any input is opened.
    compatible_versions.load_registry()
    if value['catalog_version']!=filenames.current_version():
        raise ValueError('Catalog version must match the current definition')
    return result


def _spicy_arguments(pin,hold):
    """Read the pinned spicy-regs input and hold each table it binds to a stated generation.

    Each table path is ``generations/<family>/<digest>/<key>``, spicy-regs' own layout, so a
    table cannot be read under a generation other than the one its family states.
    """
    from viewer_publication.archive_model import SPICY_SCHEMAS,spicy_generations
    value=json.loads(Path(hold(pin)).read_text())
    if not isinstance(value,dict) or set(value)!={'version','source','generations','tables'} or value['version']!=1:
        raise ValueError('spicy-regs input requires version 1, its source, generations and tables')
    generations=spicy_generations(value['generations'])
    tables=value['tables']
    if not isinstance(tables,dict) or set(tables)!=set(SPICY_SCHEMAS):
        raise ValueError('spicy-regs input must pin every table: '+', '.join(sorted(SPICY_SCHEMAS)))
    base=Path(pin['path']).parent;held={}
    for name,table in sorted(tables.items()):
        _pin(table,{'family','key','path','sha256','size','rows'})
        if table['family'] not in generations or table['path']!=(
                f"generations/{table['family']}/{generations[table['family']]}/{table['key']}"):
            raise ValueError('spicy-regs table is not under its stated generation: '+name)
        held[name]=dict(kind='parquet',path=hold(dict(table,path=_local(table['path'],base))))
    return dict(generations=generations,tables=held)


@contextmanager
def model_arguments(spec, *, provenance_etags=None,verified_files=None,allow_existing_output=False):
    """Hold verified local inputs until native consumption completes successfully.

    The retained names prevent original-path replacement from selecting new bytes.
    Custody checks on exit reject in-place changes before the caller accepts output.
    One physical file has one verification and one retained name, including aliases.
    """
    for name in ['output','scratch']:
        path=Path(spec[name])
        if (path.exists() or path.is_symlink()) and not allow_existing_output:
            raise ValueError('Model output and scratch must be fresh')
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
        for name in OPTIONAL_TABLES:
            if spec.get(name) is not None:
                value=spec[name]
                arguments[name]=(dict(kind='parquet',path=hold(value))
                                 if value['kind']=='parquet' else dict(value))
        if spec.get('historical_recording_matcher') is not None:
            matcher=spec['historical_recording_matcher']
            arguments['historical_recording_matcher']=dict(matcher,path=hold(matcher))
        if spec.get('recovery_requirements') is not None:
            value=spec['recovery_requirements']
            arguments['recovery_requirements']=dict(value,path=hold(value))
        if spec.get('spicy_regs') is not None:
            arguments['spicy_regs']=_spicy_arguments(spec['spicy_regs'],hold)
        for _source,verified in retained.values():verified.require(verified.path)
        yield arguments
        for _source,verified in retained.values():verified.require(verified.path)


def bind_candidate(candidate,build,runtime):
    """Write ``<build>/model-spec.json`` for the completed daily a candidate holds; return its path.

    The binding is the publisher's resume path (``resume_daily_inputs``): the daily summary
    must match the digest sealed in the candidate's model intent, and completed_daily_inputs
    binds this checkout's template to its pins, catalog version and provenance records. It
    refuses, as the publisher does, a daily whose entity versions differ from this checkout's.
    A candidate is a copy, so each record is read from its own archive-daily-provenance; the
    pins check those bytes when the build holds them. The runtime is copied with its file paths
    made absolute and its workspace in the build; the credentials file is named, never opened.
    """
    # Imported here: archive_publish_job imports this module.
    from viewer_publication.archive_publish_job import ROOT,resume_daily_inputs
    candidate,build,runtime=Path(candidate).resolve(),Path(build).resolve(),Path(runtime).resolve()
    if build.exists() or build.is_symlink():raise ValueError('The build folder must be fresh: '+str(build))
    template=load_spec(ROOT/'model/jobs/publish-model.json')
    model=resume_daily_inputs(template,dict(work=str(candidate/'archive-daily')),
                               publish_work=candidate/'archive-publish')['model']
    held=candidate/'archive-daily-provenance'
    for name in PROVENANCE:
        model[name]=[dict(row,path=str(held/Path(row['path']).name)) for row in model[name]]
    missing=[Path(row['path']).name for name in PROVENANCE for row in model[name] if not Path(row['path']).is_file()]
    if missing:raise ValueError('Provenance file not in the candidate: '+', '.join(missing))
    settings=json.loads(runtime.read_text())
    if not isinstance(settings,dict):raise ValueError('Engine runtime must be an object: '+str(runtime))
    # archive_publish_job.publication_configuration resolves the same fields for its upload runtime.
    settings={name:_local(value,runtime.parent) if name in RUNTIME_PATHS else value for name,value in settings.items()}
    (build/'workspace').mkdir(parents=True)
    (build/'runtime.json').write_text(json.dumps(dict(settings,workspace=str(build/'workspace')),indent=1))
    path=build/'model-spec.json'
    path.write_text(json.dumps(dict(model,output=str(build/'archive-release'),scratch=str(build/'archive-model'),
                                    engine_config=str(build/'runtime.json')),indent=1,sort_keys=True))
    return path


def ledger_files(spec,*,ready=None,base=None):
    """The retired-link ledger the publisher passes, as (prior_links, base_retired) paths.

    ``ready`` holds the files a past publish wrote (its ``archive-publish/ledger``); ``base`` is
    a release folder carrying retired_links.parquet, derived beside the output by the same two
    release_gate calls the publisher's fetch_base makes. Neither: (None, None), an empty ledger.
    """
    if ready is not None:
        ready=Path(ready).resolve()
        for name in ('prior_links','prior_sources','base_retired'):
            if not (ready/(name+'.parquet')).is_file():raise ValueError(f'Ledger folder lacks {name}.parquet: {ready}')
        return ready/'prior_links.parquet',ready/'base_retired.parquet'
    if base is None:return None,None
    from viewer_publication.release_gate import prior_links,require_ledger_history
    require_ledger_history(base,[])
    folder=Path(spec['output']).parent/'ledger'
    if folder.exists() or folder.is_symlink():raise ValueError('The derived ledger folder must be fresh: '+str(folder))
    return prior_links(base,[],folder)


def execute(spec,*,prior_links=None,base_retired=None):
    """Verify inputs, then invoke the one maintained model producer.

    prior_links/base_retired are the retired-link ledger (ledger_files); without them the
    model's ledger starts empty, and every key the base had retired vanishes from the release.
    """
    from docspec_client.client import NativeDatasets
    from viewer_publication.archive_model import build_release
    engine_config=spec['engine_config']
    # One owner for this fallback and the publisher's copy is W5's (ct-64t4); a --from-candidate
    # build names the runtime copy in its build folder, so it never falls back.
    if not Path(engine_config).exists() and os.environ.get('DOCSPEC_RUNTIME_CONFIG'):
        engine_config=os.environ['DOCSPEC_RUNTIME_CONFIG']
    with model_arguments(spec) as arguments:
        with NativeDatasets.from_config(engine_config) as engine:
            manifest=build_release(**arguments,parser_versions=spec['parser_versions'],
                catalog_version=spec['catalog_version'],engine=engine,
                output=Path(spec['output']),scratch=Path(spec['scratch']),
                prior_links=prior_links,base_retired=base_retired)
    if spec.get('text_index'):
        from viewer_publication.archive_text_index import finish_text_index
        manifest=finish_text_index(spec,spec['output'])
    ledger=None if prior_links is None else dict(prior_links=str(prior_links),base_retired=str(base_retired))
    return dict(status='built',executed=True,release_id=manifest['release_id'],engine_config=engine_config,ledger=ledger,
        output=spec['output'],scratch=spec['scratch'],rows={entry['name']:entry['rows'] for entry in manifest['files']})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--spec',type=Path)
    source.add_argument('--from-candidate',type=Path,metavar='CANDIDATE',
        help='a completed daily candidate (archive-daily, archive-daily-provenance, archive-publish) to bind into --build')
    parser.add_argument('--build',type=Path,help='fresh folder for the spec, runtime copy, workspace, ledger, output and scratch')
    parser.add_argument('--runtime',type=Path,help='the engine runtime file the build copies, its workspace moved into --build')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--plan',action='store_true');mode.add_argument('--execute',action='store_true')
    ledger=parser.add_mutually_exclusive_group()
    ledger.add_argument('--ledger',type=Path,help='folder with ready-made prior_links, prior_sources and base_retired Parquet')
    ledger.add_argument('--ledger-base',type=Path,help='release folder carrying retired_links.parquet to derive the ledger from')
    parser.add_argument('--expect-release-id',help='fail unless the built release id starts with these 12 to 64 hex characters')
    args=parser.parse_args(argv)
    if args.from_candidate is None and (args.build or args.runtime) or args.from_candidate and not (args.build and args.runtime):
        parser.error('--from-candidate needs --build and --runtime, and --spec takes neither')
    if not args.execute and (args.ledger or args.ledger_base or args.expect_release_id):
        parser.error('--ledger, --ledger-base and --expect-release-id apply only with --execute')
    if args.expect_release_id is not None and not RELEASE_ID.fullmatch(args.expect_release_id):
        parser.error('An expected release id is 12 to 64 lowercase hex characters')
    if args.from_candidate and args.execute and not (args.ledger or args.ledger_base):
        parser.error('A candidate build needs the ledger its publisher passed: --ledger or --ledger-base')
    try:
        path=bind_candidate(args.from_candidate,args.build,args.runtime) if args.from_candidate else args.spec
        spec=load_spec(path)
        if spec.get('status')=='blocked':
            print(json.dumps(spec,sort_keys=True));return 2
        if args.execute:
            prior,retired=ledger_files(spec,ready=args.ledger,base=args.ledger_base)
            result=execute(spec,prior_links=prior,base_retired=retired)
        else:
            result=dict(status='planned',executed=False,
                inputs={name:spec[name] for name in (*TABLES,*OPTIONAL_TABLES) if spec.get(name) is not None},output=spec['output'],scratch=spec['scratch'],
                parser_versions=spec['parser_versions'],catalog_version=spec['catalog_version'])
            if spec.get('historical_recording_matcher'):
                result['inputs']['historical_recording_matcher']=spec['historical_recording_matcher']
            if spec.get('text_index'):
                result['text_index']=spec['text_index']
        if args.from_candidate:result['spec']=str(path)
    except (ValueError,OSError) as error:parser.error(str(error))
    print(json.dumps(result,sort_keys=True))
    if args.expect_release_id and not result['release_id'].startswith(args.expect_release_id):
        print(f"Built release {result['release_id']} differs from the expected {args.expect_release_id}",file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
