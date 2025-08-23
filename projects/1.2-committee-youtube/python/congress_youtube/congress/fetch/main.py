import argparse

from ...auth import load_congress_api_key
from ...globals import add_global_args
from .congress_event_fetcher import CongressEventFetcher


def main(record_path: str, chamber: str = "house"):
    api_key = load_congress_api_key()
    fetcher = CongressEventFetcher(api_key, record_path)
    fetcher.fetch_event_list(chamber)
    fetcher.process_events()


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

    args = parser.parse_known_args()

    main(vars(args))


if __name__ == "__main__":
    parse_args_and_run()
