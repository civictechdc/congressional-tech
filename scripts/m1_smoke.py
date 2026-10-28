#!/usr/bin/env python3
"""Plan or run the pinned Basin scratch probe. Credentials stay in the inherited environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

REQUIRED = ('DOCSPEC_M1_BUCKET', 'DOCSPEC_M1_CATALOG_URI', 'DOCSPEC_M1_WAREHOUSE',
            'DOCSPEC_M1_S3_ENDPOINT', 'DOCSPEC_M1_CATALOG_TOKEN',
            'DOCSPEC_M1_ACCESS_KEY_ID', 'DOCSPEC_M1_SECRET_ACCESS_KEY')


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--binary-sha256', required=True)
    parser.add_argument('--work', type=Path, required=True, help='Fresh private local evidence directory')
    parser.add_argument('--namespace', default='docspec_m1_' + uuid.uuid4().hex)
    parser.add_argument('--rows-per-day', type=int, default=100)
    parser.add_argument('--execute', action='store_true', help='Owner only: permit scratch writes and purge')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'docspec_m1_[0-9a-f]{32}', args.namespace):
        parser.error('canonical scratch namespace required')
    if not 1 <= args.rows_per_day <= 15000:
        parser.error('rows-per-day must be between 1 and 15000')
    binary = args.binary.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error('executable probe required')
    with binary.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != args.binary_sha256:
        parser.error('probe SHA-256 mismatch')
    if args.execute:
        # Only names are inspected for credentials; their values go directly to the probe.
        if missing := [name for name in REQUIRED if name not in os.environ]:
            parser.error('missing environment names: ' + ', '.join(missing))
        bucket = os.environ['DOCSPEC_M1_BUCKET']
        if not re.fullmatch(r'cx-engine-first-lock-probe-[a-z0-9][a-z0-9-]*', bucket):
            parser.error('dedicated scratch bucket required')
        if os.environ['DOCSPEC_M1_CATALOG_URI'].rstrip('/').rsplit('/', 1)[-1] != bucket:
            parser.error('catalog must target the dedicated scratch bucket')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    common = [str(binary), '--namespace', args.namespace, '--table', 'growth',
              '--rows-per-day', str(args.rows_per_day), '--allow-scratch-writes',
              '--scratch', str(work/'spill')]
    commands = [
        ('create', []),
        ('append', ['--day', '0', '--batches', '3']),
        ('observe', ['--day', '2', '--write-records', str(work/'append.json')]),
        ('race', ['--day', '3']),
        ('purge', []),
    ]
    plan = [common + ['--action', action, '--output', str(work/(action+'.json'))] + extra
            for action, extra in commands]
    write(work/'plan.json', dict(binary_sha256=digest, namespace=args.namespace, commands=plan))
    if not args.execute:
        print(f'Plan saved to {work / "plan.json"}; no probe was invoked')
        return 0
    reports = {}
    for (action, _), command in zip(commands, plan):
        # Native failure reports are sanitized; never echo process output or exception strings.
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError(f'probe {action} failed; retain {work / (action + ".json")}')
        report = json.loads((work/(action+'.json')).read_text())
        if (report.get('release_build') is not True or report.get('namespace') != args.namespace
                or report.get('table') != 'growth' or not report.get('binary_blake3')
                or (reports and report['binary_blake3'] != reports['create']['binary_blake3'])):
            raise ValueError(f'probe {action} identity or release build check failed')
        if action in {'append', 'observe', 'race'} and report.get('table_uuid') != reports['create'].get('table_uuid'):
            raise ValueError(f'probe {action} table identity check failed')
        if action == 'create' and not report.get('table_uuid'):
            raise ValueError('probe create table identity missing')
        if action == 'append' and [(b.get('day'), b.get('commits'), b.get('work_list_rows'))
                                   for b in report.get('batches', [])] != [(i, 1, args.rows_per_day) for i in range(3)]:
            raise ValueError('probe append did not commit all three days')
        if action == 'observe' and (report.get('rows_equal') is not True
                                   or report.get('rows') != 3 * args.rows_per_day):
            raise ValueError('probe observation did not preserve exact rows')
        if action == 'race' and (report.get('guarded_conflict') is not True
                or report.get('server_snapshot_conflict') is not True
                or report.get('duplicate_rows') != 0 or report.get('repeat_work_list_rows') != 0
                or report.get('repeat_commits') != 0 or not 1 <= report.get('retries', 0) <= 3):
            raise ValueError('probe race did not reject and recover a stale commit')
        reports[action] = report
    remaining = reports['purge'].get('remaining_objects')
    if not isinstance(remaining, list) or any(not isinstance(key, str) for key in remaining):
        raise ValueError('probe purge remaining-object listing missing')
    write(work/'remaining.json', remaining)
    write(work/'summary.json', dict(namespace=args.namespace, binary_sha256=digest,
          rows=reports['observe']['rows'], race_verified=True, remaining_objects=remaining))
    print(f'Smoke completed; {len(remaining)} remaining objects listed in {work / "remaining.json"}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit('M1 stopped; retain the work directory and inspect its last action report') from None
