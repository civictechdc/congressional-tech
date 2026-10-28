"""Report the local policy that disables Basin managed maintenance."""
import argparse
import json

from congress_api.retention.basin_maintenance import configure,MaintenanceError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-id',required=True)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--token-env',default='CLOUDFLARE_API_TOKEN')
    args=parser.parse_args(argv)
    try:
        report=configure(args.account_id,args.bucket,execute=args.execute)
    except (ValueError,MaintenanceError) as error:
        parser.exit(2,str(error)+'\n')
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
