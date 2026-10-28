"""B1 owner probe: install the production-equivalent indefinite bodies/ lock first."""
import argparse
import json
from congress_api.retention.lock_probe import EXPECTED, probe, validate_bucket


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    validate_bucket(args.bucket)
    if not args.execute:
        print(json.dumps(dict(bucket=args.bucket, dry_run=True, expected=EXPECTED)))
        return 0
    from congress_shared.storage import connect_r2
    result = probe(connect_r2(bucket=args.bucket), args.bucket)
    print(json.dumps(result, indent=2))
    return 0 if result['safe_to_lock'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
