"""Summarize retained benchmark reports without altering any run."""
import argparse
import json
from pathlib import Path
from statistics import median


def summarize(directory, candidate):
    runs = []
    for path in sorted(directory.glob('*/benchmark.json')):
        report = json.loads(path.read_text())
        runs.append({
            'run': path.parent.name,
            'arm': 'baseline' if path.parent.name.endswith('-baseline') else candidate,
            'status': report['status'], 'inputs_unchanged': report['inputs_unchanged'],
            'equivalent': report['semantic_equivalence_passed'],
            'association_seconds': sum(stage['elapsed_seconds'] for stage in report['stages']
                                       if stage['stage'] == 'associate_source_metadata'),
            'complete_rebuild_seconds': report['rebuild_elapsed_seconds'],
            'qualification_seconds': report['qualification_elapsed_seconds'],
            'peak_rss_bytes': report['sampled_process_tree_peak_resident_bytes'],
            'counters': report['counters'],
        })
    if len(runs) != 6:
        raise ValueError('Exactly six alternating runs are required')
    arms = {}
    for arm in ['baseline', candidate]:
        selected = [run for run in runs if run['arm'] == arm]
        if len(selected) != 3:
            raise ValueError('Exactly three observations per arm are required')
        arms[arm] = {key: {'median': median(run[key] for run in selected),
                          'min': min(run[key] for run in selected),
                          'max': max(run[key] for run in selected)}
                     for key in ['association_seconds', 'complete_rebuild_seconds',
                                 'qualification_seconds', 'peak_rss_bytes']}
    association = 1 - arms[candidate]['association_seconds']['median'] / arms['baseline']['association_seconds']['median']
    complete = arms[candidate]['complete_rebuild_seconds']['median'] / arms['baseline']['complete_rebuild_seconds']['median'] - 1
    peak = arms[candidate]['peak_rss_bytes']['max'] / arms['baseline']['peak_rss_bytes']['max'] - 1
    gates = {'exact_semantics': all(run['equivalent'] and run['inputs_unchanged'] and run['status'] == 'passed' for run in runs),
             'association_improvement_at_least_20_percent': association >= .2,
             'complete_regression_at_most_5_percent': complete <= .05,
             'no_increased_measured_peak': peak <= 0}
    return {'runs': runs, 'arms': arms, 'association_improvement_fraction': association,
            'complete_regression_fraction': complete, 'peak_change_fraction': peak,
            'cache_adoption_gates': gates, 'all_cache_gates_passed': all(gates.values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--candidate', choices=['cached', 'one-pass'], required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory, args.candidate), indent=2))
