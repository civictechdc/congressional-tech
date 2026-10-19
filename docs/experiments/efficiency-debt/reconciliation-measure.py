"""Same-body reconciliation before/after; generated local mock store only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import types

from botocore.exceptions import ClientError
from viewer_publication.continuation import Continuation
from viewer_publication.reconciliation import read_progress, MAX_READ_UPDATES

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/measure'))
from publication_costs import PublicationCosts

BASELINE = '1e572d028a53ee104c31a4ba4eeded530e34ec51'
STATE_PATH = 'packages/viewer_publication/src/viewer_publication/continuation.py'
FILES = [STATE_PATH, 'packages/viewer_publication/src/viewer_publication/reconciliation.py',
         'scripts/publication/pipeline_status.py', 'scripts/measure/publication_costs.py', 'scripts/measure/process_rss.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = subprocess.check_output(['git', 'show', f'{BASELINE}:{STATE_PATH}'], cwd=ROOT)
    before = types.ModuleType('viewer_publication._baseline_measurement')
    before.__package__ = 'viewer_publication'
    exec(compile(source, f'{BASELINE}:{STATE_PATH}', 'exec'), before.__dict__)
    current = b'current-fixture\n' * (6 * 1024**2 // 16)
    original = b'old-fixture\n' * (1024**2 // 12)
    limits = {'objects': 3, 'body_bytes': len(current) + len(original), 'repeats_per_arm': 3,
              'remote_network': False, 'seconds_per_arm': 120, 'scratch_bytes': 64 * 1024**2,
              'sampled_rss_bytes': 256 * 1024**2, 'max_observations_per_object': MAX_READ_UPDATES + 4,
              'max_latest_observation_bytes': 16384}
    (args.output / 'proposal.json').write_text(json.dumps(limits, indent=2) + '\n')
    results, expected = [], None
    for repeat in range(3):
        for arm, constructor in [('baseline', before.Continuation), ('candidate', Continuation)]:
            run = constructor(args.output / f'{arm}-{repeat}', {'fixture': 'committed, original, missing'})
            for key, payload, condition in [('viewer-publications/current', current, {'if_none_match': '*'}),
                    ('viewer-publications/original', b'future replacement', {'expected_etag': 'old'}),
                    ('viewer-publications/missing', b'future immutable', {'if_none_match': '*'})]:
                run.record('publication_write_intent', dict(key=key, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), **condition))
            costs = PublicationCosts(run.root)
            class Body(io.BytesIO):
                def read(self, size=-1):
                    raw = super().read(size)
                    costs.counts['body_read_calls'] += 1
                    costs.counts['body_read_bytes'] += len(raw)
                    return raw
            class Remote:
                gets = 0
                def get_object(self, **options):
                    self.gets += 1
                    key = options['Key']
                    if key.endswith('missing'):
                        raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
                    raw, etag = (current, 'current') if key.endswith('current') else (original, 'old')
                    return dict(Body=Body(raw), ContentLength=len(raw), ETag=etag)
            remote = Remote()
            old_replace = Path.replace
            def replace(path, destination):
                if path.name == 'reconciliation-progress.tmp': costs.counts['observation_replacements'] += 1
                return old_replace(path, destination)
            with costs.instrument(), costs.stage('reconciliation'):
                Path.replace = replace
                try: run.reconcile(remote, 'fixture')
                finally: Path.replace = old_replace
            proofs = {key: proof[1] for (_, bucket, key), proof in run._reconciled.items()}
            assert all(proof[0] is remote for proof in run._reconciled.values())
            outcome = {'state': run.value, 'proofs': proofs, 'gets': remote.gets,
                       'read_bytes': costs.counts['body_read_bytes'], 'read_calls': costs.counts['body_read_calls']}
            if expected is None: expected = outcome
            assert outcome == expected
            latest = run.root / 'reconciliation-progress.json'
            if arm == 'candidate':
                value = read_progress(latest, binding=run.value['binding'])
                assert value['state'] == 'complete' and value['checked_objects'] == 3
                assert value['observation_only'] and not value['resume_authorized'] and not value['current_readback_proof']
                assert costs.counts['observation_replacements'] <= 3 * (MAX_READ_UPDATES + 4) + 2
            result = {'arm': arm, 'repeat': repeat, 'stage': costs.stages[0], 'outcome_sha256': hashlib.sha256(json.dumps(outcome, sort_keys=True).encode()).hexdigest(),
                      'observation_bytes': latest.stat().st_size if latest.exists() else 0,
                      'gets': remote.gets}
            results.append(result)
            (args.output / f'{arm}-{repeat}.json').write_text(json.dumps(result, indent=2) + '\n')
    receipt = {'baseline_revision': BASELINE, 'baseline_source_sha256': hashlib.sha256(source).hexdigest(),
               'candidate_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'candidate_tracked_changes': subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True),
               'candidate_files': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in FILES},
               'measurement_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'python': sys.version, 'executable': sys.executable, 'limits': limits,
               'fixture_sha256': {'current': hashlib.sha256(current).hexdigest(), 'original': hashlib.sha256(original).hexdigest()},
               'results': results,
               'medians': {arm: {'seconds': statistics.median(row['stage']['seconds'] for row in results if row['arm'] == arm),
                   'serialized_characters': statistics.median(row['stage']['counts']['json_serialized_characters'] for row in results if row['arm'] == arm),
                   'fsync_calls': statistics.median(row['stage']['counts']['fsync_calls'] for row in results if row['arm'] == arm),
                   'observation_replacements': statistics.median(row['stage']['counts'].get('observation_replacements', 0) for row in results if row['arm'] == arm)} for arm in ('baseline', 'candidate')}}
    assert all(row['stage']['seconds'] < limits['seconds_per_arm'] and row['stage']['sampled_process_tree_rss_peak_bytes'] < limits['sampled_rss_bytes'] for row in results)
    assert sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file()) < limits['scratch_bytes']
    (args.output / 'comparison.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['medians'], indent=2))


if __name__ == '__main__': main()
