"""Plan or execute the one guarded archive publication path."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from congress_api.retention.body_store import validate_key
from congress_api.retention.derived_files import file_identity,check_identity
from viewer_publication.archive_model_job import load_spec as load_model_spec,_local,_pin
from viewer_publication.receipt_pins import receipt_list

ROOT=Path(__file__).resolve().parents[4]
SITE=ROOT/'apps/site'
FIELDS={'version','model_spec','bucket','work','public_origin','receipt_keys','provenance','run',
        'contract_next_release','targets'}
METADATA_BYTES=1<<20


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
    if set(value)-FIELDS-{'site_dist'}:raise ValueError('Publication job has unknown fields')
    if not FIELDS<=value.keys() or type(value['version']) is not int or value['version']!=1:
        raise ValueError('Publication job requires version 1 and all explicit inputs')
    base=path.parent
    result=dict(value)
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
    directories=[Path(result['work']),Path(result['_model']['output']),Path(result['_model']['scratch'])]
    if any(left.is_relative_to(right) or right.is_relative_to(left)
           for index,left in enumerate(directories) for right in directories[index+1:]):
        raise ValueError('Publication work, model output and model scratch must be separate')
    return result


def probe_commands(spec,*,release,release_id):
    """Fixed external probes; a job description cannot supply executable commands."""
    targets=spec['targets']['path'];work=Path(spec['work']);origin=spec['public_origin']
    return dict(contract=['npm','run','contract:archive','--','--release',str(release),
        '--next-release',spec['contract_next_release'],'--dist',spec['site_dist'],'--targets',targets,
        '--output',str(work/'contract.json')],
        canary=['npm','run','canary:archive','--','--pointer',origin+'/viewer-publications/manifest.json',
        '--release',release_id,'--raw',origin+'/','--targets',targets,'--output',str(work/'canary.json')])


def execute(spec):
    """Refuse local problems, qualify a remote runtime, then connect the SDK."""
    spec['_model_identity'].require(spec['model_spec']['path'])
    targets,target_identity=_read_metadata(spec['targets'])
    names=['startupMs','searchMs','detailMs','heapBytes']
    if (not isinstance(targets,dict) or type(targets.get('version')) is not int or targets.get('version')!=1
            or targets.get('status')!='measured' or not isinstance(targets.get('ceilings'),dict)
            or any(type(targets['ceilings'].get(name)) not in (int,float)
                   or not math.isfinite(targets['ceilings'][name]) or targets['ceilings'][name]<=0 for name in names)):
        raise ValueError('Publication requires valid measured site targets')
    for name in ['work']:
        path=Path(spec[name])
        if path.exists() or path.is_symlink():raise ValueError('Publication work must be fresh')
    for name in ['output','scratch']:
        path=Path(spec['_model'][name])
        if path.exists() or path.is_symlink():raise ValueError('Model output and scratch must be fresh')
    if not Path(spec['site_dist']).is_dir():raise ValueError('Publication site_dist must already exist; build the site first')
    from docspec_client.client import NativeDatasets
    from congress_shared.storage import connect_r2
    from viewer_publication.archive_controller import run_publish
    with NativeDatasets.from_config(spec['_model']['engine_config']) as engine:
        if not engine.remote:raise ValueError('Publication requires an explicitly configured remote native engine')
        engine.verify_runtime()
        spec['_model_identity'].require(spec['model_spec']['path'])
        target_identity.require(spec['targets']['path'])
        client=connect_r2(bucket=spec['bucket'],retries={'total_max_attempts':1})
        def probe(name,context):
            target_identity.require(spec['targets']['path'])
            commands=probe_commands(spec,release=context.get('release',spec['_model']['output']),release_id=context['release_id'])
            subprocess.run(commands[name],cwd=SITE,check=True,timeout=180)
            receipt_path=Path(spec['work'])/(name+'.json')
            if receipt_path.stat().st_size>METADATA_BYTES:raise ValueError('Site probe receipt exceeds the metadata allowance')
            receipt=json.loads(receipt_path.read_text())
            target_identity.require(spec['targets']['path'])
            return receipt
        result=run_publish(spec['_model'],client=client,engine=engine,bucket=spec['bucket'],work=spec['work'],
            receipt_keys=spec['receipt_keys'],provenance=spec['provenance'],run=spec['run'],public_origin=spec['public_origin'],
            contract=lambda **context:probe('contract',context),canary=lambda **context:probe('canary',context))
        spec['_model_identity'].require(spec['model_spec']['path'])
        return result


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
    except (ValueError,OSError,subprocess.SubprocessError) as error:parser.error(str(error))
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
