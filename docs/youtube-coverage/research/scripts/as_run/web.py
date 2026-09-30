"""
Shared, cached, rate-limited web helper for the missing-video investigation agents.

    import sys; sys.path.insert(0, "<scratch>/swarm"); import web
    web.get(url, params=None)                    -> page text ("" on failure); cached on disk, throttled per host
    web.wayback_snapshots("waysandmeans.house.gov/event/*", 2016, 2018, limit=2000)
                                                 -> [(timestamp, original_url, status)] from the CDX API
    web.wayback_page(url, timestamp=None)        -> archived page text (closest snapshot at/after timestamp)
    web.wayback_closest(url, timestamp)          -> archived URL or "" (availability API)
    web.video_links(html)                        -> YouTube IDs, .mp4/.wmv/.m3u8 links, ustream/vimeo/c-span embeds found in a page
    web.yt_status(video_id)                      -> {"status": "ok"|"gone", "title", "author"} via YouTube oEmbed
    web.transcript_head(html_url, chars=4000)    -> start of a GPO transcript (title page, date, "CLOSED" notices)

Every network call is cached (shared by all agents) and throttled per host, so never bypass this module.
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
from congress_api.transport import zyte

CACHE = os.path.join(HERE, "cache"); os.makedirs(CACHE, exist_ok=True)
MIN_INTERVAL = {"web.archive.org": 1.0, "archive.org": 1.0, "www.c-span.org": 1.0, "www.youtube.com": 0.5}
_sess = requests.Session()
HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US"}


def _throttle(host):
    lock = os.path.join(HERE, f".ratelimit.{host}")
    with open(lock, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try: last = float(f.read() or 0)
        except ValueError: last = 0
        wait = last + MIN_INTERVAL.get(host, 1.0) - time.time()
        if wait > 0: time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time()))
        fcntl.flock(f, fcntl.LOCK_UN)


def get(url, params=None, timeout=60):
    key = hashlib.sha1((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    path = os.path.join(CACHE, key)
    if os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(3):
        _throttle(host)
        try:
            if host in ZYTE_HOSTS:
                status, text = _zyte(url, params)
            elif host in CURL_HOSTS:
                status, text = _curl(url, params, timeout)
            else:
                r = _sess.get(url, params=params, headers=HDR, timeout=timeout)
                status, text = r.status_code, r.text
        except (requests.RequestException, subprocess.SubprocessError):
            time.sleep(5 * (attempt + 1)); continue
        if status in (202, 429) or status >= 500:  # 202 is c-span.org's bot challenge
            time.sleep(20 * (attempt + 1)); continue
        if status == 200:
            open(path, "w", encoding="utf-8").write(text)
            return text
        open(path, "w", encoding="utf-8").write("")  # 404s etc. are cached as empty
        return ""
    return ""


CURL_HOSTS = set()
## c-span.org answers python-requests with a 202 bot challenge, and curl too after the first hit.
##  Zyte's API (httpResponseBody = the site's own bytes) gets through (congress_api.zyte).
ZYTE_HOSTS = {"www.c-span.org"}


def _zyte(url, params):
    """Fetch through Zyte's API. Returns (status of the target site, body text)."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    status, body = zyte.get(url, _sess)
    return (429 if not body and status in (429, 503, 520) else status), body.decode("utf-8", "replace")


def _curl(url, params, timeout):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    out = subprocess.run(["curl", "-s", "-L", "-m", str(timeout), "-A", HDR["User-Agent"], "-H", "Accept-Language: en-US",
                          "-w", "\n__STATUS__%{http_code}", url], capture_output=True, text=True, errors="replace")
    body, _, status = out.stdout.rpartition("\n__STATUS__")
    return int(status or 0), body


def wayback_snapshots(url_pattern, from_year, to_year, limit=2000, status="200"):
    """CDX API listing. url_pattern may end in '*' (prefix match). Returns [(timestamp, original, statuscode)]."""
    text = get("https://web.archive.org/cdx/search/cdx", {"url": url_pattern, "from": str(from_year), "to": str(to_year),
                "limit": str(limit), "fl": "timestamp,original,statuscode", "filter": f"statuscode:{status}", "collapse": "urlkey"})
    return [tuple(line.split(" ", 2)) for line in text.splitlines() if line.strip()]


def wayback_closest(url, timestamp):
    """Nearest archived copy (availability API). timestamp like '20140301'. Returns the archived URL or ''."""
    text = get("https://archive.org/wayback/available", {"url": url, "timestamp": timestamp})
    try:
        return json.loads(text)["archived_snapshots"]["closest"]["url"]
    except (ValueError, KeyError):
        return ""


def wayback_page(url, timestamp=None):
    """Archived page text. With a timestamp, Wayback redirects to the closest snapshot. Uses id_ to get the raw page."""
    ts = timestamp or "2"
    return get(f"https://web.archive.org/web/{ts}id_/{url}")


VIDEO_PATTERNS = [
    ("youtube", re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|v/|live/)|youtu\.be/)([\w-]{11})")),
    ("file", re.compile(r"https?://[^\s\"'<>]+\.(?:mp4|wmv|m3u8|flv|mov|mp3|asx|wvx)(?:\?[^\s\"'<>]*)?", re.I)),
    ("ustream", re.compile(r"https?://(?:www\.)?ustream\.tv/[^\s\"'<>]+")),
    ("vimeo", re.compile(r"https?://(?:player\.)?vimeo\.com/[^\s\"'<>]+")),
    ("cspan", re.compile(r"https?://(?:www\.)?c-span\.org/video/\?[^\s\"'<>]+")),
    ("facebook", re.compile(r"https?://(?:www\.)?facebook\.com/[^\s\"'<>]*/videos/[^\s\"'<>]+")),
    ("stream", re.compile(r"https?://[^\s\"'<>]*(?:mms://|rtmp://|livestream\.com|stream\.house\.gov|houselive\.gov|video\.house\.gov)[^\s\"'<>]*")),
]


def video_links(html):
    """Every video reference in a page, as [(kind, id_or_url)], deduplicated."""
    out, seen = [], set()
    for kind, pat in VIDEO_PATTERNS:
        for m in pat.finditer(html or ""):
            val = m.group(1) if kind == "youtube" else m.group(0)
            if (kind, val) not in seen:
                seen.add((kind, val)); out.append((kind, val))
    return out


def yt_status(video_id):
    text = get("https://www.youtube.com/oembed", {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    if not text:
        return {"status": "gone"}
    d = json.loads(text)
    return {"status": "ok", "title": d.get("title"), "author": d.get("author_name"), "channel_url": d.get("author_url")}


def transcript_head(html_url, chars=4000):
    return re.sub(r"<[^>]+>", "", get(html_url))[:chars]


def cspan_search(query, sdate, edate=None, max_pages=3):
    """C-SPAN video-library search, server-rendered. Dates 'YYYY-MM-DD'. Returns [{url, title, date, abstract, kind}]
    where kind is 'house-committee', 'senate-committee', etc. Query '' with a date range lists everything that day."""
    def us(d): y, m, dd = d.split("-"); return f"{m}/{dd}/{y}"
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        params = {"sdate": us(sdate), "edate": us(edate or sdate), "searchtype": "Videos", "sort": "Most Recent Event", "text": "0", "query": query, "page": str(page)}
        html = get("https://www.c-span.org/search/", params)
        items = re.findall(r"<li class='onevid'>(.*?)</li>", html, re.S)
        for it in items:
            m = re.search(r"href='(//www\.c-span\.org/program/([\w-]+)/[^']+)' class='title'>\s*<h3>(.*?)</h3>", it, re.S)
            if not m: continue
            url = "https:" + m.group(1)
            if url in seen: continue
            seen.add(url)
            date = re.search(r"<time datetime='(\d{4}-\d{2}-\d{2})'", it)
            abstract = re.search(r"<p class='abstract'>(.*?)</p>", it, re.S)
            clean = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()
            out.append({"url": url, "kind": m.group(2), "title": clean(m.group(3)), "date": date.group(1) if date else "", "abstract": clean(abstract.group(1) if abstract else "")})
        total = re.search(r"of (\d+)\s*</span>", html)
        if not items or (total and len(seen) >= int(total.group(1))):
            break
    return out


def cspan_program(url):
    """A C-SPAN program page: {title, date, duration_seconds, description}. The visible h1 is a template
    placeholder; the og: meta tags and JSON-LD carry the real values."""
    html = get(url)
    g = lambda p: (re.search(p, html, re.S).group(1) if re.search(p, html, re.S) else "")
    m = re.search(r'"duration"\s*:\s*"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"', html)
    seconds = sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1))) if m else None
    unesc = lambda t: t.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'").replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"')
    return {"title": unesc(g(r"og:title'[^>]*content=\"([^\"]*)\"")),
            "date": g(r"<title>[^|]*\|\s*([A-Z][a-z]+ \d{1,2}, \d{4})") or g(r'"(?:startDate|uploadDate|datePublished)"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
            "duration_seconds": seconds,
            "description": unesc(g(r"og:description'[^>]*content=\"([^\"]*)\""))}
