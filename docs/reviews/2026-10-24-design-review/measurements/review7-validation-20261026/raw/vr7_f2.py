"""Finding 2: receipt type conflicts (data side)."""
import sys, os, json, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vr7_db import con, q
c=con()
q(c,"select top_keys, count(*) from l group by 1 order by 2 desc","top-level key sets")
q(c,"select rec_type, count(*), count(distinct rk) from l group by 1","record JSON type: lines, receipts")
q(c,"select rk, count(*) from l where rec_type='list' group by 1 order by 1","receipts with record-as-list")
q(c,"select r_http_status, count(*), count(distinct rk) from l where r_http_status like 'str:%' or r_http_status like 'null%' or r_http_status like 'float%' group by 1","record.http_status non-int")
q(c,"select split_part(r_http_status,':',1) t, count(*) from l where r_http_status is not null group by 1","record.http_status types")
q(c,"select rk, count(*) from l where r_http_status = 'str:' group by 1","receipts with http_status ''")
q(c,"select ptr_types, count(*), count(distinct rk) from r where kind='cap' group by 1","captures[].pointer element types")
q(c,"select max(nbytes), arg_max(rk, nbytes), count(*) filter (nbytes > 1048576), count(*) filter (nbytes>16*1048576) from l","longest line; lines >1 MiB; >16 MiB")
# type conflicts per receipt from the walk
lines_per=dict(c.execute("select rk, count(*) from l group by 1").fetchall())
per_path=collections.defaultdict(lambda: collections.defaultdict(collections.Counter))  # path -> type -> rk -> lines
for fn in glob.glob('scan/types/*.json'):
    d=json.load(open(fn)); rk=d['rk']
    for p,t,n,nl in d['types']:
        per_path[p][t][rk]+=nl
def conflicts(kind):
    """kind='within': a path has >=2 non-null types inside one receipt.
       kind='corpus': a path has >=2 non-null types anywhere; a receipt holding the minority type conflicts."""
    bad=collections.defaultdict(set)
    for p,tm in per_path.items():
        types={t for t in tm if t!='null'}
        if len(types)<2: continue
        if kind=='within':
            for rk in set().union(*[set(tm[t]) for t in types]):
                ts={t for t in types if rk in tm[t]}
                if len(ts)>=2: bad[rk].add((p,tuple(sorted(ts))))
        else:
            tot={t:sum(tm[t].values()) for t in types}; maj=max(tot,key=tot.get)
            for t in types:
                if t==maj: continue
                for rk in tm[t]: bad[rk].add((p,maj+'->'+t))
    return bad
for kind in ('within','corpus'):
    bad=conflicts(kind)
    print(f'## {kind}: receipts with a conflict', len(bad), 'lines', sum(lines_per[r] for r in bad))
    # exclude int/float only conflicts
    def real(cs): return {x for x in cs if not (isinstance(x[1],tuple) and set(x[1])<= {'int','float'}) and x[1] not in ('int->float','float->int')}
    bad2={r:real(cs) for r,cs in bad.items() if real(cs)}
    print(f'   excluding int/float-only: receipts', len(bad2), 'lines', sum(lines_per[r] for r in bad2))
    pc=collections.Counter(); 
    for r,cs in bad2.items():
        for p,t in cs: pc[(p,t if isinstance(t,str) else '/'.join(t))]+=1
    for (p,t),n in pc.most_common(25): print('   ',n,p,t)
    if kind=='within':
        for r in sorted(bad2, key=lambda r:-lines_per[r])[:30]: print('    ', r, lines_per[r], len(bad2[r]))
# distinct record keys across corpus (unnormalized), via the walk is impossible for >64-key dicts; count normalized
rk_keys={p.split('.')[2] for p in per_path if p.startswith('$.record.') and p.count('.')>=2}
print('## distinct $.record.<key> paths (dicts >64 keys collapsed to *):', len(rk_keys))
