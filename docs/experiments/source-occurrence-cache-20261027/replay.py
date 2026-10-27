"""Offline full source-leaf replay: retained native bytes, reconstructed routing metadata."""
import base64
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import pyarrow as pa
import pyarrow.compute as pc
from congress_api.retention.catalog_rows import CatalogRows
from congress_api.retention.immutable_metadata import MetadataObjects, encoded
from viewer_publication.filename_native import NativeSourceAssets, ViewerAssets
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY

base=Path(sys.argv[2])
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
retained=base/'source-leaf-qualification'
selection=json.loads((base/'local-release-streamed/metadata-cache/r2-native-manifests/catalog-selections-v2/97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8.json').read_bytes())
value=json.loads((retained/'selected-leaf.json').read_bytes())['value']
tables=[pa.ipc.open_file(str(retained/f'native-input-{i}.arrow')).read_all()for i in (0,1)]
schemas={name:pa.ipc.read_schema(pa.BufferReader(base64.b64decode(raw)))for name,raw in selection['schemas'].items()}
class Store:
 def __init__(self):self.values={}
 def put(self,key,raw,**kwargs):self.values[key]=raw
 def read(self,key):return self.values.get(key)
store=Store()
schema_ref=value['source_schema'];schema_path=base/'local-release-streamed/metadata-cache/r2-native-manifests'/schema_ref['key'].removeprefix('indexes/native-manifests/')
store.values[schema_ref['key']]=schema_path.read_bytes()
pin=value['release'];descriptor=pin['catalog_rows'];summary=descriptor['root']['summary']
part=dict(index=0,release=dict(dataset=dict(dataset=pin['dataset']['dataset']+'-occ-0')),rows=len(tables[1]),arrow_bytes=tables[1].nbytes,owner_min=summary['owner_min'],owner_max=summary['owner_max'])
objects=MetadataObjects(store,'catalog-occurrences-v1')
descriptor['root']=dict(objects.put(dict(format=descriptor['format'],summary=summary,parts=[part])),summary=summary)
descriptor.pop('binding')
descriptor['binding']=sha256(encoded(dict(core={k:v for k,v in pin.items()if k!='catalog_rows'},descriptor=descriptor))).hexdigest()
class Native:
 def __init__(self):self.reads=[]
 @contextmanager
 def source_batches(self,pin,*,schema=None):
  i=int(pin['dataset']['dataset'].endswith('-occ-0'));self.reads.append(i)
  yield tables[i].to_reader()
native=Native()
snapshot=SimpleNamespace(native=native,store=store,selection=selection,schemas=schemas)
metrics={};renderer=NativeSourceAssets(snapshot,ViewerAssets(out/'assets'),policy=DEFAULT_DECODED_POLICY,metrics=metrics)
counters=dict(schema_decodes=0,descriptor_checks=0,owner_comparison_rows=0)
read_schema=pa.ipc.read_schema;checked=CatalogRows._checked;equal=pc.equal

def tracked_schema(*args,**kwargs):
 counters['schema_decodes']+=1
 return read_schema(*args,**kwargs)
def tracked_checked(*args,**kwargs):
 counters['descriptor_checks']+=1
 return checked(*args,**kwargs)
def tracked_equal(left,right,*args,**kwargs):
 if isinstance(left,pa.ChunkedArray)and left.type==pa.int64()and isinstance(right,int):counters['owner_comparison_rows']+=len(left)
 return equal(left,right,*args,**kwargs)
pa.ipc.read_schema=tracked_schema;CatalogRows._checked=tracked_checked;pc.equal=tracked_equal
started=time.perf_counter()
result=renderer.render_source(value)
seconds=time.perf_counter()-started
files={str(p.relative_to(out/'assets')):dict(bytes=p.stat().st_size,sha256=sha256(p.read_bytes()).hexdigest())for p in sorted((out/'assets').rglob('*'))if p.is_file()}
(out/'source.json').write_bytes(encoded(result))
report=dict(seconds=seconds,counters=counters,native_reads=native.reads,rows=result['rows'],observations=result['files']['occurrences']['rows'],files=files,source_sha256=sha256(encoded(result)).hexdigest(),inputs=[dict(file=f'native-input-{i}.arrow',sha256=sha256((retained/f'native-input-{i}.arrow').read_bytes()).hexdigest())for i in(0,1)],metadata='Reconstructed one-part directory and descriptor binding; exact retained native Arrow bytes; no network calls',metrics=metrics)
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k]for k in('seconds','counters','native_reads','rows','observations','source_sha256')}),flush=True)
