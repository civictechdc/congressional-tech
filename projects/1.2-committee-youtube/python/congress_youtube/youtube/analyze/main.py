import argparse
import csv
import logging
import re

from dataclasses import asdict, dataclass
from pathlib import Path
from tinydb import Query

from ...globals import add_global_args, add_youtube_args, CONGRESS_METADATA


from ..tables import (
    get_all_commitee_names,
    get_all_committee_handless,
    open_tinydb_for_committee,
)
from ...globals import (
    DEFAULT_YOUTUBE_REPORT_FILE,
    DEFAULT_TINYDB_DIR,
    DEFAULT_CHANNELS_CSV,
)

EVENT_ID_REGEX = ".*(\\d{6}|eventid).*"


## define columns in row of final report
@dataclass
class EventIdReport:
    committee_name: str
    handle: str
    total_videos: int
    missing_event_id: int
    congress_number: int
    control: str
    chamber: str = "house"


def main(
    output_path: Path = DEFAULT_YOUTUBE_REPORT_FILE,
    tinydb_dir: Path = DEFAULT_TINYDB_DIR,
    channels_csv_path: Path = DEFAULT_CHANNELS_CSV,
) -> None:
    report: list[EventIdReport] = []
    ## load all the names & their indices
    committee_names = get_all_commitee_names(
        with_index=True, csv_path=channels_csv_path
    )
    ## load all the corresponding handles
    committee_handless = get_all_committee_handless(channels_csv_path)
    for committee_name in committee_names:
        try:
            db = open_tinydb_for_committee(
                committee_name_or_index=committee_name[1],
                csv_path=channels_csv_path,
                tinydb_dir=tinydb_dir,
                assert_exists=True,
            )
            handles = committee_handless[committee_name[1]]
            ## TODO: this needs to be automatically set by handle once we add senate handles
            ##  to the CSV
            chamber = "house"
            ## skip when we're in a row that has fewer handles than the max # (-> empty column)
            for handle in handles:
                if handle == "":
                    continue
                ## load the tinydb table
                all_videos = db.table(f"youtube_videos_{handle}")
                ## keep track of # of videos for validation at the end
                total_count = len(all_videos)
                running_count = 0
                ## loop through each congress to split metrics by congress #
                for congress_number, meta in CONGRESS_METADATA.items():
                    start_date = meta["start"]
                    end_date = meta["end"]

                    ## videos have:
                    ##  "publishedAt": "2025-07-23T23:26:16Z",

                    ## First filter videos by date range
                    video = Query()
                    videos_in_date_range = all_videos.search(
                        (video.publishedAt >= start_date)
                        & (video.publishedAt <= end_date)
                    )

                    ## metric #1: total number of videos
                    congress_count = len(videos_in_date_range)

                    ## keep track of count for validation
                    running_count += congress_count

                    ## apply the RE to filter videos & count
                    has_event_id_count = sum(
                        1
                        for video in videos_in_date_range
                        if re.search(
                            EVENT_ID_REGEX, video["description"], re.IGNORECASE
                        )
                        or re.search(EVENT_ID_REGEX, video["title"], re.IGNORECASE)
                    )

                    row = EventIdReport(
                        ## committee name, repeats for multiple handles
                        committee_name[0],
                        handle,  ## this handle
                        congress_count,  ## all videos in this congress #
                        congress_count - has_event_id_count,  ## bad videos
                        congress_number,
                        meta[chamber],  ## party in control of this chamber
                        chamber,
                    )
                    logging.info(f"Reporting {row}")
                    ## add the row
                    report.append(row)
                if total_count != running_count:
                    raise ValueError(
                        f"{total_count - running_count} videos are outside the applied date ranges and were excluded from reporting."
                    )
        except ValueError as e:
            logging.error(e)

    write_to_csv(report, output_path)


def write_to_csv(report: list[EventIdReport], output_path: Path):
    if len(report) == 0:
        return
    field_names = list(report[0].__annotations__.keys())
    with open(output_path, mode="w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=field_names)

        writer.writeheader()
        for row in report:
            writer.writerow(asdict(row))


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Generates report on committee videos with missing event ids"
    )

    ## add shared args to the parser
    add_global_args(parser)

    ## add youtube specific args
    add_youtube_args(parser)

    parser.add_argument(
        "--output-path",  ## dashes are automatically converted to underscores
        type=Path,
        default=DEFAULT_YOUTUBE_REPORT_FILE,
        help="Path to the output CSV file.",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
