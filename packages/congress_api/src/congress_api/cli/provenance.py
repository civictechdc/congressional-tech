"""Inspect an immutable provenance stage; --apply imports it after owner parity approval."""
import argparse
import json
from pathlib import Path

from congress_api.retention.body_store import BodyStore,R2Adapter
from congress_api.retention.provenance import apply_staged,load_stage,stage_records,finish_stage,file_pin,validate_provenance
from congress_api.retention.writer_identity import writer_identity

ROOT=Path(__file__).resolve().parents[5]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--bucket',default='congressional-tech-raw')
    parser.add_argument('--records',type=Path,help='Author new JSONL decisions into a local stage')
    parser.add_argument('--kind',choices=('reviews','recoveries'))
    parser.add_argument('--decided-at',help='Explicit timestamp for the local decision batch')
    args=parser.parse_args(argv)
    if args.records:
        if args.apply:raise ValueError('Create the stage and apply it as separate owner actions')
        if not args.kind or not args.decided_at:raise ValueError('New decisions need kind and batch timestamp')
        records=[json.loads(line) for line in args.records.read_text().splitlines()]
        for record in records:validate_provenance(args.kind,record)
        args.stage.mkdir(parents=True,exist_ok=False)
        key,count=stage_records(args.stage,args.kind,records,decided_at=args.decided_at)
        result=finish_stage(args.stage,kind=args.kind,provenance=key,records=count,
                            inputs=dict(authored_records=file_pin(args.records)))
        print(json.dumps(result,indent=2));return
    root,value=load_stage(args.stage)
    summary=dict(kind=value['kind'],records=value['records'],objects=len(value['files']),apply=False)
    if args.apply:
        identity=writer_identity(ROOT,'provenance-import')
        from congress_shared.storage import connect_r2
        client=connect_r2(bucket=args.bucket,retries={'mode':'standard','max_attempts':5})
        summary.update(apply_staged(root,BodyStore(R2Adapter(client,args.bucket))),apply=True,writer=identity)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
