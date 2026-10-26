"""F1: raw shape of provider-response lines that reference WARC bodies. Prints structure, never header values beyond content-type."""
import gzip, json, os, collections, sys
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/external/provider-responses'
SENS={'set-cookie','cookie','authorization'}
def red(o):
    if isinstance(o,dict): return {k:('<redacted>' if k.lower() in SENS else red(v)) for k,v in o.items()}
    if isinstance(o,list): return [red(x) for x in o]
    if isinstance(o,str) and len(o)>160: return o[:160]+'...'
    return o
stats=collections.Counter(); shown=0
for r,d,fs in sorted(os.walk(R)):
    for f in sorted(fs):
        p=os.path.join(r,f)
        with gzip.open(p,'rt') as fh:
            for ln in fh:
                o=json.loads(ln)
                caps=o.get('captures') or []
                mts=[c.get('media_type') for c in caps]
                has_warc=any(m and 'arc' in m for m in mts)
                stats[('lines',)]+=1
                if not has_warc: stats[('nowarc_line', tuple(sorted(set(map(str,mts)))))]+=1; continue
                stats[('warc_line_ncaps',len(caps))]+=1
                stats[('warc_line_media', tuple(sorted(set(map(str,mts)))))]+=1
                rec=o.get('record',{})
                stats[('rec_http_status_cls', str(rec.get('http_status'))[:1])]+=1
                stats[('rec_outcome', rec.get('outcome'))]+=1
                stats[('rec_mode', rec.get('mode'))]+=1
                stats[('rec_complete', rec.get('complete'))]+=1
                stats[('rec_transport', rec.get('transport'))]+=1
                for c in caps:
                    stats[('cap_keys', tuple(sorted(c.keys())))]+=1
                    stats[('cap_ptr_media', str(c.get('pointer'))[:60], c.get('media_type'), c.get('fidelity'), c.get('http_status'))]+=1
                if shown<2:
                    shown+=1
                    print('=== example line', p.split('receipts/')[1])
                    print(json.dumps({k:v for k,v in red(o).items() if k!='record'},indent=1)[:3000])
                    print('record keys', sorted(rec.keys()))
                    print(json.dumps({k:red(rec.get(k)) for k in ['http_status','outcome','mode','complete','url','requested_url','transport','provider_http_status','redirects','prior_attempts']},indent=1)[:2500])
                    rh=rec.get('response_headers') or {}
                    print('response_headers keys', sorted(rh.keys()) if isinstance(rh,dict) else type(rh), 'content-type', (rh or {}).get('content-type') if isinstance(rh,dict) else None)
                    pr=rec.get('provider_response')
                    print('provider_response type', type(pr).__name__, (sorted(pr.keys()) if isinstance(pr,dict) else str(pr)[:200]))
for k,v in sorted(stats.items(), key=lambda kv:(str(kv[0][0]),-kv[1])): print(v,k)
