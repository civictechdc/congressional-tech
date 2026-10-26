# Labeling sheet: one entry per distinct short text (digits normalized), host nav prefix/suffix stripped.
import duckdb, re, os, collections, json
c = duckdb.connect()
c.sql("create table x as select * from read_json_auto('parsed.jsonl', format='newline_delimited') join 'sample.parquet' using(sha256)")
rows = c.sql("select sha256, host, coalesce(member_path, context_url) loc, title, text, text_bytes, weight, refresh, pdf_links, n_links, challenge_marker, err_word, heading from x where text_bytes<2048 order by host, loc").fetchall()
byhost = collections.defaultdict(list)
for r in rows: byhost[r[1]].append(r)
def common_affix(texts, rev=False):
    ws = [t.split()[::-1] if rev else t.split() for t in texts]
    n = 0
    while all(len(w) > n for w in ws) and len({w[n] for w in ws}) == 1: n += 1
    return n
groups = collections.OrderedDict()
for h, rs in byhost.items():
    texts = list({re.sub(r'\d', '#', r[4]) for r in rs})
    p = common_affix(texts) if len(texts) >= 3 else 0
    s = common_affix(texts, True) if len(texts) >= 3 else 0
    for r in rs:
        key = (h, re.sub(r'\d', '#', r[4].lower()))
        w = r[4].split(); core = ' '.join(w[p: len(w) - s if s else None])
        hd = (r[12] or '').strip()
        if hd and len(hd) > 3 and r[4].find(hd) > 0: core = '[H1] ' + r[4][r[4].find(hd):]
        g = groups.setdefault(key, dict(id=len(groups), host=h, n=0, est=0.0, shas=[], loc=r[2], title=r[3], bytes=r[5], core=core, sig=dict(refresh=r[7], pdf=r[8], links=r[9], chal=r[10], errw=r[11])))
        g['n'] += 1; g['est'] += r[6]; g['shas'].append(r[0])
json.dump(list(groups.values()), open('groups.json', 'w'))
with open('sheet.txt', 'w') as f:
    for g in groups.values():
        f.write(f"#{g['id']} n={g['n']} est={g['est']:.0f} {g['bytes']}B {g['loc'][:120]}\n  T: {g['title'][:120]}\n  {g['core'][:650]}\n\n")
print(len(groups), 'groups')
