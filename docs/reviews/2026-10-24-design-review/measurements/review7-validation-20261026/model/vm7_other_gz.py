"""F1 side check: are the 'other'-format real bodies (retained-file members named *.gz) gzip originals, i.e. would DM 6.2's one-layer sniff
also miss their format? First bytes of 6 sampled bodies from the public host."""
import duckdb, os, urllib.request, zlib, time
D=os.path.dirname(os.path.abspath(__file__)); con=duckdb.connect(D+'/vm7.duckdb', read_only=True)
H='https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'; UA={'User-Agent':'congressional-tech-review/1.0'}
print(con.execute("SELECT fam, ext, count(DISTINCT sha), round(sum(bytes)/1e9,2) FROM real WHERE fmt='other' GROUP BY ALL ORDER BY 3 DESC LIMIT 6").fetchall())
for key, mem, fam in con.execute("SELECT body_key, mem, fam FROM real WHERE fmt='other' AND ext='.gz' ORDER BY hash(sha) LIMIT 6").fetchall():
    req=urllib.request.Request(H+key, headers={**UA,'Range':'bytes=0-2047'})
    with urllib.request.urlopen(req, timeout=30) as r: raw=r.read()
    time.sleep(0.3)
    l1=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw) if key.endswith('.gz') else raw
    l2=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(l1)[:40] if l1[:2]==b'\x1f\x8b' else b''
    print(fam, (mem or '')[-40:], 'after storage gunzip:', l1[:6], 'second layer:', l2)
