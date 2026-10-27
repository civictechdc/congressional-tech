"""Stage receipt-derived captures and explicitly append through native tables."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake.captures import compact_counter, stage_captures
from congress_api.lake.capture_comparison import compare_old
from congress_api.lake.tables import append_rows, create_table


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-inventory',type=Path,required=True)
    parser.add_argument('--receipt-root',type=Path)
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--validated-counter',type=Path)
    source.add_argument('--metadata',type=Path)
    parser.add_argument('--existing',type=Path)
    parser.add_argument('--old-index',type=Path)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--catalog-root',type=Path)
    parser.add_argument('--table')
    parser.add_argument('--create-table',action='store_true')
    parser.add_argument('--table-location',type=Path)
    args=parser.parse_args(argv)
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    if args.apply and (not args.catalog_root or not args.table):
        parser.error('--apply requires an explicit local catalog root and versioned table')
    if args.create_table and (not args.apply or not args.table_location):
        parser.error('--create-table requires --apply and --table-location')
    files=json.loads(args.receipt_inventory.read_text())
    if not isinstance(files,list) or not files:
        parser.error('Receipt inventory must be a nonempty list')
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
    engine=NativeDatasets.from_config(args.engine_config)
    metadata=args.metadata
    if args.validated_counter:
        metadata=compact_counter(args.validated_counter,engine=engine,
            work=args.work.parent/(args.work.name+'-metadata'))
    stage=stage_captures(normalized,engine=engine,work=args.work,
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
                create_namespace=True)
        identity=json.loads((stage/'ingested-receipts.json').read_text())['mapping_digest']
        append_rows(stage/'captures.parquet',engine=engine,work=stage/'append',
            catalog_root=args.catalog_root,table=table,keys=['receipt_key'],definition=identity)
    print(json.dumps(dict(stage=str(stage),applied=args.apply),sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
