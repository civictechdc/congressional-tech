"""Scan the local receipt mirror: credential parameters in recorded URLs (counts and hosts only, never values),
declared-length headers on successful HTML responses, cookies and local paths. Read-only."""
import gzip, json, os, sys, collections, re
from urllib.parse import urlsplit, parse_qsl
ROOT = sys.argv[1]
CRED = {'api_key', 'apikey', 'key', 'token', 'access_token', 'authorization', 'auth', 'password', 'secret'}
PATH_RE = re.compile(r'^(/Users/|/home/|/private/|/tmp/|/var/folders/|[A-Za-z]:\\)')
cred = collections.Counter(); cred_hosts = collections.Counter(); cred_fields = collections.Counter()
html = collections.Counter(); cookies = 0; cookie_lines = 0; path_fields = collections.Counter(); lines = 0; files = 0
def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, path + (k,))
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, path + ('[]',))
    else:
        yield path, o
def headers_of(rec):
    h = {}
    for key in ('response_headers', 'headers'):
        v = rec.get(key)
        if isinstance(v, dict):
            for k, val in v.items(): h[str(k).lower()] = val
    items = rec.get('response_header_items')
    if isinstance(items, list):
        for it in items:
            if isinstance(it, (list, tuple)) and len(it) == 2: h[str(it[0]).lower()] = it[1]
            elif isinstance(it, dict) and 'name' in it: h[str(it['name']).lower()] = it.get('value')
    return h
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if not f.endswith('.jsonl.gz'): continue
        files += 1
        with gzip.open(os.path.join(dp, f), 'rt', errors='replace') as fh:
            for line in fh:
                try: rec = json.loads(line)
                except Exception: continue
                lines += 1
                had_cookie = False
                for path, v in walk(rec, ()):
                    if not isinstance(v, str): continue
                    last = str(path[-1]).lower() if path else ''
                    if v.startswith(('http://', 'https://')) and '?' in v:
                        try:
                            parts = urlsplit(v)
                            names = {n.lower() for n, _ in parse_qsl(parts.query, keep_blank_values=True)}
                        except Exception:
                            continue
                        hit = names & CRED
                        for n in hit:
                            cred[n] += 1; cred_hosts[(n, parts.hostname)] += 1
                            cred_fields['.'.join(p for p in path if p != '[]')[:80]] += 1
                    if last in ('set-cookie', 'cookie') or (len(path) >= 2 and str(path[-2]).lower() in ('set-cookie', 'cookie')):
                        cookies += 1; had_cookie = True
                    if PATH_RE.match(v):
                        path_fields['.'.join(p for p in path if p != '[]')[:80]] += 1
                if had_cookie: cookie_lines += 1
                st = rec.get('http_status'); h = headers_of(rec)
                ct = str(h.get('content-type', '') or rec.get('media_type', '') or '')
                if isinstance(st, int) and 200 <= st < 300 and 'html' in ct.lower():
                    html['html_2xx'] += 1
                    te = str(h.get('transfer-encoding', '')).lower()
                    if 'content-length' in h: html['has_content_length'] += 1
                    elif 'chunked' in te: html['chunked_no_length'] += 1
                    elif not h: html['no_headers_recorded'] += 1
                    else: html['headers_without_length'] += 1
                    if h.get('content-encoding'): html['content_encoded'] += 1
print(json.dumps({'files': files, 'lines': lines,
  'credential_param_occurrences': cred, 'credential_param_by_host': {f'{n} @ {h}': c for (n, h), c in cred_hosts.most_common(25)},
  'credential_param_fields': dict(cred_fields.most_common(15)),
  'cookie_values': cookies, 'lines_with_cookies': cookie_lines,
  'local_path_fields': dict(path_fields.most_common(15)), 'html_2xx_length': html}, indent=1, default=str))
