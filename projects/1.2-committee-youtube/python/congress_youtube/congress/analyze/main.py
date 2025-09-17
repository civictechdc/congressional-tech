import argparse
from collections import defaultdict


from ...globals import add_global_args
from ..fetch.congress_committee_fetcher import CongressCommitteeFetcher
from ..fetch.congress_event_fetcher import CongressEventFetcher


def main(tinydb_dir: str, chamber: str = "house", congress_number: int = 119):
    ## pass a dummy api_key so we can access tinydb tables
    committee_fetcher = CongressCommitteeFetcher("", tinydb_dir)
    committee_mapping = committee_fetcher.return_system_code_committees_mapping()
    event_fetcher = CongressEventFetcher("", tinydb_dir)
    event_mapping = event_fetcher.return_eventid_event_mapping()
    lens = defaultdict(int)
    for event in event_mapping.values():
        committees: list | dict = event["committees"]
        if isinstance(committees, list):
            for committee in committees:
                committee_mapping[committee["systemCode"]].events.append(event)
        elif isinstance(committee, dict):
            if "item" not in committees.keys():
                raise KeyError(
                    f"Expected 'item', got: {committees.keys()} for event {event['eventId']}"
                )
    for committee in committee_mapping.values():
        if len(committee.events) > 0:
            print(committee.youtube)


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Fetch all events from a chamber of the US Congress and store them in a TinyDB database."
    )

    ## add shared args to the parser
    add_global_args(parser)

    parser.add_argument(
        "--chamber",
        type=str,
        choices=["house", "senate", "nochamber"],
        default="house",
        help="The chamber of Congress whose calendar to pull from.",
    )

    parser.add_argument(
        "--congress_number",
        type=int,
        choices=range(100, 120),
        default=119,
        help="The session of Congress to pull data from (NOTE: only tried 119, not sure how early you can go back).",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
