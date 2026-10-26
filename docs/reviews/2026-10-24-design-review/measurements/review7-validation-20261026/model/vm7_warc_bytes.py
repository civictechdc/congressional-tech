"""F1: first bytes of sampled WARC bodies from the public host; one gzip layer (storage) removed, as DM 6.2's sniff would. Also what old readings say."""
import duckdb, urllib.request, zlib, time, glob
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
H='https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'
UA={'User-Agent':'congressional-tech-review/1.0'}
con=duckdb.connect()
rows=con.execute(f"""SELECT body_key, media_type, bytes, stored_bytes, resolution FROM read_parquet('{B}captures.parquet')
  WHERE media_type ILIKE '%arc+gzip%' ORDER BY hash(sha256) LIMIT 7""").fetchall()
rows+=con.execute(f"""SELECT body_key, media_type, bytes, stored_bytes, resolution FROM read_parquet('{B}captures.parquet')
  WHERE media_type ILIKE '%application/arc+gzip%' LIMIT 1""").fetchall()
def get(key, n=4096):
    req=urllib.request.Request(H+key, headers={**UA,'Range':f'bytes=0-{n-1}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.headers.get('Content-Type'), r.headers.get('Content-Encoding'), r.read()
for key, mt, b, sb, res in rows:
    st, ct, ce, raw = get(key); time.sleep(0.3)
    lay1 = zlib.decompressobj(16+zlib.MAX_WBITS).decompress(raw)  # storage gzip
    lay2 = b''
    if lay1[:2]==b'\x1f\x8b':
        try: lay2 = zlib.decompressobj(16+zlib.MAX_WBITS).decompress(lay1)
        except Exception as e: lay2=repr(e).encode()
    print(f"{key[-20:]} media={mt} orig={b} stored={sb} res={res} http={st} ct={ct} ce={ce}")
    print('   stored first bytes:', raw[:4].hex(), ' after storage gunzip:', lay1[:4].hex(), repr(lay1[:12]))
    print('   after second gunzip:', repr(lay2[:60]))
# old readings for WARC bodies
fs=f"{B}readings/*.parquet"
print(con.execute(f"""WITH w AS (SELECT DISTINCT body_key FROM read_parquet('{B}captures.parquet') WHERE media_type ILIKE '%arc+gzip%')
 SELECT r.body_format::VARCHAR, r.status, r.record_role::VARCHAR, count(*) FROM read_parquet('{fs}') r JOIN w USING (body_key) GROUP BY ALL ORDER BY 4 DESC""").fetchall())
print('WARC bodies with any reading:', con.execute(f"""WITH w AS (SELECT DISTINCT body_key FROM read_parquet('{B}captures.parquet') WHERE media_type ILIKE '%arc+gzip%')
 SELECT count(*), count(*) FILTER (WHERE body_key IN (SELECT body_key FROM read_parquet('{fs}'))) FROM w""").fetchall())
