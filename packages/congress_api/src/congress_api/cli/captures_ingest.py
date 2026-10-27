"""Stage receipt-derived captures and explicitly append through native tables."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake.captures import compact_counter, stage_captures
from congress_api.lake.capture_comparison import compare_old
from congress_api.lake.tables import append_rows, create_table, validate_catalog_authority
from congress_api.lake.receipt_inventory import LocalReceiptStore, discover_receipts, select_receipts


def main(argv=None,*,engine_factory=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-inventory',type=Path,help='Explicit JSON receipt metadata inventory')
    parser.add_argument('--receipt-root',type=Path,help='Read-only local raw root; also resolves inventory keys')
    parser.add_argument('--receipt-family',action='append',default=[],
        help='Family to discover below receipt-root; repeat for each family')
    parser.add_argument('--inventory-mode',choices=['incremental','backfill','raw-check'],default='incremental',
        help='Incremental lists dated prefixes inclusively; backfill/raw-check also list non-date segments')
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--validated-counter',type=Path)
    source.add_argument('--metadata',type=Path)
    parser.add_argument('--receipt-batch-size',type=int,default=64,
                        help='Receipt keys per native metadata batch (1..1024; default 64)')
    parser.add_argument('--existing',type=Path)
    parser.add_argument('--old-index',type=Path)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--catalog-root',type=Path,
        help='Local catalog authority; omit for an explicitly configured remote engine')
    parser.add_argument('--table')
    parser.add_argument('--create-table',action='store_true')
    parser.add_argument('--create-namespace',action='store_true',
        help='Explicitly create the namespace while creating the table; omit for an existing namespace')
    parser.add_argument('--table-location',help='Local table path or exact remote object URI')
    args=parser.parse_args(argv)
    if not 1<=args.receipt_batch_size<=1024:
        parser.error('--receipt-batch-size must be between 1 and 1024')
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    if args.apply and not args.table:
        parser.error('--apply requires an explicit versioned table')
    if args.create_table and (not args.apply or not args.table_location):
        parser.error('--create-table requires --apply and --table-location')
    if args.create_namespace and not args.create_table:
        parser.error('--create-namespace requires --create-table')
    if args.receipt_inventory and args.receipt_family:
        parser.error('Choose an explicit inventory or discovered families')
    if not args.receipt_inventory and (not args.receipt_root or not args.receipt_family):
        parser.error('Discovery requires --receipt-root and at least one --receipt-family')
    engine=(engine_factory or NativeDatasets.from_config)(args.engine_config)
    if args.apply:
        try:
            validate_catalog_authority(engine,args.catalog_root)
        except ValueError as error:
            parser.error(str(error))
    selection_work=args.work.parent/(args.work.name+'-inventory')
    if args.receipt_inventory:
        files=json.loads(args.receipt_inventory.read_text())
        if not isinstance(files,list):
            parser.error('Receipt inventory must be a list')
    else:
        files=discover_receipts(LocalReceiptStore(args.receipt_root),args.receipt_family,
            existing=args.existing,engine=engine,work=selection_work,mode=args.inventory_mode)
    normalized=[]
    for item in files:
        item=dict(key=item) if isinstance(item,str) else dict(item)
        if 'path' not in item and args.receipt_root is not None:
            relative=Path(item['key'])
            if relative.is_absolute() or '..' in relative.parts:
                parser.error('Receipt keys must be relative raw keys')
            item['path']=str((args.receipt_root/relative).resolve())
        if 'path' not in item and not (args.metadata or args.validated_counter):
            parser.error('Local receipt inputs require --receipt-root or inventory paths')
        normalized.append(item)
    if args.receipt_inventory:
        normalized=select_receipts(normalized,args.existing,engine=engine,work=selection_work)
    if not normalized:
        print(json.dumps(dict(stage=None,applied=False,no_work=True,receipts=0),sort_keys=True))
        return 0
    metadata=args.metadata
    if args.validated_counter:
        metadata=compact_counter(args.validated_counter,engine=engine,
            work=args.work.parent/(args.work.name+'-metadata'),
            receipt_keys=[f['key'] for f in normalized],receipt_batch_size=args.receipt_batch_size)
    # Native receipt file declarations accept only source key and local path;
    # listing metadata remains in the preceding inventory job for inspection.
    reader_files=[{k:item[k] for k in ('key','path') if k in item} for item in normalized]
    stage=stage_captures(reader_files,engine=engine,work=args.work,
                         existing=args.existing,counter=metadata)
    comparison=None
    if args.old_index:
        comparison=compare_old(stage/'capture-evidence.parquet',args.old_index,
                               engine=engine,work=stage/'comparison')
        if comparison['owner_gate']:
            print(json.dumps(dict(stage=str(stage),comparison=comparison),sort_keys=True))
            return 2
    if args.apply:
        parts=args.table.split('.')
        if len(parts)<2 or not all(parts):
            parser.error('--table must name namespace.table')
        table=dict(namespace=parts[:-1],name=parts[-1])
        if args.create_table:
            schema=Path(__file__).resolve().parents[5]/'model/lake/captures.schema.json'
            create_table(engine=engine,work=stage/'create',catalog_root=args.catalog_root,
                table=table,schema=json.loads(schema.read_text()),location=args.table_location,
                create_namespace=args.create_namespace)
        identity=json.loads((stage/'ingested-receipts.json').read_text())['mapping_digest']
        append_rows(stage/'captures.parquet',engine=engine,work=stage/'append',
            catalog_root=args.catalog_root,table=table,keys=['receipt_key'],definition=identity)
    print(json.dumps(dict(stage=str(stage),applied=args.apply),sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
