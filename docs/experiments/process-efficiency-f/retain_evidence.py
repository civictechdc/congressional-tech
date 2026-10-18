"""Retain reports, commands, logs, and failed setup attempts without rewriting them."""
from hashlib import sha256
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'output/process-efficiency-f'
DEST = ROOT / 'docs/experiments/process-efficiency-f/evidence'


def main():
    sources = [ROOT / 'output/process-efficiency-f-first-tests.log']
    sources += sorted(OUT.glob('*.log'))
    for group in ('files-runs', 'cache-runs', 'component-runs', 'component-runs-2'):
        sources += sorted((OUT / group).glob('*.log'))
        sources += sorted((OUT / group).glob('*.json'))
        sources += sorted((OUT / group).glob('*/benchmark.json'))
    records = {}
    for path in sources:
        data = path.read_bytes()
        label = str(path.relative_to(ROOT / 'output')).replace('/', '-') + '.gz'
        (DEST / label).write_bytes(gzip.compress(data, mtime=0))
        records[str(path.relative_to(ROOT))] = {'sha256': sha256(data).hexdigest(), 'bytes': len(data), 'saved': label}
    (DEST / 'raw-evidence.json').write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()
