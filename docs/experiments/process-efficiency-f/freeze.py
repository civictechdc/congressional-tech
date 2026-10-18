"""Freeze the current F route, preceding bytes route, and optional cache arm."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'output/process-efficiency-f'
BASE = '5afecfc'
CHANGED = ['catalog_cache', 'catalog_publication', 'catalog_staging', 'document_index', 'r2', 'raw_archive', 'raw_catalog']


def main():
    sources = OUTPUT / 'sources'
    sources.mkdir(exist_ok=False)
    candidate = sources / 'files'
    for name in ('packages', 'scripts', '.github/scripts'):
        shutil.copytree(ROOT / name, candidate / name,
            ignore=shutil.ignore_patterns('__pycache__', 'node_modules', '.venv', 'target'))
    baseline = sources / 'bytes'
    shutil.copytree(candidate, baseline)
    for name in CHANGED:
        relative = f'packages/congress_api/src/congress_api/retention/{name}.py'
        (baseline / relative).write_bytes(subprocess.check_output(['git', 'show', BASE + ':' + relative], cwd=ROOT))
    cache = sources / 'cached'
    shutil.copytree(candidate, cache)
    (cache / 'tests').mkdir()
    for name in ('test_document_source_context.py', 'test_core_benchmark.py'):
        shutil.copyfile(ROOT / 'tests' / name, cache / 'tests' / name)
    patch = (ROOT / 'docs/experiments/process-efficiency-d/rejected-cache.patch').read_text()
    subprocess.run(['patch', '-p1'], input=patch, text=True, cwd=cache, check=True)
    for path in cache.rglob('*.orig'):
        path.unlink()
    frozen = {}
    for arm in (baseline, candidate, cache):
        frozen[arm.name] = {str(path.relative_to(arm)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(arm.rglob('*')) if path.is_file()}
    (ROOT / 'docs/experiments/process-efficiency-f/evidence/freeze.json').write_text(
        json.dumps({'bytes_source_base': BASE, 'arms': frozen}, indent=2) + '\n')


if __name__ == '__main__':
    main()
