import argparse
from tinydb import Query

from ...globals import add_global_args
from ..fetch.congress_event_fetcher import CongressEventFetcher
from .committee_summary import CommitteeSummary


def main(tinydb_dir: str, chamber: str = "house", congress_number: int = 119):
    ## pass a dummy api_key so we can access tinydb tables
    fetcher = CongressEventFetcher("", tinydb_dir)
    committees = fetcher.committees_tb.all()
    committee_q = Query()
    summaries = CommitteeSummary.from_dicts(committees)
    top_level = [summary for summary in summaries if summary.parent is None]
    types = {c.committeeTypeCode: 0 for c in top_level}
    for ctype in types.keys():
        types[ctype] = fetcher.committees_tb.count(
            committee_q.committeeTypeCode == ctype
        )
    print(types)
    has_children = [summary for summary in summaries if summary.children]
    for c in has_children:
        print(c, end="----\n" * 4)

    # fetcher.fetch_event_list(congress_number, chamber)
    # fetcher.process_events()


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

    print(args)
    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
