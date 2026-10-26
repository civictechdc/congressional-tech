# Stratified sample (host group x raw-size bucket) with inclusion weights.
import duckdb, math, random
c = duckdb.connect()
c.sql("""create table p as select *,
  case when host='www.govinfo.gov' and member_path is null then 'govinfo-details'
       when host='www.govinfo.gov' then 'govinfo-chrg-member'
       when host in (select host from 'pop.parquet' group by host having count(*)>=100) then host
       when host like '%house.gov' then 'small-house'
       when host like '%senate.gov' then 'small-senate'
       else 'small-other' end as hgroup,
  case when bytes<5000 then 'a<5k' when bytes<15000 then 'b5-15k' when bytes<40000 then 'c15-40k' else 'd>=40k' end as sbucket
  from 'pop.parquet'""")
strata = c.sql("select hgroup, sbucket, count(*) from p group by all").fetchall()
BUDGET = 3000
small = [s for s in strata if s[1] in ('a<5k','b5-15k')]
big = [s for s in strata if s[1] not in ('a<5k','b5-15k')]
alloc = {}
for h, b, n in small:
    alloc[(h, b)] = min(n, 400)           # small raw bodies: take nearly all
left = BUDGET - sum(alloc.values())
ss = sum(math.sqrt(n) for _, _, n in big)
for h, b, n in big:
    alloc[(h, b)] = min(n, max(15, round(left * math.sqrt(n) / ss)))
rows = []
rng = random.Random(20261025)
for (h, b), k in alloc.items():
    shas = [r[0] for r in c.sql("select sha256 from p where hgroup=? and sbucket=? order by sha256", params=[h, b]).fetchall()]
    N = len(shas)
    for s in rng.sample(shas, k):
        rows.append((s, h, b, N / k))
c.sql("create table s(sha256 varchar, hgroup varchar, sbucket varchar, weight double)")
c.executemany("insert into s values (?,?,?,?)", rows)
c.sql("copy (select p.*, s.weight from p join s using(sha256, hgroup, sbucket)) to 'sample.parquet'")
c.sql("copy (select hgroup, sbucket, count(*) N from p group by all) to 'strata.parquet'")
print(len(rows), 'sampled; weight sum', sum(r[3] for r in rows))
for k, v in sorted(alloc.items()): print(k, v)
