"""Cluster the multipart ETags from etags_all.json by upload time, size and first receipt."""
import json, collections, email.utils
d=json.load(open('etags_all.json'))
rows=[]
for r in d['results']:
    h=r['r2dev']; sn=r['snapshot']
    lm=email.utils.parsedate_to_datetime(h['last_modified']) if h.get('last_modified') else None
    e=h.get('etag') or ''
    rows.append(dict(mp='-' in e, parts=int(e.strip('"').split('-')[1]) if '-' in e else None,
        stored=int(h['length']), orig=sn['bytes'], lm=lm, rk=sn['receipt_key'], t0=sn['first_retrieved_at'], ct=h.get('content_type')))
mp=[r for r in rows if r['mp']]; nmp=[r for r in rows if not r['mp']]
print('multipart',len(mp),'of',len(rows))
print('mp last-modified range',min(r['lm'] for r in mp),max(r['lm'] for r in mp))
print('mp stored range',min(r['stored'] for r in mp),max(r['stored'] for r in mp))
print('mp first receipts',collections.Counter(r['rk'] for r in mp))
print('mp part size check (stored/parts MiB)',sorted({round(r['stored']/r['parts']/2**20,1) for r in mp})[:5], 'ceil(stored/16MiB)==parts:', sum(1 for r in mp if -(-r['stored']//(16*2**20))==r['parts']))
lo,hi=min(r['lm'] for r in mp),max(r['lm'] for r in mp)
win=[r for r in nmp if r['lm'] and lo<=r['lm']<=hi]
print('non-mp uploaded inside mp window',len(win),'max stored',max((r['stored'] for r in win),default=None))
print('non-mp stored >= min mp stored', sum(1 for r in nmp if r['stored']>=min(x['stored'] for x in mp)))
big=[r for r in nmp if r['stored']>=min(x['stored'] for x in mp)]
print(' their last-modified days',collections.Counter(r['lm'].strftime('%m-%d') for r in big))
print('all by last-modified day x mp',sorted(collections.Counter((r['lm'].strftime('%m-%d'),r['mp']) for r in rows).items()))
print('content types mp',collections.Counter(r['ct'] for r in mp))
print('non-mp >=200MiB stored: first receipts', collections.Counter(r['rk'] for r in nmp if r['stored']>200*2**20).most_common(5))
print('Oct-1 uploads by first receipt', collections.Counter((r['rk'],r['mp']) for r in rows if r['lm'].strftime('%m-%d')=='10-01').most_common(6))
print('largest stored overall', max(r['stored'] for r in rows), 'its last-modified', max(rows,key=lambda r:r['stored'])['lm'])
thr=200*2**20
print('rule check: (Oct-1 upload and stored>200MiB) == multipart:', sum(1 for r in rows if ((r['lm'].strftime('%m-%d')=='10-01' and r['stored']>thr)==r['mp'])), 'of', len(rows))
