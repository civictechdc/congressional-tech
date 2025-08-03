import os
import pathlib
import requests
from typing import Literal
import json
import pickle
import time
from xml_to_dict import parse_xml_string
import argparse


CONGRESS_API_BASE_URL = "https://api.congress.gov/v3/"


def load_api_key() -> str:
    """
    Load the DATA.GOV API key, in order of precedence:
    1. Command-line argument (--api-key)
    2. Environment variable DATA_GOV_API_KEY
    3. File at ~/.data.gov.key

    Returns:
        str: The API key string.

    Raises:
        RuntimeError: If no API key is found.
    """
    parser = argparse.ArgumentParser(description="Congress.gov API data fetcher.")
    parser.add_argument("--api-key", help="DATA.GOV API key")
    args, _ = parser.parse_known_args()

    if args.api_key:
        return args.api_key

    api_key = os.environ.get("DATA_GOV_API_KEY")
    if api_key:
        return api_key

    key_path = os.path.join(pathlib.Path.home(), ".data.gov.key")
    try:
        with open(key_path) as handle:
            return handle.read().strip()
    except Exception:
        raise RuntimeError(
            f"API key not found. Provide it via --api-key, DATA_GOV_API_KEY env var, or save it to {key_path}"
        )


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


class CongressionalEventFetcher(object):
    """
    A utility class for retrieving and processing congressional committee meeting data
    from the Congress.gov API.

    Attributes:
        record_path (str): The base path used to read/write cached event data.
        events (dict): A dictionary of committee events, keyed by event ID.

    Methods:
        read(): Load previously cached events from disk.
        dump(): Persist events to disk in JSON or pickle format.
        get_all_events(): Populate the event dictionary with committee meeting URLs.
        process_events(): Expand and hydrate stored event URLs into full metadata.
        committee_meetings(): Fetch committee meeting metadata by chamber and congress.
        committee_meeting_details(): Fetch full metadata for a specific committee event.
    """

    def __init__(self, record_path: str = "events_output") -> None:
        ## initialize a dictionary to store the events in; keyed by their ids
        self.record_path = record_path

        ## read in any events that we might have already processed
        try:
            self.read()
        except FileNotFoundError:
            self.events = {}

    def read(self) -> None:
        """
        Load the contents of the output file back into self.events.
        Tries both JSON and Pickle formats based on file presence.
        """
        if os.path.isfile(f"{self.record_path}.json"):
            with open(f"{self.record_path}.json", "r") as f:
                self.events = json.load(f)
        elif os.path.isfile(f"{self.record_path}.pkl"):
            with open(f"{self.record_path}.pkl", "rb") as f:
                self.events = pickle.load(f)
        else:
            raise FileNotFoundError("No output file found to load events.")

    def dump(self, format: str = "json") -> None:
        """
        Dump the contents of self.events to a file.
        Args:
            output_path (str): The base path to write the output file (no extension).
            format (str): Either "json" or "pickle".
        """
        if format == "json":
            with open(f"{self.record_path}.json", "w") as f:
                json.dump(self.events, f, indent=2)
        elif format == "pickle":
            with open(f"{self.record_path}.pkl", "wb") as f:
                pickle.dump(self.events, f)
        else:
            raise ValueError("Unsupported format. Use 'json' or 'pickle'.")

    def get_all_events(
        self,
        chamber: Literal["house", "senate", "nochamber"] = "house",
    ):
        events = self.committee_meetings(chamber=chamber)["committeeMeetings"]
        for event in events:
            self.events[event["eventId"]] = event["url"]

    def process_events(self, api_key: str) -> None:
        total = len(self.events.keys())

        i = 0
        event_ids = list(self.events.items())
        retried = False
        while i < total:
            eventId, value = event_ids[i]
            ## if the value is a placeholder url, let's expand it
            if isinstance(value, str) and value.startswith("https://api.congress.gov"):
                message = f"Processing {i + 1}/{total} -> {eventId}"
                print(f"\r{message.ljust(40)}", end="", flush=True)
                try:
                    if retried:
                        ## apparently some entries are broken and can't be json serialized...
                        value = value.replace("json", "xml")
                    self.events[eventId] = generic_request(value, api_key=api_key)
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 429:
                        print(
                            f"\nRate limit hit while fetching {eventId}. Skipping remaining fetches."
                        )
                        return
                    elif (
                        e.response is not None
                        and e.response.status_code == 500
                        and not retried
                    ):
                        retried = True
                        time.sleep(1)
                        continue
                    else:
                        raise RuntimeError(f"Failed to fetch {eventId}: {e}")
                except Exception as e:
                    message = f"Unexpected error while fetching {eventId}: {e}, try: {value}&api_key={api_key}"
                    print(message)
            ## if xml was dumped straight to the file, let's parse it
            elif isinstance(value, str) and value.startswith(
                '<?xml version="1.0" encoding="utf-8"?>'
            ):
                value = parse_xml_string(value)["api-root"]
                self.events[eventId] = value
                message = f"Converted {eventId} from xml."
                print(message)
            i += 1
            retried = False
        print("\nDone processing all events.")

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
    api_key = load_api_key()
    fetcher = CongressionalEventFetcher()

    ## if we haven't recorded any events, let's go ahead and do that
    ##  first
    if len(fetcher.events.keys()) == 0:
        fetcher.get_all_events("house")
        fetcher.dump()

    try:
        fetcher.process_events(api_key=api_key)
    except Exception as e:
        raise e
    finally:
        ## overwrite whatever is on disk with wherever we got
        fetcher.dump()


if __name__ == "__main__":
    main()
