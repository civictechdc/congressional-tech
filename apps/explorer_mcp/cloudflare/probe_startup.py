"""Measure fresh prepare -> worker readiness -> research reads using the normal CLI.

Run under scripts/archive_watchdog.py for process-tree RSS and disk samples.
This source-runtime probe does not replace a measurement of the deployed image.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from congressional_explorer_mcp.release import load_selection

REPO = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', required=True)
    parser.add_argument('--work', type=Path, required=True, help='New durable directory for data, logs and report')
    parser.add_argument('--archive-origin')
    parser.add_argument('--probe-plan', type=Path)
    parser.add_argument('--require-research', action='store_true')
    parser.add_argument('--timeout-seconds', type=float, default=1800)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    data = args.work.resolve() / 'data'
    sampler = module('startup_process_owner', REPO / 'scripts/measure/process_rss.py')
    smoke = module('startup_mcp_smoke', Path(__file__).with_name('smoke.py'))
    plan = json.loads(args.probe_plan.read_text()) if args.probe_plan else None
    cli = [sys.executable, '-m', 'congressional_explorer_mcp.cli']
    start = time.monotonic()
    def prepare(log):
        process = sampler.start_owned([*cli, 'prepare', '--publication', args.publication,
            '--data-dir', str(data), *(['--archive-origin', args.archive_origin] if args.archive_origin else [])],
            stdout=log, stderr=log)
        try:
            code = process.wait(timeout=args.timeout_seconds)
            if code:
                raise RuntimeError(f'Prepare failed with exit {code}; see prepare.log')
        finally:
            sampler.stop_owned(process)
    with (args.work / 'prepare.log').open('w') as log:
        prepare(log)
    prepared = time.monotonic()
    selection = load_selection(data)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with (args.work / 'server.log').open('w') as log:
        process = sampler.start_owned([*cli, 'serve', '--data-dir', str(data), '--transport', 'http',
            '--warm', '--host', '127.0.0.1', '--port', str(port)], stdout=log, stderr=log)
        try:
            deadline = start + args.timeout_seconds
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with urlopen(url + '/ready', timeout=1) as response:
                        ready = json.load(response)
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Selected worker did not become ready; see server.log')
            ready_at = time.monotonic()
            assert ready['release_id'] == selection['release_id'], ready
            result = asyncio.run(smoke.check(url + '/mcp', selection['release_id'],
                plan=plan, require_research=args.require_research))
        finally:
            sampler.stop_owned(process)
    report = dict(status='passed', runtime='local source environment', publication=args.publication,
        release_id=selection['release_id'], prepare_seconds=round(prepared-start, 3),
        worker_ready_seconds=round(ready_at-prepared, 3), cold_start_seconds=round(ready_at-start, 3),
        retained_asset_bytes=sum(Path(item['path']).stat().st_size for item in selection['files'].values()),
        selection_file=str(data / 'selection.json'), readiness=ready, smoke=result,
        limits=['Qualify the actual image and hosted instance separately; this probe measures the checkout runtime.',
                'Attach the outer archive_watchdog report for process-tree RSS and disk samples.'])
    (args.work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
