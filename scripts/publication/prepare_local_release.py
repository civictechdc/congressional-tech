#!/usr/bin/env python3
"""Prepare or resume local viewer output with bounded retries for remote reads."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from congress_api.retention.docspec import NativeDatasets
from congress_shared.storage import connect_r2
from viewer_publication import attempt, publish_viewer_r2 as publisher
from viewer_publication.publication_cli import save_report

RETRIES = {'mode': 'standard', 'total_max_attempts': 3}
READ_OPERATIONS = ('get_object', 'head_object')


class ReadOnlyClient:
    """Expose only the SDK reads used by preparation and store retry metadata."""

    def __init__(self, client):
        self.__client = client

    @property
    def meta(self):
        return self.__client.meta

    def get_object(self, **parameters):
        return self.__client.get_object(**parameters)

    def head_object(self, **parameters):
        return self.__client.head_object(**parameters)

    def __getattr__(self, name):
        raise PermissionError('Local preparation refuses SDK operation: ' + name)


def make_client(*, max_pool_connections=None):
    options = {'max_pool_connections': max_pool_connections} if max_pool_connections is not None else {}
    return ReadOnlyClient(connect_r2(connect_timeout=15, read_timeout=180,
                                     retries=dict(RETRIES), **options))


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--public-url', default=publisher.PUBLIC_URL)
    parser.add_argument('--native-config', type=Path, default=os.environ.get('DOCSPEC_CONFIG'))
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID'))
    parser.add_argument('--run-attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT'))
    parser.add_argument('--renderer-upgrade', action='store_true')
    parser.add_argument('--resume-preparation', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--metadata-cache', type=Path, help='Maintained immutable metadata disk cache')
    args = parser.parse_args(argv)
    if not args.run_id or not args.run_attempt:
        parser.error('prepare requires --run-id and --run-attempt')
    if not args.native_config:
        parser.error('prepare requires --native-config or DOCSPEC_CONFIG')
    return args


def main(argv=None):
    args = arguments(argv)
    # This operational record stays beside the preparation directory. It is not
    # part of its binding, accepted output inventory, or GitHub artifact custody.
    receipt_path = args.directory.with_name(args.directory.name + '.local-prepare-operation.json')
    receipt = dict(version=1, kind='local_preparation_operation', status='started',
        started_at=datetime.now(timezone.utc).isoformat(),
        adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        retries=dict(RETRIES), connect_timeout=15, read_timeout=180,
        allowed_operations=list(READ_OPERATIONS), directory=str(args.directory.resolve()),
        native_config=str(args.native_config.resolve()), run_id=str(args.run_id),
        run_attempt=str(args.run_attempt), renderer_upgrade=args.renderer_upgrade,
        resume_preparation=args.resume_preparation,
        metadata_cache_dir=str(args.metadata_cache.resolve()) if args.metadata_cache else None)
    save_report(receipt_path, receipt)
    try:
        native = NativeDatasets.from_config(args.native_config)
        options = {'metadata_cache_dir': args.metadata_cache} if args.metadata_cache else {}
        result = attempt.prepare(publisher, make_client(), args.directory,
            run_id=args.run_id, run_attempt=args.run_attempt, public_url=args.public_url,
            native=native, renderer_upgrade=args.renderer_upgrade,
            resume_preparation=args.resume_preparation,
            stage_event=lambda event: print(json.dumps(event, sort_keys=True), flush=True), **options)
        save_report(args.report, result)
    except BaseException as error:
        outcome = dict(status='failed', command='prepare', error_type=type(error).__name__,
            error=str(error) if isinstance(error, ValueError) else 'Preparation failed; see traceback',
            run_id=args.run_id, run_attempt=args.run_attempt)
        try:
            save_report(args.report, outcome)
            if args.directory.is_dir():
                save_report(args.directory / 'command-outcome.json', outcome)
            save_report(receipt_path, dict(receipt, status='failed', error_type=type(error).__name__,
                finished_at=datetime.now(timezone.utc).isoformat()))
        except BaseException as diagnostic:
            error.add_note('Local preparation diagnostics failed: ' + type(diagnostic).__name__)
        raise
    save_report(receipt_path, dict(receipt, status=result['status'],
        finished_at=datetime.now(timezone.utc).isoformat()))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
