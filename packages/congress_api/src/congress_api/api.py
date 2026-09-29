import requests
from .xml_to_dict import parse_xml_string
from .models.congress import parse_response
from .models.congress_xml import CongressXmlDocument
from .congress_source import CongressResponse, parse_congress_xml

CONGRESS_API_BASE_URL = "https://api.congress.gov/v3/"


def validate_paginated_response(response_json: dict) -> list:
    """Validate that response_json contains aggregatable list keys and return them."""
    if "pagination" not in response_json:
        return []

    response_keys = [
        key for key in response_json if key not in {"pagination", "request"}
    ]

    for key in response_keys:
        if not isinstance(response_json[key], list):
            raise TypeError(
                f"Type of {key} ({type(response_json[key])}) cannot be aggregated."
            )

    return response_keys


def congress_api_get(endpoint: str, pagination=True, **kwargs):
    if "api_key" not in kwargs.keys():
        raise KeyError("Missing api key, provided:", kwargs.keys())
    url = f"{CONGRESS_API_BASE_URL}{endpoint}"

    # apply default parameters but overwrite w/ kwargs
    params = {
        "format": "json",
        "limit": 250,
        **kwargs,
        "api_key": kwargs.get("api_key"),
    }

    response_json = generic_request(url, **params)

    if pagination and "pagination" in response_json:
        ## determine the key to aggregate
        response_keys = validate_paginated_response(response_json)
        ## find the total count
        count = response_json.get("pagination", {}).get("count")
        retrieved = len(response_json[response_keys[0]])

        next_url = response_json.get("pagination", {}).get("next")
        while next_url:
            message = (
                f"Fetched {retrieved: >5} summaries out of {count: >5} "
                f"({(count - retrieved) // params['limit'] + 1: >3} fetches remaining)"
            )
            print(message)
            next_response_json = generic_request(
                next_url, api_key=kwargs.get("api_key")
            )
            validate_paginated_response(next_response_json)
            for key in response_keys:
                response_json[key].extend(next_response_json[key])
            next_url = next_response_json.get("pagination", {}).get("next")
            retrieved += len(next_response_json[response_keys[0]])

    return response_json


def generic_request(url: str, **params) -> dict:
    """Compatibility dictionaries; new consumers can use ``request_source``."""
    source = request_source(url, **params)
    if isinstance(source, CongressXmlDocument):
        value = parse_xml_string(source.content.body_bytes())
        # XML-to-dict is a legacy interpretation. Retain its full input as well.
        value["_source_xml"] = source.content.source_dict()
        return value
    return source.source_dict()


def request_source(url: str, **params) -> CongressResponse:
    """Fetch and parse a canonical source model, without writing a cache."""
    response = requests.get(url, params=params)
    response.raise_for_status()
    try:
        value = response.json()
    except ValueError:
        try:
            return parse_congress_xml(response.content)
        except Exception as e:
            raise ValueError(f"Failed to parse Congress.gov XML: {type(e).__name__}") from e
    return parse_response(value)
