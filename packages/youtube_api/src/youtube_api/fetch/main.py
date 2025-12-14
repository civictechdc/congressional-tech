import argparse
import logging

from pathlib import Path

from apps.congress_youtube.auth import load_youtube_api_key
from apps.congress_youtube.globals import add_global_args, add_youtube_args
from packages.youtube_api.tables import (
    get_all_committee_handless,
    get_all_commitee_names,
    get_committee_index,
)
from .youtube_event_fetcher import YoutubeEventFetcher


def main(
    tinydb_dir: Path, committee_name: str, committee_index: int, channels_csv_path: str
) -> None:
    api_key = load_youtube_api_key()

    ## read the names of each committee from the CSV file, include their row
    ##  indices so we can name their json files programmatically
    committee_names = get_all_commitee_names(
        with_index=True, csv_path=channels_csv_path
    )

    ## read all the handles for all the committees
    all_committee_handless = get_all_committee_handless()

    ## if we were passed a selection, determine both the committee name and index
    if committee_name is not None:
        committee_index = get_committee_index(channels_csv_path, committee_name)
        committee_names = [(committee_names[committee_index][0], committee_index)]
    elif committee_index is not None:
        committee_names = [(committee_names[committee_index][0], committee_index)]

    ## loop through the selected committees (defaults to all of them)
    for committee_name, committee_index in committee_names:
        ## specify the tinydb for this committee
        ## create a fetcher for this committee
        fetcher = YoutubeEventFetcher(
            youtube_api_key=api_key,
            committee_index=committee_index,
            csv_path=channels_csv_path,
            tinydb_dir=tinydb_dir,
        )

        handles = all_committee_handless[committee_index]
        for handle in handles:
            logging.info(f"Working on: {handle}")
            if len(handle) > 0:
                ## save channel metadata to the fetcher & the DB
                fetcher.get_channel(handle)
                ## read the "uploaded" playlist from the previously fetched metadata
                ##  and then store details about each video to the DB
                fetcher.get_all_channel_videos(handle)


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Fetch all YouTube videos from a channel and store them to record_path."
    )

    ## add shared args to the parser
    add_global_args(parser)

    ## add youtube specific args
    add_youtube_args(parser)

    # Create a mutually exclusive group
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-n",
        "--committee-name",  ## dashes are automatically converted to underscores
        type=str,
        help="Name of the committee to match against in the CSV file",
    )
    group.add_argument(
        "-i",
        "--committee-index",  ## dashes are automatically converted to underscores
        type=int,
        choices=range(len(get_all_commitee_names())),
        help="Index of the committee in the CSV file",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
