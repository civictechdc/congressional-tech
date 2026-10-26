"""Fetch HTML bodies from the public host (GET, fixed UA, <=4 req/s, cached) and classify them with the committed short-page rule
(short-pages-20261025 rules.json 'c2': error word in title/heading | error URL | challenge marker | download interstitial | text < 128 B)
plus DM 7.3's other HTML arms: wrapper marker; listing signals reported raw (link count, link-text share; thresholds unset in DM).
Usage: vm7_classify.py <input.parquet with sha, body_key, ctx> <cache dir> <out.jsonl>"""
import sys, time, gzip, re, json, pathlib, duckdb, urllib.request
import lxml.html
H='https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'
UA={'User-Agent':'congressional-tech-review/1.0'}
# regexes copied from sp_rules.py (committed)
ERRW = re.compile(r'access denied|forbidden|not found|retry later|service unavailable|\berror\b', re.I)
ERRURL = re.compile(r'/(404|error|errors|notfound|not-found|page-not-found)(\b|[/.?_-])|[?&]aspxerrorpath=', re.I)
CHAL = re.compile(r'cf-chl|challenge-platform|_Incapsula_Resource|<title>\s*(Just a moment|Client Challenge|Attention Required|Access Denied)', re.I)
WS=re.compile(r'\s+')
inp, cache, out = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3]
cache.mkdir(exist_ok=True)
rows=duckdb.sql(f"SELECT DISTINCT sha, body_key, any_value(ctx) OVER (PARTITION BY sha) FROM '{inp}'").fetchall()
seen=set(); res=[]
for sha, key, ctx in rows:
    if sha in seen: continue
    seen.add(sha)
    p=cache/(sha+'.gz')
    if not p.exists():
        t0=time.monotonic()
        req=urllib.request.Request(H+key, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=60) as r: p.write_bytes(r.read())
        except Exception as e:
            res.append(dict(sha=sha, ctx=ctx, error=str(e)[:80])); continue
        time.sleep(max(0, 0.26-(time.monotonic()-t0)))
    raw=p.read_bytes()
    try: b=gzip.decompress(raw)
    except Exception: b=raw
    head=b[:30000].decode('utf-8','replace')
    try:
        doc=lxml.html.document_fromstring(b)
    except Exception as e:
        res.append(dict(sha=sha, ctx=ctx, parse_error=str(e)[:80])); continue
    title=WS.sub(' ',' '.join(doc.xpath('//title//text()'))).strip()
    links=doc.xpath('//a[@href]')
    link_text=sum(len(WS.sub(' ',a.text_content()).strip().encode()) for a in links)
    for el in doc.xpath('//script|//style|//noscript|//template|//head'): el.drop_tree()
    text=WS.sub(' ',doc.text_content()).strip()
    h=doc.xpath('//h1|//h2|//h3'); heading=WS.sub(' ',h[0].text_content()).strip() if h else ''
    tb=len(text.encode())
    sig=dict(errw=bool(ERRW.search(title) or ERRW.search(heading)), errurl=bool(ERRURL.search(ctx or '')), chal=bool(CHAL.search(head)),
             inter=('download will begin shortly' in text) or heading=='Download File', tiny=tb<128)
    role='error_response' if (sig['errw'] or sig['errurl'] or sig['chal'] or sig['tiny']) else 'wrapper' if sig['inter'] else 'document'
    res.append(dict(sha=sha, ctx=ctx, title=title[:150], heading=heading[:150], text_bytes=tb, n_links=len(links), link_text_bytes=link_text,
                    link_share=round(link_text/max(tb,1),2), role_c2=role, **sig, text_head=text[:300]))
pathlib.Path(out).write_text('\n'.join(json.dumps(r) for r in res))
import collections; print(len(res), collections.Counter(r.get('role_c2','ERR') for r in res))
