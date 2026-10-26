# Population estimates per kind with stratified 95% intervals.
import duckdb, json, math, collections
c = duckdb.connect()
c.sql("create table x as select * from read_json_auto('parsed.jsonl', format='newline_delimited') join 'sample.parquet' using(sha256)")
sig = json.load(open('signals.json'))
c.sql("create table l(sha256 varchar, kind varchar)"); c.executemany("insert into l values (?,?)", [(k, v['kind']) for k, v in sig.items()])
strata = {(h, b): N for h, b, N in c.sql("select hgroup, sbucket, N from 'strata.parquet'").fetchall()}
rows = c.sql("select hgroup, sbucket, kind, text_bytes from x join l using(sha256)").fetchall()
by = collections.defaultdict(list)
for h, b, k, tb in rows: by[(h, b)].append((k, tb))
def est(pred):
    e = v = 0.0
    for key, items in by.items():
        N, n = strata[key], len(items); p = sum(pred(k, tb) for k, tb in items) / n
        e += N * p
        if n > 1: v += N * N * (1 - n / N) * p * (1 - p) / (n - 1)
    return e, 1.96 * math.sqrt(v)
tot = sum(strata.values())
out = {}
e, ci = est(lambda k, tb: tb < 2048); out['short_all'] = (e, ci)
print(f'population {tot}; short {e:.0f} ± {ci:.0f} ({100*e/tot:.1f}%)')
for kind in sorted({k for _, _, k, _ in rows}):
    e, ci = est(lambda k, tb, kind=kind: k == kind and tb < 2048)
    if e: out[kind] = (e, ci); print(f'{kind:28s} {e:8.0f} ± {ci:5.0f}  {100*e/out["short_all"][0]:.1f}% of short')
e, ci = est(lambda k, tb: k == 'download_interstitial' and tb >= 2048); out['interstitial_long'] = (e, ci); print('interstitials >=2KB', round(e), round(ci))
e, ci = est(lambda k, tb: k == 'long_page' and tb < 3072); print('long pages 2-3KB', round(e), round(ci))
json.dump(out, open('estimates.json', 'w'))
