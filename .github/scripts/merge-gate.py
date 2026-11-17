#!/usr/bin/env python3
"""Pass when every other workflow run on this pull request's commit has passed.

main requires one check, this job (.github/workflows/merge-gate.yml). It waits for the other
pull-request workflow runs on HEAD_SHA and fails as soon as one has failed. A pull request
that starts no other workflow (tickets, docs) passes after the settling wait.

After fixing a failure, push a commit, or re-run the failed workflow and then this job: a
finished gate does not watch a re-run.

Cannot see: a check that is not a workflow run in this repository (another app's status).

gh reads GH_TOKEN and GH_REPO. Standard library only, so the job needs no project environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

PASSED = {'success', 'skipped', 'neutral'}
# A workflow run is created when the pull request event fires, before this job has a runner.
# The wait covers a slow registration, so "no other run" is not read off an early, empty list.
SETTLE_SECONDS = 90
POLL_SECONDS = 30


def verdict(runs: list[dict], own: int) -> tuple[str, list[str]]:
    """('fail' | 'wait' | 'pass', the runs that say so) from this commit's pull-request runs."""
    others = [run for run in runs if run['databaseId'] != own]
    line = lambda run: f"{run['workflowName']}: {run.get('conclusion') or run['status']} {run['url']}"
    failed = [run for run in others if run['status'] == 'completed' and run['conclusion'] not in PASSED]
    if failed:
        return 'fail', [line(run) for run in failed]
    waiting = [run for run in others if run['status'] != 'completed']
    if waiting:
        return 'wait', [line(run) for run in waiting]
    return 'pass', [line(run) for run in others]


def runs_for(sha: str) -> list[dict]:
    listed = subprocess.run(['gh', 'run', 'list', '--commit', sha, '--event', 'pull_request', '--limit', '100',
                             '--json', 'databaseId,workflowName,status,conclusion,url'],
                            stdout=subprocess.PIPE, text=True, check=True).stdout
    return json.loads(listed)


def main(env=os.environ, *, read=runs_for, sleep=time.sleep, clock=time.monotonic) -> int:
    sha, own, started = env['HEAD_SHA'], int(env['GITHUB_RUN_ID']), clock()
    while True:
        state, lines = verdict(read(sha), own)
        if state == 'fail':
            print('A workflow run on this commit failed:', *lines, sep='\n  ')
            return 1
        if state == 'pass' and clock() - started >= SETTLE_SECONDS:
            print(f'Every other workflow run on {sha[:12]} passed:', *(lines or ['(none started)']), sep='\n  ')
            return 0
        if state == 'wait':
            print(f'Waiting for {len(lines)}: ' + '; '.join(lines), flush=True)
        sleep(POLL_SECONDS)


if __name__ == '__main__':
    sys.exit(main())
