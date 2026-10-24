"""Time house_naming.Engine.extract on a random sample of real filenames."""
import sys, time, statistics, resource
sys.path.insert(0, "/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/house-naming/src")
try:
    import jsonschema  # noqa
    print("jsonschema", jsonschema.__version__)
except Exception as e:
    print("jsonschema import failed:", e)
import duckdb
from house_naming import Engine

base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect(); con.execute("SET threads=2; SET memory_limit='3GB';")
rows = con.execute(f"""select filename, source_url from read_parquet('{base}/filenames.parquet')
                       where filename is not null using sample 3000 rows (reservoir, 42)""").fetchall()
print("sample", len(rows))
t = time.time(); eng = Engine(); print(f"Engine() load {time.time()-t:.2f}s")
times = []
ok = 0
for fn, url in rows:
    t = time.perf_counter()
    try:
        eng.extract(fn, source_url=url)
        ok += 1
    except Exception as e:
        pass
    times.append((time.perf_counter()-t)*1000)
times.sort()
n=len(times)
print(f"extract: n={n} ok={ok} mean={statistics.mean(times):.2f}ms median={times[n//2]:.2f}ms p90={times[int(n*.9)]:.2f}ms p99={times[int(n*.99)]:.2f}ms max={times[-1]:.1f}ms total={sum(times)/1000:.1f}s")
per = statistics.mean(times)/1000
print(f"extrapolated single-core: 1,683,430 filenames -> {1683430*per/60:.1f} min; 1,241,157 docs -> {1241157*per/60:.1f} min; on 4 vCPU -> {1683430*per/60/4:.1f} min")
print(f"maxrss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20:.0f}MB")
