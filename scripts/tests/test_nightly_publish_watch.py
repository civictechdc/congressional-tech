"""Durable status, failure tracking, notification, and launchd watch for nightly_publish (ct-b7bv)."""
import datetime
import fcntl
import importlib.util
import json
from pathlib import Path
import plistlib

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location('nightly_publish_watch', ROOT / 'scripts/nightly_publish.py')
nightly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nightly)


def test_record_run_state_tracks_latest_summary_and_clears_last_failure_on_recovery(tmp_path):
    nightly_dir = tmp_path / '.cache/archive-release/nightly'
    fail_dir = nightly_dir / '20261112T053000.000000Z'
    fail_dir.mkdir(parents=True)
    failed = dict(started='20261112T053000.000000Z', finished='20261112T054000Z',
                  status='failed', step='publish', exit=1, commit='a' * 40)
    (fail_dir / 'summary.json').write_text(json.dumps(failed) + '\n')

    nightly.record_run_state(nightly_dir, failed, summary_path=fail_dir / 'summary.json')
    assert json.loads((nightly_dir / 'latest-summary.json').read_text())['status'] == 'failed'
    assert json.loads((nightly_dir / 'last-failure.json').read_text())['step'] == 'publish'

    # Prepare-only runs must not clear an unacknowledged production failure.
    prep_dir = nightly_dir / '20261112T060000.000000Z'
    prep_dir.mkdir(parents=True)
    prepared = dict(started='20261112T060000.000000Z', finished='20261112T060500Z',
                    status='prepared', exit=0, commit='a' * 40)
    nightly.record_run_state(nightly_dir, prepared, summary_path=prep_dir / 'summary.json', prepare_only=True)
    assert (nightly_dir / 'last-failure.json').is_file()

    ok_dir = nightly_dir / '20261112T070000.000000Z'
    ok_dir.mkdir(parents=True)
    recovered = dict(started='20261112T070000.000000Z', finished='20261112T072500Z',
                     status='ok', exit=0, commit='b' * 40)
    (ok_dir / 'summary.json').write_text(json.dumps(recovered) + '\n')
    nightly.record_run_state(nightly_dir, recovered, summary_path=ok_dir / 'summary.json')
    assert json.loads((nightly_dir / 'latest-summary.json').read_text())['status'] == 'ok'
    assert not (nightly_dir / 'last-failure.json').exists()


def test_check_status_detects_missing_failed_stale_running_and_healthy_runs(tmp_path):
    main = tmp_path / 'main'
    nightly_dir = main / '.cache/archive-release/nightly'
    now = datetime.datetime(2026, 11, 12, 13, 30, tzinfo=datetime.timezone.utc)

    missing, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 1 and missing['status'] == 'missing'

    # Historical stamp directory fallback (even before latest-summary.json exists).
    old_dir = nightly_dir / '20261110T053000.000000Z'
    old_dir.mkdir(parents=True)
    old_summary = dict(started='20261110T053000.000000Z', finished='20261110T055500Z',
                       status='ok', exit=0, commit='a' * 40)
    (old_dir / 'summary.json').write_text(json.dumps(old_summary) + '\n')
    stale, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 1 and stale['status'] == 'stale'

    # While the nightly lock is actively held, a stale previous summary reports running (exit 0).
    with (nightly_dir / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        running, code = nightly.check_status(main, max_age_hours=30.0, now=now)
        assert code == 0 and running['status'] == 'running' and running['running'] is True

    # Fresh failure returns failed (exit 1).
    fail_dir = nightly_dir / '20261112T103000.000000Z'
    fail_dir.mkdir(parents=True)
    failed = dict(started='20261112T103000.000000Z', finished='20261112T104500Z',
                  status='failed', step='publish', exit=1, commit='c' * 40)
    (fail_dir / 'summary.json').write_text(json.dumps(failed) + '\n')
    nightly.record_run_state(nightly_dir, failed, summary_path=fail_dir / 'summary.json')
    bad, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 1 and bad['status'] == 'failed'

    # Fresh ok run clears failure and returns ok (exit 0).
    ok_dir = nightly_dir / '20261112T110000.000000Z'
    ok_dir.mkdir(parents=True)
    good = dict(started='20261112T110000.000000Z', finished='20261112T112500Z',
                status='ok', exit=0, commit='d' * 40)
    (ok_dir / 'summary.json').write_text(json.dumps(good) + '\n')
    nightly.record_run_state(nightly_dir, good, summary_path=ok_dir / 'summary.json')
    healthy, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 0 and healthy['status'] == 'ok' and healthy['age_hours'] == 2.08

    # Corrupt state pointer reports failed cleanly rather than raising JSONDecodeError.
    (nightly_dir / 'latest-summary.json').write_text('{corrupt')
    corrupt, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 1 and corrupt['status'] == 'failed' and 'corrupt nightly state' in corrupt['reason']

    # Malformed timestamp or non-dict JSON also reports failed + notifies cleanly instead of raising.
    notified = []
    (nightly_dir / 'latest-summary.json').write_text(json.dumps(dict(
        started='not-a-timestamp', finished='still-not-a-timestamp', status='ok', exit=0,
    )))
    bad_stamp, code = nightly.check_status(
        main, max_age_hours=30.0, notify=True, now=now,
    )
    assert code == 1 and bad_stamp['status'] == 'failed' and 'corrupt nightly state' in bad_stamp['reason']

    (nightly_dir / 'latest-summary.json').write_text(json.dumps(good))
    (nightly_dir / 'last-failure.json').write_text('[]')
    bad_shape, code = nightly.check_status(main, max_age_hours=30.0, now=now)
    assert code == 1 and bad_shape['status'] == 'failed' and 'corrupt nightly state' in bad_shape['reason']


def test_notify_failure_posts_webhook_runs_command_and_never_raises(tmp_path, monkeypatch):
    main = tmp_path / 'main'
    remote_runtime = main / '.cache/archive-release/remote-runtime'
    remote_runtime.mkdir(parents=True)
    (remote_runtime / 'notify.json').write_text(json.dumps(dict(
        webhook_url='https://hooks.example.invalid/nightly',
        command=['/opt/tools/notify-hook'],
        macos_notification=False,
    )))

    posted = []
    commands = []

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout=0):
        posted.append((request.full_url, json.loads(request.data.decode('utf-8')), timeout))
        return FakeResponse()

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        raise OSError('hook temporarily broken')

    monkeypatch.setattr(nightly.urllib.request, 'urlopen', fake_urlopen)
    monkeypatch.setattr(nightly.subprocess, 'run', fake_run)

    payload = dict(status='failed', step='publish', exit=1, started='20261112T053000.000000Z')
    delivered = nightly.notify_failure(main, payload, reason='step publish exited 1')
    assert posted and posted[0][0] == 'https://hooks.example.invalid/nightly'
    assert posted[0][1]['reason'] == 'step publish exited 1'
    assert commands and commands[0][0] == ['/opt/tools/notify-hook']
    assert delivered['webhook'] == 'sent' and 'OSError' in delivered['command_error']


def test_install_watch_writes_durable_launchd_watcher_agent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(nightly, 'real_tool', lambda name: f'/opt/tools/{name}/bin/{name}')
    monkeypatch.setattr(nightly.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(nightly.subprocess, 'run', lambda command, **options: calls.append(command))
    (tmp_path / 'Library/LaunchAgents').mkdir(parents=True)

    assert nightly.install_watch(tmp_path / 'main', 8, 30, 30.0) == 0
    plist_path = tmp_path / 'Library/LaunchAgents' / f'{nightly.WATCH_LABEL}.plist'
    agent = plistlib.loads(plist_path.read_bytes())
    assert agent['Label'] == nightly.WATCH_LABEL
    assert '--status' in agent['ProgramArguments'] and '--notify' in agent['ProgramArguments']
    assert agent['StartCalendarInterval'] == {'Hour': 8, 'Minute': 30}
    assert [command[1] for command in calls] == ['bootout', 'bootstrap']
