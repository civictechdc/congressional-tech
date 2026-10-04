import argparse
import csv
import datetime
import itertools
import logging
import multiprocessing
import re
import sys
import time

from dataclasses import asdict, dataclass
from pathlib import Path
from tinydb import TinyDB
from youtube_api.interpretation import DATE_FIELDS, DateBasis, availability_facts, source_time

from congress_shared.globals import add_global_args, add_youtube_args, CONGRESS_METADATA

from youtube_api.tables import (
    get_all_commitee_names,
    get_all_committee_handless,
    map_system_code_committee_handles,
    open_tinydb_for_committee,
)
from congress_shared.globals import (
    DEFAULT_YOUTUBE_REPORT_FILE,
    DEFAULT_TINYDB_DIR,
    DEFAULT_CHANNELS_CSV,
)

EVENT_ID_REGEX = ".*(\\d{6}|eventid).*"

## system codes start with the chamber: hsag00 (house), jsec00 (joint), ssfr00 (senate)
CHAMBER_BY_CODE_PREFIX = {"h": "house", "j": "joint", "s": "senate"}


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
    ## videos with captions published (YouTube's contentDetails.caption flag)
    with_captions: int = 0


def main(
    output_path: Path = DEFAULT_YOUTUBE_REPORT_FILE,
    tinydb_dir: Path = DEFAULT_TINYDB_DIR,
    channels_csv_path: Path = DEFAULT_CHANNELS_CSV,
    nthreads=None,
    date_basis: DateBasis = "playlist_added",
) -> None:
    if date_basis not in DATE_FIELDS:
        raise ValueError(f"Unknown YouTube date basis: {date_basis}")
    init_time = time.time()
    final_reports = []
    ## problems are collected so the report still covers every committee it can,
    ##  then the run exits non-zero so the workflow fails visibly
    errors = []

    if nthreads is None:
        nthreads = multiprocessing.cpu_count()

    ## load all the names & their indices
    committee_names = get_all_commitee_names(
        csv_path=channels_csv_path
    )

    ## load all the corresponding handles and system codes
    committee_handless = get_all_committee_handless(channels_csv_path)
    committee_codes = list(map_system_code_committee_handles(channels_csv_path))
    for committee_index, committee_name in enumerate(committee_names):
        try:
            ## define args required for opening the correct tinydb
            tinydb_args = dict(
                committee_name_or_index=committee_index,
                csv_path=channels_csv_path,
                tinydb_dir=tinydb_dir,
                assert_exists=True,
            )
            ## set the global _TINYDB for this process
            global _TINYDB
            _TINYDB = open_tinydb_for_committee(**tinydb_args)

            chamber = CHAMBER_BY_CODE_PREFIX[committee_codes[committee_index][0]]

            handles = committee_handless[committee_index]
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
                    itertools.repeat(committee_name),
                    itertools.repeat(handle),
                    CONGRESS_METADATA.keys(),
                    CONGRESS_METADATA.values(),
                    itertools.repeat(chamber),
                    itertools.repeat(date_basis),
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
                    errors.append(
                        f"{handle} ({committee_name}): {total_count - running_count} videos"
                        f" lack a usable {date_basis} date or fall outside the congress date ranges and were excluded from reporting."
                    )
                ## add this handle's rows (committees can have several handles)
                final_reports.extend(reports)
        except ValueError as e:
            errors.append(f"{committee_name}: {e}")

    write_to_csv(final_reports, output_path)
    if errors:
        logging.error(f"{len(errors)} problem(s):\n  " + "\n  ".join(errors))
        sys.exit(1)
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
    date_basis: DateBasis = "playlist_added",
):
    if date_basis not in DATE_FIELDS:
        raise ValueError(f"Unknown YouTube date basis: {date_basis}")
    start_date = datetime.date.fromisoformat(meta["start"])
    end_date = (None if meta["end"] == "present"
                else datetime.date.fromisoformat(meta["end"]))
    all_videos = _TINYDB.table(f"youtube_videos_{handle}")
    # Keep the historical playlist-added default explicit. Publication reports
    # do not fall back to that field when videoPublishedAt is missing.
    videos_in_date_range = [
        row for row in all_videos
        if (instant := source_time(row, basis=date_basis).instant) is not None
        and start_date <= instant.date()
        and (end_date is None or instant.date() < end_date)
    ]

    ## metric #1: total number of videos
    congress_count = len(videos_in_date_range)

    ## apply the RE to filter videos & count
    has_event_id_count = sum(
        1
        for video in videos_in_date_range
        if re.search(EVENT_ID_REGEX, video["description"], re.IGNORECASE)
        or re.search(EVENT_ID_REGEX, video["title"], re.IGNORECASE)
    )

    ## metric #3: videos with captions published
    evaluated_at = datetime.datetime.now(datetime.timezone.utc)
    with_captions_count = sum(
        1 for video in videos_in_date_range
        if availability_facts(video, evaluated_at=evaluated_at).captions.status == "available"
    )

    row = EventIdReport(
        ## committee name, repeats for multiple handles
        committee_name,
        handle,  ## this handle
        congress_count,  ## all videos in this congress #
        congress_count - has_event_id_count,  ## bad videos
        congress_number,
        meta.get(chamber, ""),  ## party in control of this chamber (none for joint)
        chamber,
        with_captions_count,
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

    parser.add_argument(
        "--date-basis", choices=tuple(DATE_FIELDS), default="playlist_added",
        help="Date used for congress ranges: playlist_added (historical default) or "
             "video_publication (requires videoPublishedAt; no playlist fallback).",
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()
