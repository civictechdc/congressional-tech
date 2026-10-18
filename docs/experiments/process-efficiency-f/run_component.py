"""Run the preregistered large selected-pair read component with a fixed limit."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
IMAGE = 'sha256:c9d2d30b8afc862ec42f7879480624fc798473a54807b2610df471a4491d730c'


def main():
    inputs = json.loads((ROOT / 'docs/experiments/process-efficiency-f/evidence/component-inputs.json').read_text())
    mirror = Path(inputs['root'])
    results = ROOT / 'output/process-efficiency-f/component-runs-2'
    results.mkdir(exist_ok=False)
    manifest = {'image': IMAGE, 'cpus': 2, 'memory_bytes': 2 * 1024**3,
                'order': ['bytes', 'files', 'files', 'bytes'], 'commands': [], 'outcomes': []}
    for number, arm in enumerate(manifest['order'], 1):
        assert sha256((mirror / 'indexes/catalog.json').read_bytes()).hexdigest() == inputs['selector_sha256']
        temporary = results / f'tmp-{number}'; temporary.mkdir()
        command = ['docker', 'run', '--rm', '--network', 'none', '--cpus', '2', '--memory', '2g',
            '--mount', f'type=bind,source={ROOT},target=/workspace,readonly',
            '--mount', f'type=bind,source={mirror},target=/catalog,readonly',
            '--mount', f'type=bind,source={results},target=/results',
            '--workdir', f'/workspace/output/process-efficiency-f/sources/{arm}',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', f'TMPDIR=/results/tmp-{number}',
            '--env', 'PYTHONPATH=/workspace/docs/experiments/process-efficiency-f:.:packages/congress_api/src:packages/house-naming/src:packages/congress_shared/src:packages/committee_meeting/src',
            IMAGE, '/opt/venv/bin/python', '.github/scripts/offline-python.py',
            '-m', 'read_component',
            '--mirror', '/catalog', '--output', f'/results/{number}-{arm}.json',
            '--scratch-root', f'/results/tmp-{number}']
        manifest['commands'].append(command)
        with (results / f'{number}-{arm}.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        manifest['outcomes'].append({'run': f'{number}-{arm}', 'exit_code': result.returncode})
        (results / 'runs.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'{number} {arm}: exit {result.returncode}', flush=True)
        if result.returncode:
            raise SystemExit('Component failure retained; no automatic retry or capacity increase')


if __name__ == '__main__':
    main()
