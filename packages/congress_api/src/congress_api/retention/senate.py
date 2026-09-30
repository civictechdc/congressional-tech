"""Read captured Senate HTML from a local cache."""

import re
from pathlib import Path


def cached_html_path(cache, url):
    """Retained hearing page: ``{cache}/senate_pages/{slug}.html``."""
    return Path(cache) / "senate_pages" / (re.sub(r"\W+", "_", url)[-180:] + ".html")


def seed_fetch(cache, url):
    path = cached_html_path(cache, url)
    return path.read_bytes().decode("utf-8", "replace") if path.exists() else ""
