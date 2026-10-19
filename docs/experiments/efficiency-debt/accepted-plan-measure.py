"""One bounded actual builder/guarded-uploader arm; only in-memory I/O."""
import sys
from pathlib import Path
root, fixture, output, arm = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
sys.path[:0] = [str(p) for p in (list((root / 'packages').glob('*/src')) + [root / 'apps/site/scripts', root / 'scripts/measure', root / 'scripts'])]
import importlib.util
import io
import json
import hashlib
from collections import Counter
from types import SimpleNamespace
from congress_api.retention.catalog_validation import validate_catalog_pair
from congress_api.retention.document_index import validate_document_indexes
from viewer_publication.local import LocalContinuation
from viewer_publication.client import ContinuedPublicationClient
from publication_costs import PublicationCosts
import pyarrow.parquet as pq

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
publisher = load('measured_publisher', root / 'apps/site/scripts/publish-viewer-r2.py')
builder = load('measured_builder', root / 'apps/site/scripts/publish-filename-viewer.py')
control = load('measured_control', root / 'scripts/corpus_recovery/dispatch_corpus_recovery_publication.py')
fixture_module = load('measured_remote_fixture', root / 'packages/viewer_publication/tests/test_viewer_publication_attempt.py')
remote = fixture_module.Remote(fixture)
remote.meta = SimpleNamespace(config=SimpleNamespace(retries={'total_max_attempts': 1}))
output.mkdir(parents=True)
run = LocalContinuation(output / 'attempt', dict(pins={'source': 'common-fixture-pin'}))
run.value['versions'] = {key: remote.versions.get(key) for key in ('indexes/catalog.json', publisher.ACCEPTED_KEY, publisher.PREFIX+'manifest.json')}
run.value['release_plan'] = dict(release='releases/'+'f'*32+'/', published_at='2026-10-19T00:00:00+00:00')
run.flush()
manifest = json.loads((fixture / 'indexes/catalog.json').read_bytes())
bodies = {body for body in pq.read_table(fixture / manifest['files']['filenames']['key'], columns=['body_key']).column(0).to_pylist() if body}
# Both routes begin with the same already-accepted real source pair.
pair = validate_catalog_pair(fixture, manifest, validator=validate_document_indexes, expected_bodies=bodies)
metrics = PublicationCosts(output)
# Count actual complete file_identity passes too; the maintained telemetry helper
# intentionally counts only hashlib.file_digest. Preserve both categories.
if arm != 'baseline':
    import corpus_recovery.publication
from congress_api.retention import derived_files
original_identity = derived_files.file_identity
def issued_hash(path, _original=original_identity):
    result = _original(path)
    if Path(path).is_relative_to(run.root / 'prepared'):
        metrics.counts['output_issued_hash_passes'] += 1
        metrics.counts['output_issued_hash_bytes'] += result['bytes']
    return result
for loaded in list(sys.modules.values()):
    if loaded is None or loaded.__name__ == '__main__':
        continue
    for name, value in list(vars(loaded).items()):
        if value is original_identity:
            setattr(loaded, name, issued_hash)
original_file_digest = hashlib.file_digest
def named_hash(stream, *args, **kwargs):
    before = stream.tell()
    result = original_file_digest(stream, *args, **kwargs)
    if isinstance(getattr(stream, 'name', None), (str, Path)) and Path(stream.name).is_relative_to(run.root / 'prepared'):
        metrics.counts['output_named_hash_passes'] += 1
        metrics.counts['output_named_hash_bytes'] += stream.tell() - before
    return result
hashlib.file_digest = named_hash
# Explicit-file builder modules are intentionally outside sys.modules.
if builder.file_identity is original_identity:
    builder.file_identity = issued_hash
scans = Counter(); stage = 'preparation'; original_index = publisher.index_recoveries
publisher.index_recoveries = lambda *args, **kw: scans.update([stage]) or original_index(*args, **kw)
class Public(io.BytesIO):
    headers = {'Access-Control-Allow-Origin': '*'}
publisher.open_public = lambda request, **kw: Public(remote.objects[publisher.PREFIX + request.full_url.removeprefix(publisher.PUBLIC_URL)])
proxy = ContinuedPublicationClient(remote, continuation=run, guard=lambda: None, journal=run.record, after_write=lambda *args: None)
plan = None
with metrics.instrument():
    with metrics.stage('preparation'):
        if arm == 'baseline':
            prepared = run.phase('prepared', lambda: builder.publish(fixture, run.root/'prepared', '2026-10-18T00:00:00+00:00', validation=pair),
                files=lambda: [p for p in (run.root/'prepared').rglob('*') if p.is_file()])
        else:
            from corpus_recovery.publication import prepare_viewer
            plan = prepare_viewer(publisher, builder, remote, run, fixture,
                lambda value: pair.require(fixture, value, validator=validate_document_indexes, expected_bodies=bodies),
                lambda: pair, control.publication_conditions)
            prepared = plan.manifest
    stage = 'upload'
    with metrics.stage('upload'):
        result = publisher.upload(proxy, run.root/'prepared', prepared,
            **(plan.conditions if plan is not None else control.publication_conditions(run)),
            publication_plan=run.value['release_plan'], **({'plan': plan} if plan else {}), probe=lambda *args: None)
    if plan is not None:
        stage = 'restore'
        with metrics.stage('restore'):
            restored = LocalContinuation(run.root, run.value['binding'], resume=True)
            restored_plan = prepare_viewer(publisher, None, None, restored, fixture,
                lambda *args: (_ for _ in ()).throw(AssertionError('Source pair revalidated during accepted restore')),
                lambda: None, control.publication_conditions)
        assert restored_plan.conditions == plan.conditions
        assert restored_plan.release_plan == plan.release_plan
    assert result['status'] == 'published'
files = {str(p.relative_to(run.root/'prepared')): hashlib.sha256(p.read_bytes()).hexdigest() for p in (run.root/'prepared').rglob('*') if p.is_file() and p.name not in ('manifest.json','recovery-prepared.json')}
prepared_normal = dict(prepared); prepared_normal.pop('published_at')
pointer = json.loads(remote.objects[publisher.PREFIX+'manifest.json'])
source_identity = pointer.pop('full_release_inputs')
recovery_identity = pointer['recovery_inputs'].pop('full_release_inputs')
status = json.loads(remote.objects[publisher.PREFIX+pointer['recovery']['path']])
release_manifest = json.loads(remote.objects[publisher.PREFIX+pointer['manifest']])
receipt = dict(arm=arm,root=str(root),source_manifest=manifest,files=files,prepared=prepared_normal,result=result,
    pointer=pointer,release_manifest=release_manifest,recovery=status,release_source_identity=source_identity,
    recovery_source_identity=recovery_identity,recovery_scans=dict(scans),stages=metrics.stages,
    release_source_files=publisher.release_source_files(root),
    GETs=dict(Counter(remote.gets)-Counter(remote.heads)),HEADs=dict(remote.heads),PUTs=remote.puts,
    modules={name: str(module.__file__) for name,module in list(sys.modules.items()) if name in ('viewer_publication.local','viewer_publication.plan','viewer_publication.continuation','corpus_recovery.publication','congress_api.retention.viewer_inventory')})
assert all(Path(path).is_relative_to(root) for path in receipt['modules'].values())
assert len(files) == 269
assert max(s['sampled_process_tree_rss_peak_bytes'] for s in metrics.stages) < 2*1024**3
assert sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) < 1024**3
(output / 'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(dict(arm=arm,scans=dict(scans),counts={s['stage']:s['counts'] for s in metrics.stages}),indent=2))
