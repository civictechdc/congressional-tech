"""Compare retained D1 batch evidence with the complete pinned old capture index."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake.capture_comparison import compare_old
from congress_shared.custody import bounded_control_read


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-inventory',type=Path,required=True,
        help='JSON list of retained private evidence Parquet paths')
    parser.add_argument('--receipt-keys',type=Path,
        help='JSON list selecting only original receipt keys from new evidence; old rows are never filtered')
    parser.add_argument('--old-index',type=Path,required=True)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.engine_config:parser.error('An explicit pinned engine configuration is required')
    def metadata(path):
        with path.open('rb') as stream:
            return json.loads(bounded_control_read(stream,kind='accepted'))
    evidence=metadata(args.evidence_inventory)
    if (not isinstance(evidence,list) or not evidence or any(not isinstance(path,str)
            or not Path(path).is_absolute() for path in evidence)):
        parser.error('Evidence inventory requires a nonempty list of absolute Parquet paths')
    keys=metadata(args.receipt_keys) if args.receipt_keys is not None else None
    result=compare_old(evidence,args.old_index,engine=NativeDatasets.from_config(args.engine_config),
        work=args.work,receipt_keys=keys)
    print(json.dumps(result,sort_keys=True))
    return 2 if result['owner_gate'] else 0


if __name__=='__main__':raise SystemExit(main())
