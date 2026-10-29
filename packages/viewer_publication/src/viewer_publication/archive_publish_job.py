"""Plan or execute the one guarded archive publication path."""
import argparse
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from tempfile import TemporaryDirectory
from uuid import UUID

from congress_api.retention.body_store import validate_key
from congress_api.retention.derived_files import file_identity,check_identity
from viewer_publication.archive_model_job import (
    load_spec as load_model_spec,validate_spec as validate_model_spec,_local,_pin,
    TABLES,PROVENANCE,provenance_record_kind,provenance_etag_md5,
)
from viewer_publication.receipt_pins import receipt_list
from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance,require_comparison

ROOT=Path(__file__).resolve().parents[4]
SITE=ROOT/'apps/site'
FIELDS={'version','model_spec','bucket','work','public_origin','receipt_keys','provenance','run',
        'contract_next_release','targets'}
METADATA_BYTES=1<<20


def completed_daily_inputs(template,production,records):
    """Bind only a completed producer's fresh pins and complete receipt set."""
    if not isinstance(production,dict) or production.get('status')!='completed':
        raise ValueError('Publication requires completed daily production')
    pins=production.get('pins');keys=production.get('receipt_keys');versions=production.get('currentversions')
    if (not isinstance(pins,dict) or set(pins)!=set(TABLES)
            or not isinstance(keys,list) or any(not isinstance(key,str) for key in keys)
            or keys!=sorted(set(keys)) or not isinstance(versions,dict)
            or not {'parsers','filename_readings'}<=versions.keys()):
        raise ValueError('Daily publication requires three fresh pins, complete receipt keys and definitions')
    receipt_list(keys)
    value=dict(template,parser_versions=versions['parsers'],catalog_version=versions['filename_readings'])
    for name in TABLES:
        if (not isinstance(pins[name],dict)
                or set(pins[name])!={'metadata_location','table_uuid','snapshot','schema_id'}):
            raise ValueError('Invalid daily native table pin')
        value[name]=dict(pins[name],kind='native_table')
    selected={};families={family:[] for family in PROVENANCE.values()}
    for row in records:
        _pin(row,{'key','path','etag','sha256','size'})
        kind=provenance_record_kind(row['key'])
        if kind is None or row['key'] in selected:raise ValueError('Daily records must have distinct recognized keys')
        provenance_etag_md5(row['etag'])
        selected[row['key']]=row
        families[kind].append({k:v for k,v in row.items() if k!='etag'})
    produced=production.get('provenance')
    if not isinstance(produced,dict) or set(produced)!={'recoveries','reviews','unreadable'}:
        raise ValueError('Daily production requires complete decision provenance')
    for kind,rows in produced.items():
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
            raise ValueError('Invalid daily decision provenance')
        actual={key:row for key,row in selected.items() if provenance_record_kind(key)==kind}
        if (len(rows)!=len(actual) or {row.get('key') for row in rows}!=set(actual)
                or any(row!=actual[row['key']] for row in rows)):
            raise ValueError('Daily provenance differs from checked records and acknowledged imports')
    for name,kind in PROVENANCE.items():value[name]=sorted(families[kind],key=lambda row:row['key'])
    return validate_model_spec(value,base=Path.cwd()),list(keys)


def produce_daily_inputs(template,daily,*,engine,raw_store):
    """Run the maintained producer once against one complete raw snapshot."""
    from congress_api.lake.daily import produce_daily,_validate as validate_daily
    from congress_api.retention.provenance_inventory import provenance_inventory
    if not isinstance(daily,dict) or daily.get('provenance')!={kind:[] for kind in ['recoveries','reviews','unreadable']}:
        raise ValueError('Daily publication selects provenance from the current raw inventory')
    validate_daily(daily,engine,raw_store)
    work=Path(daily['work']).resolve()
    if work.exists() or work.is_symlink():raise ValueError('Daily production work must be fresh')
    snapshot=provenance_inventory(raw_store,work=work.with_name(work.name+'-provenance'))
    full={row['key']:row for row in snapshot.metadata()}
    records=snapshot.qualify([key for key in full if provenance_record_kind(key) is not None])
    selected=dict(daily,provenance={kind:[row for row in records if provenance_record_kind(row['key'])==kind]
        for kind in ['recoveries','reviews','unreadable']})
    production=produce_daily(selected,engine=engine,raw_store=raw_store)
    summary={key:production.get(key) for key in ['status','pins','receipt_keys','new_receipt_keys','currentversions']}
    with (work/'daily-summary.json').open('x') as target:json.dump(summary,target,sort_keys=True)
    if production['status']!='completed':return dict(status=production['status'],daily=summary)
    records=snapshot.rows()
    model,keys=completed_daily_inputs(template,production,records)
    for row in records:
        if row['key'] not in full:
            if provenance_record_kind(row['key'])!='unreadable':raise ValueError('Unexpected daily provenance addition')
            full[row['key']]=dict(key=row['key'],etag=row['etag'],size=row['size'])
    return dict(status='ready',model=model,receipt_keys=keys,daily=summary,
        provenance=[dict(key=key,etag=full[key]['etag']) for key in sorted(full)],
        verified_files=snapshot.verified())


def _metadata_pin(value,base):
    _pin(value,{'path','sha256','size'})
    if value['size']>METADATA_BYTES:raise ValueError('Publication metadata exceeds the small JSON allowance')
    return dict(value,path=_local(value['path'],base))


def _verify_metadata(pin):
    path=Path(pin['path'])
    if path.stat().st_size>METADATA_BYTES:raise ValueError('Publication metadata exceeds the small JSON allowance')
    identity=file_identity(path)
    check_identity(identity,dict(sha256=pin['sha256'],bytes=pin['size']),str(path))
    return identity


def _read_metadata(pin):
    identity=_verify_metadata(pin)
    value=json.loads(Path(pin['path']).read_text())
    identity.require(pin['path'])
    return value,identity


def load_spec(path):
    """Read only the publisher/model descriptions and current code definitions."""
    path=Path(path).resolve();value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Publication job spec must be an object')
    if value.get('status')=='blocked':
        if set(value)!={'status','reason'} or not isinstance(value['reason'],str) or not value['reason'].strip():
            raise ValueError('Blocked publication job requires exactly its reason')
        return value
    if set(value)-FIELDS-{'site_dist','daily','model_kind','comparison_acceptance'}:raise ValueError('Publication job has unknown fields')
    if not FIELDS<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Publication job requires version 1 and all explicit inputs')
    base=path.parent
    result=dict(value)
    kind=value.get('model_kind','raw')
    if kind not in {'raw','seed_v5'}:raise ValueError('Unknown publication model_kind')
    if kind=='seed_v5' and (value['receipt_keys'] or value['provenance'] or 'daily' in value):
        raise ValueError('A display-only seed cannot select raw receipts, provenance or daily production')
    result['model_kind']=kind
    if 'comparison_acceptance' in value:
        selected=value['comparison_acceptance']
        if kind!='raw' or 'daily' in value:raise ValueError('Comparison acceptance selects only an explicit raw model publication')
        if (not isinstance(selected,dict) or set(selected)!={'receipt','mapping_digest'} or
                not isinstance(selected['mapping_digest'],str) or re.fullmatch('[a-f0-9]{64}',selected['mapping_digest']) is None):
            raise ValueError('Comparison acceptance requires its receipt pin and mapping digest')
        result['comparison_acceptance']=dict(receipt=_metadata_pin(selected['receipt'],base),mapping_digest=selected['mapping_digest'])
    for name in ['model_spec','targets']:result[name]=_metadata_pin(value[name],base)
    for name in ['work','contract_next_release']:result[name]=_local(value[name],base)
    result['site_dist']=_local(value['site_dist'],base) if 'site_dist' in value else str(SITE/'dist')
    origin=urlsplit(value['public_origin']) if isinstance(value['public_origin'],str) else None
    if (origin is None or origin.scheme!='https' or not origin.hostname or origin.username or origin.password
            or origin.query or origin.fragment or origin.path not in {'','/'}
            or any(char.isspace() or ord(char)<32 for char in value['public_origin'])):
        raise ValueError('Publication requires an HTTPS public origin without a path or credentials')
    # Accessing port also refuses malformed authorities before any SDK construction.
    try:origin.port
    except ValueError:raise ValueError('Invalid HTTPS public origin') from None
    result['public_origin']=value['public_origin'].rstrip('/')
    if not isinstance(value['bucket'],str) or re.fullmatch('[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',value['bucket']) is None:
        raise ValueError('Invalid archive bucket')
    if not isinstance(value['receipt_keys'],list):raise ValueError('Publication receipt keys must be a list')
    receipt_list(value['receipt_keys'])
    if not isinstance(value['run'],dict) or not value['run']:raise ValueError('Publication requires explicit run metadata')
    if 'expected_release_id' in value['run']:
        expected=value['run']['expected_release_id']
        if not isinstance(expected,str) or re.fullmatch('[a-f0-9]{64}',expected) is None:
            raise ValueError('Invalid expected publication release ID')
    if not isinstance(value['provenance'],list):raise ValueError('Publication provenance must be a list')
    seen=set()
    for item in value['provenance']:
        if (not isinstance(item,dict) or set(item)!={'key','etag'} or not isinstance(item['key'],str)
                or not item['key'].startswith('provenance/') or not isinstance(item['etag'],str) or not item['etag'].strip()
                or item['key'] in seen):raise ValueError('Publication requires distinct provenance keys and ETags')
        validate_key(item['key']);seen.add(item['key'])
    result['_model_identity']=_verify_metadata(result['model_spec'])
    if kind=='seed_v5':
        from viewer_publication.archive_seed import load_seed_spec
        result['_model']=load_seed_spec(result['model_spec']['path'])
    else:result['_model']=load_model_spec(result['model_spec']['path'])
    result['_model_identity'].require(result['model_spec']['path'])
    if result['_model'].get('status')=='blocked':return result['_model']
    if 'comparison_acceptance' in result and result['_model']['captures'].get('kind')!='native_table':raise ValueError('Comparison acceptance requires the exact native capture selector')
    directories=[Path(result['work']),Path(result['_model']['output']),Path(result['_model']['scratch'])]
    if 'daily' in value:
        if value['receipt_keys'] or value['provenance']:
            raise ValueError('Daily publication derives receipt and provenance identities from production')
        result['daily']=_metadata_pin(value['daily'],base)
        daily,result['_daily_identity']=_read_metadata(result['daily'])
        if (not isinstance(daily,dict) or daily.get('provenance')!={kind:[] for kind in ['recoveries','reviews','unreadable']}):
            raise ValueError('Daily publication selects provenance from the current raw inventory')
        if daily.get('catalog_root','missing') is not None:
            raise ValueError('Daily publisher requires its configured remote lake catalog')
        for name in ['work','body_inventory','local_root']:
            daily[name]=_local(daily.get(name),Path(result['daily']['path']).parent)
        result['_daily']=daily
        daywork=Path(daily['work']);directories.extend([daywork,daywork.with_name(daywork.name+'-provenance')])
    if any(left.is_relative_to(right) or right.is_relative_to(left)
           for index,left in enumerate(directories) for right in directories[index+1:]):
        raise ValueError('Publication work, model output and model scratch must be separate')
    return result


def _public_configuration(path):
    path=Path(path)
    if path.stat().st_size>METADATA_BYTES:raise ValueError('Publication destination metadata is oversized')
    identity=file_identity(path);value=json.loads(path.read_text());identity.require(path)
    if not isinstance(value,dict):raise ValueError('Invalid publication destination configuration')
    return value,identity


def publication_configuration(path,*,bucket):
    """Read public destination metadata; never read the credential file.

    The model keeps its lake scope. A derived upload runtime changes only the
    owned object prefix, using the same explicit R2 account/bucket and native pins.
    """
    path=Path(path).resolve();settings,runtime_identity=_public_configuration(path)
    if not settings.get('remote'):raise ValueError('Publication requires an explicitly configured remote native engine')
    settings=dict(settings)
    for name in ['binary','workspace','remote','limits','credentials']:
        if name in settings:settings[name]=_local(settings[name],path.parent)
    remote,remote_identity=_public_configuration(settings['remote'])
    properties=remote.get('properties');references=remote.get('secret_env')
    allowed={'uri','warehouse','s3.endpoint','s3.region','s3.path-style-access',
             's3.disable-ec2-metadata','s3.disable-config-load','docspec.namespace-generation'}
    if (set(remote)!={'owned_prefix','properties','secret_env'} or not isinstance(properties,dict)
            or set(properties)-allowed or any(not isinstance(value,str) for value in properties.values())
            or not isinstance(references,dict)
            or not {'token','s3.access-key-id','s3.secret-access-key'}<=references.keys()
            or references.keys()-{'token','s3.access-key-id','s3.secret-access-key','s3.session-token'}
            or any(not isinstance(key,str) or not isinstance(value,str)
                   or re.fullmatch('DOCSPEC_[A-Z0-9_]+',value) is None for key,value in references.items())):
        raise ValueError('Publication destination requires public properties and explicit secret environment references')
    endpoint=properties.get('s3.endpoint')
    account=(re.fullmatch(r'https://([a-f0-9]{32})\.r2\.cloudflarestorage\.com',endpoint)
             if isinstance(endpoint,str) else None)
    scope=remote.get('owned_prefix')
    if (account is None or properties.get('s3.region')!='auto' or not isinstance(scope,str)
            or re.fullmatch(re.escape('s3://'+bucket+'/__r2_data_catalog/')+r'[A-Za-z0-9][A-Za-z0-9_.-]*/?',scope) is None):
        raise ValueError('Publication destination must be one explicit R2 account, bucket and lake namespace')
    account=account[1]
    if (properties.get('uri')!='https://catalog.cloudflarestorage.com/'+account+'/'+bucket
            or properties.get('warehouse')!=account+'_'+bucket):
        raise ValueError('Publication destination catalog and object provider identities differ')
    try:
        if UUID(properties.get('docspec.namespace-generation','')).int==0:raise ValueError
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Publication destination requires an explicit catalog namespace generation') from None
    return settings,remote,endpoint,[(path,runtime_identity),(Path(settings['remote']),remote_identity)]


class PublicationRuntime:
    """Use lake SQL and publication uploads through their two explicit scopes."""
    def __init__(self,model,uploads):self.model,self.uploads=model,uploads
    def __getattr__(self,name):return getattr(self.model,name)
    @property
    def remote(self):return self.uploads.remote
    def create_file(self,spec):return self.uploads.create_file(spec)
    def verify_runtime(self):
        model=self.model.verify_runtime();uploads=self.uploads.verify_runtime()
        if model!=uploads:raise ValueError('Publication runtime qualification pins differ')
        return model


def probe_commands(spec,*,release,release_id,probe_selectors):
    """Fixed external probes; a job description cannot supply executable commands."""
    if (not isinstance(probe_selectors,dict) or set(probe_selectors)!={'saved_row','link_key'}
            or type(probe_selectors['saved_row']) is not int or probe_selectors['saved_row']<0
            or not isinstance(probe_selectors['link_key'],str)
            or re.fullmatch('[a-f0-9]{16}',probe_selectors['link_key']) is None):
        raise ValueError('Publication requires actual native probe selectors')
    targets=spec['targets']['path'];work=Path(spec['work']);origin=spec['public_origin']
    return dict(contract=['npm','run','contract:archive','--','--release',str(release),
        '--next-release',spec['contract_next_release'],'--dist',spec['site_dist'],'--targets',targets,
        '--output',str(work/'contract.json'),'--link-key',probe_selectors['link_key']],
        canary=['npm','run','canary:archive','--','--pointer',origin+'/viewer-publications/manifest.json',
        '--release',release_id,'--raw',origin+'/','--targets',targets,'--output',str(work/'canary.json'),'--saved-row',str(probe_selectors['saved_row'])])


def execute(spec,*,runtime_factory=None,storage_factory=None,process_runner=None):
    """Refuse local problems, qualify a remote runtime, then connect the SDK."""
    spec['_model_identity'].require(spec['model_spec']['path'])
    acceptance=None
    if 'comparison_acceptance' in spec:
        selected=spec['comparison_acceptance']
        acceptance=ComparisonAcceptance(selected['receipt'],expected_mapping_digest=selected['mapping_digest'],
            capture_pin={k:v for k,v in spec['_model']['captures'].items() if k!='kind'})
        require_comparison(acceptance,captures=spec['_model']['captures'])
    targets,target_identity=_read_metadata(spec['targets'])
    # The site owns profile, median and run validation. Execute its fixed local
    # metadata command once, before constructing a runtime or SDK client.
    target_identity.require(spec['targets']['path'])
    try:
        checked=subprocess.run(['npm','run','--silent','targets:archive','--','--check',spec['targets']['path'],
            '--origin-kind','seed_v5' if spec.get('model_kind')=='seed_v5' else 'model',
            '--display-only','true' if spec.get('model_kind')=='seed_v5' else 'false'],
            cwd=SITE,check=True,capture_output=True,text=True,timeout=30)
        if len(checked.stdout.encode())>METADATA_BYTES:raise ValueError('Target validator output exceeds the metadata allowance')
        target_metadata=json.loads(checked.stdout)
    except (subprocess.SubprocessError,ValueError) as error:
        raise ValueError('Publication requires valid measured site targets (owner-approved or candidate-bound provisional-emulated)') from error
    target_identity.require(spec['targets']['path'])
    if (not isinstance(target_metadata,dict) or set(target_metadata)!={'status','basis','measured_release_id'}
            or target_metadata['status']!=targets.get('status') or target_metadata['basis']!=targets.get('basis')):
        raise ValueError('Shared targets validation differs from the pinned metadata')
    measured_release_id=target_metadata['measured_release_id']
    expected_release_id=spec['run'].get('expected_release_id')
    if (expected_release_id is not None and measured_release_id is not None
            and expected_release_id!=measured_release_id):
        raise ValueError('Measured site targets differ from the approved release')
    measured_release_id=expected_release_id or measured_release_id
    for name in ['work']:
        path=Path(spec[name])
        if path.exists() or path.is_symlink():raise ValueError('Publication work must be fresh')
    for name in ['output','scratch']:
        path=Path(spec['_model'][name])
        if path.exists() or path.is_symlink():raise ValueError('Model output and scratch must be fresh')
    if '_daily' in spec:
        spec['_daily_identity'].require(spec['daily']['path'])
        path=Path(spec['_daily']['work'])
        if any(p.exists() or p.is_symlink() for p in [path,path.with_name(path.name+'-provenance')]):
            raise ValueError('Daily production work and provenance cache must be fresh')
    if not Path(spec['site_dist']).is_dir():raise ValueError('Publication site_dist must already exist; build the site first')
    from docspec_client.client import NativeDatasets
    from congress_shared.storage import connect_r2
    from viewer_publication.archive_controller import run_publish,run_seed_publish,_publication_directory
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    process_runner=process_runner or subprocess.run
    settings,remote,endpoint,configuration_pins=publication_configuration(spec['_model']['engine_config'],bucket=spec['bucket'])
    def require_configuration():
        for path,identity in configuration_pins:identity.require(path)
        require_comparison(acceptance)
    parent=_publication_directory(Path(spec['work']).parent,fresh=False)
    with TemporaryDirectory(prefix='.'+Path(spec['work']).name+'-startup-',dir=parent) as directory:
        directory=Path(directory)
        upload_remote=directory/'remote.json';upload_settings=directory/'runtime.json'
        upload_remote.write_text(json.dumps(dict(remote,owned_prefix='s3://'+spec['bucket']+'/viewer-publications')))
        upload_settings.write_text(json.dumps(dict(settings,remote=str(upload_remote),workspace=str(directory/'workspace'))))
        with runtime_factory(spec['_model']['engine_config']) as model, runtime_factory(upload_settings) as uploads:
            if (Path(model.remote).resolve()!=Path(settings['remote']) or Path(uploads.remote).resolve()!=upload_remote):
                raise ValueError('Publication destination differs from the loaded runtime')
            engine=PublicationRuntime(model,uploads)
            engine.verify_runtime();require_configuration()
            spec['_model_identity'].require(spec['model_spec']['path'])
            target_identity.require(spec['targets']['path'])
            client=storage_factory(bucket=spec['bucket'],endpoint_url=endpoint,retries={'total_max_attempts':1})
            selected_model=spec['_model'];keys=spec['receipt_keys'];provenance=spec['provenance'];verified=None;daily=None
            if '_daily' in spec:
                from congress_api.retention.body_store import BodyStore,R2Adapter
                spec['_daily_identity'].require(spec['daily']['path'])
                daily=produce_daily_inputs(selected_model,spec['_daily'],engine=model,
                    raw_store=BodyStore(R2Adapter(client,spec['bucket'])))
                spec['_daily_identity'].require(spec['daily']['path'])
                spec['_model_identity'].require(spec['model_spec']['path']);require_configuration()
                if daily['status']!='ready':return daily
                selected_model=daily['model'];keys=daily['receipt_keys'];provenance=daily['provenance'];verified=daily['verified_files']
            def probe(name,context):
                target_identity.require(spec['targets']['path']);require_configuration()
                commands=probe_commands(spec,release=context.get('release',spec['_model']['output']),
                    release_id=context['release_id'],probe_selectors=context.get('probe_selectors'))
                process_runner(commands[name],cwd=SITE,check=True,timeout=180)
                receipt_path=Path(spec['work'])/(name+'.json')
                if receipt_path.stat().st_size>METADATA_BYTES:raise ValueError('Site probe receipt exceeds the metadata allowance')
                receipt=json.loads(receipt_path.read_text())
                target_identity.require(spec['targets']['path']);require_configuration()
                return receipt
            options=dict(client=client,engine=engine,bucket=spec['bucket'],work=spec['work'],run=spec['run'],
                public_origin=spec['public_origin'],contract=lambda **context:probe('contract',context),
                canary=lambda **context:probe('canary',context))
            if spec.get('model_kind')=='seed_v5':result=run_seed_publish(selected_model,
                measured_release_id=measured_release_id,**options)
            else:result=run_publish(selected_model,receipt_keys=keys,provenance=provenance,verified_files=verified,
                measured_release_id=measured_release_id,comparison_acceptance=acceptance,**options)
            spec['_model_identity'].require(spec['model_spec']['path']);require_configuration()
            return dict(result,daily=daily['daily']) if daily is not None else result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--plan',action='store_true');mode.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':print(json.dumps(spec,sort_keys=True));return 2
        result=execute(spec) if args.execute else dict(status='planned',executed=False,
            model_spec=spec['model_spec'],bucket=spec['bucket'],work=spec['work'],public_origin=spec['public_origin'],
            targets=spec['targets'],site_dist=spec['site_dist'])
        if not args.execute and 'daily' in spec:result['daily']=spec['daily']
        if not args.execute and spec.get('model_kind')=='seed_v5':result['model_kind']='seed_v5'
    except (ValueError,OSError,subprocess.SubprocessError) as error:parser.error(str(error))
    print(json.dumps(result,sort_keys=True));return 2 if result.get('status') in {'pending','backfill_required'} else 0


if __name__=='__main__':raise SystemExit(main())
