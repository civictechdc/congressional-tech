"""Retained metadata checkpoint retry and exact private recovery replay; no network."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import pyarrow as pa
from congress_api.retention import catalog_batches as module
from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from congress_shared.custody import file_identity
from viewer_publication.filename_native_recoveries import index_catalog_recoveries
from test_catalog_coalesced_batches import Native as FixtureNative

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
base=Path('/Users/mikewolfd/Work/congressional-tech/output')
cache=base/'release-finish-20261026/local-release-streamed/metadata-cache/r2-native-manifests'
selected=json.loads((cache/'catalog-selections-v2/97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8.json').read_bytes())
source=json.loads((base/'release-finish-20261026/local-release-compact/source-precompute/context.json').read_bytes())['source_identity']
schema=module._component_schema(dict(schema=selected['schemas']['filenames']))
refs=[];rows=0;inputs=[]
for path in sorted((cache/'catalog-component-pages-v1').glob('*.json'))[:32]:
 raw=path.read_bytes();page=json.loads(raw);digest=sha256(raw).hexdigest();inputs.append(digest)
 reference=dict(key='indexes/native-manifests/'+str(path.relative_to(cache)),bytes=len(raw),sha256=digest)
 for component,proof in sorted(page['components'].items()):
  refs.append((component,dict(page=reference,component=component)));rows+=sum(v['rows']for v in proof['tables']['filenames']['chunks'])
class Store:
 def read(self,key):
  assert key.startswith('indexes/native-manifests/')
  return(cache/key.removeprefix('indexes/native-manifests/')).read_bytes()
class FailedRead(OSError):pass
class Native:
 @contextmanager
 def source_batches(self,*args,**kwargs):
  raise FailedRead('Deliberate private native boundary failure')
  yield
folder=out/'retained-metadata-checkpoint';assert not folder.exists()
table=module.SelectedCatalogTable(schema,lambda:iter(refs),store=Store(),native=Native(),label='filenames',rows=rows,max_ordered_bytes=96<<20,selection_identity=dict(source=source,components=selected['components']))
counts=dict(admissions=0,bindings=0)
original_admit=table._admit;original_binding=module._component_binding

def admit(db):
 counts['admissions']+=1;return original_admit(db)
def binding(value):
 counts['bindings']+=1;return original_binding(value)
table._admit=admit;module._component_binding=binding
stages=[]
for stage in('fresh_then_native_failure','retry_after_native_failure'):
 before=dict(counts);start=time.perf_counter();cpu=time.process_time()
 try:list(table.iter_batches(columns=['source_id'],include_order=True,admission_directory=folder))
 except FailedRead:pass
 else:raise AssertionError('Private native failure boundary not reached')
 stages.append(dict(stage=stage,seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,admissions=counts['admissions']-before['admissions'],binding_checks=counts['bindings']-before['bindings']))
 if len(stages)==1:
  table.component_refs=lambda:(_ for _ in()).throw(AssertionError('Members re-enumerated on retry'))
module._component_binding=original_binding
assert stages[0]['admissions']==1 and stages[0]['binding_checks']==len(refs)
assert stages[1]['admissions']==stages[1]['binding_checks']==0
receipt=json.loads((folder/'complete.json').read_bytes());assert dict(file_identity(folder/'admission.sqlite'))==receipt['file']
# The fixture/native Arrow bytes are shared with the prior baseline, not regenerated.
fixture=base/'recovery-admission-20261027/fixture'
class InterruptedFixture(FixtureNative):
 fail=True
 @contextmanager
 def source_batches(self,*args,**kwargs):
  with super().source_batches(*args,**kwargs)as reader:
   if self.fail:
    self.fail=False
    def partial():
     yield reader.read_next_batch().slice(0,1)
     raise FailedRead('Deliberate private truncated native stream')
    with pa.RecordBatchReader.from_batches(reader.schema,partial())as truncated:yield truncated
   else:yield reader
native=InterruptedFixture();native.tables={name:pa.ipc.open_file(str(fixture/path)).read_all()for name,path in json.loads((fixture/'native.json').read_bytes()).items()}
snapshot=read_catalog(LocalStore(fixture/'store'),native=native)
private=out/'private-recovery-checkpoint';assert not private.exists()
try:index_catalog_recoveries(snapshot,[],max_ordered_bytes=1<<20,admission_directory=private)
except FailedRead:pass
else:raise AssertionError('Private truncation did not fail')
original=module.SelectedCatalogTable._admit
module.SelectedCatalogTable._admit=lambda *args:(_ for _ in()).throw(AssertionError('Private recovery admission repeated'))
try:result=index_catalog_recoveries(snapshot,[],max_ordered_bytes=1<<20,admission_directory=private)
finally:module.SelectedCatalogTable._admit=original
expected=(base/'recovery-admission-20261027/baseline-paired-1-recovery.json').read_bytes()
assert encoded(result)==expected
(out/'recovery.json').write_bytes(encoded(result))
report=dict(status='passed',components=len(refs),logical_source_rows=rows,stages=stages,checkpoint_file=receipt['file'],input_page_sha256=inputs,private_recovery_byte_equal=True,private_recovery_sha256=sha256(encoded(result)).hexdigest(),private_source_rows=result['rows'],private_document_rows=result['entries'],native_network_access=False,operational_checkpoint_accessed=False)
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k]for k in('status','components','stages','checkpoint_file','private_recovery_byte_equal','private_recovery_sha256')}))
