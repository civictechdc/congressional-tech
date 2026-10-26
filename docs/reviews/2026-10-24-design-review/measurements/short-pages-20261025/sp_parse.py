# Parse cached bodies: browser-visible text, title, first heading, and simple signals.
import sys, gzip, re, pathlib, duckdb, json
import lxml.html
from lxml import etree
BODIES = pathlib.Path(sys.argv[2])
ERR_WORDS = re.compile(r'access denied|forbidden|not found|\b404\b|retry later|try again later|service unavailable|\berror\b|page cannot be|unavailable|request rejected|maintenance', re.I)
CHALLENGE = re.compile(r'just a moment|checking your browser|cf-chl|challenge-platform|captcha|incapsula|_incapsula_resource|akamai|bot manager|are you a robot|enable javascript and cookies|request unsuccessful|attention required', re.I)
ERR_URL = re.compile(r'/(404|error|errors|notfound|not-found|page-not-found|sorry)(\b|[/.?_-])', re.I)
WS = re.compile(r'\s+')

def load(p):
    raw = p.read_bytes()
    try: return gzip.decompress(raw)
    except Exception: return raw

def parse(b):
    try:
        doc = lxml.html.document_fromstring(b)
    except Exception as e:
        return dict(parse_error=str(e)[:80])
    title = WS.sub(' ', ' '.join(doc.xpath('//title//text()'))).strip()
    refresh = bool(doc.xpath('//meta[translate(@http-equiv,"REFRESH","refresh")="refresh"]'))
    n_script = len(doc.xpath('//script'))
    script_bytes = sum(len((s.text or '').encode()) for s in doc.xpath('//script'))
    hrefs = [h.strip() for h in doc.xpath('//a/@href|//iframe/@src|//embed/@src|//object/@data')]
    pdf_links = sum(1 for h in hrefs if re.search(r'\.pdf(\b|$|\?|#)', h, re.I))
    raw_head = b[:20000].decode('utf-8', 'replace')
    challenge_marker = bool(CHALLENGE.search(raw_head))
    for el in doc.xpath('//script|//style|//noscript|//template|//head'):
        el.drop_tree()
    # text_content() is XPath string(): comments are already excluded
    text = WS.sub(' ', doc.text_content()).strip()
    h = doc.xpath('//h1|//h2|//h3')
    heading = WS.sub(' ', h[0].text_content()).strip() if h else ''
    return dict(title=title[:300], heading=heading[:300], text=text[:4000], text_bytes=len(text.encode('utf-8')),
                refresh=refresh, n_script=n_script, script_bytes=script_bytes, n_links=len(hrefs), pdf_links=pdf_links,
                challenge_marker=challenge_marker,
                err_word=bool(ERR_WORDS.search(title) or ERR_WORDS.search(heading)),
                raw_bytes=len(b))

rows = duckdb.sql(f"select sha256, body_key, coalesce(member_path, context_url) loc, context_url from '{sys.argv[1]}'").fetchall()
out = []
for sha, key, loc, url in rows:
    p = BODIES / key.rsplit('/', 1)[1]
    if not p.exists(): continue
    try: d = parse(load(p))
    except Exception as e: d = dict(parse_error=str(e)[:80])
    d.update(sha256=sha, err_url=bool(ERR_URL.search(url or '')))
    out.append(d)
pathlib.Path(sys.argv[3]).write_text('\n'.join(json.dumps(o) for o in out))
print(len(out), 'parsed')
