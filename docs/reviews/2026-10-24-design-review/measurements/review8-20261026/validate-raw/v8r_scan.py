import gzip, json, sys, glob, re, collections as C, pickle, time
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
TK=re.compile(r'(_at|date|time|timestamp)$',re.I)
S=C.defaultdict(C.Counter)   # name -> counter
imports=[]  # per retained_import line: dict of presence
maxfr=(0,None)
t0=time.time()
files=sorted(glob.glob(R+'**/*.gz',recursive=True))
def g(o,r,k):
    if k in o: return o[k]
    if isinstance(r,dict): return r.get(k)
    return None
def walk_keys(v,prefix,out,depth=0):
    if depth>4: return
    if isinstance(v,dict):
        for k,x in v.items():
            out.add(prefix+k); walk_keys(x,prefix+k+'.',out,depth+1)
    elif isinstance(v,list):
        for x in v[:50]: walk_keys(x,prefix+'[].',out,depth+1)
for p in files:
    key=p.replace(R,'')
    pfam='/'.join(key.split('/')[:-2])
    with gzip.open(p,'rt') as f:
        for ln,l in enumerate(f):
            o=json.loads(l); r=o.get('record')
            S['lines']['all']+=1; S['lines_by_pathfam'][pfam]+=1
            S['rtype'][type(r).__name__]+=1
            caps=o.get('captures') or []; frs=o.get('file_references') or []
            if caps: S['lines']['captures_nonempty']+=1
            if frs: S['lines']['fr_nonempty']+=1
            rows=caps if caps else (frs if frs else [None])
            if len(frs)>maxfr[0]: maxfr=(len(frs),key)
            mode=g(o,r,'mode'); S['mode'][mode]+=1
            # urls (A6)
            u=g(o,r,'url'); ru=g(o,r,'requested_url')
            if not u and not ru:
                S['A6']['line_no_url_no_requested']+=1
                S['A6_fam'][pfam]+=1
                alts=[k for k in ('_url','final_url','resolved_url','master_url','segment_url','playlist_url','source_url') if g(o,r,k)]
                frc=any(isinstance(e,dict) and e.get('context_url') for e in frs)
                S['A6_alt']['+'.join(alts) or ('fr.context_url' if frc else 'none')]+=1
            # family (A6)
            lf=g(o,r,'family')
            for e in rows:
                S['rows']['all']+=1
                ef=e.get('family') if isinstance(e,dict) else None
                body = isinstance(e,dict) and bool(e.get('sha256'))
                if body: S['rows']['body']+=1
                if body and not ef and not lf:
                    S['A6']['body_row_no_family']+=1
                if ef and ef!=pfam: S['A6_fammismatch'][(pfam,ef)]+=1
                # time (A5)
                rt = (isinstance(e,dict) and e.get('retrieved_at')) or g(o,r,'retrieved_at')
                if not rt:
                    S['A5']['row_no_retrieved_at']+=1
                    ca=(isinstance(e,dict) and e.get('captured_at')) or g(o,r,'captured_at')
                    if ca: S['A5']['has_captured_at']+=1
                    tk=set()
                    if isinstance(e,dict): tk|={'entry.'+k for k in e if TK.search(k) or k=='_retrieved_at'}
                    tk|={'top.'+k for k in o if TK.search(k)}
                    if isinstance(r,dict): tk|={'rec.'+k for k in r if TK.search(k) or k=='_retrieved_at'}
                    if not tk: S['A5']['no_time_key_depth1']+=1; S['A5_notime_fam'][pfam]+=1
                    else:
                        for k in tk: S['A5_keys'][k]+=1
                        S['A5_timefam'][pfam]+=1
            # A4 / E6
            for e in frs:
                if not isinstance(e,dict): continue
                S['fr']['entries']+=1
                op=e.get('original_path')
                if op is not None:
                    S['fr']['original_path']+=1
                    if op.startswith('/'): S['fr']['original_path_abs']+=1
                    pj=str(e.get('pointer_json') or e.get('pointer') or '')
                    S['fr_op_kind'][('archive' if 'archive_members' in pj else 'non-archive', e.get('fidelity'), e.get('reference_kind'))]+=1
                if not e.get('sha256') and not e.get('body_key'): S['fr']['bodiless']+=1; S['fr_bodiless_ex'][key]+=1
            for e in caps:
                if isinstance(e,dict) and 'original_path' in e: S['cap']['original_path']+=1
            # A7
            if isinstance(r,dict):
                rl=r.get('retry_later')
                if isinstance(rl,dict) and 'delay_seconds' in rl:
                    S['A7']['retry_later.delay_seconds']+=1
                    S['A7_status'][g(o,r,'http_status') or r.get('status_code') or r.get('status')]+=1
            hdrs=g(o,r,'response_headers')
            if isinstance(hdrs,dict) and any(k.lower()=='retry-after' for k in hdrs): S['A7']['retry-after header']+=1
            hi=g(o,r,'response_header_items')
            if isinstance(hi,list) and any(isinstance(x,(list,tuple)) and x and str(x[0]).lower()=='retry-after' or isinstance(x,dict) and str(x.get('name','')).lower()=='retry-after' for x in hi): S['A7']['retry-after header_items']+=1
            if '"retry_after"' in l or 'Retry-After' in l or 'retry-after' in l: S['A7']['line mentions retry-after']+=1
            # A14 / A1 url census
            for uu in (u,ru,g(o,r,'_url')):
                if isinstance(uu,str) and 'api.congress.gov' in uu:
                    path=re.sub(r'\?.*','',uu).split('/v3/')[-1].split('/')[0]
                    fmt=re.search(r'format=(\w+)',uu)
                    S['congress_api'][(path, fmt.group(1) if fmt else None, pfam)]+=1
                    break
            for e in rows:
                if isinstance(e,dict) and e.get('sha256'):
                    cu=e.get('context_url') or u or ru or g(o,r,'_url') or ''
                    if 'api.congress.gov/v3/committee-meeting' in cu:
                        S['A1_bodies'][e['sha256'][-64:]]+=1
            # imports
            if mode=='retained_import':
                ks=set(); walk_keys(o,'',ks)
                re_=g(o,r,'recovery_evidence') or {}
                acq=re_.get('acquisition') or {} if isinstance(re_,dict) else {}
                sa=(r.get('source_associations') if isinstance(r,dict) else None) or []
                ou_any = re_.get('original_url') or acq.get('original_url') or any(isinstance(x,dict) and x.get('original_url') for x in sa) or ((acq.get('candidate') or {}).get('original_url') if isinstance(acq.get('candidate'),dict) else None)
                imports.append(dict(key=key,ln=ln,ks=ks,url=u,requested_url=ru,
                    re_ou=re_.get('original_url'), acq_ou=acq.get('original_url'), sa_ou=[x.get('original_url') for x in sa if isinstance(x,dict)],
                    rec_url=acq.get('recovered_url'), pac=acq.get('prior_access_category'), cat=acq.get('category'), kind=acq.get('kind'),
                    imported_at=re_.get('imported_at'), match_basis=re_.get('match_basis'), ou_any=bool(ou_any),
                    nbody=sum(1 for e in rows if isinstance(e,dict) and e.get('sha256')) + (1 if isinstance(r,dict) and isinstance(r.get('content'),dict) and r['content'].get('sha256') else 0)))
print('elapsed',time.time()-t0, file=sys.stderr)
pickle.dump((dict(S),imports,maxfr),open(sys.argv[1],'wb'))
