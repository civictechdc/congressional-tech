# For every capture row of the sampled bodies, read its raw receipt line from the local mirror
# (each receipt file decompressed once) and record receipt-level status, completeness, outcome, type.
import gzip, json, collections, duckdb, sys
D = '/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
R = '/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
caps = duckdb.sql(f"""select c.sha256, c.receipt_key, c.receipt_line, c.pointer_json, c.http_status, c.resolution, c.fidelity, c.context_url
  from '{D}captures.parquet' c where c.sha256 in (select sha256 from '{sys.argv[1]}')""").fetchall()
by_file = collections.defaultdict(list)
for row in caps: by_file[row[1]].append(row)
out = []; offsets = collections.Counter()
def local(rec, ptr):
    """Walk the capture pointer; the deepest object on the path that states a status/completeness wins."""
    p = json.loads(ptr or '[]')
    node = rec; st = rec.get('http_status', rec.get('status_code')); comp = rec.get('complete', rec.get('body_complete')); ct = None; outc = rec.get('outcome')
    for k in p:
        try: node = node[k]
        except Exception: break
        if isinstance(node, dict):
            st = node.get('http_status', node.get('status_code', node.get('statusCode', st)))
            comp = node.get('complete', node.get('body_complete', comp)); outc = node.get('outcome', outc)
            h = node.get('response_headers') or node.get('headers')
            if isinstance(h, dict): ct = h.get('content-type', ct)
            ct = node.get('media_type', ct) if k != p[-1] else ct
    if p and p[0] == 'provider_response':
        st = rec.get('provider_http_status', st)
    return st, comp, outc, ct
for key, rows in by_file.items():
    wanted = {}
    for r in rows:
        for off in (0, -1, 1): wanted.setdefault(r[2] + off, [])
    lines = {}
    with gzip.open(R + key.removeprefix('receipts/'), 'rt') as fh:
        for i, line in enumerate(fh):
            if i in wanted: lines[i] = line
    for sha, _, ln, ptr, st, res, fid, url in rows:
        hit = None
        for off in (0, -1, 1):
            t = lines.get(ln + off)
            if t and sha in t: hit = (off, json.loads(t)); break
        if not hit:
            offsets['miss'] += 1; out.append(dict(sha256=sha, matched=False, snap_status=st, resolution=res)); continue
        offsets[hit[0]] += 1
        d = hit[1]; rec = d.get('record', {})
        hdrs = rec.get('response_headers') or {}
        out.append(dict(sha256=sha, matched=True, offset=hit[0], pointer=ptr, snap_status=st, resolution=res, fidelity=fid,
            rec_status=rec.get('http_status', rec.get('status_code')), ptr_status=local(rec, ptr)[0], ptr_complete=local(rec, ptr)[1], ptr_outcome=local(rec, ptr)[2], ptr_ctype=local(rec, ptr)[3],
            complete=rec.get('complete'), outcome=rec.get('outcome') or (d.get('download_state') or {}).get('outcome'),
            ctype=hdrs.get('content-type') or rec.get('content_type'), transport=rec.get('transport'),
            final_url=(rec.get('source_metadata') or {}).get('final_url') or rec.get('resolved_url'),
            requested_url=rec.get('requested_url'), rec_keys=sorted(rec.keys())))
open(sys.argv[2], 'w').write('\n'.join(json.dumps(o) for o in out))
print(len(caps), 'capture rows;', len(by_file), 'receipt files; line offsets', dict(offsets))
