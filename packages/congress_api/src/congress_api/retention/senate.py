"""Read captured Senate HTML from a local cache."""

import re


def seed_fetch(cache, url):
    path = cache / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")
    return path.read_bytes().decode("utf-8", "replace") if path.exists() else ""
