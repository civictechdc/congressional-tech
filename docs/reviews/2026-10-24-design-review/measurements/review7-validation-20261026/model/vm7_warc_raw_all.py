"""F1: every raw line holding a WARC/ARC entry (35 receipt files named by the snapshot): entry status, line status/outcome/complete/mode, fidelity, payload sibling, payload vs WARC size."""
import duckdb, gzip, json, collections
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
M='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/'
keys=[r[0] for r in duckdb.sql(f"SELECT DISTINCT receipt_key FROM read_parquet('{B}captures.parquet') WHERE media_type ILIKE '%arc+gzip%'").fetchall()]
st=collections.Counter(); small=[]
for k in keys:
    with gzip.open(M+k,'rt') as fh:
        for ln in fh:
            o=json.loads(ln); caps=o.get('captures') or []
            w=[c for c in caps if 'arc' in str(c.get('pointer'))]
            if not w: continue
            rec=o.get('record',{})
            st['lines']+=1
            st[('line', rec.get('mode'), rec.get('complete'), rec.get('outcome'), str(rec.get('http_status'))[:1]+'xx', rec.get('transport'))]+=1
            for c in w: st[('warc_entry', c.get('media_type'), c.get('fidelity'), c.get('http_status'), c.get('context_url')==rec.get('url'))]+=1
            p=[c for c in caps if 'arc' not in str(c.get('pointer'))]
            st[('payload_entries', len(p), tuple(sorted(set(str(c.get('pointer')) for c in p))))]+=1
            for c in p:
                st[('payload', (c.get('media_type') or '').split(';')[0], c.get('fidelity'), c.get('http_status'))]+=1
                ratio=c['bytes']/max(1,w[0]['bytes'])
                st[('payload/warc bytes', '<0.5' if ratio<0.5 else '0.5-0.9' if ratio<0.9 else '>=0.9')]+=1
                if ratio<0.5 and len(small)<5: small.append((c.get('media_type'), c['bytes'], w[0]['bytes'], rec.get('url')[:90]))
for k,v in sorted(st.items(), key=lambda kv:-kv[1]): print(v,k)
print('examples payload<0.5 WARC size:'); [print('  ',x) for x in small]
