from pathlib import Path
import re
import csv
from tinydb import TinyDB, Query
from tinydb.table import Table
import logging
from dataclasses import asdict, dataclass

import argparse
from ..tables import (
    get_all_commitee_names,
    open_tinydb_for_committee,
    get_committee_handles,
)

DEFAULT_OUTPUT_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "data"
    / "event_id_report.csv"
)

EVENT_ID_REGEX = ".*(\\d{6}|eventid).*"

@dataclass
class EventIdReport:
    committee_name: str
    handle: str
    total_videos: int
    missing_event_id: int


def main(output_path:Path=DEFAULT_OUTPUT_FILE) -> None:
    report: list[EventIdReport] = []
    committee_names = get_all_commitee_names(with_index=True)
    for committee in committee_names:
        try:
            db = open_tinydb_for_committee(committee[1])
            handles = get_committee_handles(committee[0])
            for handle in handles:
                if handle == "":
                    continue
                all_videos = db.table(f"youtube_videos_{handle}")
                video = Query()
                total_videos = len(all_videos)
                has_event_id_count = all_videos.count(
                    (video.description.matches(EVENT_ID_REGEX, flags=re.IGNORECASE))
                    | video.title.matches(EVENT_ID_REGEX, flags=re.IGNORECASE)
                )
                report.append(
                    EventIdReport(
                        committee[0],
                        handle,
                        total_videos,
                        total_videos - has_event_id_count,
                    )
                )
        except ValueError as e:
            logging.error(e)

    write_to_csv(report, output_path)


def write_to_csv(report: list[EventIdReport], output_path: Path):
    if len(report) == 0:
        return
    field_names = list(report[0].__annotations__.keys())
    with open(output_path, mode="w", newline='') as file:
        writer = csv.DictWriter(file, fieldnames=field_names)

        writer.writeheader()
        for row in report:
            writer.writerow(asdict(row))


def parse_args_and_run():
    parser = argparse.ArgumentParser(
        description="Generates report on committee videos with missing event ids"
    )

    ## ignore the unknown args
    args = parser.parse_known_args()[0]

    main(**vars(args))


if __name__ == "__main__":
    parse_args_and_run()

