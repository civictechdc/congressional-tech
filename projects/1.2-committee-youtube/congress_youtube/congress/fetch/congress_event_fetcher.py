import os
import requests
from typing import Literal
from tinydb import TinyDB
from tinydb.table import Document
import time
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

    def __init__(self, record_path: str = "congress_youtube_db.json") -> None:
        ## initialize a dictionary to store the events in; keyed by their ids
        self.record_path = record_path

        self.events_tb = TinyDB(self.record_path).table("committee_meetings")
        print(
            f"Loaded {len(self.events_tb):d} events from {os.path.abspath(self.record_path)}"
        )
        self.event_urls = {}

    def fetch_event_list(
        self,
        api_key: str,
        chamber: Literal["house", "senate", "nochamber"] = "house",
    ):
        events = self.committee_meetings(chamber=chamber, api_key=api_key)[
            "committeeMeetings"
        ]
        for event in events:
            self.event_urls[event["eventId"]] = event["url"]

    def process_events(self, api_key: str) -> None:
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
                        event = generic_request(url, api_key=api_key)
                        event = event["api-root"]
                    else:
                        event = generic_request(url, api_key=api_key)

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
                    message = f"Unexpected error while fetching {eventId}: {e}, try: {url}&api_key={api_key}"
                    print(message)
            i += 1
            retried = False
        print("\nDone with all events.")

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
