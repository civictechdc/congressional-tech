"""F4: root elements of the three GovInfo manifest members of two ZIPs (public GETs, first 2 KB), and the first line of one ARC body (F1)."""
import duckdb, os, urllib.request, zlib, re, time
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
H='https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'; UA={'User-Agent':'congressional-tech-review/1.0'}
def head(key, n=2048):
    req=urllib.request.Request(H+key, headers={**UA,'Range':f'bytes=0-{n-1}'})
    with urllib.request.urlopen(req, timeout=30) as r: raw=r.read()
    time.sleep(0.3)
    return zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if key.endswith('.gz') else raw
for zipurl in ['https://www.govinfo.gov/content/pkg/CHRG-109shrg25116.zip','https://www.govinfo.gov/content/pkg/CHRG-114hhrg98898.zip']:
    for mem, key in con.execute("SELECT DISTINCT mem, body_key FROM c WHERE ctx=? AND regexp_matches(mem,'(dip|mods|premis)\\.xml$') ORDER BY 1", [zipurl]).fetchall():
        b=head(key); m=re.search(rb'<([A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)[\s>]', re.sub(rb'<\?.*?\?>|<!--.*?-->',b'',b,flags=re.S))
        print(zipurl.rsplit('/',1)[1], mem.rsplit('/',1)[1], 'root:', (m.group(1) or b'').decode()+m.group(2).decode())
key=con.execute("SELECT body_key FROM c WHERE mt='application/arc+gzip' ORDER BY sha LIMIT 1").fetchone()[0]
b=head(key, 4096); inner=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(b)
print('ARC first line:', inner.split(b'\n')[0][-80:])
