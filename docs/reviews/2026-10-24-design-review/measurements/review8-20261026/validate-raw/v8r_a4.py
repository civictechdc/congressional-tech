import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); ex=C.Counter()
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            if 'original_path' not in l and 'file_references":[{' not in l: continue
            o=json.loads(l); caps=o.get('captures') or []; frs=o.get('file_references') or []
            for e in caps:
                if isinstance(e,dict) and 'original_path' in e:
                    ptr=str(e.get('pointer') or e.get('pointer_json'))
                    c[('cap op', 'archive_members' in ptr)]+=1
            for e in frs:
                if isinstance(e,dict) and e.get('original_path') is not None:
                    c[('fr op', 'row' if not caps else 'shadowed-by-captures', e['original_path'].startswith('/'))]+=1
                    seg=e['original_path'].rsplit('/',1)[-1]
                    ex['hexname' if len(seg)>=64 and all(ch in '0123456789abcdef' for ch in seg[:64]) else 'other']+=1
            if frs: c[('fr len max',)]=max(c[('fr len max',)],len(frs))
print(sorted(c.items(),key=str)); print('last segment of fr original_path',ex)
