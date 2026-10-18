"""Run the preregistered source-context arms through the existing benchmark."""
import argparse
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', choices=['cached', 'one-pass'], required=True)
    parser.add_argument('--image', default='congressional-process-python:local')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    evidence = root / 'output/process-efficiency-d'
    results = evidence / (args.candidate + '-runs')
    results.mkdir(exist_ok=False)
    order = ['baseline', args.candidate, args.candidate, 'baseline', 'baseline', args.candidate]
    image = subprocess.check_output(['docker', 'image', 'inspect', args.image, '--format', '{{.Id}}'], text=True).strip()
    manifest = {'image': image, 'cpus': 2, 'memory_bytes': 2 * 1024**3,
                'cache_condition': 'warm uncontrolled OS cache', 'order': order, 'commands': []}
    started = time.monotonic()
    for number, arm in enumerate(order, 1):
        temporary = results / f'tmp-{number}'
        temporary.mkdir()
        command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '2', '--memory', '2g',
            '--mount', f'type=bind,source={root},target=/workspace,readonly',
            '--mount', f'type=bind,source={results},target=/results',
            '--workdir', f'/workspace/output/process-efficiency-d/{arm}',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', f'TMPDIR=/results/tmp-{number}',
            '--env', 'PYTHONPATH=.:packages/congress_api/src:packages/house-naming/src:packages/congress_shared/src:packages/committee_meeting/src',
            args.image, '/opt/venv/bin/python', '.github/scripts/offline-python.py', '-m', 'scripts.benchmark_core_rebuild',
            '--mirror', '/workspace/output/process-efficiency-d/fixture-v2',
            '--reference', '/workspace/output/process-efficiency-d/reference',
            '--output', f'/results/{number}-{arm}', '--workers', '1', '--max-peak-gib', '2',
            '--code-revision', '24137dd08241c34f1632afcd78a80a6138e5779d' + ('' if arm == 'baseline' else '+' + arm)]
        manifest['commands'].append(command)
        (results / 'runs.json').write_text(json.dumps(manifest, indent=2) + '\n')
        with (results / f'{number}-{arm}.log').open('w') as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        print(f'{number} {arm}: exit {completed.returncode}', flush=True)
        if completed.returncode:
            raise SystemExit('Failed run retained; inspect its log and benchmark report before continuing')
        if time.monotonic() - started > 30 * 60:
            raise SystemExit('Benchmark time bound reached')


if __name__ == '__main__':
    main()
