"""Plan catalog maintenance; the owner applies it only after M1 qualifies Basin."""
import argparse
import json
import os

from congress_api.retention.basin_maintenance import configure,MaintenanceError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account-id',required=True)
    parser.add_argument('--bucket',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--token-env',default='CLOUDFLARE_API_TOKEN')
    args=parser.parse_args(argv)
    try:
        if not args.execute:
            report=configure(args.account_id,args.bucket)
        else:
            token=os.environ.get(args.token_env)
            if not token:raise ValueError('The owner must supply the catalog-write token in the selected environment variable')
            import requests
            with requests.Session() as session:
                session.headers['Authorization']='Bearer '+token
                report=configure(args.account_id,args.bucket,execute=True,session=session)
    except (ValueError,MaintenanceError) as error:
        parser.exit(2,str(error)+'\n')
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
