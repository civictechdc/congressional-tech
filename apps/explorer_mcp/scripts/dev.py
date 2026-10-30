#!/usr/bin/env python3
"""Checks for this app's independent, locked DuckDB 2 runtime."""
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def main():
    if sys.argv[1:2] != ['test']:
        raise SystemExit('Usage: .venv/bin/python scripts/dev.py test [pytest arguments]')
    if Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        raise SystemExit('Run uv sync --locked in apps/explorer_mcp, then use its .venv/bin/python')
    lock = tomllib.loads((ROOT / 'uv.lock').read_text())
    for package in lock['package']:
        if package['name'] in ('duckdb', 'fastmcp', 'pyarrow', 'pytest'):
            if version(package['name']) != package['version']:
                raise SystemExit('Runtime differs from uv.lock; run uv sync --locked')
    subprocess.run([sys.executable, str(REPO / 'scripts/dev.py'), 'inventory'], cwd=REPO, check=True)
    return subprocess.call([sys.executable, str(REPO / '.github/scripts/offline-python.py'), '-m', 'pytest',
                            '-c', str(ROOT / 'pyproject.toml'), *sys.argv[2:]], cwd=ROOT)


if __name__ == '__main__':
    raise SystemExit(main())
