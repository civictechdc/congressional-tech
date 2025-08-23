import argparse
import csv
from pathlib import Path

from ...auth import load_youtube_api_key
from ...globals import add_global_args
from .youtube_event_fetcher import YoutubeEventFetcher


def get_committee_handles(committee_name_or_index: str | int, csv_path: Path) -> str:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        if isinstance(committee_name_or_index, str):
            for row in reader:
                if row["committee"].lower() == committee_name_or_index.lower():
                    return [value for value in list(row.values())[1:]]
            raise ValueError(
                f"No handle found for committee: {committee_name_or_index}"
            )
        elif isinstance(committee_name_or_index, int):
            rows = list(reader)
            if 0 <= committee_name_or_index < len(rows):
                return rows[committee_name_or_index].values()[1:]
            else:
                raise IndexError(
                    f"Index out of bounds for committee list {csv_path} (length {len(rows)})."
                )


def main(
    record_path: str, committee_name: str, committee_index: int, channels_csv: str
) -> None:
    api_key = load_youtube_api_key()
    fetcher = YoutubeEventFetcher(api_key, record_path)

    ## read the mapping from the committee name -> youtube handle (thanks Ezra!)
    handles = get_committee_handles(
        committee_name if not committee_index else committee_index, channels_csv
    )

    for handle in handles:
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

    parser.add_argument(
        "--csv_path",
        type=str,
        help="Path to the CSV file mapping committee names to their YouTube handles",
    )

    # Create a mutually exclusive group
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "-n",
        "--committee_name",
        type=str,
        help="Name of the committee to match against in the CSV file",
    )
    group.add_argument(
        "-i",
        "--committee_index",
        type=int,
        choices=range(13),
        help="Index of the committee in the CSV file",
    )

    args = parser.parse_known_args()

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
