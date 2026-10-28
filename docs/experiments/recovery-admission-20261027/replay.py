"""Retained metadata admission replay and shared private recovery fixture; no network."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import pyarrow as pa
from congress_api.retention import catalog_batches as module
from congress_api.retention.immutable_metadata import encoded
from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention.catalog_publication import read_catalog
from viewer_publication.filename_native_recoveries import index_catalog_recoveries

out=Path(sys.argv[1]);arm=sys.argv[2];out.mkdir(parents=True,exist_ok=True)
cache=Path('/Users/mikewolfd/Work/congressional-tech/output/release-finish-20261026/local-release-streamed/metadata-cache/r2-native-manifests')
selected=json.loads((cache/'catalog-selections-v2/97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8.json').read_bytes())
schema=module._component_schema(dict(schema=selected['schemas']['filenames']))
refs=[];rows=0;inputs=[]
for path in sorted((cache/'catalog-component-pages-v1').glob('*.json'))[:32]:
 raw=path.read_bytes();page=json.loads(raw);digest=sha256(raw).hexdigest();inputs.append(digest)
 reference=dict(key='indexes/native-manifests/'+str(path.relative_to(cache)),bytes=len(raw),sha256=digest)
 for component,proof in sorted(page['components'].items()):
  refs.append((component,dict(page=reference,component=component)))
  rows+=sum(view['rows']for view in proof['tables']['filenames']['chunks'])
class Store:
 def read(self,key):
  assert key.startswith('indexes/native-manifests/')
  return(cache/key.removeprefix('indexes/native-manifests/')).read_bytes()
class Finished(Exception):pass
class Native:
 @contextmanager
 def source_batches(self,*args,**kwargs):
  raise Finished('Admission finished; native payload deliberately not accessed')
  yield
stats=dict(compatibility_calls=0,chunk_sql_reads=0,binding_encodes=0,binding_json_bytes=0)
old_compatibility=module.can_read_catalog_schema;old_encoded=module.encoded

def compatibility(*args):
 stats['compatibility_calls']+=1
 return old_compatibility(*args)
def counted(value):
 raw=old_encoded(value)
 if isinstance(value,dict)and'component'in value and'validation'in value:
  stats['binding_encodes']+=1;stats['binding_json_bytes']+=len(raw)
 return raw
module.can_read_catalog_schema=compatibility;module.encoded=counted
original_connect=sqlite3.connect
admission={};digest_seconds=[0.0];digest_cpu=[0.0]
class Connection(sqlite3.Connection):
 def close(self):
  digest_started=time.perf_counter();digest_cpu_started=time.process_time()
  for table in('members','chunks','physical','views'):
   digest=sha256();count=0
   for row in self.execute('SELECT * FROM '+table+' ORDER BY 1,2'):
    digest.update(encoded(row));count+=1
   admission[table]=dict(rows=count,sha256=digest.hexdigest())
  digest_seconds[0]+=time.perf_counter()-digest_started
  digest_cpu[0]+=time.process_time()-digest_cpu_started
  super().close()
def connect(*args,**kwargs):
 result=original_connect(*args,**kwargs,factory=Connection)
 result.set_trace_callback(lambda sql: stats.__setitem__('chunk_sql_reads',stats['chunk_sql_reads']+1)if sql.startswith('SELECT body FROM chunks')else None)
 return result
module.sqlite3.connect=connect
started=time.perf_counter();cpu_started=time.process_time()
try:
 list(module.SelectedCatalogTable(schema,lambda:iter(refs),store=Store(),native=Native(),label='filenames',rows=rows,max_ordered_bytes=96<<20).iter_batches(columns=['source_id'],include_order=True))
except Finished:pass
else:raise AssertionError('Private native boundary was not reached')
seconds=time.perf_counter()-started-digest_seconds[0]
cpu_seconds=time.process_time()-cpu_started-digest_cpu[0]
module.sqlite3.connect=original_connect;module.can_read_catalog_schema=old_compatibility;module.encoded=old_encoded
# Create once, then reuse the exact private selected catalog/native Arrow inputs.
fixture=out/'fixture';manifest=fixture/'native.json'
from test_catalog_coalesced_batches import Native as FixtureNative
from test_catalog_recovery_lookup import seed
if not manifest.exists():
 fixture.mkdir();store=LocalStore(fixture/'store');native=FixtureNative();seed(fixture,store,native)
 native_files={}
 for i,(name,table)in enumerate(sorted(native.tables.items())):
  path=fixture/f'native-{i}.arrow'
  with pa.OSFile(str(path),'wb')as sink,pa.ipc.new_file(sink,table.schema)as writer:writer.write_table(table)
  native_files[name]=path.name
 manifest.write_bytes(encoded(native_files))
native=FixtureNative();native.tables={name:pa.ipc.open_file(str(fixture/path)).read_all()for name,path in json.loads(manifest.read_bytes()).items()}
snapshot=read_catalog(LocalStore(fixture/'store'),native=native);metrics={}
result=index_catalog_recoveries(snapshot,[],max_ordered_bytes=1<<20,metrics=metrics)
(out/(arm+'-recovery.json')).write_bytes(encoded(result))
report=dict(seconds=seconds,cpu_seconds=cpu_seconds,comparison_digest_seconds=digest_seconds[0],components=len(refs),logical_source_rows=rows,input_page_sha256=inputs,statistics=stats,admission=admission,recovery_sha256=sha256(encoded(result)).hexdigest(),recovery_rows=result['rows'],recovery_entries=result['entries'],recovery_metrics=metrics,source_file=str(Path(module.__file__)),source_sha256=sha256(Path(module.__file__).read_bytes()).hexdigest())
(out/(arm+'.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k]for k in('seconds','cpu_seconds','components','logical_source_rows','statistics','recovery_sha256')}))
