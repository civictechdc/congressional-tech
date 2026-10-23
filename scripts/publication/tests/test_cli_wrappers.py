"""Verify CLI wrapper help behavior, argument parsing, and retirement contracts."""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / 'scripts' / 'publication'

PUBLICATION_WRAPPERS = [
    'publish-viewer-r2.py',
    'publish-filename-viewer.py',
    'apply-r2-edge-rules.py',
    'backfill-uncompressed-pdfs.py',
    'publish-docspec-runtime.py',
    'filename-test-fixture.py',
]


@pytest.mark.parametrize('script_name', PUBLICATION_WRAPPERS)
def test_all_publication_wrappers_help_exits_zero(script_name):
    script_path = SCRIPTS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), '--help'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f'{script_name} --help failed with code {result.returncode}:\n{result.stderr}'
    assert 'usage:' in result.stdout.lower()


def test_publish_filename_viewer_help_contains_deprecation():
    script_path = SCRIPTS_DIR / 'publish-filename-viewer.py'
    result = subprocess.run(
        [sys.executable, str(script_path), '--help'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert 'Direct viewer generation is retired' in result.stdout
    assert 'publish-viewer-r2.py prepare' in result.stdout


def test_publish_filename_viewer_execution_raises_retirement_error():
    script_path = SCRIPTS_DIR / 'publish-filename-viewer.py'
    result_bare = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_bare.returncode == 1
    assert 'Direct viewer generation is retired; use publish-viewer-r2.py prepare with explicit native storage.' in result_bare.stderr

    result_args = subprocess.run(
        [sys.executable, str(script_path), '--output', '/tmp/ignored'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_args.returncode == 1
    assert 'Direct viewer generation is retired; use publish-viewer-r2.py prepare with explicit native storage.' in result_args.stderr


def test_filename_test_fixture_help_does_not_create_directory():
    script_path = SCRIPTS_DIR / 'filename-test-fixture.py'
    help_dir = ROOT / '--help'
    assert not help_dir.exists(), '--help directory already exists before test!'

    result = subprocess.run(
        [sys.executable, str(script_path), '--help'],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert 'usage: filename-test-fixture.py' in result.stdout
    assert not help_dir.exists(), '--help directory was created on disk by --help invocation!'


def test_filename_test_fixture_no_args_exits_with_code_2():
    script_path = SCRIPTS_DIR / 'filename-test-fixture.py'
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert 'error: the following arguments are required: root' in result.stderr


def test_filename_test_fixture_generates_fixture(tmp_path):
    script_path = SCRIPTS_DIR / 'filename-test-fixture.py'
    fixture_dir = tmp_path / 'test_fixture'
    result = subprocess.run(
        [sys.executable, str(script_path), str(fixture_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert (fixture_dir / 'indexes' / 'catalog.json').is_file()
    assert (fixture_dir / 'expected.json').is_file()
    assert (fixture_dir / 'source-records.json').is_file()
