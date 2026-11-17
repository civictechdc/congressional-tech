"""Unattended workflows keep one alert issue each; the nightly archive has a freshness alarm."""
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ci_alerts', ROOT / '.github/scripts/ci-alerts.py')
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)
NOW = datetime(2026, 11, 17, 14, 37, tzinfo=timezone.utc)
RUN = {'id': 44052307169, 'run_attempt': 2, 'name': 'Capture archive sources', 'conclusion': 'failure',
       'html_url': 'https://github.com/o/r/actions/runs/44052307169', 'event': 'schedule', 'head_sha': 'a' * 40}
JOBS = [{'name': 'capture', 'conclusion': 'failure', 'steps': [
    {'name': 'Set up job', 'conclusion': 'success'},
    {'name': 'Capture from the public release', 'conclusion': 'failure'},
    {'name': 'Post checkout', 'conclusion': 'skipped'}]},
    {'name': 'report', 'conclusion': 'success', 'steps': []}]


class FakeGitHub:
    """Open ci-failure issues, labels and runs as gh would list them; records every call."""

    def __init__(self, issues=(), labels=(), runs=None):
        self.issues, self.labels, self.runs, self.calls = list(issues), set(labels), runs or {}, []

    def writes(self):
        return [args[:2] for args, _ in self.calls if args[1] in {'create', 'comment', 'close'}]

    def __call__(self, *args, stdin=None):
        self.calls.append((args, stdin))
        option = lambda name: args[args.index(name) + 1]
        if args[:2] == ('issue', 'list'):
            assert option('--label') == 'ci-failure' and option('--state') == 'open'
            return json.dumps(self.issues)
        if args[:2] == ('issue', 'create'):
            assert option('--label') in self.labels
            self.issues.append({'number': len(self.issues) + 1, 'title': option('--title')})
            return ''
        if args[:2] == ('issue', 'close'):
            self.issues = [issue for issue in self.issues if issue['number'] != int(args[2])]
            return ''
        if args[:2] == ('issue', 'comment'):
            assert any(issue['number'] == int(args[2]) for issue in self.issues)
            return ''
        if args[:2] == ('label', 'list'):
            return json.dumps([{'name': name} for name in self.labels])
        if args[:2] == ('label', 'create'):
            self.labels.add(args[2])
            return ''
        if args[:2] == ('run', 'view'):
            assert args[2:6] == ('44052307169', '--attempt', '2', '--json')
            return json.dumps({'jobs': JOBS})
        if args[:2] == ('run', 'list'):
            assert option('--branch') == 'main'
            return json.dumps(self.runs.get((option('--workflow'), option('--status')), []))
        raise AssertionError(args)


@pytest.fixture
def github(monkeypatch):
    def install(**state):
        fake = FakeGitHub(**state)
        monkeypatch.setattr(alerts, 'gh', fake)
        return fake
    return install


def test_first_failure_creates_the_label_and_opens_an_issue_naming_the_failed_step(github):
    fake = github()
    alerts.failure(RUN)
    assert fake.issues == [{'number': 1, 'title': 'Capture archive sources'}]
    assert fake.labels == {'ci-failure'}
    body = next(stdin for args, stdin in fake.calls if args[:2] == ('issue', 'create'))
    for fact in [RUN['html_url'], '`schedule`', 'a' * 40, 'capture (step: Capture from the public release)']:
        assert fact in body
    assert 'report' not in body and 'Post checkout' not in body


def test_second_failure_comments_on_the_open_issue(github):
    fake = github(issues=[{'number': 7, 'title': 'Update committee data'},
                          {'number': 8, 'title': 'Capture archive sources'}], labels=['ci-failure'])
    alerts.failure(RUN)
    assert fake.writes() == [('issue', 'comment')]
    assert next(args for args, _ in fake.calls if args[1] == 'comment')[2] == '8'
    assert len(fake.issues) == 2


def test_failure_without_a_failed_job_still_reports_the_run(github, monkeypatch):
    fake = github(labels=['ci-failure'])
    monkeypatch.setitem(JOBS[0], 'conclusion', 'success')
    alerts.failure({**RUN, 'conclusion': 'timed_out'})
    body = next(stdin for args, stdin in fake.calls if args[:2] == ('issue', 'create'))
    assert '`timed_out`' in body and 'No job reported a failure' in body


def test_success_closes_the_open_issue_with_the_green_run(github):
    fake = github(issues=[{'number': 3, 'title': 'Capture archive sources'}], labels=['ci-failure'])
    alerts.recovered({**RUN, 'conclusion': 'success'})
    close = next(args for args, _ in fake.calls if args[:2] == ('issue', 'close'))
    assert close[2] == '3' and RUN['html_url'] in close[close.index('--comment') + 1]
    assert fake.issues == []


def test_success_without_an_open_issue_writes_nothing(github):
    fake = github(issues=[{'number': 3, 'title': 'Update committee data'}])
    alerts.recovered({**RUN, 'conclusion': 'success'})
    assert fake.writes() == []


def runs(capture_age, publish_age):
    def run(age, conclusion):
        finished = (NOW - age).strftime('%Y-%m-%dT%H:%M:%SZ')
        return [{'url': 'https://github.com/o/r/actions/runs/1', 'updatedAt': finished, 'conclusion': conclusion}]
    found = {}
    if capture_age is not None:
        found[(alerts.CAPTURE, 'success')] = run(capture_age, 'success')
    if publish_age is not None:
        found[(alerts.PUBLISH, 'completed')] = run(publish_age, 'failure')
    return found


@pytest.mark.parametrize('capture_age,publish_age', [
    (timedelta(hours=31), timedelta(hours=2)),
    (timedelta(hours=2), timedelta(hours=30, minutes=1)),
    (timedelta(hours=2), None),
])
def test_stale_nightly_opens_then_comments(github, capture_age, publish_age):
    fake = github(runs=runs(capture_age, publish_age))
    alerts.freshness('true', '', NOW)
    alerts.freshness('true', 'false', NOW)
    assert fake.issues == [{'number': 1, 'title': 'Nightly archive is stale'}]
    assert fake.writes() == [('label', 'create'), ('issue', 'create'), ('issue', 'comment')]


def test_fresh_nightly_closes_the_stale_issue_and_otherwise_writes_nothing(github):
    fake = github(issues=[{'number': 4, 'title': 'Nightly archive is stale'}], labels=['ci-failure'],
                  runs=runs(timedelta(hours=3), timedelta(hours=29)))
    alerts.freshness('true', '', NOW)
    assert fake.writes() == [('issue', 'close')] and fake.issues == []
    alerts.freshness('true', '', NOW)
    assert fake.writes() == [('issue', 'close')]


@pytest.mark.parametrize('enabled,disabled', [('', ''), ('false', ''), ('true', 'true')])
def test_switched_off_nightly_is_not_checked(github, enabled, disabled):
    fake = github(runs=runs(None, None))
    alerts.freshness(enabled, disabled, NOW)
    assert fake.calls == []


def test_main_reads_the_workflow_run_payload_and_switches(github, tmp_path):
    fake = github(issues=[{'number': 2, 'title': 'Capture archive sources'}], labels=['ci-failure'])
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'workflow_run': {**RUN, 'conclusion': 'success'}}))
    alerts.main(['recovered'], env={'GITHUB_EVENT_PATH': str(event)})
    assert fake.writes() == [('issue', 'close')]
    alerts.main(['freshness'], env={'ARCHIVE_CAPTURE_ENABLED': 'false'}, now=NOW)
    assert len(fake.calls) == 2


def test_script_runs_on_the_runner_python_without_project_packages():
    tree = ast.parse((ROOT / '.github/scripts/ci-alerts.py').read_text())
    imported = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= set(sys.stdlib_module_names) | {'__future__'}


def test_workflow_watches_named_workflows_with_issue_rights_only_here():
    load = lambda path: yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    names = {path.name: load(path)['name'] for path in (ROOT / '.github/workflows').glob('*.yml')}
    value = load(ROOT / '.github/workflows/ci-alerts.yml')
    trigger = value['on']['workflow_run']
    assert trigger['workflows'] == [names[name] for name in
                                    ['capture-archive.yml', 'archive-jobs.yml', 'update-data.yml', 'bls-cpi-update.yml']]
    assert {alerts.CAPTURE, alerts.PUBLISH} <= set(trigger['workflows'])
    assert trigger['types'] == ['completed'] and trigger['branches'] == ['main']
    minute, hour = value['on']['schedule'][0]['cron'].split()[:2]
    assert minute not in {'0', '00'} and 13 <= int(hour) <= 16
    assert value['permissions'] == {'contents': 'read', 'issues': 'write', 'actions': 'read'}
    assert value['env']['GH_TOKEN'] == '${{ github.token }}'
    assert set(value['jobs']) == {'failure', 'recovered', 'freshness'}
    for name, job in value['jobs'].items():
        assert int(job['timeout-minutes']) <= 10
        assert job['steps'][-1]['run'] == f'python3 -I .github/scripts/ci-alerts.py {name}'
    assert "'failure'" in value['jobs']['failure']['if'] and "'timed_out'" in value['jobs']['failure']['if']
    assert "'success'" in value['jobs']['recovered']['if']
    freshness = value['jobs']['freshness']['steps'][-1]['env']
    assert freshness == {'ARCHIVE_CAPTURE_ENABLED': '${{ vars.ARCHIVE_CAPTURE_ENABLED }}',
                         'ARCHIVE_NIGHTLY_DISABLED': '${{ vars.ARCHIVE_NIGHTLY_DISABLED }}'}
