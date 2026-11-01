# Independent re-derivation of the release-diff numbers: pyarrow and Python sets, no SQL.
import sys,collections,hashlib,json,os
import pyarrow.parquet as pq, pyarrow.compute as pc
d,A=sys.argv[1:3]
def col(s,t,c): return pq.read_table(f'{d}/{s}/{t}.parquet',columns=[c]).column(c)
def tab(s,t,cs): return pq.read_table(f'{d}/{s}/{t}.parquet',columns=cs).to_pylist()
pl={bytes(x) for x in col('prev','links','link_key').to_pylist()}; ll={bytes(x) for x in col('live','links','link_key').to_pylist()}
print('links prev-live',len(pl-ll),'live-prev',len(ll-pl))
for s in('prev','live'):
    print(s,'member rows',pc.sum(pc.is_valid(col(s,'sources','member_path'))).as_py(),'null url',pc.sum(pc.is_null(col(s,'sources','url'))).as_py(),'formats',{k:v for k,v in collections.Counter(col(s,'list','format').to_pylist()).items() if k in('zip','html','pdf')})
pu=set(col('prev','url_state','requested_url').to_pylist());lu=set(col('live','url_state','requested_url').to_pylist())
rem=pu-lu;print('url_state rem',len(rem),'oembed',sum('/wp-json/oembed/' in u for u in rem),'add',len(lu-pu))
pb=set(col('prev','bills','bill_id').to_pylist());lb=set(col('live','bills','bill_id').to_pylist())
print('bills rem',len(pb-lb),'add',len(lb-pb))
pm=pq.read_table(f'{d}/live/meetings.parquet',columns=['event_id','chamber','meeting_date'])
ev=pm.column('event_id').to_pylist();ch=pm.column('chamber').to_pylist();md=pm.column('meeting_date').to_pylist()
print('live null chamber',sum(c is None for c in ch),'and no date',sum(c is None and m is None for c,m in zip(ch,md)),'7 present',[i for i in(117688,335202,335760,335780,337725,338764,338786) if i in set(ev)])
t=pq.read_table(f'{A}/publish_v21/inputs/captures.parquet',columns=['member_path','complete'])
mp=pc.is_valid(t.column('member_path'));print('input member rows',pc.sum(mp).as_py(),'with complete null',pc.sum(pc.and_(mp,pc.is_null(t.column('complete')))).as_py())
# Section 3 results.
pl_rows=collections.defaultdict(set);ll_rows={}
for r in tab('prev','links',['link_key','list_row']): pl_rows[bytes(r['link_key'])].add(r['list_row'])
pairs=collections.defaultdict(set);rp=collections.defaultdict(set)
for r in tab('live','links',['link_key','list_row']):
    for p in pl_rows.get(bytes(r['link_key']),()): pairs[p].add(r['list_row']);rp[r['list_row']].add(p)
n=col('prev','list','filename').length();m=col('live','list','filename').length()
sp=collections.Counter(len(v) for v in pairs.values());mg=collections.Counter(len(v) for v in rp.values())
removed=n-len(pairs);added=m-len(rp)
print('list prev rows by live',dict(sp),'live rows by prev',dict(mg),'removed',removed,'added',added,'sum',sum((k-1)*v for k,v in sp.items())-sum((k-1)*v for k,v in mg.items())-removed+added,'delta',m-n)
def counter(s,t,f): return collections.Counter(f(r) for r in tab(s,t,COLS[t]))
COLS={'witnesses':['occasion','name'],'sources':['url','member_path'],'urls':['lookup_key']}
w=lambda r:(r['occasion'],(r['name'] or '').strip().lower() if r['name'] is not None else None)
wp,wl=counter('prev','witnesses',w),counter('live','witnesses',w)
print('witness only prev',sum(wp[k] for k in wp if k not in wl),'only live',sum(wl[k] for k in wl if k not in wp),'extra shared',sum(wl[k]-wp[k] for k in wp if k in wl and wl[k]>wp[k]),'fewer shared',sum(wp[k]-wl[k] for k in wp if k in wl and wl[k]<wp[k]))
s=lambda r:(r['url'],r['member_path'])
sp_,sl=counter('prev','sources',s),counter('live','sources',s)
print('sources url gone',sum(1 for k in sp_ if k not in sl and k[1] is None),'new',sum(1 for k in sl if k not in sp_ and k[1] is None and k[0]),'fewer',sum(sp_[k]-sl[k] for k in sp_ if k in sl and sl[k]<sp_[k]),'more',sum(sl[k]-sp_[k] for k in sp_ if k in sl and sl[k]>sp_[k]))
u=lambda r:bytes(r['lookup_key'])
up,ul=counter('prev','urls',u),counter('live','urls',u)
print('urls keys gone',sum(1 for k in up if k not in ul),'new',sum(1 for k in ul if k not in up),'net',sum(ul.values())-sum(up.values()))
rk=lambda s:{r['video_key'] for r in tab(s,'recordings',['video_key'])}
print('recordings add',len(rk('live')-rk('prev')),'rem',len(rk('prev')-rk('live')))
# Second copy of each file, from the build rather than the publisher's manifest.
for s,v in (('prev','publish_v20'),('live','publish_v21')):
    M=json.load(open(f'{d}/{s}/manifest.json'));bad=[];n=0
    for f in M['files']:
        p=f'{A}/{v}/release/{f["name"]}'
        if os.path.exists(p):
            n+=1
            if hashlib.sha256(open(p,'rb').read()).hexdigest()!=f['sha256']: bad.append(f['name'])
    print(s,'build copy compared',n,'of',len(M['files']),'mismatched',bad)
