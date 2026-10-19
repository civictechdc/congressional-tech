"""Congress.gov JSON requests with API credentials and the existing retry budget."""

from congress_api.transport.http import get_with_retry

API = "https://api.congress.gov/v3"


def get(session, url, api_key, params=None, attempts=5):
    return get_with_retry(session, url, params={**(params or {}), "api_key": api_key, "format": "json"}, attempts=attempts).json()
