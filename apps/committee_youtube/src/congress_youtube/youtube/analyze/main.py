import argparse
import csv
import datetime
import itertools
import logging
import multiprocessing
import re
import time

from dataclasses import asdict, dataclass
from pathlib import Path
from tinydb import Query, TinyDB

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


_TINYDB: TinyDB = None


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
    nthreads=None,
) -> None:
    init_time = time.time()
    final_reports = []

    if nthreads is None:
        nthreads = multiprocessing.cpu_count()

    ## load all the names & their indices
    committee_names = get_all_commitee_names(
        with_index=True, csv_path=channels_csv_path
    )

    ## load all the corresponding handles
    committee_handless = get_all_committee_handless(channels_csv_path)
    for committee_name in committee_names:
        try:
            ## define args required for opening the correct tinydb
            tinydb_args = dict(
                committee_name_or_index=committee_name[1],
                csv_path=channels_csv_path,
                tinydb_dir=tinydb_dir,
                assert_exists=True,
            )
            ## set the global _TINYDB for this process
            global _TINYDB
            _TINYDB = open_tinydb_for_committee(**tinydb_args)

            ## TODO: this needs to be automatically set by handle once we add senate handles
            ##  to the CSV
            chamber = "house"

            handles = committee_handless[committee_name[1]]
            for handle in handles:
                if handle == "":
                    ## skip when we're in a row that has fewer
                    ##  handles than the max # (-> empty column)
                    continue

                ## load the tinydb table
                all_videos = _TINYDB.table(f"youtube_videos_{handle}")

                ## keep track of # of videos for validation at the end
                total_count = len(all_videos)
                running_count = 0

                ## loop through each congress to split metrics by congress #
                ##  define the args for generating each row of the report
                argss = zip(
                    itertools.repeat(committee_name[0]),
                    itertools.repeat(handle),
                    CONGRESS_METADATA.keys(),
                    CONGRESS_METADATA.values(),
                    itertools.repeat(chamber),
                )

                if nthreads > 1:
                    ## in parallel...
                    ## have to open tinydb separately in each process
                    with multiprocessing.Pool(
                        nthreads, initializer=set_global_tinydb, initargs=[tinydb_args]
                    ) as pool:
                        reports = pool.starmap(
                            generate_report_for_congress_number, argss
                        )
                else:
                    ## in series...
                    ## can share the existing tinydb in single process
                    reports = [
                        generate_report_for_congress_number(*args) for args in argss
                    ]

                ## concatenate the rows
                running_count = sum([report.total_videos for report in reports])

                ## validate that we didn't accidentally exclude any videos
                if total_count != running_count:
                    raise ValueError(
                        f"{total_count - running_count} videos are outside"
                        " the applied date ranges and were excluded from reporting."
                    )
            final_reports.extend(reports)
        except ValueError as e:
            logging.error(e)

    write_to_csv(final_reports, output_path)
    logging.info(f"{time.time() - init_time} s elapsed")


def set_global_tinydb(tinydb_args: dict[str, any]):
    global _TINYDB
    _TINYDB = open_tinydb_for_committee(**tinydb_args)


def generate_report_for_congress_number(
    committee_name: str,
    handle: str,
    congress_number: int,
    meta: dict[str, any],
    chamber: str,
):
    start_date = meta["start"]
    end_date = meta["end"]
    if end_date == "present":
        end_date = datetime.date.today().isoformat()

    ## videos have:
    ##  "publishedAt": "2025-07-23T23:26:16Z",

    all_videos = _TINYDB.table(f"youtube_videos_{handle}")
    ## First filter videos by date range
    video = Query()
    videos_in_date_range = all_videos.search(
        (video.publishedAt >= start_date) & (video.publishedAt <= end_date)
    )

    ## metric #1: total number of videos
    congress_count = len(videos_in_date_range)

    ## apply the RE to filter videos & count
    has_event_id_count = sum(
        1
        for video in videos_in_date_range
        if re.search(EVENT_ID_REGEX, video["description"], re.IGNORECASE)
        or re.search(EVENT_ID_REGEX, video["title"], re.IGNORECASE)
    )

    row = EventIdReport(
        ## committee name, repeats for multiple handles
        committee_name,
        handle,  ## this handle
        congress_count,  ## all videos in this congress #
        congress_count - has_event_id_count,  ## bad videos
        congress_number,
        meta[chamber],  ## party in control of this chamber
        chamber,
    )
    logging.info(f"Reporting {row}")
    return row


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

    parser.add_argument(
        "--nthreads",
        type=lambda x: None if x.lower() == "none" else int(x),
        default=None,
        help="Number of threads to use (default: all available threads)."
        " Should be an integer or 'None'.",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
