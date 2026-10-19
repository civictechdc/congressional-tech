"""Bounded local journal comparison; no network, acquisition, or catalog build."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/measure'))
from publication_costs import PublicationCosts
from viewer_publication.local import LocalContinuation
from viewer_publication.client import GuardedPublicationClient

BASELINE = '75820f3f6dcb5ea52fece46c77af27ffd1a5759a'
STATE_PATH = 'packages/viewer_publication/src/viewer_publication/continuation.py'
DISPATCH_PATH = 'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    baseline_source = subprocess.check_output(['git', 'show', f'{BASELINE}:{STATE_PATH}'], cwd=ROOT)
    baseline_dispatch = subprocess.check_output(['git', 'show', f'{BASELINE}:{DISPATCH_PATH}'], cwd=ROOT)
    module = types.ModuleType('local_events_baseline')
    exec(compile(baseline_source, f'{BASELINE}:{STATE_PATH}', 'exec'), module.__dict__)
    results = []
    expected = None
    for repeat in range(3):
        for arm, constructor in [('baseline', module.Continuation), ('candidate', LocalContinuation)]:
            root = args.output / f'{arm}-{repeat}'
            costs = PublicationCosts(root)
            class Remote:
                def __init__(self): self.objects = {}; self.puts = 0; self.gets = 0
                def put_object(self, **options):
                    self.puts += 1
                    body = options['Body']
                    etag = hashlib.sha256(body).hexdigest()
                    self.objects[options['Key']] = body
                    return {'ETag': etag}
                def get_object(self, **options):
                    self.gets += 1
                    body = self.objects[options['Key']]
                    return dict(Body=io.BytesIO(body), ContentLength=len(body), ETag=hashlib.sha256(body).hexdigest())
            remote = Remote()
            with costs.instrument(), costs.stage('local-normal'):
                run = constructor(root, {'fixture': '128 deterministic writes; four accepted phases'})
                run.value['versions']['indexes/catalog.json'] = None
                run.flush()
                def journal(event, value):
                    run.record(event, value)
                    if arm == 'baseline':
                        with (root / 'events.jsonl').open('a') as stream:
                            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), event=event, value=value)) + '\n')
                            stream.flush(); module.os.fsync(stream.fileno())
                def after_write(key, version):
                    if arm == 'baseline' and key in run.value['versions']:
                        run.value['versions'][key] = version
                        run.flush()
                proxy = GuardedPublicationClient(remote, guard=lambda: None, journal=journal, after_write=after_write)
                for phase, name in enumerate(('catalog', 'mappings', 'prepared', 'publication')):
                    def action():
                        for number in range(32):
                            index = phase * 32 + number
                            key = 'indexes/catalog.json' if index == 0 else f'viewer-publications/local-fixture/{index:03d}.json'
                            body = json.dumps({'index': index, 'text': 'José 雪', 'values': list(range(8))}, sort_keys=True).encode()
                            proxy.put_object(Bucket='fixture', Key=key, Body=body, IfNoneMatch='*')
                        path = root / (name + '.json')
                        path.write_text(json.dumps({'accepted': name}))
                        return {'accepted': name}
                    run.phase(name, action, files=lambda: [root / (name + '.json')])
                journal('failed', {'error': 'retained bounded diagnostic'})
            events = [json.loads(line) for line in (root / 'events.jsonl').read_bytes().splitlines()]
            facts = [{'event': row['event'], 'value': row['value']} for row in events if row['event'] != 'local_checkpoint']
            bodies = {key: hashlib.sha256(value).hexdigest() for key, value in sorted(remote.objects.items())}
            outcome = {'state': run.value, 'events': facts, 'bodies': bodies, 'puts': remote.puts, 'gets': remote.gets}
            if expected is None: expected = outcome
            assert outcome == expected, (arm, repeat)
            restored = constructor(root, run.value['binding'], resume=True)
            assert restored.value == run.value and not restored._reconciled
            result = {'arm': arm, 'repeat': repeat, 'stage': costs.stages[0], 'outcome_sha256': hashlib.sha256(json.dumps(outcome, sort_keys=True).encode()).hexdigest(),
                      'events_bytes': (root / 'events.jsonl').stat().st_size,
                      'checkpoint_bytes': run.path.stat().st_size}
            results.append(result)
            (args.output / f'{arm}-{repeat}.json').write_text(json.dumps(result, indent=2) + '\n')
    receipt = {'baseline_revision': BASELINE, 'candidate_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'candidate_tracked_changes': subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True),
               'candidate_files': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in (STATE_PATH, DISPATCH_PATH,
                    'packages/viewer_publication/src/viewer_publication/local.py', 'packages/viewer_publication/src/viewer_publication/client.py',
                    'scripts/measure/publication_costs.py', 'scripts/measure/process_rss.py')},
               'baseline_source_sha256': hashlib.sha256(baseline_source).hexdigest(),
               'baseline_dispatch_sha256': hashlib.sha256(baseline_dispatch).hexdigest(),
               'candidate_source_sha256': hashlib.sha256((ROOT / 'packages/viewer_publication/src/viewer_publication/local.py').read_bytes()).hexdigest(),
               'measurement_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'telemetry_sha256': hashlib.sha256((ROOT / 'scripts/measure/publication_costs.py').read_bytes()).hexdigest(),
               'python': sys.version, 'executable': sys.executable,
               'limits': {'writes': 128, 'accepted_phases': 4, 'repeats_per_arm': 3, 'remote_network': False,
                          'fixture_body_bytes': sum(len(value) for value in remote.objects.values()),
                          'execution_ceiling_seconds': 120, 'scratch_ceiling_bytes': 64 * 1024**2,
                          'sampled_rss_ceiling_bytes': 512 * 1024**2},
               'results': results, 'medians': {arm: {'seconds': statistics.median(row['stage']['seconds'] for row in results if row['arm'] == arm),
                    'serialized_characters': statistics.median(row['stage']['counts']['json_serialized_characters'] for row in results if row['arm'] == arm),
                    'fsync_calls': statistics.median(row['stage']['counts']['fsync_calls'] for row in results if row['arm'] == arm)} for arm in ('baseline', 'candidate')}}
    assert sum(path.stat().st_size for path in args.output.rglob('*') if path.is_file()) < 64 * 1024**2
    assert all(row['stage']['seconds'] < 120 and row['stage']['sampled_process_tree_rss_peak_bytes'] < 512 * 1024**2 for row in results)
    (args.output / 'comparison.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['medians'], indent=2))


if __name__ == '__main__': main()
