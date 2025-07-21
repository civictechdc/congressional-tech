import os
import pathlib
import requests
from typing import Literal


CONGRESS_API_BASE_URL = "https://api.congress.gov/v3/"


def congress_api_get(endpoint: str, pagination=True, **kwargs):
    url = f"{CONGRESS_API_BASE_URL}{endpoint}"

    # apply default parameters but overwrite w/ kwargs
    params = {"format": "json", "limit": 250, **kwargs, "api_key": DATA_GOV_API_KEY}

    response_json = generic_request(url, **params)

    if pagination and "pagination" in response_json:
        ## determine the key to aggregate
        response_keys = [
            key for key in response_json.keys() if key not in {"pagination", "request"}
        ]
        ## validate the type of the aggregate values
        for key in response_keys:
            if type(response_json[key]) is not list:
                raise TypeError(
                    f"Type of {key} ({type(response_json[key])}) cannot be aggregated."
                )
        ## find the total count
        count = response_json.get("pagination", {}).get("count")
        retrieved = len(response_json[response_keys[0]])

        next_url = response_json.get("pagination", {}).get("next")
        while next_url:
            message = f"retrieved {retrieved: >5} out of {count: >5} ({(count - retrieved) // params['limit'] + 1: >3} fetches remaining)"
            print(message)
            next_response_json = generic_request(next_url, api_key=DATA_GOV_API_KEY)
            for key in response_keys:
                response_json[key].append(next_response_json[key])
            next_url = next_response_json.get("pagination", {}).get("next")
            retrieved += len(next_response_json[response_keys[0]])

    return response_json


def generic_request(url: str, **params) -> dict:
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Error fetching from Congress API: {e}")


try:
    with open(os.path.join(pathlib.Path.home(), ".data.gov.key")) as handle:
        DATA_GOV_API_KEY = handle.read().strip()
except Exception as e:
    print("API KEY NOT FOUND, EXITING")
    print(e.message)
    quit(1)


class CongressionalEventFetcher(object):
    def __init__(self):
        ## initialize a dictionary to store the events in; keyed by their ids
        self.events: dict = {}

    def get_all_events(
        self,
        chamber: Literal["house", "senate", "nochamber"] = "house",
    ):
        events = self.committee_meetings(chamber=chamber, pagination=False)[
            "committeeMeetings"
        ]
        print(events.keys())
        import pdb

        pdb.set_trace()

    def committee_meetings(
        self,
        congress: int = 119,
        chamber: Literal["house", "senate", "nochamber"] = "house",
        **kwargs,
    ) -> dict:
        return congress_api_get(f"committee-meeting/{congress}/{chamber}", **kwargs)

    def committee_meeting_details(
        self,
        eventId: int,
        congress: int = 119,
        chamber: Literal["house", "senate", "nochamber"] = "house",
        **kwargs,
    ):
        ## validate chamber input
        if chamber not in {"house", "senate", "nochamber"}:
            raise ValueError(
                f"Invalid chamber: {chamber}, must be one of: 'house', 'senate', 'nochamber'"
            )
        return congress_api_get(
            f"committee-meeting/{congress}/{chamber}/{eventId}", **kwargs
        )


def main():
    fetcher = CongressionalEventFetcher()

    fetcher.get_all_events("house")

    fetcher.dump()


if __name__ == "__main__":
    main()
