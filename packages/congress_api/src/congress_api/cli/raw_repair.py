"""Owner-only B12 repair commands. Preparation is local; writes require --apply."""
import argparse
import json
from pathlib import Path

from congress_api.retention.body_store import BodyStore,R2Adapter
from congress_api.retention.raw_repair import prepare_repair,apply_flat,apply_native,restore_missing,load_repair
from congress_api.retention.raw_verifier import selected_captures
from congress_api.retention.writer_identity import writer_identity
from docspec_client.client import NativeDatasets

ROOT=Path(__file__).resolve().parents[5]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--captures',type=Path,help='Pinned flat old index; never a raw receipt')
    mode.add_argument('--old-native-config',type=Path,help='Selected old native index')
    mode.add_argument('--restore-input',type=Path,help='JSON rows {key,stored_path,stored_sha256} from retained exact bytes')
    parser.add_argument('--repairs',type=Path,help='Native B9 digest-repairs.parquet')
    parser.add_argument('--expected',help='Flat index SHA-256 or selected raw manifest identity')
    parser.add_argument('--engine-config',type=Path)
    parser.add_argument('--work',type=Path)
    parser.add_argument('--bucket',default='congressional-tech-raw')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args(argv)
    if args.restore_input:
        rows=json.loads(args.restore_input.read_text())
        if not args.apply:
            print(json.dumps(dict(mode='missing-body-restoration',objects=len(rows),apply=False)))
            return
    elif not args.work or not args.expected or not args.apply and not all((args.repairs,args.engine_config)):
        parser.error('Index preparation needs work, expected identity, repairs and engine config')
    if args.apply and not args.restore_input and load_repair(args.work)['expected']!=args.expected:
        raise ValueError('Explicit capture identity differs from the reviewed repair stage')
    client=None
    if args.old_native_config or args.restore_input:
        writer_identity(ROOT,'old-raw-repair')
        from congress_shared.storage import connect_r2
        client=connect_r2(bucket=args.bucket,retries={'mode':'standard','max_attempts':5})
    storage=None
    if args.old_native_config:
        from congress_api.retention.r2 import R2Store
        from congress_api.retention.raw_storage import RawStorage
        storage=RawStorage.open(R2Store(client,args.bucket),NativeDatasets.from_config(args.old_native_config))
    if args.restore_input:
        store=BodyStore(R2Adapter(client,args.bucket))
        result=[dict(key=row['key'],outcome=restore_missing(store,row['key'],row['stored_path'],
            expected_stored_sha256=row['stored_sha256']).outcome) for row in rows]
    elif args.apply:
        result=apply_native(args.work,storage) if storage else apply_flat(args.work,args.captures)
    else:
        result=prepare_repair(selected_captures(storage) if storage else args.captures,args.repairs,
            engine=NativeDatasets.from_config(args.engine_config),work=args.work,expected=args.expected)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
