"""Bounded offline publication comparison against the frozen pre-change reader.

Reuses the previous experiment's receipt and watchdog helpers, not its packed
membership candidate. Both arms execute real source, pinned by Git revision.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASELINE = '3b87599d27603195146afc36bb30e75ebda8af56'
VIEWER = ROOT / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
PUBLISHER = ROOT / 'apps/site/scripts/publish-filename-viewer.py'
HELPER = ROOT / 'docs/experiments/efficiency-debt/catalog_measure.py'
spec = importlib.util.spec_from_file_location('catalog_previous_helpers', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def frozen(path, name):
    relative = str(path.relative_to(ROOT))
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{relative}'], cwd=ROOT)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def inventory(folder):
    return {str(p.relative_to(folder)): dict(bytes=p.stat().st_size, sha256=helper.digest(p))
            for p in folder.rglob('*') if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['run', 'arm'])
    parser.add_argument('output', type=Path)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--kind', choices=['baseline', 'candidate'])
    parser.add_argument('--measure', choices=['measure', 'publish'])
    args = parser.parse_args()
    if args.operation == 'arm':
        normal_load = helper.load
        helper.viewer = lambda _: frozen(VIEWER, 'measured_catalog') if args.kind == 'baseline' else normal_load(VIEWER, 'measured_catalog')
        helper.load = lambda path, name: frozen(path, name) if args.kind == 'baseline' and path == PUBLISHER else normal_load(path, name)
        helper.arm(args.fixture, args.output, args.kind, args.measure)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    fixture_before = inventory(args.fixture)
    helper.save(args.output / 'proposal.json', dict(baseline_revision=BASELINE,
        candidate_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        candidate_sources={str(p.relative_to(ROOT)): helper.digest(p) for p in (VIEWER, PUBLISHER)},
        harness_sha256=helper.digest(__file__), helper_sha256=helper.digest(HELPER),
        fixture=fixture_before, maximum_document_groups=32768, deadline_per_child_seconds=helper.DEADLINE,
        sampled_rss_ceiling=helper.CEILING, output_ceiling=helper.OUTPUT_CEILING,
        scope='Existing closed fixture only; no acquisition, rebuild, live publication or held-out work.'))
    receipts = {'baseline': {}, 'candidate': {}}
    for sample in range(3):
        # Reverse order on the middle sample to avoid always favoring one arm.
        for kind in (['candidate', 'baseline'] if sample == 1 else ['baseline', 'candidate']):
            for operation in ('measure', 'publish'):
                name = f'{kind}-{operation}-{sample}'
                helper.guarded([sys.executable, str(Path(__file__).resolve()), 'arm', str(args.output / name),
                    '--fixture', str(args.fixture), '--kind', kind, '--measure', operation],
                    args.output / (name + '-watchdog.json'))
                receipts[kind].setdefault(operation, []).append(json.loads((args.output / name / 'receipt.json').read_text()))
    baseline = receipts['baseline']['publish'][0]
    for kind in receipts.values():
        for receipt in kind['publish']:
            assert baseline['files'] == receipt['files']
            assert baseline['manifest'] == receipt['manifest']
        assert all(row['readers_closed'] and not row['search_indexes_built'] for row in kind['measure'])
    assert fixture_before == inventory(args.fixture)
    summary = {}
    for kind, arms in receipts.items():
        summary[kind] = dict(
            constructor_seconds_median=statistics.median(r['constructor_seconds'] for r in arms['measure']),
            constructor_highwater_rss_median=statistics.median(r['constructor_highwater_rss'] for r in arms['measure']),
            publication_seconds_median=statistics.median(r['seconds'] for r in arms['publish']),
            publication_highwater_rss_median=statistics.median(r['highwater_rss'] for r in arms['publish']),
            arrow_bytes=arms['measure'][0]['arrow_bytes'],
            samples={operation: [{key: r[key] for key in ('constructor_seconds', 'constructor_highwater_rss')}
                if operation == 'measure' else {key: r[key] for key in ('seconds', 'highwater_rss')}
                for r in rows] for operation, rows in arms.items()})
    helper.save(args.output / 'summary.json', dict(results=summary, parity=dict(
        all_payload_bytes_equal=True, all_non_timestamp_manifest_values_equal=True,
        payload_files=len(baseline['files']), fixture_unchanged=True,
        readers_closed=True, samples_per_arm=3,
        normalization='Only manifest published_at removed; every other manifest value and payload hash/size compared.'),
        payload_inventory=baseline['files']))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
