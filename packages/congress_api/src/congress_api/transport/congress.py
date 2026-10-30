"""Congress.gov JSON requests with API credentials and the existing retry budget."""

from congress_api.transport.http import get_with_retry

API = "https://api.congress.gov/v3"


def api_headers(api_key: str):
    """Return a per-URL header provider supplying `X-Api-Key` for Congress.gov API endpoints."""
    def _headers(url: str) -> dict[str, str]:
        if url and "api.congress.gov" in url:
            return {"X-Api-Key": api_key}
        return {}
    return _headers


def get_with_header(session, url, api_key, params=None, attempts=5):
    """Congress.gov JSON request sending `X-Api-Key` in request headers instead of query params."""
    clean_params = {k: v for k, v in (params or {}).items() if k.casefold() != "api_key"}
    clean_params["format"] = "json"
    return get_with_retry(
        session,
        url,
        params=clean_params,
        headers={"X-Api-Key": api_key},
        attempts=attempts,
    ).json()


def get(session, url, api_key, params=None, attempts=5, *, use_header=False):
    if use_header:
        return get_with_header(session, url, api_key, params=params, attempts=attempts)
    return get_with_retry(session, url, params={**(params or {}), "api_key": api_key, "format": "json"}, attempts=attempts).json()
