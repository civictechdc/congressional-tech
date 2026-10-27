"""Run the shipped reader against release bytes written by the native engine."""
import os
from pathlib import Path
import subprocess

from docspec_client.client import NativeDatasets
from viewer_publication.archive_release import build_fixture_release

ROOT = Path(__file__).parents[3]


def test_shared_reader_contract(tmp_path):
    release = tmp_path / 'release'
    build_fixture_release(ROOT / 'model/fixtures/hand-release.json', output=release,
        scratch=tmp_path / 'job', engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']))
    result = subprocess.run(['node', '--test', str(ROOT / 'apps/site/scripts/archive-reader.test.mjs')],
        cwd=ROOT / 'apps/site', env=dict(os.environ, ARCHIVE_FIXTURE=str(release)),
        capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
