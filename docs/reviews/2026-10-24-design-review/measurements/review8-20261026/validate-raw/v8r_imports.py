import pickle,sys,collections as C
S,imp,maxfr=pickle.load(open(sys.argv[1],'rb'))
n=len(imp); print('import lines',n)
keyc=C.Counter()
for d in imp:
    for k in d['ks']:
        if 'recovery_evidence' in k or k.startswith('record.source_associations') or k in ('record.url','record.requested_url','record.retrieved_at','record.publisher_requested','record.content.sha256','captures','file_references','record.mode'):
            keyc[k]+=1
for k,v in sorted(keyc.items()):
    if k.count('.')<=4 and 'requests' not in k and 'candidate' not in k[:]: print(f'{v:6d} {k}')
