"""Successful HTML responses: is a declared length recorded? Uses record.response_headers / source_metadata.response_headers."""
import gzip, json, os, sys, collections
ROOT = sys.argv[1]
c = collections.Counter(); by_fam = collections.Counter(); proto = collections.Counter()
def hdrs(r):
    out = {}
    sm = r.get('source_metadata') if isinstance(r.get('source_metadata'), dict) else {}
    pm = r.get('provider_metadata') if isinstance(r.get('provider_metadata'), dict) else {}
    for src in (r.get('response_headers'), sm.get('response_headers'), pm.get('response_headers')):
        if isinstance(src, dict):
            for k, v in src.items(): out.setdefault(str(k).lower(), v)
        elif isinstance(src, list):
            for it in src:
                if isinstance(it, (list, tuple)) and len(it) == 2: out.setdefault(str(it[0]).lower(), it[1])
    return out
for dp, dn, fn in os.walk(ROOT):
    fam = os.path.relpath(dp, ROOT).split(os.sep)[0]
    for f in fn:
        if not f.endswith('.jsonl.gz'): continue
        with gzip.open(os.path.join(dp, f), 'rt', errors='replace') as fh:
            for line in fh:
                try: rec = json.loads(line)
                except Exception: continue
                r = rec.get('record') if isinstance(rec.get('record'), dict) else {}
                st = r.get('http_status')
                if not isinstance(st, int):
                    st = next((cp.get('http_status') for cp in rec.get('captures') or [] if isinstance(cp, dict) and isinstance(cp.get('http_status'), int)), None)
                h = hdrs(r)
                ct = str(h.get('content-type', '')).lower()
                if not (isinstance(st, int) and 200 <= st < 300 and 'html' in ct): continue
                c['html_2xx'] += 1; by_fam[fam] += 1
                te = str(h.get('transfer-encoding', '')).lower()
                if 'content-length' in h: c['content_length'] += 1
                elif 'chunked' in te: c['chunked'] += 1
                else: c['no_length_no_chunked_header'] += 1
                if h.get('content-encoding'): c['content_encoded'] += 1
                if r.get('transport'): proto[str(r.get('transport'))] += 1
print(json.dumps({'html_2xx_lines': dict(c), 'by_family': dict(by_fam), 'transport': dict(proto.most_common(8))}, indent=1))
