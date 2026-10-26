import pyarrow.parquet as pq,re,sys,collections
t=pq.read_table(sys.argv[1]+'/congress_bills.parquet',columns=['bill_id','congress','bill_type','bill_number'])
ids=t.column('bill_id').to_pylist(); ty=t.column('bill_type').to_pylist(); cg=t.column('congress').to_pylist(); nb=t.column('bill_number').to_pylist()
pat=re.compile(r'\d+-[a-z]+-\d+')
bad=[(i,c,b,n) for i,c,b,n in zip(ids,cg,ty,nb) if i is None or not pat.fullmatch(i)]
print('rows',len(ids),'distinct',len(set(ids)),'nonmatching',len(bad))
for r in bad[:20]: print('  ',r)
print('types',collections.Counter(ty).most_common())
mism=[(i,c,b,n) for i,c,b,n in zip(ids,cg,ty,nb) if i and pat.fullmatch(i) and i!=f"{c}-{(b or '').lower()}-{n}"]
print('id != congress-type-number:',len(mism),mism[:5])
