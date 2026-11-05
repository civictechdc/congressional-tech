"""Capture from one verified public release; --apply is the owner live gate."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from congress_api.acquisition.capture_scheduler import CapturePolicy,load_release,plan_queue,reviewed_cutoffs,run_capture
from congress_api.retention.body_store import BodyStore,LocalAdapter,R2Adapter
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).resolve().parents[5]
DEFAULT_FETCHER_BINARY=ROOT/'packages/source-fetch/target/release/source-fetch'


def _default_fetcher_binary():
    env_bin=os.environ.get('SOURCE_FETCH_BINARY')
    if env_bin:return Path(env_bin)
    return DEFAULT_FETCHER_BINARY if DEFAULT_FETCHER_BINARY.is_file() else None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pointer',help='HTTPS public archive pointer')
    source.add_argument('--release-root',type=Path,help='Local immutable release fixture')
    parser.add_argument('--request-budget',type=int,required=True)
    parser.add_argument('--byte-budget',type=int,required=True)
    parser.add_argument('--spool-budget',type=int,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--cutoff-urls',type=Path,help='Owner-reviewed exact URL list; no raw index')
    parser.add_argument('--campaign',type=Path,help='Pinned recovery campaign descriptor')
    parser.add_argument('--admission-db',type=Path,help='Shared campaign request/spend ledger; caps must agree')
    parser.add_argument('--spend-cap-micros',type=int,help='Maximum provider spend in microdollars')
    parser.add_argument('--zyte-cost-bound-micros',type=int,help='Conservative maximum cost per Zyte request in microdollars')
    parser.add_argument('--as-of',help='Fixed campaign clock; reused automatically on continuation')
    parser.add_argument('--firecrawl-cost-bound-micros',type=int,help='Conservative maximum Firecrawl call cost in microdollars')
    parser.add_argument('--engine-config',type=Path,default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--local-store',type=Path,help='Local create-only body/receipt destination')
    parser.add_argument('--bucket',default='congressional-tech-raw')
    parser.add_argument('--max-discovery-jobs',type=int,default=8)
    parser.add_argument('--fetcher-binary',type=Path,default=_default_fetcher_binary())
    parser.add_argument('--workers',type=int,default=int(os.environ.get('CAPTURE_WORKERS','1')))
    parser.add_argument('--files-per-second',type=int,default=int(os.environ.get('CAPTURE_FILES_PER_SECOND','60')))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if not args.engine_config:parser.error('An explicit native engine configuration is required')
    if any(value<=0 for value in (args.request_budget,args.byte_budget,args.spool_budget,args.max_discovery_jobs,args.workers,args.files_per_second)):
        parser.error('Resource budgets must be positive')
    paid=args.zyte_cost_bound_micros is not None or args.firecrawl_cost_bound_micros is not None
    if (paid and args.spend_cap_micros is None) or any(value is not None and value<=0 for value in (args.spend_cap_micros,args.zyte_cost_bound_micros,args.firecrawl_cost_bound_micros)):
        parser.error('Paid capture needs a positive spend cap and a positive cost bound for each configured provider')
    if args.apply and args.zyte_cost_bound_micros and not os.environ.get('ZYTE_TOKEN'):
        parser.error('Configured Zyte capture requires ZYTE_TOKEN')
    if args.apply and args.firecrawl_cost_bound_micros and not os.environ.get('FIRECRAWL_API_KEY'):
        parser.error('Configured Firecrawl capture requires FIRECRAWL_API_KEY')
    if args.work.resolve().is_relative_to(ROOT):
        parser.error('Keep capture work outside the clean writer checkout')
    cutoffs=json.loads(args.cutoff_urls.read_text()) if args.cutoff_urls else []
    if not isinstance(cutoffs,list):
        raise ValueError('Cutoff input must be an owner-reviewed URL list')
    cutoffs=list(reviewed_cutoffs(cutoffs))
    identity=writer_identity(ROOT,'capture-scheduler') if args.apply else None
    args.work.mkdir(parents=True,exist_ok=True)
    from congress_api.acquisition.capture_journal import durable_json
    selection=args.work/'selection.json'
    source=dict(pointer=args.pointer,release_root=str(args.release_root.resolve()) if args.release_root else None)
    if selection.exists():
        selected=json.loads(selection.read_text())
        if selected['source']!=source:raise ValueError('Continuation release selection changed')
        if 'cutoff_urls' not in selected:
            # Older selections recorded only the release. Bind the supplied list on first reuse.
            durable_json(selection,dict(selected,cutoff_urls=cutoffs))
        elif selected['cutoff_urls']!=cutoffs:
            raise ValueError('Continuation reviewed cutoff input changed')
        release=selected['release']
        args.as_of=args.as_of or selected['as_of']
    else:
        args.as_of=args.as_of or datetime.now(timezone.utc).isoformat()
        release=load_release(work=args.work/'release',release_root=args.release_root,pointer=args.pointer)
        durable_json(selection,dict(source=source,as_of=args.as_of,cutoff_urls=cutoffs,
            release=json.loads(json.dumps(release,default=str))))
    engine=NativeDatasets.from_config(args.engine_config)
    from congress_shared.campaign import load_campaign
    campaign=load_campaign(args.campaign) if args.campaign else None
    if not args.apply:
        result=plan_queue(release,engine=engine,work=args.work/'plan',as_of=args.as_of,
            request_budget=args.request_budget,cutoff_urls=cutoffs,campaign=campaign)
        result.update(apply=False,reviewed_cutoff_urls=cutoffs,
            budgets=dict(requests=args.request_budget,bytes=args.byte_budget,spool=args.spool_budget))
    else:
        CapturePolicy(release['scope']).require_capture()
        import requests
        from congress_api.transport.raw_adapters import DirectAdapter,ProviderAdapter,FirecrawlAdapter
        from congress_api.transport.rust_fetch import RustFetcher
        with ExitStack() as stack:
            if args.fetcher_binary and Path(args.fetcher_binary).is_file():
                session=stack.enter_context(RustFetcher(args.fetcher_binary,
                    files_per_second=args.files_per_second,workers=max(args.workers,1)))
                workers=args.workers
            else:
                session=stack.enter_context(requests.Session())
                workers=1
            provider_session=stack.enter_context(requests.Session()) if (os.environ.get('ZYTE_TOKEN') and
                args.spend_cap_micros is not None and args.zyte_cost_bound_micros is not None) else None
            provider=None
            if provider_session is not None:
                from congress_api.transport import zyte
                provider=ProviderAdapter(lambda payload:provider_session.post(zyte.API,json=payload,
                    auth=(zyte.token(),''),stream=True,allow_redirects=False,timeout=(15,300)))
            firecrawl=None
            if args.firecrawl_cost_bound_micros is not None:
                firecrawl_session=stack.enter_context(requests.Session())
                firecrawl=FirecrawlAdapter(lambda payload:firecrawl_session.post('https://api.firecrawl.dev/v2/scrape',
                    json=payload,headers={'Authorization':'Bearer '+os.environ['FIRECRAWL_API_KEY']},
                    stream=True,allow_redirects=False,timeout=(15,300)))
            if args.local_store:
                store=BodyStore(LocalAdapter(args.local_store))
            else:
                from congress_shared.storage import connect_r2
                store=BodyStore(R2Adapter(connect_r2(bucket=args.bucket,
                    max_pool_connections=max(32,workers*2),
                    retries={'mode':'standard','max_attempts':5}),args.bucket))
            def headers(url):
                if urlsplit(url).hostname in {'api.congress.gov','api.govinfo.gov'}:
                    key=os.environ.get('DATA_GOV_API_KEY')
                    if not key:raise ValueError('DATA_GOV_API_KEY is required for API capture')
                    return {'X-Api-Key':key}
                return {}
            from congress_api.acquisition.admission import Admission
            admission_path=args.admission_db or args.work/'admission.sqlite'
            admission_path.parent.mkdir(parents=True,exist_ok=True)
            admission=Admission(admission_path,args.request_budget,args.spend_cap_micros or 0)
            result=run_capture(release,engine=engine,work=args.work/'capture',as_of=args.as_of,
                request_budget=args.request_budget,byte_budget=args.byte_budget,spool_budget=args.spool_budget,
                store=store,identity=identity,direct=DirectAdapter(session),provider=provider,
                cutoff_urls=cutoffs,max_discovery_jobs=args.max_discovery_jobs,headers=headers,workers=workers,campaign=campaign,
                admission=admission,provider_cost=args.zyte_cost_bound_micros,firecrawl=firecrawl,firecrawl_cost=args.firecrawl_cost_bound_micros)
    (args.work/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
