import json,hashlib,shutil
from pathlib import Path
import duckdb

HERE=Path(__file__).resolve().parent
OUT=Path((HERE/'scratch-path.txt').read_text().strip())
ROOT=Path('/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-impl/cx_model_design')
REPO=HERE.parents[2]
OLD=Path('/var/folders/g8/10vdwk2n07z85vqn_vlv2lfc0000gn/T/url-trace-validation-9vlmw_gm')
FROZEN=OLD/'defense-inputs'
CAM=ROOT/'recovery_campaign_v1'
PUB=ROOT/'publish_v20'
def connect(): return duckdb.connect(str(OUT/'audit.duckdb'),config={'threads':2,'memory_limit':'1GB'})
def rows(c,sql,args=()):
 r=c.execute(sql,args); names=[x[0] for x in r.description]
 return [dict(zip(names,x)) for x in r.fetchall()]
def dump(name,data):
 (OUT/name).write_text(json.dumps(data,indent=2,default=lambda x:x.hex() if isinstance(x,bytes) else str(x))+'\n')
def pin(source,name):
 target=OUT/'inputs'/name;target.parent.mkdir(exist_ok=True)
 before=source.stat();shutil.copy2(source,target);after=source.stat()
 assert (before.st_mtime_ns,before.st_size)==(after.st_mtime_ns,after.st_size),(source,'changed during copy')
 return {'source':str(source),'path':str(target),'size':target.stat().st_size,'sha256':hashlib.file_digest(target.open('rb'),'sha256').hexdigest()}
