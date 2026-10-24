"""Connected components proxy over real source-file graph + occurrence stats."""
import time, resource, array, sys
import duckdb

base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect(); con.execute("SET memory_limit='8GB'; SET threads=4;")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/2**20

t0=time.time()
# occurrences stats from documents.parquet
r = con.execute(f"""
select count(*) docs, sum(len(source_occurrences)) occ, max(len(source_occurrences)) max_occ,
       quantile_cont(len(source_occurrences),0.5) med_occ, quantile_cont(len(source_occurrences),0.99) p99_occ,
       sum(len(body_keys)) body_refs, max(len(body_keys)) max_bodies, sum(len(filenames)) fn_refs, max(len(filenames)) max_filenames,
       sum(len(source_urls)) url_refs, max(len(source_urls)) max_urls
from read_parquet('{base}/documents.parquet')""").fetchall()[0]
print("documents:", dict(zip(["docs","occurrences","max_occ","med_occ","p99_occ","body_refs","max_bodies","fn_refs","max_filenames","url_refs","max_urls"], r)), f"{time.time()-t0:.1f}s")

r = con.execute(f"""
select count(*) n_rows, count(distinct source_id) src, count(distinct document_id) docs, count(distinct body_key) bodies,
       count(distinct source_url) urls, count(distinct filename) filenames, sum(len(source_occurrences)) occ, sum(len(state_body_key)) state_keys
from read_parquet('{base}/filenames.parquet')""").fetchall()[0]
print("filenames:", dict(zip(["rows","source_ids","document_ids","bodies","urls","filenames","occurrences","state_body_keys"], r)), f"{time.time()-t0:.1f}s")

# record_role distribution and docs per role
print(con.execute(f"select record_role[1] rr, count(*) n from read_parquet('{base}/filenames.parquet') group by 1 order by 2 desc").fetchall())

# Build integer edge lists.
t1=time.time()
con.execute(f"""
create table f as select source_id, body_key, source_url, state_body_key from read_parquet('{base}/filenames.parquet');
create table nodes as select node, row_number() over () - 1 as nid from (
  select distinct node from (
    select source_id node from f union all select body_key from f union all select source_url from f
    union all select unnest(state_body_key) from f) where node is not null);
""")
n_nodes = con.execute("select count(*) from nodes").fetchone()[0]
print(f"nodes={n_nodes:,} built in {time.time()-t1:.1f}s rss={rss():.0f}MB")

def edges(sql):
    t=time.time()
    a,b = con.execute(sql).fetchnumpy().values() if False else (None,None)
    rows = con.execute(sql).fetchall()
    print(f"  edges={len(rows):,} fetched in {time.time()-t:.1f}s")
    return rows

def cc(edge_rows, n):
    t=time.time()
    parent = array.array('i', range(n))
    def find(x):
        root = x
        while parent[root] != root: root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root
    for a,b in edge_rows:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb: parent[rb] = ra
            else: parent[ra] = rb
    roots = {}
    for i in range(n):
        r = find(i); roots[r] = roots.get(r,0)+1
    sizes = sorted(roots.values(), reverse=True)
    print(f"  union-find: {time.time()-t:.1f}s rss={rss():.0f}MB components={len(sizes):,} largest={sizes[:5]} singletons={sum(1 for s in sizes if s==1):,}")
    return parent

e_body = edges("""select a.nid, b.nid from f join nodes a on a.node=f.source_id join nodes b on b.node=f.body_key""")
e_url  = edges("""select a.nid, b.nid from f join nodes a on a.node=f.source_id join nodes b on b.node=f.source_url""")
e_state= edges("""select a.nid, b.nid from (select source_id, unnest(state_body_key) k from f) x join nodes a on a.node=x.source_id join nodes b on b.node=x.k""")

print("CC over source-body edges only:"); cc(e_body, n_nodes)
print("CC over source-body + source-state_body edges:"); cc(e_body+e_state, n_nodes)
print("CC over source-body + state + source-url edges:"); cc(e_body+e_state+e_url, n_nodes)
print(f"total {time.time()-t0:.1f}s peak rss={rss():.0f}MB")
