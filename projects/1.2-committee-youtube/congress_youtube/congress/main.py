import os
import requests
from typing import Literal
import json
import pickle
import time
from .xml_to_dict import parse_xml_string
from .auth import load_api_key
from .api import congress_api_get, generic_request


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
        api_key: str,
        chamber: Literal["house", "senate", "nochamber"] = "house",
    ):
        events = self.committee_meetings(chamber=chamber, api_key=api_key)[
            "committeeMeetings"
        ]
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
        fetcher.get_all_events(api_key, "house")
        fetcher.dump()

    try:
        fetcher.process_events(api_key)
    except Exception as e:
        raise e
    finally:
        ## overwrite whatever is on disk with wherever we got
        fetcher.dump()


if __name__ == "__main__":
    main()
