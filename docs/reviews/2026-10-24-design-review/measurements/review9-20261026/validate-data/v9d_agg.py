import pickle, collections, re
res = pickle.load(open('out/scan.pkl','rb'))
C = collections.Counter(); P = collections.Counter(); seg = collections.Counter(); rt = collections.Counter()
for r in res:
    C.update(r['C']); P.update(r['P']); seg.update(r['seg']); rt.update(r['rt'])
print('== line counters'); [print(' ', k, v) for k, v in sorted(C.items())]
print('== roundtrip'); [print(' ', k, v) for k, v in sorted(rt.items())]
cut = [r for r in res if r['has_cut']]
print('receipts with cut', len(cut), 'of', len(res), 'MB', sum(r['size'] for r in cut)/1e6, 'clean MB', sum(r['size'] for r in res if not r['has_cut'])/1e6)
kinds = collections.defaultdict(collections.Counter)
for (k, p), v in P.items(): kinds[k][p] += v
for k, c in sorted(kinds.items()):
    print(f'== {k}: total {sum(c.values())} in {len(c)} normalized paths')
    def gen(p): return re.sub(r'\.<(abs|dyn)-key>', '.<*>', p)
    print('   paths after collapsing dyn keys:', len({gen(p) for p in c}))
    for p, v in c.most_common(12 if 'cookie' in k else 6): print('    ', v, p[:140])
print('== first segments of /-leading values (top 25, local-looking marked)')
for s, v in seg.most_common(25): print('   ', v, s)
print('== per family latest')
fam = collections.defaultdict(lambda: ['', '', ''])
for r in res:
    f = fam[r['fam']]
    if re.match(r'\d{4}-', r['ddir']) and r['ddir'] > f[0]: f[0] = r['ddir']
    if r['fdate'] > f[1]: f[1] = r['fdate']
    if r['maxts'] > f[2]: f[2] = r['maxts']
for k, v in sorted(fam.items()): print(f'   {k:28s} dir={v[0]:10s} filename={v[1]:10s} max_retrieved={v[2][:19]}')
