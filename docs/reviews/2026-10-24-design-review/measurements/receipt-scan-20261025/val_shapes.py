"""Keys-only structure of receipt lines, YouTube key value shape (length/distinct count only), local-path prefixes by field."""
import gzip, json, os, sys, collections, re, hashlib
from urllib.parse import urlsplit, parse_qsl
ROOT = sys.argv[1]
PATH_RE = re.compile(r'^(/Users/|/home/|/private/|/tmp/|/var/folders/|[A-Za-z]:\\)')
shapes = collections.Counter(); keyvals = collections.Counter(); keylens = collections.Counter()
prefix = collections.Counter(); hdr_paths = collections.Counter(); status_paths = collections.Counter()
def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items(): yield from walk(v, path + (k,))
    elif isinstance(o, list):
        for v in o: yield from walk(v, path + ('[]',))
    else: yield path, o
n = 0
for dp, dn, fn in os.walk(ROOT):
    for f in sorted(fn):
        if not f.endswith('.jsonl.gz'): continue
        fam = os.path.relpath(dp, ROOT).split(os.sep)[0]
        with gzip.open(os.path.join(dp, f), 'rt', errors='replace') as fh:
            for i, line in enumerate(fh):
                if i >= 200: break   # 200 lines per file is enough for shape statistics
                try: rec = json.loads(line)
                except Exception: continue
                n += 1
                shapes[(fam, tuple(sorted(rec.keys()))[:12])] += 1
                for path, v in walk(rec, ()):
                    p = '.'.join(x for x in path if x != '[]')
                    pl = p.lower()
                    if ('header' in pl) and (pl.endswith('content-length') or pl.endswith('transfer-encoding') or pl.endswith('content-type')):
                        hdr_paths[re.sub(r'\.[^.]*$', '.<header>', p)[:70]] += 1
                    if pl.endswith('http_status') or pl.endswith('status_code') or pl.endswith('.status'):
                        status_paths[p[:70]] += 1
                    if isinstance(v, str):
                        if 'youtube.com' in v and 'key=' in v:
                            for k2, val in parse_qsl(urlsplit(v).query, keep_blank_values=True):
                                if k2.lower() == 'key':
                                    keylens[len(val)] += 1
                                    keyvals[hashlib.sha256(val.encode()).hexdigest()[:10]] += 1
                        m = PATH_RE.match(v)
                        if m: prefix[(p[:60], m.group(1))] += 1
print('lines sampled', n)
print('distinct youtube key values (hashed)', len(keyvals), 'lengths', dict(keylens))
print('top shapes:'); [print(' ', c, s) for s, c in shapes.most_common(12)]
print('header field paths:'); [print(' ', c, s) for s, c in hdr_paths.most_common(12)]
print('status field paths:'); [print(' ', c, s) for s, c in status_paths.most_common(8)]
print('local-path fields by prefix:'); [print(' ', c, s) for s, c in prefix.most_common(40)]
