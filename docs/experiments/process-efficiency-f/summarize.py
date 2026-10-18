"""Preserve all per-run measures and paired changes; no historical-baseline subtraction."""
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'output/process-efficiency-f'


def describe(values):
    return {'minimum': min(values), 'median': median(values), 'maximum': max(values), 'values': values}


def main():
    comparisons = {}
    for name, first, second in [('files', 'bytes', 'files'), ('cache', 'files', 'cached')]:
        rows = []
        for path in sorted((OUT / (name + '-runs')).glob('*/benchmark.json')):
            data = json.loads(path.read_text())
            rows.append({'run': path.parent.name, 'arm': path.parent.name.split('-', 1)[1],
                'status': data['status'], 'rebuild_seconds': data['rebuild_elapsed_seconds'],
                'qualification_seconds': data['qualification_elapsed_seconds'],
                'association_seconds': sum(stage['elapsed_seconds'] for stage in data['stages']
                    if stage['stage'] == 'associate_source_metadata'),
                'peak_rss_bytes': data['sampled_process_tree_peak_resident_bytes'],
                'peak_scratch_bytes': data['sampled_scratch_peak_bytes'],
                'peak_scratch_allocated_bytes': data['sampled_scratch_peak_allocated_bytes'],
                'counters': data['counters']})
        assert len(rows) == 6 and all(row['status'] == 'passed' for row in rows)
        metrics = ['rebuild_seconds', 'qualification_seconds', 'association_seconds', 'peak_rss_bytes',
                   'peak_scratch_bytes', 'peak_scratch_allocated_bytes']
        stats = {arm: {metric: describe([row[metric] for row in rows if row['arm'] == arm])
                       for metric in metrics} for arm in (first, second)}
        pairs = []
        for number in range(0, 6, 2):
            pair = {row['arm']: row for row in rows[number:number + 2]}
            pairs.append({metric: (pair[second][metric] / pair[first][metric] - 1) * 100 for metric in metrics})
        comparisons[name] = {'rows': rows, 'statistics': stats, 'paired_change_percent': pairs,
            'median_change_percent': {metric: (stats[second][metric]['median'] / stats[first][metric]['median'] - 1) * 100
                                      for metric in metrics}}
    components = []
    for path in sorted((OUT / 'component-runs-2').glob('[1-4]-*.json')):
        report = json.loads(path.read_text())
        components.append({'run': path.stem, 'arm': path.stem.split('-', 1)[1], **report})
    assert len(components) == 4
    return {'comparisons': comparisons, 'read_components': components}


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
