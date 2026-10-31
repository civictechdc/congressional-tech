"""Measured whole-process-tree RSS and owned disk for a raw provider journey."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest


def test_streamed_provider_journey_has_bounded_process_tree_and_scratch(tmp_path):
    if shutil.which('ps') is None:pytest.skip('Requires the host process sampler')
    tests=Path(__file__).parent
    code=f'''
import sys,json,base64,hashlib,gzip
from pathlib import Path
sys.path.insert(0,{str(tests)!r})
from test_capture_durable import *
from congress_api.acquisition.admission import Admission
root=Path({str(tmp_path)!r});root.mkdir(exist_ok=True)
url=URL
source=root/'encoded-provider.json'
# Build a valid one-page PDF with an uncompressed comment stream. Xref
# offsets and stream length are exact; fixture construction stays streaming.
body_path=root/'source.pdf';target_bytes=16<<20
objects=[b'1 0 obj\\n<< /Type /Catalog /Pages 2 0 R >>\\nendobj\\n',
         b'2 0 obj\\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\\nendobj\\n',
         b'3 0 obj\\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Resources <<>> /Contents 4 0 R >>\\nendobj\\n']
def parts(length):
    prefix=b'%PDF-1.4\\n';offsets=[0]
    for obj in objects:offsets.append(len(prefix));prefix+=obj
    offsets.append(len(prefix))
    prefix+=f'4 0 obj\\n<< /Length {{length}} >>\\nstream\\n'.encode()
    end=b'endstream\\nendobj\\n';xref=len(prefix)+length+len(end)
    suffix=end+b'xref\\n0 5\\n0000000000 65535 f \\n'
    for offset in offsets[1:]:suffix+=f'{{offset:010d}} 00000 n \\n'.encode()
    suffix+=f'trailer\\n<< /Size 5 /Root 1 0 R >>\\nstartxref\\n{{xref}}\\n%%EOF\\n'.encode()
    return prefix,suffix
length=target_bytes-600
for _ in range(5):
    prefix,suffix=parts(length);difference=target_bytes-len(prefix)-length-len(suffix)
    if difference==0:break
    length+=difference
assert len(prefix)+length+len(suffix)==target_bytes
with body_path.open('wb') as target:
    target.write(prefix);remaining=length
    comment=b'%'+b'x'*1021+b'\\n'
    while remaining>=len(comment):target.write(comment);remaining-=len(comment)
    if remaining==1:target.write(b'\\n')
    elif remaining:target.write(b'%'+b'x'*(remaining-2)+b'\\n')
    target.write(suffix)
assert body_path.stat().st_size==target_bytes
with body_path.open('rb') as body:digest=hashlib.file_digest(body,'sha256')
with source.open('wb') as target,body_path.open('rb') as body:
    target.write(b'{{"success":true,"data":{{"rawBase64":"')
    while chunk:=body.read(3*65536):target.write(base64.b64encode(chunk))
    target.write(json.dumps({{'metadata':{{'sourceURL':url,'url':url,'statusCode':200}}}},separators=(',',':')).encode().replace(b'{{"metadata"',b'","metadata"',1)+b'}}')
# Delete fixture provider bytes only after transfer owns its durable spool.
class FileResponse:
    status_code=200
    def __enter__(self):self.source=source.open('rb');return self
    def __exit__(self,*_):self.source.close()
    def iter_content(self,chunk_size):
        while part:=self.source.read(chunk_size):yield part
selected=load(release(root,[dict(requested_url=url,attempts=0)]),root/'read')
direct=Adapter({{url:(403,b'denied',{{}})}})
kwargs=options(root,selected,direct)
kwargs.update(provider=None,firecrawl=FirecrawlAdapter(lambda _:FileResponse()),firecrawl_cost=1,
              admission=Admission(root/'budget.sqlite',10,10),archive_limits=None,byte_budget=1<<30)
result=run_capture(**kwargs)
assert result['captures']==1 and result['requests']==2,result
receipt=json.loads(gzip.decompress((root/'raw'/result['receipts'][0]).read_bytes()))
assert receipt['http_status']==200 and receipt['outcome']=='stored',receipt
body=receipt['captures'][0]
assert body['complete'] is True and body['bytes']==16<<20 and body['sha256']==digest.hexdigest(),body
retained_path=root/'raw/bodies/sha256'/body['sha256'][:2]/body['sha256']
with retained_path.open('rb') as retained:
    assert hashlib.file_digest(retained,'sha256').hexdigest()==digest.hexdigest()
from congress_shared.custody import verify_local_file
from corpus_recovery.qualification import qualify,QualificationConfig
qualification=qualify(verify_local_file(retained_path),root/'qualification',
    config=QualificationConfig())
assert qualification.status=='qualified',qualification
assert qualification.pages==qualification.pages_decoded==qualification.all_pages_rendered==1,qualification
(root/'qualification-result.json').write_text(json.dumps(qualification))
(root/'result.json').write_text(json.dumps(result))
'''
    process=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    peak_rss=peak_disk=0;samples=0
    while process.poll() is None:
        rows=subprocess.run(['ps','-axo','pid=,ppid=,rss='],capture_output=True,text=True,check=True).stdout.splitlines()
        values=[tuple(map(int,row.split())) for row in rows if len(row.split())==3]
        owned={process.pid}
        while True:
            expanded=owned|{pid for pid,parent,_ in values if parent in owned}
            if expanded==owned:break
            owned=expanded
        peak_rss=max(peak_rss,sum(rss*1024 for pid,_,rss in values if pid in owned))
        inodes={}
        for path in tmp_path.rglob('*'):
            try:
                if path.is_file():
                    stat=path.stat();inodes[(stat.st_dev,stat.st_ino)]=stat.st_size
            except FileNotFoundError:pass
        peak_disk=max(peak_disk,sum(inodes.values()));samples+=1
        time.sleep(0.01)
    stdout,stderr=process.communicate()
    assert process.returncode==0,stderr
    result=json.loads((tmp_path/'result.json').read_text())
    measurement=dict(samples=samples,peak_tree_rss_bytes=peak_rss,peak_owned_disk_bytes=peak_disk,
                     byte_budget_bytes=1<<30,verified_complete_body=True,qualified_all_pages=True,qualification_memory_bytes=1<<30,qualification_input_bytes=16<<20,qualification_decoded_bytes=256<<20,qualification_max_pages=2000,body_bytes=16<<20,entity_limit_bytes=16<<20,spool_limit_bytes=1<<28,workers=1,native_threads=2,native_memory_bytes=512<<20,native_scratch_bytes=256<<20,scope='capture and qualification Python plus native/Poppler descendants; 10ms nominal sampling')
    (tmp_path/'measurement.json').write_text(json.dumps(measurement,indent=2))
    print(json.dumps(measurement,sort_keys=True))
    assert samples>1 and 0<peak_rss<768*1024**2
    # Includes the input encoded fixture and retained output as well as capture
    # scratch. This is stronger than the runner's 256MiB spool-only allowance.
    assert peak_disk<result['budgets']['spool']
    assert result['fetched_bytes']>measurement['body_bytes']
