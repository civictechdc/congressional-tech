"""Inspect an immutable provenance stage; --apply imports it after owner parity approval."""
import argparse
import json
from pathlib import Path

from congress_api.retention.body_store import BodyStore,R2Adapter
from congress_api.retention.provenance import apply_staged,load_stage
from congress_api.retention.writer_identity import writer_identity

ROOT=Path(__file__).resolve().parents[5]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--bucket',default='congressional-tech-raw')
    args=parser.parse_args(argv)
    root,value=load_stage(args.stage)
    summary=dict(kind=value['kind'],records=value['records'],objects=len(value['files']),apply=False)
    if args.apply:
        identity=writer_identity(ROOT,'provenance-import')
        from congress_shared.storage import connect_r2
        client=connect_r2(bucket=args.bucket,retries={'mode':'standard','max_attempts':5})
        summary.update(apply_staged(root,BodyStore(R2Adapter(client,args.bucket))),apply=True,writer=identity)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
