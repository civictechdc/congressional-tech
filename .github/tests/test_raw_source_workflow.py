"""Exercise the deployed shell steps without credentials, acquisition, or R2 writes."""

from fnmatch import fnmatchcase
import gzip
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/capture-raw-sources.yml"


def test_filename_viewer_trigger_tracks_capture_workflow_name():
    capture = yaml.load((WORKFLOW_PATH.parent / "capture-archive.yml").read_text(), Loader=yaml.BaseLoader)
    viewer = yaml.load((WORKFLOW_PATH.parent / "archive-jobs.yml").read_text(),
                       Loader=yaml.BaseLoader)
    assert viewer["on"]["workflow_run"]["workflows"] == [capture["name"]]
# BaseLoader preserves GitHub's `on` key instead of treating it as YAML 1.1 True.
WORKFLOW = yaml.load(WORKFLOW_PATH.read_text(), Loader=yaml.BaseLoader)
STEPS = WORKFLOW["jobs"]["capture"]["steps"]
SELECT = next(step for step in STEPS if step.get("id") == "operation")
PUBLISH = next(step for step in STEPS if step.get("id") == "sync")
SUMMARY = next(step for step in STEPS if step.get("name") == "Show operation summary")


def run_step(step, directory, **env):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        cwd=directory,
        env={"PATH": os.defpath, **env},
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def recording_command(tmp_path):
    command = tmp_path / "raw-source-sync"
    command.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path('invocation.json').write_text(json.dumps(sys.argv[1:]))\n"
        "if os.environ.get('FAIL_SYNC'): sys.exit(17)\n"
        "if not os.environ.get('OMIT_SUMMARY'):\n"
        "    pathlib.Path('raw-capture-summary.json').write_text('{\"catalog_id\": \"fixture\"}')\n"
    )
    command.chmod(0o755)
    (tmp_path / 'python').symlink_to(sys.executable)
    scripts = tmp_path / '.github/scripts'
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / '.github/scripts/capture-memory-guard.py', scripts)
    writer = tmp_path / 'clean-writer'
    (writer / '.venv/bin').mkdir(parents=True)
    (writer / '.venv/bin/python').symlink_to(sys.executable)
    (writer / '.venv/bin/raw-source-sync').symlink_to(command)
    writer_scripts = writer / '.github/scripts'
    writer_scripts.mkdir(parents=True)
    shutil.copy(ROOT / '.github/scripts/capture-memory-guard.py', writer_scripts)
    return {
        "RAW_WRITER_ROOT": str(writer),
        "PATH": f"{tmp_path}:{os.defpath}",
        "GITHUB_WORKSPACE": str(tmp_path),
        "CAPTURE_LIMIT": "31",
        "CAPTURE_TRANSPORT": "direct",
        "DOCSPEC_RUNTIME_CONFIG": str(tmp_path / "native-runtime.json"),
    }


@pytest.mark.parametrize(
    ("event", "requested", "schedule", "expected"),
    [
        ("workflow_dispatch", "update", "", "update"),
        ("workflow_dispatch", "capture", "", "capture"),
        ("schedule", "", "23 3 * * *", "update"),
    ],
)
def test_events_execute_one_command_in_the_selected_mode(
    tmp_path, recording_command, event, requested, schedule, expected
):
    output = tmp_path / "outputs"
    result = run_step(
        SELECT,
        tmp_path,
        EVENT_NAME=event,
        INPUT_MODE=requested,
        EVENT_SCHEDULE=schedule,
        GITHUB_OUTPUT=str(output),
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"mode={expected}\n"
    seed = tmp_path / "pipeline-data/meeting-inventory/senate.json.gz"
    seed.parent.mkdir(parents=True)
    seed.touch()
    result = run_step(PUBLISH, tmp_path, SYNC_MODE=expected, **recording_command)
    assert result.returncode == 0, result.stderr
    args = json.loads((tmp_path / "invocation.json").read_text())
    assert args[:6] == [
        "--bucket",
        "congressional-tech-raw",
        "--index-workers",
        "2",
        "--summary",
        "raw-capture-summary.json",
    ]
    assert args[-2:] == ["--seed", "pipeline-data/meeting-inventory/senate.json.gz"]
    assert args[6:8] == ["--native-config", str(tmp_path / "native-runtime.json")]
    if expected == "update":
        assert args[8:-2] == ["--update-only"]
    else:
        assert "--rebuild-only" not in args
        assert "--capture-only" in args
        assert args[args.index("--limit") + 1] == "31"
        assert args[args.index("--transport") + 1] == "direct"
        assert "--fetcher-binary" in args

    # Use the installed triggering revision's real parser as the interface check.
    from congress_api.cli.raw_sync import parser

    parsed = parser().parse_args(args)
    assert parsed.rebuild_only is (expected == "rebuild")
    assert parsed.update_only is (expected == "update")
    assert parsed.capture_only is (expected == "capture")
    assert parsed.inspect_bodies is False
    if expected == 'capture':
        assert parsed.initial_only is True
        assert (parsed.workers, parsed.download_workers, parsed.metadata_workers) == (80, 48, 3)
        assert (parsed.max_buffer_mib, parsed.max_spool_mib, parsed.max_file_mib) == (2048, 5120, 64)
        assert parsed.max_seconds == 18000


def test_update_workflow_arguments_execute_without_acquisition(
    tmp_path, recording_command, monkeypatch
):
    """Argument parsing alone cannot detect a later CLI mode/seed rejection."""
    import boto3
    from congress_api.cli import raw_sync

    seed = tmp_path / "pipeline-data/meeting-inventory/senate.json.gz"
    seed.parent.mkdir(parents=True)
    seed.write_bytes(
        gzip.compress(b'{"documents": [{"url": "https://example.gov/report.pdf"}]}')
    )
    result = run_step(PUBLISH, tmp_path, SYNC_MODE="update", **recording_command)
    assert result.returncode == 0, result.stderr
    args = json.loads((tmp_path / "invocation.json").read_text())
    summary = tmp_path / "raw-capture-summary.json"
    summary.unlink()
    calls = []
    store = object()
    from types import SimpleNamespace
    owner = SimpleNamespace(store=store, snapshot=lambda: SimpleNamespace(identity='a' * 64))

    def forbidden(*args, **kwargs):
        pytest.fail("The workflow's catalog update entered acquisition")

    def update(actual_store, *, seeds=(), raw_storage, directory, candidate):
        assert raw_storage is owner
        assert actual_store is store
        assert len(candidate) == 32 and all(c in '0123456789abcdef' for c in candidate)
        assert directory == Path('raw-capture-summary.catalog-update') / candidate
        calls.append(list(seeds))
        return dict(counts=dict(source_rows=1, document_rows=1))

    for name in ("Archive", "RustFetcher", "run_sync"):
        monkeypatch.setattr(raw_sync, name, forbidden)
    monkeypatch.setattr(raw_sync.zyte, "token", forbidden)
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: object())
    monkeypatch.setattr(raw_sync, "R2Store", lambda *a: store)
    monkeypatch.setattr(raw_sync, "update_from_raw", update)
    for name in ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "workflow-test")
    monkeypatch.chdir(tmp_path)
    from congress_api.cli.raw_progress import ProgressLog
    from io import StringIO
    parsed = raw_sync.parser().parse_args(args)
    with ProgressLog(parsed.summary.with_suffix('.progress.json'), stream=StringIO()) as log:
        raw_sync.run(parsed, log, store=store, raw_storage=owner)
    assert len(calls) == 1
    seeds = calls[0]
    assert [row["url"] for row in seeds] == ["https://example.gov/report.pdf"]
    assert json.loads(summary.read_text())["mode"] == "update"


@pytest.mark.parametrize(
    "event,mode",
    [
        ("pull_request", "rebuild"),
        ("workflow_dispatch", ""),
        ("workflow_dispatch", "typo"),
        ("workflow_dispatch", "rebuild"),
        ("schedule", ""),
    ],
)
def test_unsupported_events_and_manual_modes_fail_closed(tmp_path, event, mode):
    output = tmp_path / "outputs"
    result = run_step(
        SELECT, tmp_path, EVENT_NAME=event, INPUT_MODE=mode, GITHUB_OUTPUT=str(output)
    )
    assert result.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize("mode", ["", "typo"])
def test_publication_never_defaults_to_acquisition(tmp_path, recording_command, mode):
    result = run_step(PUBLISH, tmp_path, SYNC_MODE=mode, **recording_command)
    assert result.returncode != 0
    assert not (tmp_path / "invocation.json").exists()


@pytest.mark.parametrize("failure", ["FAIL_SYNC", "OMIT_SUMMARY"])
def test_failed_command_or_missing_receipt_fails_the_step(
    tmp_path, recording_command, failure
):
    result = run_step(
        PUBLISH, tmp_path, SYNC_MODE="update", **recording_command, **{failure: "1"}
    )
    assert result.returncode != 0
    if failure == "FAIL_SYNC":
        assert result.returncode == 17


@pytest.mark.parametrize(
    "mode,status,outcome,receipt",
    [
        ("rebuild", "success", "success", True),
        ("rebuild", "failure", "failure", False),
        ("capture", "failure", "failure", True),
        ("capture", "success", "success", True),
        ("", "failure", "skipped", False),
    ],
)
def test_summary_reports_success_failure_and_setup_failure(
    tmp_path, mode, status, outcome, receipt
):
    if receipt:
        (tmp_path / "raw-capture-summary.json").write_text('{"catalog_id": "fixture"}')
    summary = tmp_path / "summary.md"
    result = run_step(
        SUMMARY,
        tmp_path,
        SYNC_MODE=mode,
        EVENT_NAME="push",
        CODE_REVISION="trigger-sha",
        JOB_STATUS=status,
        SYNC_OUTCOME=outcome,
        GITHUB_STEP_SUMMARY=str(summary),
    )
    assert result.returncode == 0, result.stderr
    text = summary.read_text()
    assert "Code revision: trigger-sha" in text
    assert f"Job status: {status}; sync step: {outcome}" in text
    assert ("catalog_id" in text) is receipt
    assert ("operation is unverified" in text) is not receipt
    if mode == "capture":
        assert "after verification, the dependent job updates the catalog" in text


def test_interrupted_run_keeps_last_progress_in_summary_and_artifact(tmp_path):
    (tmp_path / 'raw-capture-summary.progress.json').write_text(
        '{"stage":"read_house_xml","status":"running","completed":1200}')
    summary = tmp_path / 'summary.md'
    result = run_step(SUMMARY, tmp_path, SYNC_MODE='rebuild', EVENT_NAME='push',
                      CODE_REVISION='trigger-sha', JOB_STATUS='cancelled',
                      SYNC_OUTCOME='cancelled', GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    text = summary.read_text()
    assert 'read_house_xml' in text and '1200' in text
    assert 'interrupted' in text and 'operation is unverified' in text
    artifact = next(step for step in STEPS if step.get('uses', '').startswith('actions/upload-artifact@') and step.get('if') == '${{ always() }}')
    assert 'raw-capture-summary.progress.json' in artifact['with']['path'].splitlines()


def test_shared_writer_lock_revision_credentials_and_single_rebuild():
    assert set(WORKFLOW["jobs"]) == {'capture', 'finalize', 'update_catalog_after_capture'}
    finalizer = WORKFLOW['jobs']['finalize']
    assert finalizer['needs'] == 'capture' and 'always()' in finalizer['if']
    assert finalizer['timeout-minutes'] == '5'
    assert WORKFLOW["concurrency"] == {
        "group": "${{ github.event_name == 'push' && format('raw-source-validation-{0}', github.ref) || 'raw-source-mirror' }}",
        "cancel-in-progress": "false",
        "queue": "max",
    }
    assert WORKFLOW["permissions"] == {"contents": "read"}
    checkouts = [
        step for step in STEPS if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkouts[0]["with"]["ref"] == "${{ github.sha }}"
    assert all(step["with"]["persist-credentials"] == "false" for step in checkouts)
    assert SELECT["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "INPUT_MODE": "${{ inputs.mode }}",
        "EVENT_SCHEDULE": "${{ github.event.schedule }}",
    }
    assert PUBLISH["env"]["SYNC_MODE"] == "${{ steps.operation.outputs.mode }}"
    assert (
        PUBLISH["env"]["ZYTE_TOKEN"]
        == "${{ steps.operation.outputs.mode == 'capture' && secrets.ZYTE_TOKEN || '' }}"
    )
    native = [
        step
        for step in STEPS
        if "cargo " in step.get("run", "")
        or "test_rust_fetch_native.py" in step.get("run", "")
    ]
    assert len(native) == 2
    assert all(
        step["if"] == "(steps.operation.outputs.mode == 'capture' || steps.operation.outputs.mode == 'validate') && steps.fetcher.outputs.cache-hit != 'true'" for step in native
    )
    assert sum(step.get("run", "").count('"$RAW_WRITER_ROOT/.venv/bin/raw-source-sync" "') for step in STEPS) == 1
    assert SUMMARY["if"] == "${{ always() }}"
    artifact = next(
        step
        for step in STEPS
        if step.get("uses", "").startswith("actions/upload-artifact@") and step.get("if") == "${{ always() }}"
    )
    assert artifact["if"] == "${{ always() }}"
    for path in WORKFLOW_PATH.parent.glob("*.yml"):
        if "R2_ACCESS_KEY_ID" in path.read_text():
            writer = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            # Pages reads a hash-verified immutable generation. It does not
            # write R2 objects or participate in the archive writer lock.
            # Its read-only client calls are checked in test_filename_publication.
            if path.name == 'archive-jobs.yml':
                assert writer['concurrency']['group'] == 'archive-lake-and-publication'
                assert 'raw-source-sync' not in path.read_text()
            elif path.name == 'capture-archive.yml':
                assert writer['concurrency']['group'] == 'archive-capture'
                assert 'raw-source-sync' not in path.read_text()
            elif path.name == 'update-data.yml':
                # Weekly snapshots write only create-only bodies and run-named
                # receipts the mirror's download-* scan skips; no index, no lock.
                assert writer['concurrency']['group'] == 'update-data'
                assert 'raw-source-sync' not in path.read_text()
            elif path != WORKFLOW_PATH and path.name != 'deploy-pages.yml':
                assert writer["concurrency"] == {
                    "group": "raw-source-mirror", "cancel-in-progress": "false", "queue": "max",
                }, path


def test_verified_capture_updates_catalog_before_viewer_publication():
    update = WORKFLOW['jobs']['update_catalog_after_capture']
    assert update['needs'] == ['capture', 'finalize']
    assert "needs.capture.result == 'success'" in update['if']
    assert "needs.finalize.result == 'success'" in update['if']
    assert "needs.capture.outputs.mode == 'capture'" in update['if']
    verification = next(step for step in STEPS if step.get('name') == 'Verify completed capture checkpoint')
    assert verification.get('continue-on-error', 'false') == 'false'
    step = next(step for step in update['steps'] if step.get('name') == 'Update catalog from the verified capture')
    assert '--update-only' in step['run']
    assert '--capture-only' not in step['run']


def test_triggers_cover_parser_changes_and_exclude_generated_outputs():
    triggers = WORKFLOW["on"]
    assert set(triggers) == {"push", "workflow_dispatch", "schedule"}
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["schedule"] == [{"cron": "23 3 * * *"}]
    assert triggers["workflow_dispatch"]["inputs"]["mode"]["default"] == "update"
    patterns = triggers["push"]["paths"]
    for path in [
        "packages/house-naming/src/house_naming/data/guide.json",
        "packages/congress_api/src/congress_api/parsers/senate_page.py",
        "packages/congress_api/src/congress_api/parsers/document_cover.py",
        "packages/congress_api/src/congress_api/retention/capture_inspection.py",
        "packages/congress_api/src/congress_api/retention/pdf_tools.py",
        "packages/congress_api/src/congress_api/retention/image_tools.py",
        "packages/congress_api/src/congress_api/retention/document_index.py",
        "packages/congress_api/src/congress_api/retention/raw_catalog.py",
        "packages/congress_api/src/congress_api/cli/raw_sync.py",
        ".github/workflows/capture-raw-sources.yml",
    ]:
        assert any(fnmatchcase(path, pattern) for pattern in patterns), path
    for path in [
        "README.md",
        "apps/site/src/pages/index.astro",
        "apps/committee_youtube/data/house_documents_found.csv",
        "pipeline-data/meeting-inventory/senate.json.gz",
        "indexes/documents.parquet",
        "packages/document-catalog/src/document_catalog/store.py",
        "packages/youtube_api/src/youtube_api/main.py",
        "docs/development.md",
    ]:
        assert not any(fnmatchcase(path, pattern) for pattern in patterns), path


def test_validation_is_reused_only_for_exact_revision_and_dependency_environment():
    restores = {step['id']: step for step in STEPS if step.get('uses') == 'actions/cache/restore@v4'}
    assert set(restores) == {'verified', 'fetcher'}
    for step in restores.values():
        assert '${{ github.sha }}' in step['with']['key']
        assert '${{ steps.runtime.outputs.key }}' in step['with']['key']
        assert 'restore-keys' not in step['with']
    verification = next(step for step in STEPS if step.get('name') == 'Verify capture and recovery offline')
    assert verification['if'] == "steps.verified.outputs.cache-hit != 'true'"
    saves = [step for step in STEPS if step.get('uses') == 'actions/cache/save@v4']
    assert len(saves) == 2
    for step in saves:
        assert 'always()' not in step['if']
        assert STEPS.index(step) < STEPS.index(PUBLISH)
    assert STEPS.index(saves[0]) > STEPS.index(verification)
    assert STEPS.index(saves[1]) > next(i for i, step in enumerate(STEPS)
        if step.get('name') == 'Verify native concurrency and request pacing on loopback')


def test_loopback_tests_run_in_a_native_step():
    # Keep the frozen raw workflow's original native checks. New cases belong
    # to the maintained lane; extending this frozen workflow is a separate choice.
    native = {word for step in STEPS if 'python -m pytest' in (run := step.get('run', ''))
              and 'offline-python.py' not in run for word in run.split()
              if word.startswith('tests/') and word.endswith('.py')}
    assert native == {
        'tests/test_async_capture_native.py', 'tests/test_capture_processes_native.py',
        'tests/test_r2_body_files_native.py', 'tests/test_document_filename_viewer.py',
        'tests/test_document_review_viewer.py', 'tests/test_rust_fetch_native.py',
        'tests/test_rust_fetch_size_admission_native.py',
    }
    lane = tomllib.loads((ROOT / 'test-suites.toml').read_text())['lanes']['native-loopback']
    assert lane['marker'] == 'loopback' and lane['offline'] is False
    assert lane['required_binary_env'] == 'SOURCE_FETCH_BINARY'
    marked = {path.relative_to(ROOT).as_posix()
              for root in lane['roots'] if (ROOT / root).exists()
              for path in (ROOT / root).glob('test_*.py')
              if 'pytest.mark.loopback' in path.read_text()}
    covered = {name for name in marked if any(
        name == root or name.startswith(root.rstrip('/') + '/') for root in lane['roots'])}
    assert marked and marked == covered, sorted(marked - covered)
    maintained = yaml.load((ROOT / '.github/workflows/validate-explorer.yml').read_text(), Loader=yaml.BaseLoader)
    native_steps = [step for step in maintained['jobs']['validate']['steps']
                    if step.get('run', '').strip() == 'python scripts/dev.py test native-loopback']
    assert len(native_steps) == 1
    assert native_steps[0]['env']['SOURCE_FETCH_BINARY'].endswith('/packages/source-fetch/target/release/source-fetch')


def test_full_rebuild_and_global_reprocessing_are_not_workflow_operations():
    inputs = WORKFLOW['on']['workflow_dispatch']['inputs']
    assert inputs['mode']['options'] == ['update', 'capture']
    assert 'repair' not in inputs and 'inspect_bodies' not in inputs
    assert '--rebuild-only' not in PUBLISH['run']
    assert '--repair' not in PUBLISH['run'] and '--inspect-bodies' not in PUBLISH['run']


def test_native_runtime_is_required_before_archive_data_steps(tmp_path):
    preflight = next(step for step in STEPS if step.get('name') == 'Require an approved native runtime before archive access')
    assert STEPS.index(preflight) < STEPS.index(PUBLISH)
    assert preflight['if'] == "steps.operation.outputs.mode != 'validate'"
    result = subprocess.run([sys.executable, str(ROOT / '.github/scripts/setup-native-runtime.py'),
        '--directory', str(tmp_path / 'runtime'), '--output', str(tmp_path / 'check.json')],
        env={'PATH': os.defpath, 'PYTHONPATH': os.environ.get('PYTHONPATH', '')},
        capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'Runtime artifact descriptor' in result.stderr
    assert not (tmp_path / 'runtime').exists()
    for step in STEPS:
        if 'verify-capture-run.py' in step.get('run', ''):
            assert '--native-config "$DOCSPEC_RUNTIME_CONFIG"' in step['run']
    update = WORKFLOW['jobs']['update_catalog_after_capture']
    assert any('setup-native-runtime.py' in step.get('run','') for step in update['steps'])
    command = next(step['run'] for step in update['steps'] if step.get('name') == 'Update catalog from the verified capture')
    assert '--native-config "$DOCSPEC_RUNTIME_CONFIG"' in command


@pytest.mark.parametrize('limit', ['0', '-1', '20001', '1.5', 'oops', '18446744073709571616', '020000'])
def test_capture_refuses_invalid_attempt_caps_before_start(tmp_path, recording_command, limit):
    result = run_step(PUBLISH, tmp_path, SYNC_MODE='capture',
                      **{**recording_command, 'CAPTURE_LIMIT': limit})
    assert result.returncode != 0
    assert not (tmp_path / 'invocation.json').exists()


def test_capture_can_explicitly_select_historical_queue(tmp_path, recording_command):
    result = run_step(PUBLISH, tmp_path, SYNC_MODE='capture', INITIAL_ONLY='false', **recording_command)
    assert result.returncode == 0, result.stderr
    assert '--initial-only' not in json.loads((tmp_path / 'invocation.json').read_text())


def test_source_digest_mismatch_stops_before_acquisition(tmp_path, recording_command):
    step = next(s for s in STEPS if s.get('name') == 'Record and check capture source revision')
    script = Path(recording_command['RAW_WRITER_ROOT']) / '.github/scripts/capture-source-manifest.py'
    script.write_text("from pathlib import Path\nPath('raw-capture-source-manifest.json').write_text('{\"source_digest\":\"actual\"}')\n")
    result = run_step(step, tmp_path, EXPECTED_SOURCE_DIGEST='expected', **recording_command)
    assert result.returncode != 0
    assert 'Capture source mismatch' in result.stderr
    assert not (tmp_path / 'invocation.json').exists()


def test_capture_verification_brackets_the_single_writer():
    assert PUBLISH['env']['CAPTURE_LIMIT'] == '${{ inputs.limit }}'
    names = [step.get('name') for step in STEPS]
    assert names.index('Verify previous capture checkpoint before writes') < names.index(PUBLISH['name'])
    assert names.index('Verify completed capture checkpoint') > names.index(PUBLISH['name'])
    after = next(s for s in STEPS if s.get('name') == 'Verify completed capture checkpoint')
    assert after['if'] == "steps.operation.outputs.mode == 'capture'"
    assert WORKFLOW['on']['workflow_dispatch']['inputs']['limit']['default'] == '20000'
    assert WORKFLOW['on']['workflow_dispatch']['inputs']['initial_only']['default'] == 'true'



def test_previous_verification_requires_the_capture_destination(tmp_path, recording_command):
    step = next(s for s in STEPS if s.get('name') == 'Verify previous capture checkpoint before writes')
    result = run_step(step, tmp_path, PREVIOUS_SUMMARY=json.dumps({'bucket': 'another-bucket'}),
                      **recording_command)
    assert result.returncode != 0
    assert 'Previous capture bucket does not match' in result.stderr
    assert not (tmp_path / 'previous-capture-summary.json').exists()
    assert not (tmp_path / 'invocation.json').exists()


@pytest.mark.parametrize('requested', ['', 'capture', 'rebuild'])
def test_push_validates_without_archive_access(tmp_path, recording_command, requested):
    output = tmp_path / 'outputs'
    result = run_step(SELECT, tmp_path, EVENT_NAME='push', INPUT_MODE=requested,
                      GITHUB_OUTPUT=str(output))
    assert result.returncode == 0, result.stderr
    assert output.read_text() == 'mode=validate\n'
    # Every credential-bearing step is excluded, including failure finalization.
    for step in STEPS:
        if 'R2_ACCESS_KEY_ID' in step.get('env', {}):
            assert step['if'] in {
                "steps.operation.outputs.mode != 'validate'",
                "steps.operation.outputs.mode == 'capture'",
                "steps.operation.outputs.mode == 'capture' && inputs.previous_summary != ''",
            }
    assert WORKFLOW['jobs']['finalize']['if'] == "${{ always() && github.event_name != 'push' }}"
    seed_checkout = next(s for s in STEPS if s.get('with', {}).get('ref') == 'pipeline-data')
    assert seed_checkout['if'] == "steps.operation.outputs.mode != 'validate'"
    # Even if its step guard regresses, the writer rejects validation mode.
    result = run_step(PUBLISH, tmp_path, SYNC_MODE='validate', **recording_command)
    assert result.returncode != 0
    assert not (tmp_path / 'invocation.json').exists()


@pytest.mark.parametrize('status', ['success', 'failure'])
def test_validation_summary_does_not_claim_a_data_operation(tmp_path, status):
    summary = tmp_path / 'summary.md'
    result = run_step(SUMMARY, tmp_path, SYNC_MODE='validate', EVENT_NAME='push',
                      CODE_REVISION='trigger-sha', JOB_STATUS=status, SYNC_OUTCOME='skipped',
                      GITHUB_STEP_SUMMARY=str(summary))
    assert result.returncode == 0, result.stderr
    assert 'Validation only; no archive reads or writes.' in summary.read_text()
    assert f'Job status: {status}' in summary.read_text()
    assert 'operation is unverified' not in summary.read_text()
