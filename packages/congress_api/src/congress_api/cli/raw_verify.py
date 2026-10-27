"""Owner-run raw verifier. A preview stages evidence; --apply-staged creates its pinned records."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

from congress_api.retention.body_store import BodyStore,R2Adapter
from congress_api.retention.raw_verifier import selected_captures,verify
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).resolve().parents[5]


class R2Source:
    def __init__(self,client,bucket):self.client,self.bucket=client,bucket

    def listing(self):
        pages=self.client.get_paginator('list_objects_v2').paginate(Bucket=self.bucket,Prefix='bodies/')
        for page in pages:
            for obj in page.get('Contents',[]):
                yield dict(key=obj['Key'],size=obj['Size'],etag=obj['ETag'].strip('"'))

    def get(self,key):return self.client.get_object(Bucket=self.bucket,Key=key)


def apply_staged(work,store):
    work=Path(work)
    report=json.loads((work/'report.json').read_text())
    records=work/'verification.jsonl'
    if not report.get('valid'):
        raise ValueError('Refused raw verification cannot be applied')
    with records.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest()!=report['records_sha256']:
            raise ValueError('Verification records changed after staging')
    key=report['provenance_key']
    if not key.startswith('provenance/verification/'):
        raise ValueError('Invalid verification provenance key')
    store.put(key,records,'application/x-ndjson')
    return dict(provenance=key,listed=report['listed'],checked=report['checked'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket',default='congressional-tech-raw')
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--engine-config',type=Path)
    selection=parser.add_mutually_exclusive_group()
    selection.add_argument('--captures',type=Path,help='Explicit selected old capture Parquet')
    selection.add_argument('--old-native-config',type=Path,help='Read the old selector and its exact source TablePins')
    parser.add_argument('--receipt-inventory',type=Path,help='JSON array of exact {key,path} receipt files')
    parser.add_argument('--verification-inventory',type=Path,help='JSON array of exact {key,path} gzip verification files')
    parser.add_argument('--seed')
    parser.add_argument('--apply-staged',action='store_true')
    args=parser.parse_args(argv)
    if not args.apply_staged and not all((args.engine_config,args.captures or args.old_native_config,
                                         args.receipt_inventory,args.verification_inventory)):
        parser.error('Preview requires engine config, selected captures, receipt and verification inventories')
    writer_identity(ROOT,'raw-verifier')
    from congress_shared.storage import connect_r2
    client=connect_r2(bucket=args.bucket,retries={'mode':'standard','max_attempts':5})
    if args.apply_staged:
        result=apply_staged(args.work,BodyStore(R2Adapter(client,args.bucket)))
    else:
        captures=args.captures
        if args.old_native_config:
            from congress_api.retention.r2 import R2Store
            from congress_api.retention.raw_storage import RawStorage
            captures=selected_captures(RawStorage.open(R2Store(client,args.bucket),
                NativeDatasets.from_config(args.old_native_config)))
        result=verify(R2Source(client,args.bucket),captures=captures,
            receipts=json.loads(args.receipt_inventory.read_text()),
            previous=json.loads(args.verification_inventory.read_text()),
            engine=NativeDatasets.from_config(args.engine_config),work=args.work,
            checked_at=datetime.now(timezone.utc).isoformat(),seed=args.seed)
    print(json.dumps(result,indent=2))
    return 0 if result.get('valid',True) else 1


if __name__=='__main__':raise SystemExit(main())
