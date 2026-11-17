#!/usr/bin/env python3
"""Keep one GitHub issue per unattended workflow alert.

  failure    a watched workflow failed on main: open its issue, or comment on the open one
  recovered  it succeeded on main again: comment on its open issue and close it
  freshness  while the nightly capture or publish is over 30 hours old, open or comment
             on "Nightly archive is stale"; close it once both are fresh

failure and recovered read the workflow_run payload at GITHUB_EVENT_PATH. gh reads
GH_TOKEN and GH_REPO. Standard library only, so the job needs no project environment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

LABEL = 'ci-failure'
STALE_TITLE = 'Nightly archive is stale'
STALE_AFTER = timedelta(hours=30)
CAPTURE = 'Capture archive sources'
PUBLISH = 'Archive publish, backfill and maintenance'
PASSED = {'success', 'skipped', 'neutral'}


def gh(*args: str, stdin: str | None = None) -> str:
    """Run gh; its errors reach the job log and fail the job."""
    return subprocess.run(['gh', *args], input=stdin, stdout=subprocess.PIPE, text=True, check=True).stdout


def open_issue(title: str) -> int | None:
    # The list endpoint, not search: a just-created issue is listed at once.
    issues = json.loads(gh('issue', 'list', '--state', 'open', '--label', LABEL, '--limit', '200',
                           '--json', 'number,title'))
    return next((issue['number'] for issue in issues if issue['title'] == title), None)


def report(title: str, body: str) -> None:
    """Comment on the open issue with this title, or open it."""
    number = open_issue(title)
    if number is not None:
        gh('issue', 'comment', str(number), '--body-file', '-', stdin=body)
        return
    labels = json.loads(gh('label', 'list', '--limit', '200', '--json', 'name'))
    if LABEL not in {label['name'] for label in labels}:
        gh('label', 'create', LABEL, '--force', '--color', 'B60205',
           '--description', 'An unattended workflow failed on main or went stale')
    gh('issue', 'create', '--title', title, '--label', LABEL, '--body-file', '-', stdin=body)


def failure(run: dict) -> None:
    jobs = json.loads(gh('run', 'view', str(run['id']), '--attempt', str(run['run_attempt']),
                         '--json', 'jobs'))['jobs']
    lines = [f"**{run['name']}** concluded `{run['conclusion']}` on main.", '',
             f"- Run: {run['html_url']}", f"- Event: `{run['event']}`", f"- Head SHA: `{run['head_sha']}`"]
    failed = [job for job in jobs if job['conclusion'] not in PASSED]
    for job in failed:
        steps = [step['name'] for step in job.get('steps', [])
                 if step.get('conclusion') and step['conclusion'] not in PASSED]
        lines.append(f"- Failed job: {job['name']}" + (f" (step: {'; '.join(steps)})" if steps else ''))
    if not failed:
        lines.append('- No job reported a failure; open the run for details.')
    report(run['name'], '\n'.join(lines) + '\n')


def recovered(run: dict) -> None:
    number = open_issue(run['name'])
    if number is None:
        print(f"No open {LABEL} issue for {run['name']}.")
        return
    gh('issue', 'close', str(number), '--comment',
       f"Recovered: {run['html_url']} succeeded on main at `{run['head_sha']}`.")


def newest(workflow: str, status: str) -> dict | None:
    runs = json.loads(gh('run', 'list', '--workflow', workflow, '--branch', 'main', '--status', status,
                         '--limit', '1', '--json', 'url,updatedAt,conclusion'))
    return runs[0] if runs else None


def freshness(capture_enabled: str, nightly_disabled: str, now: datetime) -> None:
    if capture_enabled != 'true' or nightly_disabled == 'true':
        print('Nightly capture or publish is switched off; freshness not checked.')
        return
    lines, stale = [], False
    for label, run in [(f'successful "{CAPTURE}"', newest(CAPTURE, 'success')),
                       (f'completed "{PUBLISH}"', newest(PUBLISH, 'completed'))]:
        if run is None:
            stale = True
            lines.append(f'- Newest {label} run on main: none found')
            continue
        finished = datetime.fromisoformat(run['updatedAt'].replace('Z', '+00:00'))
        age = now - finished
        stale |= age > STALE_AFTER
        lines.append(f"- Newest {label} run on main: {run['url']} ({run['conclusion']}), "
                     f"finished {run['updatedAt']}, {age.total_seconds() / 3600:.1f} hours ago")
    checked = f"Checked {now:%Y-%m-%dT%H:%M}Z; the limit is {STALE_AFTER.total_seconds() / 3600:.0f} hours."
    if stale:
        report(STALE_TITLE, '\n'.join([checked, '', *lines]) + '\n')
        return
    number = open_issue(STALE_TITLE)
    if number is None:
        print('\n'.join(['Nightly archive is fresh. ' + checked, *lines]))
        return
    gh('issue', 'close', str(number), '--comment', '\n'.join(['Fresh again. ' + checked, '', *lines]))


def main(argv: list[str] | None = None, env=os.environ, now: datetime | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('check', choices=['failure', 'recovered', 'freshness'])
    check = parser.parse_args(argv).check
    if check == 'freshness':
        freshness(env.get('ARCHIVE_CAPTURE_ENABLED', ''), env.get('ARCHIVE_NIGHTLY_DISABLED', ''),
                  now or datetime.now(timezone.utc))
        return
    run = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())['workflow_run']
    (failure if check == 'failure' else recovered)(run)


if __name__ == '__main__':
    main()
