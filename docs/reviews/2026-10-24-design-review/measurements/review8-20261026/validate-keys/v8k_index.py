import json,sys
d=json.load(open(sys.argv[1]))
want=set(sys.argv[2].split(','))
for fam,f in d['families'].items():
    for t,m in f.get('tables',{}).items():
        name=t.rsplit('.',1)[0]
        if name in want or 'all' in want:
            print(fam, t, m.get('rows'), m.get('byteSize'), f['prefix']+'/'+m.get('key',t))
            if 'all' not in want: print('   ', [c[0]+':'+c[1] for c in m['columns']])
