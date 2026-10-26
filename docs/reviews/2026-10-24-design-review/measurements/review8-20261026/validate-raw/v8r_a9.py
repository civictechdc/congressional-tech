import gzip,json,glob,collections as C,re
import duckdb
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); bodies=C.defaultdict(set); folders=C.defaultdict(set)
for fam in ('house/witness-xml','house/meeting-xml'):
    for p in glob.glob(R+fam+'/*/*.gz'):
        for l in gzip.open(p,'rt'):
            o=json.loads(l); r=o.get('record') if isinstance(o.get('record'),dict) else {}
            rows=(o.get('captures') or [])+(o.get('file_references') or [])
            for e in rows:
                u=e.get('context_url') or r.get('url') or ''
                fn=u.rsplit('/',1)[-1]
                pat=re.sub(r'\d+','N',fn)
                c[(fam,pat)]+=1
                if e.get('sha256'): bodies[fam].add(e['sha256'])
                m=re.search(r'/meetings/\w+/\w+/\d+/(\d+)/',u)
                if m: folders[fam].add(m.group(1))
for k,v in c.most_common(12): print(v,k)
print({k:len(v) for k,v in bodies.items()}); print('meeting folders',{k:len(v) for k,v in folders.items()}, 'both',len(folders['house/witness-xml']&folders['house/meeting-xml']))
con=duckdb.connect()
print(con.sql("select family,count(*) n,count(distinct sha256) b from '/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/captures.parquet' where family like 'house/%' group by 1 order by 1").fetchall())
