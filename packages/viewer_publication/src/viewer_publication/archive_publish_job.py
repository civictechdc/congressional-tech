"""Plan or execute the one guarded archive publication path."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from tempfile import TemporaryDirectory
from uuid import UUID,uuid4

from congress_api.lake.daily import DAILY_CAPTURE_RECORDS
from congress_api.retention.body_store import validate_key
from congress_api.retention.derived_files import file_identity,check_identity
from viewer_publication.archive_model_job import (
    load_spec as load_model_spec,validate_spec as validate_model_spec,_local,_pin,
    TABLES,OPTIONAL_TABLES,ENTITY_TABLES,EXPLORER_TABLES,PROVENANCE,provenance_record_kind,provenance_etag_md5,
)
from viewer_publication.receipt_pins import receipt_list
from viewer_publication.archive_comparison_acceptance import ComparisonAcceptance,require_comparison

ROOT=Path(__file__).resolve().parents[4]
SITE=ROOT/'apps/site'
# Base daily pins and the optional meeting/appearance pair.
ALL_TABLES=(*TABLES,*ENTITY_TABLES)
FIELDS={'version','model_spec','bucket','work','public_origin','receipt_keys','provenance','run',
        'contract_next_release','targets'}
METADATA_BYTES=1<<20
# Gate 3 (ct-tk10): raw receipt lines through every producer to release files.
END_TO_END=['scripts/dev.py','test','production-offline','--path',
    'packages/viewer_publication/tests/test_release_end_to_end.py','--','-q']


def _expected_entity_versions():
    from congress_api.lake import appearance_records,meeting_records
    return {
        'meeting_records':meeting_records.current_versions(),
        'appearance_records':appearance_records.current_versions(),
    }


def completed_daily_inputs(template,production,records):
    """Bind only a completed producer's fresh pins and complete receipt set."""
    if not isinstance(production,dict) or production.get('status')!='completed':
        raise ValueError('Publication requires completed daily production')
    pins=production.get('pins');keys=production.get('receipt_keys');versions=production.get('currentversions')
    if (not isinstance(pins,dict) or set(pins)-set(DAILY_CAPTURE_RECORDS) not in (set(TABLES),set(ALL_TABLES))
            or not isinstance(keys,list) or any(not isinstance(key,str) for key in keys)
            or keys!=sorted(set(keys)) or not isinstance(versions,dict)
            or not {'parsers','filename_readings'}<=versions.keys()):
        raise ValueError('Daily publication requires fresh pins, complete receipt keys and definitions')
    if not isinstance(versions.get('parsers'),dict):
        raise ValueError('Daily publication requires page parser versions')
    from congress_api.lake.compatible_versions import DERIVED_PARSERS
    merged_parsers=dict(versions['parsers'])
    template_parsers=template.get('parser_versions') or {}
    # The readings head retains settled derived rows when their daily pass is disabled.
    for name in DERIVED_PARSERS:
        if name in versions:
            merged_parsers[name]=versions[name]
        elif name in template_parsers:
            merged_parsers[name]=template_parsers[name]
    if 'meeting_records' in pins or 'appearance_records' in pins:
        for entity_name,expected_ver in _expected_entity_versions().items():
            ver=versions.get(entity_name)
            if not isinstance(ver,dict) or ver!=expected_ver:
                raise ValueError(f'Daily publication {entity_name} producer version differs from current source-scoped definitions')
            if entity_name in pins:
                merged_parsers[entity_name]=dict(ver)
    # Unchanged entity and Explorer selectors keep their pinned parser definitions.
    for name in (*ENTITY_TABLES,*EXPLORER_TABLES):
        if name not in pins and template.get(name) is not None and name in template_parsers:
            merged_parsers[name]=dict(template_parsers[name])
    for name,module in DAILY_CAPTURE_RECORDS.items():
        if name in pins:
            version=versions.get(name)
            if version!=module.current_versions():
                raise ValueError(f'Daily publication {name} producer version differs from current definitions')
            merged_parsers[name]=dict(version)
        elif template.get(name) is not None and name not in merged_parsers:
            merged_parsers[name]=dict(template['parser_versions'][name])
    receipt_list(keys)
    value=dict(template,parser_versions=merged_parsers,catalog_version=versions['filename_readings'])
    for name in pins:
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
    # Recording decisions only feed the Explorer tables, which daily does not produce; the
    # template carries those pins when a release has them, so the decisions go with them.
    if not all(value.get(name) is not None for name in EXPLORER_TABLES):value['recording_decision_files']=[]
    return validate_model_spec(value,base=Path.cwd()),list(keys)


def produce_daily_inputs(template,daily,*,engine,raw_store,producer_records=None,retain=False):
    """Run the maintained producer once against one complete raw snapshot."""
    from congress_api.lake.daily import produce_daily,_validate as validate_daily
    from congress_api.retention.provenance_inventory import provenance_inventory
    if not isinstance(daily,dict) or daily.get('provenance')!={kind:[] for kind in ['recoveries','reviews','unreadable']}:
        raise ValueError('Daily publication selects provenance from the current raw inventory')
    validate_daily(daily,engine,raw_store)
    work=Path(daily['work']).resolve()
    if work.exists() or work.is_symlink():raise ValueError('Daily production work must be fresh')
    snapshot=provenance_inventory(raw_store,work=work.with_name(work.name+'-provenance'),
        include_verification_history=True)
    full={row['key']:row for row in snapshot.metadata()}
    records=snapshot.qualify([key for key in full if provenance_record_kind(key) is not None])
    selected=dict(daily,provenance={kind:[row for row in records if provenance_record_kind(row['key'])==kind]
        for kind in ['recoveries','reviews','unreadable']})
    # Bodies are read from raw_store itself unless the spec pins an inventory; an empty
    # inventory made every new body a pending read, so daily publication never got past readings.
    if selected.get('body_inventory') is not None and not Path(selected['body_inventory']).exists():
        raise ValueError('The pinned daily body inventory is absent: '+str(selected['body_inventory']))
    production=produce_daily(selected,engine=engine,raw_store=raw_store,producer_records=producer_records)
    summary={key:production.get(key) for key in ['status','pins','receipt_keys','new_receipt_keys','currentversions','producers','carried']}
    summary_path=work/'daily-summary.json'
    if retain:
        from viewer_publication.archive_controller import _save_continuation
        _save_continuation(summary_path,summary)
    else:
        with summary_path.open('x') as target:json.dump(summary,target,sort_keys=True)
    if production['status']!='completed':return dict(status=production['status'],daily=summary)
    records=snapshot.rows()
    model,keys=completed_daily_inputs(template,production,records)
    for row in records:
        if row['key'] not in full:
            if provenance_record_kind(row['key'])!='unreadable':raise ValueError('Unexpected daily provenance addition')
            full[row['key']]=dict(key=row['key'],etag=row['etag'],size=row['size'])
    provenance=[dict(key=key,etag=full[key]['etag']) for key in sorted(full)]
    handoff={}
    if retain:
        from congress_api.lake.receipt_inventory import retained_discovery,receipt_metadata_digest
        deferred=receipt_metadata_digest(retained_discovery(work/'receipt-discovery'),exclude=keys)
        _save_continuation(summary_path,dict(summary,publication=dict(
            records=records,provenance=provenance,deferred=deferred)))
        handoff['daily_summary_sha256']=sha256(summary_path.read_bytes()).hexdigest()
    return dict(status='ready',model=model,receipt_keys=keys,daily=summary,provenance=provenance,
        verified_files=snapshot.verified(),**handoff)


def _resume_daily_inputs(template,daily,*,publish_work):
    """Rebind the completed daily inputs before consulting the current selection."""
    from viewer_publication.archive_controller import _read_continuation
    _,checkpoint=_read_continuation(publish_work,daily=True)
    summary_path=Path(daily['work'])/'daily-summary.json'
    if summary_path.is_symlink():raise ValueError('Retained daily summary must be a regular file')
    raw=summary_path.read_bytes()
    digest=sha256(raw).hexdigest()
    if digest!=checkpoint['daily_summary_sha256']:
        raise ValueError('Retained daily summary differs from the model continuation')
    summary=json.loads(raw)
    retained=summary.pop('publication',None) if isinstance(summary,dict) else None
    if not isinstance(retained,dict) or set(retained)!={'records','provenance','deferred'}:
        raise ValueError('Retained daily summary lacks complete publication inputs')
    records=retained['records']
    model,keys=completed_daily_inputs(template,dict(summary,provenance={
        kind:[row for row in records if provenance_record_kind(row['key'])==kind]
        for kind in ('recoveries','reviews','unreadable')}),records)
    return dict(status='ready',model=model,receipt_keys=keys,daily=summary,
        provenance=retained['provenance'],verified_files=None,daily_summary_sha256=digest,
        deferred_receipt_digest=retained['deferred'])


def _require_current_daily(daily,retained,*,engine,raw_store,work):
    from congress_api.lake.receipt_inventory import R2ReceiptStore,discover_receipts,receipt_metadata_digest
    from congress_api.lake.tables import resolve_tables
    from viewer_publication.archive_controller import PublicationInputsChanged
    heads=resolve_tables(engine=engine,work=work/'heads',catalog_root=daily['catalog_root'],tables=daily['tables'])
    if heads!=retained['daily']['pins']:
        raise PublicationInputsChanged('Daily catalog heads changed since the retained candidate')
    adapter=raw_store.adapter
    rows=discover_receipts(R2ReceiptStore(adapter.client,adapter.bucket),daily['receipt_families'],
        existing=heads['captures'],engine=engine,work=work/'receipt-discovery')
    if receipt_metadata_digest(rows)!=retained['deferred_receipt_digest']:
        raise PublicationInputsChanged('Daily receipt selection changed since the retained candidate')


def nightly_spec(spec,root):
    """Put the Mac's active candidate outside worktree cleanup using the same publisher."""
    if not spec.get('_daily',{}).get('receipt_families') or spec.get('resume'):
        raise ValueError('Nightly work requires daily receipt-family discovery')
    root=Path(root).resolve()
    work=root/'archive-publish'
    model=dict(spec['_model'],output=str(root/'archive-release'),scratch=str(root/'archive-model'))
    if model.get('text_index'):
        model['text_index']=dict(model['text_index'],work=os.environ.get('CONGRESS_TEXT_INDEX_WORK',str(root.parent/'text-index-work')))
    resume=(work/'completed-model.json').exists() or (
        (work/'model-intent.json').exists() and (Path(model['output'])/'manifest.json').exists())
    return dict(spec,work=str(work),_model=model,_daily=dict(spec['_daily'],work=str(root/'archive-daily')),
                _nightly=True,resume=resume)


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
    if set(value)-FIELDS-{'site_dist','daily','model_kind','comparison_acceptance','resume','release_causes','link_history','first_release','producers','automatic_causes'}:raise ValueError('Publication job has unknown fields')
    if not FIELDS<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Publication job requires version 1 and all explicit inputs')
    base=path.parent
    result=dict(value)
    if type(value.get('resume',False)) is not bool:raise ValueError('Publication resume must be boolean')
    if value.get('resume') and 'daily' in value:raise ValueError('Daily publication resume requires the scheduled candidate directory')
    kind=value.get('model_kind','raw')
    if kind!='raw':raise ValueError('Unknown publication model_kind')
    result['model_kind']=kind
    if 'comparison_acceptance' in value:
        selected=value['comparison_acceptance']
        if kind!='raw' or 'daily' in value:raise ValueError('Comparison acceptance selects only an explicit raw model publication')
        if (not isinstance(selected,dict) or set(selected)!={'receipt','mapping_digest'} or
                not isinstance(selected['mapping_digest'],str) or re.fullmatch('[a-f0-9]{64}',selected['mapping_digest']) is None):
            raise ValueError('Comparison acceptance requires its receipt pin and mapping digest')
        result['comparison_acceptance']=dict(receipt=_metadata_pin(selected['receipt'],base),mapping_digest=selected['mapping_digest'])
    for name in ['model_spec','targets']:result[name]=_metadata_pin(value[name],base)
    # Gates 1 and 2: the committed cause record for this candidate, and the earlier
    # releases whose keys seed the ledger when the live release has none.
    if 'release_causes' in value:result['release_causes']=_metadata_pin(value['release_causes'],base)
    producers=value.get('producers',{})
    if not isinstance(producers,dict):raise ValueError('producers must map each pinned table to its record pin')
    result['producers']={name:_metadata_pin(pin,base) for name,pin in producers.items()}
    history=value.get('link_history',[])
    if (not isinstance(history,list) or len(set(history))!=len(history)
            or any(not isinstance(item,str) or re.fullmatch('[a-f0-9]{64}',item) is None for item in history)):
        raise ValueError('link_history must list distinct 64-hex release IDs')
    result['link_history']=list(history)
    if type(value.get('first_release',False)) is not bool:raise ValueError('first_release must be boolean')
    if type(value.get('automatic_causes',False)) is not bool:raise ValueError('automatic_causes must be boolean')
    if value.get('first_release') and history:raise ValueError('A first release has no link history')
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
    result['_model']=load_model_spec(result['model_spec']['path'])
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
        # body_inventory and local_root are optional (daily reads bodies through raw_store
        # unless the spec pins an inventory); only paths that are given are resolved.
        for name in ['work','body_inventory','local_root']:
            if name=='work' or daily.get(name) is not None:
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


def require_end_to_end(runner=None):
    """Run the fixed end-to-end gate through the project runner on the local-only engine.

    dev.py doctor refuses a DOCSPEC_JOB_CONFIG with remote or credentials keys.
    """
    if not os.environ.get('DOCSPEC_JOB_CONFIG'):
        raise ValueError('Publication requires the end-to-end gate (DOCSPEC_JOB_CONFIG local-only)')
    try:(runner or subprocess.run)([sys.executable,*END_TO_END],cwd=ROOT,check=True,timeout=900,env={**os.environ})
    except (subprocess.SubprocessError,OSError) as error:
        raise ValueError('Publication requires the end-to-end gate (DOCSPEC_JOB_CONFIG local-only)') from error


def execute(spec,*,runtime_factory=None,storage_factory=None,process_runner=None,end_to_end_runner=None):
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
            '--origin-kind','model','--display-only','false'],
            cwd=SITE,check=True,capture_output=True,text=True,timeout=30)
        if len(checked.stdout.encode())>METADATA_BYTES:raise ValueError('Target validator output exceeds the metadata allowance')
        target_metadata=json.loads(checked.stdout)
    except (subprocess.SubprocessError,ValueError) as error:
        raise ValueError('Publication requires valid measured site targets (owner-approved or candidate-bound provisional-emulated) or a recorded owner deferral') from error
    target_identity.require(spec['targets']['path'])
    deferred=targets.get('status')=='deferred'
    if (not isinstance(target_metadata,dict)
            or set(target_metadata)!={'status','basis','measured_release_id'}|({'deferral'} if deferred else set())
            or target_metadata['status']!=targets.get('status') or target_metadata['basis']!=targets.get('basis')):
        raise ValueError('Shared targets validation differs from the pinned metadata')
    if deferred:
        deferral=target_metadata['deferral']
        if (not isinstance(deferral,dict) or deferral.get('timing')!='unverified'
                or any(deferral.get(name)!=targets.get(name) for name in ('decided_on','decided_by','reason','restores_gate'))):
            raise ValueError('Shared targets validation differs from the pinned metadata')
        # A deferred speed gate is recorded with the release, never skipped silently.
        site_targets=dict(status='deferred',**deferral)
        print(f"Site speed targets are deferred (owner decision {deferral['decided_on']}; restored by {deferral['restores_gate']}): "
              'timing is unverified for this release.',file=sys.stderr)
    else:
        site_targets=dict(status=target_metadata['status'],basis=target_metadata['basis'],
            measured_release_id=target_metadata['measured_release_id'],timing='verified')
    measured_release_id=target_metadata['measured_release_id']
    expected_release_id=spec['run'].get('expected_release_id')
    if (expected_release_id is not None and measured_release_id is not None
            and expected_release_id!=measured_release_id):
        raise ValueError('Measured site targets differ from the approved release')
    measured_release_id=expected_release_id or measured_release_id
    for name in ['work']:
        path=Path(spec[name])
        if (path.exists() or path.is_symlink()) and not spec.get('resume',False):raise ValueError('Publication work must be fresh')
    for name in ['output','scratch']:
        path=Path(spec['_model'][name])
        if (path.exists() or path.is_symlink()) and not spec.get('resume',False):raise ValueError('Model output and scratch must be fresh')
    if '_daily' in spec:
        spec['_daily_identity'].require(spec['daily']['path'])
        path=Path(spec['_daily']['work'])
        if not spec.get('resume') and any(p.exists() or p.is_symlink() for p in [path,path.with_name(path.name+'-provenance')]):
            raise ValueError('Daily production work and provenance cache must be fresh')
    if not Path(spec['site_dist']).is_dir():raise ValueError('Publication site_dist must already exist; build the site first')
    from docspec_client.client import NativeDatasets
    from congress_shared.storage import connect_r2
    from viewer_publication.archive_controller import run_publish,_publication_directory
    runtime_factory=runtime_factory or NativeDatasets.from_config
    storage_factory=storage_factory or connect_r2
    process_runner=process_runner or subprocess.run
    engine_config=spec['_model']['engine_config']
    if not Path(engine_config).exists() and os.environ.get('DOCSPEC_RUNTIME_CONFIG'):
        engine_config=os.environ['DOCSPEC_RUNTIME_CONFIG']
    settings,remote,endpoint,configuration_pins=publication_configuration(engine_config,bucket=spec['bucket'])
    require_end_to_end(end_to_end_runner)
    def require_configuration():
        for path,identity in configuration_pins:identity.require(path)
        require_comparison(acceptance)
    parent=_publication_directory(Path(spec['work']).parent,fresh=False)
    with TemporaryDirectory(prefix='.'+Path(spec['work']).name+'-startup-',dir=parent) as directory:
        directory=Path(directory)
        upload_remote=directory/'remote.json';upload_settings=directory/'runtime.json'
        upload_remote.write_text(json.dumps(dict(remote,owned_prefix='s3://'+spec['bucket']+'/viewer-publications')))
        upload_settings.write_text(json.dumps(dict(settings,remote=str(upload_remote),workspace=str(directory/'workspace'))))
        with runtime_factory(engine_config) as model, runtime_factory(upload_settings) as uploads:
            if (Path(model.remote).resolve()!=Path(settings['remote']) or Path(uploads.remote).resolve()!=upload_remote):
                raise ValueError('Publication destination differs from the loaded runtime')
            engine=PublicationRuntime(model,uploads)
            engine.verify_runtime();require_configuration()
            spec['_model_identity'].require(spec['model_spec']['path'])
            target_identity.require(spec['targets']['path'])
            client=storage_factory(bucket=spec['bucket'],endpoint_url=endpoint,retries={'total_max_attempts':1})
            selected_model=spec['_model'];keys=spec['receipt_keys'];provenance=spec['provenance'];verified=None;daily=None;reads=None
            from congress_api.lake.producer_records import ProducerRecords
            anchors={}
            for name,pin in spec.get('producers',{}).items():
                identity=_verify_metadata(pin);anchors[name]=Path(pin['path']).read_bytes();identity.require(pin['path'])
            ledger=ProducerRecords(anchors,client=client,bucket=spec['bucket'])
            if '_daily' in spec:
                from congress_api.retention.body_store import BodyStore,R2Adapter
                from congress_api.retention.r2 import configure_read_retries
                spec['_daily_identity'].require(spec['daily']['path'])
                # Body reads get their own client: a transient R2 server error on one of thousands of
                # GETs retries, while this job's writes keep their single attempt.
                reads=configure_read_retries(storage_factory(bucket=spec['bucket'],endpoint_url=endpoint,retries={'total_max_attempts':1}))
                raw_store=BodyStore(R2Adapter(reads,spec['bucket']))
                if spec.get('resume'):
                    daily=_resume_daily_inputs(selected_model,spec['_daily'],publish_work=Path(spec['work']))
                else:
                    retention={'retain':True} if spec.get('_nightly') else {}
                    daily=produce_daily_inputs(selected_model,spec['_daily'],engine=model,
                        raw_store=raw_store,producer_records=ledger,**retention)
                spec['_daily_identity'].require(spec['daily']['path'])
                spec['_model_identity'].require(spec['model_spec']['path']);require_configuration()
                if daily['status']!='ready':return daily
                selected_model=daily['model'];keys=daily['receipt_keys'];provenance=daily['provenance'];verified=daily['verified_files']
            # Gate 5: every pinned derived row names a current or compatible producer, before any build.
            from viewer_publication.producer_proof import find_records,require_producers
            proof_work=(parent/'producer-proof'/uuid4().hex if spec.get('_nightly') else directory/'producer-proof')
            require_producers(selected_model,engine=model,work=proof_work,
                records=find_records(selected_model,ledger,anchors),ledger=ledger)
            def probe(name,context):
                target_identity.require(spec['targets']['path']);require_configuration()
                probe_spec=spec
                if spec.get('resume',False):
                    probe_work=Path(spec['work'])/('probe-'+uuid4().hex)
                    probe_work.mkdir()
                    probe_spec=dict(spec,work=str(probe_work))
                commands=probe_commands(probe_spec,release=context.get('release',spec['_model']['output']),
                    release_id=context['release_id'],probe_selectors=context.get('probe_selectors'))
                process_runner(commands[name],cwd=SITE,check=True,timeout=180)
                receipt_path=Path(probe_spec['work'])/(name+'.json')
                if receipt_path.stat().st_size>METADATA_BYTES:raise ValueError('Site probe receipt exceeds the metadata allowance')
                receipt=json.loads(receipt_path.read_text())
                target_identity.require(spec['targets']['path']);require_configuration()
                return receipt
            options=dict(client=client,engine=engine,bucket=spec['bucket'],work=spec['work'],run=dict(spec['run'],site_targets=site_targets),
                public_origin=spec['public_origin'],contract=lambda **context:probe('contract',context),
                canary=lambda **context:probe('canary',context))
            if spec.get('automatic_causes'):
                # The automatic proof reads one raw receipt per new receipt key; a transient error on
                # one of thousands of GETs must retry, never end the night (ct-gc99).
                if reads is None:
                    from congress_api.retention.r2 import configure_read_retries
                    reads=configure_read_retries(storage_factory(bucket=spec['bucket'],endpoint_url=endpoint,retries={'total_max_attempts':1}))
                options['receipt_client']=reads
            if spec.get('_nightly'):
                options['daily_summary_sha256']=daily['daily_summary_sha256']
                if spec.get('resume'):
                    options['check_current_daily']=lambda:_require_current_daily(
                        spec['_daily'],daily,engine=model,raw_store=raw_store,work=directory/'resume-daily')
            causes=None
            if 'release_causes' in spec:
                from viewer_publication.release_gate import load_causes
                causes=load_causes(spec['release_causes'])
            result=run_publish(selected_model,receipt_keys=keys,provenance=provenance,verified_files=verified,
                measured_release_id=measured_release_id,comparison_acceptance=acceptance,resume=spec.get('resume',False),
                release_causes=causes,link_history=spec.get('link_history',[]),
                first_release=spec.get('first_release',False),automatic_causes=spec.get('automatic_causes',False),**options)
            spec['_model_identity'].require(spec['model_spec']['path']);require_configuration()
            return dict(result,daily=daily['daily']) if daily is not None else result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--plan',action='store_true');mode.add_argument('--execute',action='store_true')
    parser.add_argument('--nightly-work',type=Path,help='Use the scheduled Mac candidate directory')
    args=parser.parse_args(argv)
    if args.nightly_work is not None and not args.execute:
        parser.error('--nightly-work requires --execute')
    from viewer_publication.archive_controller import PublicationInputsChanged,_save_continuation
    try:
        spec=load_spec(args.spec)
        if spec.get('status')=='blocked':print(json.dumps(spec,sort_keys=True));return 2
        if args.nightly_work is not None:spec=nightly_spec(spec,args.nightly_work)
        result=execute(spec) if args.execute else dict(status='planned',executed=False,
            model_spec=spec['model_spec'],bucket=spec['bucket'],work=spec['work'],public_origin=spec['public_origin'],
            targets=spec['targets'],site_dist=spec['site_dist'])
        if not args.execute and spec.get('_model',{}).get('text_index'):
            result['text_index']=spec['_model']['text_index']
        if not args.execute and 'daily' in spec:result['daily']=spec['daily']
    except PublicationInputsChanged as error:
        if args.nightly_work is None or not spec.get('resume'):parser.error(str(error))
        _save_continuation(args.nightly_work/'inputs-changed.json',dict(reason=str(error)))
        print(str(error),file=sys.stderr)
        return 2
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        parser.error('\n'.join([str(error),*getattr(error,'__notes__',())]))
    daily=result.get('daily') if args.execute else None
    stopped=isinstance(daily,dict) and daily.get('status')!='completed'
    print(json.dumps(result,sort_keys=True));return 2 if stopped else 0


if __name__=='__main__':raise SystemExit(main())
