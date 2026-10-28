"""Record the lead's baseline-relative landing gate without changing CI status."""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


SHARDS = {f'Offline regressions ({index}/6)' for index in range(1, 7)}
IDENTITY = re.compile(r'^(?:FAILED |ERROR |SUBFAILED\([^)]*\) )\S')
SUMMARY = re.compile(r'^(\d+ [a-z ]+(?:, \d+ [a-z ]+)*) in (\d+(?:\.\d+)?)s(?: \([^)]+\))?$')
LABELS = {'failed', 'passed', 'skipped', 'deselected', 'error', 'errors', 'xfailed',
          'xpassed', 'warning', 'warnings', 'subtests passed', 'subtests failed'}
ANSI = re.compile(r'\x1b\[[0-9;]*m')
TIMESTAMP = re.compile(r'^\d{4}-\d\d-\d\dT[0-9:.]+Z\s+')
COLLECTION = re.compile(r'^collected (\d+) items?(?: / (\d+) deselected(?: / (\d+) selected)?)?$')
EXIT_STATUS = re.compile(r'^CT_OFFLINE_EXIT_STATUS=(\d+)$')
TEST_STEP = 'Test the complete offline partition'


def verify(run, log_lines, baseline, expected_head):
    """Read each log line once; retain failure identities and six completion rows."""
    issues = []
    expected = {case for case in baseline if isinstance(case, str)} if isinstance(baseline, list) else set()
    if (not isinstance(baseline, list) or len(baseline) != 36 or len(expected) != 36
            or not all(IDENTITY.match(case) for case in expected)):
        issues.append('The pinned baseline must contain exactly 36 distinct failure identities')
    run = run if isinstance(run, dict) else {}
    if not re.fullmatch('[0-9a-f]{40}', expected_head) or run.get('headSha') != expected_head:
        issues.append('Run head differs from the qualified application')
    if run.get('event') != 'workflow_dispatch' or run.get('status') != 'completed' or run.get('conclusion') not in {'failure', 'success'}:
        issues.append('A completed workflow_dispatch result is required')
    jobs = run.get('jobs', [])
    jobs = [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []
    jobs = [job for job in jobs if str(job.get('name', '')).startswith('Offline regressions')]
    if len(jobs) != 6 or {job.get('name') for job in jobs} != SHARDS:
        issues.append('Exactly six distinct hosted shard jobs are required')
    ids = [job.get('databaseId') for job in jobs]
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
        issues.append('Hosted shard job IDs must be positive and distinct')
    failures = defaultdict(set)
    summaries = defaultdict(list)
    selected = defaultdict(list)
    exits = defaultdict(list)
    for line in log_lines:
        cells = line.rstrip('\n').split('\t', 2)
        if len(cells) != 3 or cells[0] not in SHARDS:
            continue
        name, _, payload = cells
        payload = ANSI.sub('', TIMESTAMP.sub('', payload)).strip()
        if IDENTITY.match(payload):
            failures[name].add(payload.split(' - ', 1)[0].strip())
        if match := COLLECTION.fullmatch(payload):
            count = int(match[1]) - int(match[2] or 0)
            if match[3] is not None and int(match[3]) != count:
                issues.append(f'{name}: selected collection count is inconsistent')
            selected[name].append(count)
        if match := EXIT_STATUS.fullmatch(payload):
            exits[name].append(int(match[1]))
        if match := SUMMARY.fullmatch(payload.strip('= ')):
            counts = {}
            for item in match[1].split(', '):
                number, label = item.split(' ', 1)
                if label not in LABELS or label in counts:
                    issues.append(f'{name}: invalid or duplicate pytest summary count')
                counts[label] = int(number)
            summaries[name].append(counts)
    recorded = []
    for job in jobs:
        name = job['name']
        if job.get('status') != 'completed' or job.get('conclusion') not in {'failure', 'success'}:
            issues.append(f'{name}: shard did not complete normally')
        elapsed = None
        try:
            start = datetime.fromisoformat(job['startedAt'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(job['completedAt'].replace('Z', '+00:00'))
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError('Missing timezone')
            elapsed = (end - start).total_seconds()
            if not 0 < elapsed <= 1800:
                raise ValueError('Outside the hosted time budget')
        except (KeyError, AttributeError, TypeError, ValueError):
            issues.append(f'{name}: invalid clock or exceeded 30-minute budget')
        rows = summaries[name]
        statuses = exits[name]
        if len(statuses) != 1 or statuses[0] not in {0, 1}:
            issues.append(f'{name}: missing, duplicate or abnormal runner exit status')
        collection = selected[name]
        if len(collection) != 1 or collection[0] <= 0:
            issues.append(f'{name}: exactly one positive selected collection count is required')
        if len(rows) != 1:
            issues.append(f'{name}: exactly one complete pytest summary is required')
        else:
            counts = rows[0]
            failed = counts.get('failed', 0) + counts.get('subtests failed', 0)
            errors = counts.get('errors', 0) + counts.get('error', 0)
            observed_failed = sum(case.startswith(('FAILED ', 'SUBFAILED(')) for case in failures[name])
            observed_errors = sum(case.startswith('ERROR ') for case in failures[name])
            if (failed, errors) != (observed_failed, observed_errors):
                issues.append(f'{name}: pytest counts differ from retained failure identities')
            subfailed = sum(case.startswith('SUBFAILED(') for case in failures[name])
            completed = sum(counts.get(label, 0) for label in ('passed', 'skipped', 'xfailed', 'xpassed')) + failed + errors - subfailed
            if len(collection) != 1 or completed != collection[0]:
                issues.append(f'{name}: completed node count differs from the selected collection')
            expected_exit = 1 if failed or errors else 0
            if statuses != [expected_exit]:
                issues.append(f'{name}: runner exit differs from pytest result')
            if job.get('conclusion') != ('failure' if failed or errors else 'success'):
                issues.append(f'{name}: job result differs from pytest result')
        steps = job.get('steps', [])
        steps = steps if isinstance(steps, list) else []
        test_steps = [step for step in steps if isinstance(step, dict) and step.get('name') == TEST_STEP]
        if len(test_steps) != 1:
            issues.append(f'{name}: exactly one named offline test step is required')
        for step in steps:
            if not isinstance(step, dict) or step.get('status') != 'completed':
                issues.append(f'{name}: an infrastructure or test step did not complete')
                continue
            if step.get('name') == TEST_STEP:
                expected_result = 'success' if statuses == [0] else 'failure'
                if step.get('conclusion') != expected_result:
                    issues.append(f'{name}: test step result differs from runner exit')
            elif step.get('conclusion') not in {'success', 'skipped'}:
                issues.append(f'{name}: an infrastructure or post-job step failed')
        recorded.append(dict(name=name, job_id=job.get('databaseId'), seconds=elapsed,
                             conclusion=job.get('conclusion'), summaries=rows,
                             selected_nodes=collection, runner_exits=statuses))
    observed = set().union(*failures.values())
    new, missing = sorted(observed - expected), sorted(expected - observed)
    if new:
        issues.append('Failure identities outside the pinned baseline are forbidden')
    if run.get('conclusion') != ('failure' if observed else 'success'):
        issues.append('Workflow conclusion differs from the retained test failures')
    if observed:
        status = ('red on the 36 pre-existing baseline failures, no new failures' if not missing else
                  f'red on {len(observed)} pre-existing baseline failures, no new failures; {len(missing)} resolved')
    else:
        status = f'green: no failures; {len(missing)} baseline identities resolved'
    return dict(accepted=not issues, hosted_status=status if not issues else 'not accepted',
        expected_head=expected_head, baseline=sorted(expected), observed=sorted(observed),
        new=new, missing=missing, resolved=missing, issues=issues, shards=recorded)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'log', 'baseline', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args(argv)
    baseline_bytes = args.baseline.read_bytes()
    digest = hashlib.sha256()
    def lines(stream):
        for line in stream:
            digest.update(line)
            yield line.decode('utf-8', errors='replace')
    with args.log.open('rb') as stream:
        report = verify(json.loads(args.run.read_text()), lines(stream),
                        json.loads(baseline_bytes), args.expected_head)
    report.update(baseline_sha256=hashlib.sha256(baseline_bytes).hexdigest(),
                  log_sha256=digest.hexdigest())
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    print(report['hosted_status'])
    return 0 if report['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
