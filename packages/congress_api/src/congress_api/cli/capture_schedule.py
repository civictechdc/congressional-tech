"""Capture from one verified public release; --apply is the owner live gate."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.acquisition.capture_scheduler import CapturePolicy,load_release,plan_queue,run_capture
from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).resolve().parents[5]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pointer',help='HTTPS public archive pointer')
    source.add_argument('--release-root',type=Path,help='Local immutable release fixture')
    parser.add_argument('--request-budget',type=int,required=True)
    parser.add_argument('--byte-budget',type=int,required=True)
    parser.add_argument('--spool-budget',type=int,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--seed-inventory',action='append',type=Path,default=[])
    parser.add_argument('--cutoff-urls',type=Path,help='Owner-reviewed exact URL list; no raw index')
    parser.add_argument('--as-of',default=datetime.now(timezone.utc).isoformat())
    parser.add_argument('--engine-config',type=Path,default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--url-keys-sql',type=Path,help='Shared E url_key definition; no identity fallback')
    parser.add_argument('--url-key-inputs',type=Path,help='Profile native input declarations for shared URL rules/variants')
    parser.add_argument('--local-store',type=Path,help='Local create-only body/receipt destination')
    parser.add_argument('--bucket',default='congressional-tech-raw')
    parser.add_argument('--max-discovery-jobs',type=int,default=8)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if not args.engine_config:parser.error('An explicit native engine configuration is required')
    if any(value<=0 for value in (args.request_budget,args.byte_budget,args.spool_budget,args.max_discovery_jobs)):
        parser.error('Resource budgets must be positive')
    if args.work.resolve().is_relative_to(ROOT):
        parser.error('Keep capture work outside the clean writer checkout')
    identity=writer_identity(ROOT,'capture-scheduler') if args.apply else None
    args.work.mkdir(parents=True,exist_ok=False)
    release=load_release(work=args.work/'release',release_root=args.release_root,pointer=args.pointer)
    if args.url_keys_sql:release['url_keys_sql']=args.url_keys_sql
    if args.url_key_inputs:release['url_key_inputs']=json.loads(args.url_key_inputs.read_text())
    engine=NativeDatasets.from_config(args.engine_config)
    cutoffs=json.loads(args.cutoff_urls.read_text()) if args.cutoff_urls else []
    if not isinstance(cutoffs,list) or any(not isinstance(url,str) for url in cutoffs):
        raise ValueError('Cutoff input must be an owner-reviewed URL list')
    if not args.apply:
        result=plan_queue(release,engine=engine,work=args.work/'plan',as_of=args.as_of,
            request_budget=args.request_budget,seed_inventories=args.seed_inventory,cutoff_urls=cutoffs)
        result.update(apply=False,budgets=dict(requests=args.request_budget,bytes=args.byte_budget,spool=args.spool_budget))
    else:
        CapturePolicy(release['scope']).require_capture()
        import requests
        from congress_api.transport.raw_adapters import DirectAdapter,ProviderAdapter
        session=requests.Session()
        provider=None
        if os.environ.get('ZYTE_TOKEN'):
            from congress_api.transport import zyte
            provider=ProviderAdapter(lambda payload:session.post(zyte.API,json=payload,
                auth=(zyte.token(),''),stream=True,allow_redirects=False,timeout=(15,300)))
        if args.local_store:
            store=BodyStore(LocalAdapter(args.local_store))
        else:
            from congress_shared.storage import connect_r2
            store=BodyStore(R2Adapter(connect_r2(bucket=args.bucket,
                retries={'mode':'standard','max_attempts':5}),args.bucket))
        def headers(url):
            if urlsplit(url).hostname in {'api.congress.gov','api.govinfo.gov'}:
                key=os.environ.get('DATA_GOV_API_KEY')
                if not key:raise ValueError('DATA_GOV_API_KEY is required for API capture')
                return {'X-Api-Key':key}
            return {}
        result=run_capture(release,engine=engine,work=args.work/'capture',as_of=args.as_of,
            request_budget=args.request_budget,byte_budget=args.byte_budget,spool_budget=args.spool_budget,
            store=store,identity=identity,direct=DirectAdapter(session),provider=provider,
            seed_inventories=args.seed_inventory,cutoff_urls=cutoffs,max_discovery_jobs=args.max_discovery_jobs,headers=headers)
    (args.work/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
