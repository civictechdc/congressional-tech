"""
Search the web for a sample of gap rows and say what each search surfaced.

    SERPAPI_TOKEN=... python docs/youtube-coverage/research/scripts/search_smoke.py sample.json results.json [--youtube-key KEY]

`sample.json` is a list of rows with at least `key`, `date`, `query` (the smoke-test samples). Each
query goes to Google through SerpAPI once (answers are cached in `results.json`, so a rerun costs
nothing), and the answer is reduced to its organic and video results with real URLs. YouTube links
are looked up in the Data API (title, channel, published, duration) so a find can be judged: a
recording on the meeting's day or the day after, at least 20 minutes long, is reported as `video`;
a house.gov, senate.gov or c-span.org page is reported as `page`; anything else as `other`.
Metered: SerpAPI charges per search, so the sample should be chosen before running.
"""
import argparse, json, os, re, sys, time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages/congress_api/src"))
from congress_api.gpo.match import VIDEO_ID  # noqa: E402

OFFICIAL = re.compile(r"\.(house|senate)\.gov|c-span\.org|congress\.gov|govinfo\.gov", re.I)
ISO8601 = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def google(query, key, cache, attempts=4):
    """One Google search through SerpAPI, cached by query; SerpAPI sometimes takes a minute to answer, so retry."""
    if query not in cache:
        for attempt in range(attempts):
            try:
                r = requests.get("https://serpapi.com/search.json", params={"engine": "google", "q": query, "num": 10, "api_key": key}, timeout=120)
                r.raise_for_status()
                cache[query] = r.json()
                break
            except requests.RequestException as ex:
                if attempt == attempts - 1:
                    raise
                print(f"  retrying after {ex.__class__.__name__}", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        time.sleep(1)
    return cache[query]


def hits(answer):
    """(title, url) for every organic and video result in a SerpAPI answer."""
    out = []
    for block in ("organic_results", "inline_videos", "video_results", "top_stories"):
        for item in answer.get(block) or []:
            if item.get("link"):
                out.append((item.get("title", ""), item["link"]))
    return out


def youtube_details(ids, key, cache):
    """title, channel, published date and seconds for YouTube IDs, via the Data API."""
    todo = [i for i in ids if i not in cache]
    for start in range(0, len(todo), 50):
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "snippet,contentDetails", "id": ",".join(todo[start:start + 50]), "key": key}, timeout=60).json()
        for it in r.get("items", []):
            dur = ISO8601.match(it["contentDetails"]["duration"])
            h, m, s = (int(x or 0) for x in dur.groups()) if dur else (0, 0, 0)
            cache[it["id"]] = {"title": it["snippet"]["title"], "channel": it["snippet"]["channelTitle"], "published": it["snippet"]["publishedAt"][:10], "seconds": h * 3600 + m * 60 + s}
        for i in todo[start:start + 50]:
            cache.setdefault(i, None)
    return {i: cache.get(i) for i in ids}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sample"); p.add_argument("results"); p.add_argument("--youtube-key", default=os.environ.get("YOUTUBE_API_KEY"))
    a = p.parse_args()
    key = os.environ["SERPAPI_TOKEN"]
    sample = json.load(open(a.sample))
    store = json.load(open(a.results)) if Path(a.results).exists() else {"searches": {}, "youtube": {}}
    for row in sample:
        answer = google(row["query"], key, store["searches"])
        json.dump(store, open(a.results, "w"))
        found = hits(answer)
        ids = list(dict.fromkeys(m.group(1) for _, u in found for m in [VIDEO_ID.search(u)] if m))
        details = youtube_details(ids, a.youtube_key, store["youtube"]) if ids and a.youtube_key else {}
        row["results"] = []
        for title, url in found:
            m = VIDEO_ID.search(url)
            d = details.get(m.group(1)) if m else None
            if m and d:
                near = d["published"][:7] == row["date"][:7] and 0 <= int(d["published"].replace("-", "")) - int(row["date"].replace("-", "")) <= 1
                row["results"].append({"kind": "video" if near and d["seconds"] >= 1200 else "youtube", "id": m.group(1), "url": url, **d})
            elif OFFICIAL.search(url):
                row["results"].append({"kind": "page", "title": title, "url": url})
            else:
                row["results"].append({"kind": "other", "title": title, "url": url})
        print(f"{row['key']} {row['date']} {row.get('committee', '')[:24]:24} | " + ("; ".join(
            f"VIDEO {r['id']} {r['channel'][:22]} {r['published']} {r['seconds'] // 60}min {r['title'][:50]}" if r["kind"] == "video" else
            f"yt {r['id']} {r['channel'][:18]} {r['published']} {r['seconds'] // 60}min {r['title'][:40]}" if r["kind"] == "youtube" else
            f"page {r['url'][:70]}" for r in row["results"][:6]) or "nothing"))
    json.dump(store, open(a.results, "w"))
    json.dump(sample, open(Path(a.results).with_suffix(".rows.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
