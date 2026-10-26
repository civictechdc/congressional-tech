import duckdb, os
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
local={}
for d,_,fs in os.walk(R):
    for f in fs:
        p=os.path.join(d,f); local['receipts/'+os.path.relpath(p,R)]=os.path.getsize(p)
con=duckdb.connect()
rows=con.execute("select key,bytes,last_modified_utc from read_csv('/Users/mikewolfd/Work/congressional-tech/output/r2-survey-20261019/congressional-tech-raw-objects.csv.gz',header=true,columns={'key':'VARCHAR','bytes':'BIGINT','last_modified_utc':'VARCHAR'}) where key like 'receipts/%'").fetchall()
lst={k:b for k,b,_ in rows}
print('local',len(local),sum(local.values()),'listing',len(lst),sum(lst.values()))
print('same keys',len(set(local)&set(lst)),'size match',sum(1 for k in lst if local.get(k)==lst[k]))
print('max lm',max(r[2] for r in rows))
print('only local',list(set(local)-set(lst))[:3],'only listing',list(set(lst)-set(local))[:3])
