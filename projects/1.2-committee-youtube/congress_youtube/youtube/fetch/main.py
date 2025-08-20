from pathlib import Path
import csv
from ...auth import load_youtube_api_key
from .youtube_event_fetcher import YoutubeEventFetcher


def get_committee_handle(committee: str, csv_path: Path) -> str:
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row["committee"] == committee:
                return row["handle"]
    raise ValueError(f"No handle found for committee: {committee}")


def main():
    ## TODO: this is hard-coding a single committee name and title in
    ##  to see if we can find it.
    test_committee, test_title = (
        "Appropriations",
        "Budget Hearing - U.S. Department of Health and Human Services",
    )

    api_key = load_youtube_api_key()
    fetcher = YoutubeEventFetcher(api_key)

    test_handle = get_committee_handle(
        test_committee, Path(__file__).parent.parent / "youtube-accounts.csv"
    )
    test_channel = fetcher.get_channel(test_handle)

    video = fetcher.get_event(title=test_title, channel_id=test_channel["id"])

    print(video)
    print(f"Recording URL: https://youtu.be/{video['id']['videoId']}")


if __name__ == "__main__":
    main()
