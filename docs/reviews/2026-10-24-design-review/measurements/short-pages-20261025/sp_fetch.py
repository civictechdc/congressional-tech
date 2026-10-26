# Fetch sampled bodies from the public bucket: GET only, fixed UA, <=4.5 req/s, cached on disk.
import sys, time, pathlib, duckdb, httpx
BASE = 'https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'
OUT = pathlib.Path(sys.argv[2])
keys = [r[0] for r in duckdb.sql(f"select body_key from '{sys.argv[1]}'").fetchall()]
todo = [k for k in keys if not (OUT / (k.rsplit('/', 1)[1])).exists()]
print(len(keys), 'keys,', len(todo), 'to fetch', flush=True)
fails = 0
with httpx.Client(headers={'User-Agent': 'congressional-tech-review/1.0'}, timeout=60) as cl:
    for i, k in enumerate(todo):
        t0 = time.monotonic()
        try:
            r = cl.get(BASE + k)
            if r.status_code == 200:
                (OUT / k.rsplit('/', 1)[1]).write_bytes(r.content)
            else:
                fails += 1; print('status', r.status_code, k, flush=True)
        except Exception as e:
            fails += 1; print('err', k, e, flush=True)
        if i % 250 == 0: print(i, 'done', fails, 'fails', flush=True)
        time.sleep(max(0, 0.23 - (time.monotonic() - t0)))
print('finished', fails, 'fails', flush=True)
