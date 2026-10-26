# Compare candidate error rules on the labeled sample (weighted to the population).
import duckdb, json, re, gzip, collections
c = duckdb.connect()
c.sql("create table x as select * from read_json_auto('parsed.jsonl', format='newline_delimited') join 'sample.parquet' using(sha256)")
L = json.load(open('labels_rule.json'))
rows = c.sql("select sha256, body_key, context_url, coalesce(member_path, context_url) loc, title, heading, text, text_bytes, n_script, pdf_links, n_links, refresh, weight, hgroup from x").fetchall()
ERRW = re.compile(r'access denied|forbidden|not found|retry later|service unavailable|\berror\b', re.I)
ERRURL = re.compile(r'/(404|error|errors|notfound|not-found|page-not-found)(\b|[/.?_-])|[?&]aspxerrorpath=', re.I)
CHAL = re.compile(r'cf-chl|challenge-platform|_Incapsula_Resource|<title>\s*(Just a moment|Client Challenge|Attention Required|Access Denied)', re.I)
NOTDOC = {'soft_error', 'bot_challenge', 'empty_or_js_shell', 'download_interstitial', 'landing_or_unrelated', 'document_wrapper_page'}
STRICT = {'real_doc_errata', 'real_doc_short_release'}
BROAD = STRICT | {'real_doc_gpo_cover_only'}
LISTING = {'hearing_event_page', 'listing_page', 'document_index_page'}
def raw(k): return gzip.decompress(open('bodies/' + k.rsplit('/', 1)[1], 'rb').read())[:30000].decode('utf-8', 'replace')
sig = {}
for sha, key, url, loc, title, heading, text, tb, nscr, npdf, nl, refresh, w, hg in rows:
    r = raw(key)
    kind = L[sha]
    if kind == 'long_page' and 'whdfs28' in url: kind = 'soft_error'   # redirect-to-index read by hand
    sig[sha] = dict(kind=kind, w=w, short=tb < 2048, errw=bool(ERRW.search(title or '') or ERRW.search(heading or '')),
        errurl=bool(ERRURL.search(url or '')), chal=bool(CHAL.search(r)),
        inter=('download will begin shortly' in text) or (heading or '').strip() == 'Download File',
        refresh=bool(refresh), lonepdf=(npdf == 1 and tb < 2048), tiny=tb < 128, empty=tb == 0)
rules = {
  'a  short alone': lambda s: s['short'],
  'b  short AND (error word | error URL | challenge)': lambda s: s['short'] and (s['errw'] or s['errurl'] or s['chal']),
  'c1 b OR interstitial OR challenge OR text<128B': lambda s: (s['short'] and (s['errw'] or s['errurl'])) or s['chal'] or s['inter'] or s['tiny'],
  'c2 (error word | error URL | challenge | interstitial | text<128B), no length test': lambda s: s['errw'] or s['errurl'] or s['chal'] or s['inter'] or s['tiny'],
  'c3 short AND meta refresh': lambda s: s['short'] and s['refresh'],
  'c4 short AND one PDF link': lambda s: s['lonepdf'],
}
tot = collections.Counter()
for s in sig.values():
    k = s['kind']; tot['notdoc' if k in NOTDOC else 'strict' if k in STRICT else 'broad_extra' if k in BROAD else 'listing' if k in LISTING else 'long']+= s['w']
print('population by truth class (weighted):', {k: round(v) for k, v in tot.items()})
res = {}
for name, f in rules.items():
    m = collections.Counter(); n = collections.Counter()
    for s in sig.values():
        hit = f(s); k = s['kind']
        if k in NOTDOC and not hit: m['notdoc_kept'] += s['w']; n['notdoc_kept'] += 1
        if k in NOTDOC and hit: m['notdoc_caught'] += s['w']
        if k in STRICT and hit: m['strict_dropped'] += s['w']; n['strict_dropped'] += 1
        if k in BROAD and hit: m['broad_dropped'] += s['w']; n['broad_dropped'] += 1
        if k in LISTING and hit: m['listing_flagged'] += s['w']; n['listing_flagged'] += 1
        if k == 'long_page' and hit: m['long_flagged'] += s['w']; n['long_flagged'] += 1
    res[name] = {k: round(v) for k, v in m.items()} | {'n_' + k: v for k, v in n.items()}
    print(name, res[name])
json.dump(res, open('rules.json', 'w'), indent=1)
# which not-docs does rule b miss, by kind
mk = collections.Counter()
for s in sig.values():
    if s['kind'] in NOTDOC and not rules['b  short AND (error word | error URL | challenge)'](s): mk[s['kind']] += s['w']
print('rule b misses:', {k: round(v) for k, v in mk.items()})
mk = collections.Counter()
for sha, s in sig.items():
    if s['kind'] in NOTDOC and not rules['c1 b OR interstitial OR challenge OR text<128B'](s): mk[s['kind']] += s['w']; print('  c1 miss', sha[:12], s['kind'])
print('rule c1 misses:', {k: round(v) for k, v in mk.items()})
json.dump(sig, open('signals.json', 'w'))
