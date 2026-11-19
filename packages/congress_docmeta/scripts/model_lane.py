#!/usr/bin/env python3
"""Run the `docmeta-model` lane: DocMeta tests that need the fast-gemma4 engine (tokenizer, llguidance, ANE, MLX).

fast-gemma4 is an Apple Silicon checkout with no remote, so it cannot be in this repository's uv.lock. The lane
therefore runs under fast-gemma4's own interpreter, with this checkout's `congress_docmeta` first on the path.
`FAST_GEMMA4_PYTHON` names that interpreter; the default is the checkout beside this repository's main checkout.
"""
import os
from pathlib import Path
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
TESTS = PACKAGE / 'tests/model'


def sibling_work_root():
    common = subprocess.run(['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent.parent  # a worktree's main checkout, then its sibling parent dir


def engine_python():
    if named := os.environ.get('FAST_GEMMA4_PYTHON'):
        return Path(named)
    return sibling_work_root() / 'fast-gemma4/.venv/bin/python'


def decision_models_src():
    if named := os.environ.get('FAST_DECISION_MODELS_SRC'):
        return Path(named)
    return sibling_work_root() / 'fast-decision-models/src'


def main():
    if sys.argv[1:2] != ['test']:
        raise SystemExit('Usage: .venv/bin/python scripts/dev.py test docmeta-model [-- pytest arguments]')
    python = engine_python()
    if not python.is_file():
        raise SystemExit(f'No fast-gemma4 interpreter at {python}; set FAST_GEMMA4_PYTHON. This lane runs only '
                         'where the engine is installed (Apple Silicon).')
    # This checkout's package first, then sibling fast-decision-models, then any caller PYTHONPATH.
    fdm_src = decision_models_src()
    path_parts = [str(PACKAGE / 'src')]
    if fdm_src.is_dir():
        path_parts.append(str(fdm_src))
    if extra := os.environ.get('PYTHONPATH'):
        path_parts.append(extra)
    path = os.pathsep.join(path_parts)
    env = dict(os.environ, PYTHONPATH=path, PYTHONDONTWRITEBYTECODE='1')
    probe = subprocess.run([str(python), '-c', 'import congress_docmeta, fast_gemma4, fast_decision_models; print(congress_docmeta.__file__)'],
                           capture_output=True, text=True, env=env)
    if probe.returncode or not Path(probe.stdout.strip()).resolve().is_relative_to(PACKAGE / 'src'):
        raise SystemExit(f'{python} would not test this checkout on the engine: {probe.stderr.strip() or probe.stdout.strip()}')
    return subprocess.call([str(python), '-m', 'pytest', '-c', str(TESTS / 'pytest.ini'), '--rootdir', str(TESTS),
                            *(sys.argv[2:] or [str(TESTS)])], cwd=REPO, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
