import gzip, json, os, collections
root="/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/"
cat=collections.Counter(); ou=collections.Counter(); kinds=collections.Counter(); n=0
for dp,_,fs in os.walk(root):
    for f in fs:
        p=os.path.join(dp,f); op=gzip.open if f.endswith(".gz") else open
        with op(p,"rt",encoding="utf-8",errors="replace") as fh:
            for line in fh:
                try: o=json.loads(line)
                except Exception: continue
                if not isinstance(o,dict): continue
                rec=o.get("record",o)
                src=rec if "recovery_evidence" in rec else (o if "recovery_evidence" in o else None)
                if src is None: continue
                n+=1
                re_=src.get("recovery_evidence") or {}
                acq=re_.get("acquisition") or {}
                cat[acq.get("prior_access_category") or "<none>"]+=1
                kinds[acq.get("kind") or "<none>"]+=1
                has=("re.original_url" if re_.get("original_url") else "")+("|acq.original_url" if acq.get("original_url") else "")
                ou[has or "<neither>"]+=1
print("import lines:",n)
print("prior_access_category:",cat.most_common())
print("acquisition.kind:",kinds.most_common())
print("original_url presence:",ou.most_common())
