"""Compare retained D1 batch evidence with the complete pinned old capture index, or
compare two capture generations (--previous-pin/--new-pin) and gate their eligibility changes."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake.capture_comparison import GenerationChange,compare_generations,compare_old
from congress_shared.custody import bounded_control_read


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-pin',type=Path,help='JSON native table pin (or a Parquet path) of the previous generation')
    parser.add_argument('--new-pin',type=Path,help='JSON native table pin (or a Parquet path) of the rebuilt generation')
    parser.add_argument('--expected',type=Path,help='JSON expected eligibility change classes for --previous-pin/--new-pin')
    parser.add_argument('--evidence-inventory',type=Path,
        help='JSON list of retained private evidence Parquet paths')
    parser.add_argument('--receipt-keys',type=Path,
        help='JSON list selecting only original receipt keys from new evidence; old rows are never filtered')
    parser.add_argument('--old-index',type=Path)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args(argv)
    if not args.engine_config:parser.error('An explicit pinned engine configuration is required')
    def metadata(path):
        with path.open('rb') as stream:
            return json.loads(bounded_control_read(stream,kind='accepted'))
    if args.previous_pin is not None or args.new_pin is not None:
        if args.previous_pin is None or args.new_pin is None:
            parser.error('A generation comparison needs both --previous-pin and --new-pin')
        pin=lambda path:str(path.resolve()) if path.suffix=='.parquet' else metadata(path)
        expected=metadata(args.expected) if args.expected is not None else None
        try:
            report=compare_generations(pin(args.previous_pin),pin(args.new_pin),
                engine=NativeDatasets.from_config(args.engine_config),work=args.work,expected=expected,
                receipt_keys=metadata(args.receipt_keys) if args.receipt_keys is not None else None)
        except GenerationChange as error:
            print(json.dumps(error.report,sort_keys=True,default=str))
            return 2
        print(json.dumps(report,sort_keys=True,default=str))
        return 0
    if args.evidence_inventory is None or args.old_index is None:
        parser.error('An oracle comparison needs --evidence-inventory and --old-index')
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
