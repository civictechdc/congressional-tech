import argparse
from tinydb import Query

from ...globals import add_global_args
from ..fetch.congress_event_fetcher import CongressEventFetcher
from .committee_summary import CommitteeSummary
from .committee import Committee


def main(tinydb_dir: str, chamber: str = "house", congress_number: int = 119):
    ## pass a dummy api_key so we can access tinydb tables
    fetcher = CongressEventFetcher("", tinydb_dir)
    dicts = fetcher.committees_tb.all()
    committee_q = Query()
    summaries = CommitteeSummary.from_dicts(dicts)
    committees: list[Committee] = [
        Committee.from_summary(summary) for summary in summaries
    ]

    ## load details for each committee
    for committee in committees:
        committee.get_details("")  ## use dummy api key

    top_level = [
        c for c in committees if (c.summary.parent is None and c.details.isCurrent)
    ]

    for c in top_level:
        print("-" * 80)
        print(c)
        print("-" * 40)
        print("Sub-committees:", len(c.summary.children))
        print(
            "Sub-sub-committees",
            sum(
                [
                    len([child for child in sc_summary.children])
                    for sc_summary in c.summary.children
                ]
            ),
        )
        print("Type:", c.summary.committeeTypeCode)


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
