import argparse
from pathlib import Path

from apps.congress_youtube.auth import load_congress_api_key
from apps.congress_youtube.globals import add_global_args
from ..analyze.committee import Committee
from ..analyze.committee_summary import CommitteeSummary
from .congress_event_fetcher import CongressEventFetcher
from .congress_committee_fetcher import CongressCommitteeFetcher


def fetch_committees(api_key: str, tinydb_dir: Path, chamber):
    committee_fetcher = CongressCommitteeFetcher(api_key, tinydb_dir)

    ## fetch the summaries
    committee_fetcher.fetch_all_committees(chamber)
    dicts = committee_fetcher.committees_tb.all()

    ## map the summaries to their class instances
    summaries = CommitteeSummary.from_dicts(dicts)

    ## initialize Committee instances in order to fetch the details
    committees = [Committee.from_summary(summary) for summary in summaries]
    num_committees = len(committees)
    for i, committee in enumerate(committees):
        if not i % 25:
            print(f"Working on {i}/{num_committees}")
        committee.get_details(api_key)


## TODO import chamber + congress_number typing and validation
def fetch_events(api_key: str, tinydb_dir: Path, chamber, congress_number: int):
    event_fetcher = CongressEventFetcher(api_key, tinydb_dir)
    event_fetcher.fetch_event_list(chamber, congress_number)


def main(tinydb_dir: Path, chamber: str = "house", congress_number: int = 119):
    api_key = load_congress_api_key()
    fetch_committees(api_key, tinydb_dir, chamber)
    fetch_events(tinydb_dir, chamber, congress_number)


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
