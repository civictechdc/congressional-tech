"""One pass over the receipt mirror (read-only). Never prints values; aggregates only.

Per file returns counters; per capture writes one CSV row to a scratch part file.
"""
import collections, csv, gzip, json, os, pickle, re, sys
from multiprocessing import Pool

R = '/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
OUT = os.path.dirname(os.path.abspath(__file__)) + '/out'
LOCAL = r'(?:/Users/|/home/|/private/|/tmp/|/var/folders/|/Volumes/|/root/|/opt/|/mnt/|/runner/|/github/|/workspace/|[A-Za-z]:\\)'
FULL = re.compile('^' + LOCAL)
SUB = re.compile(r'(?<![\w.:/\-%])' + LOCAL)  # not preceded by host/url chars
NAMEKEYS = ('name', 'Name', 'key', 'header', 'k')
VALKEYS = ('value', 'Value', 'v')
DATE = re.compile(r'(20\d\d)-?(\d\d)-?(\d\d)')


def norm_key(k):
    if FULL.match(k):
        return '<abs-key>'
    if '/' in k or len(k) > 40:
        return '<dyn-key>'
    return k


def scan_file(fp):
    rel = fp[len(R) + 1:]
    parts = rel.split('/')
    fam = 'documents' if parts[0] == 'documents' else '/'.join(parts[:2])
    ddir = parts[1] if parts[0] == 'documents' else parts[2]
    C = collections.Counter()   # scalar counters
    P = collections.Counter()   # (kind, normpath) -> values
    PL = collections.defaultdict(set)  # (kind) -> set of line nos
    seg = collections.Counter()  # first segment of '/'-leading values (not printed raw)
    stored = {}
    maxts = ''
    rows = []
    receipt_has_cut = False
    rt = {'cut_lines': 0, 'rt_fail_compact_ascii': 0, 'rt_fail_compact_utf8': 0, 'rt_fail_both': 0,
          'all_lines': 0, 'all_fail_compact_ascii': 0, 'all_fail_compact_utf8': 0, 'all_fail_both': 0,
          'cut_lines_nonascii_raw': 0, 'cut_lines_uescape': 0}
    with gzip.open(fp, 'rb') as fh:
        for ln, raw in enumerate(fh):
            line = raw.rstrip(b'\n').decode('utf-8')
            obj = json.loads(line)
            hits = collections.Counter()

            def walk(o, path):
                if isinstance(o, dict):
                    lk = {k.lower(): k for k in o if isinstance(k, str)}
                    # {name: set-cookie, value: ...} item
                    for nk in NAMEKEYS:
                        v = o.get(nk)
                        if isinstance(v, str) and v.strip().lower() == 'set-cookie' and any(x in o for x in VALKEYS):
                            P[('cookie_item', path)] += 1
                            hits['cookie_item'] += 1
                            break
                    for k, v in o.items():
                        kl = k.lower()
                        np = path + '.' + norm_key(k)
                        if kl == 'set-cookie':
                            n = len(v) if isinstance(v, list) else 1
                            P[('cookie_keyed', np)] += n
                            P[('cookie_keyed_keys', np)] += 1
                            hits['cookie_keyed'] += n
                        elif kl == 'cookie':
                            P[('req_cookie_keyed', np)] += 1
                            hits['req_cookie'] += 1
                        if FULL.match(k):
                            P[('path_key', path + '.<abs-key>')] += 1
                            hits['path_key'] += 1
                        elif SUB.search(k):
                            P[('path_key_sub', path)] += 1
                            hits['path_key'] += 1
                        walk(v, np)
                elif isinstance(o, list):
                    if len(o) == 2 and isinstance(o[0], str) and o[0].strip().lower() == 'set-cookie':
                        P[('cookie_pair', path)] += 1
                        hits['cookie_pair'] += 1
                    for x in o:
                        walk(x, path + '[]')
                elif isinstance(o, str):
                    if o.startswith('/') and not o.startswith('//'):
                        seg[o.split('/')[1][:20]] += 1
                    if FULL.match(o):
                        P[('path_value', path)] += 1
                        hits['path_value'] += 1
                        # a second path inside the same value
                        if SUB.search(o, 1):
                            P[('path_value_multi', path)] += 1
                    elif SUB.search(o):
                        P[('path_sub', path)] += 1
                        hits['path_sub'] += 1
                    lo = o.lower()
                    if 'set-cookie' in lo and lo.strip() != 'set-cookie':
                        P[('cookie_substr', path)] += 1
                        hits['cookie_substr'] += 1

            walk(obj, '$')
            for k, v in hits.items():
                C['lines_with_' + k] += 1
                C['n_' + k] += v
            cookie = hits['cookie_keyed'] + hits['cookie_item'] + hits['cookie_pair'] + hits['cookie_substr']
            pth = hits['path_value'] + hits['path_key'] + hits['path_sub']
            if cookie:
                C['lines_with_any_cookie'] += 1
            if pth:
                C['lines_with_any_path'] += 1
            # round trip
            a = json.dumps(obj, separators=(',', ':'), ensure_ascii=True) == line
            u = json.dumps(obj, separators=(',', ':'), ensure_ascii=False) == line
            rt['all_lines'] += 1
            rt['all_fail_compact_ascii'] += not a
            rt['all_fail_compact_utf8'] += not u
            rt['all_fail_both'] += not (a or u)
            if cookie or pth:
                receipt_has_cut = True
                rt['cut_lines'] += 1
                rt['rt_fail_compact_ascii'] += not a
                rt['rt_fail_compact_utf8'] += not u
                rt['rt_fail_both'] += not (a or u)
                rt['cut_lines_nonascii_raw'] += any(ord(ch) > 127 for ch in line)
                rt['cut_lines_uescape'] += '\\u' in line
            # timestamps
            rec = obj.get('record') if isinstance(obj.get('record'), dict) else {}
            ts = [rec.get('retrieved_at'), rec.get('_retrieved_at')]
            caps = obj.get('captures') or []
            ts += [c.get('retrieved_at') for c in caps if isinstance(c, dict)]
            for t in ts:
                if isinstance(t, str) and t > maxts:
                    maxts = t
            outcome = rec.get('outcome')
            ds = obj.get('download_state') if isinstance(obj.get('download_state'), dict) else {}
            rdate = (rec.get('retrieved_at') or '')[:10]
            for c in caps:
                if not isinstance(c, dict):
                    continue
                sh = c.get('sha256')
                ss, sb = c.get('stored_sha256'), c.get('stored_bytes')
                prev = stored.get(sh)
                key = (ss, sb)
                if prev is None:
                    stored[sh] = {key: 1, '_bytes': c.get('bytes'), '_bk': c.get('body_key')}
                else:
                    prev[key] = prev.get(key, 0) + 1
                rows.append((sh, fam, ddir, rdate, json.dumps(c.get('pointer'), separators=(',', ':')),
                             outcome or '', ds.get('outcome') or '', (c.get('media_type') or '')[:40],
                             c.get('bytes'), ln))
    os.makedirs(OUT + '/caps', exist_ok=True)
    name = rel.replace('/', '__')
    with open(OUT + '/caps/' + name + '.csv', 'w', newline='') as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow((rel,) + r)
    fname_date = DATE.search(os.path.basename(fp))
    return dict(rel=rel, fam=fam, ddir=ddir, C=C, P=P, seg=seg, stored=stored, maxts=maxts,
                fdate='-'.join(fname_date.groups()) if fname_date else '', has_cut=receipt_has_cut,
                size=os.path.getsize(fp), rt=rt)


def main():
    files = sorted(os.path.join(d, f) for d, _, fs in os.walk(R) for f in fs if f.endswith('.jsonl.gz'))
    print('files', len(files), flush=True)
    res = []
    with Pool(8) as p:
        for i, r in enumerate(p.imap_unordered(scan_file, files, chunksize=4)):
            # stored map is merged here, then dropped from the per-file result
            res.append(r)
            if i % 200 == 0:
                print(i, flush=True)
    with open(OUT + '/scan.pkl', 'wb') as f:
        pickle.dump(res, f)


if __name__ == '__main__':
    main()
