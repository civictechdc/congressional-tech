import gzip, json, os, sys, collections
root="/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/"
modes=collections.Counter(); seen=0; imp=None; fetch_keys=collections.Counter(); imp_keys=collections.Counter()
eq=collections.Counter(); house_ids=collections.Counter(); n_lines=0
for dp,_,fs in os.walk(root):
    for f in fs:
        p=os.path.join(dp,f)
        op=gzip.open if f.endswith(".gz") else open
        try:
            with op(p,"rt",encoding="utf-8",errors="replace") as fh:
                for line in fh:
                    line=line.strip()
                    if not line: continue
                    try: o=json.loads(line)
                    except Exception: continue
                    n_lines+=1
                    rec=o.get("record",o)
                    m=o.get("mode") or rec.get("mode")
                    modes[m]+=1
                    if m=="retained_import" or "recovery_evidence" in rec or "recovery_evidence" in o:
                        src=rec if "recovery_evidence" in rec else o
                        imp_keys.update(sorted(src.keys()))
                        re_=src.get("recovery_evidence",{})
                        acq=re_.get("acquisition",{}) if isinstance(re_,dict) else {}
                        imp_keys.update("recovery_evidence."+k for k in re_.keys()) if isinstance(re_,dict) else None
                        imp_keys.update("acquisition."+k for k in acq.keys())
                        ou=re_.get("original_url") if isinstance(re_,dict) else None
                        eq["url==original_url" if src.get("url")==ou else "url!=original_url"]+=1
                        eq["requested_url==original_url" if src.get("requested_url")==ou else "requested_url!=original_url"]+=1
                        eq["url is None" if src.get("url") is None else "url set"]+=1
                        eq["url==recovered_url" if src.get("url")==acq.get("recovered_url") else "url!=recovered_url"]+=1
                    else:
                        fetch_keys.update(sorted(rec.keys()))
        except Exception as e:
            print("ERR",p,e)
print("lines:",n_lines)
print("modes:",modes.most_common())
print("import-line top-level + nested field names:",sorted(imp_keys.items(),key=lambda x:-x[1])[:40])
print("import url comparisons:",eq.most_common())
print("fetch-line field names (top 40):",fetch_keys.most_common(40))
