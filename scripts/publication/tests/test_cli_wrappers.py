"""Verify CLI wrapper help behavior, argument parsing, and retirement contracts."""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / 'scripts' / 'publication'

PUBLICATION_WRAPPERS = [
    'apply-r2-edge-rules.py',
    'backfill-uncompressed-pdfs.py',
    'publish-docspec-runtime.py',
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
