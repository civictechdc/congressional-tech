"""
Shared YouTube helper for the swarm agents. Import it from python:

    import sys; sys.path.insert(0, "/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm")
    import yt
    yt.search("House Armed Services hearing Navy budget 2014")   # -> list of dicts
    yt.oembed("dQw4w9WgXcQ")                                      # -> {author, channel_url, title} or {status}
    yt.channel_search("@HouseArmedServices", "readiness")         # search inside one channel
    yt.local_videos("hsas00", "2014-03-01", "2014-04-15")         # tracked-channel videos from our data
    yt.meetings("hsas00", "2014-03-01", "2014-03-10")             # Congress.gov meeting records

Every network call is cached on disk (shared by all agents) and globally
rate-limited across processes, so never bypass this module for YouTube.
"""
import csv, fcntl, hashlib, json, os, re, time, urllib.parse, datetime as dt
import requests

SWARM = os.path.dirname(os.path.abspath(__file__))
SCRATCH = os.path.dirname(SWARM)
REPO = "/home/user/congressional-tech"
CACHE = os.path.join(SWARM, "cache")
os.makedirs(CACHE, exist_ok=True)
LOCK = os.path.join(SWARM, ".ratelimit")
MIN_INTERVAL = 0.5  # seconds between YouTube requests across ALL agents
_sess = requests.Session()
_HDR = {"Accept-Language": "en-US", "User-Agent": "Mozilla/5.0"}


def _throttle():
    with open(LOCK, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read() or 0)
        except ValueError:
            last = 0
        wait = last + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time()))
        fcntl.flock(f, fcntl.LOCK_UN)


def _get(url, params=None, retry_on_bot=True):
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    path = os.path.join(CACHE, key)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    for attempt in range(4):
        _throttle()
        r = _sess.get(url, params=params, headers=_HDR, timeout=40)
        text = r.text
        if r.status_code == 429 or "confirm you" in text and "not a bot" in text:
            if not retry_on_bot:
                return ""
            time.sleep(60 * (attempt + 1))
            continue
        if r.status_code == 200:
            open(path, "w", encoding="utf-8").write(text)
        return text if r.status_code == 200 else ""
    return ""


def _videos_from_page(text):
    out = []
    for m in re.finditer(r'"videoRenderer":\{"videoId":"([\w-]{11})"(.{0,6000}?)"navigationEndpoint"', text):
        body = m.group(2)
        title = re.search(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', body)
        tail = text[m.start(): m.start() + 12000]
        owner = re.search(r'"ownerText":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)".{0,600}?"canonicalBaseUrl":"/(@[^"]+)"', tail)
        when = re.search(r'"publishedTimeText":\{"simpleText":"([^"]+)"', tail)
        length = re.search(r'"lengthText":\{.{0,300}?"simpleText":"([^"]+)"', tail)
        out.append({
            "videoId": m.group(1),
            "title": json.loads('"' + title.group(1) + '"') if title else "",
            "channel_name": json.loads('"' + owner.group(1) + '"') if owner else "",
            "channel": owner.group(2) if owner else "",
            "published": when.group(1) if when else "",
            "length": length.group(1) if length else "",
        })
    seen, uniq = set(), []
    for v in out:
        if v["videoId"] not in seen:
            seen.add(v["videoId"]); uniq.append(v)
    return uniq


def search(query):
    """YouTube video search. Returns up to ~20 results with channel handle, relative date and length."""
    return _videos_from_page(_get("https://www.youtube.com/results", {"search_query": query}))


def channel_search(handle, query):
    """Search within one channel, e.g. channel_search('@HouseArmedServices', 'readiness posture')."""
    return _videos_from_page(_get(f"https://www.youtube.com/{handle}/search", {"query": query}))


def oembed(video_id):
    """Resolve any video (including unlisted) to its channel. {'status': 404} means private/deleted/nonexistent."""
    text = _get("https://www.youtube.com/oembed", {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"})
    if not text:
        return {"status": "unavailable"}
    d = json.loads(text)
    return {"author": d.get("author_name"), "channel_url": d.get("author_url"), "title": d.get("title")}


def video_page(video_id):
    """Upload date, duration (seconds) and description of a video, from its watch page."""
    ## watch pages are often behind YouTube's bot check from this server; fail fast
    t = _get("https://www.youtube.com/watch", {"v": video_id}, retry_on_bot=False)
    if not t:
        return {"status": "unavailable (bot check); use oembed() and search() instead"}
    g = lambda p: (re.search(p, t).group(1) if re.search(p, t) else "")
    return {"uploadDate": g(r'"uploadDate":"([^"]+)"'), "publishDate": g(r'"publishDate":"([^"]+)"'),
            "lengthSeconds": g(r'"lengthSeconds":"(\d+)"'), "channel": g(r'"canonicalBaseUrl":"/(@[^"]+)"'),
            "description": json.loads('"' + g(r'"shortDescription":"((?:[^"\\]|\\.)*)"') + '"')[:1500] if g(r'"shortDescription":"((?:[^"\\]|\\.)*)"') else ""}


# ---- local data (no network) ----
_local = None
def _load_local():
    global _local
    if _local is None:
        chan = list(csv.DictReader(open(f"{REPO}/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv")))
        _local = {}
        for i, row in enumerate(chan):
            p = f"{SCRATCH}/d4/youtube_{i:02d}.json"
            if not os.path.exists(p):
                continue
            for t, rows in json.load(open(p)).items():
                if t.startswith("youtube_videos_"):
                    for v in rows.values():
                        _local.setdefault(row["systemCode"], []).append({"videoId": v["videoId"], "channel": t[15:], "publishedAt": v["publishedAt"][:10], "title": v["title"], "description": v["description"]})
    return _local


def local_videos(committee_code, start, end, text=None):
    """Videos on our tracked channels for a committee between two ISO dates; optional case-insensitive text filter on title+description."""
    out = [v for v in _load_local().get(committee_code, []) if start <= v["publishedAt"] <= end]
    if text:
        out = [v for v in out if text.lower() in (v["title"] + " " + v["description"]).lower()]
    return sorted(out, key=lambda v: v["publishedAt"])


def local_find_video(video_id):
    for code, vs in _load_local().items():
        for v in vs:
            if v["videoId"] == video_id:
                return dict(v, committee_code=code)
    return None


_meet = None
def meetings(committee_code, start, end):
    """Congress.gov meeting records (House + joint, 112th on) for a parent committee code between two ISO dates."""
    global _meet
    alias = {"jjec00": "jsec00", "hlvc00": "hsgo00", "hlfd00": "hsju00", "hlqj00": "hsju00"}
    if _meet is None:
        _meet = [json.loads(l) for l in open(f"{SCRATCH}/meetings.jsonl")]
    out = []
    for m in _meet:
        codes = {alias.get(c["systemCode"][:4] + "00", c["systemCode"][:4] + "00") for c in m.get("committees", [])}
        if committee_code in codes and start <= m["date"][:10] <= end:
            out.append({"eventId": m["eventId"], "date": m["date"][:10], "type": m.get("type"), "status": m.get("meetingStatus"),
                        "title": m.get("title"), "committees": [c.get("name", "") for c in m.get("committees", [])],
                        "videos": [v.get("url") for v in (m.get("videos") or [])]})
    return sorted(out, key=lambda m: m["date"])


def transcript_head(html_url, chars=4000):
    """First part of the official GPO transcript (title page: date, location, 'closed' notices)."""
    t = _get(html_url)
    return re.sub(r"<[^>]+>", "", t)[:chars]
