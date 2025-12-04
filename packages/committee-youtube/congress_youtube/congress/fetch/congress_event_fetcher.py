import os
import requests
import time
from tinydb import TinyDB
from tinydb.table import Document
from typing import Literal

from ...globals import DEFAULT_TINYDB_DIR
from ..api import congress_api_get, generic_request


class CongressEventFetcher(object):
    """
    A utility class for retrieving and processing congressional committee meeting data
    from the Congress.gov API.

    Attributes:
        record_path (str): The base path used to read/write cached event data.
        events (dict): A dictionary of committee events, keyed by event ID.

    Methods:
        read(): Load previously cached events from disk.
        fetch_event_list(): Populate the event dictionary with committee meeting URLs.
        process_events(): Expand and hydrate stored event URLs into full metadata.
        committee_meetings(): Fetch committee meeting metadata by chamber and congress.
        committee_meeting_details(): Fetch full metadata for a specific committee event.
    """

    ## initialize a dictionary to store the events in; keyed by their ids
    event_urls = {}

    def __init__(self, api_key: str, tinydb_dir: str = DEFAULT_TINYDB_DIR) -> None:
        self.api_key = api_key
        self.tinydb_dir = tinydb_dir

        self.events_tinydb_path = os.path.join(tinydb_dir, "events.json")
        self.events_tb = TinyDB(self.events_tinydb_path).table("committee_meetings")
        print(
            f"Loaded {len(self.events_tb):d} events from {os.path.abspath(self.events_tinydb_path)}"
        )

    def fetch_event_list(
        self,
        chamber: Literal["house", "senate", "nochamber"] = "house",
        congress_number: int = 119,
    ):
        events = get_committee_meetings(
            congress=congress_number, chamber=chamber, api_key=self.api_key
        )["committeeMeetings"]
        for event in events:
            self.event_urls[event["eventId"]] = event["url"]

    def process_events(self) -> None:
        total = len(self.event_urls.keys())

        i = 0
        event_ids = list(self.event_urls.keys())
        retried = False
        ## use a while loop so we can stay in one spot
        ##  and only advance if we succeed
        while i < total:
            eventId = event_ids[i]
            url: str = self.event_urls[eventId]
            ## if the value is a placeholder url, let's expand it
            if not self.events_tb.contains(doc_id=eventId) and url.startswith(
                "https://api.congress.gov"
            ):
                message = f"Fetching details for {i + 1}/{total} -> {eventId}"
                print(f"\r{message.ljust(40)}", end="", flush=True)
                try:
                    if retried:
                        ## apparently some entries are broken and can't be json serialized...
                        ##  so we'll try the xml endpoint instead
                        url = url.replace("json", "xml")
                        print("Trying XML instead...")
                        event = generic_request(url, api_key=self.api_key)
                        event = event["api-root"]
                    else:
                        event = generic_request(url, api_key=self.api_key)

                    self.events_tb.insert(
                        Document(event["committeeMeeting"], doc_id=eventId)
                    )
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
                    message = f"Unexpected error while fetching {eventId}: {e}, try: {url}&api_key={self.api_key}"
                    print(message)
            i += 1
            retried = False
        print("\nDone with all events.")

    def return_eventid_event_mapping(self):
        dicts = self.events_tb.all()
        event_ids = [this_dict["eventId"] for this_dict in dicts]
        return dict(zip(event_ids, dicts))


def get_committee_meetings(
    congress: int = 119,
    chamber: Literal["house", "senate", "nochamber"] = "house",
    **kwargs,
) -> dict:
    ## validate chamber input
    if not (100 <= congress <= 120):
        raise ValueError(f"Invalid congress: {congress}, must be between 100 and 120")
    if chamber not in {"house", "senate", "nochamber"}:
        raise ValueError(
            f"Invalid chamber: {chamber}, must be one of: 'house', 'senate', 'nochamber'"
        )
    return congress_api_get(f"committee-meeting/{congress}/{chamber}", **kwargs)
