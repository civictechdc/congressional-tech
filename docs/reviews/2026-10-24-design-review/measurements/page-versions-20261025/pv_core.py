import json, gzip, glob, re, unicodedata, difflib
from lxml import html as LH
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
d=json.load(open(O+'compare_html.json'))
SEL=["//*[contains(concat(' ',@class,' '),' field-name-body ')]","//main","//article","//*[@id='main-content']","//*[@role='main']","//pre"]
ERR=re.compile(r'not found|access denied|error encountered|page not found|404|forbidden|just a moment|attention required',re.I)
def norm(t): return ' '.join(unicodedata.normalize('NFKC',t).split())
def core(sha):
    p=glob.glob(O+'downloads/'+sha+'*')[0]
    doc=LH.document_fromstring(gzip.decompress(open(p,'rb').read()))
    for el in doc.xpath('//script|//style|//noscript|//template|//svg'): el.drop_tree()
    for s in SEL:
        els=doc.xpath(s)
        if els:
            return s, norm(' '.join(e.text_content() for e in els))
    return 'whole', norm(doc.text_content())
def trivial_only(a,b):
    aw,bw=a.split(),b.split()
    sm=difflib.SequenceMatcher(None,aw,bw,autojunk=False)
    ch=[w for tag,i1,i2,j1,j2 in sm.get_opcodes() if tag!='equal' for w in aw[i1:i2]+bw[j1:j2]]
    nontriv=[w for w in ch if not re.fullmatch(r'[\d:/.,\-#]+|(am|pm|AM|PM|EST|EDT|GMT)',w)]
    return sm.ratio(), len(ch), nontriv
for r in d:
    if r.get('identical_text') is not False: continue
    vs=r['versions']
    cores=[core(v['sha']) for v in vs]
    r['core_sel']=[c[0] for c in cores]
    r['core_identical']=all(c[1]==cores[0][1] for c in cores)
    r['core_bytes']=[len(c[1]) for c in cores]
    ratio,nch,nontriv=trivial_only(cores[0][1],cores[1][1])
    r['core_ratio']=ratio; r['core_changed']=nch; r['core_nontrivial_words']=len(nontriv); r['core_nontriv_sample']=' '.join(nontriv[:40])
    r['error_titles']=[bool(ERR.search(v['title'] or '')) for v in vs]
json.dump(d, open(O+'compare_html.json','w'), indent=1)
import collections
C=collections.Counter()
for r in d:
    if r.get('identical_text') is False:
        C[(r['stratum'], r['core_identical'], 'err' if any(r['error_titles']) else '', r['core_nontrivial_words']==0)]+=1
for k,v in sorted(C.items(),key=str): print(k,v)
