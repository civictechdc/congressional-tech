import duckdb, gzip, os, re, unicodedata, difflib, json, sys
from lxml import html as LH, etree
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
DL=O+'downloads/'
c=duckdb.connect()
c.sql(f"create table s as select * from '{O}sample_html.parquet'")
c.sql(f"create table b as select * from '{O}bodies_html.parquet'")
c.sql(f"create table o as select * from '{O}origin_html.parquet'")
c.sql(f"create table g as select * from '{O}good_html.parquet'")
rows=c.sql("""select s.context_url, coalesce(s.stratum,'other'), list(b.body_key order by b.first_seen) from s join b using(context_url) group by all""").fetchall()
orig={r[0]:r[1:] for r in c.sql("select k, nlines, has_attempt, has_import, has_fileref from o").fetchall()}
# per body origin label: attempt(direct) / final(zyte) / import / fileref / fetch
borig={}
for k,sha,mode,att,tr,ts in c.sql("select req_key, sha256, mode, attempt, transport, coalesce(retrieved_at,rec_retrieved_at) from g").fetchall():
    lab=('fileref' if mode.startswith('fileref') else 'import' if mode=='retained_import' else ('attempt-'+str(tr) if att>=0 else 'final-'+str(tr)))
    borig.setdefault((k,sha),set()).add(lab+'@'+(ts or '')[:10])
def visible(raw):
    try:
        doc=LH.document_fromstring(raw)
    except Exception as e:
        return None, {}
    for el in doc.xpath('//script|//style|//noscript|//template|//svg'):
        el.drop_tree()
    for el in doc.xpath('//comment()'):
        p=el.getparent()
        if p is not None: p.remove(el)
    title=' '.join(doc.xpath('string(//title)').split())
    links=doc.xpath('//a[@href]')
    ltb=sum(len(' '.join(a.text_content().split())) for a in links)
    t=doc.text_content()
    t=' '.join(unicodedata.normalize('NFKC',t).split())
    h1=' '.join(doc.xpath('string((//h1)[1])').split())
    # main region if present
    main=doc.xpath('//main|//article|//*[@id="main-content"]|//*[@role="main"]')
    mt=' '.join(unicodedata.normalize('NFKC',main[0].text_content()).split()) if main else None
    return t, dict(title=title, h1=h1, links=len(links), link_text=ltb, text_bytes=len(t.encode()), main=mt)
out=[]
for url, stratum, keys in rows:
    keys=keys[:6]
    vers=[]
    for k in keys:
        p=DL+k.split('/')[-1]
        if not os.path.exists(p): vers.append(None); continue
        raw=gzip.decompress(open(p,'rb').read())
        t,meta=visible(raw)
        sha=k.split('/')[-1][:-3]
        vers.append(dict(sha=sha, bytes=len(raw), text=t, meta=meta, origin=sorted(borig.get((url,sha),[]))))
    ok=[v for v in vers if v and v['text'] is not None]
    rec=dict(url=url, stratum=stratum, n=len(keys), nfetched=len(ok), origin=orig.get(url))
    if len(ok)>=2:
        a,bv=ok[0],ok[1]
        rec['identical_text']=all(v['text']==a['text'] for v in ok)
        rec['identical_main']=all(v['meta']['main']==a['meta']['main'] for v in ok) if a['meta']['main'] is not None else None
        aw,bw=a['text'].split(),bv['text'].split()
        sm=difflib.SequenceMatcher(None,aw,bw,autojunk=False)
        ops=[(tag,' '.join(aw[i1:i2])[:300],' '.join(bw[j1:j2])[:300]) for tag,i1,i2,j1,j2 in sm.get_opcodes() if tag!='equal']
        rec['ratio']=sm.ratio(); rec['changed_words']=sum(max(i2-i1,j2-j1) for tag,i1,i2,j1,j2 in sm.get_opcodes() if tag!='equal')
        rec['ops']=ops[:15]; rec['nops']=len(ops)
        rec['versions']=[dict(sha=v['sha'][:12], bytes=v['bytes'], origin=v['origin'], **{k:v['meta'][k] for k in ('title','h1','links','link_text','text_bytes')}) for v in ok]
    out.append(rec)
json.dump(out, open(O+'compare_html.json','w'), indent=1)
print(len(out), sum(1 for r in out if r.get('identical_text')), sum(1 for r in out if r['nfetched']>=2))
