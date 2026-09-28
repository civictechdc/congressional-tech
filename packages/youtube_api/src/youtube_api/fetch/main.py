import argparse
import logging
import sys

from pathlib import Path

from congress_shared.auth import load_youtube_api_key
from congress_shared.globals import add_global_args, add_youtube_args
from youtube_api.tables import (
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
    all_committee_handless = get_all_committee_handless(
        csv_path=channels_csv_path, include_member_channels=True
    )

    ## if we were passed a selection, determine both the committee name and index
    if committee_name is not None:
        committee_index = get_committee_index(committee_name, channels_csv_path)
        committee_names = [(committee_names[committee_index][0], committee_index)]
    elif committee_index is not None:
        # Validate the committee index
        if committee_index < 0 or committee_index >= len(committee_names):
            raise ValueError(f"Committee index {committee_index} is out of range (0-{len(committee_names)-1})")
        committee_names = [(committee_names[committee_index][0], committee_index)]

    failures = []

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
                ## keep going on failure so one run reports every broken channel,
                ##  then exit non-zero below so the workflow fails
                try:
                    ## save channel metadata to the fetcher & the DB
                    if fetcher.get_channel(handle) is None:
                        failures.append(f"{handle} ({committee_name}): channel not found")
                        continue
                    ## read the "uploaded" playlist from the previously fetched metadata
                    ##  and then store details about each video to the DB
                    fetcher.get_all_channel_videos(handle)
                    ## record each video's caption flag and duration
                    if not fetcher.update_video_details(handle):
                        failures.append(f"{handle} ({committee_name}): video details check failed")
                except Exception as ex:
                    # HttpError text/tracebacks can contain the authenticated
                    # request URL. Keep the failure type and status, not the key.
                    status = getattr(getattr(ex, "resp", None), "status", None)
                    reason = type(ex).__name__ + (f" (HTTP {status})" if status else "")
                    logging.error(f"Failed on {handle}: {reason}")
                    failures.append(f"{handle} ({committee_name}): {reason}")

    if failures:
        logging.error(
            f"{len(failures)} channel(s) failed:\n  " + "\n  ".join(failures)
        )
        sys.exit(1)


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
        help="Index of the committee in the CSV file",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
