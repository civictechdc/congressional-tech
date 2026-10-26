# Cluster the short pages: by normalized title, opening words, host, and TF-IDF + k-means (numpy).
import json, re, collections, duckdb, numpy as np, sys
c = duckdb.connect()
c.sql("create table x as select * from read_json_auto('parsed.jsonl', format='newline_delimited') join 'sample.parquet' using(sha256)")
rows = c.sql("select sha256, hgroup, host, coalesce(member_path, context_url) loc, title, heading, text, text_bytes, weight from x where text_bytes < 2048").fetchall()
norm = lambda s: re.sub(r'\s+', ' ', re.sub(r'[0-9]+', '#', (s or '').lower())).strip()
def show(name, keyf, top=25):
    cnt = collections.Counter(); w = collections.Counter()
    for r in rows: k = keyf(r); cnt[k] += 1; w[k] += r[8]
    print(f'\n== by {name} (sample n, weighted est.)')
    for k, n in cnt.most_common(top): print(f'{n:5d} {w[k]:9.0f}  {k[:110]!r}')
show('normalized title', lambda r: norm(re.split(r' \| ', r[4] or '')[0])[:90])
show('opening words', lambda r: ' '.join(norm(r[6]).split()[:8]))
show('host group', lambda r: r[1])
# TF-IDF + k-means over word unigrams
TOK = re.compile(r'[a-z]{3,}')
docs = [TOK.findall((r[4] + ' ' + r[6]).lower()) for r in rows]
df = collections.Counter(t for d in docs for t in set(d))
vocab = [t for t, n in df.items() if n >= 3 and n <= 0.9 * len(docs)]
ix = {t: i for i, t in enumerate(vocab)}
X = np.zeros((len(docs), len(vocab)))
for i, d in enumerate(docs):
    for t, n in collections.Counter(d).items():
        if t in ix: X[i, ix[t]] = (1 + np.log(n)) * np.log(len(docs) / df[t])
X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
K = int(sys.argv[1]) if len(sys.argv) > 1 else 14
rng = np.random.default_rng(0)
best = None
for seed in range(5):
    C = X[rng.choice(len(X), K, replace=False)]
    for _ in range(50):
        lab = (X @ C.T).argmax(1)
        C = np.array([X[lab == k].mean(0) if (lab == k).any() else C[k] for k in range(K)])
        C /= np.maximum(np.linalg.norm(C, axis=1, keepdims=True), 1e-9)
    score = (X * C[lab]).sum()
    if best is None or score > best[0]: best = (score, lab, C)
_, lab, C = best
print(f'\n== TF-IDF k-means, k={K}')
out = {}
for k in range(K):
    m = np.where(lab == k)[0]
    if not len(m): continue
    terms = [vocab[j] for j in C[k].argsort()[::-1][:8]]
    print(f'\ncluster {k}: n={len(m)} est={sum(rows[i][8] for i in m):.0f} terms={terms}')
    for i in m[:3]: print('   ', rows[i][1], '|', (rows[i][4] or '')[:70], '|', rows[i][6][:90])
    for i in m: out[rows[i][0]] = int(k)
json.dump(out, open('kmeans.json', 'w'))
# term table over short pages (title + visible text), weighted by inclusion weight
STOP = set('the and for with this that from are was were you your our will has have not but all can its his her their they them more about into than also only any been who which what when where how other such these those may per one two new use page home click here search skip content menu close link main site'.split())
tc = collections.Counter(); tw = collections.Counter()
for r, d in zip(rows, docs):
    for t in set(d):
        if t not in STOP: tc[t] += 1; tw[t] += r[8]
json.dump({'count': tc.most_common(80), 'weighted': tw.most_common(80)}, open('terms.json', 'w'))
print('\n== top terms (pages containing term: sample n / weighted est.)')
for t, n in tw.most_common(40): print(f'{t:20s} {tc[t]:5d} {n:9.0f}')
