"""Plan or execute bounded readings with local files or pinned raw ranges."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake import readings
from congress_api.retention.body_store import BodyStore,LocalAdapter


def main(argv=None,*,read_current=None,body_store=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True,type=Path)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--plan',action='store_true',help='Only build and count the metadata work list')
    actions.add_argument('--execute',action='store_true',help='Parse and append after admission')
    parser.add_argument('--mode',choices=['daily','backfill'])
    parser.add_argument('--max-work-items',type=int,help='Required positive daily work-list budget')
    parser.add_argument('--batch-size',type=int,help='Required positive backfill body count per append')
    parser.add_argument('--durable-unreadable-root',type=Path,
                        help='Explicit local durable raw store for unreadable decisions')
    parser.add_argument('--raw-bucket',help='Use pinned raw R2 ranges and bounded page caches; credentials stay in runtime env')
    parser.add_argument('--raw-cache-bytes',type=int,help='Per-run body cache bound, at most10GiB (default1GiB)')
    parser.add_argument('--raw-get-workers',type=int,help='Concurrent page-prefetch GETs,1–64 (default64)')
    args=parser.parse_args(argv)
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    modern=args.plan or args.execute
    cache_bytes=readings.RAW_CACHE_BYTES if args.raw_cache_bytes is None else args.raw_cache_bytes
    get_workers=64 if args.raw_get_workers is None else args.raw_get_workers
    try:readings._raw_policy(body_store,cache_bytes,get_workers)
    except ValueError as error:parser.error(str(error))
    if args.raw_bucket and not modern:parser.error('--raw-bucket requires --mode and --plan or --execute')
    if (body_store is not None or args.raw_cache_bytes is not None or args.raw_get_workers is not None) and not args.raw_bucket:
        parser.error('Raw reader and cache options require --raw-bucket')
    if body_store is not None and body_store.bucket!=args.raw_bucket:
        parser.error('Raw store bucket must equal --raw-bucket')
    if modern != (args.mode is not None):
        parser.error('--mode requires exactly one of --plan or --execute')
    if not modern and any(v is not None for v in
            (args.max_work_items,args.batch_size,args.durable_unreadable_root)):
        parser.error('Budget and durable-store options require --mode and --plan or --execute')
    if modern:
        if args.mode=='daily' and args.batch_size is not None:
            parser.error('--batch-size is only for backfill')
        if args.mode=='backfill' and args.max_work_items is not None:
            parser.error('--max-work-items is only for daily')
        if args.mode=='daily' and (args.max_work_items is None or args.max_work_items<=0):
            parser.error('daily requires positive --max-work-items')
        if args.mode=='backfill' and (args.batch_size is None or args.batch_size<=0):
            parser.error('backfill requires positive --batch-size')
        if args.execute and args.durable_unreadable_root is None and not args.raw_bucket:
            parser.error('--execute requires --durable-unreadable-root or --raw-bucket')
    spec=json.loads(args.spec.read_text())
    required={'captures','body_inventory','local_root','work','decided_at','parser'}
    allowed=required|{'existing','sniff_version','parser_version','unreadable_files','apply'}
    if not isinstance(spec,dict) or not required<=spec.keys() or spec.keys()-allowed:
        parser.error('Reading spec requires explicit local inputs, parser, time and work directory')
    apply=spec.pop('apply',None)
    if apply is not None and (not isinstance(apply,dict) or set(apply)!={'catalog_root','table'}):
        parser.error('Apply requires an explicit local catalog_root and table identifier')
    if modern and (args.execute or args.mode=='backfill') and apply is None:
        parser.error('Execution and backfill planning require an explicit apply table authority')
    if args.raw_bucket and args.execute and body_store is None:
        from congress_api.retention.r2 import R2Store
        from congress_shared.storage import R2Config,connect_r2
        body_store=R2Store(connect_r2(R2Config.from_env(bucket=args.raw_bucket,max_pool_connections=get_workers)),
            args.raw_bucket,cache_dir=Path(spec['work'])/'raw-pages')
    with NativeDatasets.from_config(args.engine_config) as engine:
        if engine.remote is not None:
            parser.error('This local readings command requires a local-only engine configuration')
        if modern:
            try:
                result=readings.run(**spec,engine=engine,mode=args.mode,execute=args.execute,
                    max_work_items=args.max_work_items,batch_size=args.batch_size,
                    unreadable_store=BodyStore(LocalAdapter(args.durable_unreadable_root))
                        if args.durable_unreadable_root is not None else body_store.raw
                        if args.execute and body_store is not None else None,
                    body_store=body_store if args.execute else None,raw_ranges=args.raw_bucket is not None,
                    max_cache_bytes=cache_bytes,max_get_workers=get_workers,read_current=read_current,**(apply or {}))
            except (readings.BackfillRequired,readings.RawCustodyRequired) as error:
                print(json.dumps(error.as_dict(),default=str,sort_keys=True))
                return 2
        else:
            result=readings.stage(**spec,engine=engine)
            if apply is not None:
                result['append']=readings.append(result,engine=engine,
                    work=Path(spec['work'])/'append',**apply)
            result['applied']=apply is not None
    print(json.dumps(result,default=str,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
