"""Retrieve Senate playlists and caption segments with the existing retry policy."""

import requests

from congress_api.models.content import RawContent
from congress_api.models.media import MediaTextSource

HDR = {"User-Agent": "Mozilla/5.0"}


sess = requests.Session()


sess.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))


def get_source(url: str, attempts: int = 3, *, sources: list[MediaTextSource] | None = None) -> MediaTextSource:
    """Return the complete response and its status for HTTP 200 or 404.

    Exhausted errors must remain errors: converting them to empty text turns a
    temporary outage into a permanent negative row in the incremental index.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")
    error = None
    for i in range(attempts):
        try:
            r = sess.get(url, headers=HDR, timeout=30)
            if r.status_code in (200, 404):
                source = {"url": url, "text": r.text, "status_code": r.status_code}
                if isinstance(getattr(r, "content", None), bytes):
                    media_type = getattr(r, "headers", {}).get("Content-Type", "text/vtt" if url.split("?", 1)[0].endswith(".vtt") else "application/vnd.apple.mpegurl")
                    source["raw_body"] = RawContent.from_bytes(r.content, media_type)
                captured = MediaTextSource.model_validate(source)
                if sources is not None:
                    sources.append(captured)
            if r.status_code == 200:
                if r.text.strip():
                    return captured
                error = requests.RequestException(f"Empty HTTP 200 response for {url}")
            if r.status_code == 404:
                return captured
            elif r.status_code != 200:
                error = requests.HTTPError(f"HTTP {r.status_code} for {url}", response=r)
        except requests.RequestException as exc:
            error = exc
    raise error


def get(url: str, attempts: int = 3) -> str:
    """Compatibility text reader; typed acquisition retains original bytes."""
    result = get_source(url, attempts)
    return result.text if result.status_code == 200 else ""
