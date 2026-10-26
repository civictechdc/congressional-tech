"""Finding 6, second method: sniff real body bytes. Ranged GET of the first 64 KiB of each .gz body
on the r2.dev host, gunzip the prefix, and test for %PDF- in the first 1 KiB. Seeded samples per group."""
import sys, os, json, random, time, zlib, urllib.request, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, A
HOST="https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/"; UA="congressional-tech-review/1.0"
c=con()
c.execute(f"create view rd as select * from read_parquet('{A}readings/*.parquet', union_by_name=true)")
c.execute("create temp table mt as select sha256, bool_or(media_type ilike '%pdf%') mpdf, string_agg(distinct media_type, '|') mts from c where sha256 is not null group by 1")
c.execute("""create temp table loc as select sha256, bool_or(regexp_matches(lower(coalesce(original_path_tail,'')), '\\.pdf$') or regexp_matches(lower(coalesce(context_url,'')), '\\.pdf($|[?#])')) lpdf from r where sha256 is not null group by 1""")
c.execute("""create temp table sf as select regexp_extract(body_key,'([0-9a-f]{64})',1) sha256, bool_or(list_contains(body_format,'pdf')) spdf, bool_or(len(body_format)>0) sniffed, string_agg(distinct array_to_string(body_format,','), '|') bfs from f where body_key is not null group by 1""")
c.execute("create temp table g as select mt.*, coalesce(lpdf,false) lpdf, coalesce(spdf,false) spdf, coalesce(sniffed,false) sniffed, bfs from mt left join loc using (sha256) left join sf using (sha256)")
groups={
 'mt_sniffed_other': "mpdf and sniffed and not spdf",
 'mt_unsniffed': "mpdf and not sniffed",
 'missed69': "spdf and not mpdf",
 'mt_and_sniff_pdf': "mpdf and spdf",
 'locator_only': "lpdf and not mpdf and not spdf",
}
N={'mt_sniffed_other':60,'mt_unsniffed':100,'missed69':69,'mt_and_sniff_pdf':40,'locator_only':60}
rnd=random.Random(20261026); last=[0.0]
def head_bytes(sha):
    w=0.25-(time.time()-last[0]); 
    if w>0: time.sleep(w)
    last[0]=time.time()
    req=urllib.request.Request(f"{HOST}bodies/sha256/{sha[:2]}/{sha}.gz", headers={"User-Agent":UA,"Range":"bytes=0-65535"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: data=r.read()
    except Exception as e: return 'ERR:'+type(e).__name__
    try: raw=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(data)
    except Exception as e: return 'GZERR'
    head=raw[:1024].lstrip()
    if b'%PDF-' in raw[:1024]: return 'pdf'
    if head[:5].lower() in (b'<!doc',b'<html') or b'<html' in head[:300].lower(): return 'html'
    if head[:5]==b'<?xml': return 'xml'
    if head[:2]==b'PK': return 'zip'
    if head[:4]==b'\xd0\xcf\x11\xe0': return 'ole'
    if len(raw)==0: return 'empty'
    return 'other'
out={}
for gname,pred in groups.items():
    rows=c.execute(f"select sha256, mts, bfs from g where {pred} order by sha256").fetchall()
    samp=rows if len(rows)<=N[gname] else rnd.sample(rows,N[gname])
    res=collections.Counter(); ex=[]
    for sha,mts,bfs in samp:
        k=head_bytes(sha); res[k]+=1; ex.append((sha,mts,bfs,k))
    out[gname]={'population':len(rows),'sampled':len(samp),'bytes_sniff':dict(res),'rows':ex}
    print(gname,'population',len(rows),'sampled',len(samp),dict(res))
json.dump(out,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'pdf_bytes.json'),'w'),indent=1)
