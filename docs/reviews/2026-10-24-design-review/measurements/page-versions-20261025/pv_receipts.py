import gzip, json, glob, os
import pyarrow as pa, pyarrow.parquet as pq
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
KEEP=('html','pdf','zip','word','msword','octet')
cols={k:[] for k in ['rfile','line','mode','outcome','complete','rec_status','cap_status','context_url','sha256','body_key','media_type','fidelity','pointer','retrieved_at','rec_retrieved_at','family','timestamp_basis','requested_url','final_url','transport','attempt','att_status','att_complete']}
files=sorted(glob.glob(R+'**/*.jsonl.gz', recursive=True))
for f in files:
    rf=f[len(R):]
    with gzip.open(f,'rt') as fh:
        for i,l in enumerate(fh):
            if '"captures": []' in l and '"file_references": []' in l: continue
            d=json.loads(l)
            caps=[dict(c, _kind='capture') for c in (d.get('captures') or [])]+[dict(c, _kind='fileref') for c in (d.get('file_references') or [])]
            if not caps: continue
            rec=d.get('record') if isinstance(d.get('record'),dict) else {}
            re_=rec.get('recovery_evidence') or {}
            for c in caps:
                mt=(c.get('media_type') or '').lower()
                if not any(k in mt for k in KEEP): continue
                cols['rfile'].append(rf); cols['line'].append(i)
                cols['mode'].append(rec.get('mode') if c['_kind']=='capture' else 'fileref:'+str(c.get('reference_kind'))); cols['outcome'].append(rec.get('outcome') if c['_kind']=='capture' else c.get('resolution'))
                cols['complete'].append(rec.get('complete')); cols['rec_status'].append(rec.get('http_status'))
                cols['cap_status'].append(c.get('http_status')); cols['context_url'].append(c.get('context_url'))
                cols['sha256'].append(c.get('sha256')); cols['body_key'].append(c.get('body_key'))
                cols['media_type'].append(mt); cols['fidelity'].append(c.get('fidelity'))
                cols['pointer'].append(json.dumps(c.get('pointer')) if c['_kind']=='capture' else c.get('pointer_json')); cols['retrieved_at'].append(c.get('retrieved_at'))
                cols['rec_retrieved_at'].append(rec.get('retrieved_at')); cols['family'].append(c.get('family'))
                ptr=c.get('pointer') if c['_kind']=='capture' else None
                att=None; a={}
                if isinstance(ptr,list) and len(ptr)>1 and ptr[0]=='prior_attempts' and isinstance(ptr[1],int):
                    att=ptr[1]; pa_=rec.get('prior_attempts') or []
                    a=pa_[att] if att < len(pa_) and isinstance(pa_[att],dict) else {}
                cols['attempt'].append(att if att is not None else -1)
                src=a if att is not None else rec
                cols['requested_url'].append(rec.get('requested_url')); cols['final_url'].append(src.get('url'))
                cols['transport'].append(src.get('transport')); cols['att_status'].append(src.get('http_status') if isinstance(src.get('http_status'),int) else None)
                cols['att_complete'].append(src.get('complete') if isinstance(src.get('complete'),bool) else None)
                cols['timestamp_basis'].append(re_.get('timestamp_basis') if isinstance(re_,dict) else None)
for k in ('rec_status','cap_status'):
    cols[k]=[int(x) if isinstance(x,(int,float)) or (isinstance(x,str) and x.isdigit()) else None for x in cols[k]]
cols['complete']=[x if isinstance(x,bool) else None for x in cols['complete']]
pq.write_table(pa.table(cols), O+'receipt_caps.parquet')
print(len(files), len(cols['rfile']))
