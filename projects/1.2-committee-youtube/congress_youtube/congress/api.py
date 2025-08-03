import requests
from .xml_to_dict import parse_xml_string

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
            message = f"retrieved {retrieved: >5} out of {count: >5} ({(count - retrieved) // params['limit'] + 1: >3} fetches remaining)"
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
    response = requests.get(url, params=params)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        try:
            return_value = parse_xml_string(response.text)
            if "api-root" not in return_value.keys():
                raise ValueError(f"Invalid XML with keys: {return_value.keys()}")
        except Exception as e:
            raise ValueError(f"Failed to parse XML {e.message}")
        return return_value
