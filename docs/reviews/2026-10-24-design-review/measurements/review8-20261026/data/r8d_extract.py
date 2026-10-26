import gzip, json, os, hashlib
from multiprocessing import Pool
import pyarrow as pa, pyarrow.parquet as pq
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review8/data/rows'
os.makedirs(O,exist_ok=True)
files=sorted(os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz'))
def s(v):
    if v is None: return None
    return v if isinstance(v,str) else json.dumps(v)
def i(v):
    try: return int(v) if v is not None and not isinstance(v,bool) else None
    except: return None
def hget(h,name):
    if isinstance(h,dict):
        for k,v in h.items():
            if k.lower()==name: return s(v)
    if isinstance(h,list):
        for e in h:
            if isinstance(e,dict) and str(e.get('name','')).lower()==name: return s(e.get('value'))
    return None
def work(args):
    idx,p=args
    rows=[]
    key=p[len(R)+1:]
    with gzip.open(p,'rt') as fh:
        for ln,line in enumerate(fh):
            o=json.loads(line)
            rec=o.get('record'); islist=isinstance(rec,list)
            r=rec[0] if islist and rec and isinstance(rec[0],dict) else (rec if isinstance(rec,dict) else {})
            hdr=r.get('response_headers') or r.get('response_header_items') or r.get('headers')
            re_=r.get('recovery_evidence') or {}
            acq=re_.get('acquisition') or {} if isinstance(re_,dict) else {}
            line_d=dict(rkey=key, ln=ln, run=s(o.get('source_file')), rec_list=islist,
                rkeys=','.join(sorted(r.keys())),
                mode=s(r.get('mode')), outcome=s(r.get('outcome')), http_status=i(r.get('http_status')),
                status_code=i(r.get('status_code')), url=s(r.get('url')), requested_url=s(r.get('requested_url')),
                retrieved_at=s(r.get('retrieved_at')), captured_at=s(r.get('captured_at')), rfamily=s(r.get('family')),
                complete_rec=r.get('complete') if isinstance(r.get('complete'),bool) else None,
                pub_req=r.get('publisher_requested') if isinstance(r.get('publisher_requested'),bool) else None,
                has_re=bool(re_), pac=s(acq.get('prior_access_category')) if isinstance(acq,dict) else None,
                body_path=s((acq.get('body_path') if isinstance(acq,dict) else None) or (acq.get('request',{}) or {}).get('body_path') if isinstance(acq,dict) else None),
                re_orig=s(re_.get('original_url')) if isinstance(re_,dict) else None,
                hdr_kind=('response_headers' if r.get('response_headers') else 'response_header_items' if r.get('response_header_items') else 'headers' if r.get('headers') else None),
                h_cl=hget(hdr,'content-length'), h_ce=hget(hdr,'content-encoding'), h_ct=hget(hdr,'content-type'), h_cd=hget(hdr,'content-disposition'),
                n_prior=len(r.get('prior_attempts') or []) if isinstance(r.get('prior_attempts'),list) else None,
                n_am=len(r.get('archive_members') or []) if isinstance(r.get('archive_members'),list) else None,
                retry_later=s(r.get('retry_later')))
            caps=o.get('captures') or []; frefs=o.get('file_references') or []
            src='captures' if caps else ('file_references' if frefs else None)
            ents=caps if caps else frefs
            line_d['n_caps']=len(caps); line_d['n_frefs']=len(frefs)
            if not ents:
                d=dict(line_d); d.update(ci=0, src=None); rows.append(d); continue
            for ci,e in enumerate(ents):
                d=dict(line_d)
                d.update(ci=ci, src=src, sha=s(e.get('sha256')), bytes=i(e.get('bytes')), ctx=s(e.get('context_url')),
                    opath=s(e.get('original_path')), pointer=s(e.get('pointer') or e.get('pointer_json')), e_mt=s(e.get('media_type')),
                    fidelity=s(e.get('fidelity')), e_status=i(e.get('http_status') if e.get('http_status') is not None else e.get('status_code')),
                    e_ret=s(e.get('retrieved_at')), e_cap=s(e.get('captured_at')), e_family=s(e.get('family')),
                    body_key=s(e.get('body_key')), stored_bytes=i(e.get('stored_bytes')), e_keys=','.join(sorted(e.keys())))
                rows.append(d)
    cols=['rkey','ln','ci','src','run','rec_list','rkeys','mode','outcome','http_status','status_code','url','requested_url','retrieved_at','captured_at','rfamily','complete_rec','pub_req','has_re','pac','body_path','re_orig','hdr_kind','h_cl','h_ce','h_ct','h_cd','n_prior','n_am','retry_later','n_caps','n_frefs','sha','bytes','ctx','opath','pointer','e_mt','fidelity','e_status','e_ret','e_cap','e_family','body_key','stored_bytes','e_keys']
    types={'ln':pa.int64(),'ci':pa.int64(),'http_status':pa.int64(),'status_code':pa.int64(),'n_prior':pa.int64(),'n_am':pa.int64(),'n_caps':pa.int64(),'n_frefs':pa.int64(),'bytes':pa.int64(),'e_status':pa.int64(),'stored_bytes':pa.int64(),'rec_list':pa.bool_(),'complete_rec':pa.bool_(),'pub_req':pa.bool_(),'has_re':pa.bool_()}
    t=pa.table({c:pa.array([r.get(c) for r in rows],type=types.get(c,pa.string())) for c in cols})
    pq.write_table(t,f'{O}/part-{idx:05d}.parquet',compression='zstd')
    return len(rows)
if __name__=='__main__':
    with Pool(8) as pool:
        n=sum(pool.imap_unordered(work,list(enumerate(files)),chunksize=2))
    print('rows',n)
