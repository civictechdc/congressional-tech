"""Copy pipeline-data snapshot files into the raw bucket, create-only.

--snapshot reads a checkout's HEAD commit (the weekly job, after its force-push);
--rescue-batch reads a content-addressed batch of earlier snapshots (blobs/,
files.jsonl, commits.jsonl) without modifying it. --dry-run prints counts and
planned keys and opens no connection.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from congress_api.retention.body_files import file_digest
from congress_api.retention import pipeline_raw

ROOT = Path(__file__).resolve().parents[5]


def writer(job):
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], check=True,
                            capture_output=True, text=True).stdout.strip()
    return dict(job=job, commit=commit, lockfile_digest=file_digest(ROOT / 'uv.lock'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path, help='A pipeline-data git checkout')
    source.add_argument('--rescue-batch', type=Path, help='A content-addressed snapshot batch')
    job = os.environ.get('GITHUB_JOB')
    parser.add_argument('--job', default=f'update-data/{job}' if job else 'pipeline-raw',
                        help="The receipt's writer.job")
    parser.add_argument('--bucket', default='congressional-tech-raw')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    files = list(pipeline_raw.checkout_files(args.snapshot) if args.snapshot
                 else pipeline_raw.rescue_files(args.rescue_batch))
    if args.dry_run:
        summary = pipeline_raw.plan(files)
        summary['receipts'] = pipeline_raw.receipt_keys('<run_id>', summary['files'], '<UTC date>')
    else:
        from congress_shared.storage import connect_r2
        from congress_api.retention.r2 import R2Store

        # The capture writer's retry policy; R2Store adds its own 429 backoff.
        client = connect_r2(bucket=args.bucket, retries={'mode': 'standard', 'max_attempts': 5})
        store = R2Store(client, args.bucket)
        summary = pipeline_raw.archive(store, files, writer=writer(args.job))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
