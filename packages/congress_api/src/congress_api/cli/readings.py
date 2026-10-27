"""Stage bounded body readings from explicit local inputs; apply only on request."""
import argparse
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets
from congress_api.lake import readings


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',required=True,type=Path)
    parser.add_argument('--engine-config',default=os.environ.get('DOCSPEC_JOB_CONFIG'))
    args=parser.parse_args(argv)
    if not args.engine_config:
        parser.error('An explicit pinned engine configuration is required')
    spec=json.loads(args.spec.read_text())
    required={'captures','body_inventory','local_root','work','decided_at','parser'}
    allowed=required|{'existing','sniff_version','parser_version','unreadable_files','apply'}
    if not isinstance(spec,dict) or not required<=spec.keys() or spec.keys()-allowed:
        parser.error('Reading spec requires explicit local inputs, parser, time and work directory')
    apply=spec.pop('apply',None)
    if apply is not None and (not isinstance(apply,dict) or set(apply)!={'catalog_root','table'}):
        parser.error('Apply requires an explicit local catalog_root and table identifier')
    with NativeDatasets.from_config(args.engine_config) as engine:
        if engine.remote is not None:
            parser.error('This local readings command requires a local-only engine configuration')
        result=readings.stage(**spec,engine=engine)
        if apply is not None:
            result['append']=readings.append(result,engine=engine,
                work=Path(spec['work'])/'append',**apply)
    result['applied']=apply is not None
    print(json.dumps(result,default=str,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
