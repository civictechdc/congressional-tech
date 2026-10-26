import json, urllib.request, time, io, os, sys
import pyarrow.parquet as pq, pyarrow as pa, duckdb
UA={"User-Agent":"congressional-tech-review/1.0"}
BASE="https://data.spicygov.ai/"
idx=json.load(open("dl/publication.v2.json"))
fams=idx["families"]
want={"committee-rosters":["committees","committee_assignments"],"members":["members","member_terms"],
      "bill-family":["cbo_cost_estimates","bill_vote_references","congress_bills"],"roll-call-votes":["roll_call_votes"],"nominations":["nominations"]}
last=[0.0]
def throttle():
    d=time.time()-last[0]
    if d<0.25: time.sleep(0.25-d)
    last[0]=time.time()
def head(url):
    throttle(); r=urllib.request.urlopen(urllib.request.Request(url,method="HEAD",headers=UA),timeout=60); return int(r.headers["Content-Length"])
class HttpFile(io.RawIOBase):
    def __init__(s,url): s.url=url; s.n=head(url); s.pos=0
    def readable(s): return True
    def seekable(s): return True
    def tell(s): return s.pos
    def seek(s,off,wh=0):
        s.pos={0:off,1:s.pos+off,2:s.n+off}[wh]; return s.pos
    def read(s,k=-1):
        if k<0: k=s.n-s.pos
        if k==0: return b""
        throttle(); h=dict(UA); h["Range"]=f"bytes={s.pos}-{s.pos+k-1}"
        b=urllib.request.urlopen(urllib.request.Request(s.url,headers=h),timeout=120).read(); s.pos+=len(b); return b
    def readinto(s,buf):
        b=s.read(len(buf)); buf[:len(b)]=b; return len(b)
    def size(s): return s.n
    @property
    def closed(s): return False
os.makedirs("dl/t",exist_ok=True)
con=duckdb.connect()
for fam,tabs in want.items():
    f=fams[fam]; prefix=f["prefix"]; tbl=f["tables"]
    for t in tabs:
        key=tbl.get(t+".parquet",{}).get("key", t+".parquet") if isinstance(tbl,dict) else t+".parquet"
        url=BASE+prefix+"/"+key
        hf=HttpFile(url)
        pf=pq.ParquetFile(pa.PythonFile(hf,mode="r"))
        print(f"=== {t}: {hf.n/1e6:.1f} MB rows={pf.metadata.num_rows} rgs={pf.metadata.num_row_groups}")
        print("   cols:",[(fld.name,str(fld.type)) for fld in pf.schema_arrow])
        local=f"dl/t/{t}.parquet"
        if hf.n<60e6:
            throttle(); open(local,"wb").write(urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=300).read())
        else:
            tb=pf.read_row_group(0); pq.write_table(tb,local); print("   (first row group only saved locally)")
print("done")
