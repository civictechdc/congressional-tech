"""
Search the web for a sample of gap rows and say what each search surfaced.

    SERPAPI_TOKEN=... python docs/youtube-coverage/research/scripts/search_smoke.py sample.json results.json [--embeds] [--threads 8]

`sample.json` is a list of rows with at least `key`, `date`, `query` (the smoke-test samples). Each
query goes to Google through SerpAPI once (answers are cached in `results.json`, so a rerun costs
nothing), and the answer is reduced to its organic and video results with real URLs. YouTube links
are looked up in the Data API (title, channel, published, duration) so a find can be judged: a
recording of at least 20 minutes that was published on the meeting's day or the day after, or whose
title carries the meeting's date, is reported as `video`; a house.gov, senate.gov, congress.gov,
govinfo.gov or c-span.org page is reported as `page`; anything else as `other`.

With `--embeds`, every committee page among the results (a house.gov or senate.gov page that is not
docs.house.gov, congress.gov or the like) is fetched once and read for what it embeds: YouTube
videos, Facebook videos and Senate player recordings. Embedded YouTube videos get the same check;
Senate player filenames are probed on the archive. That is where unlisted uploads and Facebook
streams live, since neither reaches a channel's uploads playlist.

Writes `results.json` (the cache) and `results.rows.json` (the sample with a `results` list per row),
and prints one line per row. Metered: SerpAPI charges per search, so choose the sample first.
"""
import argparse, datetime as dt, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages/congress_api/src"))
from congress_api.gpo.match import VIDEO_ID  # noqa: E402
from congress_api.senate.isvp import STREAM, archive_url, live_url, player_url  # noqa: E402
from hearing_text_sources import title_dates  # noqa: E402

OFFICIAL = re.compile(r"\.(house|senate)\.gov|c-span\.org|congress\.gov|govinfo\.gov", re.I)
## official pages that never embed a recording of their own
NOT_A_COMMITTEE_PAGE = re.compile(r"docs\.house\.gov|congress\.gov|govinfo\.gov|live\.house\.gov|clerk\.house\.gov|majorityleader\.gov|www\.house\.gov|www\.senate\.gov/legislative|c-span\.org|\.pdf($|\?)", re.I)
ISO8601 = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
FACEBOOK_VIDEO = re.compile(r"facebook\.com(?:/|%2F)(?:[\w.]+(?:/|%2F)videos(?:/|%2F)|watch/?\?v=)(\d+)", re.I)
ISVP_FILENAME = re.compile(r"senate\.gov/isvp/?\?[^\"'\s]*?filename=([A-Za-z]+\d{6}[A-Za-z]?)", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
FULL_SECONDS = 1200


def search(query, key, attempts=4):
    """One Google search through SerpAPI; SerpAPI sometimes takes a minute to answer, so retry. None when it keeps failing."""
    for attempt in range(attempts):
        try:
            r = requests.get("https://serpapi.com/search.json", params={"engine": "google", "q": query, "num": 10, "api_key": key}, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    return None


def hits(answer):
    """(title, url) for every organic and video result in a SerpAPI answer."""
    return [(item.get("title", ""), item["link"]) for block in ("organic_results", "inline_videos", "video_results", "top_stories")
            for item in (answer or {}).get(block) or [] if item.get("link")]


def youtube_details(ids, key):
    """{id: title, channel, published date, seconds} from the Data API; None for an ID YouTube no longer serves."""
    out = dict.fromkeys(ids)
    for start in range(0, len(ids), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,contentDetails", "id": ",".join(ids[start:start + 50]), "key": key}, timeout=60).json()
        for it in r.get("items", []):
            dur = ISO8601.match(it["contentDetails"]["duration"])
            h, m, s = (int(x or 0) for x in dur.groups()) if dur else (0, 0, 0)
            out[it["id"]] = {"title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"], "published": it["snippet"]["publishedAt"][:10], "seconds": h * 3600 + m * 60 + s}
    return out


def read_page(url):
    """What a committee page embeds: YouTube IDs, Facebook video IDs, Senate player filenames."""
    try:
        html = requests.get(url, timeout=45, headers=UA).text
    except requests.RequestException:
        html = ""
    return {"youtube": sorted({m.group(1) for m in VIDEO_ID.finditer(html)}), "facebook": sorted(set(FACEBOOK_VIDEO.findall(html))),
            "isvp": sorted(set(ISVP_FILENAME.findall(html))), "bytes": len(html)}


def senate_recording(filename):
    """The player URL when the Senate archive serves this filename, else ""."""
    comm = re.sub(r"[AB]?\d{6}[A-Za-z]?$", "", filename).lower()  # "appropsA031120" -> "approps"
    if comm not in STREAM:
        return ""
    for u in (archive_url(comm, filename), live_url(comm, filename)):
        try:
            if requests.head(u, timeout=20, headers=UA).status_code == 200:
                return player_url(comm, filename)
        except requests.RequestException:
            pass
    return ""


def is_the_meeting(video, day):
    """A full recording of the meeting held on `day`: long enough, and posted then or the next day, or titled with that date."""
    d0 = dt.date.fromisoformat(day)
    posted = dt.date.fromisoformat(video["published"])
    return video["seconds"] >= FULL_SECONDS and (0 <= (posted - d0).days <= 1 or d0 in title_dates(video["title"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sample"); p.add_argument("results"); p.add_argument("--youtube-key", default=os.environ.get("YOUTUBE_API_KEY"))
    p.add_argument("--embeds", action="store_true", help="fetch the committee pages among the results and read their embeds")
    p.add_argument("--threads", type=int, default=8)
    a = p.parse_args()
    key = os.environ["SERPAPI_TOKEN"]
    sample = json.load(open(a.sample))
    store = json.load(open(a.results)) if Path(a.results).exists() else {}
    for k in ("searches", "youtube", "pages", "isvp"):
        store.setdefault(k, {})

    def fill(cache, keys, fn, keep=lambda v: True):
        """Run fn over the keys the cache lacks, in parallel, and save."""
        todo = sorted({k for k in keys if k not in cache})
        with ThreadPoolExecutor(a.threads) as pool:
            cache.update({k: v for k, v in zip(todo, pool.map(fn, todo)) if keep(v)})
        json.dump(store, open(a.results, "w"))
        return len(todo)

    n = fill(store["searches"], [r["query"] for r in sample], lambda q: search(q, key), keep=lambda v: v is not None)
    found = {r["key"]: hits(store["searches"].get(r["query"])) for r in sample}
    pages = {r["key"]: list(dict.fromkeys(u for _, u in found[r["key"]] if OFFICIAL.search(u) and not NOT_A_COMMITTEE_PAGE.search(u))) if a.embeds else [] for r in sample}
    n_pages = fill(store["pages"], [u for us in pages.values() for u in us], read_page)
    ids = sorted({m.group(1) for fs in found.values() for _, u in fs for m in [VIDEO_ID.search(u)] if m}
                 | {v for us in pages.values() for u in us for v in store["pages"][u]["youtube"]})
    new_ids = [i for i in ids if i not in store["youtube"]]
    if new_ids and a.youtube_key:
        store["youtube"].update(youtube_details(new_ids, a.youtube_key))
    n_isvp = fill(store["isvp"], [fn for us in pages.values() for u in us for fn in store["pages"][u]["isvp"]], senate_recording)
    json.dump(store, open(a.results, "w"))
    print(f"{n} searches, {n_pages} pages, {len(new_ids)} videos and {n_isvp} Senate filenames fetched now; the rest came from {a.results}", file=sys.stderr)

    for row in sample:
        if row["query"] not in store["searches"]:
            row["results"] = [{"kind": "search_failed"}]
            continue
        row["results"] = []
        for title, url in found[row["key"]]:
            m = VIDEO_ID.search(url)
            d = store["youtube"].get(m.group(1)) if m else None
            if m and d:
                row["results"].append({"kind": "video" if is_the_meeting(d, row["date"]) else "youtube", "id": m.group(1), "url": url, **d})
            else:
                row["results"].append({"kind": "page" if OFFICIAL.search(url) else "other", "title": title, "url": url})
        for url in pages[row["key"]]:
            e = store["pages"][url]
            for v in e["youtube"]:
                d = store["youtube"].get(v)
                if d:
                    row["results"].append({"kind": "embed_video" if is_the_meeting(d, row["date"]) else "embed_youtube", "id": v, "page": url, **d})
            row["results"] += [{"kind": "embed_facebook", "id": fb, "page": url} for fb in e["facebook"]]
            row["results"] += [{"kind": "embed_senate" if store["isvp"].get(fn) else "embed_senate_missing", "filename": fn, "url": store["isvp"].get(fn, ""), "page": url} for fn in e["isvp"]]
        finds = [f"{r['kind'].upper()} {r.get('id') or r.get('filename')} {r.get('channel', '')[:20]} {r.get('published', '')} {r.get('seconds', 0) // 60}min {r.get('title', '')[:45]} <{r.get('page', r.get('url', ''))[:70]}>"
                 for r in row["results"] if r["kind"] in ("video", "embed_video", "embed_facebook", "embed_senate")]
        print(f"{row['key']} {row['date']} {row.get('committee', '')[:22]:22} | pages {len(pages[row['key']])} | " + ("; ".join(finds) or "nothing"))
    json.dump(sample, open(Path(a.results).with_suffix(".rows.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
