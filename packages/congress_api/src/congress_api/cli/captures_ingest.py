"""Stage receipt-derived captures and explicitly append through native tables."""
import argparse
import json
import os
from pathlib import Path
import re

from congress_shared.custody import custody_identity,verify_local_file
from docspec_client.client import NativeDatasets
from congress_api.lake.captures import current_version,stage_captures
from congress_api.lake.capture_comparison import compare_old
from congress_api.lake.daily import _source_qualifications
from congress_api.lake.tables import append_rows, create_table, resolve_tables, validate_catalog_authority
from congress_api.lake.receipt_inventory import LocalReceiptStore, discover_receipts, select_receipts
from congress_api.retention.control_documents import CONTROL_LIMITS,bounded_control_read
from congress_api.retention.provenance import run_job


def _accepted_stage(stage,keys,*,engine,work,evidence=False):
    """Admit one immutable direct-source output without reopening its raw input."""
    stage=Path(stage).resolve()
    manifest_path=stage/'ingested-receipts.json'
    if custody_identity(manifest_path)[2]>CONTROL_LIMITS['accepted']:
        raise ValueError('Accepted stage manifest exceeds its metadata limit')
    proofs=[verify_local_file(manifest_path)]
    with manifest_path.open('rb') as stream:
        manifest=json.loads(bounded_control_read(stream,kind='accepted',expected=proofs[0].size_bytes))
    proofs[0].require(manifest_path)
    if (not isinstance(manifest,dict) or type(manifest.get('version')) is not int or manifest['version']!=2
            or manifest.get('mapping_digest')!=current_version()
            or not isinstance(manifest.get('input'),dict) or manifest['input'].get('kind')!='receipt-files'):
        raise ValueError('Accepted stage requires current version2 direct-receipt mapping')
    recorded=manifest.get('receipt_keys')
    if (not isinstance(recorded,list) or any(not isinstance(k,str) for k in recorded)
            or len(recorded)!=len(set(recorded)) or sorted(recorded)!=sorted(keys)):
        raise ValueError('Accepted stage receipt keys must exactly equal the full batch inventory')
    outputs=manifest.get('outputs')
    if not isinstance(outputs,list) or any(not isinstance(o,dict) for o in outputs):
        raise ValueError('Accepted stage requires native output pins')
    def hold(path,pin):
        if (not isinstance(pin,dict) or not isinstance(pin.get('sha256'),str)
                or re.fullmatch('[0-9a-f]{64}',pin['sha256']) is None
                or type(pin.get('size')) is not int or pin['size']<0):
            raise ValueError('Accepted stage requires exact SHA-256 and byte size pins')
        if custody_identity(path)[2]!=pin['size']:raise ValueError('Accepted stage file size changed')
        proofs.append(verify_local_file(path,expected_sha256=pin['sha256'],expected_size=pin['size']))
    captured=[o for o in outputs if o.get('name')=='captures']
    if len(captured)!=1 or type(captured[0].get('rows')) is not int or captured[0]['rows']<0:
        raise ValueError('Accepted stage requires one native captures output with a row count')
    hold(stage/'captures.parquet',captured[0])
    hold(stage/'job.json',manifest['input'].get('job'))
    if evidence:
        private=[o for o in outputs if o.get('name')=='capture-evidence']
        if len(private)!=1:raise ValueError('Accepted stage comparison requires a private evidence pin')
        hold(stage/'capture-evidence.parquet',private[0])
    admission=work/'admission';admission.mkdir(parents=True,exist_ok=False)
    actual=run_job(admission,engine,inputs=[dict(name='accepted',kind='parquet',path=str(stage/'captures.parquet'))],
        steps=[],outputs=[],queries=[
            dict(name='counts',sql='''SELECT count(*) AS rows,coalesce(sum(CASE WHEN receipt_key IS NULL
                OR receipt_line IS NULL OR capture_index IS NULL THEN 1 ELSE 0 END),0) AS null_keys FROM accepted'''),
            dict(name='primary_keys',sql='''SELECT count(*) AS n FROM (SELECT receipt_key,receipt_line,capture_index
                FROM accepted GROUP BY receipt_key,receipt_line,capture_index)'''),
            dict(name='receipts',sql='SELECT DISTINCT receipt_key FROM accepted ORDER BY receipt_key')])
    counts=actual['counts'][0]
    if counts['rows']!=captured[0]['rows'] or counts['null_keys'] or actual['primary_keys'][0]['n']!=counts['rows']:
        raise ValueError('Accepted stage native row count or primary keys differ from its manifest')
    if [r['receipt_key'] for r in actual['receipts']]!=sorted(recorded):
        raise ValueError('Accepted stage native receipt keys differ from its manifest')
    _require_stage(manifest,proofs)
    return stage,manifest,proofs


def _require_stage(manifest,proofs):
    if manifest['mapping_digest']!=current_version():
        raise ValueError('Accepted stage mapping changed before append')
    for proof in proofs:proof.require(proof.path)


def main(argv=None,*,engine_factory=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt-inventory',type=Path,help='Explicit JSON receipt metadata inventory')
    parser.add_argument('--receipt-root',type=Path,help='Read-only local raw root; also resolves inventory keys')
    parser.add_argument('--receipt-family',action='append',default=[],
        help='Family to discover below receipt-root; repeat for each family')
    parser.add_argument('--inventory-mode',choices=['incremental','backfill','raw-check'],default='incremental',
        help='Incremental lists dated prefixes inclusively; backfill/raw-check also list non-date segments')
    parser.add_argument('--validated-counter',type=Path)
    parser.add_argument('--source-qualifications',type=Path,
        help='Reviewed JSON map of source paths to immutable creation or qualification manifests')
    parser.add_argument('--existing',type=Path)
    parser.add_argument('--append-stage',type=Path,help='Append a pinned accepted direct-receipt stage without reparsing raw')
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
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    if args.apply and not args.table:
        parser.error('--apply requires an explicit versioned table')
    if args.apply and args.existing is not None:
        parser.error('--existing is staging-only and cannot be combined with --apply')
    if args.append_stage:
        if not args.apply or not args.receipt_inventory:
            parser.error('--append-stage requires --apply and --receipt-inventory')
        if args.validated_counter or args.receipt_root or args.receipt_family or args.source_qualifications:
            parser.error('--append-stage conflicts with raw source selection and qualification flags')
    table=None
    if args.apply:
        parts=args.table.split('.')
        if len(parts)<2 or not all(parts):
            parser.error('--table must name namespace.table')
        table=dict(namespace=parts[:-1],name=parts[-1])
    if args.create_table and (not args.apply or not args.table_location):
        parser.error('--create-table requires --apply and --table-location')
    if args.create_namespace and not args.create_table:
        parser.error('--create-namespace requires --create-table')
    if args.receipt_inventory and args.receipt_family:
        parser.error('Choose an explicit inventory or discovered families')
    if not args.receipt_inventory and (not args.receipt_root or not args.receipt_family):
        parser.error('Discovery requires --receipt-root and at least one --receipt-family')
    qualifications=None
    if args.source_qualifications:
        qualifications=json.loads(args.source_qualifications.read_text())
        if (not isinstance(qualifications,dict)
                or any(not isinstance(k,str) or not isinstance(v,str)
                       for k,v in qualifications.items())):
            parser.error('source qualifications must map source paths to manifest paths')
    engine=(engine_factory or NativeDatasets.from_config)(args.engine_config)
    existing=args.existing
    if args.apply:
        try:
            validate_catalog_authority(engine,args.catalog_root)
        except ValueError as error:
            parser.error(str(error))
        if not args.create_table:
            existing=resolve_tables(engine=engine,
                work=args.work.parent/(args.work.name+'-current'),catalog_root=args.catalog_root,
                tables={'captures':table})['captures']
    selection_work=args.work.parent/(args.work.name+'-inventory')
    if args.receipt_inventory:
        files=json.loads(args.receipt_inventory.read_text())
        if not isinstance(files,list):
            parser.error('Receipt inventory must be a list')
    else:
        files=discover_receipts(LocalReceiptStore(args.receipt_root),args.receipt_family,
            existing=existing,engine=engine,work=selection_work,mode=args.inventory_mode)
    normalized=[]
    for item in files:
        item=dict(key=item) if isinstance(item,str) else dict(item)
        if 'path' not in item and args.receipt_root is not None:
            relative=Path(item['key'])
            if relative.is_absolute() or '..' in relative.parts:
                parser.error('Receipt keys must be relative raw keys')
            item['path']=str((args.receipt_root/relative).resolve())
        if 'path' not in item and not args.validated_counter and not args.append_stage:
            parser.error('Local receipt inputs require --receipt-root or inventory paths')
        normalized.append(item)
    batch_keys=[item['key'] for item in normalized]
    if args.receipt_inventory:
        normalized=select_receipts(normalized,existing,engine=engine,work=selection_work)
    if not normalized:
        print(json.dumps(dict(stage=None,applied=False,no_work=True,receipts=0),sort_keys=True))
        return 0
    # Keep explicit qualification references for admission; the stage passes
    # only source keys and paths to the native receipt reader.
    proofs=[]
    if args.append_stage:
        if args.work.resolve()==args.append_stage.resolve():
            parser.error('--append-stage requires a separate fresh --work directory')
        args.work.mkdir(parents=True,exist_ok=False)
        stage,manifest,proofs=_accepted_stage(args.append_stage,batch_keys,engine=engine,
            work=args.work,evidence=args.old_index is not None)
    else:
        stage=stage_captures(normalized,engine=engine,work=args.work,
                             validated_counter=args.validated_counter,
                             source_qualifications=_source_qualifications(dict(
                                 source_qualifications=qualifications,validated_counter=args.validated_counter),normalized))
        manifest=json.loads((stage/'ingested-receipts.json').read_text())
    comparison=None
    if args.old_index:
        comparison=compare_old(stage/'capture-evidence.parquet',args.old_index,
                               engine=engine,work=args.work/'comparison')
        if comparison['owner_gate']:
            print(json.dumps(dict(stage=str(stage),comparison=comparison),sort_keys=True))
            return 2
    if args.apply:
        _require_stage(manifest,proofs)
        if args.create_table:
            schema=Path(__file__).resolve().parents[5]/'model/lake/captures.schema.json'
            create_table(engine=engine,work=args.work/'create',catalog_root=args.catalog_root,
                table=table,schema=json.loads(schema.read_text()),location=args.table_location,
                create_namespace=args.create_namespace)
        _require_stage(manifest,proofs)
        identity=manifest['mapping_digest']
        append_rows(stage/'captures.parquet',engine=engine,work=args.work/'append',
            catalog_root=args.catalog_root,table=table,keys=['receipt_key'],definition=identity)
    print(json.dumps(dict(stage=str(stage),applied=args.apply),sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
