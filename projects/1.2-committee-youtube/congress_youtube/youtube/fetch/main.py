import polars as pl
from pathlib import Path
from ...auth import load_youtube_api_key
from .youtube_event_fetcher import YoutubeEventFetcher


def main():
    committee, title = "Appropriations", "Budget Hearing – U.S. Department of Health and Human Services"

    api_key = load_youtube_api_key()
    fetcher = YoutubeEventFetcher(api_key)

    youtube_accounts = pl.read_csv(Path(__file__).parent.parent / "youtube-accounts.csv")

    appropriations_handle = youtube_accounts.filter(pl.col("Committee Name") == committee).row(0, named=True)["handle"]

    appropriations_channel = fetcher.get_channel(appropriations_handle)

    video = fetcher.get_event(
        title=title,
        channel_id=appropriations_channel["id"]
    )
    print(video)
    print(f"Recording URL: https://youtu.be/{video['id']['videoId']}")


if __name__ == "__main__":
    main()
